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
            self.assertEqual([(c['start'], c['duration'], c['sourceStart']) for c in clips], [(0, 2, 1), (4, 2, 4)])
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
