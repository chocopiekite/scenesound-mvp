const test=require('node:test'),assert=require('node:assert/strict'),{createHmac}=require('node:crypto');
let relay;global.Deno={env:{get:()=> 'relay-test-secret'},serve(fn){relay=fn;}};
require('../supabase/functions/video-upload/index.ts');
function permit(extra={}){const value={url:'https://tl-api-assets-prod.s3.us-west-2.amazonaws.com/chunk',size:3,exp:Date.now()+60000,headers:{},...extra};const encoded=Buffer.from(JSON.stringify(value)).toString('base64url');return encoded+'.'+createHmac('sha256','relay-test-secret').update(encoded).digest('base64url');}
function req(token,body='abc',origin='https://scenesound-mvp.vercel.app'){return new Request('https://example.test',{method:'PUT',headers:{origin,'x-upload-permit':token},body});}
test('relay rejects forged permits, expired permits, other destinations and oversized chunks',async()=>{
 const old=global.fetch;global.fetch=()=>{throw Error('must not fetch');};
 try{assert.equal((await relay(req('forged'))).status,403);assert.equal((await relay(req(permit({exp:1})))).status,403);assert.equal((await relay(req(permit({url:'https://example.com/private'})))).status,403);assert.equal((await relay(req(permit(),'abcdef'))).status,413);assert.equal((await relay(req(permit(),'abc','https://evil.test'))).status,403);}finally{global.fetch=old;}
});
test('relay forwards only the authorized bytes and exposes receipt for browser completion',async()=>{
 const old=global.fetch;global.fetch=async(url,options)=>{assert.equal(url.hostname,'tl-api-assets-prod.s3.us-west-2.amazonaws.com');assert.equal(Buffer.from(options.body).toString(),'abc');assert.equal(options.redirect,'error');return new Response(null,{headers:{ETag:'receipt'}});};
 try{const response=await relay(req(permit()));assert.equal(response.status,200);assert.equal(response.headers.get('ETag'),'receipt');assert.equal(response.headers.get('Access-Control-Expose-Headers'),'ETag');}finally{global.fetch=old;delete global.Deno;}
});
