const test=require('node:test'),assert=require('node:assert/strict');
const sounds=require('../api/sounds'),preview=require('../api/epidemic-preview'),events=require('../api/sound-events');
function call(handler,url,method='GET',body,host='127.0.0.1:8001'){const r={setHeader(){},status(c){this.code=c;return this;},json(d){this.data=d;}};return handler({url,method,body,headers:{host,'x-sound-session':'12345678-1234-4234-8234-123456789abc'}},r).then(()=>r);}
test('prototype key never activates on Vercel or a public host',async()=>{
 process.env.EPIDEMIC_API_KEY='epidemic-test-secret';
 const r=await call(sounds,'/api/sounds?providers=1','GET',null,'scenesound-mvp.vercel.app');assert.equal(r.data.epidemic,false);process.env.VERCEL='1';assert.equal((await call(preview,'/api/epidemic-preview?id=123')).code,404);delete process.env.VERCEL;
});
test('search uses backend auth and never requests audio URLs while listing',async()=>{
 const old=fetch;let calls=0;global.fetch=async(url,options)=>{calls++;assert.match(url,/sound-effects\/search/);assert.match(url,/order=desc/);assert.equal(options.headers.Authorization,'Bearer epidemic-test-secret');return{ok:true,json:async()=>({soundEffects:[{id:'id-123',title:'Rain, General, Window',length:5}]})};};
 try{const r=await call(sounds,'/api/sounds?q=rain&provider=epidemic');assert.equal(r.code,200);assert.equal(calls,1);assert.equal(r.data.candidates[0].provider,'epidemic');assert.equal(r.data.candidates[0].preview,undefined);assert.doesNotMatch(JSON.stringify(r.data),/epidemic-test-secret/);assert.match(r.data.candidates[0].license,/시험/);}finally{global.fetch=old;}
});
test('one failed library keeps successful candidates and returns a warning',async()=>{
 process.env.FREESOUND_API_KEY='fs-test';const old=fetch;global.fetch=async url=>{if(String(url).includes('freesound.org'))return{ok:false,status:500};return{ok:true,json:async()=>({soundEffects:[{id:'rain',title:'Rain',length:8}]})};};
 try{const r=await call(sounds,'/api/sounds?q=rain');assert.equal(r.code,200);assert.equal(r.data.candidates.length,1);assert.equal(r.data.warnings.length,1);}finally{global.fetch=old;delete process.env.FREESOUND_API_KEY;}
});
test('preview validates CDN and reports only allowed anonymous events',async()=>{
 const old=fetch;let body;
 try{global.fetch=async()=>({ok:true,json:async()=>({url:'https://evil.example/a.mp3'})});assert.equal((await call(preview,'/api/epidemic-preview?id=rain')).code,502);
 global.fetch=async()=>({ok:true,json:async()=>({url:'https://pdn.epidemicsound.com/a.mp3?sig=keep',expires:'tomorrow'})});assert.equal((await call(preview,'/api/epidemic-preview?id=rain')).data.preview,'https://pdn.epidemicsound.com/a.mp3?sig=keep');
 global.fetch=async(url,options)=>{body=JSON.parse(options.body);return{ok:true,status:204};};assert.equal((await call(events,'/api/sound-events','POST',{id:'rain',type:'trackPreviewed'})).code,200);assert.equal(body.events[0].userId,'12345678-1234-4234-8234-123456789abc');assert.equal((await call(events,'/api/sound-events','POST',{id:'rain',type:'anything'})).code,400);
 }finally{global.fetch=old;delete process.env.EPIDEMIC_API_KEY;}
});
