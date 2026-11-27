// Local processing service; public mode requires a Vercel-issued session and owner checks.
const fs=require('node:fs/promises');
const fss=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const {randomUUID}=require('node:crypto');
const {spawn,spawnSync}=require('node:child_process');
const root=path.join(__dirname,'..');
const auth=require('../lib/studio-auth.cjs');
const chunkUpload=require('./file-upload.cjs');
const storage=require('./storage.cjs');
const bridge=require('./local-bridge.cjs');
const {validateChannels,applyEdits}=require('./editor-model.js');
const publicMode=process.env.STUDIO_PUBLIC==='1';
const maxDuration=1800,maxBytes=(publicMode?1:8)*1024**3;
// This deployment was evicted when its /tmp volume exceeded 2 GB. Leave headroom.
const storageBudget=publicMode?Math.floor(1.5*1024**3):0;
const allowedOrigin=process.env.STUDIO_ALLOWED_ORIGIN||'https://scenesound-mvp.vercel.app';
const jobs=new Map();let active=false;
const scratch=process.env.STUDIO_DATA_DIR||path.join(os.tmpdir(),'scenesound-studio');
const python=process.env.STUDIO_PYTHON||path.join(root,'.venv-studio','bin','python');
const lifetime=24*60*60*1000;
let automaticFiltersReady;
function automaticReady(){if(automaticFiltersReady===undefined){try{const result=spawnSync('ffmpeg',['-hide_banner','-filters'],{encoding:'utf8',timeout:15000,maxBuffer:1024*1024});automaticFiltersReady=result.status===0&&['adeclip ','afftdn ','alimiter '].every(x=>result.stdout.includes(x));}catch{automaticFiltersReady=false;}}return automaticFiltersReady&&fss.existsSync(python)&&fss.existsSync(process.env.STUDIO_VAD_MODEL||path.join(root,'.venv-studio/models/silero_vad_v5.1.2.onnx'));}
function validateAutomatic(manifest,body){if(!body||typeof body!=='object'||Array.isArray(body))throw fail(400,'자동 정리 설정을 확인해 주세요.');if(manifest.workflow!=='automatic')throw fail(400,'자동 정리 전용 화면에서 파일을 가져와 주세요.');const strength=body.strength===undefined?'standard':body.strength;if(!['gentle','standard'].includes(strength))throw fail(400,'정리 강도를 확인해 주세요.');return {strength};}

