from pathlib import Path
import unittest,tempfile,json,wave
from unittest.mock import patch
import numpy as np
import aaf2
from test_engine import engine
from test_reference import FixtureAnalyzer
import dialogue_preserve as p
import dialogue_layout as layout

class SceneLayoutTests(unittest.TestCase):
    def test_scene_lanes_aux_walla_omf_original_media_gain_and_fades(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rate=48000
            x=np.random.default_rng(88).normal(0,.001,rate*20)
            with wave.open(str(root/'source.wav'),'wb') as w:
                w.setparams((1,2,rate,0,'NONE','not compressed'));w.writeframes(np.round(x*32767).astype('<i2').tobytes())
            with aaf2.open(str(root/'edit.aaf'),'w') as f:
                m=f.create.MasterMob('raw');f.content.mobs.append(m);src=m.import_audio_essence(str(root/'source.wav'),edit_rate=rate)
                c=f.create.CompositionMob('scene test');c.usage='Usage_TopLevel';f.content.mobs.append(c)
                main=c.create_sound_slot(rate);main.name='DX'
                for start in [2,6,10]:main.segment.components.append(m.create_source_clip(src.slot_id,start=start*rate,length=4*rate))
                main.segment.length=12*rate
                dup=c.create_sound_slot(rate);dup.name='DX duplicate';dup.segment=main.segment.copy()
                aux=c.create_sound_slot(rate);aux.name='other mic';aux.segment.components.append(f.create.Filler('sound',length=rate));aux.segment.components.append(m.create_source_clip(src.slot_id,start=15*rate,length=rate));aux.segment.components.append(f.create.Filler('sound',length=10*rate));aux.segment.length=12*rate
                walla=c.create_sound_slot(rate);walla.name='DIA B';walla.segment.components.append(f.create.Filler('sound',length=8*rate));walla.segment.components.append(m.create_source_clip(src.slot_id,start=16*rate,length=2*rate));walla.segment.components.append(f.create.Filler('sound',length=2*rate));walla.segment.length=12*rate
                before={str(e.mob_id):p.digest_stream(e,engine) for e in f.content.essencedata}
            engine.save(root/'uploads.json',[{'role':'aaf','file':'edit.aaf'}]);manifest=p.inspect_job(root,engine)
            roles={t['id']:layout.default_role(t['name']) for t in manifest['tracks']}
            engine.save(root/'settings.json',{'roles':roles,'scenes':[{'start':0,'title':'실내'},{'start':8,'title':'야외'}],'regroupScenes':True,'fades':True})
            with patch.object(p,'Analyzer',FixtureAnalyzer):result=p.render_dialogue(root,engine)
            r=result['report'];self.assertTrue(r['sceneRegrouping']);self.assertEqual(len(r['duplicates']),3);self.assertEqual(r['retainedClips'],5)
            names=[t['name'] for t in result['tracks']];self.assertTrue(any('AUX' in n for n in names));self.assertTrue(any(n.startswith('DIA B S02') for n in names));self.assertTrue(any(n.startswith('DIA S02') for n in names));self.assertTrue(r['comparisonTracks']);self.assertEqual(len(r['fades']),1)
            self.assertTrue(r['fades'][0]['samePcm'])
            with aaf2.open(str(root/result['renderDirectory']/'dialogue-clips.aaf')) as f:
                self.assertEqual({str(e.mob_id):p.digest_stream(e,engine) for e in f.content.essencedata},before)
                comp=next(f.content.toplevel());guide=[s for s in comp.slots if s.name.startswith('OMF')];self.assertEqual(len(guide),4)
                b=next(s for s in comp.slots if s.name.startswith('DIA B S02'));leaf,g=p.ungroup(next(c for c in b.segment.components if c.__class__.__name__!='Filler'));self.assertEqual(g,1)
            with wave.open(str(root/'dialogue-approved.wav')) as w:self.assertEqual(w.getnframes(),12*rate)

    def test_boundary_crossing_is_not_split_and_overlap_is_never_dropped(self):
        def row(slot,start,length,role='dialogue'):
            return {'slotId':slot,'componentIndex':0,'start':start,'duration':length,'timelineTicks':int(start*48000),'lengthTicks':int(length*48000),'editRate':'48000','layout':(48000,1,2,960000,0),'layoutRole':role}
        rows=[row(1,0,6),row(2,1,2),row(3,5,3),row(4,6,2,'walla')]
        lanes=layout.allocate(rows,[{'start':0,'title':'A'},{'start':5,'title':'B'}],10)
        self.assertEqual(sum(len(l['rows']) for l in lanes),4);self.assertTrue(rows[0]['crossesScene']);self.assertTrue(rows[1]['auxiliary']);self.assertEqual(rows[3]['laneName'],'DIA B S02')

if __name__=='__main__':unittest.main()
