const {createHmac,randomUUID}=require('node:crypto');
const {MAX_BYTES,MAX_DURATION,sign,verify,provider}=require('../lib/video-session.cjs');
function relayUrls(urls,session,headers){
 return (urls||[]).map(entry=>{
  const target=new URL(entry.url);if(target.protocol!=='https:'||target.hostname!=='tl-api-assets-prod.s3.us-west-2.amazonaws.com')throw new Error('Unexpected upload destination');
  const payload=Buffer.from(JSON.stringify({url:entry.url,headers,size:Math.min(session.chunkSize,session.size-(entry.chunk_index-1)*session.chunkSize),exp:Date.now()+3600000})).toString('base64url');
  const proof=createHmac('sha256',process.env.VIDEO_UPLOAD_RELAY_SECRET).update(payload).digest('base64url');
  return {chunk_index:entry.chunk_index,url:'https://tyunlhiyvaakxkrubuku.supabase.co/functions/v1/video-upload',permit:payload+'.'+proof};
 });
}
module.exports=async(req,res)=>{
  res.setHeader('Cache-Control','no-store');
  const reply=(code,data)=>res.status(code).json(data);
  if(req.method!=='POST')return reply(405,{error:'지원하지 않는 요청이에요.'});
  if(!process.env.TWELVELABS_API_KEY||!process.env.VIDEO_UPLOAD_RELAY_SECRET)return reply(503,{error:'영상 분석 연결을 준비 중이에요.'});
  try{
    const b=typeof req.body==='string'?JSON.parse(req.body):req.body||{};
    if(b.action==='create'){
      if(!Number.isSafeInteger(b.size)||b.size<1||b.size>MAX_BYTES||!Number.isFinite(b.duration)||b.duration<1||b.duration>MAX_DURATION||!['video/mp4','video/webm','video/quicktime'].includes(b.mimeType))return reply(400,{error:'10분 이내 · 200MB 이하의 MP4, WebM, MOV 영상을 선택해 주세요.'});
      const extension={'video/mp4':'mp4','video/webm':'webm','video/quicktime':'mov'}[b.mimeType];
      const data=await provider('/assets/multipart-uploads','POST',{filename:randomUUID()+'.'+extension,type:'video',total_size:b.size,enable_hls:false,enable_thumbnail:false});
      if(!data.asset_id||!data.upload_id||!Number.isSafeInteger(data.chunk_size)||data.chunk_size<1||data.total_chunks!==Math.ceil(b.size/data.chunk_size))throw new Error('업로드 준비 결과를 확인하지 못했어요.');
      const token=sign({headers:data.upload_headers||{},asset:data.asset_id,upload:data.upload_id,size:b.size,duration:b.duration,chunkSize:data.chunk_size,total:data.total_chunks});
      return reply(200,{token,chunkSize:data.chunk_size,totalChunks:data.total_chunks,urls:relayUrls(data.upload_urls,{chunkSize:data.chunk_size,size:b.size},data.upload_headers||{}),headers:{}});
    }
    const session=verify(b.token||'');if(!session)return reply(403,{error:'업로드 확인 시간이 만료됐어요. 영상을 다시 선택해 주세요.'});
    if(b.action==='urls'){
      if(!Number.isSafeInteger(b.index)||b.index<1||b.index>session.total)return reply(400,{error:'업로드 순서를 확인해 주세요.'});
      const data=await provider('/assets/multipart-uploads/'+session.upload+'/presigned-urls','POST',{start:b.index,count:1});return reply(200,{urls:relayUrls(data.upload_urls,session,session.headers)});
    }
    if(b.action==='report'){
      if(!Number.isSafeInteger(b.index)||b.index<1||b.index>session.total||typeof b.proof!=='string'||b.proof.length<1||b.proof.length>256)return reply(400,{error:'업로드 확인 정보가 올바르지 않아요.'});
      const chunk_size=Math.min(session.chunkSize,session.size-(b.index-1)*session.chunkSize);
      await provider('/assets/multipart-uploads/'+session.upload,'POST',{completed_chunks:[{chunk_index:b.index,proof:b.proof,proof_type:'etag',chunk_size}]});return reply(200,{ok:true});
    }
    if(b.action==='status'){
      const data=await provider('/assets/'+session.asset);
      if(data.status==='ready'){
        if(!Number.isFinite(data.duration)||data.duration<1||data.duration>MAX_DURATION||data.size>MAX_BYTES){await provider('/assets/'+session.asset,'DELETE');return reply(400,{error:'실제 영상이 10분 또는 200MB를 초과해요.'});}
        return reply(200,{status:'ready',analysisToken:sign({...session,duration:data.duration,ready:true})});
      }
      if(data.status==='failed')return reply(422,{error:'이 영상을 읽지 못했어요. MP4로 변환한 후 다시 시도해 주세요.'});
      return reply(200,{status:'processing'});
    }
    if(b.action==='delete'){await provider('/assets/'+session.asset,'DELETE');return reply(200,{ok:true});}
    return reply(400,{error:'요청을 확인해 주세요.'});
  }catch(error){return reply(error.status||502,{error:error.status?error.message:'영상 업로드를 처리하지 못했어요. 다시 시도해 주세요.'});}
};
