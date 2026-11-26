// MacPlay USB/AirPlay transport -> compressed H.264 -> native QNX decode/display.
// HID bytes are generated in QNX; audio and protocol encryption remain on Mac.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {spawn}=require('node:child_process');
const {pathToFileURL}=require('node:url');
const avc=require('./avc.cjs');
const ROOT=path.resolve(__dirname,'..'),BASE=path.dirname(ROOT);
const NATIVE=path.join(BASE,'CarPlay-QNX-Native'),NBT=path.join(BASE,'NBT-Original');
const METRICS=path.join(NATIVE,'logs/live-qnx-video.json');
const profile=JSON.parse(fs.readFileSync(process.env.MACPLAY_SETTINGS_PATH,'utf8'));
const connection=profile.wireless?'wireless':'USB';
const ssh=['-F',path.join(NATIVE,'build/nbt_ssh_config'),'-oBatchMode=yes','-oConnectTimeout=5','nbt-native'];
const origins=new Set(['http://127.0.0.1:8876','http://localhost:8876']);
let stack=null,session=false,phoneName=null,hid=null,decoder=null,decoderReady=false;
let config=null,codec=null,started=false,ending=false,firstDecoded=false,decoderAt=0;
let frames=0,receivedFrames=0,bytes=0,keyframes=0,dropped=0,lastError=null,mode='carplay',modeChosen=false;
let sent=0,reportsSent=0,lastAction=null,lastGuestMs=null,inputQueue=Promise.resolve(),queueDepth=0;
let onDecoded,requestKey,guest={},peerAddress=null;
let lastNalTypes=[],lastWasKeyframe=false,dropNotReady=0,dropWaitingKey=0;
let nextDecoderAt=0,decoderFailures=0,recoveries=0,lastKeyRequest=0,lastVideoAt=0,lastForwardAt=0;
let decodedProgress=0,decodedProgressAt=Date.now(),recoveryWindow=[];
let stockReady=process.env.NBT_QNX_DEFER_VIDEO_UNTIL_HMI!=='1',stockProbe=false;
function probeStockReady(){
 if(stockReady||stockProbe||ending)return;stockProbe=true;
 const request=http.get('http://127.0.0.1:8876/status',response=>{
  let body='';response.on('data',chunk=>{body+=chunk;if(body.length>8192)request.destroy();});
  response.on('end',()=>{stockProbe=false;try{if(JSON.parse(body).controller_ready){stockReady=true;ensureDecoder();requestKeyframe();}}catch{}});
 });
 request.setTimeout(1000,()=>request.destroy());request.on('error',()=>{stockProbe=false;});
}
function requestKeyframe(){const now=Date.now();if(now-lastKeyRequest<1000)return;lastKeyRequest=now;requestKey?.();}
function atomicJSON(file,value){const temporary=file+'.tmp-'+process.pid;fs.writeFileSync(temporary,JSON.stringify(value,null,2),{mode:0o600});fs.renameSync(temporary,file);}
function readGuest(){
 try{
  const m=JSON.parse(fs.readFileSync(path.join(NBT,'vm/renderer-metrics.json'),'utf8'));
  guest=m.ready&&Date.now()/1000-m.sampled_at<5&&m.guest_sample_age_seconds<3&&m.sampled_at>decoderAt+1?m:{};
 }catch{guest={};}
 return guest;
}
function controlReady(){const s=stack?._active;return !!(session&&stack?.hasVerifiedSession&&s?.eventCipher&&s?.eventSock&&!s.eventSock.destroyed&&s.eventSock.writable&&hid?.ready);}
function state(){
 const g=readGuest();return {running:!ending,ready:controlReady(),session_active:session,mode,
  messages_sent:sent,reports_sent:reportsSent,last_action:lastAction,last_error:lastError,
  protocol_location:'MacPlay on Mac',hid_encoding_location:'QNX',native_hid_ready:hid?.ready===true,
  native_hid_pid:hid?.pid??null,native_hid_error:hid?.error??null,last_guest_roundtrip_ms:lastGuestMs,
  video_decode_location:'QNX',video_display_location:'QNX HmiMain3D',codec,received_frames:receivedFrames,forwarded_frames:frames,
  decoded_frames:g.decoded_frames??0,displayed_frames:g.presented_frames??0,pid:process.pid,
  connection,peer_address:peerAddress,decoder_transport_ready:decoderReady,decoder_stdin_writable:decoder?.stdin.writable??false,
  last_nal_types:lastNalTypes,last_was_keyframe:lastWasKeyframe,drop_not_ready:dropNotReady,drop_waiting_key:dropWaitingKey,
  decoder_recoveries:recoveries,decoder_retry_pending:!decoder&&nextDecoderAt>Date.now(),waiting_for_hmi:!stockReady};
}
function receiverState(){return {deviceName:'MacPlay · NBT',sessionActive:session,phone:phoneName,
 backend:'MacPlay '+connection+' -> QNX',nativeHidInput:true,nativeProtocolMigrated:false,
 display:{width:1280,height:480,fps:profile.fps},video:state()};}