const ready=fs.mkdir(scratch,{recursive:true,mode:0o700}).then(async()=>{
 const entries=(await fs.readdir(scratch,{withFileTypes:true})).filter(e=>e.isDirectory()&&/^job-[0-9a-f-]{36}$/.test(e.name));
 for(const e of entries){const dir=path.join(scratch,e.name),stat=await fs.stat(dir);if(Date.now()-stat.mtimeMs>lifetime){await fs.rm(dir,{recursive:true,force:true});continue;}
  try{const uploads=JSON.parse(await fs.readFile(path.join(dir,'uploads.json'),'utf8'));const id=e.name.slice(4),job={id,dir,uploads,bytes:0,created:stat.mtimeMs,status:'uploading'};
   for(const u of uploads)job.bytes+=(await fs.stat(path.join(dir,u.file))).size;
   try{job.manifest=JSON.parse(await fs.readFile(path.join(dir,'manifest.json'),'utf8'));job.data=job.manifest;job.status='ready';}catch{}
   job.dialogueReady=fss.existsSync(path.join(dir,'dialogue-approved.wav'));
   if(job.dialogueReady)try{job.dialogueData=JSON.parse(await fs.readFile(path.join(dir,'dialogue-approved.json'),'utf8'));}catch{}
   try{job.settings=JSON.parse(await fs.readFile(path.join(dir,'settings.json'),'utf8'));}catch{}
   const renders=[];for(const name of await fs.readdir(dir))if(/^render-[0-9a-f]{32}$/.test(name))try{const data=JSON.parse(await fs.readFile(path.join(dir,name,'result.json'),'utf8'));renders.push({data,time:(await fs.stat(path.join(dir,name))).mtimeMs});}catch{}
   renders.sort((a,b)=>b.time-a.time);if(renders[0]){job.data=renders[0].data;job.status='ready';job.settings={...job.settings,assets:job.data.assets,warnings:job.data.warnings,summary:job.data.summary};}
   {try{job.owner=JSON.parse(await fs.readFile(path.join(dir,'owner.json'),'utf8')).sid;}catch{if(publicMode)continue;}}
   jobs.set(id,job);
  }catch{}
 }
});
function uploadLimit(role){return Math.min(maxBytes,role==='aaf'?5*1024**3:role==='video'?2*1024**3:1024**3);}
function fail(status,message){return Object.assign(Error(message),{status});}
async function json(req){let size=0,chunks=[];for await(const c of req){size+=c.length;if(size>128*1024)throw fail(413,'작업 설정이 너무 커요.');chunks.push(c);}try{return size?JSON.parse(Buffer.concat(chunks)):{};}catch{throw fail(400,'작업 설정을 확인해 주세요.');}}
function run(action,job){return new Promise((resolve,reject)=>{
 const child=spawn(python,[path.join(__dirname,'engine.py'),action,job.dir],{stdio:['ignore','pipe','pipe'],env:{...process.env,STUDIO_STORAGE_BUDGET_BYTES:String(storageBudget)}});job.child=child;let data='',errors='',storageError,checking=false;
 const timer=setTimeout(()=>child.kill('SIGKILL'),120*60*1000);
 const monitor=storageBudget?setInterval(async()=>{if(checking)return;checking=true;try{await storage.check(scratch,0,storageBudget);}catch(e){storageError=e;console.warn(JSON.stringify({event:'storage_budget_stop',action,budgetBytes:storageBudget}));child.kill('SIGKILL');}finally{checking=false;}},500):null;
 function clear(){clearTimeout(timer);if(monitor)clearInterval(monitor);job.child=null;}
 child.stdout.on('data',c=>{data+=c;if(data.length>2e6)child.kill('SIGKILL');});child.stderr.on('data',c=>{errors=(errors+c).slice(-1000);});
 child.once('error',()=>{clear();reject(Error('처리 엔진을 시작하지 못했어요. Python 환경과 FFmpeg를 확인해 주세요.'));});
 child.once('close',code=>{clear();if(storageError)return reject(storageError);try{const output=JSON.parse(data);if(code||output.error)reject(Error(output.error||'처리를 완료하지 못했어요.'));else resolve(output);}catch{reject(Error('처리 엔진이 중단됐어요. 지원 형식이나 파일 크기를 확인해 주세요.'));}});
 });}

