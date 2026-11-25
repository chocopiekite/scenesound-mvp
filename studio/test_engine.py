import importlib.util
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave
import struct
import array
import sys
import aaf2

spec = importlib.util.spec_from_file_location('engine', Path(__file__).with_name('engine.py'))
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def fixture(root, offline=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with wave.open(str(root / 'dialogue.wav'), 'wb') as w:
        w.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        w.writeframes(b''.join(struct.pack('<h', int((0.035 if i < 3 * 48000 else 0.16) * 32767 * math.sin(2 * math.pi * 330 * i / 48000))) for i in range(8 * 48000)))
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=640x360:r=24:d=8', '-vf', 'drawbox=x=100:y=80:w=100:h=200:color=brown:t=fill:enable=between(t\\,2\\,5)', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(root / 'reference.mp4')], check=True)
    with aaf2.open(str(root / 'edit.aaf'), 'w') as f:
        mob = f.create.MasterMob('DX source')
        f.content.mobs.append(mob)
        source = mob.import_audio_essence(str(root / 'dialogue.wav'), edit_rate=48000, offline=offline)
        if offline:
            physical = source.segment.mob
            locator = f.create.NetworkLocator()
            locator['URLString'].value = 'file:///must-not-read-this-location/dialogue.wav'
            physical.descriptor['Locator'].append(locator)
        comp = f.create.CompositionMob('Synthetic SceneSound test')
        comp.usage = 'Usage_TopLevel'
        f.content.mobs.append(comp)
        track = comp.create_sound_slot(48000)
        track.name = 'DX dialogue'
        track.segment.components.append(mob.create_source_clip(source.slot_id, start=48000, length=2 * 48000))
        track.segment.components.append(f.create.Filler(media_kind='sound', length=2 * 48000))
        track.segment.components.append(mob.create_source_clip(source.slot_id, start=4 * 48000, length=2 * 48000))
        track.segment.components.append(f.create.Filler(media_kind='sound', length=2 * 48000))
        track.segment.length = 8 * 48000
    (root / 'uploads.json').write_text(json.dumps([{'role': 'aaf', 'name': 'edit.aaf', 'file': 'edit.aaf'}, {'role': 'video', 'name': 'reference.mp4', 'file': 'reference.mp4'}]))


class EngineTests(unittest.TestCase):
    def test_pcm_aaf_cuts_processing_export_and_reimport(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-engine-test-') as d:
            root = Path(d)
            fixture(root)
            manifest = engine.inspect_job(root)
            self.assertEqual(len(manifest['tracks']), 1)
            clips = manifest['tracks'][0]['clips']
            self.assertEqual([(c['start'], c['duration'], c['sourceStart']) for c in clips], [(0, 2, 0), (4, 2, 0)])
            engine.save(root / 'settings.json', {'roles': {'t0': 'dialogue'}, 'clean': True, 'trackGains': {}, 'assets': [{'id': 's0', 'file': 'dialogue.wav', 'title': 'Test ambience', 'role': 'ambience', 'start': 0, 'end': 8, 'gain': -24, 'enabled': True}], 'warnings': [], 'summary': 'Synthetic test only'})
            prepared = engine.prepare_analysis(root)
            info, proxy_duration = engine.probe(root / prepared['analysisVideo'])
            self.assertTrue(any(s['codec_type'] == 'audio' for s in info['streams']))
            self.assertAlmostEqual(proxy_duration, 8, places=1)
            result = engine.render(root)
            source_root = root
            root = root / result['renderDirectory']
            self.assertEqual([t['role'] for t in result['tracks']], ['dialogue', 'ambience'])
            with wave.open(str(root / 'original.wav'), 'rb') as w:
                self.assertEqual(w.getframerate(), 48000)
                self.assertEqual(w.getnframes(), 8 * 48000)
                w.setpos(3 * 48000)
                self.assertEqual(set(w.readframes(4800)), {0})
            def rms(filename, start, duration=.4):
                with wave.open(str(root / filename), 'rb') as w:
                    w.setpos(round(start * 48000))
                    data = array.array('h', w.readframes(round(duration * 48000)))
                    return math.sqrt(sum(x*x for x in data) / len(data))
            gain_ratio = rms('t0.wav', .5) / rms('t0-original.wav', .5)
            self.assertGreater(gain_ratio, 1.6)
            self.assertLess(gain_ratio, 2.05)  # max +6dB, preserves a useful bound
            engine.mix(root, [{'file': 's0-placed.wav', 'gain': -24}], 'unducked.wav', 8)
            self.assertLess(rms('ambience.wav', 5), rms('unducked.wav', 5) * .95)
            self.assertNotEqual((root / 't0.wav').read_bytes(), (root / 't0-original.wav').read_bytes())
            with aaf2.open(str(root / 'SceneSound.aaf'), 'r') as f:
                comp = next(f.content.toplevel())
                self.assertEqual(len(list(comp.slots)), 2)
                self.assertEqual([slot.length for slot in comp.slots], [8 * 48000, 8 * 48000])
            self.assertGreater((root / 'preview.mp4').stat().st_size, 1000)
            # Reimport the actual exported AAF: catches broken essence and source chains.
            engine.save(root / 'uploads.json', [{'role': 'aaf', 'name': 'SceneSound.aaf', 'file': 'SceneSound.aaf'}, {'role': 'video', 'name': 'reference.mp4', 'file': str(source_root / 'reference.mp4')}])
            again = engine.inspect_job(root)
            self.assertEqual(len(again['tracks']), 2)
            self.assertEqual(again['tracks'][0]['clips'][0]['duration'], 8)

    def test_dialogue_aaf_only_dedup_loudness_and_handoff(self):
        import dialogue
        with tempfile.TemporaryDirectory(prefix='scenesound-dialogue-test-') as d:
            root = Path(d)
            fixture(root)
            with aaf2.open(str(root / 'edit.aaf'), 'rw') as f:
                comp = next(f.content.toplevel())
                original = comp.slots[0]
                duplicate = comp.create_sound_slot(48000)
                duplicate.name = 'DX duplicate'
                duplicate.segment = original.segment.copy()
            uploads = json.loads((root / 'uploads.json').read_text())
            engine.save(root / 'uploads.json', [u for u in uploads if u['role'] != 'video'])
            m = engine.inspect_job(root)
            self.assertIsNone(m['video'])
            self.assertEqual(m['duration'], 8)
            settings = {'roles': {t['id']: 'dialogue' for t in m['tracks']}, 'clean': True, 'deduplicate': True, 'scenes': [{'start': 0, 'title': '실내 씬'}, {'start': 4, 'title': '복도 씬'}]}
            engine.save(root / 'settings.json', settings)
            r = dialogue.render_dialogue(root, engine)
            self.assertEqual(len(r['report']['duplicates']), 2)
            self.assertEqual(r['report']['removedDuplicateTracks'], 1)
            self.assertEqual(r['report']['normalizationMode'], 'clipStaticShortTerm')
            self.assertEqual(r['report']['shortClipCount'], 2)
            self.assertTrue(all(a['peakReached'] for a in r['report']['adjustments']))
            out = root / r['renderDirectory']
            after = dialogue.measure(engine, out / 'mix.wav')
            self.assertTrue(math.isfinite(after['input_i']))
            self.assertGreater(r['report']['needsReview'], 0)  # sine crest cannot meet both targets
            with wave.open(str(out / 'mix.wav')) as w:
                self.assertEqual(w.getnframes(), 8 * 48000)
                self.assertEqual(w.getnchannels(), 2)
                w.setpos(3 * 48000)
                self.assertEqual(set(w.readframes(4800)), {0})
            self.assertTrue((root / 'dialogue-approved.wav').exists())
            scene_samples = []
            for t in r['tracks']:
                with wave.open(str(out / t['export'])) as w:
                    samples = array.array('h', w.readframes(w.getnframes()))
                    padded = array.array('h', [0]) * (8 * 48000 * 2)
                    begin = round(t['start'] * 48000) * 2
                    padded[begin:begin+len(samples)] = samples
                    scene_samples.append(padded)
            with wave.open(str(out / 'mix.wav')) as w:
                bus = array.array('h', w.readframes(w.getnframes()))
            self.assertLessEqual(max(abs(bus[i] - sum(s[i] for s in scene_samples)) for i in range(len(bus))), 2)
            # Exported scene tracks start with a fade rather than a hard boundary click.
            self.assertEqual(scene_samples[0][0], 0)
            self.assertEqual(scene_samples[1][4 * 48000 * 2], 0)
            # Disabling duplicate removal restores both original tracks.
            settings['deduplicate'] = False
            engine.save(root / 'settings.json', settings)
            restored = dialogue.render_dialogue(root, engine)
            self.assertEqual(len(restored['report']['duplicates']), 0)
            self.assertEqual(len(restored['tracks']), 2)
            with aaf2.open(str(root / restored['renderDirectory'] / 'SceneSound.aaf')) as f:
                comp = next(f.content.toplevel())
                self.assertEqual([slot.name for slot in comp.slots], ['실내 씬', '복도 씬'])
                self.assertTrue(all(slot.length == 8 * 48000 for slot in comp.slots))
            reimport = root / restored['renderDirectory']
            engine.save(reimport / 'uploads.json', [{'role': 'aaf', 'file': 'SceneSound.aaf', 'name': 'SceneSound.aaf'}])
            self.assertEqual(len(engine.inspect_job(reimport)['tracks']), 2)
            # Real video attachment and effects hand-off preserve the approved dialogue bus.
            engine.save(root / 'uploads.json', uploads)
            engine.attach_video(root)
            settings.update(useDialogue=True, assets=[], trackGains={})
            engine.save(root / 'settings.json', settings)
            prepared = engine.prepare_analysis(root)
            self.assertEqual(prepared['analysisVideo'], 'analysis-reference.mp4')
            mixed = engine.render(root)
            stem = root / mixed['renderDirectory'] / 'dialogue-export.wav'
            self.assertAlmostEqual(dialogue.measure(engine, stem)['input_i'], restored['report']['afterLufs'], delta=.2)

    def test_clip_static_shortterm_and_peak_constraints(self):
        import dialogue
        self.assertAlmostEqual(dialogue.clip_gain(-30, -18), 6)  # both met: -24 / -12
        self.assertAlmostEqual(dialogue.clip_gain(-30, -10), 0)  # upper peak wins
        self.assertAlmostEqual(dialogue.clip_gain(-30, -25), 10)  # lower peak wins
        self.assertEqual(dialogue.clip_gain(None, None), 0)
        with tempfile.TemporaryDirectory(prefix='scenesound-shortterm-') as d:
            root = Path(d)
            samples = [int(.07 * 32767 * math.sin(2 * math.pi * 330 * i / 48000)) for i in range(6 * 48000)]
            # A short transient gives speech-like crest factor, unlike a plain sine.
            samples[4 * 48000] = int(.15 * 32767)
            with wave.open(str(root / 'voice.wav'), 'wb') as w:
                w.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                w.writeframes(array.array('h', samples).tobytes())
            before = dialogue.clip_level(engine, root / 'voice.wav', 6)
            self.assertEqual(before['metric'], 'shortTerm')
            gain = dialogue.clip_gain(before['lufs'], before['truePeakDbtp'])
            engine.ff('-i', root / 'voice.wav', '-af', 'volume=%fdB' % gain, '-c:a', 'pcm_f32le', root / 'leveled.wav')
            after = dialogue.clip_level(engine, root / 'leveled.wav', 6)
            self.assertAlmostEqual(after['lufs'], -24, delta=.2)
            self.assertGreaterEqual(after['truePeakDbtp'], -15.15)
            self.assertLessEqual(after['truePeakDbtp'], -9.85)
            self.assertAlmostEqual(after['lufs'] - before['lufs'], gain, delta=.1)
            # No invented short-term readings for files shorter than 3 seconds.
            engine.ff('-i', root / 'voice.wav', '-t', 2, root / 'short.wav')
            short = dialogue.clip_level(engine, root / 'short.wav', 2)
            self.assertEqual(short['metric'], 'momentary')
            self.assertIsNotNone(short['lufs'])
            engine.ff('-i', root / 'voice.wav', '-t', .2, root / 'tiny.wav')
            self.assertIsNone(dialogue.clip_level(engine, root / 'tiny.wav', .2)['lufs'])

    def test_overlapping_different_pcm_is_not_duplicate(self):
        import dialogue
        with tempfile.TemporaryDirectory(prefix='scenesound-dialogue-overlap-') as d:
            root = Path(d)
            fixture(root)
            m = engine.inspect_job(root)
            first = m['tracks'][0]
            # Same position and length, different recording section: keep both.
            second = {'id': 't1', 'name': 'DX different mic', 'role': 'dialogue', 'clips': [{**first['clips'][0], 'file': 'dialogue.wav', 'sourceStart': 4}]}
            m['tracks'].append(second)
            engine.save(root / 'manifest.json', m)
            engine.save(root / 'settings.json', {'roles': {'t0': 'dialogue', 't1': 'dialogue'}, 'clean': False})
            r = dialogue.render_dialogue(root, engine)
            self.assertEqual(r['report']['duplicates'], [])
            self.assertEqual(len(r['tracks']), 1)
            self.assertEqual(len(r['tracks'][0]['clips']), 3)
            # Silence must fail explicitly rather than claim a successful -24 LUFS result.
            for filename in {c['file'] for t in m['tracks'] for c in t['clips']}:
                with wave.open(str(root / filename), 'wb') as w:
                    w.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                    w.writeframes(bytes(8 * 48000 * 2))
            with self.assertRaisesRegex(ValueError, '측정 가능한'):
                dialogue.render_dialogue(root, engine)

    def test_manual_sound_channels_are_separate_in_wav_and_aaf(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-channels-') as d:
            root = Path(d)
            fixture(root)
            m = engine.inspect_job(root)
            channels = [{'id': 'effect', 'role': 'effect', 'name': '발소리', 'gain': 0},
                        {'id': 'effect-2', 'role': 'effect', 'name': '문소리', 'gain': -6},
                        {'id': 'ambience', 'role': 'ambience', 'name': '빈 배경음', 'gain': 0}]
            assets = [{'id': 's%d' % i, 'channelId': c['id'], 'role': 'effect', 'file': 'dialogue.wav', 'start': 1, 'end': 3, 'gain': -12, 'enabled': True, 'title': c['name']} for i, c in enumerate(channels[:2])]
            engine.save(root / 'settings.json', {'roles': {t['id']: 'original' for t in m['tracks']}, 'clean': False,
                        'effectChannels': channels, 'trackGains': {'effect-2': -6}, 'assets': assets})
            r = engine.render(root)
            self.assertEqual(r['effectChannels'], channels)
            out = root / r['renderDirectory']
            with aaf2.open(str(out / 'SceneSound.aaf')) as f:
                comp = next(f.content.toplevel())
                self.assertEqual([slot.name for slot in comp.slots][-3:], ['발소리', '문소리', '빈 배경음'])
            peaks = []
            for name in ['effect-export.wav', 'effect-2-export.wav', 'ambience-export.wav']:
                with wave.open(str(out / name)) as w:
                    samples = array.array('h', w.readframes(w.getnframes()))
                    peaks.append(max(abs(v) for v in samples))
            self.assertGreater(peaks[0], 0)
            self.assertAlmostEqual(peaks[1] / peaks[0], 10 ** (-6 / 20), delta=.01)
            self.assertEqual(peaks[2], 0)

    def test_wave_descriptor_extensible_pcm_and_constant_gain(self):
        import io
        from types import SimpleNamespace
        import dialogue
        with tempfile.TemporaryDirectory(prefix='scenesound-wave-aaf-') as d:
            root = Path(d)
            fixture(root)
            engine.ff('-i', root / 'dialogue.wav', '-c:a', 'pcm_s24le', '-write_bext', 1, root / 'embedded.wav')
            payload = (root / 'embedded.wav').read_bytes()
            with aaf2.open(str(root / 'edit.aaf'), 'rw') as f:
                mob = next(m for m in f.content.sourcemobs() if m.descriptor.__class__.__name__ == 'PCMDescriptor')
                descriptor = f.create.WAVEDescriptor()
                descriptor['SampleRate'].value = 48000
                descriptor['Length'].value = 8 * 48000
                descriptor['Summary'].value = bytearray(payload[:min(len(payload), 1024)])
                mob.descriptor = descriptor
                stream = mob.essence.open('w')
                stream.write(payload)
                stream.close()
                op = f.create.OperationDef('9d2ea894-0968-11d3-8a38-0050040ef7d2', 'Audio Gain')
                op.media_kind = 'sound'
                op['IsTimeWarp'].value = False
                op['NumberInputs'].value = 1
                f.dictionary.register_def(op)
                param = f.create.ParameterDef('e4962321-2267-11d3-8a4c-0050040ef7d2', 'Amplitude', typedef='Rational')
                f.dictionary.register_def(param)
                seq = next(f.content.toplevel()).slots[0].segment
                group = f.create.OperationGroup(op, length=seq.components[0].length, media_kind='sound')
                group.segments.append(seq.components[0].copy())
                group.parameters.append(f.create.ConstantValue(param, '1/2'))
                seq.components[0] = group
            m = engine.inspect_job(root)
            self.assertEqual([c['sourceGain'] for c in m['tracks'][0]['clips']], [.5, 1])
            clip = m['tracks'][0]['clips'][0]
            with wave.open(str(root / clip['file'])) as w:
                self.assertEqual((w.getsampwidth(), w.getframerate(), w.getnframes()), (3, 48000, 2 * 48000))
            engine.save(root / 'settings.json', {'roles': {'t0': 'dialogue'}, 'clean': False})
            r = dialogue.render_dialogue(root, engine)
            self.assertTrue((root / r['renderDirectory'] / 'SceneSound.aaf').exists())
            # Truncated RIFF chunk payload must fail rather than read arbitrary offsets.
            stream = io.BytesIO(payload[:-100]);stream.dir = SimpleNamespace(byte_size=len(payload)-100)
            with aaf2.open(str(root / 'edit.aaf')) as f:
                desc = next(m.descriptor for m in f.content.sourcemobs() if m.descriptor.__class__.__name__=='WAVEDescriptor')
                with self.assertRaisesRegex(ValueError, '잘렸'):
                    engine.pcm_layout(desc, stream)

    def test_fractional_sample_mix_finishes_and_has_exact_sample_count(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='scenesound-fractional-mix-') as d:
            root = Path(d)
            engine.ff('-f', 'lavfi', '-i', 'sine=frequency=330:duration=1', '-ar', 48000, '-ac', 2, root / 'one.wav')
            inputs = [{'file': 'one.wav', 'start': t} for t in [0, 5.505, 5.505, 5.505, 14.431, 14.431, 14.431, 16.642]]
            original_run = engine.run
            with patch.object(engine, 'run', side_effect=lambda args: original_run(args, timeout=15)):
                engine.mix(root, inputs, 'sum.wav', 19.394374999999968, limit=False, codec='pcm_f32le')
            _, duration = engine.probe(root / 'sum.wav', allow_long=True)
            self.assertAlmostEqual(duration, 930930 / 48000, places=5)

    def test_video_only_sound_tool_needs_no_aaf(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-video-only-') as d:
            root = Path(d)
            fixture(root)
            engine.save(root / 'uploads.json', [{'role': 'video', 'name': 'reference.mp4', 'file': 'reference.mp4'}])
            m = engine.inspect_job(root)
            self.assertTrue(m['videoOnly'])
            self.assertEqual(m['tracks'][0]['role'], 'original')
            engine.save(root / 'settings.json', {'roles': {'t0': 'original'}, 'clean': False, 'assets': [], 'trackGains': {}})
            r = engine.render(root)
            self.assertTrue((root / r['renderDirectory'] / 'preview.mp4').exists())

    def test_long_embedded_source_extracts_only_used_region(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-long-source-') as d:
            root = Path(d)
            with wave.open(str(root / 'long.wav'), 'wb') as w:
                w.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                for i in range(720):
                    w.writeframesraw(struct.pack('<h', 1234 if i >= 700 else 0) * 48000)
            with aaf2.open(str(root / 'edit.aaf'), 'w') as f:
                mob=f.create.MasterMob('DX long recording');f.content.mobs.append(mob)
                src=mob.import_audio_essence(str(root / 'long.wav'),edit_rate=48000)
                comp=f.create.CompositionMob('Long source short cut');comp.usage='Usage_TopLevel';f.content.mobs.append(comp)
                slot=comp.create_sound_slot(48000);slot.name='DX';slot.segment.components.append(mob.create_source_clip(src.slot_id,start=700*48000,length=8*48000));slot.segment.length=8*48000
            engine.save(root / 'uploads.json',[{'role':'aaf','file':'edit.aaf','name':'edit.aaf'}])
            m=engine.inspect_job(root);c=m['tracks'][0]['clips'][0]
            self.assertEqual(c['sourceStart'],0);self.assertEqual(c['originalSourceStart'],700)
            self.assertLess((root / c['file']).stat().st_size,1024**2)
            with wave.open(str(root / c['file'])) as w:
                self.assertEqual(w.getnframes(),8*48000)
                self.assertEqual(struct.unpack('<h',w.readframes(1))[0],1234)

    def test_batched_mix_retains_timing_and_sample_sum(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-batch-mix-') as d:
            root=Path(d);fixture(root)
            items=[{'file':'dialogue.wav','start':0,'gain':-30} for _ in range(17)]
            engine.mix(root,items,'batch.wav',8,limit=False)
            engine.mix(root,[{'file':'dialogue.wav','gain':-30+20*math.log10(17)}],'single.wav',8,limit=False)
            with wave.open(str(root / 'batch.wav')) as a, wave.open(str(root / 'single.wav')) as b:
                av=array.array('h',a.readframes(a.getnframes()));bv=array.array('h',b.readframes(b.getnframes()))
                self.assertLessEqual(max(abs(x-y) for x,y in zip(av,bv)),2)
            self.assertEqual(list(root.glob('batch-*.wav')),[])

    def test_linked_media_requires_explicit_upload(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-linked-') as d:
            root = Path(d)
            fixture(root, offline=True)
            with self.assertRaisesRegex(ValueError, '연결 오디오가 없거나'):
                engine.inspect_job(root)
            uploads = json.loads((root / 'uploads.json').read_text())
            uploads.append({'role': 'audio', 'name': 'dialogue.wav', 'file': 'dialogue.wav'})
            engine.save(root / 'uploads.json', uploads)
            data = engine.inspect_job(root)
            self.assertEqual(data['tracks'][0]['clips'][0]['sourceStart'], 1)

    def test_playlist_cannot_open_remote_media(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-playlist-') as d:
            path = Path(d) / 'fake.wav'
            path.write_text('#EXTM3U\n#EXTINF:8,\nhttps://example.invalid/private.wav\n')
            with self.assertRaises(ValueError):
                engine.probe(path)

    def test_unsupported_operation_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='scenesound-unsupported-') as d:
            root = Path(d)
            fixture(root)
            with aaf2.open(str(root / 'edit.aaf'), 'rw') as f:
                slot = next(f.content.toplevel()).slots[0]
                slot.segment = f.create.Timecode(fps=24, drop=False, length=192)
                slot.segment.media_kind = 'sound'
            with self.assertRaisesRegex(ValueError, '지원하지 않는 AAF'):
                engine.inspect_job(root)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fixture':
        fixture(sys.argv[2])
    else:
        unittest.main()
