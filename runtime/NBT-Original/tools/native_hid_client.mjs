// A persistent SSH transport to the QNX encoder. No host-side HID encoding.
import {spawn} from 'node:child_process';
import path from 'node:path';
export class NativeHidClient {
 constructor(root,width,height,changed=()=>{}){
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<2||height<2||width>65535||height>65535)throw Error('Invalid HID display dimensions');
  this.root=root;this.width=width;this.height=height;this.changed=changed;
  this.ready=false;this.closed=false;this.pending=new Map();this.sequence=0;this.error=null;this.pid=null;
 }
 start(){
  if(this.closed||this.child)return;
  let buffer='';
  const child=spawn('/usr/bin/ssh',['-F',path.join(this.root,'build/nbt_ssh_config'),'-oBatchMode=yes','-oConnectTimeout=4',
   '-oServerAliveInterval=3','-oServerAliveCountMax=2','nbt-native',
   `export LD_LIBRARY_PATH=/boot/lib; exec ${process.env.NBT_QNX_BUILTIN_TOOLS==='1'?'/boot/native/native_hid':'/var/tmp/nbt-native/native_hid'} ${this.width} ${this.height}`],{stdio:['pipe','pipe','pipe']});
  this.child=child;
  child.stdin.on('error',()=>{});child.stderr.on('data',()=>{});
  child.stdout.on('data',chunk=>{
   buffer+=chunk.toString();if(buffer.length>65536){this.fail('QNX HID 响应过长');child.kill();return;}
   let at;while((at=buffer.indexOf('\n'))!==-1){
    const line=buffer.slice(0,at);buffer=buffer.slice(at+1);
    let m;try{m=JSON.parse(line);}catch{this.fail('QNX HID 响应格式错误');child.kill();return;}
    if(m.type==='ready'){
     if(m.platform!=='QNX'||m.width!==this.width||m.height!==this.height){this.fail('QNX HID 编码器版本不匹配');child.kill();return;}
     this.ready=true;this.error=null;this.pid=m.pid;this.changed();continue;
    }
    const request=this.pending.get(m.seq);if(!request)continue;
    this.pending.delete(m.seq);clearTimeout(request.timer);
    if(m.ok===true&&Array.isArray(m.reports)&&m.reports.length>0&&m.reports.length<=4&&m.reports.every(r=>
      Number.isInteger(r.uid)&&[0x2a2a2a2a,0x2a2a2a2b].includes(r.uid)&&typeof r.hex==='string'&&/^(?:[0-9a-f]{8}|[0-9a-f]{24})$/.test(r.hex)))request.resolve(m.reports);
    else request.reject(Error('QNX 拒绝了无效的控制指令'));
   }
  });
  const startup=setTimeout(()=>{if(!this.ready){this.fail('等待 QNX HID 编码器超时');child.kill();}},12000);
  child.on('error',()=>{this.fail('无法启动 QNX HID 通道');});
  child.on('close',()=>{
   clearTimeout(startup);if(this.child!==child)return;
   this.child=null;this.fail(this.closed?'QNX HID 通道已停止':'QNX HID 通道未就绪');
   if(!this.closed)this.retry=setTimeout(()=>this.start(),2000);
  });
 }
 fail(message){
  this.ready=false;this.pid=null;this.error=message;
  for(const request of this.pending.values()){clearTimeout(request.timer);request.reject(Error(message));}
  this.pending.clear();this.changed();
 }
 request(kind,args=[]){
  if(!this.ready||!this.child||this.closed)return Promise.reject(Error('QNX HID 编码器尚未就绪'));
  if(this.pending.size>=32)return Promise.reject(Error('控制指令过多，请稍候'));
  const seq=++this.sequence;
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{this.pending.delete(seq);reject(Error('QNX 控制指令超时'));this.child?.kill();},8000);
   this.pending.set(seq,{resolve,reject,timer});
   this.child.stdin.write([kind,seq,...args].join(' ')+'\n');
  });
 }
 action(action,steps){
  if(!['up','down','rotate','tilt_left','tilt_right','tilt_up','tilt_down','select','back','menu'].includes(action))throw Error('不支持的操作');
  if(action==='rotate'&&(!Number.isInteger(steps)||steps===0||Math.abs(steps)>16))throw Error('旋转步数无效');
  return this.request('A',[action,action==='rotate'?steps:0]);
 }
 touch(contacts){
  if(!Array.isArray(contacts)||contacts.length>2)throw Error('触控数据无效');
  const seen=new Set();const fields=[];
  for(const c of contacts){
   if(!Number.isInteger(c.id)||c.id<0||c.id>1||seen.has(c.id)||!Number.isFinite(c.x)||!Number.isFinite(c.y)||typeof c.down!=='boolean')throw Error('触控坐标无效');
   seen.add(c.id);fields.push(c.id,c.x,c.y,c.down?1:0);
  }
  return this.request('T',[contacts.length,...fields]);
 }
 release(){return this.request('R');}
 close(){this.closed=true;clearTimeout(this.retry);this.child?.stdin.end();this.child?.kill('SIGTERM');this.fail('QNX HID 通道已停止');}
}
