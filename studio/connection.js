'use strict';
(()=>{
const origin='https://scenesound-mvp.vercel.app',base='http://127.0.0.1:8001',storageKey='scenesound-local-connection';
let connection;
try{const fragment=new URLSearchParams(location.hash.slice(1)),value=fragment.get('local');if(value&&location.origin===origin){if(!/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value)||value.length>2048)throw Error('연결 권한 형식을 확인해 주세요.');sessionStorage.setItem(storageKey,JSON.stringify({token:value,expires:Date.now()+86400000}));history.replaceState(null,'',location.pathname+location.search);}const saved=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(location.origin===origin&&saved?.expires>Date.now()&&typeof saved.token==='string')connection={base,token:saved.token};}catch{sessionStorage.removeItem(storageKey);}
window.SceneSoundConnection={local:connection,key:name=>connection?name+'-local':name};
const box=document.getElementById('processing-location');if(!box)return;
const tool=location.pathname.includes('auto-dialogue')?'automatic':'dialogue';
const title=document.createElement('strong');title.textContent=connection?'내 컴퓨터에서 처리하도록 연결했어요':location.hostname==='127.0.0.1'?'이 컴퓨터에서 처리 중이에요':'큰 AAF는 내 컴퓨터에서 처리하세요';
const note=document.createElement('p');note.className='note';note.textContent=connection?'AAF와 결과는 이 컴퓨터에만 저장해요. 처리·다운로드가 끝날 때까지 로컬 서버와 이 창을 켜 두세요. 자동으로 공개 서버로 전환하지 않아요.':location.hostname==='127.0.0.1'?'AAF와 결과는 이 컴퓨터에서 처리해요. 영상 씬 분석은 별도 외부 AI 경로를 사용해요.':'무료로 AAF 5GB까지 입력할 수 있어요. 폴더의 SceneSound-로컬서버.command를 실행한 뒤 연결해 주세요.';
box.append(title,note);
if(location.hostname==='127.0.0.1')return;
const link=document.createElement('a');link.className='secondary';link.href=base+'/connect.html?tool='+tool;link.textContent=connection?'내 컴퓨터 다시 연결':'내 컴퓨터 연결';box.append(link);
if(connection){const disconnect=document.createElement('button');disconnect.type='button';disconnect.className='text-button';disconnect.textContent='공개 서버로 돌아가기';disconnect.onclick=()=>{sessionStorage.removeItem(storageKey);location.reload();};box.append(disconnect);const fallback=document.createElement('a');fallback.href=base+(tool==='automatic'?'/auto-dialogue.html':'/dialogue.html');fallback.onclick=()=>{const id=sessionStorage.getItem(SceneSoundConnection.key(tool==='automatic'?'scenesound-automatic-job':'scenesound-dialogue-job'));if(id&&/^[0-9a-f-]{36}$/.test(id))fallback.href=base+(tool==='automatic'?'/auto-dialogue.html':'/dialogue.html')+'?job='+id;};fallback.className='text-button';fallback.textContent='브라우저가 연결을 막으면 로컬 화면 열기';box.append(fallback);}
})();
