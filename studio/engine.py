"""Local, bounded AAF/PCM renderer. All media paths come from the job upload manifest.
No AAF locator is opened directly. Unsupported editing operations fail closed.
"""
import array
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import wave
import zipfile
from uuid import uuid4
from fractions import Fraction
import aaf2

RATE = 48000
MAX_DURATION = int(os.environ.get('STUDIO_MAX_DURATION', 600))
MAX_TRACKS = int(os.environ.get('STUDIO_MAX_TRACKS', 24))
MAX_CLIPS = int(os.environ.get('STUDIO_MAX_CLIPS', 256))
MAX_SECONDS = int(os.environ.get('STUDIO_MAX_SECONDS', 3600))


def run(args, timeout=180):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError('오디오 변환에 실패했어요. PCM WAV 또는 지원되는 미디어인지 확인해 주세요.')
    return result.stderr.decode('utf8', 'replace')


def ff(*args):
    bounded = []
    for arg in args:
        if str(arg) == '-i':
            bounded += ['-protocol_whitelist', 'file,pipe', '-format_whitelist', 'lavfi,wav,aiff,mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,ogg,flac']
        bounded.append(str(arg))
    return run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'info', '-y', '-threads', '1', '-filter_threads', '1', '-filter_complex_threads', '1', *bounded])


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'wav,aiff,mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,ogg,flac', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('미디어를 읽지 못했어요.')
    data = json.loads(result.stdout)
    duration = float(data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION + 60:
        raise ValueError('미디어 길이는 11분 이하여야 해요.')
    return data, duration


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')


def inspect_job(root):
    uploads = json.loads((root / 'uploads.json').read_text())
    aafs = [u for u in uploads if u['role'] == 'aaf']
    videos = [u for u in uploads if u['role'] == 'video']
    if len(aafs) != 1 or len(videos) != 1:
        raise ValueError('AAF 1개와 참조 영상 1개를 선택해 주세요.')
    video_info, video_duration = probe(root / videos[0]['file'])
    video_stream = next((s for s in video_info.get('streams', []) if s.get('codec_type') == 'video'), {})
    width, height = video_stream.get('width', 0), video_stream.get('height', 0)
    if min(width, height) < 360 or max(width, height) / max(1, min(width, height)) > 2.4:
        raise ValueError('영상 가로·세로는 각각 360픽셀 이상, 화면 비율은 2.4:1 이내여야 해요.')
    if not video_stream or video_duration > MAX_DURATION:
        raise ValueError('참조 영상은 10분 이하의 영상이어야 해요.')
    linked = {}
    for u in uploads:
        if u['role'] == 'audio':
            key = u['name'].casefold()
            if key in linked:
                raise ValueError('같은 이름의 연결 오디오가 두 개 있어요. 파일 이름을 구분해 주세요.')
            linked[key] = u['file']
    tracks, warnings, extracted, clip_count = [], [], {}, [0]
    with aaf2.open(str(root / aafs[0]['file']), 'r') as f:
        comps = list(f.content.toplevel())
        if len(comps) != 1:
            raise ValueError('최상위 Composition이 하나인 AAF를 내보내 주세요.')
        comp = comps[0]

        def media(mob):
            key = str(mob.mob_id)
            if key in extracted:
                return extracted[key]
            descriptor = mob.descriptor
            if mob.essence is not None:
                if descriptor.__class__.__name__ != 'PCMDescriptor':
                    raise ValueError('현재는 PCM 오디오가 포함된 AAF를 지원해요. PCM/WAV로 다시 내보내 주세요.')
                if int(descriptor['QuantizationBits'].value) not in (16, 24, 32) or int(descriptor['Channels'].value) not in (1, 2):
                    raise ValueError('16/24/32비트 모노·스테레오 PCM만 지원해요.')
                if int(descriptor.length) > 660 * float(descriptor['AudioSamplingRate'].value):
                    raise ValueError('AAF에 포함된 소스 오디오가 너무 길어요. 필요한 구간만 포함해서 내보내 주세요.')
                filename = 'essence-%d.wav' % len(extracted)
                mob.export_audio(str(root / filename))
            else:
                matches = set()
                for locator in descriptor['Locator'].value or []:
                    url = str(locator['URLString'].value)
                    from urllib.parse import unquote, urlparse
                    basename = Path(unquote(urlparse(url.replace('\\', '/')).path)).name.casefold()
                    if basename in linked:
                        matches.add(linked[basename])
                if len(matches) != 1:
                    raise ValueError('연결 오디오가 없거나 이름이 모호해요: ' + str(mob.name or '이름 없는 소스')[:100])
                filename = next(iter(matches))
                probe(root / filename)
            extracted[key] = filename
            return filename

        def flatten(seg, rate, window, duration, dest, clips, depth=0):
            if depth > 20:
                raise ValueError('AAF의 참조 구조가 너무 복잡해요.')
            kind = seg.__class__.__name__
            if kind == 'Filler':
                return
            if window < 0 or window + duration > Fraction(seg.length) / rate + Fraction(1, RATE):
                raise ValueError('AAF 참조 구간이 연결된 트랙의 길이를 벗어났어요.')
            if kind == 'Sequence':
                cursor = Fraction(0)
                for child in seg.components:
                    length = Fraction(child.length) / rate
                    lo, hi = max(cursor, window), min(cursor + length, window + duration)
                    if hi > lo:
                        flatten(child, rate, lo - cursor, hi - lo, dest + lo - window, clips, depth + 1)
                    cursor += length
                return
            if kind != 'SourceClip':
                raise ValueError('아직 지원하지 않는 AAF 편집 요소가 있어요: ' + kind + '. 전환·플러그인·속도 변경을 렌더링한 PCM AAF를 사용해 주세요.')
            mob, slot = seg.mob, seg.slot
            if mob is None or slot is None:
                raise ValueError('AAF에서 연결되지 않은 소스를 발견했어요.')
            source_rate = Fraction(str(slot.edit_rate))
            source_start = Fraction(seg.start) / source_rate + window
            if mob.__class__.__name__ == 'SourceMob':
                filename = media(mob)
                _, source_duration = probe(root / filename)
                if source_start < 0 or float(source_start + duration) > source_duration + 0.025:
                    raise ValueError('AAF 클립의 소스 범위가 오디오 길이를 벗어났어요.')
                clip_count[0] += 1
                if clip_count[0] > MAX_CLIPS:
                    raise ValueError('오디오 클립은 %d개까지 지원해요.' % MAX_CLIPS)
                clips.append({'file': filename, 'sourceStart': float(source_start), 'start': float(dest), 'duration': float(duration)})
            else:
                flatten(slot.segment, source_rate, source_start, duration, dest, clips, depth + 1)

        for slot in comp.slots:
            if slot.media_kind != 'Sound':
                # pyaaf2 uses lowercase 'sound' for ordinary sound slots.
                if str(slot.media_kind).lower() != 'sound':
                    continue
            rate = Fraction(str(slot.edit_rate))
            duration = Fraction(slot.segment.length) / rate
            if duration <= 0:
                continue
            if duration > MAX_DURATION:
                raise ValueError('AAF 타임라인은 %d분 이하여야 해요.' % (MAX_DURATION // 60))
            if abs(int(slot['Origin'].value or 0)) > 0:
                raise ValueError('오디오 트랙 Origin이 0인 AAF로 내보내 주세요. 현재 버전은 다른 Origin을 자동 보정하지 않아요.')
            clips = []
            flatten(slot.segment, rate, Fraction(0), duration, Fraction(0), clips)
            if len(clips) > 96:
                raise ValueError('한 트랙에 오디오 클립은 96개까지 지원해요.')
            if clips:
                name = str(slot.name or '오디오 %d' % slot.slot_id)[:100]
                role = 'dialogue' if re.search(r'dialog|dx|대사|voice|vo|speech', name, re.I) else 'original'
                tracks.append({'id': 't%d' % len(tracks), 'name': name, 'role': role, 'clips': clips})
        if not tracks or len(tracks) > MAX_TRACKS:
            raise ValueError('오디오 트랙이 1~%d개인 AAF를 사용해 주세요.' % MAX_TRACKS)
        if sum(c['duration'] for t in tracks for c in t['clips']) > MAX_SECONDS:
            raise ValueError('오디오 트랙의 사용 구간 합계는 %d분 이하여야 해요.' % (MAX_SECONDS // 60))
        end = max(c['start'] + c['duration'] for t in tracks for c in t['clips'])
        if end > video_duration + 0.1:
            raise ValueError('AAF가 참조 영상보다 길어요. 영상 첫 프레임과 AAF 시작점을 맞춰 주세요.')
        if video_duration - end > 1:
            warnings.append('AAF 오디오가 영상보다 짧아요. 뒤쪽 구간은 무음으로 유지합니다.')
        warnings.append('현재 버전은 PCM AAF의 컷·빈 구간을 읽어요. 자동 대사 인식·화자 분리와 고도 왜곡 복원은 포함하지 않아요. 대사 트랙을 확인해 주세요.')
        result = {'name': str(comp.name or 'SceneSound')[:100], 'duration': video_duration, 'video': videos[0]['file'], 'tracks': tracks, 'warnings': warnings}
    save(root / 'manifest.json', result)
    return result


def mix(root, inputs, output, duration, duck=None):
    """inputs: file, delay seconds, gain dB. Each file is already trimmed to fit."""
    args, filters = [], []
    for i, item in enumerate(inputs):
        args += ['-i', str(root / item['file'])]
        filters.append('[%d:a]aresample=48000,aformat=channel_layouts=stereo,volume=%fdB,adelay=%d:all=1[a%d]' % (i, item.get('gain', 0), round(item.get('start', 0) * 1000), i))
    if not inputs:
        ff('-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', duration, '-c:a', 'pcm_s16le', root / output)
        return
    labels = ''.join('[a%d]' % i for i in range(len(inputs)))
    filters.append(labels + 'amix=inputs=%d:normalize=0:dropout_transition=0,apad,atrim=0:%f[m]' % (len(inputs), duration))
    if duck:
        args += ['-i', str(root / duck)]
        filters.append('[m][%d:a]sidechaincompress=threshold=0.04:ratio=3:attack=15:release=300:makeup=1[d]' % len(inputs))
        last = '[d]'
    else:
        last = '[m]'
    filters.append(last + 'alimiter=limit=0.89:level=0:latency=1,apad,atrim=end_sample=%d[out]' % round(duration * RATE))
    ff(*args, '-filter_complex', ';'.join(filters), '-map', '[out]', '-t', duration, '-ar', RATE, '-c:a', 'pcm_s16le', root / output)


def waveform(path, duration):
    with wave.open(str(path), 'rb') as w:
        values = []
        chunk = max(1, round(w.getframerate() * duration / 180))
        while True:
            raw = w.readframes(chunk)
            if not raw:
                break
            data = array.array('h', raw)
            if sys.byteorder != 'little':
                data.byteswap()
            values.append(round(max((abs(n) for n in data), default=0) / 32768, 3))
        return values


def prepare_analysis(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    settings = json.loads((root / 'settings.json').read_text())
    inputs = []
    for track in manifest['tracks']:
        if settings['roles'].get(track['id']) == 'ignore':
            continue
        for i, clip in enumerate(track['clips']):
            name = 'analysis-%s-%d.wav' % (track['id'], i)
            ff('-ss', clip['sourceStart'], '-i', root / clip['file'], '-t', clip['duration'], '-vn', '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / name)
            inputs.append({'file': name, 'start': clip['start']})
    mix(root, inputs, 'analysis-original.wav', manifest['duration'])
    ff('-i', root / manifest['video'], '-i', root / 'analysis-original.wav', '-map', '0:v:0', '-map', '1:a:0', '-vf', 'scale=w=min(960\\,iw):h=min(960\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', 26, '-maxrate', '1800k', '-bufsize', '3600k', '-c:a', 'aac', '-b:a', '128k', '-t', manifest['duration'], '-movflags', '+faststart', root / 'analysis-reference.mp4')
    return {**manifest, 'analysisVideo': 'analysis-reference.mp4'}


def render(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    settings = json.loads((root / 'settings.json').read_text())
    source_root = root
    root = source_root / ('render-' + uuid4().hex)
    root.mkdir(mode=0o700)
    save(root / 'manifest.json', manifest)
    duration = manifest['duration']
    warnings = list(manifest['warnings'])
    stems, originals, dialogue = [], [], []
    roles = settings['roles']
    for track in manifest['tracks']:
        role = roles.get(track['id'], 'original')
        if role == 'ignore':
            continue
        dry, wet = [], []
        for i, clip in enumerate(track['clips']):
            base = '%s-%d' % (track['id'], i)
            raw, processed = base + '-raw.wav', base + '-clean.wav'
            if not (root / raw).exists():
                ff('-ss', clip['sourceStart'], '-i', source_root / clip['file'], '-t', clip['duration'], '-vn', '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / raw)
            dry.append({'file': raw, 'start': clip['start']})
            if role == 'dialogue' and settings.get('clean', True):
                if not (root / processed).exists():
                    stats = ff('-i', root / raw, '-af', 'volumedetect', '-f', 'null', '-')
                    mean = re.search(r'mean_volume: (-?[\d.]+) dB', stats)
                    peak = re.search(r'max_volume: (-?[\d.]+) dB', stats)
                    gain = max(-6, min(6, -23 - float(mean.group(1)))) if mean else 0
                    if peak and float(peak.group(1)) >= -0.1:
                        warnings.append(track['name'] + ': 원본에 피크가 높은 구간이 있어요. 찌그러진 소리가 복원됐는지 직접 확인해 주세요.')
                    ff('-i', root / raw, '-af', 'highpass=f=65,afftdn=nr=6:nf=-50:tn=1,volume=%fdB,acompressor=threshold=0.18:ratio=1.5:attack=20:release=200:makeup=1,alimiter=limit=0.89:level=0:latency=1' % gain, '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / processed)
                wet.append({'file': processed, 'start': clip['start']})
            else:
                wet.append({'file': raw, 'start': clip['start']})
        dryfile, wetfile = track['id'] + '-original.wav', track['id'] + '.wav'
        mix(root, dry, dryfile, duration)
        mix(root, wet, wetfile, duration)
        originals.append({'file': dryfile})
        gain = settings.get('trackGains', {}).get(track['id'], 0)
        stems.append({'id': track['id'], 'name': track['name'], 'role': role, 'file': wetfile, 'gain': gain, 'clips': track['clips']})
        if role == 'dialogue':
            dialogue.append({'file': wetfile, 'gain': gain})
    if not stems:
        raise ValueError('사용할 원본 오디오 트랙을 하나 이상 골라 주세요.')
    mix(root, dialogue, 'dialogue-sidechain.wav', duration)
    for role, title in [('effect', '효과음'), ('ambience', '배경음')]:
        clips = []
        for asset in settings.get('assets', []):
            if asset['role'] != role or not asset.get('enabled', True):
                continue
            length = min(asset['end'] - asset['start'], duration - asset['start'])
            if length <= 0:
                continue
            out = asset['id'] + '-placed.wav'
            # Ambience loops; one-shot effects are never repeated automatically.
            args = ['-stream_loop', '-1'] if role == 'ambience' else []
            ff(*args, '-i', source_root / asset['file'], '-t', length, '-af', 'afade=t=in:st=0:d=0.02,afade=t=out:st=%f:d=0.03' % max(0, length - 0.03), '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / out)
            clips.append({'file': out, 'start': asset['start'], 'gain': asset.get('gain', -12 if role == 'effect' else -20), 'title': asset['title'], 'duration': length})
        if clips:
            filename = role + '.wav'
            mix(root, clips, filename, duration, 'dialogue-sidechain.wav' if dialogue else None)
            stems.append({'id': role, 'name': title, 'role': role, 'file': filename, 'gain': settings.get('trackGains', {}).get(role, 0), 'clips': clips})
    mix(root, originals, 'original.wav', duration)
    mix(root, [{'file': t['file'], 'gain': t['gain']} for t in stems], 'mix.wav', duration)
    # Exports contain the same track gains as the rendered mix, including explicit mute (-60 dB).
    for t in stems:
        export = t['id'] + '-export.wav'
        ff('-i', root / t['file'], '-af', 'volume=%fdB' % t['gain'], '-ar', RATE, '-c:a', 'pcm_s16le', root / export)
        t['export'] = export
        t['waveform'] = waveform(root / t['file'], duration)
    with aaf2.open(str(root / 'SceneSound.aaf'), 'w') as f:
        comp = f.create.CompositionMob('SceneSound processed stems')
        comp.usage = 'Usage_TopLevel'
        f.content.mobs.append(comp)
        for t in stems:
            mob = f.create.MasterMob(t['name'])
            f.content.mobs.append(mob)
            source = mob.import_audio_essence(str(root / t['export']), edit_rate=RATE)
            slot = comp.create_sound_slot(RATE)
            slot.name = t['name']
            clip = mob.create_source_clip(source.slot_id)
            slot.segment.components.append(clip)
            slot.segment.length = clip.length
    # Reference image + processed mix; original camera audio is not doubled.
    ff('-i', source_root / manifest['video'], '-i', root / 'mix.wav', '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', 24, '-c:a', 'aac', '-b:a', '192k', '-t', duration, '-movflags', '+faststart', root / 'preview.mp4')
    credits = {'note': '자동 선택한 라이브러리 미리 듣기 음원을 사용한 초안입니다. 각 원본과 이용 조건을 확인하세요.', 'assets': [{k: v for k, v in a.items() if k not in ('file', 'preview')} for a in settings.get('assets', [])]}
    save(root / 'credits.json', credits)
    result = {'renderDirectory': root.name, 'duration': duration, 'tracks': stems, 'assets': settings.get('assets', []), 'warnings': list(dict.fromkeys(warnings + settings.get('warnings', []))), 'summary': settings.get('summary', ''), 'files': ['mix.wav', 'original.wav', 'SceneSound.aaf', 'preview.mp4', 'credits.json']}
    save(root / 'result.json', result)
    with zipfile.ZipFile(root / 'SceneSound.zip', 'w', zipfile.ZIP_STORED) as z:
        for name in ['mix.wav', 'SceneSound.aaf', 'preview.mp4', 'credits.json', 'manifest.json'] + [t['export'] for t in stems]:
            z.write(root / name, name)
    return result


def main():
    root = Path(sys.argv[2]).resolve()
    action = sys.argv[1]
    try:
        result = inspect_job(root) if action == 'inspect' else render(root) if action == 'render' else prepare_analysis(root) if action == 'prepare' else None
        if result is None:
            raise ValueError('지원하지 않는 작업이에요.')
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        message = str(e) if isinstance(e, ValueError) else 'AAF/오디오를 처리하지 못했어요. 지원 형식과 연결 파일을 확인해 주세요.'
        print(json.dumps({'error': message}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
