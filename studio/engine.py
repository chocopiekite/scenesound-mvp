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
import struct
import sys
import wave
import zipfile
from uuid import uuid4
from fractions import Fraction
import aaf2

RATE = 48000
MAX_DURATION = int(os.environ.get('STUDIO_MAX_DURATION', 1800))
MAX_TRACKS = int(os.environ.get('STUDIO_MAX_TRACKS', 32))
MAX_CLIPS = int(os.environ.get('STUDIO_MAX_CLIPS', 1024))
MAX_SECONDS = int(os.environ.get('STUDIO_MAX_SECONDS', 14400))


def run(args, timeout=3600):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        if b'No space left' in result.stderr:
            raise ValueError('작업 서버 임시 공간이 부족해요. 사용 구간만 포함해 AAF를 내보내거나 이전 작업을 정리해 주세요.')
        raise ValueError('오디오 변환에 실패했어요. PCM WAV 또는 지원되는 미디어인지 확인해 주세요.')
    return result.stderr.decode('utf8', 'replace')


def ff(*args):
    bounded = []
    for arg in args:
        if str(arg) == '-i':
            bounded += ['-protocol_whitelist', 'file,pipe', '-format_whitelist', 'lavfi,wav,aiff,mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,ogg,flac']
        bounded.append(str(arg))
    return run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'info', '-y', '-threads', '1', '-filter_threads', '1', '-filter_complex_threads', '1', *bounded[:-1], '-threads', '1', bounded[-1]])


