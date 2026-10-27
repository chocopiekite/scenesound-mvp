const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
process.env.STUDIO_PUBLIC='1';process.env.STUDIO_WORKER_SECRET='test-only-not-a-production-secret-123456789';process.env.STUDIO_WORKER_URL='https://test-worker.onrender.com';process.env.STUDIO_DATA_DIR=fs.mkdtempSync(path.join(os.tmpdir(),'scenesound-public-test-'));
const auth=require('../lib/studio-auth.cjs');const handler=require('../studio/server.cjs');const sessionHandler=require('../api/studio-session.js');
const A='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',B='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
async function call(url,method='GET',token,extra={}){let code=200,data,headers={};const req={url,method,headers:{host:'worker.onrender.com',origin:'https://scenesound-mvp.vercel.app',...(token?{authorization:'Bearer '+token}:{}),...extra}};const res={setHeader(k,v){headers[k]=v;},status(c){code=c;return this;},json(d){data=d;},end(){}};await handler(req,res);return{code,data,headers};}
test('public mode requires signed sessions and checks each job owner',async()=>{
 assert.equal((await call('/api/studio/jobs','POST')).code,401);
 assert.equal((await call('/api/studio/jobs','POST',auth.session(A)+'x')).code,401);
 const created=await call('/api/studio/jobs','POST',auth.session(A));assert.equal(created.code,200);const url='/api/studio/jobs/'+created.data.id;
 assert.equal((await call(url,'GET',auth.session(B))).code,403);
 assert.equal((await call(url,'DELETE',auth.session(B))).code,403);
 const own=await call(url,'GET',auth.session(A));assert.equal(own.code,200);assert.ok(own.data.ticket);
 assert.equal((await call(url+'/files/does-not-exist.wav?ticket='+auth.ticket(B,created.data.id))).code,403);
 assert.equal((await call(url+'/files/does-not-exist.wav?ticket='+auth.ticket(A,'other-job'))).code,403);
 assert.equal((await call(url+'/files/does-not-exist.wav?ticket='+own.data.ticket)).code,404);
 assert.equal((await call(url,'DELETE',auth.session(A))).code,200);
});
test('public worker blocks other origins and provides exact CORS',async()=>{
 assert.equal((await call('/api/studio/status','GET',null,{origin:'https://evil.example'})).code,403);
 const status=await call('/api/studio/status');assert.equal(status.headers['Access-Control-Allow-Origin'],'https://scenesound-mvp.vercel.app');assert.equal(status.data.maxDuration,300);
});
test('token purposes and expiry cannot be exchanged',()=>{
 assert.equal(auth.verify(auth.sign({sid:A,kind:'session',exp:1}),'session'),null);
 assert.equal(auth.verify(auth.ticket(A,'job'),'session'),null);
 assert.equal(auth.verify(auth.session(A),'media'),null);
});
test('Vercel session refresh keeps the private browser identity and never returns shared secret',async()=>{
 let data,headers={};const res={setHeader(k,v){headers[k]=v;},status(){return this;},json(d){data=d;}};
 await sessionHandler({method:'GET',headers:{}},res);assert.ok(data.ready);assert.ok(!JSON.stringify(data).includes(process.env.STUDIO_WORKER_SECRET));const first=auth.verify(data.token,'session');
 const cookie=headers['Set-Cookie'].split(';')[0];await sessionHandler({method:'GET',headers:{cookie}},res);assert.equal(auth.verify(data.token,'session').sid,first.sid);
});
test.after(()=>fs.rmSync(process.env.STUDIO_DATA_DIR,{recursive:true,force:true}));
