const test=require('node:test'),assert=require('node:assert/strict');
const commons=require('../lib/commons.cjs'),sounds=require('../api/sounds'),freesound=require('../lib/freesound.cjs');
function item(id,license='cc0',extra={}){return{pageid:id,index:id,title:'File:Rain '+id+'.ogg',imageinfo:[{mime:'application/ogg',size:1000,url:'https://upload.wikimedia.org/wikipedia/commons/rain'+id+'.ogg',descriptionurl:'https://commons.wikimedia.org/wiki/File:Rain_'+id+'.ogg',metadata:[{name:'length',value:5}],extmetadata:{License:{value:license},LicenseShortName:{value:license==='pd'?'Public domain':license},LicenseUrl:{value:'https://creativecommons.org/licenses/by/4.0'},Artist:{value:'<a>Recorder &amp; artist</a>'},...extra}}]};}
async function call(fn,url){const r={setHeader(){},status(c){this.code=c;return this;},json(d){this.data=d;}};await fn({url,method:'GET',headers:{host:'example.test'}},r);return r;}
test('Commons validates licenses, author text, audio destination and excludes pronunciation',async()=>{
 const old=fetch;global.fetch=async()=>({ok:true,json:async()=>({query:{pages:{a:item(1),b:item(2,'cc-by-4.0'),c:item(3,'cc-by-sa-4.0'),d:item(4,'cc0',{Categories:{value:'Pronunciation'}}),e:{...item(5),imageinfo:[{...item(5).imageinfo[0],url:'https://evil.example/a.ogg'}]},f:item(6,'pd')}}})});
 try{const rows=await commons.search('rain');assert.deepEqual(rows.map(x=>x.id),[1,2,6]);assert.equal(rows[0].creator,'Recorder & artist');assert.match(rows[1].license,/출처 표시/);assert.equal(rows[2].license,'퍼블릭 도메인');assert.ok(rows.every(x=>x.library==='Wikimedia Commons'));}finally{global.fetch=old;}
});
test('refresh advances upstream pages and excludes sounds already seen by provider ID',async()=>{
 const old=fetch;const requests=[];process.env.FREESOUND_API_KEY='test-only';
 global.fetch=async url=>{requests.push(url);if(url.hostname==='commons.wikimedia.org')return{ok:true,json:async()=>({query:{pages:{a:item(7),b:item(8)}}})};return{ok:true,json:async()=>({results:[]})};};
 try{const r=await call(sounds,'/api/sounds?q=rain&page=2&exclude=commons%3A7');assert.equal(r.code,200);assert.deepEqual(r.data.candidates.map(x=>x.id),[8]);assert.equal(requests.find(x=>x.hostname==='commons.wikimedia.org').searchParams.get('gsroffset'),'12');assert.equal(requests.find(x=>x.hostname==='freesound.org').searchParams.get('page'),'2');assert.equal(requests.find(x=>x.hostname==='freesound.org').searchParams.get('page_size'),'3');}finally{global.fetch=old;delete process.env.FREESOUND_API_KEY;}
});
test('bad refresh inputs are rejected before any upstream request',async()=>{
 const old=fetch;global.fetch=()=>{throw Error('must not fetch');};try{for(const q of ['page=0','page=51','page=NaN','exclude=evil:5'])assert.equal((await call(sounds,'/api/sounds?q=rain&'+q)).code,400);}finally{global.fetch=old;}
});
test('Commons failure keeps available Freesound results with a warning',async()=>{
 const old=fetch;process.env.FREESOUND_API_KEY='test-only';
 global.fetch=async url=>{if(url.hostname==='commons.wikimedia.org')throw Error('offline');return{ok:true,json:async()=>({results:[{id:99,name:'Rain',username:'Recorder',duration:5,license:'https://creativecommons.org/publicdomain/zero/1.0/',previews:{'preview-hq-mp3':'https://cdn.freesound.org/a.mp3'},url:'https://freesound.org/people/Recorder/sounds/99/'}]})};};
 try{const r=await call(sounds,'/api/sounds?q=rain');assert.equal(r.code,200);assert.equal(r.data.candidates[0].id,99);assert.equal(r.data.warnings.length,1);}finally{global.fetch=old;delete process.env.FREESOUND_API_KEY;}
});
