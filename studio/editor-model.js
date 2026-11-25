(function(root){
'use strict';
const roles=['effect','ambience'];
function validateChannels(channels){
 if(!Array.isArray(channels)||channels.length<1||channels.length>16)throw Error('효과음·배경음 채널은 합계 16개까지 사용할 수 있어요.');
 const seen=new Set();return channels.map(c=>{
  if(!c||!roles.includes(c.role)||typeof c.id!=='string'||!new RegExp('^'+c.role+'(?:-[a-z0-9]{1,24})?$').test(c.id)||seen.has(c.id)||typeof c.name!=='string'||!c.name.trim()||c.name.length>60||!Number.isFinite(c.gain)||c.gain< -60||c.gain>6)throw Error('채널 이름·종류·음량을 확인해 주세요.');
  seen.add(c.id);return{id:c.id,role:c.role,name:c.name.trim(),gain:c.gain};
 });
}
function initialChannels(assets,tracks,provided){
 if(provided?.length)return{channels:validateChannels(provided),assets:assets.map(a=>({...a,channelId:provided.some(c=>c.id===a.channelId&&c.role===a.role)?a.channelId:provided.find(c=>c.role===a.role)?.id||a.role}))};
 const channels=[],assigned=new Map();
 for(const role of roles){const lanes=[];const sorted=assets.filter(a=>a.role===role).slice().sort((a,b)=>a.start-b.start);
  for(const a of sorted){let lane=lanes.findIndex(end=>end<=a.start);if(lane<0)lane=lanes.length;lane=Math.min(lane,7);lanes[lane]=Math.max(lanes[lane]||0,a.end);assigned.set(a.id,lane);}
  for(let i=0;i<Math.max(1,lanes.length);i++)channels.push({id:i?role+'-'+(i+1):role,role,name:(role==='effect'?'효과음':'배경음')+' '+(i+1),gain:tracks.find(t=>t.id===role)?.gain||0});
 }
 return{channels,assets:assets.map(a=>({...a,channelId:assigned.get(a.id)?a.role+'-'+(assigned.get(a.id)+1):a.role}))};
}
function applyEdits(assets,edits,channels,duration){
 if(!Array.isArray(edits)||edits.length>60||new Set(edits.map(e=>e?.id)).size!==edits.length||edits.some(e=>!assets.some(a=>a.id===e?.id)))throw Error('수정할 소리를 확인해 주세요.');
 return assets.map(a=>{const e=edits.find(e=>e.id===a.id)||a,channelId=e.channelId||a.channelId||a.role;
  if(!channels.some(c=>c.id===channelId&&c.role===a.role))throw Error('소리와 채널 종류를 확인해 주세요.');
  if(![e.start,e.end,e.gain].every(Number.isFinite)||e.start<0||e.end<=e.start||e.end>duration||e.gain< -60||e.gain>6)throw Error('배치 위치와 음량을 확인해 주세요.');
  return{...a,start:e.start,end:e.end,gain:e.gain,enabled:e.enabled!==false,channelId};
 });
}
function playbackAt(asset,channel,time,sourceDuration){
 if(![asset.start,asset.end,asset.gain,time,channel?.gain].every(Number.isFinite)||asset.end<=asset.start)return null;
 if(!channel||!asset.enabled||channel.gain<=-60||time<asset.start||time>=asset.end||!Number.isFinite(sourceDuration)||sourceDuration<=0)return null;
 const elapsed=time-asset.start;if(asset.role!=='ambience'&&elapsed>=sourceDuration)return null;
 const length=asset.end-asset.start,fade=Math.min(1,elapsed/.02,(length-elapsed)/.03);
 return{offset:asset.role==='ambience'?elapsed%sourceDuration:elapsed,gain:10**((asset.gain+channel.gain)/20)*Math.max(0,fade)};
}
const api={validateChannels,initialChannels,playbackAt,applyEdits};
if(typeof module!=='undefined')module.exports=api;else root.SceneSoundEditor=api;
})(typeof window==='undefined'?{}:window);
