// Loopback-only pairing, with an ephemeral key that never leaves this process.
const {randomBytes,randomUUID,createHmac,timingSafeEqual}=require('node:crypto');
const ORIGIN='https://scenesound-mvp.vercel.app',LOCAL='http://127.0.0.1:8001';
const secret=randomBytes(32);
const fail=(s,m)=>Object.assign(Error(m),{status:s});
function sign(data){const body=Buffer.from(JSON.stringify(data)).toString('base64url');return body+'.'+createHmac('sha256',secret).update('local-v1:'+body).digest('base64url');}
function verify(token,kind){try{if(typeof token!=='string'||token.length>2048)return null;const [body,sig,extra]=token.split('.');if(extra||!body||!sig)return null;const a=Buffer.from(sig,'base64url'),b=createHmac('sha256',secret).update('local-v1:'+body).digest();if(a.length!==b.length||!timingSafeEqual(a,b))return null;const d=JSON.parse(Buffer.from(body,'base64url'));if(d.kind!==kind||!Number.isSafeInteger(d.exp)||d.exp<=Date.now()/1000||!/^[0-9a-f-]{36}$/.test(d.sid))return null;return d;}catch{return null;}}
function session(){return sign({kind:'session',sid:randomUUID(),exp:Math.floor(Date.now()/1000)+24*3600});}
function ticket(sid,jid){return sign({kind:'media',sid,jid,exp:Math.floor(Date.now()/1000)+24*3600});}
function authorize(req,res,url){
 if(req.headers.host!=='127.0.0.1:8001')throw fail(403,'이 컴퓨터의 로컬 서버에서만 연결할 수 있어요.');
 const origin=req.headers.origin,remote=origin===ORIGIN;
 if(origin&&origin!==ORIGIN&&origin!==LOCAL)throw fail(403,'허용되지 않은 웹사이트예요.');
 if(remote){res.setHeader('Access-Control-Allow-Origin',ORIGIN);res.setHeader('Vary','Origin');res.setHeader('Access-Control-Allow-Headers','Authorization,Content-Type,Range');res.setHeader('Access-Control-Allow-Methods','GET,POST,DELETE,OPTIONS');res.setHeader('Access-Control-Expose-Headers','Content-Range,Content-Length,Accept-Ranges,Content-Disposition');res.setHeader('Access-Control-Allow-Private-Network','true');}
 if(req.method==='OPTIONS'){if(!remote&&origin!==LOCAL)throw fail(403,'연결 출처를 확인해 주세요.');res.statusCode=204;res.end();return {preflight:true};}
 const bearer=(req.headers.authorization||'').replace(/^Bearer /,'');
 let identity=verify(bearer,'session');
 if(!identity&&req.method==='GET'&&url.pathname.includes('/files/'))identity=verify(url.searchParams.get('ticket'),'media');
 if(remote||identity||url.searchParams.has('ticket')){if(!identity)throw fail(401,'로컬 연결이 만료됐어요. 내 컴퓨터 연결을 다시 진행해 주세요.');return {identity};}
 if(['cross-site','same-site'].includes(req.headers['sec-fetch-site']))throw fail(403,'로컬 연결 권한이 필요해요.');
 return {};
}
function pair(req,res){
 if(req.method!=='POST'||req.headers.host!=='127.0.0.1:8001'||req.headers.origin!==LOCAL||req.headers['x-scenesound-connect']!=='1'||req.headers['sec-fetch-site']==='cross-site')throw fail(403,'로컬 연결 화면에서 직접 연결해 주세요.');
 res.setHeader('Cache-Control','no-store');return res.json({token:session(),expiresIn:86400});
}
module.exports={authorize,pair,ticket,verify,ORIGIN,LOCAL};
