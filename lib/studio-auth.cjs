const {createHmac,timingSafeEqual,randomUUID}=require('node:crypto');
const TTL=2*60*60;
function key(){const k=process.env.STUDIO_WORKER_SECRET;if(!k||k.length<32)throw Error('Missing studio secret');return k;}
function sign(payload){const body=Buffer.from(JSON.stringify(payload)).toString('base64url');return body+'.'+createHmac('sha256',key()).update('studio-v1:'+body).digest('base64url');}
function verify(token,kind){try{if(typeof token!=='string'||token.length>2048)return null;const [body,sig,extra]=token.split('.');if(extra||!body||!sig)return null;const a=Buffer.from(sig,'base64url'),b=createHmac('sha256',key()).update('studio-v1:'+body).digest();if(a.length!==b.length||!timingSafeEqual(a,b))return null;const data=JSON.parse(Buffer.from(body,'base64url'));if(data.kind!==kind||!Number.isSafeInteger(data.exp)||data.exp<=Math.floor(Date.now()/1000)||typeof data.sid!=='string'||!/^[0-9a-f-]{36}$/.test(data.sid))return null;return data;}catch{return null;}}
function session(sid=randomUUID()){return sign({kind:'session',sid,exp:Math.floor(Date.now()/1000)+TTL});}
function ticket(sid,jid){return sign({kind:'media',sid,jid,exp:Math.floor(Date.now()/1000)+3600});}
module.exports={sign,verify,session,ticket};
