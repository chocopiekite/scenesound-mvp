from pathlib import Path
import tempfile, hashlib, wave, json
import unittest
from unittest.mock import patch
import numpy as np
import automatic
from test_engine import fixture, engine


def pcm16(path, x):
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        w.writeframes(np.round(np.asarray(x) * 32767).astype('<i2').tobytes())


def pcm24(path):
    offset, n = automatic.pcm_wave_info(path, encoding=1, expected_bits=24)
    with path.open('rb') as f:
        f.seek(offset); b = np.frombuffer(f.read(n * 3), dtype=np.uint8).reshape(-1, 3).astype(np.int32)
    v = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
    return ((v ^ 0x800000) - 0x800000) / 8388608.


class AutomaticTests(unittest.TestCase):
    def test_attenuated_flat_tops_are_found_next_to_louder_clean_audio(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); t = np.arange(48000 * 2) / 48000
            clean = .2 * np.sin(2 * np.pi * 220 * t)
            damaged = clean.copy(); damaged[:48000] = np.clip(damaged[:48000], -.05, .05)
            pcm16(root / 'partly-clipped.wav', damaged)
            result = automatic.clipping_ranges(root / 'partly-clipped.wav')
            self.assertTrue(result['ranges'])
            self.assertLess(result['ranges'][0][0], .1)
            self.assertLess(result['ranges'][-1][1], 1.2)

    def test_repair_without_candidates_leaves_scratch_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'work.wav'
            automatic.write_float(path, np.zeros(48000, dtype=np.float32))
            before = path.read_bytes()
            result = automatic.repair_regions(path, [], engine)
            self.assertFalse(result['attemptedRanges'])
            self.assertEqual(path.read_bytes(), before)

    def test_clipping_detection_and_masked_repair_quality_and_alignment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); t = np.arange(48000 * 3) / 48000
            clean = .22 * np.sin(2 * np.pi * 220 * t) + .02 * np.sin(2 * np.pi * 440 * t)
            clipped = np.clip(clean, -.12, .12)
            pcm16(root / 'clean.wav', clean); pcm16(root / 'clipped.wav', clipped)
            self.assertFalse(automatic.clipping_ranges(root / 'clean.wav')['ranges'])
            self.assertTrue(automatic.clipping_ranges(root / 'clipped.wav')['ranges'])
            work = root / 'work.wav'; automatic.write_float(work, clipped)
            report = automatic.repair_regions(work, [[.25, 2.75]], engine)
            off, count = automatic.pcm_wave_info(work)
            with work.open('rb') as f:
                f.seek(off); result = np.frombuffer(f.read(count * 4), dtype='<f4')
            self.assertEqual(count, len(clean)); self.assertEqual(len(report['attemptedRanges']), 1)
            np.testing.assert_array_equal(result[:12000], clipped[:12000].astype('<f4'))
            np.testing.assert_array_equal(result[132000:], clipped[132000:].astype('<f4'))
            self.assertLess(float(np.mean((clean - result) ** 2)), float(np.mean((clean - clipped) ** 2)) * .7)
            errors = [np.mean((clean[30000:110000] - result[30000 + lag:110000 + lag]) ** 2) for lag in range(-25, 26)]
            self.assertEqual(int(np.argmin(errors)) - 25, 0)

    def test_audio_exports_are_separate_24bit_sample_exact_and_source_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); x = np.random.default_rng(14).normal(0, .002, 48000 * 2)
            pcm16(root / 'input.wav', x)
            before = hashlib.sha256((root / 'input.wav').read_bytes()).hexdigest()
            engine.save(root / 'uploads.json', [{'role': 'audio', 'file': 'input.wav', 'name': 'voice.wav'}])
            engine.save(root / 'settings.json', {'strength': 'gentle'})
            m = automatic.inspect_job(root, engine)
            self.assertEqual(m['workflow'], 'automatic')
            with patch.object(automatic, 'find_reference', return_value=(None, -55)):
                result = automatic.render(root, engine)
            out = root / result['renderDirectory']
            self.assertEqual(result['mode'], 'automatic'); self.assertEqual(result['exportMode'], 'processedWav')
            self.assertEqual(result['report']['noiseReductionDb'], 3)
            self.assertFalse(result['report']['declipAttempted'])
            self.assertEqual(len(pcm24(out / 'auto-original.wav')), len(x))
            y = pcm24(out / 'auto-clean.wav'); self.assertEqual(len(y), len(x))
            self.assertTrue(np.all(np.isfinite(y)))
            self.assertLess(np.sqrt(np.mean(y * y)), np.sqrt(np.mean(x * x)))
            self.assertEqual(hashlib.sha256((root / 'input.wav').read_bytes()).hexdigest(), before)
            self.assertFalse(list(out.glob('*.aaf')))

    def test_aaf_preparation_does_not_create_or_modify_an_expert_aaf(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); fixture(root)
            engine.save(root / 'uploads.json', [{'role': 'aaf', 'file': 'edit.aaf', 'name': 'test.aaf'}])
            before = hashlib.sha256((root / 'edit.aaf').read_bytes()).hexdigest()
            automatic.inspect_job(root, engine)
            engine.save(root / 'settings.json', {'strength': 'standard'})
            with patch.object(automatic, 'find_reference', return_value=(None, -55)):
                result = automatic.render(root, engine)
            out = root / result['renderDirectory']
            self.assertEqual(result['report']['preparation']['retainedClips'], 2)
            self.assertFalse(list(out.glob('*.aaf')))
            self.assertEqual(hashlib.sha256((root / 'edit.aaf').read_bytes()).hexdigest(), before)
            self.assertEqual(len(pcm24(out / 'auto-clean.wav')), round(result['duration'] * 48000))

    def test_native_aaf_fades_render_without_modifying_original(self):
        import aaf2, dialogue_fades as fades
        from aaf2.auid import AUID
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); rate = 48000
            pcm16(root / 'tone.wav', .02 * np.sin(2 * np.pi * 220 * np.arange(rate * 3) / rate))
            with aaf2.open(str(root / 'edit.aaf'), 'w') as f:
                master = f.create.MasterMob('original'); f.content.mobs.append(master)
                source = master.import_audio_essence(str(root / 'tone.wav'), edit_rate=rate)
                comp = f.create.CompositionMob('native'); comp.usage = 'Usage_TopLevel'; f.content.mobs.append(comp)
                slot = comp.create_sound_slot(rate); slot.name = 'DIA'
                slot.segment.components.append(master.create_source_clip(source.slot_id, start=0, length=76800))
                op, param = fades.definitions(f)
                tr = f.create.Transition('sound', length=9600); tr.cutpoint = 4800
                group = f.create.OperationGroup(op, length=9600, media_kind='sound')
                curve = f.create.VaryingValue(param, AUID(fades.LINEAR)); curve.add_keyframe(0, 0); curve.add_keyframe(1, 1)
                group.parameters.append(curve); tr['OperationGroup'].value = group
                slot.segment.components.append(tr)
                slot.segment.components.append(master.create_source_clip(source.slot_id, start=67200, length=76800))
                slot.segment.length = 144000
            before = hashlib.sha256((root / 'edit.aaf').read_bytes()).hexdigest()
            engine.save(root / 'uploads.json', [{'role': 'aaf', 'file': 'edit.aaf', 'name': 'native.aaf'}])
            engine.save(root / 'settings.json', {'strength': 'gentle'})
            manifest = automatic.inspect_job(root, engine)
            self.assertTrue(manifest['nativeInput']); self.assertEqual(manifest['nativeFades'], 1)
            with patch.object(automatic, 'find_reference', return_value=(None, -55)):
                result = automatic.render(root, engine)
            original = pcm24(root / result['renderDirectory'] / 'auto-original.wav')
            expected = np.round(.02 * np.sin(2 * np.pi * 220 * np.arange(144000) / rate) * 32767) / 32768
            np.testing.assert_allclose(original, expected, atol=2e-7)
            self.assertEqual(result['report']['preparation']['fades'], 1)
            self.assertEqual(hashlib.sha256((root / 'edit.aaf').read_bytes()).hexdigest(), before)
            self.assertFalse(list((root / result['renderDirectory']).glob('*.aaf')))

    def test_video_audio_offset_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); t = np.arange(48000) / 48000
            pcm16(root / 'tone.wav', .1 * np.sin(2 * np.pi * 1000 * t))
            engine.ff('-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=25:d=2', '-itsoffset', .3, '-i', root / 'tone.wav',
                      '-map', '0:v:0', '-map', '1:a:0', '-t', 2, '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', root / 'input.mp4')
            engine.save(root / 'uploads.json', [{'role': 'video', 'file': 'input.mp4', 'name': 'video.mp4'}])
            engine.save(root / 'settings.json', {'strength': 'gentle'})
            automatic.inspect_job(root, engine)
            with patch.object(automatic, 'find_reference', return_value=(None, -55)):
                result = automatic.render(root, engine)
            out = root / result['renderDirectory']; original = pcm24(out / 'auto-original.wav'); clean = pcm24(out / 'auto-clean.wav')
            self.assertEqual(len(original), 96000); self.assertEqual(len(clean), 96000)
            self.assertLess(float(np.max(np.abs(original[:12000]))), 1e-5)
            first = int(np.argmax(np.abs(original) > .01)) / 48000
            first_clean = int(np.argmax(np.abs(clean) > .01)) / 48000
            self.assertAlmostEqual(first, .3, delta=.025)
            self.assertAlmostEqual(first_clean, first, delta=.01)

    def test_silence_is_not_amplified_or_claimed_as_repaired_speech(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); pcm16(root / 'input.wav', np.zeros(48000))
            engine.save(root / 'uploads.json', [{'role': 'audio', 'file': 'input.wav', 'name': 'silence.wav'}])
            engine.save(root / 'settings.json', {'strength': 'standard'})
            automatic.inspect_job(root, engine)
            result = automatic.render(root, engine); out = root / result['renderDirectory']
            self.assertIsNone(result['report']['reference']); self.assertIsNone(result['report']['outputTruePeakDbtp'])
            self.assertFalse(result['report']['declipAttempted'])
            self.assertFalse(np.any(pcm24(out / 'auto-clean.wav')))


if __name__ == '__main__':
    unittest.main()
