// Relays only server-authorized chunks to TwelveLabs. No database or storage writes.
const allowedOrigins=new Set(['https://scenesound-mvp.vercel.app','http://127.0.0.1:8001']);
Deno.serve(async(req:Request)=>{
  const origin=req.headers.get('origin')||'';
  const cors={'Access-Control-Allow-Origin':allowedOrigins.has(origin)?origin:'https://scenesound-mvp.vercel.app','Access-Control-Allow-Methods':'PUT, OPTIONS','Access-Control-Allow-Headers':'content-type, x-upload-permit','Access-Control-Expose-Headers':'ETag','Vary':'Origin','Cache-Control':'no-store'};
  const reply=(status:number,message:string)=>new Response(message,{status,headers:cors});
  if(origin&&!allowedOrigins.has(origin))return reply(403,'Origin not allowed');
  if(req.method==='OPTIONS')return new Response(null,{status:204,headers:cors});
  if(req.method!=='PUT')return reply(405,'Method not allowed');
  try{
    const secret=Deno.env.get('VIDEO_UPLOAD_RELAY_SECRET');if(!secret)return reply(503,'Upload unavailable');
    const [encoded,signature]=(req.headers.get('x-upload-permit')||'').split('.');
    const decode=(s:string)=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
    const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['verify']);
    if(!encoded||!signature||!await crypto.subtle.verify('HMAC',key,decode(signature),new TextEncoder().encode(encoded)))return reply(403,'Invalid upload permit');
    const permitData=JSON.parse(new TextDecoder().decode(decode(encoded)));
    const target=new URL(permitData.url);
    if(permitData.exp<Date.now()||target.protocol!=='https:'||target.hostname!=='tl-api-assets-prod.s3.us-west-2.amazonaws.com'||!Number.isSafeInteger(permitData.size)||permitData.size<1||permitData.size>32*1024*1024)return reply(403,'Invalid upload permit');
    const reader=req.body?.getReader();if(!reader)return reply(400,'Missing video chunk');
    const chunks:Uint8Array[]=[];let length=0;
    while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>permitData.size){await reader.cancel();return reply(413,'Chunk too large');}chunks.push(value);}
    if(length!==permitData.size)return reply(400,'Incomplete chunk');
    const body=new Uint8Array(length);let offset=0;for(const c of chunks){body.set(c,offset);offset+=c.length;}
    const upstream=await fetch(target,{method:'PUT',headers:permitData.headers,body,redirect:'error',signal:AbortSignal.timeout(90000)});
    if(!upstream.ok)return reply(502,'Video transfer failed');
    const etag=upstream.headers.get('etag');if(!etag)return reply(502,'Missing transfer receipt');
    return new Response(null,{status:200,headers:{...cors,ETag:etag}});
  }catch{return reply(502,'Video transfer failed');}
});
