const test=require('node:test'),assert=require('node:assert/strict');
const {configuration,frame}=require('./avc.cjs');
const avc=Buffer.from('0164001fffe100046764001f01000268ee','hex');
test('AVC configuration preserves SPS/PPS bytes and length size',()=>{
 const c=configuration(avc);assert.equal(c.lengthSize,4);
 assert.equal(c.annexB.toString('hex'),'000000016764001f0000000168ee');
});
test('access unit preserves each compressed NAL and detects IDR',()=>{
 const out=frame(Buffer.from('00000002658800000002419a','hex'),4);
 assert.equal(out.bytes.toString('hex'),'00000001658800000001419a');assert.equal(out.keyframe,true);
 assert.equal(frame(Buffer.from('02419a','hex'),1).keyframe,false);
});
test('malformed codec records and frame boundaries are rejected',()=>{
 for(const b of [Buffer.alloc(0),avc.subarray(0,8),avc.subarray(0,14)])assert.throws(()=>configuration(b));
 for(const h of ['0000','00000000','000000056588'])assert.throws(()=>frame(Buffer.from(h,'hex'),4));
 assert.throws(()=>frame(Buffer.alloc(1024*1024+1),4));
});
