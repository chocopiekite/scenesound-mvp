const test=require('node:test'),assert=require('node:assert/strict');
const handler=require('../api/upload'),analyze=require('../api/analyze');
const {sign}=require('../lib/video-session.cjs');
async function call(fn,body){const r={setHeader(){},status(c){this.code=c;return this;},json(d){this.data=d;}};await fn({method:'POST',body},r);return r;}
test('large uploads reject oversized files and forged asset capabilities before provider calls',async()=>{
 process.env.TWELVELABS_API_KEY='test-placeholder';process.env.VIDEO_UPLOAD_RELAY_SECRET='relay-test-placeholder';const old=global.fetch;global.fetch=()=>{throw Error('must not fetch');};
 try{assert.equal((await call(handler,{action:'create',size:201*1024*1024,duration:120,mimeType:'video/mp4'})).code,400);assert.equal((await call(handler,{action:'status',token:'forged'})).code,403);}finally{global.fetch=old;}
});
test('200 MB session keeps key private and server validates actual media duration',async()=>{
 const old=global.fetch;const calls=[];global.fetch=async(url,options)=>{calls.push([url,options]);return {ok:true,status:200,json:async()=>url.endsWith('multipart-uploads')?{asset_id:'asset1',upload_id:'upload1',chunk_size:5242880,total_chunks:40,upload_urls:[],upload_headers:{}}:{status:'ready',duration:601,size:209715200}};};
 try{const r=await call(handler,{action:'create',size:200*1024*1024,duration:600,mimeType:'video/mp4'});assert.equal(r.code,200);assert.doesNotMatch(JSON.stringify(r),/test-placeholder/);assert.equal((await call(handler,{action:'status',token:r.data.token})).code,400);assert.equal(calls.at(-1)[1].method,'DELETE');}finally{global.fetch=old;}
});
test('long video analysis uses signed asset ID without base64 and cleans up after result',async()=>{
 const old=global.fetch,calls=[];global.fetch=async(url,options)=>{calls.push([url,options]);if(options.method==='DELETE')return{ok:true,status:204};const body=JSON.parse(options.body);assert.deepEqual(body.video,{type:'asset_id',asset_id:'only-this-asset'});return{ok:true,json:async()=>({finish_reason:'stop',data:JSON.stringify({summary:'긴 장면',sounds:[{title:'발소리',type:'효과음',why:'걷기',where:'복도',start:90,end:95}]})})};};
 try{const token=sign({asset:'only-this-asset',ready:true,duration:120});const r=await call(analyze,{token});assert.equal(r.code,200);assert.equal(r.data.sounds[0].start,90);assert.equal(calls.at(-1)[0],'https://api.twelvelabs.io/v1.3/assets/only-this-asset');assert.equal(calls.at(-1)[1].method,'DELETE');}finally{global.fetch=old;delete process.env.TWELVELABS_API_KEY;}
});
