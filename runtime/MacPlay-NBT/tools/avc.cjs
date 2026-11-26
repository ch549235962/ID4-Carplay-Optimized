// Reframe compressed AVC only. No decoding, scaling or transcoding on the Mac.
const START=Buffer.from([0,0,0,1]);
function configuration(record){
 if(!Buffer.isBuffer(record)||record.length<7||record[0]!==1)throw Error('Invalid AVC configuration');
 let at=6;const sets=[];
 function group(count){for(let i=0;i<count;i++){
  if(at+2>record.length)throw Error('Truncated AVC parameter set');
  const length=record.readUInt16BE(at);at+=2;
  if(!length||at+length>record.length)throw Error('Invalid AVC parameter set length');
  sets.push(START,record.subarray(at,at+length));at+=length;
 }}
 group(record[5]&31);if(at>=record.length)throw Error('Missing AVC PPS count');group(record[at++]);
 if(!sets.length)throw Error('Missing AVC parameter sets');
 return {lengthSize:(record[4]&3)+1,annexB:Buffer.concat(sets)};
}
function frame(payload,lengthSize){
 if(!Buffer.isBuffer(payload)||payload.length>1024*1024||payload.length===0)throw Error('Invalid video frame size');
 const chunks=[],nalTypes=[];let at=0,keyframe=false;
 while(at<payload.length){
  if(at+lengthSize>payload.length)throw Error('Truncated NAL length');
  const length=payload.readUIntBE(at,lengthSize);at+=lengthSize;
  if(!length||at+length>payload.length)throw Error('Invalid NAL length');
  const nal=payload.subarray(at,at+length);at+=length;
  nalTypes.push(nal[0]&31);
  if((nal[0]&31)===5)keyframe=true;
  chunks.push(START,nal);
 }
 const bytes=Buffer.concat(chunks);
 if(bytes.length>1024*1024-65536)throw Error('Frame exceeds QNX access-unit capacity');
 return {bytes,keyframe,nalTypes};
}
module.exports={configuration,frame,AUD:Buffer.from([0,0,0,1,9,240])};