function save(){
 const report={mode:'MacPlay '+connection+' protocol -> compressed H.264 -> QNX decoder -> QNX HMI GLES',
  native_protocol_migrated:false,backend:'macplay-'+connection.toLowerCase(),pid:process.pid,decoder_ssh_pid:decoder?.pid??null,
  frames:receivedFrames,forwarded_frames:frames,bytes,keyframes,dropped,lastError,codec,updated_at:new Date().toISOString()};
 report.decoder_recoveries=recoveries;report.decoder_retry_at=nextDecoderAt;
 atomicJSON(METRICS,report);
 atomicJSON(path.join(ROOT,'state.json'),receiverState());
}
function ensureDecoder(){
 if(ending||decoder||!stockReady||Date.now()<nextDecoderAt)return;
 decoderAt=Date.now()/1000;guest={};
 const binary=process.env.NBT_QNX_BUILTIN_TOOLS==='1'?'/boot/native/native_decoder':'/var/tmp/nbt-native/native_decoder';
 const command='export PATH=/boot/bin; export LD_LIBRARY_PATH=/boot/lib; /boot/native/native_video_ctl '+(mode==='carplay'?'show':'hide')+'; exec '+binary+' -';
 const child=spawn('/usr/bin/ssh',[...ssh.slice(0,-1),'-oServerAliveInterval=3','-oServerAliveCountMax=2',ssh.at(-1),command],{stdio:['pipe','ignore','pipe']});decoder=child;
 let stderrBuffer='';
 child.stdin.on('error',()=>{});
 child.stderr.on('data',chunk=>{
  stderrBuffer=(stderrBuffer+chunk.toString()).slice(-8192);
  if(!decoderReady&&stderrBuffer.includes('QNX_NATIVE_DECODER_READY')){
   decoderReady=true;decoderFailures=0;decodedProgress=0;decodedProgressAt=Date.now();console.log('NBT_QNX_DECODER_TRANSPORT_READY');requestKeyframe();
  }
  process.stderr.write(chunk);
 });
 child.on('error',()=>{lastError='Cannot start QNX video transport';save();});
 child.on('close',code=>{if(decoder!==child)return;decoder=null;decoderReady=false;started=false;
  if(!ending){decoderFailures++;nextDecoderAt=Date.now()+Math.min(8000,500*2**Math.min(decoderFailures,4));lastError='QNX decoder disconnected ('+code+'); retry scheduled';save();requestKeyframe();}});
}
function checkDecoder(){
 if(ending||!config||!session)return;
 if(!stockReady){probeStockReady();return;}
 const now=Date.now();
 if(!decoder){ensureDecoder();return;}
 if(!decoderReady&&now-decoderAt*1000>15000){decoder.kill('SIGTERM');return;}
 const g=readGuest();if(!g.ready)return;
 if(g.decoded_frames!==decodedProgress){decodedProgress=g.decoded_frames;decodedProgressAt=now;return;}
 // A static phone screen does not prove a stalled decoder. Recover only while
 // compressed frames continue to arrive and be forwarded into this decoder.
 if(decoderReady&&lastVideoAt>now-3000&&lastForwardAt>now-3000&&now-decodedProgressAt>12000){
  recoveryWindow=recoveryWindow.filter(at=>now-at<60000);
  if(recoveryWindow.length>=3){nextDecoderAt=now+30000;lastError='QNX decoder recovery paused after repeated failures';return;}
  recoveryWindow.push(now);recoveries++;lastError='QNX video stalled; restarting decoder only';
  decoder.kill('SIGTERM');decodedProgressAt=now;requestKeyframe();save();
 }
}
function setCodec(value){codec=value;if(value!=='h264'){lastError='QNX requires H.264; received '+value;save();}}
function setConfiguration(value){
 if(codec!=='h264')return;
 try{config=avc.configuration(Buffer.from(value));started=false;ensureDecoder();}
 catch(e){lastError=e.message;save();}
}
function receiveFrame(value){
 if(ending||codec!=='h264'||!config)return;
 receivedFrames++;
 lastVideoAt=Date.now();
 try{
  const frame=avc.frame(Buffer.from(value),config.lengthSize);
  lastNalTypes=frame.nalTypes;lastWasKeyframe=frame.keyframe;
  ensureDecoder();
  if(!decoderReady||!decoder?.stdin.writable){dropped++;dropNotReady++;started=false;if(stockReady)requestKeyframe();return;}
  if(decoder.stdin.writableLength>2*1024*1024){dropped++;started=false;requestKeyframe();return;}
  if(!started&&!frame.keyframe){dropped++;dropWaitingKey++;requestKeyframe();return;}
  if(!started||frame.keyframe)decoder.stdin.write(config.annexB);
  decoder.stdin.write(frame.bytes);decoder.stdin.write(avc.AUD);
  // Resuming a static screen starts a new active-input observation window.
  // Old decode timestamps must not classify the first new frame as a stall.
  const forwardedAt=Date.now();
  if(forwardedAt-lastForwardAt>3000)decodedProgressAt=forwardedAt;
  started=true;frames++;lastForwardAt=forwardedAt;bytes+=frame.bytes.length;if(frame.keyframe)keyframes++;lastError=null;
 }catch(e){lastError=e.message;started=false;requestKeyframe();save();}
}
function pollDecoded(){
 if(firstDecoded||!decoderReady||frames===0)return;
 const g=readGuest();
 if(g.decoded_frames>0){firstDecoded=true;console.log(JSON.stringify({stage:'first-qnx-decoded-frame',decoded:g.decoded_frames}));onDecoded?.();}
}
function setStack(value,name,peer){stack=value;session=!!value;phoneName=name??phoneName;peerAddress=peer??null;if(!modeChosen)mode=session?'carplay':'nbt';save();}
function clearStack(value){if(stack!==value)return;stack=null;session=false;save();}
function queue(task){if(queueDepth>=32)return Promise.reject(Error('控制指令过多，请稍候'));queueDepth++;
 const result=inputQueue.then(task);inputQueue=result.catch(()=>{});return result.finally(()=>queueDepth--);}
