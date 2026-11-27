'use strict';
(()=>{
const root=document.querySelector('[data-usage-guide]');if(!root)return;
const modes={
 automatic:{name:'간편 자동 정리',tag:'복잡한 설정 없이 통 WAV가 필요할 때',file:'영상 · 오디오 · AAF',href:'/auto-dialogue.html',cta:'간편 자동 정리 시작',steps:[['파일 하나 올리기','영상, 오디오 또는 원본 소리가 포함된 AAF 하나를 골라요.'],['자동으로 대사 정돈하기','클리핑 의심 구간은 복원을 시도하고, 일정한 잡음은 가볍게 줄여요.'],['원본과 바꿔 들어보기','같은 재생 위치에서 원본과 처리본을 비교해요. 원래 느낌을 더 살리고 싶다면 약하게 다시 정리하세요.'],['통 WAV 받아 편집하기','원래 길이를 유지한 48kHz·24bit 모노 WAV를 받아 영상 편집에 넣어요.']],note:'심한 왜곡·음악·겹친 목소리는 완전히 복구하거나 분리하지 못해요.'},
 aaf:{name:'원본 AAF 편집',tag:'Pro Tools에서 클립 편집을 이어가고 싶을 때',file:'원본 PCM AAF + 참조 영상',href:'/dialogue.html',cta:'원본 AAF 편집 시작',steps:[['AAF·참조 영상 가져오기','원본 오디오가 내장된 AAF와 시작점이 맞는 영상을 넣어요.'],['영상 씬과 목소리 분류 확인','영상으로 씬을 제안받고 대사·왈라 후보를 팝업에서 확인해요. 시간은 입력하지 않아도 돼요.'],['씬별 트랙·룸톤·페이드 정리','같은 씬은 DIA, 겹침은 AUX, 왈라는 DIA B로 모아요. 기준 대사와 룸톤을 맞추고 안전한 페이드를 넣어요.'],['원본 보존 AAF로 이어 편집','원본 미디어와 개별 클립을 유지한 AAF를 받아요. Pro Tools에서 Import Clip Gain을 켜고 가져오세요.']],note:'OMF는 원본 비교용이에요. Pro Tools에서 평소에는 뮤트하고, 비교할 때만 켜 주세요.'},
 curation:{name:'사운드 큐레이션',tag:'장면에 어울리는 효과음과 배경음이 필요할 때',file:'영상 파일 · AAF는 선택',href:'/studio.html',cta:'사운드 큐레이션 시작',steps:[['장면이 담긴 영상 올리기','영상만으로 시작할 수 있어요. AAF가 있다면 함께 넣어 사용할 원본 트랙을 확인하세요.'],['효과음과 배경음 추천받기','장면을 분석해 필요한 소리를 찾고, 효과음·배경음 트랙에 나눠 초안을 배치해요.'],['듣고, 옮기고, 바꿔보기','소리를 골라 위치·길이·음량을 조정해요. 마음에 들지 않으면 다른 추천을 받아요. 변경은 재생에 바로 반영돼요.'],['확인한 초안 내려받기','소리를 입힌 영상, WAV 또는 AAF로 받아 편집을 이어가요. 음원별 이용 조건도 확인해 주세요.']],note:'라이브러리 미리 듣기 음원을 쓴 초안이에요. 공개 콘텐츠에 쓰기 전 출처·이용 조건을 확인하세요.'}
};
let mode='automatic',step=0,playing=!matchMedia('(prefers-reduced-motion: reduce)').matches,timer,onscreen=false;
const $=s=>root.querySelector(s),tabs=[...root.querySelectorAll('[data-guide-mode]')];
function text(x,y,value,size=16,fill='#d9d7e7'){return `<text x="${x}" y="${y}" font-size="${size}" fill="${fill}">${value}</text>`;}
function rect(x,y,w,h,fill,stroke='#393849',r=8){return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}"/>`;}
function bars(x,y,w,h,color,count=54,quiet=false){let s='';for(let i=0;i<count;i++){let a=quiet?4+Math.sin(i*2.4)**2*7:6+Math.sin(i*.73)**2*(h*.7)*(i%17<4?.35:1);s+=`<path d="M${(x+i*w/count).toFixed(2)} ${(y+(h-a)/2).toFixed(2)}v${a.toFixed(2)}" stroke="${color}" stroke-width="2"/>`;}return s;}
function clip(x,y,w,label,color='#b9a6ff',fill='#39304f'){return rect(x,y,w,49,fill,color,5)+bars(x+7,y+20,w-14,24,color,Math.max(8,Math.floor(w/7)))+text(x+9,y+15,label,12,'#f0edf8');}
function top(title){return rect(1,1,678,348,'#14151d','#3c3b4b',14)+`<path d="M1 47H679" stroke="#343441"/>`+`<circle cx="22" cy="24" r="4" fill="#8774c3"/>`+text(36,29,title,14)+text(567,29,'SceneSound',12,'#a8a3bb');}
function fileCard(ext,label){return rect(258,102,164,146,'#272333','#70628e',13)+text(282,141,ext,26,'#d3c5ff')+`<path d="M286 164h107m-107 14h76" stroke="#8e82a9" stroke-width="3"/>`+text(280,222,label,14);}
function upload(title,ext,label){return top(title)+`<rect x="70" y="75" width="540" height="231" rx="12" fill="none" stroke="#514961" stroke-dasharray="6 6"/>`+fileCard(ext,label)+text(213,285,'파일을 골라 시작해요',17,'#d5c9ff');}
function timeline(kind){let s=top(kind==='aaf'?'개별 클립은 그대로, 연결은 자연스럽게':'효과음과 배경음은 각각 다른 트랙에');s+=text(117,77,'00:00',12,'#8e8ca2')+text(325,77,'00:05',12,'#8e8ca2')+text(551,77,'00:10',12,'#8e8ca2');for(let j=0;j<3;j++){s+=text(22,125+j*67,kind==='aaf'?['대사 1','대사 2','비교용'][j]:['효과음 1','효과음 2','배경음'][j],13,'#bdb7cf');s+=rect(106,92+j*67,549,58,'#1a1b24','#292a36',4);}return s;}
function art(){let s='';if(step===0)return upload(modes[mode].name,mode==='aaf'?'AAF':mode==='curation'?'VIDEO':'WAV / AAF',mode==='aaf'?'원본 오디오 포함':mode==='curation'?'내 영상 파일':'내 대사 파일');
if(mode==='automatic'){
 if(step===1){s=top('가벼운 잡음 정리 · 필요한 구간만 디클립');s+=text(30,91,'원본 소리',14,'#bdb7cf')+rect(30,104,620,84,'#22212e')+bars(42,115,596,60,'#9e90bd');s+=`<rect x="270" y="104" width="91" height="84" rx="5" fill="#e7b46b" fill-opacity=".12" stroke="#d5a164"/>`+text(245,211,'클리핑 의심 구간 확인',14,'#e6be88');s+=rect(30,238,620,55,'#252134','#70618d')+bars(44,245,590,40,'#c1aaff')+`<path class="guide-scan" d="M55 102v190" stroke="#c4b1ff" stroke-width="2"/>`;}
 if(step===2){s=top('같은 위치에서 원본과 처리본 비교');s+=rect(30,70,139,32,'#30283f','#9f86d3',16)+text(49,92,'정리한 대사',14,'#e0d3ff')+rect(180,70,122,32,'#1e1e29','#454151',16)+text(199,92,'원본 비교본',14);s+=text(31,137,'원본',14)+rect(100,112,548,65,'#22212b')+bars(112,119,522,49,'#9b91ac');s+=text(31,230,'처리본',14)+rect(100,204,548,65,'#282337')+bars(112,211,522,49,'#c7b2ff');s+=`<path class="guide-playhead" d="M182 107v172" stroke="#d0b7ff" stroke-width="2"/>`+text(100,310,'음량과 작은 대사가 자연스러운지 들어보세요',15,'#bdb7cf');}
 if(step===3){s=top('확인했다면, 통 WAV로 받아 가세요');s+=fileCard('WAV','정리한 대사')+text(199,286,'48kHz · 24bit · 모노 · 원래 길이 유지',15,'#cdbce8');}
}else if(mode==='aaf'){
 s=timeline('aaf');s+=clip(116,98,158,'기준 클립')+clip(275,98,175,'대사 클립')+clip(449,98,195,'대사 클립');s+=clip(321,165,185,'겹친 대사는 유지','#9ca9d8','#29334e');s+=rect(116,232,528,48,'#272832','#50505c',5)+bars(125,243,505,27,'#7c7e91');
 if(step===1)s+=`<rect x="114" y="96" width="162" height="53" rx="6" fill="none" stroke="#e1cdff" stroke-width="2"/>`+text(116,314,'기준 대사 먼저 맞춤 · 나머지는 룸톤에 연결',15,'#d0b9f1');
 if(step===2)s+=`<path d="M255 101l40 45m-40 0l40-45M430 101l40 45m-40 0l40-45" stroke="#e1caff" stroke-width="2"/>`+text(116,314,'같은 녹음의 겹침은 equal-gain 페이드',15,'#d0b9f1');
 if(step===3)s+=rect(151,285,476,43,'#30263f','#8d74b7',8)+text(172,312,'AAF  ·  원본 미디어 + 개별 클립 + 게인·페이드',15,'#e4d2ff');
}else{
 s=timeline('curation');s+=clip(step===2?193:138,98,152,'문 여는 소리','#94cdb5','#254239')+clip(410,165,165,'발소리','#8ac0df','#263d4e')+clip(116,232,528,'실내 공간음','#c6b0e7','#393044');
 if(step===1)s+=text(116,314,'장면에 필요한 소리를 찾아 초안에 배치해요',15,'#add9c5');
 if(step===2)s+=`<rect x="191" y="96" width="156" height="53" rx="7" fill="none" stroke="#e1f2e9" stroke-width="2"/>`+text(116,314,'위치 · 길이 · 음량 조정 / 다른 음원 추천',15,'#add9c5');
 if(step===3)s+=rect(145,284,490,44,'#203a31','#669b84',8)+text(173,312,'소리 입힌 영상   /   믹스 WAV   /   AAF',16,'#c7ead9');
}return s;}
function schedule(){clearTimeout(timer);root.dataset.motion=playing&&onscreen&&!document.hidden?'running':'paused';if(playing&&onscreen&&!document.hidden)timer=setTimeout(()=>{step=(step+1)%4;render();},4800);}
function render(){const d=modes[mode];root.dataset.mode=mode;tabs.forEach(t=>{let active=t.dataset.guideMode===mode;t.setAttribute('aria-selected',active);t.tabIndex=active?0:-1;});$('#guide-panel').setAttribute('aria-labelledby','guide-tab-'+mode);$('#guide-tag').textContent=d.tag;$('#guide-file').textContent=d.file;$('#guide-figure').innerHTML=`<svg viewBox="0 0 680 350" role="img" aria-label="${d.name}: ${d.steps[step][0]}" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system, BlinkMacSystemFont, sans-serif">${art()}</svg>`;$('#guide-caption').textContent=d.steps[step][0];$('#guide-steps').innerHTML=d.steps.map((v,i)=>`<li><button type="button" data-guide-step="${i}" ${i===step?'aria-current="step"':''}><span class="guide-step-index">${i+1}</span><span><strong>${v[0]}</strong><span class="guide-step-copy">${v[1]}</span></span></button></li>`).join('');$('#guide-note').textContent=d.note;$('#guide-start').textContent=d.cta;$('#guide-start').href=d.href;$('#guide-toggle').textContent=playing?'자동 재생 멈추기':'자동 재생하기';$('#guide-count').textContent=(step+1)+' / 4';schedule();}
function choose(t){mode=t.dataset.guideMode;step=0;render();}
tabs.forEach((t,i)=>{t.addEventListener('click',()=>choose(t));t.addEventListener('keydown',e=>{let n=e.key==='ArrowRight'?(i+1)%3:e.key==='ArrowLeft'?(i+2)%3:e.key==='Home'?0:e.key==='End'?2:-1;if(n<0)return;e.preventDefault();choose(tabs[n]);tabs[n].focus();});});
$('#guide-steps').addEventListener('click',e=>{const button=e.target.closest('[data-guide-step]');if(!button)return;step=Number(button.dataset.guideStep);playing=false;render();$('#guide-steps').querySelector(`[data-guide-step="${step}"]`).focus({preventScroll:true});});
$('#guide-toggle').addEventListener('click',()=>{playing=!playing;render();});
$('#guide-next').addEventListener('click',()=>{step=(step+1)%4;playing=false;render();});
new IntersectionObserver(entries=>{onscreen=entries[0].isIntersecting;schedule();},{threshold:.15}).observe(root);
document.addEventListener('visibilitychange',schedule);
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',e=>{if(e.matches){playing=false;render();}});
render();
})();
