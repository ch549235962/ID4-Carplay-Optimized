const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),{EventEmitter}=require('node:events');
test('decoder retry, fragmented readiness, static-screen guard and shutdown',async()=>{
 let now=100000,guest={ready:true,sampled_at:100,guest_sample_age_seconds:0,decoded_frames:1,presented_frames:1};
 const children=[],timers=[],writes=new Map();
 const fakeFS={readFileSync:file=>file.endsWith('renderer-metrics.json')?JSON.stringify({...guest,sampled_at:now/1000}):JSON.stringify({wireless:false}),writeFileSync:(file,data)=>writes.set(file,data),renameSync:(a,b)=>writes.set(b,writes.get(a)),appendFileSync:()=>{}};
 const spawn=(exe,args)=>{const child=new EventEmitter();child.pid=200+children.length;child.args=args;child.stderr=new EventEmitter();child.stdout=new EventEmitter();child.stdin={writable:true,writableLength:0,write:()=>true,on:()=>{},end:()=>{}};child.kills=0;child.kill=()=>{child.kills++;child.emit('close',1)};children.push(child);return child;};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
 const ctx={module:{exports:{}},__dirname:path.resolve(__dirname),Buffer,Date:Clock,process:{env:{MACPLAY_SETTINGS_PATH:'profile.json',NBT_QNX_BUILTIN_TOOLS:'1'},pid:99,stderr:{write:()=>{}},kill:()=>{}},console:{log:()=>{},error:()=>{}},performance:{now:()=>now},setTimeout:()=>({unref(){}}),clearTimeout:()=>{},setInterval:fn=>(timers.push(fn),1),clearInterval:()=>{}};
 ctx.require=name=>name==='node:fs'?fakeFS:name==='node:child_process'?{spawn}:name==='node:http'?{createServer:()=>({on(){},listen(){},close(){}})}:name==='./avc.cjs'?{configuration:()=>({lengthSize:4,annexB:Buffer.from([1])}),frame:value=>({keyframe:value[0]===5,bytes:value,nalTypes:[value[0]]}),AUD:Buffer.from([9])}:require(name);
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'nbt_bridge.cjs'),'utf8'),ctx);await new Promise(resolve=>setImmediate(resolve));
 const bridge=ctx.module.exports;let keys=0;bridge.onKeyframe(()=>keys++);bridge.setStack({},'test','::1');bridge.setCodec('h264');bridge.setConfiguration(Buffer.from([1]));assert.equal(children.length,1);assert.ok(children[0].args.at(-1).includes('/boot/native/native_decoder'));
 children[0].stderr.emit('data',Buffer.from('QNX_NATIVE_'));assert.equal(bridge.state().decoder_transport_ready,false);children[0].stderr.emit('data',Buffer.from('DECODER_READY ffmpeg=test\n'));assert.equal(bridge.state().decoder_transport_ready,true);
 bridge.receiveFrame(Buffer.from([5]));children[0].emit('close',1);
 for(let i=0;i<100;i++)bridge.receiveFrame(Buffer.from([1]));assert.equal(children.length,1);assert.equal(keys,1);
 now+=1500;timers[0]();assert.equal(children.length,2);children[1].stderr.emit('data',Buffer.from('QNX_NATIVE_DECODER_READY'));bridge.receiveFrame(Buffer.from([5]));
 now+=1500;timers[0]();now+=20000;timers[0]();assert.equal(children[1].kills,0,'static video must not cause recovery');
 bridge.receiveFrame(Buffer.from([5]));timers[0]();assert.equal(children[1].kills,0,'resuming a static screen must allow decoding to progress');
 for(let i=0;i<13;i++){now+=1000;bridge.receiveFrame(Buffer.from([1]));timers[0]();}
 assert.equal(children[1].kills,1,'continuous input without decoded progress must still recover');assert.equal(bridge.state().decoder_recoveries,1);
 const count=children.length;bridge.close();now+=60000;timers[0]();assert.equal(children.length,count,'shutdown must cancel automatic retries');
});