async function sendReports(reports,action){
 if(!controlReady())throw Error('QNX 或 CarPlay 控制通道未就绪');
 const s=stack._active,socket=s.eventSock;
 for(const r of reports){
  const b=Buffer.from(r.hex,'hex');
  if(![0x2a2a2a2a,0x2a2a2a2b].includes(r.uid)||b.length!==(r.uid===0x2a2a2a2b?4:12))throw Error('无效 HID 报告');
  stack._sendHidReport(r.uid,b);
 }
 await new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>finish(Error('CarPlay 控制发送超时')),3000);
  const fail=error=>finish(error);
  function finish(error){clearTimeout(timer);socket.removeListener('error',fail);error?reject(error):resolve();}
  socket.once('error',fail);socket.write(Buffer.alloc(0),error=>finish(error));
 });
 sent++;reportsSent+=reports.length;lastAction=action;lastError=null;
 fs.appendFileSync(path.join(NBT,'logs/carplay-input-events.jsonl'),JSON.stringify({at:new Date().toISOString(),index:sent,
  action,backend:'MacPlay '+connection,hid_encoding_location:'QNX',native_hid_pid:hid.pid,reports:reports.length,event_channel_written:true})+'\n',{mode:0o600});save();
}
async function encodeAndSend(fn,action){const at=performance.now();const reports=await fn();lastGuestMs=Math.round((performance.now()-at)*10)/10;await sendReports(reports,action);}
function overlay(target){return new Promise((resolve,reject)=>{
 const child=spawn('/usr/bin/ssh',[...ssh,'export LD_LIBRARY_PATH=/boot/lib; /boot/native/native_video_ctl '+(target==='carplay'?'show':'hide')],{stdio:['ignore','ignore','ignore']});
 const timeout=setTimeout(()=>{child.kill();reject(Error('切换显示超时'));},7000);
 child.on('error',e=>{clearTimeout(timeout);reject(e)});child.on('exit',code=>{clearTimeout(timeout);code===0?resolve():reject(Error('切换显示失败'))});
});}
function respond(res,status,value,origin){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',
 ...(origins.has(origin)?{'Access-Control-Allow-Origin':origin,'Vary':'Origin'}:{})});res.end(JSON.stringify(value));}