def probe(path, allow_long=False):
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'wav,aiff,mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,ogg,flac', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('미디어를 읽지 못했어요.')
    data = json.loads(result.stdout)
    duration = float(data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or not 0 < duration <= (8 * 3600 if allow_long else MAX_DURATION + 60):
        raise ValueError('미디어 길이는 11분 이하여야 해요.')
    return data, duration


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')


def open_pcm_stream(essence):
    # pyaaf2's normal Stream constructor builds a Python-int list per sector.
    # Compact 32-bit sector indexes avoid hundreds of MB for a multi-GB PCM stream.
    from aaf2.cfb import Stream, ENDOFCHAIN
    prop = essence['Data']
    entry = prop.parent.dir.get(prop.stream_name) if prop.attached else prop.dir
    storage = essence.root.cfb
    if entry is None or entry.byte_size < storage.min_stream_max_size:
        return essence.open('r')
    stream = Stream.__new__(Stream)
    stream.storage, stream.dir, stream.mode, stream.pos = storage, entry, 'r', 0
    chain = array.array('I')
    current = fast = entry.sector_id
    max_sectors = len(storage.fat)
    while current != ENDOFCHAIN:
        if not isinstance(current, int) or not 0 <= current < max_sectors or len(chain) >= max_sectors:
            raise ValueError('AAF 오디오 섹터 연결을 읽지 못했어요.')
        chain.append(current)
        current = storage.fat[current]
        for _ in range(2):
            if fast == ENDOFCHAIN:
                break
            if not isinstance(fast, int) or not 0 <= fast < max_sectors:
                raise ValueError('AAF 오디오 섹터 연결이 잘못됐어요.')
            fast = storage.fat[fast]
        if current != ENDOFCHAIN and current == fast:
            raise ValueError('AAF 오디오 섹터가 순환해요.')
    if len(chain) * storage.sector_size < entry.byte_size:
        raise ValueError('AAF 오디오가 잘렸어요.')
    stream.fat_chain = chain
    return stream


def pcm_layout(descriptor, stream):
    kind = descriptor.__class__.__name__
    if kind == 'PCMDescriptor':
        bits, channels = int(descriptor['QuantizationBits'].value), int(descriptor['Channels'].value)
        rate, frames = int(float(descriptor['AudioSamplingRate'].value)), int(descriptor.length)
        offset = 0
    elif kind == 'WAVEDescriptor':
        stream.seek(0)
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:12] != b'WAVE':
            raise ValueError('AAF 안의 WAV 헤더를 읽지 못했어요. RIFF PCM WAV를 지원해요.')
        size = stream.dir.byte_size
        cursor, fmt = 12, None
        for _ in range(10000):
            if cursor + 8 > size:
                break
            stream.seek(cursor)
            chunk = stream.read(8)
            if len(chunk) != 8:
                break
            tag, length = chunk[:4], struct.unpack('<I', chunk[4:])[0]
            if cursor + 8 + length > size:
                raise ValueError('AAF에 포함된 WAV 오디오가 잘렸어요.')
            if tag == b'fmt ':
                if not 16 <= length <= 4096:
                    raise ValueError('AAF WAV의 오디오 형식 정보가 잘못됐어요.')
                raw = stream.read(length)
                code, channels, rate, _, align, bits = struct.unpack('<HHIIHH', raw[:16])
                if code == 0xfffe:
                    if len(raw) < 40 or struct.unpack('<H', raw[16:18])[0] < 22 or raw[24:40] != bytes.fromhex('0100000000001000800000aa00389b71'):
                        raise ValueError('AAF WAV의 압축 또는 부동소수점 형식은 아직 지원하지 않아요.')
                elif code != 1:
                    raise ValueError('AAF WAV의 압축 또는 부동소수점 형식은 아직 지원하지 않아요.')
                if bits not in (16, 24, 32) or channels not in (1, 2) or align != channels * (bits // 8):
                    raise ValueError('16/24/32비트 모노·스테레오 PCM WAV를 지원해요.')
                fmt = rate, channels, bits, align
            elif tag == b'data':
                if fmt is None:
                    raise ValueError('AAF WAV의 PCM 형식 정보를 찾지 못했어요.')
                rate, channels, bits, align = fmt
                if length % align:
                    raise ValueError('AAF WAV 오디오의 샘플 크기가 맞지 않아요.')
                offset, frames = cursor + 8, length // align
                break
            cursor += 8 + length + (length % 2)
        else:
            raise ValueError('AAF WAV의 메타데이터가 너무 복잡해요.')
        if fmt is None or 'frames' not in locals():
            raise ValueError('AAF WAV에서 오디오 데이터 구간을 찾지 못했어요.')
    else:
        raise ValueError('현재는 PCMDescriptor 또는 WAVEDescriptor의 PCM 오디오가 포함된 AAF를 지원해요.')
    if bits not in (16, 24, 32) or channels not in (1, 2) or not 8000 <= rate <= 192000 or frames < 1:
        raise ValueError('AAF PCM 샘플 형식을 확인해 주세요.')
    return rate, channels, bits // 8, frames, offset


def inspect_job(root):
    uploads = json.loads((root / 'uploads.json').read_text())
    aafs = [u for u in uploads if u['role'] == 'aaf']
    videos = [u for u in uploads if u['role'] == 'video']
    if not aafs and len(videos) == 1:
        return inspect_video_job(root, videos[0])
    if len(aafs) != 1 or len(videos) > 1:
        raise ValueError('AAF 1개를 선택해 주세요. 참조 영상은 선택 사항이에요.')
    video_duration = None
    if videos:
        video_duration = validate_video(root / videos[0]['file'])
    linked = {}
    for u in uploads:
        if u['role'] == 'audio':
            key = u['name'].casefold()
            if key in linked:
                raise ValueError('같은 이름의 연결 오디오가 두 개 있어요. 파일 이름을 구분해 주세요.')
            linked[key] = u['file']
    tracks, warnings, extracted, clip_count = [], [], {}, [0]
    clip_seconds = [0]
    timeline_duration = 0
    empty_tracks = 0
    with aaf2.open(str(root / aafs[0]['file']), 'r') as f:
        comps = list(f.content.toplevel())
        if len(comps) != 1:
            raise ValueError('최상위 Composition이 하나인 AAF를 내보내 주세요.')
        comp = comps[0]

        def media(mob, start, duration):
            key = (str(mob.mob_id), str(start), str(duration))
            if key in extracted:
                return extracted[key]
            descriptor = mob.descriptor
            if mob.essence is not None:
                stream = open_pcm_stream(mob.essence)
                sample_rate, channels, width, available, data_offset = pcm_layout(descriptor, stream)
                first = round(start * sample_rate)
                frames = round(duration * sample_rate)
                if first < 0 or frames < 1 or first + frames > available:
                    stream.close()
                    raise ValueError('AAF 오디오 샘플 범위를 확인해 주세요.')
                filename = 'essence-%d.wav' % len(extracted)
                stream.seek(data_offset + first * channels * width)
                remaining = frames * channels * width
                import shutil
                if shutil.disk_usage(root).free < remaining + 512 * 1024**2:
                    raise ValueError('AAF 사용 구간을 추출할 임시 공간이 부족해요.')
                with wave.open(str(root / filename), 'wb') as out:
                    out.setparams((channels, width, sample_rate, 0, 'NONE', 'not compressed'))
                    while remaining:
                        block = stream.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError('AAF에 포함된 오디오가 잘렸어요.')
                        out.writeframesraw(block)
                        remaining -= len(block)
                stream.close()
                extracted[key] = (filename, Fraction(0))
                return extracted[key]
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
                probe(root / filename, allow_long=True)
            extracted[key] = (filename, start)
            return extracted[key]

        def flatten(seg, rate, window, duration, dest, clips, depth=0, source_gain=1.0):
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
                        flatten(child, rate, lo - cursor, hi - lo, dest + lo - window, clips, depth + 1, source_gain)
                    cursor += length
                return
            if kind == 'OperationGroup':
                inputs, parameters = list(seg.segments), list(seg.parameters)
                if str(seg.operation.auid) != '9d2ea894-0968-11d3-8a38-0050040ef7d2' or len(inputs) != 1 or len(parameters) != 1 or parameters[0].__class__.__name__ != 'ConstantValue' or str(parameters[0].parameterdef.auid) != 'e4962321-2267-11d3-8a4c-0050040ef7d2':
                    raise ValueError('이 AAF 효과는 아직 지원하지 않아요. 고정 Audio Gain만 읽을 수 있어요.')
                amplitude = float(parameters[0].value)
                if not math.isfinite(amplitude) or amplitude < 0 or amplitude * source_gain > 1e6:
                    raise ValueError('AAF 클립 게인 값을 확인해 주세요.')
                flatten(inputs[0], rate, window, duration, dest, clips, depth + 1, source_gain * amplitude)
                return
            if kind != 'SourceClip':
                raise ValueError('아직 지원하지 않는 AAF 편집 요소가 있어요: ' + kind + '. 전환·플러그인·속도 변경을 렌더링한 PCM AAF를 사용해 주세요.')
            mob, slot = seg.mob, seg.slot
            if mob is None or slot is None:
                raise ValueError('AAF에서 연결되지 않은 소스를 발견했어요.')
            source_rate = Fraction(str(slot.edit_rate))
            source_start = Fraction(seg.start) / source_rate + window
            if mob.__class__.__name__ == 'SourceMob':
                clip_seconds[0] += float(duration)
                if clip_seconds[0] > MAX_SECONDS:
                    raise ValueError('사용 구간 합계가 처리 상한을 초과했어요.')
                original_start = source_start
                if clip_count[0] >= MAX_CLIPS or float(duration) > MAX_DURATION or source_start < 0:
                    raise ValueError('AAF 클립 수 또는 구간 범위를 초과했어요.')
                filename, source_start = media(mob, source_start, duration)
                _, source_duration = probe(root / filename, allow_long=True)
                if source_start < 0 or float(source_start + duration) > source_duration + 0.025:
                    raise ValueError('AAF 클립의 소스 범위가 오디오 길이를 벗어났어요.')
                clip_count[0] += 1
                if clip_count[0] > MAX_CLIPS:
                    raise ValueError('오디오 클립은 %d개까지 지원해요.' % MAX_CLIPS)
                clips.append({'file': filename, 'sourceStart': float(source_start), 'originalSourceStart': float(original_start), 'start': float(dest), 'duration': float(duration), 'sourceGain': source_gain})
            else:
                flatten(slot.segment, source_rate, source_start, duration, dest, clips, depth + 1, source_gain)

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
            if len(clips) > 512:
                raise ValueError('한 트랙에 오디오 클립은 512개까지 지원해요.')
            timeline_duration = max(timeline_duration, float(duration))
            if not clips:
                empty_tracks += 1
            if clips:
                name = str(slot.name or '오디오 %d' % slot.slot_id)[:100]
                role = 'dialogue' if re.search(r'dialog|dx|대사|voice|vo|speech', name, re.I) else 'original'
                tracks.append({'id': 't%d' % len(tracks), 'name': name, 'role': role, 'clips': clips})
        if not tracks or len(tracks) > MAX_TRACKS:
            raise ValueError('오디오 트랙이 1~%d개인 AAF를 사용해 주세요.' % MAX_TRACKS)
        if sum(c['duration'] for t in tracks for c in t['clips']) > MAX_SECONDS:
            raise ValueError('오디오 트랙의 사용 구간 합계는 %d분 이하여야 해요.' % (MAX_SECONDS // 60))
        end = max(c['start'] + c['duration'] for t in tracks for c in t['clips'])
        if video_duration is not None and end > video_duration + 0.1:
            raise ValueError('AAF가 참조 영상보다 길어요. 영상 첫 프레임과 AAF 시작점을 맞춰 주세요.')
        if video_duration is not None and video_duration - end > 1:
            warnings.append('AAF 오디오가 영상보다 짧아요. 뒤쪽 구간은 무음으로 유지합니다.')
        warnings.append('현재 버전은 PCM AAF의 컷·빈 구간을 읽어요. 자동 대사 인식·화자 분리와 고도 왜곡 복원은 포함하지 않아요. 대사 트랙을 확인해 주세요.')
        result = {'name': str(comp.name or 'SceneSound')[:100], 'duration': video_duration or timeline_duration, 'video': videos[0]['file'] if videos else None, 'tracks': tracks, 'emptyTracks': empty_tracks, 'warnings': warnings}
    save(root / 'manifest.json', result)
    return result


def inspect_video_job(root, video):
    duration = validate_video(root / video['file'])
    info, _ = probe(root / video['file'])
    if any(s.get('codec_type') == 'audio' for s in info.get('streams', [])):
        ff('-i', root / video['file'], '-vn', '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / 'camera-original.wav')
    else:
        ff('-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', duration, '-c:a', 'pcm_s16le', root / 'camera-original.wav')
    result = {'name': video['name'], 'videoOnly': True, 'duration': duration, 'video': video['file'], 'emptyTracks': 0,
              'tracks': [{'id': 't0', 'name': '영상 원본 소리', 'role': 'original', 'clips': [{'file': 'camera-original.wav', 'sourceStart': 0, 'start': 0, 'duration': duration}]}],
              'warnings': ['영상 원본 소리는 유지하고 효과음·배경음을 더해요. 대사 클리닝은 별도 대사 도구에서 진행해 주세요.']}
    save(root / 'manifest.json', result)
    return result


def validate_video(path):
    info, duration = probe(path)
    stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    width, height = stream.get('width', 0), stream.get('height', 0)
    if not stream or duration > MAX_DURATION or min(width, height) < 360 or max(width, height) / max(1, min(width, height)) > 2.4:
        raise ValueError('영상은 %d분 이하, 가로·세로 각각 360픽셀 이상, 비율 2.4:1 이내여야 해요.' % (MAX_DURATION // 60))
    return duration


def attach_video(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    videos = [u for u in json.loads((root / 'uploads.json').read_text()) if u['role'] == 'video']
    if len(videos) != 1:
        raise ValueError('참조 영상을 하나 선택해 주세요.')
    duration = validate_video(root / videos[0]['file'])
    if duration + .1 < manifest['duration']:
        raise ValueError('영상이 AAF보다 짧아요. 시작점과 길이를 맞춰 주세요.')
    manifest.update(video=videos[0]['file'], duration=max(duration, manifest['duration']))
    save(root / 'manifest.json', manifest)
    return manifest


def mix(root, inputs, output, duration, duck=None, limit=True, codec='pcm_s16le', channels=2):
    """inputs: file, delay seconds, gain dB. Each file is already trimmed to fit."""
    if len(inputs) > 8:
        ordered = sorted(inputs, key=lambda x: x.get('start', 0))
        partials, intermediates = [], []
        try:
            for i in range(0, len(ordered), 8):
                batch = ordered[i:i + 8]
                lo = min(x.get('start', 0) for x in batch)
                hi = min(duration, max(x.get('start', 0) + probe(root / x['file'], allow_long=True)[1] for x in batch))
                name = 'batch-' + uuid4().hex + '.wav'
                intermediates.append(name)
                mix(root, [{**x, 'start': x.get('start', 0) - lo} for x in batch], name, hi - lo, limit=False, codec='pcm_f32le', channels=channels)
                partials.append({'file': name, 'start': lo})
            mix(root, partials, output, duration, duck=duck, limit=limit, codec=codec, channels=channels)
            return
        finally:
            for name in intermediates:
                (root / name).unlink(missing_ok=True)
    args, filters = [], []
    for i, item in enumerate(inputs):
        args += ['-i', str(root / item['file'])]
        filters.append('[%d:a]aresample=48000,aformat=channel_layouts=%s,volume=%fdB,adelay=%dS:all=1[a%d]' % (i, 'mono' if channels == 1 else 'stereo', item.get('gain', 0), round(item.get('start', 0) * RATE), i))
    if not inputs:
        ff('-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=' + ('mono' if channels == 1 else 'stereo'), '-t', duration, '-c:a', codec, root / output)
        return
    labels = ''.join('[a%d]' % i for i in range(len(inputs)))
    filters.append(labels + 'amix=inputs=%d:normalize=0:dropout_transition=0[m]' % len(inputs))
    if duck:
        args += ['-i', str(root / duck)]
        filters.append('[m][%d:a]sidechaincompress=threshold=0.04:ratio=3:attack=15:release=300:makeup=1[d]' % len(inputs))
        last = '[d]'
    else:
        last = '[m]'
    filters.append(last + ('alimiter=limit=0.89:level=0:latency=1,' if limit else '') + 'apad,atrim=end_sample=%d[out]' % round(duration * RATE))
    ff(*args, '-filter_complex', ';'.join(filters), '-map', '[out]', '-ar', RATE, '-c:a', codec, root / output)


def waveform(path, duration, points=180):
    with wave.open(str(path), 'rb') as w:
        values = []
        chunk = max(1, round(w.getframerate() * duration / points))
        while True:
            raw = w.readframes(chunk)
            if not raw:
                break
            data = array.array('h', raw)
            if sys.byteorder != 'little':
                data.byteswap()
            values.append(round(max((abs(n) for n in data), default=0) / 32768, 3))
        return values


def cached_pcm(path, duration):
    try:
        with wave.open(str(path), 'rb') as w:
            return (w.getframerate() == RATE and w.getnchannels() == 2 and w.getsampwidth() == 2
                    and abs(w.getnframes() - round(duration * RATE)) <= 2
                    and path.stat().st_size >= w.getnframes() * 4)
    except (OSError, EOFError, wave.Error):
        return False


def prepare_analysis(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    settings = json.loads((root / 'settings.json').read_text())
    if not manifest.get('video'):
        raise ValueError('효과음·배경음 단계에서는 참조 영상이 필요해요.')
    inputs = []
    for track in ([] if settings.get('useDialogue') else manifest['tracks']):
        if settings['roles'].get(track['id']) == 'ignore':
            continue
        for i, clip in enumerate(track['clips']):
            name = 'analysis-%s-%d.wav' % (track['id'], i)
            if not cached_pcm(root / name, clip['duration']):
                ff('-ss', clip['sourceStart'], '-i', root / clip['file'], '-t', clip['duration'], '-vn', '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / name)
            inputs.append({'file': name, 'start': clip['start'], 'gain': 20 * math.log10(clip.get('sourceGain', 1)) if clip.get('sourceGain', 1) > 0 else -120})
    if settings.get('useDialogue'):
        inputs = [{'file': 'dialogue-approved.wav'}]
    mix(root, inputs, 'analysis-original.wav', manifest['duration'])
    segments = []
    count = math.ceil(manifest['duration'] / 600)
    for i in range(count):
        start = i * manifest['duration'] / count
        length = min(600, manifest['duration'] - start, manifest['duration'] / count)
        name = 'analysis-reference.mp4' if i == 0 else 'analysis-%03d.mp4' % i
        ff('-ss', start, '-i', root / manifest['video'], '-ss', start, '-i', root / 'analysis-original.wav', '-map', '0:v:0', '-map', '1:a:0', '-vf', 'scale=w=min(960\\,iw):h=min(960\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', 26, '-maxrate', '1800k', '-bufsize', '3600k', '-c:a', 'aac', '-b:a', '128k', '-t', length, '-movflags', '+faststart', root / name)
        segments.append({'file': name, 'start': start, 'duration': length})
    return {**manifest, 'analysisVideo': segments[0]['file'], 'analysisSegments': segments}



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
    for track in ([] if settings.get('useDialogue') else manifest['tracks']):
        role = roles.get(track['id'], 'original')
        if role == 'ignore':
            continue
        dry, wet = [], []
        for i, clip in enumerate(track['clips']):
            base = '%s-%d' % (track['id'], i)
            raw, processed = base + '-raw.wav', base + '-clean.wav'
            if not (root / raw).exists():
                ff('-ss', clip['sourceStart'], '-i', source_root / clip['file'], '-t', clip['duration'], '-vn', '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / raw)
            source_gain_db = 20 * math.log10(clip.get('sourceGain', 1)) if clip.get('sourceGain', 1) > 0 else -120
            dry.append({'file': raw, 'start': clip['start'], 'gain': source_gain_db})
            if role == 'dialogue' and settings.get('clean', True):
                if not (root / processed).exists():
                    stats = ff('-i', root / raw, '-af', 'volumedetect', '-f', 'null', '-')
                    mean = re.search(r'mean_volume: (-?[\d.]+) dB', stats)
                    peak = re.search(r'max_volume: (-?[\d.]+) dB', stats)
                    gain = max(-6, min(6, -23 - float(mean.group(1)))) if mean else 0
                    if peak and float(peak.group(1)) >= -0.1:
                        warnings.append(track['name'] + ': 원본에 피크가 높은 구간이 있어요. 찌그러진 소리가 복원됐는지 직접 확인해 주세요.')
                    ff('-i', root / raw, '-af', 'highpass=f=65,afftdn=nr=6:nf=-50:tn=1,volume=%fdB,acompressor=threshold=0.18:ratio=1.5:attack=20:release=200:makeup=1,alimiter=limit=0.89:level=0:latency=1' % gain, '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / processed)
                wet.append({'file': processed, 'start': clip['start'], 'gain': source_gain_db})
            else:
                wet.append({'file': raw, 'start': clip['start'], 'gain': source_gain_db})
        dryfile, wetfile = track['id'] + '-original.wav', track['id'] + '.wav'
        mix(root, dry, dryfile, duration)
        mix(root, wet, wetfile, duration)
        originals.append({'file': dryfile})
        gain = settings.get('trackGains', {}).get(track['id'], 0)
        stems.append({'id': track['id'], 'name': track['name'], 'role': role, 'file': wetfile, 'gain': gain, 'clips': track['clips']})
        if role == 'dialogue':
            dialogue.append({'file': wetfile, 'gain': gain})
    if settings.get('useDialogue'):
        import shutil
        for name in ['dialogue-approved.wav', 'dialogue-original.wav']:
            shutil.copyfile(source_root / name, root / name)
        stems.append({'id': 'dialogue', 'name': '정리된 대사 · 클립별 보정', 'role': 'dialogue', 'file': 'dialogue-approved.wav', 'gain': settings.get('trackGains', {}).get('dialogue', 0), 'clips': [{'start': 0, 'duration': duration}]})
        originals.append({'file': 'dialogue-original.wav'})
        dialogue.append({'file': 'dialogue-approved.wav'})
    if not stems:
        raise ValueError('사용할 원본 오디오 트랙을 하나 이상 골라 주세요.')
    mix(root, dialogue, 'dialogue-sidechain.wav', duration)
    channels = settings.get('effectChannels') or [{'id': 'effect', 'name': '효과음', 'role': 'effect'}, {'id': 'ambience', 'name': '배경음', 'role': 'ambience'}]
    for channel in channels:
        role, title = channel['role'], channel['name']
        clips = []
        for asset in settings.get('assets', []):
            if asset.get('channelId', asset['role']) != channel['id'] or not asset.get('enabled', True):
                continue
            length = min(asset['end'] - asset['start'], duration - asset['start'])
            if length <= 0:
                continue
            out = asset['id'] + '-placed.wav'
            # Ambience loops; one-shot effects are never repeated automatically.
            args = ['-stream_loop', '-1'] if role == 'ambience' else []
            ff(*args, '-i', source_root / asset['file'], '-t', length, '-af', 'afade=t=in:st=0:d=0.02,afade=t=out:st=%f:d=0.03' % max(0, length - 0.03), '-ac', 2, '-ar', RATE, '-c:a', 'pcm_s16le', root / out)
            clips.append({'file': out, 'start': asset['start'], 'gain': asset.get('gain', -12 if role == 'effect' else -20), 'title': asset['title'], 'duration': length})
        if clips or settings.get('effectChannels'):
            filename = channel['id'] + '.wav'
            # Each channel keeps the existing dialogue sidechain ducking.
            mix(root, clips, filename, duration, 'dialogue-sidechain.wav' if dialogue else None)
            stems.append({'id': channel['id'], 'name': title, 'role': role, 'file': filename, 'gain': settings.get('trackGains', {}).get(channel['id'], 0), 'clips': clips})
    mix(root, originals, 'original.wav', duration)
    mix(root, [{'file': t['file'], 'gain': t['gain']} for t in stems if t['gain'] > -60], 'mix.wav', duration)
    # Exports contain the same track gains as the rendered mix, including explicit mute (-60 dB).
    for t in stems:
        export = t['id'] + '-export.wav'
        ff('-i', root / t['file'], '-af', 'volume=0' if t['gain'] <= -60 else 'volume=%fdB' % t['gain'], '-ar', RATE, '-c:a', 'pcm_s16le', root / export)
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
    result = {'renderDirectory': root.name, 'duration': duration, 'tracks': stems, 'assets': settings.get('assets', []), 'effectChannels': channels, 'editorVersion': 1, 'warnings': list(dict.fromkeys(warnings + settings.get('warnings', []))), 'summary': settings.get('summary', ''), 'files': ['mix.wav', 'original.wav', 'SceneSound.aaf', 'preview.mp4', 'credits.json']}
    save(root / 'result.json', result)
    with zipfile.ZipFile(root / 'SceneSound.zip', 'w', zipfile.ZIP_STORED) as z:
        for name in ['mix.wav', 'SceneSound.aaf', 'preview.mp4', 'credits.json', 'manifest.json'] + [t['export'] for t in stems]:
            z.write(root / name, name)
    return result


def main():
    root = Path(sys.argv[2]).resolve()
    action = sys.argv[1]
    try:
        from dialogue import render_dialogue
        if action in ['inspect-automatic', 'automatic']:
            import automatic
            result = automatic.inspect_job(root, sys.modules[__name__]) if action == 'inspect-automatic' else automatic.render(root, sys.modules[__name__])
            print(json.dumps(result, ensure_ascii=False))
            return
        if action=='prepare-dialogue-video':
            from dialogue_video import prepare
            print(json.dumps(prepare(root,sys.modules[__name__]),ensure_ascii=False));return
        result = __import__('dialogue_preserve').inspect_job(root, sys.modules[__name__]) if action == 'inspect-dialogue' else render_dialogue(root, sys.modules[__name__]) if action == 'dialogue' else attach_video(root) if action == 'attach-video' else inspect_job(root) if action == 'inspect' else render(root) if action == 'render' else prepare_analysis(root) if action == 'prepare' else None
        if result is None:
            raise ValueError('지원하지 않는 작업이에요.')
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        message = str(e) if isinstance(e, ValueError) else 'AAF/오디오를 처리하지 못했어요. 지원 형식과 연결 파일을 확인해 주세요.'
        print(json.dumps({'error': message}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
