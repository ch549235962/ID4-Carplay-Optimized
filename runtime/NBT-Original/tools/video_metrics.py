#!/opt/homebrew/bin/python3.13
"""Publish native QNX video counters for the existing live metrics endpoint.

One persistent SSH connection reads counters only; neither phone session nor
guest rendering is restarted. Rates use host monotonic time, not guest time.
"""
import collections,datetime,json,os,signal,subprocess,sys,threading,time,urllib.request
from pathlib import Path
R=Path(__file__).resolve().parents[1]
NATIVE=R.parent/'CarPlay-QNX-Native'
sys.path.insert(0,str(NATIVE/'tools'))
from nbt_guest import ssh_args
STOP=threading.Event()

def rate(history,index):
    if len(history)<2:return None
    first,last=history[0],history[-1]
    elapsed=last[0]-first[0]
    return round((last[index]-first[index])/elapsed,1) if elapsed>0 else None

class Collector:
    def __init__(self):
        self.lock=threading.Lock();self.guest={};self.guest_at=None;self.child=None
        self.guest_history=collections.deque(maxlen=4)
        self.input_history=collections.deque(maxlen=5)
        self.input_pid=None;self.input_updated=None
        self.frame_base=None
        self.phone_active=None;self.last_receiver_check=0

    def read_guest(self):
        command='export LD_LIBRARY_PATH=/boot/lib; while /boot/native/native_video_ctl; do /boot/bin/sleep 1; done'
        while not STOP.is_set():
            try:
                child=subprocess.Popen(ssh_args()+[command],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,text=True)
                with self.lock:self.child=child
                for line in child.stdout:
                    if STOP.is_set():break
                    try:sample=json.loads(line)
                    except ValueError:continue
                    now=time.monotonic()
                    with self.lock:
                        self.guest=sample;self.guest_at=now
                        if sample.get('ready'):
                            point=(now,sample['decoded'],sample['rendered'])
                            if self.guest_history and (point[1]<self.guest_history[-1][1] or point[2]<self.guest_history[-1][2]):
                                self.guest_history.clear();self.frame_base=None
                            if self.frame_base is None:self.frame_base=sample['rendered']
                            self.guest_history.append(point)
                        else:self.guest_history.clear()
                child.stdout.close()
                if child.poll() is None:child.terminate()
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            except OSError:pass
            STOP.wait(2)

    def snapshot(self):
        now=time.monotonic()
        try:
            stream=json.loads((NATIVE/'logs/live-qnx-video.json').read_text())
            stream_age=max(0,time.time()-datetime.datetime.fromisoformat(stream['updated_at'].replace('Z','+00:00')).timestamp())
            fresh=stream_age<5
            identity=stream.get('decoder_ssh_pid')
            if identity!=self.input_pid:
                self.input_history.clear();self.input_pid=identity;self.input_updated=None
            if fresh and identity and stream.get('updated_at')!=self.input_updated:
                count=int(stream['frames'])
                if self.input_history and count<self.input_history[-1][1]:self.input_history.clear()
                self.input_history.append((now,count));self.input_updated=stream['updated_at']
        except (OSError,ValueError,KeyError):stream={};fresh=False
        if now-self.last_receiver_check>=2:
            self.last_receiver_check=now
            try:
                with urllib.request.urlopen('http://127.0.0.1:8878/api/status',timeout=.8) as response:
                    self.phone_active=bool(json.load(response).get('sessionActive'))
            except (OSError,ValueError):self.phone_active=None
        with self.lock:
            guest=dict(self.guest)
            age=now-self.guest_at if self.guest_at is not None else None
            valid=guest.get('ready',False) and age is not None and age<10
            decoded=rate(self.guest_history,1) if valid else None
            displayed=rate(self.guest_history,2) if valid else None
            frames=max(0,guest.get('rendered',0)-(self.frame_base or 0))
        received=rate(self.input_history,1) if fresh and self.input_pid else None
        return {'source':'qnx_native_video','sampled_at':time.time(),'ready':valid,
            'frames':frames,'presented_frames':guest.get('rendered',0),'decoded_frames':guest.get('decoded',0),
            'received_frames':stream.get('frames',0),
            'fps':{'received':received,'decoded':decoded,'displayed':displayed},
            'guest_sample_age_seconds':round(age,1) if age is not None else None,
            'decode_errors':guest.get('errors'),'display_errors':guest.get('render_errors'),
            'dropped_frames':stream.get('dropped'),'phone_session_active':self.phone_active,
            'visible':bool(guest.get('visible')),
            'frames_basis':'Native QNX overlay presentations, including repeated frames',
            'rate_time_basis':'Host monotonic wall time'}

    def close(self):
        STOP.set()
        with self.lock:child=self.child
        if child and child.poll() is None:child.terminate()

def main():
    qemu_pid=int((R/'vm/pid').read_text())
    collector=Collector()
    for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,lambda *_:collector.close())
    worker=threading.Thread(target=collector.read_guest,daemon=True);worker.start()
    path=R/'vm/renderer-metrics.json';temporary=path.with_suffix('.tmp-'+str(os.getpid()))
    try:
        while not STOP.is_set():
            try:
                if int((R/'vm/pid').read_text())!=qemu_pid:break
                os.kill(qemu_pid,0)
            except (OSError,ValueError):break
            temporary.write_text(json.dumps(collector.snapshot()));temporary.replace(path)
            STOP.wait(1)
    finally:
        collector.close();worker.join(timeout=4);temporary.unlink(missing_ok=True)
        try:
            prior=json.loads(path.read_text())
            if prior.get('source')=='qnx_native_video':path.unlink()
        except (OSError,ValueError):pass

if __name__=='__main__':main()
