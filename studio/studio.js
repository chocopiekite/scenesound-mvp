'use strict';
const $=id=>document.getElementById(id);
let apiBase='',apiToken='',mediaTicket='',publicWorker=false,limits={duration:1800,bytes:8*1024**3};
async function configureServer(){if(location.hostname==='127.0.0.1')return;const r=await fetch('/api/studio-session',{cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'작업 서버 연결을 준비 중이에요.');const url=new URL(data.worker);if(url.protocol!=='https:'||!url.hostname.endsWith('.onrender.com'))throw Error('작업 서버 주소를 확인해 주세요.');apiBase=url.origin;apiToken=data.token;publicWorker=true;limits={duration:data.maxDuration,bytes:data.maxBytes};document.querySelector('header .badge').textContent='실제 자동 처리 · 공개 알파';$('upload-limits').textContent='30분 이하 · AAF 5GB · 영상 2GB · 오디오 1GB · 전체 8GB 이하. AAF와 영상의 시작점을 맞춰 주세요.';$('privacy-note').textContent='AAF·오디오·영상과 결과 파일은 Render 작업 서버의 임시 비공개 폴더에서 처리해요. 브라우저별 임시 권한으로 작업을 구분해요. 선택한 AAF 소리를 합친 분석용 영상은 Supabase 전송 서버를 거쳐 TwelveLabs로 전달되며 분석 후 삭제를 요청해요. 소리 검색어는 Freesound·Wikimedia Commons로 전달돼요. 재시작·연결 중단으로 파일이 사라지거나 외부 분석 파일이 남을 수 있어요.';$('retention-note').textContent='무료 서버는 잠들었다가 다시 켜질 수 있어요. 재시작·배포 시 임시 파일이 사라질 수 있으니 결과를 바로 내려받아 주세요. 완료 작업은 최대 24시간 보관하고 정리합니다.';}
let useDialogue=false;
let jobId,manifest,result,selectedVideo,working=false,players=[],originalPlayer,mode='wet',revision=0,playbackGeneration=0,selectedAssetId=null,dirty=false,localVideoUrl;
const emptyTimeline=$('timeline').innerHTML;
let channels=[],assetPlayers=new Map(),audioContext,masterGain,animationFrame,exporting=false,duckGain=1,lastDuckTime=0;
const savedEditorKey=()=> 'scenesound-editor-'+jobId;
function saveEditor(){if(!result)return;try{sessionStorage.setItem(savedEditorKey(),JSON.stringify({renderDirectory:result.renderDirectory,channels,edits:edits()}));}catch{}}
function refreshDownloadLinks(){for(const a of document.querySelectorAll('.downloads a')){a.setAttribute('aria-busy',String(dirty));a.title=dirty?'최신 편집으로 파일을 준비한 뒤 내려받아요.':'파일 내려받기';}}
function markDirty(){dirty=true;$('dirty-status').hidden=false;$('dirty-status').textContent='편집 즉시 재생에 반영됨 · 다운로드 시 최신 파일 준비';$('timeline-state').textContent='실시간 편집';const invalid=edits().some(a=>![a.start,a.end,a.gain].every(Number.isFinite)||a.start<0||a.end<=a.start||a.end>result.duration||a.gain< -60||a.gain>6);if(invalid){$('dirty-status').textContent='시작·끝·음량을 확인해 주세요. 유효한 값만 재생할 수 있어요.';}else{saveEditor();sync();}refreshDownloadLinks();}
function resetDirty(){dirty=false;$('dirty-status').hidden=true;$('timeline-state').textContent='효과음 · 배경음';refreshDownloadLinks();}
function updateTransport(){const v=$('preview');$('time-display').textContent=formatTime(v.currentTime)+' / '+formatTime(result?.duration||manifest?.duration||v.duration);$('timeline-play').textContent=v.paused?'▶ 재생':'Ⅱ 일시 정지';}
function formatTime(t){t=Number.isFinite(t)?Math.max(0,t):0;return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');}
$('open-import').onclick=()=>{$('import-panel').hidden=false;$('import-panel').scrollIntoView({behavior:'smooth',block:'start'});$(useDialogue?'video-file':'aaf-file').focus({preventScroll:true});};
function togglePlay(){if(working||!$('preview').getAttribute('src'))return;const v=$('preview');if(v.paused){ensureAudio();v.play().catch(()=>error('영상을 재생하지 못했어요. 재생 버튼을 다시 눌러 주세요.'));}else v.pause();}
$('timeline-play').onclick=togglePlay;
function setZoom(value){const input=$('timeline-zoom');input.value=Math.max(1,Math.min(12,value));$('timeline').style.width=(Number(input.value)*100)+'%';$('zoom-value').textContent=Number(input.value).toFixed(1)+'×';updateRuler();}
$('timeline-zoom').oninput=()=>setZoom(Number($('timeline-zoom').value));
document.addEventListener('keydown',e=>{if(e.defaultPrevented||e.repeat||e.isComposing||e.altKey||e.ctrlKey||e.metaKey||working)return;const t=e.target;if(t.closest('input,textarea,select,a,[contenteditable=true],summary,video'))return;if(e.code==='Space'){e.preventDefault();togglePlay();}else if(['KeyR','Minus'].includes(e.code)){e.preventDefault();setZoom(Number($('timeline-zoom').value)-.5);}else if(['KeyT','Equal','NumpadAdd'].includes(e.code)){e.preventDefault();setZoom(Number($('timeline-zoom').value)+.5);}else if(e.code==='Home'&&$('preview').getAttribute('src')){e.preventDefault();$('preview').currentTime=0;sync(true);}else if(['ArrowLeft','ArrowRight'].includes(e.code)&&$('preview').getAttribute('src')){e.preventDefault();$('preview').currentTime=Math.max(0,Math.min(result?.duration||$('preview').duration,$('preview').currentTime+(e.code==='ArrowRight'?1:-1)*(e.shiftKey?5:1)));sync(true);}});
$('video-file').onchange=()=>{if(result)return;if(localVideoUrl)URL.revokeObjectURL(localVideoUrl);const file=$('video-file').files[0];if(!file)return;localVideoUrl=URL.createObjectURL(file);$('preview').src=localVideoUrl;$('preview').muted=false;$('preview').hidden=false;$('video-placeholder').hidden=true;$('viewer-state').textContent='참조 영상';$('timeline-play').disabled=false;};
const fileUrl=name=>apiBase+'/api/studio/jobs/'+jobId+'/files/'+encodeURIComponent(name)+'?v='+revision+(mediaTicket?'&ticket='+encodeURIComponent(mediaTicket):'');
function status(text){$('analysis-status').hidden=false;$('analysis-status').textContent=text;}
function error(message){$('error').hidden=false;$('error').textContent=message;}
function busy(value){working=value;$('preview').controls=!value;document.querySelectorAll('button,input,select').forEach(el=>{el.disabled=value;});if(value){$('error').hidden=true;$('preview').pause();}else{for(const id of ['listen-wet','listen-dry','add-effect-channel','add-ambience-channel'])$(id).disabled=!result;$('timeline-play').disabled=!$('preview').getAttribute('src');}}
async function request(path,body,method='POST',retried=false){const response=await fetch(apiBase+'/api/studio/'+path,{method,headers:{...(body?{'Content-Type':'application/json'}:{}),...(apiToken?{Authorization:'Bearer '+apiToken}:{})},...(body?{body:JSON.stringify(body)}:{})});const data=await response.json();if(response.status===401&&publicWorker&&!retried){await configureServer();return request(path,body,method,true);}if(!response.ok)throw Error(data.error||'작업을 진행하지 못했어요.');if(data.ticket)mediaTicket=data.ticket;return data;}

async function waitJob(){for(let i=0;i<7200;i++){const data=await request('jobs/'+jobId,null,'GET');if(data.status==='ready')return data.data;if(data.status==='error')throw Error(data.error);status(data.stage||'파일을 처리하고 있어요.');await new Promise(resolve=>setTimeout(resolve,1000));}throw Error('처리가 오래 걸리고 있어요. 서버를 확인하고 다시 열어 주세요.');}
function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
function showRoles(){
 $('import-panel').hidden=true;$('roles-panel').hidden=false;$('job-actions').hidden=false;$('track-roles').replaceChildren();
 for(const track of manifest.tracks){const row=node('div',undefined,'track-role'),label=node('label',track.name+' · '+track.clips.length+'개 클립');const select=node('select');select.id='role-'+track.id;label.htmlFor=select.id;for(const [value,text]of [['dialogue','대사 · 잡음 감소와 레벨 보정'],['original','현장음·기존 소리 · 원본 유지'],['ignore','사용하지 않기']]){const option=node('option',text);option.value=value;select.append(option);}select.value=track.role;row.append(label,select);$('track-roles').append(row);}
 if(!result)drawTimeline();
}
function config(){return{useDialogue,roles:Object.fromEntries(manifest.tracks.map(t=>[t.id,$('role-'+t.id).value])),clean:$('clean').checked,effectChannels:channels.length?channels:undefined,trackGains:{...Object.fromEntries((result?.tracks||[]).map(t=>[t.id,t.gain])),...Object.fromEntries(channels.map(c=>[c.id,c.gain]))}};}
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
 if(video.size>2*1024**3||files.reduce((s,x)=>s+x.file.size,0)>limits.bytes||files.length>64)throw Error(publicWorker?'영상 2GB·전체 8GB·파일 64개 이하여야 해요.':'영상은 2GB, 전체는 6GB, 파일은 64개 이하여야 해요.');
 if(files.some(x=>x.file.size>(x.role==='aaf'?5*1024**3:x.role==='video'?2*1024**3:1024**3)))throw Error('AAF는 5GB, 영상은 2GB, 오디오는 1GB 이하여야 해요.');
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
function ensureAudio(){
 if(!audioContext){audioContext=new (window.AudioContext||window.webkitAudioContext)();masterGain=audioContext.createGain();masterGain.gain.value=1;const guard=audioContext.createDynamicsCompressor();guard.threshold.value=-1;guard.knee.value=0;guard.ratio.value=20;guard.attack.value=.003;guard.release.value=.08;masterGain.connect(guard);guard.connect(audioContext.destination);}
 audioContext.resume().catch(()=>error('소리 재생을 허용한 뒤 다시 재생해 주세요.'));
 for(const a of [...players,originalPlayer,...[...assetPlayers.values()].map(p=>p.audio)].filter(Boolean))if(!a._gain){const source=audioContext.createMediaElementSource(a),gain=audioContext.createGain();source.connect(gain);if(a.dataset.role==='dialogue'){const analyser=audioContext.createAnalyser();analyser.fftSize=1024;gain.connect(analyser);analyser.connect(masterGain);a._analyser=analyser;a._samples=new Float32Array(1024);}else gain.connect(masterGain);a._gain=gain;}
}
function stopPlayers(){playbackGeneration++;cancelAnimationFrame(animationFrame);for(const a of [...players,originalPlayer,...[...assetPlayers.values()].map(p=>p.audio)].filter(Boolean))a.pause();}
function setAudioGain(a,value){if(a._gain)a._gain.gain.setTargetAtTime(value,audioContext.currentTime,.005);else a.volume=Math.min(1,value);}
function dialogueDuck(){if(mode==='dry')return 1;let power=0,found=false;for(const a of players){if(!a._analyser||a.paused)continue;found=true;a._analyser.getFloatTimeDomainData(a._samples);power+=a._samples.reduce((sum,x)=>sum+x*x,0)/a._samples.length;}const rms=Math.sqrt(power),target=!found||rms<=.04?1:(rms/.04)**(-2/3),now=performance.now(),dt=Math.min(.1,(now-lastDuckTime)/1000||.016);lastDuckTime=now;const coefficient=Math.exp(-dt/(target < duckGain ? .015 : .3));duckGain=target+(duckGain-target)*coefficient;return duckGain;}
function sync(force=false){
 updateTransport();const v=$('preview'),time=v.currentTime;document.querySelectorAll('.wave').forEach(el=>el.style.setProperty('--playhead',(time/(result?.duration||manifest?.duration||1)*100)+'%'));
 const base=mode==='dry'?[originalPlayer]:players;
 for(const a of [originalPlayer,...players].filter(Boolean)){
  const active=base.includes(a);if(!active){a.pause();continue;}
  if(a.readyState>0&&(force||Math.abs(a.currentTime-time)>.12))a.currentTime=Math.min(time,a.duration||time);
  setAudioGain(a,1);if(!v.paused&&a.paused&&time<(a.duration||Infinity))a.play().catch(playError);
 }
 const duck=dialogueDuck(),changes=edits();for(const asset of result?.assets||[]){const entry=assetPlayers.get(asset.id);if(!entry)continue;const edited={...asset,...changes.find(e=>e.id===asset.id)},channel=channels.find(c=>c.id===edited.channelId),a=entry.audio;
  const plan=mode==='wet'?SceneSoundEditor.playbackAt(edited,channel,time,a.duration):null;
  if(!plan||v.paused){a.pause();continue;}
  if(a.readyState>0&&(force||Math.abs(a.currentTime-plan.offset)>.12))a.currentTime=plan.offset;
  setAudioGain(a,plan.gain*duck);if(a.paused)a.play().catch(playError);
 }
}
let lastPlayError=0;
function playError(e){if(e.name==='AbortError'||working)return;if(Date.now()-lastPlayError>5000){lastPlayError=Date.now();error('소리를 불러오지 못했어요. 잠시 후 다시 재생해 주세요.');}}
function frame(){if($('preview').paused)return;sync();animationFrame=requestAnimationFrame(frame);}
async function play(){updateTransport();if(working){$('preview').pause();return;}if(!result)return;ensureAudio();sync(true);cancelAnimationFrame(animationFrame);animationFrame=requestAnimationFrame(frame);}
$('preview').onplay=play;$('preview').onpause=()=>{stopPlayers();updateTransport();};$('preview').onloadedmetadata=updateTransport;$('preview').onseeking=()=>sync(true);$('preview').ontimeupdate=()=>{if($('preview').paused)sync();};$('preview').onended=stopPlayers;
function listen(which){mode=which;stopPlayers();$('listen-wet').setAttribute('aria-pressed',String(mode==='wet'));$('listen-dry').setAttribute('aria-pressed',String(mode==='dry'));$('play-status').textContent=mode==='dry'?'AAF 원본을 듣고 있어요.':'최신 편집을 바로 듣고 있어요. 다운로드할 때 파일을 준비해요.';if(!$('preview').paused)play();}
$('listen-wet').onclick=()=>listen('wet');$('listen-dry').onclick=()=>listen('dry');
function numberField(label,value,attrs){const wrap=node('label',label),input=node('input');input.type='number';Object.assign(input,attrs);input.value=value;wrap.append(input);return{wrap,input};}
function edits(){return[...document.querySelectorAll('.sound-edit')].map(el=>({id:el.dataset.id,start:Number(el.querySelector('[data-field=start]').value),end:Number(el.querySelector('[data-field=end]').value),gain:Number(el.querySelector('[data-field=gain]').value),enabled:el.querySelector('[data-field=enabled]').checked,channelId:el.querySelector('[data-field=channelId]').value}));}
async function remix(replace){if(working)return;busy(true);try{const time=$('preview').currentTime;const changes=edits();if(changes.some(a=>!Number.isFinite(a.start)||!Number.isFinite(a.end)||!Number.isFinite(a.gain)||a.start<0||a.end>result.duration||a.end<=a.start||a.gain< -60||a.gain>6))throw Error('시작·끝과 음량을 확인해 주세요. 끝은 시작보다 뒤여야 해요.');saveEditor();await request('jobs/'+jobId+'/remix',{...config(),edits:changes,...(replace?{replace}:{})});result=await waitJob();showResult();$('preview').currentTime=time;status('수정한 초안과 내보내기 파일을 만들었어요.');}catch(e){error(e.message);}finally{busy(false);}}

function showResult(){
 $('error').hidden=true;stopPlayers();players=[];$('audio-players').replaceChildren();originalPlayer?.remove();revision++;
 if(localVideoUrl){URL.revokeObjectURL(localVideoUrl);localVideoUrl=null;}
 $('preview').src=fileUrl('preview.mp4');$('preview').hidden=false;$('video-placeholder').hidden=true;$('viewer-state').textContent='사운드 초안';$('preview').muted=true;$('preview').playbackRate=1;
 $('preview').onratechange=()=>{for(const a of [...players,originalPlayer,...[...assetPlayers.values()].map(p=>p.audio)].filter(Boolean))a.playbackRate=$('preview').playbackRate;};
 originalPlayer=new Audio();originalPlayer.crossOrigin='anonymous';originalPlayer.src=fileUrl('original.wav');originalPlayer.preload='metadata';originalPlayer.dataset.trackPlayer='original';$('audio-players').append(originalPlayer);
 $('result-panel').hidden=false;$('summary').textContent=result.summary;
 for(const t of result.tracks.filter(t=>!['effect','ambience'].includes(t.role))){const audio=new Audio();audio.crossOrigin='anonymous';audio.src=fileUrl(t.export);audio.preload='auto';audio.dataset.trackPlayer=t.id;audio.dataset.role=t.role;audio.muted=t.gain<=-60;$('audio-players').append(audio);players.push(audio);}
 const initialized=SceneSoundEditor.initialChannels(result.assets,result.tracks,result.assets.every(a=>a.channelId)?result.effectChannels:undefined);channels=initialized.channels;result.assets=initialized.assets;
 let saved;try{saved=JSON.parse(sessionStorage.getItem(savedEditorKey()));}catch{}
 const restore=saved?.renderDirectory===result.renderDirectory;
 if(restore){try{channels=SceneSoundEditor.validateChannels(saved.channels);result.assets=result.assets.map(a=>({...a,...saved.edits.find(e=>e.id===a.id)}));}catch{saved=null;}}
 for(const p of assetPlayers.values())p.audio.remove();assetPlayers.clear();
 $('sound-edits').replaceChildren();
 for(const asset of result.assets){
 const audio=new Audio();audio.dataset.assetPlayer=asset.id;audio.crossOrigin='anonymous';audio.src=fileUrl(asset.file);audio.preload='auto';audio.loop=asset.role==='ambience';audio.onloadedmetadata=()=>sync(true);audio.onerror=()=>playError({name:'NetworkError'});$('audio-players').append(audio);assetPlayers.set(asset.id,{audio});
 const card=node('div',undefined,'sound-edit');card.dataset.id=asset.id;card.append(node('strong',asset.title+' · '+(asset.role==='effect'?'효과음':'배경음')),node('div',asset.name+' / '+asset.creator+' / '+asset.library,'note'));
 const links=node('p',undefined,'note');for(const [text,url]of [['음원 원본',asset.source],[asset.license,asset.licenseUrl]]){const a=node('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';links.append(a);}card.append(links);
 const fields=node('div',undefined,'edit-fields');
 for(const [key,label,value,min,max,step]of [['start','시작 · 초',asset.start,0,result.duration,'.01'],['end','끝 · 초',asset.end,0,result.duration,'.01'],['gain','소리 음량 · dB',asset.gain,-60,6,'1']]){
 const f=numberField(label,Number(value.toFixed(2)),{min:String(min),max:String(max),step});f.input.dataset.field=key;
 f.input.oninput=()=>{markDirty();if(key!=='gain')updateAssetBlock(asset.id);};fields.append(f.wrap);
 }
 const channelLabel=node('label','채널'),channelSelect=node('select');channelSelect.dataset.field='channelId';for(const c of channels.filter(c=>c.role===asset.role)){const o=node('option',c.name);o.value=c.id;channelSelect.append(o);}channelSelect.value=asset.channelId;channelSelect.onchange=()=>{markDirty();drawTimeline();selectAsset(asset.id);};channelLabel.append(channelSelect);fields.append(channelLabel);
 const label=node('label',' 사용하기'),enabled=node('input');enabled.type='checkbox';enabled.checked=asset.enabled;enabled.dataset.field='enabled';enabled.onchange=()=>{markDirty();updateAssetBlock(asset.id);};label.prepend(enabled);fields.append(label);
 const button=node('button','다른 음원 추천받기','secondary');button.type='button';button.onclick=()=>remix(asset.id);fields.append(button);card.append(fields);$('sound-edits').append(card);
 }
 resetDirty();drawTimeline();if(restore&&saved)markDirty();else if(channels.some(c=>!result.tracks.some(t=>t.id===c.id)))markDirty();selectAsset(result.assets.some(a=>a.id===selectedAssetId)?selectedAssetId:null);
 $('warnings').replaceChildren();for(const text of result.warnings)$('warnings').append(node('li',text));
 for(const [id,name]of [['download-all','SceneSound.zip'],['download-mix','mix.wav'],['download-aaf','SceneSound.aaf'],['download-video','preview.mp4']]){$(id).href=fileUrl(name)+'&download=1';$(id).download=name;$(id).onclick=async e=>{if(working||exporting){e.preventDefault();return;}if(!dirty)return;e.preventDefault();exporting=true;try{await remix();if(!dirty){const link=document.createElement('a');link.href=fileUrl(name)+'&download=1';link.download=name;link.click();}}finally{exporting=false;}};}
 $('timeline-hint').textContent='위치·길이·음량·채널 변경은 재생에 바로 반영돼요. 다운로드 시 최신 편집으로 파일을 준비해요. 라이브 미리 듣기와 최종 믹스는 덕킹·피크 보호 방식으로 차이가 날 수 있어요.';
 for(const id of ['listen-wet','listen-dry','add-effect-channel','add-ambience-channel','timeline-play'])$(id).disabled=working;
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
 const duration=result?.duration||manifest?.duration;if(!duration)return;$('timeline').replaceChildren();
 const rulerRow=node('div',undefined,'ruler-row');rulerRow.append(node('span','TRACKS','ruler-label'));const ruler=node('div',undefined,'ruler');ruler.onclick=e=>scrub(e,ruler);rulerRow.append(ruler);$('timeline').append(rulerRow);
 const list=channels.length?channels:[{id:'effect',role:'effect',name:'효과음 1',gain:0},{id:'ambience',role:'ambience',name:'배경음 1',gain:0}];
 const edited=edits();
 for(const t of list){
  const row=node('div',undefined,'track-row '+t.role),label=node('div',undefined,'track-controls');row.dataset.channelId=t.id;
  label.append(node('strong',t.name,'track-name'));
  if(result){
   const mixer=node('div',undefined,'track-mixer'),mute=node('button','M','mute-button'),gain=numberField('dB',t.gain,{min:'-60',max:'6',step:'1'});gain.input.dataset.trackGain=t.id;mute.type='button';mute.setAttribute('aria-label',t.name+' 음소거');mute.setAttribute('aria-pressed',String(t.gain<=-60));let savedGain=t.gain>-60?t.gain:0;
   mute.onclick=()=>{const muted=t.gain>-60;if(muted)savedGain=t.gain;t.gain=muted?-60:savedGain;gain.input.value=t.gain;mute.setAttribute('aria-pressed',String(muted));row.classList.toggle('muted',muted);markDirty();};
   gain.input.oninput=()=>{const value=Number(gain.input.value);if(!gain.input.validity.valid||!Number.isFinite(value))return;t.gain=value;mute.setAttribute('aria-pressed',String(value<=-60));row.classList.toggle('muted',value<=-60);markDirty();};
   const rename=node('button','이름','channel-rename');rename.type='button';rename.setAttribute('aria-label',t.name+' 이름 바꾸기');rename.onclick=()=>{const name=prompt('채널 이름',t.name);if(name?.trim()&&name.trim().length<=60){t.name=name.trim();refreshChannelChoices();drawTimeline();markDirty();}};mixer.append(mute,gain.wrap,rename);label.append(mixer);row.classList.toggle('muted',t.gain<=-60);
  }
  const lane=node('div',undefined,'wave');lane.dataset.channelId=t.id;lane.onclick=e=>{if(e.target===lane)scrub(e,lane);};
  const assets=(result?.assets||[]).filter(a=>(edited.find(e=>e.id===a.id)?.channelId||a.channelId||a.role)===t.id);
  for(const asset of assets){const block=node('button',undefined,'clip editable');block.type='button';block.dataset.assetId=asset.id;block.append(node('span',asset.title,'clip-title'));for(const side of ['start','end']){const h=node('span',undefined,'trim-handle '+side);h.dataset.trim=side;h.setAttribute('aria-hidden','true');block.append(h);}block.onclick=()=>selectAsset(asset.id);block.onpointerdown=e=>beginDrag(e,asset.id,lane,block);lane.append(block);}
  if(!assets.length)lane.append(node('span','소리를 선택한 뒤 이 채널로 옮겨 보세요.','channel-empty'));
  row.append(label,lane);$('timeline').append(row);
 }
 for(const asset of result?.assets||[])updateAssetBlock(asset.id);selectAsset(selectedAssetId);updateRuler();
}
function updateRuler(){const ruler=$('timeline').querySelector('.ruler'),duration=result?.duration||manifest?.duration;if(!ruler||!duration)return;const count=Math.max(2,Math.min(12,Math.floor(ruler.clientWidth/100)));ruler.replaceChildren();for(let i=0;i<=count;i++){const t=Math.round(duration*i/count*10)/10,whole=Math.floor(t),fraction=Math.round((t-whole)*10);ruler.append(node('span',formatTime(whole)+(fraction?'.'+fraction:'')));}}
window.addEventListener('resize',updateRuler);
function refreshChannelChoices(){for(const a of result?.assets||[]){const select=assetCard(a.id)?.querySelector('[data-field=channelId]');if(!select)continue;const previous=select.value;select.replaceChildren();for(const c of channels.filter(c=>c.role===a.role)){const o=node('option',c.name);o.value=c.id;select.append(o);}select.value=previous;}}
function addChannel(role){if(!result||working)return;if(channels.length>=16){error('채널은 합계 16개까지 추가할 수 있어요.');return;}channels.push({id:role+'-'+crypto.randomUUID().replaceAll('-','').slice(0,12),role,name:(role==='effect'?'효과음':'배경음')+' '+(channels.filter(c=>c.role===role).length+1),gain:0});refreshChannelChoices();drawTimeline();markDirty();}
$('add-effect-channel').onclick=()=>addChannel('effect');$('add-ambience-channel').onclick=()=>addChannel('ambience');
function beginDrag(e,id,lane,block){
 if(working||e.button!==0)return;selectAsset(id);const card=assetCard(id),startField=card.querySelector('[data-field=start]'),endField=card.querySelector('[data-field=end]');
 const initialStart=Number(startField.value),initialEnd=Number(endField.value),x=e.clientX,scale=result.duration/lane.getBoundingClientRect().width,trim=e.target.dataset.trim;
 let moved=false;block.setPointerCapture(e.pointerId);
 const move=event=>{const delta=(event.clientX-x)*scale;if(Math.abs(event.clientX-x)<3&&!moved)return;if(!moved)$('preview').pause();moved=true;let start=initialStart,end=initialEnd;
 if(trim==='start')start=Math.max(0,Math.min(initialEnd-.05,initialStart+delta));else if(trim==='end')end=Math.max(initialStart+.05,Math.min(result.duration,initialEnd+delta));else{start=Math.max(0,Math.min(result.duration-(initialEnd-initialStart),initialStart+delta));end=start+initialEnd-initialStart;}
 startField.value=(Math.round(start*100)/100).toFixed(2);endField.value=Math.min(result.duration,Math.round(end*100)/100);markDirty();updateAssetBlock(id);};
 const finish=()=>{block.removeEventListener('pointermove',move);block.removeEventListener('pointerup',finish);block.removeEventListener('pointercancel',cancel);};
 const cancel=()=>{startField.value=initialStart;endField.value=initialEnd;updateAssetBlock(id);markDirty();finish();};
 block.addEventListener('pointermove',move);block.addEventListener('pointerup',finish);block.addEventListener('pointercancel',cancel);
}
$('delete-job').onclick=async()=>{if(working)return;try{stopPlayers();$('preview').removeAttribute('src');$('preview').load();await request('jobs/'+jobId,null,'DELETE');sessionStorage.removeItem(savedEditorKey());sessionStorage.removeItem('scenesound-effects-job');channels=[];jobId=null;manifest=null;result=null;$('roles-panel').hidden=true;$('result-panel').hidden=true;$('job-actions').hidden=true;$('import-form').reset();$('import-panel').hidden=false;$('preview').hidden=true;$('video-placeholder').hidden=false;$('viewer-state').textContent='파일을 기다리는 중';$('timeline').innerHTML=emptyTimeline;$('sound-edits').replaceChildren();selectedAssetId=null;selectAsset(null);resetDirty();busy(false);updateTransport();status('임시 작업 파일을 삭제했어요. 새 편집본을 선택해 주세요.');}catch(e){error(e.message);}};
(async()=>{$('import-button').disabled=true;try{await configureServer();const info=await request('status',null,'GET');if(!info.editorVersion)throw Error('사운드 편집 서버를 업데이트하고 있어요. 잠시 후 다시 열어 주세요.');$('engine-status').textContent=info.ready?(publicWorker?'공개 처리 서버 연결됨 · 첫 연결은 서버가 깨어날 때까지 잠시 걸릴 수 있어요.':'로컬 처리 엔진 연결됨 · AAF와 오디오는 이 컴퓨터에서 처리해요.'):'처리 엔진을 설치해 주세요. README의 Studio 실행 안내를 확인하세요.';$('import-button').disabled=!info.ready;
 const stored=sessionStorage.getItem('scenesound-effects-job');if(stored){jobId=stored;const existing=await request('jobs/'+jobId,null,'GET');useDialogue=existing.dialogueReady===true;if(useDialogue){document.body.classList.add('has-dialogue');$('aaf-file').required=false;$('aaf-file').closest('label').hidden=true;$('audio-files').closest('details').hidden=true;$('import-button').textContent='참조 영상 연결';$('roles-panel').querySelector('h2').textContent='1단계 대사 정리 완료';$('import-panel').querySelector('h2').textContent='참조 영상 추가';$('video-placeholder').querySelector('.note').textContent='정리한 대사에 맞는 참조 영상을 추가해 주세요.';$('process-button').textContent='효과음·배경음 분석하고 배치';}if(existing.manifest){manifest=existing.manifest;showRoles();for(const t of manifest.tracks){if(existing.settings?.roles?.[t.id])$('role-'+t.id).value=existing.settings.roles[t.id];}if(existing.settings)$('clean').checked=existing.settings.clean;if(useDialogue&&!manifest.video)$('import-panel').hidden=false;}if(existing.status==='processing'){busy(true);const data=await waitJob();if(data.mode!=='dialogue'&&data.tracks?.[0]?.waveform){result=data;showResult();}else{manifest=data;showRoles();}busy(false);}else if(existing.data?.mode!=='dialogue'&&existing.data?.tracks?.[0]?.waveform){result=existing.data;showResult();}status('이전 작업을 복원했어요.');}
 }catch{sessionStorage.removeItem(savedEditorKey());sessionStorage.removeItem('scenesound-effects-job');channels=[];jobId=null;manifest=null;result=null;stopPlayers();$('sound-edits').replaceChildren();selectAsset(null);resetDirty();$('timeline').innerHTML=emptyTimeline;$('roles-panel').hidden=true;$('result-panel').hidden=true;$('job-actions').hidden=true;try{const info=await request('status',null,'GET');if(!info.editorVersion){$('import-button').disabled=true;$('engine-status').textContent='사운드 편집 서버를 업데이트하고 있어요. 잠시 후 다시 열어 주세요.';return;}busy(false);$('import-button').disabled=!info.ready;$('engine-status').textContent=info.ready?(publicWorker?'공개 서버 연결됨 · 이전 작업이 만료됐어요. 파일을 다시 선택해 주세요.':'로컬 처리 엔진 연결됨 · 이전 세션이 만료됐어요. 파일을 다시 선택해 주세요.'):'처리 엔진을 설치해 주세요.';}catch{$('engine-status').textContent=location.hostname==='127.0.0.1'?'로컬 처리 서버에서 열어 주세요. npm run dev → /studio.html':'공개 작업 서버에 연결하지 못했어요. 잠시 후 새로고침해 주세요.';}}})();
