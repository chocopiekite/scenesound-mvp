const test=require('node:test'),assert=require('node:assert/strict');
const {validateChannels,initialChannels,playbackAt,applyEdits}=require('../studio/editor-model.js');
const channels=[{id:'effect',role:'effect',name:'SFX 1',gain:0},{id:'effect-2',role:'effect',name:'SFX 2',gain:-6},{id:'ambience',role:'ambience',name:'AMB 1',gain:0}];
const sound={id:'a',role:'effect',start:2,end:5,gain:-12,enabled:true,channelId:'effect'};
test('overlapping recommendations get separate channels while sequential sounds share a lane',()=>{
 const r=initialChannels([sound,{...sound,id:'b',start:3,end:6},{...sound,id:'c',start:6,end:7}],[],null);
 assert.deepEqual(r.assets.map(a=>a.channelId),['effect','effect-2','effect']);assert.equal(r.channels.length,3);
});
test('channel data rejects duplicate IDs, role spoofing, oversized counts and unsafe gains',()=>{
 assert.equal(validateChannels(channels).length,3);
 for(const list of [[channels[0],channels[0]],[{...channels[0],id:'dialogue'}],[{...channels[0],gain:9}],Array(17).fill(channels[0])])assert.throws(()=>validateChannels(list));
});
test('live preview responds to moves, trims, channel gain, disabled clips and looping ambience',()=>{
 assert.equal(playbackAt(sound,channels[0],1,8),null);
 assert.equal(playbackAt(sound,channels[0],5,8),null);
 assert.deepEqual(playbackAt(sound,channels[0],3,8),{offset:1,gain:10**(-12/20)});
 assert.equal(playbackAt(sound,{...channels[0],gain:-60},3,8),null);
 assert.equal(playbackAt({...sound,enabled:false},channels[0],3,8),null);
 assert.equal(playbackAt({...sound,end:8},channels[0],6,2),null);
 assert.equal(playbackAt({...sound,role:'ambience',end:8},channels[2],6.5,2).offset,.5);
 assert.equal(playbackAt({...sound,gain:NaN},channels[0],3,8),null);
 assert.equal(playbackAt(sound,channels[1],3,8).gain,10**(-18/20));
});
test('export edits preserve channel assignment and reject cross-role moves, forged assets and invalid ranges',()=>{
 const edits=[{id:'a',start:1,end:4,gain:-3,enabled:true,channelId:'effect-2'}];
 const r=applyEdits([sound],edits,channels,8);assert.equal(r[0].channelId,'effect-2');assert.equal(r[0].start,1);
 for(const change of [{channelId:'ambience'},{end:9},{start:5},{gain:NaN},{id:'unknown'}])assert.throws(()=>applyEdits([sound],[{...edits[0],...change}],channels,8));
 assert.throws(()=>applyEdits([sound],[edits[0],edits[0]],channels,8));
});
