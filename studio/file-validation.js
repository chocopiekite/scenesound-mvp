(function(root){
 function formatBytes(bytes){return bytes>=1024**3?(bytes/1024**3).toFixed(2)+'GB':(bytes/1024**2).toFixed(1)+'MB';}
 function validateUploadFiles(files,limits){
  if(files.length>64)return '파일은 한 번에 64개까지 올릴 수 있어요. 현재 '+files.length+'개를 선택했어요.';
  const caps={aaf:limits.aafBytes??5*1024**3,video:limits.videoBytes??2*1024**3,audio:limits.audioBytes??1024**3};
  for(const {file,role}of files){if(!file||!Number.isSafeInteger(file.size)||file.size<=0)return '비어 있거나 읽을 수 없는 파일이 있어요. 다시 선택해 주세요.';if(file.size>caps[role])return file.name+' ('+formatBytes(file.size)+')의 용량이 '+formatBytes(caps[role])+' 제한을 넘었어요.';}
  const total=files.reduce((sum,x)=>sum+x.file.size,0);if(total>limits.bytes)return '선택한 파일 합계 '+formatBytes(total)+'가 전체 '+formatBytes(limits.bytes)+' 제한을 넘었어요.';
  return '';
 }
 const api={formatBytes,validateUploadFiles};if(typeof module!=='undefined')module.exports=api;else root.SceneSoundFiles=api;
})(typeof window==='undefined'?{}:window);
