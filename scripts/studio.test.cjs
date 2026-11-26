const test=require('node:test');const assert=require('node:assert/strict');
const handler=require('../studio/server.cjs');
async function call(headers,url='/api/studio/status',method='GET') {let code=200,data;const res={setHeader(){},status(c){code=c;return this;},json(d){data=d;}};await handler({headers,url,method},res);return{code,data};}
test('local worker rejects untrusted Host and cross-origin requests',async()=>{
 for(const headers of [{host:'attacker.example:8001'},{host:'127.0.0.1:8001',origin:'https://attacker.example'},{host:'127.0.0.1:8001','sec-fetch-site':'cross-site'}])assert.equal((await call(headers)).code,403);
 assert.equal((await call({host:'127.0.0.1:8001',origin:'http://127.0.0.1:8001'})).code,200);
});
test('automatic placement rejects invalid times and ignores editing advice',()=>{
 const validate=handler.validatePlan;
 const sound={title:'Door',searchQuery:'door',type:'효과음',start:1,end:2};
 assert.throws(()=>validate({sounds:[{...sound,end:11}]},10));
 assert.throws(()=>validate({sounds:[{...sound,start:-1}]},10));
 assert.throws(()=>validate({sounds:[{...sound,type:'unknown'}]},10));
 assert.deepEqual(validate({sounds:[{type:'편집 팁'}, {...sound,start:10,end:10}]},10),[]);
 assert.equal(validate({sounds:[sound]},10)[0].role,'effect');
});
test('dialogue reference selection is confined to selected tracks and its own scene',()=>{
 const validate=handler.validateDialogueReferences;
 const manifest={duration:12,tracks:[{id:'t0',slotId:3,clips:[{componentIndex:0,start:0,duration:4},{componentIndex:1,start:6,duration:4}]}]};
 const scenes=[{start:0,title:'A'},{start:6,title:'B'}],roles={t0:'dialogue'};
 assert.deepEqual(validate(manifest,roles,scenes,{'0':'3:0','1':'3:1'}),{'0':'3:0','1':'3:1'});
 for(const invalid of [[],{'9':'3:0'},{'0':'3:1'},{'0':'3:99'},{'0':'../../secret'},JSON.parse('{"__proto__":"3:0"}')]){
  if(Object.keys(invalid).length)assert.throws(()=>validate(manifest,roles,scenes,invalid));
 }
 assert.throws(()=>validate(manifest,{t0:'ignore'},scenes,{'0':'3:0'}));
 assert.throws(()=>validate(manifest,roles,scenes,[]));
});
