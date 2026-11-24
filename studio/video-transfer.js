async function uploadRequest(body){const response=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});const data=await response.json();if(!response.ok)throw Error(data.error||'영상 전송을 진행하지 못했어요.');return data;}
function putChunk(url,headers,chunk,onProgress){return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();xhr.open('PUT',url);xhr.timeout=180000;
  Object.entries(headers).forEach(([key,value])=>xhr.setRequestHeader(key,value));
  xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(e.loaded);};
  xhr.onload=()=>{const etag=xhr.getResponseHeader('ETag');if(xhr.status>=200&&xhr.status<300&&etag)resolve(etag.replaceAll('"',''));else reject(new Error('영상 전송을 확인하지 못했어요. 다시 시도해 주세요.'));};
  xhr.onerror=()=>reject(new Error('영상 전송 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.'));
  xhr.ontimeout=()=>reject(new Error('영상 전송 시간이 초과됐어요. 더 작은 파일이나 안정적인 연결로 다시 시도해 주세요.'));xhr.send(chunk);
});}
async function uploadVideo(file,duration){
  const session=await uploadRequest({action:'create',size:file.size,duration,mimeType:({'video/mp4':'video/mp4','video/webm':'video/webm','video/quicktime':'video/quicktime'}[file.type]||(/\.mov$/i.test(file.name)?'video/quicktime':'video/mp4'))});
  activeUpload=session.token;
  try{sessionStorage.setItem('scenesound-pending-upload',activeUpload);}catch{}
  for(let index=1;index<=session.totalChunks;index++){
    let entry=session.urls?.find(u=>u.chunk_index===index);
    if(!entry)entry=(await uploadRequest({action:'urls',token:activeUpload,index})).urls?.[0];
    if(!entry?.url)throw new Error('영상 전송 주소를 확인하지 못했어요.');
    const offset=(index-1)*session.chunkSize,chunk=file.slice(offset,Math.min(file.size,offset+session.chunkSize));
    let proof;
    for(let attempt=0;attempt<2;attempt++){
      try{proof=await putChunk(entry.url,{...session.headers,'x-upload-permit':entry.permit},chunk,loaded=>{$('analysis-status').textContent='영상 업로드 중 · '+Math.min(100,Math.round((offset+loaded)/file.size*100))+'%';});break;}
      catch(error){if(attempt===1)throw error;entry=(await uploadRequest({action:'urls',token:activeUpload,index})).urls[0];}
    }
    await uploadRequest({action:'report',token:activeUpload,index,proof});
  }
  $('analysis-status').textContent='업로드 완료 · 영상을 분석할 수 있도록 준비하고 있어요…';
  for(let tries=0;tries<120;tries++){
    const info=await uploadRequest({action:'status',token:activeUpload});
    if(info.status==='ready')return info.analysisToken;
    await new Promise(resolve=>setTimeout(resolve,3000));
  }
  throw new Error('영상 준비가 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.');
}
let activeUpload;
async function cleanupUpload(){
  let token=activeUpload;try{token=token||sessionStorage.getItem('scenesound-pending-upload');}catch{}
  if(!token)return;
  try{await uploadRequest({action:'delete',token});try{sessionStorage.removeItem('scenesound-pending-upload');}catch{}}catch{}
  activeUpload=undefined;
}

async function uploadStudioFile(file,role,{base,job,auth,request,onProgress}){
 const path='jobs/'+job+'/uploads',transfer=await request(path,{name:file.name,role,size:file.size});let offset=transfer.offset;
 while(offset<file.size){const chunk=file.slice(offset,Math.min(file.size,offset+transfer.chunkBytes));let next;
  for(let attempt=0;attempt<3;attempt++){
   try{const r=await fetch(base+'/api/studio/'+path+'/'+transfer.id+'?offset='+offset,{method:'POST',headers:auth()?{Authorization:'Bearer '+auth()}:{},body:chunk,signal:AbortSignal.timeout(180000)});const d=await r.json().catch(()=>({error:'파일 전송 서버의 응답을 확인하지 못했어요.'}));if(!r.ok){const e=Error(d.error||'파일 전송에 실패했어요.');e.status=r.status;throw e;}next=d.offset;break;}
   catch(e){if([400,403,413,507].includes(e.status)||attempt===2)throw e;const info=await request(path+'/'+transfer.id,null,'GET');if(info.offset>offset){next=info.offset;break;}}
  }
  if(!Number.isSafeInteger(next)||next<=offset||next>file.size)throw Error('파일 전송 위치를 확인하지 못했어요.');offset=next;onProgress?.(Math.round(offset/file.size*100));
 }
}
async function analyzePrepared(prepared,task){
 const segments=prepared.analysisSegments||[{file:prepared.analysisVideo,start:0,duration:prepared.duration}],results=[];
 for(const [i,s]of segments.entries()){
  status('영상 분석 '+(i+1)+'/'+segments.length+' · 분석용 영상 전송 중');await cleanupUpload();
  try{const r=await fetch(fileUrl(s.file));if(!r.ok)throw Error('분석용 영상을 가져오지 못했어요.');const file=new File([await r.blob()],'analysis.mp4',{type:'video/mp4'}),token=await uploadVideo(file,s.duration);status('영상 분석 '+(i+1)+'/'+segments.length+' · 장면을 살펴보고 있어요.');const response=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,...(task?{task}:{})}),signal:AbortSignal.timeout(270000)}),d=await response.json();if(!response.ok)throw Error(d.error||'영상 분석에 실패했어요.');results.push({...d,offset:s.start});}finally{await cleanupUpload();}
 }
 return combineAnalysisResults(results,task);
}
function combineAnalysisResults(results,task){
 if(task==='scenes')return{summary:results.map(r=>r.summary).join(' ').slice(0,1500),scenes:results.flatMap(r=>r.scenes.map(s=>({...s,start:s.start+r.offset,reason:s.reason+(r.offset&&s.start===0?' · 분할 분석의 시작 경계이므로 실제 씬 경계인지 확인해 주세요.':'')}))).slice(0,30)};
 return{summary:results.map(r=>r.summary).join(' ').slice(0,1500),sounds:results.flatMap(r=>r.sounds.map(s=>({...s,start:s.start+r.offset,end:s.end+r.offset}))).slice(0,60)};
}

if(typeof module!=='undefined')module.exports={combineAnalysisResults};
