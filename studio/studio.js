'use strict';
const $=id=>document.getElementById(id);
let apiBase='',apiToken='',mediaTicket='',publicWorker=false,limits={duration:1800,bytes:6*1024**3};
async function configureServer(){if(location.hostname==='127.0.0.1')return;const r=await fetch('/api/studio-session',{cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'작업 서버 연결을 준비 중이에요.');const url=new URL(data.worker);if(url.protocol!=='https:'||!url.hostname.endsWith('.onrender.com'))throw Error('작업 서버 주소를 확인해 주세요.');apiBase=url.origin;apiToken=data.token;publicWorker=true;limits={duration:data.maxDuration,bytes:data.maxBytes};document.querySelector('header .badge').textContent='실제 자동 처리 · 공개 알파';$('upload-limits').textContent='30분 이하 · AAF 2GB · 영상 2GB · 오디오 1GB · 전체 6GB 이하. AAF와 영상의 시작점을 맞춰 주세요.';$('privacy-note').textContent='AAF·오디오·영상과 결과 파일은 Render 작업 서버의 임시 비공개 폴더에서 처리해요. 브라우저별 임시 권한으로 작업을 구분해요. 선택한 AAF 소리를 합친 분석용 영상은 Supabase 전송 서버를 거쳐 TwelveLabs로 전달되며 분석 후 삭제를 요청해요. 소리 검색어는 Freesound·Wikimedia Commons로 전달돼요. 재시작·연결 중단으로 파일이 사라지거나 외부 분석 파일이 남을 수 있어요.';$('retention-note').textContent='무료 서버는 잠들었다가 다시 켜질 수 있어요. 재시작·배포 시 임시 파일이 사라질 수 있으니 결과를 바로 내려받아 주세요. 완료 작업은 최대 24시간 보관하고 정리합니다.';}
let useDialogue=false;
let jobId,manifest,result,selectedVideo,working=false,players=[],originalPlayer,mode='wet',revision=0,playbackGeneration=0,selectedAssetId=null,dirty=false,localVideoUrl;
const emptyTimeline=$('timeline').innerHTML;
function markDirty(){dirty=true;$('dirty-status').hidden=false;$('timeline-state').textContent='수정 후 반영해 주세요';}
function resetDirty(){dirty=false;$('dirty-status').hidden=true;$('timeline-state').textContent='효과음 · 배경음';}
function updateTransport(){const v=$('preview');$('time-display').textContent=formatTime(v.currentTime)+' / '+formatTime(result?.duration||manifest?.duration||v.duration);$('timeline-play').textContent=v.paused?'▶ 재생':'Ⅱ 일시 정지';}
function formatTime(t){t=Number.isFinite(t)?Math.max(0,t):0;return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');}
$('open-import').onclick=()=>{$('import-panel').hidden=false;$('import-panel').scrollIntoView({behavior:'smooth',block:'start'});$(useDialogue?'video-file':'aaf-file').focus({preventScroll:true});};
$('timeline-play').onclick=()=>{const v=$('preview');if(v.paused)v.play().catch(()=>error('영상을 재생하지 못했어요. 영상 재생 버튼을 다시 눌러 주세요.'));else v.pause();};
$('timeline-zoom').oninput=()=>{$('timeline').style.width=(Number($('timeline-zoom').value)*100)+'%';};
$('video-file').onchange=()=>{if(result)return;if(localVideoUrl)URL.revokeObjectURL(localVideoUrl);const file=$('video-file').files[0];if(!file)return;localVideoUrl=URL.createObjectURL(file);$('preview').src=localVideoUrl;$('preview').muted=false;$('preview').hidden=false;$('video-placeholder').hidden=true;$('viewer-state').textContent='참조 영상';$('timeline-play').disabled=false;};
const fileUrl=name=>apiBase+'/api/studio/jobs/'+jobId+'/files/'+encodeURIComponent(name)+'?v='+revision+(mediaTicket?'&ticket='+encodeURIComponent(mediaTicket):'');
function status(text){$('analysis-status').hidden=false;$('analysis-status').textContent=text;}
function error(message){$('error').hidden=false;$('error').textContent=message;}
function busy(value){working=value;$('preview').controls=!value;document.querySelectorAll('button,input,select').forEach(el=>{el.disabled=value;});if(value){$('error').hidden=true;$('preview').pause();}else{for(const id of ['listen-wet','listen-dry','remix-button'])$(id).disabled=!result;$('timeline-play').disabled=!$('preview').getAttribute('src');}}
async function request(path,body,method='POST',retried=false){const response=await fetch(apiBase+'/api/studio/'+path,{method,headers:{...(body?{'Content-Type':'application/json'}:{}),...(apiToken?{Authorization:'Bearer '+apiToken}:{})},...(body?{body:JSON.stringify(body)}:{})});const data=await response.json();if(response.status===401&&publicWorker&&!retried){await configureServer();return request(path,body,method,true);}if(!response.ok)throw Error(data.error||'작업을 진행하지 못했어요.');if(data.ticket)mediaTicket=data.ticket;return data;}

async function waitJob(){for(let i=0;i<7200;i++){const data=await request('jobs/'+jobId,null,'GET');if(data.status==='ready')return data.data;if(data.status==='error')throw Error(data.error);status(data.stage||'파일을 처리하고 있어요.');await new Promise(resolve=>setTimeout(resolve,1000));}throw Error('처리가 오래 걸리고 있어요. 서버를 확인하고 다시 열어 주세요.');}
function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
function showRoles(){
 $('import-panel').hidden=true;$('roles-panel').hidden=false;$('job-actions').hidden=false;$('track-roles').replaceChildren();
 for(const track of manifest.tracks){const row=node('div',undefined,'track-role'),label=node('label',track.name+' · '+track.clips.length+'개 클립');const select=node('select');select.id='role-'+track.id;label.htmlFor=select.id;for(const [value,text]of [['dialogue','대사 · 잡음 감소와 레벨 보정'],['original','현장음·기존 소리 · 원본 유지'],['ignore','사용하지 않기']]){const option=node('option',text);option.value=value;select.append(option);}select.value=track.role;row.append(label,select);$('track-roles').append(row);}
 if(!result)drawTimeline();
}
function config(){return{useDialogue,roles:Object.fromEntries(manifest.tracks.map(t=>[t.id,$('role-'+t.id).value])),clean:$('clean').checked,trackGains:Object.fromEntries([...document.querySelectorAll('[data-track-gain]')].map(input=>[input.dataset.trackGain,Number(input.value)]))};}
$('import-form').onsubmit=async e=>{
 e.preventDefault();if(working)return;busy(true);
 try{
 const aaf=$('aaf-file').files[0],video=$('video-file').files[0],audio=[...$('audio-files').files];
 if(useDialogue&&jobId&&!manifest.video){
  if(!video||video.size>2*1024**3)throw Error('2GB 이하 참조 영상을 선택해 주세요.');
  status('정리한 대사에 참조 영상을 연결하고 있어요.');
  await uploadStudioFile(video,'video',{base:apiBase,job:jobId,auth:()=>apiToken,request,onProgress:p=>status('참조 영상 전송 · '+p+'%')});
  await request('jobs/'+jobId+'/attach-video');manifest=await waitJob();showRoles();$('import-panel').hidden=true;status('참조 영상을 연결했어요. 효과음·배경음 초안을 만들어 보세요.');return;
 }
 if(!video)throw Error('참조 영상을 선택해 주세요.');
 const files=[...(aaf?[{file:aaf,role:'aaf'}]:[]),{file:video,role:'video'},...audio.map(file=>({file,role:'audio'}))];
 if(video.size>2*1024**3||files.reduce((s,x)=>s+x.file.size,0)>limits.bytes||files.length>64)throw Error(publicWorker?'영상 2GB·전체 6GB·파일 64개 이하여야 해요.':'영상은 2GB, 전체는 6GB, 파일은 64개 이하여야 해요.');
 if(files.some(x=>x.file.size>(['aaf','video'].includes(x.role)?2*1024**3:1024**3)))throw Error('AAF·영상은 각 2GB, 오디오는 각 1GB 이하여야 해요.');
 if(jobId){try{await request('jobs/'+jobId,null,'DELETE');}catch(e){if(!/만료|찾을 수 없/.test(e.message))throw e;}sessionStorage.removeItem('scenesound-effects-job');jobId=null;}
 manifest=null;result=null;stopPlayers();$('sound-edits').replaceChildren();selectAsset(null);resetDirty();$('timeline').innerHTML=emptyTimeline;$('roles-panel').hidden=true;$('result-panel').hidden=true;jobId=(await request('jobs')).id;sessionStorage.setItem('scenesound-effects-job',jobId);$('job-actions').hidden=false;selectedVideo=video;
 for(const [i,{file,role}]of files.entries()){
 status('파일 가져오는 중 · '+(i+1)+'/'+files.length+' · '+file.name);
 await uploadStudioFile(file,role,{base:apiBase,job:jobId,auth:()=>apiToken,request,onProgress:p=>status('파일 가져오기 · '+(i+1)+'/'+files.length+' · '+p+'%')});
 }
 await request('jobs/'+jobId+'/inspect');manifest=await waitJob();showRoles();$('result-panel').hidden=true;status('영상을 가져왔어요. 원본 소리를 유지하고 효과음·배경음을 배치해 보세요.');$('roles-panel').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){error(e.message);}finally{busy(false);}
};
$('process-button').onclick=async()=>{
 if(working||!manifest)return;if(!manifest.video){error('먼저 참조 영상을 연결해 주세요.');return;}busy(true);
 try{
 const chosen=config();if(!Object.values(chosen.roles).some(r=>r!=='ignore'))throw Error('사용할 트랙을 하나 이상 골라 주세요.');
 if(!Object.values(chosen.roles).includes('dialogue')){status('대사 트랙이 지정되지 않아 클리닝과 대사 기반 덕킹은 적용하지 않아요.');}
 await request('jobs/'+jobId+'/prepare-analysis',chosen);const prepared=await waitJob();const plan=await analyzePrepared(prepared);
 await request('jobs/'+jobId+'/render',{...chosen,plan});result=await waitJob();showResult();status('전체 초안을 만들었어요. 원본과 비교하고 필요한 부분을 수정해 주세요.');document.querySelector('.timeline-panel').scrollIntoView({behavior:'smooth',block:'center'});
 }catch(e){error(e.message);}finally{await cleanupUpload();busy(false);}
};
function stopPlayers(){playbackGeneration++;for(const a of players)a.pause();originalPlayer?.pause();}
function activePlayers(){return mode==='dry'?[originalPlayer]:players;}
function sync(force=false){updateTransport();const time=$('preview').currentTime;document.querySelectorAll('.wave').forEach(el=>el.style.setProperty('--playhead',(time/(result?.duration||1)*100)+'%'));for(const a of activePlayers().filter(Boolean)){if(a.readyState>0&&(force||Math.abs(a.currentTime-time)>.12))a.currentTime=Math.min(time,a.duration||time);}}
async function play(){updateTransport();if(!result)return;if(working){$('preview').pause();return;}const generation=playbackGeneration;sync(true);try{await Promise.all(activePlayers().filter(Boolean).map(a=>a.play()));}catch(e){if(working||generation!==playbackGeneration||e.name==='AbortError')return;$('preview').pause();error('트랙을 재생하지 못했어요. 잠시 뒤 영상 재생 버튼을 다시 눌러 주세요.');}}
$('preview').onplay=play;$('preview').onpause=()=>{stopPlayers();updateTransport();};$('preview').onloadedmetadata=updateTransport;$('preview').onseeking=()=>sync(true);$('preview').ontimeupdate=()=>sync();$('preview').onended=stopPlayers;
function listen(which){mode=which;stopPlayers();$('listen-wet').setAttribute('aria-pressed',String(mode==='wet'));$('listen-dry').setAttribute('aria-pressed',String(mode==='dry'));$('play-status').textContent=mode==='dry'?'AAF 원본을 듣고 있어요.':'보정·배치된 초안을 듣고 있어요.';if(!$('preview').paused)play();}
$('listen-wet').onclick=()=>listen('wet');$('listen-dry').onclick=()=>listen('dry');
function numberField(label,value,attrs){const wrap=node('label',label),input=node('input');input.type='number';Object.assign(input,attrs);input.value=value;wrap.append(input);return{wrap,input};}
function edits(){return[...document.querySelectorAll('.sound-edit')].map(el=>({id:el.dataset.id,start:Number(el.querySelector('[data-field=start]').value),end:Number(el.querySelector('[data-field=end]').value),gain:Number(el.querySelector('[data-field=gain]').value),enabled:el.querySelector('[data-field=enabled]').checked}));}
async function remix(replace){if(working)return;busy(true);try{const time=$('preview').currentTime;const changes=edits();if(changes.some(a=>!Number.isFinite(a.start)||!Number.isFinite(a.end)||!Number.isFinite(a.gain)||a.start<0||a.end>result.duration||a.end<=a.start||a.gain< -60||a.gain>6))throw Error('시작·끝과 음량을 확인해 주세요. 끝은 시작보다 뒤여야 해요.');await request('jobs/'+jobId+'/remix',{...config(),edits:changes,...(replace?{replace}:{})});result=await waitJob();showResult();$('preview').currentTime=time;status('수정한 초안과 내보내기 파일을 만들었어요.');}catch(e){error(e.message);}finally{busy(false);}}
$('remix-button').onclick=()=>remix();
function showResult(){
 $('error').hidden=true;stopPlayers();players=[];$('audio-players').replaceChildren();originalPlayer?.remove();revision++;
 if(localVideoUrl){URL.revokeObjectURL(localVideoUrl);localVideoUrl=null;}
 $('preview').src=fileUrl('preview.mp4');$('preview').hidden=false;$('video-placeholder').hidden=true;$('viewer-state').textContent='사운드 초안';$('preview').muted=true;$('preview').playbackRate=1;
 $('preview').onratechange=()=>{for(const a of [...players,originalPlayer].filter(Boolean))a.playbackRate=$('preview').playbackRate;};
 originalPlayer=new Audio(fileUrl('original.wav'));originalPlayer.preload='metadata';originalPlayer.dataset.trackPlayer='original';$('audio-players').append(originalPlayer);
 $('result-panel').hidden=false;$('summary').textContent=result.summary;
 for(const t of result.tracks){const audio=new Audio(fileUrl(t.export));audio.preload='auto';audio.dataset.trackPlayer=t.id;audio.muted=t.gain<=-60;$('audio-players').append(audio);players.push(audio);}
 $('sound-edits').replaceChildren();
 for(const asset of result.assets){
 const card=node('div',undefined,'sound-edit');card.dataset.id=asset.id;card.append(node('strong',asset.title+' · '+(asset.role==='effect'?'효과음':'배경음')),node('div',asset.name+' / '+asset.creator+' / '+asset.library,'note'));
 const links=node('p',undefined,'note');for(const [text,url]of [['음원 원본',asset.source],[asset.license,asset.licenseUrl]]){const a=node('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';links.append(a);}card.append(links);
 const fields=node('div',undefined,'edit-fields');
 for(const [key,label,value,min,max,step]of [['start','시작 · 초',asset.start,0,result.duration,'.01'],['end','끝 · 초',asset.end,0,result.duration,'.01'],['gain','소리 음량 · dB',asset.gain,-60,6,'1']]){
 const f=numberField(label,Number(value.toFixed(2)),{min:String(min),max:String(max),step});f.input.dataset.field=key;
 f.input.oninput=()=>{markDirty();if(key!=='gain')updateAssetBlock(asset.id);};fields.append(f.wrap);
 }
 const label=node('label',' 사용하기'),enabled=node('input');enabled.type='checkbox';enabled.checked=asset.enabled;enabled.dataset.field='enabled';enabled.onchange=()=>{markDirty();updateAssetBlock(asset.id);};label.prepend(enabled);fields.append(label);
 const button=node('button','다른 음원 추천받기','secondary');button.type='button';button.onclick=()=>remix(asset.id);fields.append(button);card.append(fields);$('sound-edits').append(card);
 }
 resetDirty();drawTimeline();selectAsset(result.assets.some(a=>a.id===selectedAssetId)?selectedAssetId:null);
 $('warnings').replaceChildren();for(const text of result.warnings)$('warnings').append(node('li',text));
 for(const [id,name]of [['download-all','SceneSound.zip'],['download-mix','mix.wav'],['download-aaf','SceneSound.aaf'],['download-video','preview.mp4']]){$(id).href=fileUrl(name)+'&download=1';$(id).download=name;}
 $('timeline-hint').textContent='효과음·배경음만 표시해요. 대사는 함께 재생되며 1단계에서 따로 확인할 수 있어요. 수정 반영 후 내보내기에 적용돼요.';
 for(const id of ['listen-wet','listen-dry','remix-button','timeline-play'])$(id).disabled=working;
 listen('wet');updateTransport();
}
function assetCard(id){return [...$('sound-edits').children].find(el=>el.dataset.id===id);}
function assetBlock(id){return [...document.querySelectorAll('[data-asset-id]')].find(el=>el.dataset.assetId===id);}
function selectAsset(id){
 selectedAssetId=id;for(const card of $('sound-edits').children)card.hidden=card.dataset.id!==id;
 $('inspector-empty').hidden=Boolean(id);$('edit-help').hidden=!id;
 for(const block of document.querySelectorAll('[data-asset-id]'))block.classList.toggle('selected',block.dataset.assetId===id);
}
function updateAssetBlock(id){
 const card=assetCard(id),block=assetBlock(id);if(!card||!block)return;
 const start=Number(card.querySelector('[data-field=start]').value),end=Number(card.querySelector('[data-field=end]').value);
 block.style.left=(start/result.duration*100)+'%';block.style.width=(Math.max(.02,end-start)/result.duration*100)+'%';
 block.classList.toggle('disabled-clip',!card.querySelector('[data-field=enabled]').checked);
 block.setAttribute('aria-label',card.querySelector('strong').textContent+' · '+start.toFixed(2)+'초부터 '+end.toFixed(2)+'초');
 block.title=card.querySelector('strong').textContent+' · '+start.toFixed(2)+'–'+end.toFixed(2)+'초';
}
function waveform(peaks,color){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 '+Math.max(1,peaks.length)+' 60');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
 peaks.forEach((peak,i)=>{const line=document.createElementNS(svg.namespaceURI,'line');line.setAttribute('x1',i);line.setAttribute('x2',i);line.setAttribute('y1',30-peak*28);line.setAttribute('y2',30+peak*28);line.setAttribute('stroke',color);line.setAttribute('stroke-width','.7');svg.append(line);});return svg;
}
function scrub(e,lane){if(!result||working)return;const r=lane.getBoundingClientRect();$('preview').currentTime=Math.max(0,Math.min(result.duration,(e.clientX-r.left)/r.width*result.duration));sync(true);}
function drawTimeline(){
 const duration=result?.duration||manifest?.duration;if(!duration)return;
 const tracks=(result?.tracks||manifest.tracks).filter(t=>t.role==='effect'||t.role==='ambience');$('timeline').replaceChildren();
 const rulerRow=node('div',undefined,'ruler-row');rulerRow.append(node('span','TRACKS','ruler-label'));const ruler=node('div',undefined,'ruler');for(let i=0;i<=5;i++)ruler.append(node('span',formatTime(duration*i/5)));ruler.onclick=e=>scrub(e,ruler);rulerRow.append(ruler);$('timeline').append(rulerRow);
 const list=[...tracks];for(const role of ['effect','ambience'])if(!list.some(t=>t.role===role))list.push({id:role,name:role==='effect'?'효과음':'배경음',role,clips:[],empty:true});
 for(const t of list){
 const row=node('div',undefined,'track-row '+t.role),label=node('div',undefined,'track-controls');
 label.append(node('strong',t.name,'track-name'),node('div',({dialogue:'대사',original:'기존 소리',effect:'효과음',ambience:'배경음',ignore:'미사용'})[t.role]||'원본 트랙','note'));
 if(result&&!t.empty){
 const mixer=node('div',undefined,'track-mixer'),mute=node('button','M','mute-button'),gain=numberField('dB',t.gain,{min:'-60',max:'6',step:'1'});gain.input.dataset.trackGain=t.id;mute.type='button';mute.setAttribute('aria-label',t.name+' 음소거');mute.setAttribute('aria-pressed',String(t.gain<=-60));
 let savedGain=t.gain>-60?t.gain:0;
 mute.onclick=()=>{const muted=mute.getAttribute('aria-pressed')!=='true';if(muted)savedGain=Number(gain.input.value);gain.input.value=muted?-60:savedGain;mute.setAttribute('aria-pressed',String(muted));const audio=players.find(a=>a.dataset.trackPlayer===t.id);if(audio)audio.muted=muted;row.classList.toggle('muted',muted);markDirty();};
 gain.input.oninput=()=>{const muted=Number(gain.input.value)<=-60;mute.setAttribute('aria-pressed',String(muted));const audio=players.find(a=>a.dataset.trackPlayer===t.id);if(audio)audio.muted=muted;row.classList.toggle('muted',muted);markDirty();};mixer.append(mute,gain.wrap);label.append(mixer);row.classList.toggle('muted',t.gain<=-60);
 }
 const lane=node('div',undefined,'wave');lane.onclick=e=>{if(e.target===lane||e.target.tagName==='svg')scrub(e,lane);};
 if(t.waveform?.length)lane.append(waveform(t.waveform,'var(--track)'));
 const assets=result?.assets.filter(a=>a.role===t.role)||[];
 if(assets.length){for(const asset of assets){
 const block=node('button',undefined,'clip editable');block.type='button';block.dataset.assetId=asset.id;block.append(node('span',asset.title,'clip-title'));
 for(const side of ['start','end']){const h=node('span',undefined,'trim-handle '+side);h.dataset.trim=side;h.setAttribute('aria-hidden','true');block.append(h);}
 const i1=Math.floor(asset.start/duration*(t.waveform?.length||0)),i2=Math.ceil(asset.end/duration*(t.waveform?.length||0));if(i2>i1)block.append(waveform(t.waveform.slice(i1,i2),'var(--track)'));
 block.onclick=()=>selectAsset(asset.id);block.onpointerdown=e=>beginDrag(e,asset.id,lane,block);lane.append(block);
 }}else for(const clip of t.clips||[]){const block=node('div',clip.title||t.name,'clip locked');block.style.left=(clip.start/duration*100)+'%';block.style.width=(clip.duration/duration*100)+'%';lane.append(block);}
 if(!assets.length&&!t.clips?.length)lane.append(node('span',t.empty?'아직 배치된 소리가 없어요.':'클립이 없는 트랙이에요.','sr-only'));
 row.append(label,lane);$('timeline').append(row);
 }
 for(const asset of result?.assets||[])updateAssetBlock(asset.id);
}
function beginDrag(e,id,lane,block){
 if(working||e.button!==0)return;selectAsset(id);const card=assetCard(id),startField=card.querySelector('[data-field=start]'),endField=card.querySelector('[data-field=end]');
 const initialStart=Number(startField.value),initialEnd=Number(endField.value),x=e.clientX,scale=result.duration/lane.getBoundingClientRect().width,trim=e.target.dataset.trim;
 let moved=false;block.setPointerCapture(e.pointerId);
 const move=event=>{const delta=(event.clientX-x)*scale;if(Math.abs(event.clientX-x)<3&&!moved)return;if(!moved)$('preview').pause();moved=true;let start=initialStart,end=initialEnd;
 if(trim==='start')start=Math.max(0,Math.min(initialEnd-.05,initialStart+delta));else if(trim==='end')end=Math.max(initialStart+.05,Math.min(result.duration,initialEnd+delta));else{start=Math.max(0,Math.min(result.duration-(initialEnd-initialStart),initialStart+delta));end=start+initialEnd-initialStart;}
 startField.value=(Math.round(start*100)/100).toFixed(2);endField.value=Math.min(result.duration,Math.round(end*100)/100);markDirty();updateAssetBlock(id);};
 const finish=()=>{block.removeEventListener('pointermove',move);block.removeEventListener('pointerup',finish);block.removeEventListener('pointercancel',cancel);};
 const cancel=()=>{startField.value=initialStart;endField.value=initialEnd;updateAssetBlock(id);finish();};
 block.addEventListener('pointermove',move);block.addEventListener('pointerup',finish);block.addEventListener('pointercancel',cancel);
}
$('delete-job').onclick=async()=>{if(working)return;try{stopPlayers();$('preview').removeAttribute('src');$('preview').load();await request('jobs/'+jobId,null,'DELETE');sessionStorage.removeItem('scenesound-effects-job');jobId=null;manifest=null;result=null;$('roles-panel').hidden=true;$('result-panel').hidden=true;$('job-actions').hidden=true;$('import-form').reset();$('import-panel').hidden=false;$('preview').hidden=true;$('video-placeholder').hidden=false;$('viewer-state').textContent='파일을 기다리는 중';$('timeline').innerHTML=emptyTimeline;$('sound-edits').replaceChildren();selectedAssetId=null;selectAsset(null);resetDirty();busy(false);updateTransport();status('임시 작업 파일을 삭제했어요. 새 편집본을 선택해 주세요.');}catch(e){error(e.message);}};
(async()=>{$('import-button').disabled=true;try{await configureServer();const info=await request('status',null,'GET');$('engine-status').textContent=info.ready?(publicWorker?'공개 처리 서버 연결됨 · 첫 연결은 서버가 깨어날 때까지 잠시 걸릴 수 있어요.':'로컬 처리 엔진 연결됨 · AAF와 오디오는 이 컴퓨터에서 처리해요.'):'처리 엔진을 설치해 주세요. README의 Studio 실행 안내를 확인하세요.';$('import-button').disabled=!info.ready;
 const stored=sessionStorage.getItem('scenesound-effects-job');if(stored){jobId=stored;const existing=await request('jobs/'+jobId,null,'GET');useDialogue=existing.dialogueReady===true;if(useDialogue){document.body.classList.add('has-dialogue');$('aaf-file').required=false;$('aaf-file').closest('label').hidden=true;$('audio-files').closest('details').hidden=true;$('import-button').textContent='참조 영상 연결';$('roles-panel').querySelector('h2').textContent='1단계 대사 정리 완료';$('import-panel').querySelector('h2').textContent='참조 영상 추가';$('video-placeholder').querySelector('.note').textContent='정리한 대사에 맞는 참조 영상을 추가해 주세요.';$('process-button').textContent='효과음·배경음 분석하고 배치';}if(existing.manifest){manifest=existing.manifest;showRoles();for(const t of manifest.tracks){if(existing.settings?.roles?.[t.id])$('role-'+t.id).value=existing.settings.roles[t.id];}if(existing.settings)$('clean').checked=existing.settings.clean;if(useDialogue&&!manifest.video)$('import-panel').hidden=false;}if(existing.status==='processing'){busy(true);const data=await waitJob();if(data.mode!=='dialogue'&&data.tracks?.[0]?.waveform){result=data;showResult();}else{manifest=data;showRoles();}busy(false);}else if(existing.data?.mode!=='dialogue'&&existing.data?.tracks?.[0]?.waveform){result=existing.data;showResult();}status('이전 작업을 복원했어요.');}
 }catch{sessionStorage.removeItem('scenesound-effects-job');jobId=null;manifest=null;result=null;stopPlayers();$('sound-edits').replaceChildren();selectAsset(null);resetDirty();$('timeline').innerHTML=emptyTimeline;$('roles-panel').hidden=true;$('result-panel').hidden=true;$('job-actions').hidden=true;try{const info=await request('status',null,'GET');busy(false);$('import-button').disabled=!info.ready;$('engine-status').textContent=info.ready?(publicWorker?'공개 서버 연결됨 · 이전 작업이 만료됐어요. 파일을 다시 선택해 주세요.':'로컬 처리 엔진 연결됨 · 이전 세션이 만료됐어요. 파일을 다시 선택해 주세요.'):'처리 엔진을 설치해 주세요.';}catch{$('engine-status').textContent=location.hostname==='127.0.0.1'?'로컬 처리 서버에서 열어 주세요. npm run dev → /studio.html':'공개 작업 서버에 연결하지 못했어요. 잠시 후 새로고침해 주세요.';}}})();
