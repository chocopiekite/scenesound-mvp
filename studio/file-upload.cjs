// Bounded, owner-scoped uploads. The parent handler authenticates every request.
const fs=require('node:fs/promises');
const path=require('node:path');
const {randomUUID}=require('node:crypto');
const CHUNK_BYTES=8*1024**2;
const RESERVE=1024**3;
const fail=(status,message)=>Object.assign(Error(message),{status});
async function space(dir,bytes){const s=await fs.statfs(dir);if(s.bavail*s.bsize<bytes+RESERVE)throw fail(507,'작업 서버의 임시 공간이 부족해요. 이전 작업을 정리한 뒤 다시 시도해 주세요. 계속되면 서버 임시 공간을 더 확보해야 해요.');}
async function handle(req,res,job,action,url,{json,uploadLimit,maxBytes,checkStorage=async()=>{}}){
 job.transfers??=new Map();
 if(action==='uploads'&&req.method==='POST'){
  if(job.uploading||job.busy)throw fail(409,'현재 전송이나 처리가 끝난 뒤 다시 시도해 주세요.');
  job.uploading=true;try{
  const b=await json(req),name=typeof b.name==='string'?b.name.normalize('NFC'):'',ext=path.extname(name).toLowerCase(),role=b.role;
  if(!{aaf:['.aaf'],video:['.mp4','.mov','.webm'],audio:['.wav','.aif','.aiff','.mp3','.m4a']}[role]?.includes(ext)||!name||name.length>250||/[\x00-\x1f/\\]/.test(name))throw fail(400,'파일 이름과 형식을 확인해 주세요.');
  if(job.manifest&&!(role==='video'&&!job.manifest.video))throw fail(409,'새 AAF는 새 작업에서 올려 주세요.');
  if([...job.transfers.values()].some(t=>!t.done))throw fail(409,'진행 중인 파일 전송을 먼저 끝내 주세요.');
  if(job.uploads.length>=64||role!=='audio'&&job.uploads.some(u=>u.role===role))throw fail(400,'파일 개수와 중복 파일을 확인해 주세요.');
  if(!Number.isSafeInteger(b.size)||b.size<1||b.size>uploadLimit(role)||job.bytes+b.size>maxBytes)throw fail(413,'현재 서버의 파일·전체 용량 한도를 넘었어요. 공개 서버는 합계 1GB까지 받고, 3~4GB AAF는 로컬 대사 도구를 이용해 주세요.');
  await checkStorage(b.size);await space(job.dir,b.size);
  const id=randomUUID(),file=id+ext;await fs.writeFile(path.join(job.dir,file),'',{flag:'wx',mode:0o600});
  job.transfers.set(id,{id,file,name,role,size:b.size,offset:0,done:false});
  return res.json({id,offset:0,chunkBytes:CHUNK_BYTES});
  }finally{job.uploading=false;}
 }
 const match=/^uploads\/([0-9a-f-]{36})$/.exec(action),t=match&&job.transfers.get(match[1]);
 if(!t)throw fail(404,'전송 세션이 만료됐어요. 파일을 다시 올려 주세요.');
 if(req.method==='GET')return res.json({offset:t.offset,done:t.done,size:t.size});
 if(req.method!=='POST')throw fail(405,'지원하지 않는 전송 방식이에요.');
 if(job.uploading||job.busy)throw fail(409,'현재 전송이나 처리가 끝난 뒤 다시 시도해 주세요.');
 const offset=Number(url.searchParams.get('offset'));
 if(!url.searchParams.has('offset')||!Number.isSafeInteger(offset)||offset!==t.offset||t.done)throw fail(409,'전송 위치를 다시 확인해 주세요.');
 const declared=Number(req.headers['content-length']);
 if(Number.isFinite(declared)&&(declared<1||declared>CHUNK_BYTES||declared>t.size-offset))throw fail(413,'파일 조각은 8MB 이하여야 해요.');
 job.uploading=true;let count=0,h;
 try{await checkStorage(Math.min(CHUNK_BYTES,t.size-offset));await space(job.dir,Math.min(CHUNK_BYTES,t.size-offset));h=await fs.open(path.join(job.dir,t.file),'r+');
  for await(const chunk of req){count+=chunk.length;if(count>CHUNK_BYTES||offset+count>t.size||job.bytes+count>maxBytes)throw fail(413,'파일 조각 용량을 초과했어요.');let written=0;while(written<chunk.length){const r=await h.write(chunk,written,chunk.length-written,offset+count-chunk.length+written);if(!r.bytesWritten)throw Error('File write interrupted');written+=r.bytesWritten;}}
  if(!count)throw fail(400,'빈 파일 조각이에요.');
  if(offset+count===t.size){job.uploads.push({role:t.role,name:t.name,file:t.file});try{await fs.writeFile(path.join(job.dir,'uploads.json'),JSON.stringify(job.uploads));}catch(e){job.uploads.pop();throw e;}t.done=true;}
  t.offset+=count;job.bytes+=count;
 }catch(e){if(h)await h.truncate(offset);throw e;}finally{if(h)await h.close();job.uploading=false;}
 return res.json({offset:t.offset,done:t.done,size:t.size});
}
module.exports={handle,CHUNK_BYTES};
