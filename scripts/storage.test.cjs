const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {check,directoryBytes}=require('../studio/storage.cjs');
test('storage quota uses written job bytes rather than host statfs and reserves incoming bytes',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'scenesound-storage-test-'));
 try{await fs.mkdir(path.join(root,'job'));await fs.writeFile(path.join(root,'job','input'),Buffer.alloc(100));await fs.writeFile(path.join(root,'render'),Buffer.alloc(50));assert.equal(await directoryBytes(root),150);
 await check(root,50,200);await assert.rejects(check(root,51,200),e=>e.status===507&&/저장공간/.test(e.message));await check(root,10000,0);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});
