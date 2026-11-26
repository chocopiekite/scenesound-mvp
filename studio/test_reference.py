from pathlib import Path
import tempfile, json, wave, sys, math
from unittest.mock import patch
import unittest
import numpy as np
import aaf2
import dialogue_reference as reference
import dialogue_preserve as preserved
import dialogue_fades as fades
from test_engine import engine


def row(slot=3, ci=0, **values):
    r = {'slotId': slot, 'componentIndex': ci, 'start': ci * 4, 'duration': 4, 'category': 'speech', 'speechSeconds': 2,
         'before': {'lufs': -26., 'truePeakDbtp': -14., 'metric': 'shortTerm'}, 'topGain': 1, 'totalPeakDbtp': -14,
         'roomtone': {'calibrationDbfs': -55, 'validationDbfs': -55, 'bands': [.1, .3, .4, .2]}, 'name': 'DX', 'clip': ci + 1}
    r.update(values)
    return r


class FixtureAnalyzer:
    def classify(self, path, duration, lead, amplitude=1):
        return {'category': 'speech', 'speech': [[1, 3]], 'speechSeconds': 2, 'maxSpeechProbability': .99,
                'noiseFloorDbfs': -55., 'noiseHeadDbfs': -55., 'noiseTailDbfs': -55.,
                'roomtone': {'calibrationDbfs': -55., 'validationDbfs': -55., 'bands': [.1, .3, .4, .2], 'frames': 10},
                'protectedContext': [[.85, 3.15]], 'contextLead': lead, 'contextTail': 2}

    def levels(self, *args):
        return {'lufs': -26., 'truePeakDbtp': -14., 'metric': 'shortTerm'}


class ReferenceTests(unittest.TestCase):
    def test_reference_then_roomtone_not_independent_speech_targets(self):
        anchor, other = row(), row(ci=1, before={'lufs': -40, 'truePeakDbtp': -20, 'metric': 'momentary'})
        other['roomtone']['calibrationDbfs'] = -57
        refs = reference.apply([anchor, other], [{'start': 0, 'title': '같은 씬'}], {})
        self.assertTrue(refs[0]['ready'])
        self.assertEqual(anchor['finalGainDb'], 2)
        self.assertEqual(other['finalGainDb'], 4)  # follows -53dBFS roomtone, NOT +16dB speech target
        self.assertEqual(other['method'], 'referenceRoomtone')

    def test_missing_or_conflicting_reference_holds_original(self):
        a = row(before={'lufs': -26, 'truePeakDbtp': -5, 'metric': 'shortTerm'})
        refs = reference.apply([a], [{'start': 0, 'title': '씬'}], {})
        self.assertFalse(refs[0]['ready'])
        self.assertEqual(a['finalGainDb'], 0)
        valid, invalid = row(), row(ci=1, before={'lufs': -26, 'truePeakDbtp': -5, 'metric': 'shortTerm'})
        refs = reference.apply([valid, invalid], [{'start': 0, 'title': '씬'}], {'referenceClips': {'0': '3:1'}})
        self.assertFalse(refs[0]['ready'])  # don't silently replace an explicit invalid selection

    def test_different_color_and_scene_do_not_get_blind_rms_matching(self):
        a, b, c = row(), row(ci=1), row(ci=2)
        b['roomtone']['bands'] = [1, 0, 0, 0]
        c['before'] = {'lufs': None, 'truePeakDbtp': None, 'metric': 'peakOnly'}
        reference.apply([a, b, c], [{'start': 0, 'title': 'A'}, {'start': 8, 'title': 'B'}], {})
        self.assertEqual(b['method'], 'roomtoneDifferent')
        self.assertEqual(b['finalGainDb'], 0)
        self.assertEqual(c['method'], 'referenceUnavailable')

    def test_native_equal_gain_preserves_media_timing_and_preview(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-reference-') as d:
            root = Path(d)
            rate = 48000
            x = np.random.default_rng(24).normal(0, .001, rate * 16)
            for start in [3, 7, 11]:
                t = np.arange(rate * 2) / rate
                x[start * rate:(start + 2) * rate] += .025 * np.sin(2 * np.pi * 220 * t)
            pcm = np.round(x * 32767).astype('<i2')
            with wave.open(str(root / 'source.wav'), 'wb') as w:
                w.setparams((1, 2, rate, 0, 'NONE', 'not compressed')); w.writeframes(pcm.tobytes())
            with aaf2.open(str(root / 'edit.aaf'), 'w') as f:
                master = f.create.MasterMob('continuous synthetic source'); f.content.mobs.append(master)
                source = master.import_audio_essence(str(root / 'source.wav'), edit_rate=rate)
                comp = f.create.CompositionMob('Reference synthetic'); comp.usage = 'Usage_TopLevel'; f.content.mobs.append(comp)
                slot = comp.create_sound_slot(rate); slot.name = 'DX'
                for start in [2, 6, 10]:
                    slot.segment.components.append(master.create_source_clip(source.slot_id, start=start * rate, length=4 * rate))
                slot.segment.length = 12 * rate
                before = {str(e.mob_id): preserved.digest_stream(e, engine) for e in f.content.essencedata}
            engine.save(root / 'uploads.json', [{'role': 'aaf', 'file': 'edit.aaf'}])
            manifest = preserved.inspect_job(root, engine)
            engine.save(root / 'settings.json', {'roles': {'t0': 'dialogue'}, 'referenceClips': {'0': '%s:0' % manifest['tracks'][0]['slotId']}})
            with patch.object(preserved, 'Analyzer', FixtureAnalyzer):
                result = preserved.render_dialogue(root, engine)
            self.assertEqual(len(result['report']['references']), 1)
            self.assertTrue(result['report']['references'][0]['ready'])
            self.assertEqual(len(result['report']['fades']), 2)
            self.assertTrue(all(p['samePcm'] and p['curve'] == 'equalGain' for p in result['report']['fades']))
            with aaf2.open(str(root / result['renderDirectory'] / 'dialogue-clips.aaf')) as f:
                self.assertEqual({str(e.mob_id): preserved.digest_stream(e, engine) for e in f.content.essencedata}, before)
                comp = next(f.content.toplevel())
                self.assertEqual(comp.slots[0].length, 12 * rate)
                self.assertEqual(sum(c.__class__.__name__ == 'Transition' for c in comp.slots[0].segment.components), 2)
            with wave.open(str(root / 'dialogue-approved.wav')) as w:
                self.assertEqual(w.getnframes(), 12 * rate)
                wet = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').reshape(-1, 2)[:, 0].astype(float)
            # In identical overlaps, a convex mix cannot create the old +3dB swell.
            expected = pcm[2 * rate:14 * rate].astype(float) * 10 ** (2 / 20) * math.sqrt(.5)
            for p in result['report']['fades']:
                lo, hi = round(p['start'] * rate), round(p['end'] * rate)
                self.assertLess(np.max(np.abs(wet[lo:hi] - expected[lo:hi])), 5)


if __name__ == '__main__':
    unittest.main()
