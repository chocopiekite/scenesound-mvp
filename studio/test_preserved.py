"""Contracts for source-preserving AAF export, separate from legacy renders."""
from pathlib import Path
import hashlib
import json
import math
import tempfile
import unittest
from unittest.mock import patch
import wave
import struct

import aaf2
from test_engine import fixture, engine
import dialogue_preserve as preserved
from speech import Analyzer, matching_gain


class SpeechFixture:
    def classify(self, path, duration, lead, amplitude=1):
        return {'category': 'speech', 'speech': [[0, duration]], 'speechSeconds': duration,
                'maxSpeechProbability': .99, 'noiseFloorDbfs': -50, 'noiseHeadDbfs': -50, 'noiseTailDbfs': -50}

    def levels(self, path, regions, amplitude, engine):
        return {'lufs': -30., 'metric': 'momentary', 'truePeakDbtp': -18.}


class PreservedTests(unittest.TestCase):
    def make(self, root):
        fixture(root)
        with aaf2.open(str(root / 'edit.aaf'), 'rw') as f:
            comp = next(f.content.toplevel())
            original = comp.slots[0]
            duplicate = comp.create_sound_slot(48000)
            duplicate.name = 'DX duplicate'
            duplicate.segment = original.segment.copy()
            # Quiet is NOT silent. Both tracks have the same placement.
            for name, sample in [('silence', 0), ('quiet', 1)]:
                path = root / (name + '.wav')
                with wave.open(str(path), 'wb') as w:
                    w.setparams((1, 3, 48000, 0, 'NONE', 'not compressed'))
                    w.writeframes(int(sample).to_bytes(3, 'little', signed=True) * 48000)
                master = f.create.MasterMob(name)
                f.content.mobs.append(master)
                source = master.import_audio_essence(str(path), edit_rate=48000)
                track = comp.create_sound_slot(48000)
                track.name = name
                track.segment.components.append(f.create.Filler(media_kind='sound', length=7 * 48000))
                track.segment.components.append(master.create_source_clip(source.slot_id, length=48000))
                track.segment.length = 8 * 48000
        return preserved.inspect_job(root, engine)

    def test_media_and_source_clips_survive_gain_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-preserve-') as d:
            root = Path(d)
            manifest = self.make(root)
            digest = hashlib.sha256((root / 'edit.aaf').read_bytes()).hexdigest()
            with aaf2.open(str(root / 'edit.aaf')) as f:
                before = preserved.snapshot(next(f.content.toplevel()))
                media = {str(e.mob_id): preserved.digest_stream(e, engine) for e in f.content.essencedata}
            engine.save(root / 'settings.json', {'roles': {t['id']: 'dialogue' for t in manifest['tracks']}, 'deduplicate': True, 'removeSilence': True})
            with patch.object(preserved, 'Analyzer', SpeechFixture):
                result = preserved.render_dialogue(root, engine)
            report = result['report']
            self.assertEqual(result['exportMode'], 'preservedClipGain')
            self.assertEqual(len(report['duplicates']), 2)
            self.assertEqual(len(report['silences']), 1)
            self.assertEqual(report['retainedClips'], 3)  # 2 voice clips + one nonzero quiet clip
            self.assertTrue(report['sourcePreserved'])
            self.assertEqual(hashlib.sha256((root / 'edit.aaf').read_bytes()).hexdigest(), digest)
            exported = root / result['renderDirectory'] / 'dialogue-clips.aaf'
            with aaf2.open(str(exported)) as f:
                comp = next(f.content.toplevel())
                self.assertEqual(len(comp.slots), 2)  # duplicate and empty track removed
                self.assertEqual({str(e.mob_id): preserved.digest_stream(e, engine) for e in f.content.essencedata}, media)
                first = list(comp.slots[0].segment.components)[0]
                leaf, gain = preserved.ungroup(first)
                self.assertAlmostEqual(20 * math.log10(gain), 6, places=4)
                self.assertEqual(leaf.start, before[0]['components'][0]['start'])
                self.assertEqual(str(leaf.mob_id), before[0]['components'][0]['source'])
                self.assertEqual(leaf.length, 2 * 48000)
                quiet = comp.slots[1]
                self.assertEqual(quiet.name, 'quiet')
                self.assertEqual(quiet.segment.length, 8 * 48000)
            self.assertTrue((root / 'dialogue-approved.wav').is_file())
            self.assertTrue((root / 'dialogue-original.wav').is_file())

    def test_pcm_differences_below_16bit_are_not_duplicates(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-preserve-lsb-') as d:
            root = Path(d)
            with aaf2.open(str(root / 'edit.aaf'), 'w') as f:
                comp = f.create.CompositionMob('24bit LSB test')
                comp.usage = 'Usage_TopLevel'
                f.content.mobs.append(comp)
                for i in (0, 1):
                    path = root / ('take%d.wav' % i)
                    with wave.open(str(path), 'wb') as w:
                        w.setparams((1, 3, 48000, 0, 'NONE', 'not compressed'))
                        w.writeframes(b''.join((10000 + i if n % 2 else -10000 - i).to_bytes(3, 'little', signed=True) for n in range(48000)))
                    mob = f.create.MasterMob('take%d' % i)
                    f.content.mobs.append(mob)
                    src = mob.import_audio_essence(str(path), edit_rate=48000)
                    slot = comp.create_sound_slot(48000)
                    slot.name = 'DX %d' % i
                    slot.segment.components.append(mob.create_source_clip(src.slot_id, length=48000))
            engine.save(root / 'uploads.json', [{'role': 'aaf', 'file': 'edit.aaf', 'name': 'edit.aaf'}])
            m = preserved.inspect_job(root, engine)
            engine.save(root / 'settings.json', {'roles': {t['id']: 'dialogue' for t in m['tracks']}})
            with patch.object(preserved, 'Analyzer', SpeechFixture):
                result = preserved.render_dialogue(root, engine)
            self.assertEqual(result['report']['duplicates'], [])
            self.assertEqual(result['report']['retainedClips'], 2)

    def test_reference_and_walla_lanes_default_to_preserved(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-role-') as d:
            root = Path(d)
            fixture(root)
            with aaf2.open(str(root / 'edit.aaf'), 'rw') as f:
                comp = next(f.content.toplevel())
                comp.slots[0].name = '1 OMF'
                for name in ['DIA 3', 'DIA B 1', 'WALLA', 'FILTER']:
                    slot = comp.create_sound_slot(48000)
                    slot.name = name
                    slot.segment = comp.slots[0].segment.copy()
            m = preserved.inspect_job(root, engine)
            self.assertEqual([t['role'] for t in m['tracks']], ['original', 'dialogue', 'original', 'original', 'dialogue'])

    def test_noise_gain_policy_and_real_local_model(self):
        self.assertEqual(matching_gain(-40, []), (0, 'noiseHoldNoReference', None, False))
        self.assertEqual(matching_gain(-40, [-55, -40])[1], 'noiseHoldConflictingReferences')
        self.assertEqual(matching_gain(-40, [-46, -46]), (-6, 'noiseFloorMatch', -46, False))
        self.assertEqual(matching_gain(-60, [-40])[0], 3)
        import numpy as np
        model = Analyzer()
        self.assertLess(float(model.probabilities(np.zeros(16000, dtype=np.float32)).max()), .2)
        noise = np.random.default_rng(12).normal(0, .003, 16000).astype(np.float32)
        self.assertLess(float(model.probabilities(noise).max()), .2)


if __name__ == '__main__':
    unittest.main()
