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
 const status=await call('/api/studio/status');assert.equal(status.headers['Access-Control-Allow-Origin'],'https://scenesound-mvp.vercel.app');assert.equal(status.data.maxDuration,1800);
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
test('public uploads reflect the 1 GiB safe input budget and reject oversize media before streaming',async()=>{
 const info=await call('/api/studio/status');assert.equal(info.data.maxBytes,1024**3);assert.equal(info.data.storageBudgetBytes,1.5*1024**3);assert.equal(handler.uploadLimit('video'),1024**3);assert.equal(handler.uploadLimit('aaf'),1024**3);
 const created=await call('/api/studio/jobs','POST',auth.session(A));const url='/api/studio/jobs/'+created.data.id;
 assert.equal((await call(url+'/files?role=video&name=test.mp4','POST',auth.session(A),{'content-length':String(2*1024**3+1)})).code,413);
 assert.equal((await call(url+'/files?role=aaf&name=test.aaf','POST',auth.session(A),{'content-length':String(5*1024**3+1)})).code,413);
 assert.equal((await call(url,'DELETE',auth.session(A))).code,200);
});
test('chunk uploads enforce owner, offsets, byte bounds and exactly-once completion',async()=>{
 const {Readable}=require('node:stream');
 const created=await call('/api/studio/jobs','POST',auth.session(A));const url='/api/studio/jobs/'+created.data.id;
 async function streamCall(path,body,method='POST',who=A){let code=200,data;const bytes=Buffer.isBuffer(body)?body:Buffer.from(JSON.stringify(body));const req=Readable.from([bytes]);Object.assign(req,{url:path,method,headers:{host:'worker.onrender.com',origin:'https://scenesound-mvp.vercel.app',authorization:'Bearer '+auth.session(who),'content-length':String(bytes.length)}});const res={setHeader(){},status(c){code=c;return this;},json(d){data=d;}};await handler(req,res);return{code,data};}
 try{assert.equal((await streamCall(url+'/uploads',{role:'aaf',name:'large.aaf',size:1024**3+1})).code,413);const start=await streamCall(url+'/uploads',{role:'aaf',name:'test.aaf',size:6});assert.equal(start.code,200);const upload=url+'/uploads/'+start.data.id;
 assert.equal((await streamCall(upload+'?offset=0',Buffer.from('abc'),'POST',B)).code,403);
 assert.equal((await streamCall(upload+'?offset=1',Buffer.from('abc'))).code,409);
 assert.equal((await streamCall(upload+'?offset=0',Buffer.from('abc'))).data.offset,3);
 assert.equal((await call(upload,'GET',auth.session(A))).data.offset,3);
 assert.equal((await streamCall(upload+'?offset=3',Buffer.from('defg'))).code,413);
 assert.equal((await streamCall(upload+'?offset=3',Buffer.from('def'))).data.done,true);
 assert.equal((await streamCall(upload+'?offset=3',Buffer.from('def'))).code,409);
 const folder=path.join(process.env.STUDIO_DATA_DIR,'job-'+created.data.id),uploads=JSON.parse(fs.readFileSync(path.join(folder,'uploads.json')));assert.equal(uploads.length,1);assert.equal(fs.readFileSync(path.join(folder,uploads[0].file),'utf8'),'abcdef');
 }finally{await call(url,'DELETE',auth.session(A));}
});
