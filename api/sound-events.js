const es=require('../lib/epidemic.cjs');
module.exports=async(req,res)=>{
 res.setHeader('Cache-Control','no-store');const reply=(s,d)=>res.status(s).json(d);
 if(!es.enabled(req))return reply(404,{error:'로컬 시험 연결에서만 이용할 수 있어요.'});
 if(req.method!=='POST')return reply(405,{error:'지원하지 않는 요청이에요.'});
 try{const body=typeof req.body==='string'?JSON.parse(req.body):req.body;if(!body||!/^[a-zA-Z0-9_-]{1,100}$/.test(body.id||'')||body.type!=='trackPreviewed')return reply(400,{error:'이용 정보를 확인해 주세요.'});await es.api('/analytics/report',req,'POST',{events:[{userId:es.userId(req),timestamp:new Date().toISOString(),userConnected:false,analyticsEvent:{trackId:body.id,type:'trackPreviewed'}}]});return reply(200,{ok:true});}catch{return reply(502,{error:'미리 듣기 이용 기록을 전송하지 못했어요.'});}
};
