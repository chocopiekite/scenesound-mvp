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
