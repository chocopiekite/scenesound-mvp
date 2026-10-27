const {session,verify,sign}=require('../lib/studio-auth.cjs');
const {randomUUID}=require('node:crypto');
module.exports=async(req,res)=>{
 res.setHeader('Cache-Control','no-store');res.setHeader('Referrer-Policy','no-referrer');
 if(req.method!=='GET')return res.status(405).json({error:'지원하지 않는 요청이에요.'});
 const origin=req.headers.origin;if(origin&&origin!=='https://scenesound-mvp.vercel.app')return res.status(403).json({error:'허용되지 않은 요청이에요.'});
 if(req.headers['sec-fetch-site']==='cross-site')return res.status(403).json({error:'허용되지 않은 요청이에요.'});
 try{
 const worker=new URL(process.env.STUDIO_WORKER_URL||'');if(worker.protocol!=='https:'||!worker.hostname.endsWith('.onrender.com'))throw Error('worker');
 const cookies=Object.fromEntries((req.headers.cookie||'').split(';').map(c=>c.trim().split('=')));
 const previous=verify(cookies['ss-studio-session'],'cookie'),sid=previous?.sid||randomUUID();
 res.setHeader('Set-Cookie','ss-studio-session='+sign({kind:'cookie',sid,exp:Math.floor(Date.now()/1000)+86400})+'; HttpOnly; Secure; SameSite=Strict; Path=/api/studio-session; Max-Age=86400');
 return res.status(200).json({ready:true,worker:worker.origin,token:session(sid),maxDuration:300,maxBytes:400*1024*1024});
 }catch{return res.status(503).json({error:'공개 작업 서버를 준비 중이에요. 잠시 후 다시 열어 주세요.'});}
};