async function controlRequest(req,res){
 const origin=req.headers.origin;if(origin&&!origins.has(origin))return respond(res,403,{error:'Origin not allowed'});
 if(req.method==='GET'&&req.url==='/status')return respond(res,200,state(),origin);
 if(req.method==='OPTIONS'){res.writeHead(204,{'Access-Control-Allow-Origin':origin??'http://127.0.0.1:8876','Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type'});return res.end();}
 if(ending)return respond(res,503,{error:'服务正在停止'},origin);
 if(req.method!=='POST'||!['/action','/touch','/mode'].includes(req.url))return respond(res,404,{error:'Not found'},origin);
 if(!req.headers['content-type']?.startsWith('application/json'))return respond(res,415,{error:'JSON required'},origin);
 try{
  let text='';for await(const b of req){text+=b;if(Buffer.byteLength(text)>2048)throw Error('Request too large');}
  const data=JSON.parse(text);if(!data||typeof data!=='object')throw Error('无效控制数据');
  await queue(async()=>{
   if(req.url==='/mode'){
    if(!['nbt','carplay'].includes(data.target))throw Error('无效控制目标');
    if(mode==='carplay'&&data.target==='nbt'&&controlReady())await encodeAndSend(()=>hid.release(),'release');
    await overlay(data.target);mode=data.target;modeChosen=true;save();return;
   }
   if(mode!=='carplay')throw Error('当前控制目标是 NBT');
   if(!controlReady())throw Error('控制通道尚未就绪');
   if(req.url==='/action')await encodeAndSend(()=>hid.action(data.action,data.steps),data.action);
   else await encodeAndSend(()=>hid.touch(data.contacts),data.contacts?.length?'touch':'touch-release');
  });
  respond(res,200,req.url==='/mode'?state():{queued:true,event_channel_written:true,hid_encoding_location:'QNX',messages_sent:sent},origin);
 }catch(e){lastError=e.message;save();respond(res,controlReady()?400:503,{error:e.message},origin);}
}
const page='<!doctype html><meta charset="utf-8"><title>MacPlay · NBT 接收状态</title><style>body{background:#11151d;color:#eee;font:18px system-ui;max-width:800px;margin:50px auto;padding:24px}a{color:#8cdbb7}pre{white-space:pre-wrap;background:#202733;padding:20px;border-radius:12px}</style><h1>MacPlay → NBT</h1><p>'+connection+' 接收 · QNX 解码与显示</p><p><a href="http://127.0.0.1:8876/">打开 NBT 画面与旋钮</a></p><pre id="s">正在读取…</pre><script>async function p(){try{let s=await(await fetch("/api/status")).json();document.querySelector("#s").textContent=JSON.stringify(s,null,2)}catch{}setTimeout(p,1000)}p()</script>';
const controls=http.createServer(controlRequest);
const statusServer=http.createServer((req,res)=>{
 if(req.method==='GET'&&req.url==='/api/status')return respond(res,200,receiverState());
 if(req.method==='GET'&&req.url==='/'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});return res.end(page);}
 respond(res,404,{error:'Not found'});
});
for(const server of [controls,statusServer])server.on('error',e=>{lastError=e.message;save();console.error('NBT_BRIDGE_HTTP_ERROR',e.message);process.kill(process.pid,'SIGTERM')});
controls.listen(8877,'127.0.0.1');statusServer.listen(8878,'127.0.0.1');
import(pathToFileURL(path.join(NBT,'tools/native_hid_client.mjs')).href).then(({NativeHidClient})=>{
 if(ending)return;hid=new NativeHidClient(NATIVE,1280,480,save);hid.start();
}).catch(e=>{lastError=e.message;save()});
const timer=setInterval(()=>{checkDecoder();save();},1000);
function close(){
 if(ending)return;ending=true;clearInterval(timer);controls.close();statusServer.close();
 hid?.close();decoder?.stdin.end();setTimeout(()=>decoder?.kill('SIGTERM'),2000).unref();save();
}
module.exports={setCodec,setConfiguration,receiveFrame,pollDecoded,setStack,clearStack,close,state,
 onDecoded:fn=>{onDecoded=fn},onKeyframe:fn=>{requestKey=fn},mediaActivity:nativeCounts=>[receivedFrames,nativeCounts[1]??0]};
