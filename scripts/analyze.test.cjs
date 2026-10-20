const test=require('node:test');const assert=require('node:assert/strict');const handler=require('../api/analyze');
function call(method,body){const res={setHeader(){},status(code){this.code=code;return this;},json(data){this.data=data;}};return handler({method,body},res).then(()=>res);}
test('missing key never produces recommendations',async()=>{delete process.env.TWELVELABS_API_KEY;const status=await call('GET');assert.equal(status.data.ready,false);assert.equal((await call('POST',{})).code,503);});
test('rejects unsupported input before contacting AI',async()=>{process.env.TWELVELABS_API_KEY='test-only-placeholder';assert.equal((await call('POST',{video:'AAAA',mimeType:'text/plain',duration:5})).code,400);assert.equal((await call('POST',{video:'AAAA',mimeType:'video/mp4',duration:90})).code,400);});
test('forwards video and validates timeline from AI response',async()=>{const original=global.fetch;global.fetch=async(url,options)=>{const body=JSON.parse(options.body);assert.equal(url,'https://api.twelvelabs.io/v1.3/analyze');assert.equal(body.video.type,'base64_string');assert.equal(body.video.base64_string,'AAAA');assert.equal(body.stream,false);assert.equal(body.response_format.type,'json_schema');return{ok:true,json:async()=>({finish_reason:'stop',data:JSON.stringify({summary:'문을 여는 장면',sounds:[{title:'문 여는 소리',type:'효과음',why:'동작 강조',where:'문이 열릴 때',start:1,end:2}]})})};};try{assert.equal((await call('POST',{video:'AAAA',mimeType:'video/mp4',duration:5})).code,200);assert.equal((await call('POST',{video:'AAAA',mimeType:'video/mp4',duration:1})).code,502);}finally{global.fetch=original;delete process.env.TWELVELABS_API_KEY;}});
test('rejects truncated output and handles free quota without leaking provider details',async()=>{
  process.env.TWELVELABS_API_KEY='test-only-placeholder';
  const original=global.fetch;
  const originalError=console.error;
  const logs=[];console.error=(...parts)=>logs.push(parts.join(' '));
  try {
    global.fetch=async()=>({ok:true,json:async()=>({finish_reason:'length',data:'{"summary":'})});
    assert.equal((await call('POST',{video:'AAAA',mimeType:'video/mp4',duration:5})).code,502);
    global.fetch=async()=>({ok:false,status:429,json:async()=>({code:'rate_limit_exceeded',message:'test-only-placeholder private video content'})});
    const result=await call('POST',{video:'AAAA',mimeType:'video/mp4',duration:5});
    assert.equal(result.code,429);
    assert.match(result.data.error,/무료 이용 한도/);
    assert.doesNotMatch(JSON.stringify({logs,result}),/test-only-placeholder|private video content/);
  } finally {global.fetch=original;console.error=originalError;delete process.env.TWELVELABS_API_KEY;}
});
