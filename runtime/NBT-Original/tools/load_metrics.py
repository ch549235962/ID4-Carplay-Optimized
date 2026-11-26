"""Cached local process metrics, plus explicitly identified QNX guest samples."""
import collections,json,re,subprocess,threading,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
class LoadMetrics:
 def __init__(self):
  self.lock=threading.Lock();self.value={'ready':False};self.stop=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def snapshot(self):
  with self.lock:return dict(self.value)
 def collect(self,previous):
  result={'ready':True,'sampled_at':time.time(),'processes':[],'cpu_basis':'macOS ps %cpu; 100% equals one host core','real_car_equivalent':False,'guest':None}
  processes={}
  for name,p in [('QEMU',R/'vm/pid'),('图形渲染器',R/'vm/renderer.pid'),('网页服务',R/'vm/viewer.pid')]:
   try:pid=int(p.read_text());processes[pid]=name
   except (OSError,ValueError):continue
  if processes:
   p=subprocess.run(['ps','-p',','.join(map(str,processes)),'-o','pid=,pcpu=,rss=,etime=,comm='],capture_output=True,text=True,timeout=3)
   for line in p.stdout.splitlines():
    parts=line.split(None,4)
    if len(parts)!=5:continue
    pid=int(parts[0]);name=processes.get(pid);command=parts[4]
    valid={'QEMU':'qemu-system-i386','图形渲染器':'nbt-glhost-macos','网页服务':'python'}
    if name and valid[name] in command.lower():result['processes'].append({'name':name,'pid':pid,'cpu_pct':float(parts[1]),'rss_mib':round(int(parts[2])/1024,1),'elapsed':parts[3]})
  try:
   command=json.loads((R/'vm/command-active.json').read_text());result['configuration']={'ram_mib':int(command[command.index('-m')+1].removesuffix('M')),'vcpus':int(command[command.index('-smp')+1]),'cpu_model':command[command.index('-cpu')+1],'acceleration':command[command.index('-accel')+1],'frequency_matched_to_atom':False}
   result['configuration']['clock_mode']='icount' if '-icount' in command else 'realtime'
  except (OSError,ValueError,KeyError):result['configuration']=None
  try:
   with (R/'logs/serial.log').open('rb') as f:f.seek(0,2);size=f.tell();f.seek(max(0,size-131072));tail=f.read().decode(errors='replace')
   for match in reversed(list(re.finditer(r'NBT_METRICS (\{[^\r\n]*\})',tail))):
    try:guest=json.loads(match.group(1))
    except ValueError:continue
    old=previous.get('guest') or {};same=guest.get('sample')==old.get('sample') and guest.get('guest_ns')==old.get('guest_ns');guest['received_at']=old['received_at'] if same else time.time();guest['age_seconds']=round(time.time()-guest['received_at'],1);result['guest']=guest;break
  except OSError:pass
  try:result['renderer']=json.loads((R/'vm/renderer-metrics.json').read_text())
  except (OSError,ValueError):result['renderer']=None
  return result
 def run(self):
  frame_history=collections.deque(maxlen=4);guest_history=collections.deque(maxlen=20)
  while not self.stop.is_set():
   try:
    current=self.collect(self.value);now=time.monotonic();render=current.get('renderer');frames=render['frames'] if render else 0
    if frame_history and frames<frame_history[-1][1]:frame_history.clear()
    frame_history.append((now,frames));current['render_fps']=round((frames-frame_history[0][1])/(now-frame_history[0][0]),1) if render and len(frame_history)>1 else None
    guest=current.get('guest');current['guest_time_ratio']=None
    if guest:
     if guest_history and guest['guest_ns']<guest_history[-1][1]:guest_history.clear()
     guest_history.append((now,guest['guest_ns']))
     if len(guest_history)>2:current['guest_time_ratio']=round((guest['guest_ns']-guest_history[0][1])/1e9/(now-guest_history[0][0]),3)
    with self.lock:self.value=current
   except (OSError,ValueError,subprocess.SubprocessError) as e:
    with self.lock:self.value={**self.value,'error':str(e)}
   self.stop.wait(1)
