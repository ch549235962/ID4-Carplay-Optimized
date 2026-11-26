#!/opt/homebrew/bin/python3.13
"""Recover this receiver after an exit; never start a VM or reset Bluetooth."""
import collections,fcntl,json,os,signal,time
from pathlib import Path
import macplay_nbt as manager
ROOT=Path(__file__).resolve().parents[1]
STOP=False

def note(**value):
    path=ROOT/'supervisor-state.json';tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'sampled_at':time.time(),**value},ensure_ascii=False));tmp.chmod(0o600);tmp.replace(path)
def intent():
    try:return json.loads(manager.INTENT.read_text()).get('enabled') is True
    except (OSError,ValueError):return False
def stop(*_):
    global STOP
    STOP=True

def main():
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    attempts=collections.deque();missing=0;recovered=0;next_attempt=0
    while not STOP and intent():
        if manager.nbt_vm.status().get('qemu')!='running':
            note(state='vm-stopped',recoveries=recovered);break
        if manager.running():
            missing=0;note(state='watching',recoveries=recovered)
        else:
            missing+=1;now=time.monotonic()
            while attempts and now-attempts[0]>300:attempts.popleft()
            if missing>=2 and now>=next_attempt:
                if len(attempts)>=3:
                    note(state='retry-backoff',recoveries=recovered);next_attempt=now+60
                else:
                    with (ROOT.parent/'NBT-Launcher/operation.lock').open('a') as lock:
                        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        except BlockingIOError:pass
                        else:
                            if intent() and not STOP and not manager.running():
                                attempts.append(now)
                                try:
                                    manager.start(supervise=False);recovered+=1;missing=0
                                    note(state='recovered',recoveries=recovered)
                                except Exception as error:
                                    note(state='retry-failed',error_type=type(error).__name__,recoveries=recovered)
                                    next_attempt=now+10
        for _ in range(20):
            if STOP:break
            time.sleep(.1)
    if STOP:note(state='stopped',recoveries=recovered)

if __name__=='__main__':
    os.umask(0o077)
    main()
