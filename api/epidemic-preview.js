const es=require('../lib/epidemic.cjs');
module.exports=async(req,res)=>{
 res.setHeader('Cache-Control','no-store');const reply=(s,d)=>res.status(s).json(d);
 if(!es.enabled(req))return reply(404,{error:'로컬 시험 연결에서만 이용할 수 있어요.'});
 if(req.method!=='GET')return reply(405,{error:'지원하지 않는 요청이에요.'});
 const id=new URL(req.url,'http://localhost').searchParams.get('id');if(!/^[a-zA-Z0-9_-]{1,100}$/.test(id||''))return reply(400,{error:'음원 정보를 확인해 주세요.'});
 try{const data=await es.api('/sound-effects/'+id+'/download?format=mp3&quality=normal',req);const url=new URL(data.url);if(url.protocol!=='https:'||url.hostname!=='pdn.epidemicsound.com'||url.username||url.password)throw Error('Unsafe URL');return reply(200,{preview:url.href,expires:data.expires});}catch{return reply(502,{error:'시험용 미리 듣기를 불러오지 못했어요. API 한도와 계정 연결을 확인해 주세요.'});}
};
