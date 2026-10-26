'use strict';
const $=id=>document.getElementById(id);
let jobId,manifest,result,selectedVideo,working=false,players=[],originalPlayer,mode='wet',revision=0,playbackGeneration=0;
const fileUrl=name=>'/api/studio/jobs/'+jobId+'/files/'+encodeURIComponent(name)+'?v='+revision;
function status(text){$('analysis-status').hidden=false;$('analysis-status').textContent=text;}
function error(message){$('error').hidden=false;$('error').textContent=message;}
function busy(value){working=value;$('preview').controls=!value;document.querySelectorAll('button,input,select').forEach(el=>{el.disabled=value;});if(value){$('error').hidden=true;$('preview').pause();}}
async function request(path,body,method='POST'){const response=await fetch('/api/studio/'+path,{method,headers:body?{'Content-Type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{})});const data=await response.json();if(!response.ok)throw Error(data.error||'작업을 진행하지 못했어요.');return data;}
async function waitJob(){for(let i=0;i<1500;i++){const data=await request('jobs/'+jobId,null,'GET');if(data.status==='ready')return data.data;if(data.status==='error')throw Error(data.error);status(data.stage||'파일을 처리하고 있어요.');await new Promise(resolve=>setTimeout(resolve,1000));}throw Error('처리가 오래 걸리고 있어요. 서버를 확인하고 다시 열어 주세요.');}
function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
function showRoles(){
 $('roles-panel').hidden=false;$('job-actions').hidden=false;$('track-roles').replaceChildren();
 for(const track of manifest.tracks){const row=node('div',undefined,'track-role'),label=node('label',track.name+' · '+track.clips.length+'개 클립');const select=node('select');select.id='role-'+track.id;label.htmlFor=select.id;for(const [value,text]of [['dialogue','대사 · 잡음 감소와 레벨 보정'],['original','현장음·기존 소리 · 원본 유지'],['ignore','사용하지 않기']]){const option=node('option',text);option.value=value;select.append(option);}select.value=track.role;row.append(label,select);$('track-roles').append(row);}
}
function config(){return{roles:Object.fromEntries(manifest.tracks.map(t=>[t.id,$('role-'+t.id).value])),clean:$('clean').checked,trackGains:Object.fromEntries([...document.querySelectorAll('[data-track-gain]')].map(input=>[input.dataset.trackGain,Number(input.value)]))};}
$('import-form').onsubmit=async e=>{
 e.preventDefault();if(working)return;busy(true);
 try{
 const aaf=$('aaf-file').files[0],video=$('video-file').files[0],audio=[...$('audio-files').files];
 if(!aaf||!video)throw Error('AAF와 참조 영상을 선택해 주세요.');
 const files=[{file:aaf,role:'aaf'},{file:video,role:'video'},...audio.map(file=>({file,role:'audio'}))];
 if(video.size>200*1024*1024||files.reduce((s,x)=>s+x.file.size,0)>1024**3||files.length>64)throw Error('영상은 200MB, 전체는 1GB, 파일은 64개 이하여야 해요.');
 if(jobId){try{await request('jobs/'+jobId,null,'DELETE');}catch(e){if(!/만료|찾을 수 없/.test(e.message))throw e;}sessionStorage.removeItem('scenesound-studio-job');jobId=null;}
 manifest=null;result=null;stopPlayers();$('roles-panel').hidden=true;$('result-panel').hidden=true;jobId=(await request('jobs')).id;sessionStorage.setItem('scenesound-studio-job',jobId);$('job-actions').hidden=false;selectedVideo=video;
 for(const [i,{file,role}]of files.entries()){
 status('파일 가져오는 중 · '+(i+1)+'/'+files.length+' · '+file.name);
 const r=await fetch('/api/studio/jobs/'+jobId+'/files?'+new URLSearchParams({role,name:file.name}),{method:'POST',body:file});const d=await r.json();if(!r.ok)throw Error(d.error);
 }
 await request('jobs/'+jobId+'/inspect');manifest=await waitJob();showRoles();$('result-panel').hidden=true;status('AAF를 읽었어요. 대사로 보정할 트랙을 확인해 주세요.');$('roles-panel').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){error(e.message);}finally{busy(false);}
};
async function uploadRequest(body){const response=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});const data=await response.json();if(!response.ok)throw Error(data.error||'영상 전송을 진행하지 못했어요.');return data;}
function putChunk(url,headers,chunk,onProgress){return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();xhr.open('PUT',url);xhr.timeout=180000;
  Object.entries(headers).forEach(([key,value])=>xhr.setRequestHeader(key,value));
  xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(e.loaded);};
  xhr.onload=()=>{const etag=xhr.getResponseHeader('ETag');if(xhr.status>=200&&xhr.status<300&&etag)resolve(etag.replaceAll('"',''));else reject(new Error('영상 전송을 확인하지 못했어요. 다시 시도해 주세요.'));};
  xhr.onerror=()=>reject(new Error('영상 전송이 끊겼어요. 인터넷 연결을 확인하고 다시 시도해 주세요.'));
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
$('process-button').onclick=async()=>{
 if(working||!manifest)return;busy(true);
 try{
 const chosen=config();if(!Object.values(chosen.roles).some(r=>r!=='ignore'))throw Error('사용할 트랙을 하나 이상 골라 주세요.');
 if(!Object.values(chosen.roles).includes('dialogue')){status('대사 트랙이 지정되지 않아 클리닝과 대사 기반 덕킹은 적용하지 않아요.');}
 await request('jobs/'+jobId+'/prepare-analysis',chosen);const prepared=await waitJob();const blob=await(await fetch(fileUrl(prepared.analysisVideo))).blob();selectedVideo=new File([blob],'analysis-reference.mp4',{type:'video/mp4'});
 status('영상 분석 서버에 연결하고 있어요.');await cleanupUpload();
 const token=await uploadVideo(selectedVideo,manifest.duration);status('영상의 장면과 기존 소리를 분석하고 있어요.');
 const response=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token}),signal:AbortSignal.timeout(270000)});const plan=await response.json();if(!response.ok)throw Error(plan.error||'영상 분석에 실패했어요.');
 await request('jobs/'+jobId+'/render',{...chosen,plan});result=await waitJob();showResult();status('전체 초안을 만들었어요. 원본과 비교하고 필요한 부분을 수정해 주세요.');$('result-panel').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){error(e.message);}finally{await cleanupUpload();busy(false);}
};
function stopPlayers(){playbackGeneration++;for(const a of players)a.pause();originalPlayer?.pause();}
function activePlayers(){return mode==='dry'?[originalPlayer]:players;}
function sync(force=false){const time=$('preview').currentTime;document.querySelectorAll('.wave').forEach(el=>el.style.setProperty('--playhead',(time/(result?.duration||1)*100)+'%'));for(const a of activePlayers().filter(Boolean)){if(a.readyState>0&&(force||Math.abs(a.currentTime-time)>.12))a.currentTime=Math.min(time,a.duration||time);}}
async function play(){if(working){$('preview').pause();return;}const generation=playbackGeneration;sync(true);try{await Promise.all(activePlayers().filter(Boolean).map(a=>a.play()));}catch(e){if(working||generation!==playbackGeneration||e.name==='AbortError')return;$('preview').pause();error('트랙을 재생하지 못했어요. 잠시 뒤 영상 재생 버튼을 다시 눌러 주세요.');}}
$('preview').onplay=play;$('preview').onpause=stopPlayers;$('preview').onseeking=()=>sync(true);$('preview').ontimeupdate=()=>sync();$('preview').onended=stopPlayers;
function listen(which){mode=which;stopPlayers();$('listen-wet').setAttribute('aria-pressed',String(mode==='wet'));$('listen-dry').setAttribute('aria-pressed',String(mode==='dry'));$('play-status').textContent=mode==='dry'?'AAF 원본을 듣고 있어요.':'보정·배치된 초안을 듣고 있어요.';if(!$('preview').paused)play();}
$('listen-wet').onclick=()=>listen('wet');$('listen-dry').onclick=()=>listen('dry');
function numberField(label,value,attrs){const wrap=node('label',label),input=node('input');input.type='number';Object.assign(input,attrs);input.value=value;wrap.append(input);return{wrap,input};}
function edits(){return[...document.querySelectorAll('.sound-edit')].map(el=>({id:el.dataset.id,start:Number(el.querySelector('[data-field=start]').value),end:Number(el.querySelector('[data-field=end]').value),gain:Number(el.querySelector('[data-field=gain]').value),enabled:el.querySelector('[data-field=enabled]').checked}));}
async function remix(replace){if(working)return;busy(true);try{const time=$('preview').currentTime;await request('jobs/'+jobId+'/remix',{...config(),edits:edits(),...(replace?{replace}:{})});result=await waitJob();showResult();$('preview').currentTime=time;status('수정한 초안과 내보내기 파일을 만들었어요.');}catch(e){error(e.message);}finally{busy(false);}}
$('remix-button').onclick=()=>remix();
function showResult(){
 $('error').hidden=true;stopPlayers();players=[];$('audio-players').replaceChildren();originalPlayer?.remove();revision++;$('preview').src=fileUrl('preview.mp4');$('preview').muted=true;$('preview').playbackRate=1;$('preview').onratechange=()=>{for(const a of [...players,originalPlayer].filter(Boolean))a.playbackRate=$('preview').playbackRate;};
 originalPlayer=new Audio(fileUrl('original.wav'));originalPlayer.preload='metadata';originalPlayer.dataset.trackPlayer='original';$('audio-players').append(originalPlayer);
 $('result-panel').hidden=false;$('summary').textContent=result.summary;$('timeline').replaceChildren();
 for(const t of result.tracks){
 const audio=new Audio(fileUrl(t.export));audio.preload='auto';audio.dataset.trackPlayer=t.id;$('audio-players').append(audio);players.push(audio);
 const row=node('div',undefined,'track-row '+t.role),label=node('div');label.append(node('strong',t.name),node('div',({dialogue:'대사 보정',original:'기존 소리',effect:'효과음',ambience:'배경음'})[t.role],'note'));
 const muteLabel=node('label',' 이 트랙 듣기'),check=node('input');check.type='checkbox';check.checked=t.gain> -60;audio.muted=!check.checked;check.onchange=()=>{audio.muted=!check.checked;gain.input.value=check.checked?'0':'-60';row.classList.toggle('muted',!check.checked);};muteLabel.prepend(check);label.append(muteLabel);
 const wave=node('div',undefined,'wave');const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 180 60');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
 (t.waveform||[]).forEach((peak,i)=>{const line=document.createElementNS(svg.namespaceURI,'line');line.setAttribute('x1',i);line.setAttribute('x2',i);line.setAttribute('y1',30-peak*28);line.setAttribute('y2',30+peak*28);line.setAttribute('stroke','#5954d6');line.setAttribute('stroke-width','.65');svg.append(line);});wave.append(svg);
 for(const clip of t.clips){const marker=node('div',undefined,'clip');marker.style.left=(clip.start/result.duration*100)+'%';marker.style.width=((clip.duration||0)/result.duration*100)+'%';marker.title=(clip.title||t.name)+' · '+clip.start.toFixed(2)+'초';wave.append(marker);}
 const gain=numberField('트랙 음량 dB',t.gain,{min:'-60',max:'6',step:'1'});gain.input.dataset.trackGain=t.id;
 row.append(label,wave,gain.wrap);$('timeline').append(row);
 }
 $('sound-edits').replaceChildren();
 if(!result.assets.length)$('sound-edits').append(node('p','자동으로 배치할 수 있는 음원을 찾지 못했어요. 대사·원본 트랙 초안은 그대로 들을 수 있어요.','note'));
 for(const asset of result.assets){
 const card=node('div',undefined,'sound-edit');card.dataset.id=asset.id;card.append(node('strong',asset.title+' · '+(asset.role==='effect'?'효과음':'배경음')),node('div',asset.name+' / '+asset.creator+' / '+asset.library,'note'));
 const links=node('p',undefined,'note');for(const [text,url]of [['음원 원본 ↗',asset.source],[asset.license+' ↗',asset.licenseUrl]]){const a=node('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';links.append(a);}card.append(links);
 const fields=node('div',undefined,'edit-fields');for(const [key,label,value,min,max,step]of [['start','시작 · 초',asset.start,0,result.duration,'.01'],['end','끝 · 초',asset.end,0,result.duration,'.01'],['gain','소리 음량 · dB',asset.gain,-60,6,'1']]){const f=numberField(label,Number(value.toFixed(2)),{min:String(min),max:String(max),step});f.input.dataset.field=key;fields.append(f.wrap);}
 const label=node('label',' 사용하기'),enabled=node('input');enabled.type='checkbox';enabled.checked=asset.enabled;enabled.dataset.field='enabled';label.prepend(enabled);fields.append(label);
 const button=node('button','↻ 다른 음원으로 교체','secondary');button.type='button';button.onclick=()=>remix(asset.id);fields.append(button);card.append(fields);$('sound-edits').append(card);
 }
 $('warnings').replaceChildren();for(const text of result.warnings)$('warnings').append(node('li',text));
 for(const [id,name]of [['download-all','SceneSound.zip'],['download-mix','mix.wav'],['download-aaf','SceneSound.aaf'],['download-video','preview.mp4']]){$(id).href=fileUrl(name);$(id).download=name;}
 listen('wet');
}
$('delete-job').onclick=async()=>{if(working)return;try{stopPlayers();$('preview').removeAttribute('src');$('preview').load();await request('jobs/'+jobId,null,'DELETE');sessionStorage.removeItem('scenesound-studio-job');jobId=null;manifest=null;result=null;$('roles-panel').hidden=true;$('result-panel').hidden=true;$('job-actions').hidden=true;$('import-form').reset();status('임시 작업 파일을 삭제했어요. 새 편집본을 선택해 주세요.');}catch(e){error(e.message);}};
(async()=>{try{const info=await request('status',null,'GET');$('engine-status').textContent=info.ready?'로컬 처리 엔진 연결됨 · AAF와 오디오는 이 컴퓨터에서 처리해요.':'처리 엔진을 설치해 주세요. README의 Studio 실행 안내를 확인하세요.';if(!info.ready)$('import-button').disabled=true;
 const stored=sessionStorage.getItem('scenesound-studio-job');if(stored){jobId=stored;const existing=await request('jobs/'+jobId,null,'GET');if(existing.manifest){manifest=existing.manifest;showRoles();for(const t of manifest.tracks){if(existing.settings?.roles?.[t.id])$('role-'+t.id).value=existing.settings.roles[t.id];}if(existing.settings)$('clean').checked=existing.settings.clean;}if(existing.status==='processing'){busy(true);const data=await waitJob();if(data.tracks?.[0]?.waveform){result=data;showResult();}else{manifest=data;showRoles();}busy(false);}else if(existing.data?.tracks?.[0]?.waveform){result=existing.data;showResult();}status('이전 작업을 복원했어요.');}
 }catch{sessionStorage.removeItem('scenesound-studio-job');jobId=null;try{const info=await request('status',null,'GET');$('engine-status').textContent=info.ready?'로컬 처리 엔진 연결됨 · 이전 세션이 만료됐어요. 파일을 다시 선택해 주세요.':'처리 엔진을 설치해 주세요.';}catch{$('engine-status').textContent='로컬 처리 서버에서 열어 주세요. npm run dev → /studio.html';}}})();
