const fs=require('node:fs/promises'),path=require('node:path');
const MESSAGE='공개 서버의 임시 저장공간 한도에 도달했어요. 서버 중단을 막기 위해 멈췄어요. 3~4GB AAF는 로컬 대사 도구에서 처리해 주세요.';
async function directoryBytes(root){let bytes=0;for(const entry of await fs.readdir(root,{withFileTypes:true})){const p=path.join(root,entry.name);try{if(entry.isDirectory())bytes+=await directoryBytes(p);else if(entry.isFile())bytes+=(await fs.stat(p)).size;}catch(e){if(e.code!=='ENOENT')throw e;}}return bytes;}
async function check(root,additional=0,budget=0){if(budget&&await directoryBytes(root)+additional>budget)throw Object.assign(Error(MESSAGE),{status:507});}
module.exports={directoryBytes,check,MESSAGE};
