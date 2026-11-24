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
