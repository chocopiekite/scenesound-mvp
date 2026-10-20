const test=require('node:test');
const assert=require('node:assert/strict');
const handler=require('../api/sounds');
async function call(url='/api/sounds?q=door',method='GET'){
  const res={setHeader(){},status(code){this.code=code;return this;},json(data){this.data=data;}};
  await handler({method,url},res);return res;
}
test('missing key and invalid queries never call Freesound',async()=>{
  delete process.env.FREESOUND_API_KEY;
  assert.equal((await call()).code,503);
  assert.equal((await call('/api/sounds')).code,400);
  assert.equal((await call('/api/sounds?q=door','POST')).code,405);
});
test('search uses private header, CC0 filter and excludes unsafe results',async()=>{
  process.env.FREESOUND_API_KEY='private-test-key';const original=global.fetch;
  const sound={id:123,name:'Door',username:'Artist',license:'http://creativecommons.org/publicdomain/zero/1.0/',duration:3,url:'https://freesound.org/people/Artist/sounds/123/',previews:{'preview-hq-mp3':'https://cdn.freesound.org/previews/0/123.mp3'}};
  global.fetch=async(url,options)=>{
    assert.equal(url.origin,'https://freesound.org');assert.equal(url.searchParams.get('query'),'door');
    assert.equal(url.searchParams.get('filter'),'license:"Creative Commons 0"');
    assert.equal(options.headers.Authorization,'Token private-test-key');assert.ok(!url.toString().includes('private-test-key'));
    return {ok:true,json:async()=>({results:[sound,{...sound,id:2,license:'https://creativecommons.org/licenses/by-nc/4.0/'},{...sound,id:3,previews:{'preview-hq-mp3':'https://evil.example/a.mp3'}},{...sound,id:4,url:'javascript:alert(1)'}]})};
  };
  try{const result=await call();assert.equal(result.code,200);assert.equal(result.data.candidates.length,1);assert.equal(result.data.candidates[0].license,'CC0');assert.doesNotMatch(JSON.stringify(result.data),/private-test-key/);}
  finally{global.fetch=original;delete process.env.FREESOUND_API_KEY;}
});
test('quota failures preserve no provider message or secret',async()=>{
  process.env.FREESOUND_API_KEY='private-test-key';const original=global.fetch;
  global.fetch=async()=>({ok:false,status:429});
  try{const result=await call();assert.equal(result.code,429);assert.doesNotMatch(JSON.stringify(result.data),/private-test-key/);}
  finally{global.fetch=original;delete process.env.FREESOUND_API_KEY;}
});
test('empty detailed search falls back once to broader motion sound',async()=>{
  process.env.FREESOUND_API_KEY='private-test-key';const original=global.fetch;const queries=[];
  global.fetch=async url=>{queries.push(url.searchParams.get('query'));return {ok:true,json:async()=>({results:[]})};};
  try{const result=await call('/api/sounds?q=soft%20sliding');assert.equal(result.code,200);assert.deepEqual(queries,['soft sliding','whoosh']);}
  finally{global.fetch=original;delete process.env.FREESOUND_API_KEY;}
});
