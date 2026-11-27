const test=require('node:test'),assert=require('node:assert/strict');
const {combineAnalysisResults}=require('../studio/video-transfer.js');
test('long-video scene and sound results retain offsets across 10-minute segments',()=>{
 const input=[{offset:0,summary:'a',scenes:[{start:0,title:'a',reason:'a'}],sounds:[{start:1,end:2}]},{offset:600,summary:'b',scenes:[{start:0,title:'b',reason:'b'},{start:25,title:'c',reason:'c'}],sounds:[{start:3,end:4}]}];
 input[1].walla=[{start:4,end:9,reason:'background voices'}];const scene=combineAnalysisResults(input,'scenes');assert.deepEqual(scene.walla.map(w=>[w.start,w.end]),[[604,609]]);assert.deepEqual(scene.scenes.map(s=>s.start),[0,600,625]);assert.match(scene.scenes[1].reason,/분할 분석/);
 const sounds=combineAnalysisResults(input);assert.deepEqual(sounds.sounds.map(s=>[s.start,s.end]),[[1,2],[603,604]]);
});
