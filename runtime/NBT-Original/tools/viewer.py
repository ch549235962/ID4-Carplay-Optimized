#!/usr/bin/env python3
"""Loopback-only web display and original NBT controller session."""
import http.server,json,threading,sys,time,subprocess
from load_metrics import LoadMetrics
import video_profile
from pathlib import Path
R=Path(__file__).resolve().parents[1]
SOURCE=R.parent/'NBT-Dev/src/BMW-NBT-Emulator'
sys.path.insert(0,str(SOURCE/'work/graphics-port/native-controls'))
from session import NativeInputSession,KEYBOARD_KEYS
stop=threading.Event()
metrics=LoadMetrics()
(R/'logs/relay').mkdir(exist_ok=True)
for link,target in [(R/'logs/serial_com1.log','serial.log'),(R/'logs/relay/renderer-stderr.log','../renderer.log')]:
 if not link.exists():link.symlink_to(target)
session=NativeInputSession({'run_directory':str(R/'logs'),'input_port':27872,'input_kind':'virtio','keyboard_hal':True},stop,button_hold_seconds=.020,button_release_gap_seconds=0)
session.start()
HTML='''<!doctype html><meta charset="utf-8"><title>BMW NBT 本地虚拟机</title><style>body{margin:0;background:#101114;color:#ddd;font:16px system-ui;text-align:center}main{max-width:1300px;margin:32px auto}canvas{width:100%;background:#000;aspect-ratio:8/3}button{padding:12px 18px;margin:5px;background:#252b36;color:white;border:1px solid #586274;border-radius:8px;cursor:pointer}#status{padding:12px}</style><main><h2>BMW NBT · 本地虚拟机</h2><canvas id="c" width="1280" height="480"></canvas><div id="status">原厂 QNX 正在启动…</div><div id="keys"></div><p>方向键旋转 · Enter 确认 · Esc 返回 · M 主菜单 · F2/F3/F4/F5 电台/媒体/导航/电话</p></main><script>
const c=document.querySelector('#c'),ctx=c.getContext('2d'),status=document.querySelector('#status');
async function action(a){await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:a})})}
for(const [n,a] of [['↑','up'],['↓','down'],['确认','select'],['返回','back'],['主菜单','menu'],['OPTION','option'],['电台','radio'],['媒体','media'],['导航','nav'],['电话','tel']]){let b=document.createElement('button');b.textContent=n;b.onclick=()=>action(a);document.querySelector('#keys').append(b)}
document.onkeydown=e=>{if(['SELECT','INPUT','BUTTON'].includes(e.target.tagName))return;let a={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'tilt_left',ArrowRight:'tilt_right',Enter:'select',Escape:'back',Backspace:'back',m:'menu',M:'menu',F1:'menu',F2:'radio',F3:'media',F4:'nav',F5:'tel'}[e.key];if(a){e.preventDefault();action(a)}};
let tag='',image=null;
async function poll(){
 const began=performance.now();
 try{
  const r=await fetch('/frame',{headers:{'If-None-Match':tag},cache:'no-cache'});
  if(r.ok&&r.status!==304){
   const nextTag=r.headers.get('ETag'),b=new Uint8Array(await r.arrayBuffer());let p=0,lines=[];
   while(lines.length<3&&p<100){let q=p;while(p<b.length&&b[p]!==10)p++;lines.push(new TextDecoder().decode(b.subarray(q,p++)))}
   const [w,h]=(lines[1]||'').split(' ').map(Number);
   if(w>0&&h>0&&w*h*3===b.length-p){
    if(!image||image.width!==w||image.height!==h){c.width=w;c.height=h;image=ctx.createImageData(w,h)}
    for(let i=0,j=p;i<image.data.length;i+=4,j+=3){image.data[i]=b[j];image.data[i+1]=b[j+1];image.data[i+2]=b[j+2];image.data[i+3]=255}
    ctx.putImageData(image,0,0);tag=nextTag;
   }
  }
 }catch{}
 setTimeout(poll,Math.max(1,__FRAME_INTERVAL__-(performance.now()-began)));
}
async function pollStatus(){
 try{const s=await(await fetch('/status',{cache:'no-store'})).json();status.textContent=s.controller_ready?'已启动 · iDrive 按键已连接':s.frame_ready?'界面已启动 · 等待 iDrive 按键初始化':'原厂 QNX 正在启动…'}
 catch{status.textContent='等待本地虚拟机连接…'}
 setTimeout(pollStatus,1000);
}
poll();pollStatus();</script>'''
HTML=HTML.replace('__FRAME_INTERVAL__',str(1000/video_profile.config()['target_fps'])).replace('</main><script>','__MONITOR_PANEL__</main><script>')
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def respond(self,code,data=b'',kind='application/json',etag=None):
  self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-cache')
  if etag:self.send_header('ETag',etag)
  self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if self.path=='/':return self.respond(200,HTML.replace('__MONITOR_PANEL__',(R/'tools/monitor/panel.html').read_text()).encode(),'text/html; charset=utf-8')
  if self.path=='/metrics':return self.respond(200,json.dumps(metrics.snapshot(),ensure_ascii=False).encode())
  if self.path=='/status':return self.respond(200,json.dumps({'controller_ready':session.ready,'frame_ready':(R/'vm/frame.ppm').exists()}).encode())
  if self.path=='/frame':
   try:
    with (R/'vm/frame.ppm').open('rb') as f:
     st=__import__('os').fstat(f.fileno());tag='"'+str(st.st_mtime_ns)+'"'
     if self.headers.get('If-None-Match')==tag:return self.respond(304,etag=tag)
     return self.respond(200,f.read(),'application/octet-stream',tag)
   except FileNotFoundError:return self.respond(503,b'{}')
  self.respond(404,b'{}')
 def do_POST(self):
  if self.headers.get('Origin') not in (None,'http://127.0.0.1:8876'):return self.respond(403,b'{}')
  if self.path!='/action':return self.respond(404,b'{}')
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n>128:raise ValueError()
   action=json.loads(self.rfile.read(n))['action']
   if action not in KEYBOARD_KEYS:raise ValueError()
   session.action(action);self.respond(200,b'{"queued":true}')
  except (ValueError,KeyError):self.respond(400,b'{}')
try:http.server.ThreadingHTTPServer(('127.0.0.1',8876),Handler).serve_forever()
finally:stop.set();metrics.stop.set();session.join()
