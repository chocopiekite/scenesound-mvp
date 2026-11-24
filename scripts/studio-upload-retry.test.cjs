const test=require('node:test'),assert=require('node:assert/strict');
const {uploadStudioFile}=require('../studio/video-transfer.js');
const file=Object.assign(new Blob(['abcdefgh']),{name:'test.aaf'});
test('lost acknowledgement and unavailable offset endpoint recover without sending committed bytes twice',async()=>{
 let sends=0,checks=0,offset=0,retries=0;const progress=[];
 await uploadStudioFile(file,'aaf',{base:'',job:'test',auth:()=>'',pause:async()=>{},onRetry:()=>retries++,onProgress:p=>progress.push(p),request:async(path,body)=>{if(body)return{id:'x',offset:0,chunkBytes:4};checks++;if(checks===1)throw new TypeError('Load failed');return{offset};},fetchChunk:async(url,{body})=>{sends++;offset+=body.size;if(sends===1)throw new TypeError('Load failed');return{ok:true,json:async()=>({offset})};}});
 assert.equal(sends,2);assert.equal(checks,2);assert.equal(retries,2);assert.deepEqual(progress,[50,100]);
});
test('permanent disk-space error stops immediately',async()=>{
 let sends=0;await assert.rejects(uploadStudioFile(file,'aaf',{base:'',job:'test',auth:()=>'',pause:async()=>{},request:async()=>({id:'x',offset:0,chunkBytes:4}),fetchChunk:async()=>{sends++;return{ok:false,status:507,json:async()=>({error:'임시 공간 부족'})};}}),/임시 공간 부족/);assert.equal(sends,1);
});
test('continuous network outage has bounded retries and a useful error',async()=>{
 let checks=0;await assert.rejects(uploadStudioFile(file,'aaf',{base:'',job:'test',auth:()=>'',pause:async()=>{},request:async(path,body)=>{if(body)return{id:'x',offset:0,chunkBytes:4};checks++;throw TypeError('Load failed');},fetchChunk:async()=>{throw TypeError('Load failed');}}),/업로드 연결이 계속 끊겨/);assert.equal(checks,7);
});