async function renderJob(job,action='render'){
 let result;
 try{result=await run(action,job);return result;}finally{
  const keep=new Set([result?.renderDirectory||job.data?.renderDirectory,...(action==='dialogue'&&result?[]:[job.dialogueData?.renderDirectory])].filter(Boolean));
  for(const name of await fs.readdir(job.dir))if(/^render-[0-9a-f]{32}$/.test(name)&&!keep.has(name))await fs.rm(path.join(job.dir,name),{recursive:true,force:true});
 }
}
async function mutate(job,fn){if(active)throw fail(409,'다른 작업을 처리 중이에요. 완료 후 다시 눌러 주세요.');active=true;job.busy=true;job.error=null;job.status='processing';Promise.resolve().then(async()=>{await fs.rm(path.join(job.dir,'progress.json'),{force:true});return fn();}).then(data=>{job.data=data;job.status='ready';}).catch(e=>{job.error=e.message;job.status='error';}).finally(()=>{job.busy=false;active=false;});}
function validatePlan(plan,duration){if(!plan||!Array.isArray(plan.sounds)||plan.sounds.length>60)throw fail(400,'영상 분석 결과를 확인해 주세요.');return plan.sounds.filter(s=>s.type!=='편집 팁').map(s=>{if(!['효과음','배경음'].includes(s.type)||typeof s.title!=='string'||s.title.length>200||typeof s.searchQuery!=='string'||!s.searchQuery.trim()||s.searchQuery.length>100||!Number.isFinite(s.start)||!Number.isFinite(s.end)||s.start<0||s.end<s.start||s.end>duration)throw fail(400,'추천 소리의 위치와 검색어를 확인해 주세요.');return{title:s.title,query:s.searchQuery,start:s.start,end:Math.min(duration,Math.max(s.end,s.start+.25)),role:s.type==='효과음'?'effect':'ambience'};}).filter(s=>s.start<s.end);}
async function searchSound(query,page=1){
 const url='https://scenesound-mvp.vercel.app/api/sounds?provider=all&q='+encodeURIComponent(query)+'&page='+page;
 const response=await fetch(url,{signal:AbortSignal.timeout(25000)});if(!response.ok)throw Error('라이브러리를 검색하지 못했어요.');
 const data=await response.json();return(data.candidates||[]).filter(c=>['freesound','commons'].includes(c.provider)&&Number.isFinite(c.duration)&&c.duration>0&&typeof c.preview==='string'&&(c.license==='CC0'||c.license==='퍼블릭 도메인'||/^CC BY [34]\.0/.test(c.license)));
}
async function download(url,destination){
 const u=new URL(url);if(u.protocol!=='https:'||u.username||u.password||!['cdn.freesound.org','freesound.org','upload.wikimedia.org'].includes(u.hostname))throw Error('허용되지 않은 음원 주소예요.');
 const r=await fetch(u,{redirect:'error',signal:AbortSignal.timeout(45000)});if(!r.ok||Number(r.headers.get('content-length'))>20*1024*1024)throw Error('음원을 내려받지 못했어요.');
 const file=await fs.open(destination,'wx',0o600);let bytes=0;try{for await(const c of r.body){bytes+=c.length;if(bytes>20*1024*1024)throw Error('음원이 너무 커요.');await file.write(c);}}finally{await file.close();}if(!bytes)throw Error('빈 음원이에요.');
}
function candidateOrder(candidates,sound){return candidates.sort((a,b)=>{const target=Math.max(.2,sound.end-sound.start);const score=c=>Math.abs(Math.log(Math.max(c.duration,.1)/target))+(sound.role==='ambience'&&c.duration<2?5:0);return score(a)-score(b);});}
async function place(job,sound,id,page=1){
 const candidates=candidateOrder((await searchSound(sound.query,page)).filter(c=>c.provider!==sound.provider||String(c.id)!==String(sound.soundId)),sound);
 for(const candidate of candidates){const file=id+'-'+randomUUID()+'.audio';try{await download(candidate.preview,path.join(job.dir,file));return{...sound,id,file,enabled:true,gain:sound.role==='effect'?-12:-20,page,name:candidate.name,creator:candidate.creator,source:candidate.source,license:candidate.license,licenseUrl:candidate.licenseUrl,library:candidate.library,provider:candidate.provider,soundId:candidate.id};}catch{await fs.rm(path.join(job.dir,file),{force:true});}}
 throw Error('다운로드할 수 있는 음원 후보가 없어요.');
}
function validateDialogueReferences(manifest,roles,scenes,chosen={}){
  if(!chosen||typeof chosen!=='object'||Array.isArray(chosen)||Object.keys(chosen).length>30)throw fail(400,'기준 클립 선택을 확인해 주세요.');
  const referenceClips={};
  for(const [index,value] of Object.entries(chosen)){
   if(!/^(0|[1-9][0-9]*)$/.test(index)||Number(index)>=scenes.length||typeof value!=='string')throw fail(400,'기준 클립의 씬을 확인해 주세요.');
   if(!value)continue;
   const parts=/^(\d+):(\d+)$/.exec(value),track=parts&&manifest.tracks.find(t=>t.slotId===Number(parts[1]));
   const clip=track?.clips.find(c=>c.componentIndex===Number(parts[2]));
   const end=scenes[Number(index)+1]?.start??manifest.duration;
   if(!clip||roles[track.id]!=='dialogue'||clip.start<scenes[Number(index)].start||clip.start+clip.duration>end+.001)throw fail(400,'기준은 해당 씬의 처리할 대사 트랙 안에서 골라 주세요.');
   referenceClips[index]=value;
  }
  return referenceClips;
}
function validateSettings(job,body){
 const roles=body.roles||{};if(job.manifest.tracks.some(t=>!['dialogue','original','ignore'].includes(roles[t.id])))throw fail(400,'모든 원본 트랙의 역할을 지정해 주세요.');
 if(!job.manifest.tracks.some(t=>roles[t.id]!=='ignore'))throw fail(400,'원본 트랙을 하나 이상 사용해 주세요.');
 let effectChannels;try{if(body.effectChannels)effectChannels=validateChannels(body.effectChannels);}catch(e){throw fail(400,e.message);}
 const gains={};for(const t of [...job.manifest.tracks,{id:'effect'},{id:'ambience'},{id:'dialogue'},...(effectChannels||[])]){const g=body.trackGains?.[t.id]??0;if(!Number.isFinite(g)||g< -60||g>6)throw fail(400,'트랙 음량을 확인해 주세요.');gains[t.id]=g;}
 if(body.useDialogue&&!job.dialogueReady)throw fail(409,'먼저 대사 정리를 완료해 주세요.');
 return{roles,clean:body.clean!==false,trackGains:gains,...(effectChannels?{effectChannels}:{}),...(body.useDialogue?{useDialogue:true}:{})};
}
async function serveFile(req,res,job,name){
 const allowed=new Set([...(job.uploads.filter(u=>u.role==='video').map(u=>u.file)),...(job.data?.analysisSegments||[]).map(s=>s.file),...(job.data?.tracks||[]).flatMap(t=>[t.file,t.export]),'mix.wav','original.wav','dialogue-approved.wav','dialogue-original.wav','dialogue-approved.json','dialogue-scenes.aaf','dialogue-package.zip','dialogue-clips.aaf','dialogue-review.csv','dialogue-report.json','analysis-reference.mp4','auto-clean.wav','auto-original.wav','auto-report.json','SceneSound.aaf','preview.mp4','credits.json','SceneSound.zip',...(job.settings?.assets||[]).map(a=>a.file)]);
 if(!allowed.has(name)||name!==path.basename(name)||job.busy)throw fail(404,'파일을 찾을 수 없거나 처리 중이에요.');
 const upload=(job.settings?.assets||[]).some(a=>a.file===name)||(job.data?.analysisSegments||[]).some(s=>s.file===name)||['dialogue-approved.wav','dialogue-original.wav','dialogue-approved.json','dialogue-scenes.aaf','dialogue-package.zip','analysis-reference.mp4'].includes(name)||job.uploads.some(u=>u.role==='video'&&u.file===name);const renderDirectory=['dialogue-clips.aaf','dialogue-review.csv','dialogue-report.json'].includes(name)?job.dialogueData?.renderDirectory||job.data?.renderDirectory:job.data?.renderDirectory;const p=path.join(job.dir,...(!upload&&renderDirectory?[renderDirectory]:[]),name);const stat=await fs.stat(p);let start=0,end=stat.size-1;
 if(req.headers.range){const m=/^bytes=(\d+)-(\d*)$/.exec(req.headers.range);if(!m)throw fail(416,'재생 범위를 확인해 주세요.');start=Number(m[1]);end=m[2]?Math.min(Number(m[2]),end):end;if(start>end||start>=stat.size)throw fail(416,'재생 범위를 확인해 주세요.');res.statusCode=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${stat.size}`);}
 let audioType='application/octet-stream';if(name.endsWith('.audio')){const h=await fs.open(p,'r');try{const b=Buffer.alloc(16);await h.read(b,0,16,0);audioType=b.toString('ascii',0,4)==='RIFF'?'audio/wav':b.toString('ascii',0,4)==='OggS'?'audio/ogg':b.toString('ascii',0,4)==='fLaC'?'audio/flac':b.toString('ascii',4,8)==='ftyp'?'audio/mp4':'audio/mpeg';}finally{await h.close();}}
 res.setHeader('Accept-Ranges','bytes');res.setHeader('Content-Length',end-start+1);res.setHeader('Content-Type',name.endsWith('.wav')?'audio/wav':/\.(mp4|mov|webm)$/.test(name)?(name.endsWith('.webm')?'video/webm':'video/mp4'):name.endsWith('.json')?'application/json':name.endsWith('.csv')?'text/csv; charset=utf-8':audioType);if(/\.(zip|aaf|csv)$/.test(name)||new URL(req.url,'http://worker').searchParams.get('download')==='1')res.setHeader('Content-Disposition',`attachment; filename="${name}"`);fss.createReadStream(p,{start,end}).pipe(res);
}
module.exports=async(req,res)=>{
 try{
 await ready;res.setHeader('Cache-Control','no-store');res.setHeader('Referrer-Policy','no-referrer');res.setHeader('X-Content-Type-Options','nosniff');
 const url=new URL(req.url,'http://127.0.0.1');
 let identity;
 if(publicMode){
  const origin=req.headers.origin;
  if(origin&&origin!==allowedOrigin)throw fail(403,'허용되지 않은 요청이에요.');
  if(origin===allowedOrigin){res.setHeader('Access-Control-Allow-Origin',allowedOrigin);res.setHeader('Vary','Origin');res.setHeader('Access-Control-Allow-Headers','Authorization,Content-Type,Range');res.setHeader('Access-Control-Allow-Methods','GET,POST,DELETE,OPTIONS');res.setHeader('Access-Control-Expose-Headers','Content-Range,Content-Length,Accept-Ranges');}
  if(req.method==='OPTIONS'){res.statusCode=204;return res.end();}
  if(url.pathname==='/api/studio/status'&&req.method==='GET')return res.json({ready:fss.existsSync(python),local:false,maxDuration,maxBytes,automaticVersion:1,automaticReady:automaticReady(),dialogueVersion:5,referenceFirst:true,equalGainFades:true,preserveAaf:true,speechModelReady:fss.existsSync(process.env.STUDIO_VAD_MODEL||path.join(root,'.venv-studio/models/silero_vad_v5.1.2.onnx')),editorVersion:1,uploadVersion:1,storageBudgetBytes:storageBudget,maxAafBytes:uploadLimit('aaf')});
  const token=(req.headers.authorization||'').replace(/^Bearer /,'');identity=auth.verify(token,'session');
  if(!identity&&req.method==='GET'&&url.pathname.includes('/files/'))identity=auth.verify(url.searchParams.get('ticket'),'media');
  if(!identity)throw fail(401,'작업 권한이 만료됐어요. 화면을 다시 열어 주세요.');
 }else{
  const access=bridge.authorize(req,res,url);if(access.preflight)return;identity=access.identity;
  if(url.pathname==='/api/studio/status'&&req.method==='GET')return res.json({ready:fss.existsSync(python),local:true,maxDuration,maxBytes,automaticVersion:1,automaticReady:automaticReady(),dialogueVersion:5,referenceFirst:true,equalGainFades:true,preserveAaf:true,speechModelReady:fss.existsSync(process.env.STUDIO_VAD_MODEL||path.join(root,'.venv-studio/models/silero_vad_v5.1.2.onnx')),editorVersion:1,uploadVersion:1,storageBudgetBytes:storageBudget,maxAafBytes:uploadLimit('aaf')});
 }
 if(url.pathname==='/api/studio/jobs'&&req.method==='POST'){
  for(const [id,j]of jobs)if(!j.busy&&Date.now()-j.created>lifetime){await fs.rm(j.dir,{recursive:true,force:true});jobs.delete(id);}
  if(publicMode&&[...jobs.values()].filter(j=>j.owner===identity.sid).length>=2)throw fail(429,'한 브라우저에서 작업 두 개까지 만들 수 있어요. 이전 작업을 지워 주세요.');
  if(jobs.size>=4)throw fail(429,'진행 중인 작업을 삭제한 뒤 새로 시작해 주세요.');
  await storage.check(scratch,0,storageBudget);const disk=await fs.statfs(scratch);if(disk.bavail*disk.bsize<(publicMode?512*1024**2:3*1024**3))throw fail(507,'로컬 디스크에 3GB 이상의 빈 공간이 필요해요.');
  const id=randomUUID(),dir=path.join(scratch,'job-'+id);await fs.mkdir(dir,{mode:0o700});const job={id,dir,uploads:[],bytes:0,created:Date.now(),status:'uploading',owner:identity?.sid};if(identity)await fs.writeFile(path.join(dir,'owner.json'),JSON.stringify({sid:identity.sid}));jobs.set(id,job);return res.json({id});
 }
 const match=/^\/api\/studio\/jobs\/([0-9a-f-]{36})(?:\/(.*))?$/.exec(url.pathname);if(!match)throw fail(404,'작업을 찾을 수 없어요.');const job=jobs.get(match[1]);if(!job)throw fail(404,'작업이 만료됐어요. 파일을 다시 선택해 주세요.');if((publicMode||identity)&&(job.owner!==identity.sid||(identity.kind==='media'&&identity.jid!==job.id)))throw fail(403,'이 작업에 접근할 수 없어요.');const action=match[2]||'';
 if(req.method==='GET'&&!action){let stage=job.stage;if(job.busy)try{stage=JSON.parse(await fs.readFile(path.join(job.dir,'progress.json'),'utf8')).stage||stage;}catch{}return res.json({...(identity?{ticket:publicMode?auth.ticket(identity.sid,job.id):bridge.ticket(identity.sid,job.id)}:{}),id:job.id,status:job.status,error:job.error,data:job.data,manifest:job.manifest,dialogueReady:!!job.dialogueReady,dialogue:job.dialogueData,settings:job.settings?{strength:job.settings.strength,roles:job.settings.roles,clean:job.settings.clean,deduplicate:job.settings.deduplicate,removeSilence:job.settings.removeSilence,scenes:job.settings.scenes,referenceClips:job.settings.referenceClips,fades:job.settings.fades,useDialogue:job.settings.useDialogue}:undefined,stage});}
 if(req.method==='GET'&&action.startsWith('files/'))return await serveFile(req,res,job,action.slice(6));
 if(req.method==='DELETE'&&!action){if(job.busy||job.uploading)throw fail(409,'전송·처리 완료 후 삭제해 주세요.');await fs.rm(job.dir,{recursive:true,force:true});jobs.delete(job.id);return res.json({deleted:true});}
 if(action==='uploads'||action.startsWith('uploads/'))return await chunkUpload.handle(req,res,job,action,url,{json,uploadLimit,maxBytes,checkStorage:additional=>storage.check(scratch,additional,storageBudget)});
 if(req.method!=='POST')throw fail(405,'지원하지 않는 요청이에요.');
 if(job.busy||job.uploading)throw fail(409,'현재 작업이 끝난 뒤 다시 눌러 주세요.');
 if(action==='files'){if([...job.transfers?.values()||[]].some(t=>!t.done))throw fail(409,'진행 중인 조각 전송을 먼저 끝내 주세요.');
  const role=url.searchParams.get('role'),name=(url.searchParams.get('name')||'').normalize('NFC');const ext=path.extname(name).toLowerCase();
  if(job.manifest&&!(role==='video'&&!job.manifest.video))throw fail(409,'이미 읽은 프로젝트예요. 새 작업으로 시작해 주세요.');
  const extensions={aaf:['.aaf'],video:['.mp4','.mov','.webm'],audio:['.wav','.aif','.aiff','.mp3','.m4a']};
  if(!extensions[role]?.includes(ext)||name.length>250||/[\x00-\x1f/\\]/.test(name)||job.uploads.length>=64)throw fail(400,'파일 이름과 형식·개수를 확인해 주세요.');
  if(role!=='audio'&&job.uploads.some(u=>u.role===role))throw fail(400,'AAF와 참조 영상은 각각 하나만 넣어 주세요.');
  const declared=Number(req.headers['content-length']);if(Number.isFinite(declared)&&(declared>uploadLimit(role)||declared+job.bytes>maxBytes))throw fail(413,'파일 용량 제한을 초과했어요. 영상 2GB·AAF 5GB·오디오 1GB·전체 8GB 이내로 골라 주세요.');
  await storage.check(scratch,Number.isFinite(declared)?declared:0,storageBudget);job.uploading=true;const file=randomUUID()+ext,handle=await fs.open(path.join(job.dir,file),'wx',0o600);let bytes=0;
  try{for await(const c of req){await storage.check(scratch,c.length,storageBudget);bytes+=c.length;if(bytes>uploadLimit(role)||job.bytes+bytes>maxBytes)throw fail(413,publicMode?'영상 2GB·AAF 5GB·오디오 1GB·전체 8GB 이하여야 해요.':'영상 2GB·AAF 5GB·오디오 1GB·전체 8GB 이하여야 해요.');await handle.write(c);}}catch(e){await fs.rm(path.join(job.dir,file),{force:true});throw e;}finally{await handle.close();job.uploading=false;}
  job.bytes+=bytes;job.uploads.push({role,name,file});await fs.writeFile(path.join(job.dir,'uploads.json'),JSON.stringify(job.uploads));return res.json({uploaded:true});
 }
 if(action==='inspect'){const inspectBody=await json(req);if([...job.transfers?.values()||[]].some(t=>!t.done))throw fail(409,'파일 전송이 끝난 뒤 분석해 주세요.');await mutate(job,async()=>{job.stage='AAF의 트랙·클립·연결 오디오를 읽고 있어요.';if(job.manifest&&job.manifest.workflow==='automatic'&&inspectBody.workflow!=='automatic')throw fail(400,'기존 자동 정리를 보존하려면 새 작업으로 시작해 주세요.');job.manifest=await run(inspectBody.workflow==='automatic'?'inspect-automatic':inspectBody.workflow==='dialogue'?'inspect-dialogue':'inspect',job);return job.manifest;});return res.status(202).json({started:true});}
 if(!job.manifest)throw fail(409,'먼저 AAF를 읽어 주세요.');
 if(action==='attach-video'){await mutate(job,async()=>{job.stage='참조 영상을 연결하고 있어요.';job.manifest=await run('attach-video',job);return job.manifest;});return res.status(202).json({started:true});}
 const body=await json(req);
 if(action==='automatic'){const config=validateAutomatic(job.manifest,body);if(!automaticReady())throw fail(503,'자동 클리닝 서버를 준비하고 있어요. 잠시 후 다시 시도해 주세요.');await mutate(job,async()=>{job.stage='자동 대사 정리를 시작하고 있어요.';job.settings=config;await fs.writeFile(path.join(job.dir,'settings.json'),JSON.stringify(config));return await renderJob(job,'automatic');});return res.status(202).json({started:true});}
 if(action==='dialogue'){
  if(job.manifest.workflow==='automatic')throw fail(400,'원본 AAF 편집은 별도 대사 편집 화면에서 새 작업으로 시작해 주세요.');
  const config=validateSettings(job,body);if(!Object.values(config.roles).includes('dialogue'))throw fail(400,'대사 트랙을 하나 이상 선택해 주세요.');
  const scenes=body.scenes||[{start:0,title:'씬 1'}];if(!Array.isArray(scenes)||scenes.length<1||scenes.length>30||scenes.some((s,i)=>!s||!Number.isFinite(s.start)||s.start<0||s.start>=job.manifest.duration||(i===0?s.start!==0:s.start<=scenes[i-1].start)||typeof s.title!=='string'||!s.title.trim()||s.title.length>100))throw fail(400,'씬 시작 시간과 이름을 확인해 주세요. 첫 씬은 0초, 이후는 시간순이어야 해요.');
  const referenceClips=validateDialogueReferences(job.manifest,config.roles,scenes,body.referenceClips??{});
  if(body.fades!==undefined&&typeof body.fades!=='boolean')throw fail(400,'페이드 설정을 확인해 주세요.');
  await mutate(job,async()=>{job.stage='기준 대사를 먼저 맞추고 룸톤·페이드를 정리하고 있어요.';job.settings={...config,deduplicate:body.deduplicate!==false,removeSilence:body.removeSilence!==false,clean:false,scenes,referenceClips,fades:body.fades!==false,assets:[]};await fs.writeFile(path.join(job.dir,'settings.json'),JSON.stringify(job.settings));const result=await renderJob(job,'dialogue');job.dialogueReady=true;job.dialogueData=result;return result;});return res.status(202).json({started:true});
 }
 if(action==='prepare-analysis'){const config=validateSettings(job,body);await mutate(job,async()=>{job.stage='선택한 AAF 트랙을 참조 영상에 맞춰 분석용 영상을 만들고 있어요.';await fs.writeFile(path.join(job.dir,'settings.json'),JSON.stringify(config));return await run('prepare',job);});return res.status(202).json({started:true});}
 if(action==='render'){
  const config=validateSettings(job,body),plan=validatePlan(body.plan,Math.min(maxDuration,job.manifest.duration));
  await mutate(job,async()=>{const assets=[],warnings=[];for(const [i,sound]of plan.entries()){job.stage=`소리 자동 선택 중 · ${i+1}/${plan.length}`;try{assets.push(await place(job,sound,'s'+i));}catch{warnings.push(sound.title+': 후보를 가져오지 못해 배치하지 않았어요.');}}
   job.settings={...config,assets,warnings,summary:String(body.plan.summary||'').slice(0,1500)};await fs.writeFile(path.join(job.dir,'settings.json'),JSON.stringify(job.settings));job.stage='대사를 보정하고 사운드·미리보기·AAF를 렌더링하고 있어요.';return await renderJob(job);});return res.status(202).json({started:true});
 }
 if(action==='remix'){
  if(!job.settings)throw fail(409,'먼저 초안을 만들어 주세요.');const config=validateSettings(job,body);const edits=body.edits||[];if(!Array.isArray(edits)||edits.length>60)throw fail(400,'수정할 소리를 확인해 주세요.');
  let assets;try{assets=applyEdits(job.settings.assets,edits,config.effectChannels||[{id:'effect',role:'effect'},{id:'ambience',role:'ambience'}],job.manifest.duration);}catch(e){throw fail(400,e.message);}
  await mutate(job,async()=>{job.stage='수정한 음량과 위치로 다시 렌더링하고 있어요.';if(body.replace){const index=assets.findIndex(a=>a.id===body.replace);if(index<0)throw Error('교체할 소리를 찾지 못했어요.');const previous=assets[index];const next=await place(job,previous,previous.id,(previous.page||1)+1);assets[index]={...next,start:previous.start,end:previous.end,gain:previous.gain,enabled:previous.enabled,channelId:previous.channelId};}job.settings={...job.settings,...config,assets};await fs.writeFile(path.join(job.dir,'settings.json'),JSON.stringify(job.settings));return await renderJob(job);});return res.status(202).json({started:true});
 }
 throw fail(404,'작업을 찾을 수 없어요.');
 }catch(e){if(!res.headersSent)res.status(e.status||500).json({error:e.status?e.message:'로컬 작업을 진행하지 못했어요. 처리 엔진과 파일 형식을 확인해 주세요.'});else res.destroy();}
};
module.exports.validatePlan=validatePlan;
module.exports.validateDialogueReferences=validateDialogueReferences;
module.exports.validateAutomatic=validateAutomatic;
module.exports.uploadLimit=uploadLimit;
if(publicMode)setInterval(async()=>{await ready;for(const [id,j]of jobs)if(!j.busy&&!j.uploading&&Date.now()-j.created>lifetime){await fs.rm(j.dir,{recursive:true,force:true}).catch(()=>{});jobs.delete(id);}},60000).unref();
