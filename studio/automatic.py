"""Beginner waveform cleanup. Separate outputs; never overwrite an AAF/source."""
from pathlib import Path
from uuid import uuid4
import json, math, os, subprocess, wave, struct
from fractions import Fraction
import aaf2
import numpy as np

RATE = 48000


def filters_available():
    r = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, timeout=15)
    return r.returncode == 0 and all(name in r.stdout for name in ['adeclip ', 'afftdn ', 'alimiter '])


def upload(root):
    items = json.loads((root / 'uploads.json').read_text())
    if len(items) != 1 or items[0]['role'] not in ['aaf', 'audio', 'video']:
        raise ValueError('영상·오디오·AAF 중 파일 하나만 선택해 주세요.')
    item = items[0]
    if not isinstance(item.get('file'), str) or Path(item['file']).name != item['file']:
        raise ValueError('업로드 파일 경로를 확인해 주세요.')
    return item, root / item['file']


def inspect_job(root, engine):
    item, path = upload(root)
    if not filters_available():
        raise ValueError('작업 서버의 클리닝·디클립 도구를 준비하지 못했어요.')
    if item['role'] == 'aaf':
        import dialogue_preserve
        with aaf2.open(str(path)) as f:
            native = any(c.__class__.__name__ == 'Transition' for comp in f.content.toplevel() for slot in comp.slots if str(slot.media_kind).lower() == 'sound' and slot.segment.__class__.__name__ == 'Sequence' for c in slot.segment.components)
        result = inspect_native(path, engine) if native else dialogue_preserve.inspect_job(root, engine)
        result.update(workflow='automatic', inputKind='aaf')
    else:
        data, duration = engine.probe(path)
        if duration > engine.MAX_DURATION or not any(s.get('codec_type') == 'audio' for s in data['streams']):
            raise ValueError('소리가 있는 30분 이하 파일을 선택해 주세요.')
        result = {'workflow': 'automatic', 'inputKind': item['role'], 'name': item['name'][:160], 'duration': duration, 'tracks': []}
    engine.save(root / 'manifest.json', result)
    return result


def inspect_native(path, engine):
    import dialogue_preserve as preserve
    import dialogue_fades as fades
    import re
    tracks, duration, clips, transitions = [], 0., 0, 0
    with aaf2.open(str(path)) as f:
        compositions = list(f.content.toplevel())
        if len(compositions) != 1:
            raise ValueError('최상위 편집 정보가 하나인 AAF를 사용해 주세요.')
        comp = compositions[0]
        for slot in comp.slots:
            if str(slot.media_kind).lower() != 'sound': continue
            if slot.segment.__class__.__name__ != 'Sequence' or int(slot['Origin'].value or 0):
                raise ValueError('일반 오디오 트랙 구조의 AAF를 사용해 주세요.')
            rate = Fraction(str(slot.edit_rate))
            if rate <= 0: raise ValueError('AAF 트랙의 시간 단위를 확인해 주세요.')
            duration = max(duration, float(Fraction(slot.length) / rate)); parts = []
            for index, tick, component in slot.segment.positions():
                if tick < 0: raise ValueError('AAF의 페이드 위치를 확인해 주세요.')
                if component.__class__.__name__ == 'Filler': continue
                if component.__class__.__name__ == 'Transition':
                    group = component['OperationGroup'].value
                    if str(group.operation.auid) != fades.DISSOLVE or len(group.parameters) != 1:
                        raise ValueError('지원하는 대사 페이드가 아닌 AAF 효과가 있어요.')
                    curve = list(group.parameters)[0]
                    if (str(curve.parameterdef.auid) != fades.LEVEL or len(curve['PointList']) != 2
                            or str(curve.interpolationdef.auid) not in [fades.LINEAR, fades.POWER]
                            or [(float(x.time), float(x.value)) for x in curve['PointList'].value] != [(0, 0), (1, 1)]
                            or not 0 <= component.cutpoint <= component.length or component.length <= 0):
                        raise ValueError('복잡한 페이드 곡선은 원본 AAF 편집 도구에서 확인해 주세요.')
                    transitions += 1; continue
                leaf, _ = preserve.ungroup(component)
                if leaf.__class__.__name__ != 'SourceClip': raise ValueError('PCM 오디오 컷과 기본 페이드가 포함된 AAF를 사용해 주세요.')
                seconds = Fraction(component.length) / rate
                mob, start, gain = preserve.resolve(component, duration=(seconds, rate))
                stream = engine.open_pcm_stream(mob.essence); layout = engine.pcm_layout(mob.descriptor, stream); stream.close()
                if start < 0 or round(start * layout[0]) + round(seconds * layout[0]) > layout[3]:
                    raise ValueError('AAF 원본 핸들 범위를 확인해 주세요.')
                parts.append({'start': float(Fraction(tick) / rate), 'duration': float(seconds), 'componentIndex': index, 'name': str(leaf.mob.name or '')[:160]})
                clips += 1
                if clips > engine.MAX_CLIPS: raise ValueError('AAF 클립 수가 처리 한도를 넘었어요.')
            if parts:
                name = str(slot.name or '오디오')[:100]
                role = 'original' if re.search(r'\bOMF\b|\bGUIDE\b|\bDIA\s*B\b|\bWALLA\b', name, re.I) else 'dialogue'
                tracks.append({'id': 't%d' % len(tracks), 'slotId': slot.slot_id, 'name': name, 'role': role, 'clips': parts})
        if not tracks or len(tracks) > engine.MAX_TRACKS or not 0 < duration <= engine.MAX_DURATION:
            raise ValueError('AAF 트랙 수 또는 30분 길이 한도를 확인해 주세요.')
        if sum(c['duration'] for t in tracks for c in t['clips']) > engine.MAX_SECONDS:
            raise ValueError('AAF 오디오 사용 구간의 합계가 처리 한도를 넘었어요.')
        return {'name': str(comp.name or 'AAF')[:100], 'duration': duration, 'tracks': tracks, 'nativeInput': True, 'nativeFades': transitions}


def check_space(source, duration):
    budget = int(os.environ.get('STUDIO_STORAGE_BUDGET_BYTES', 0))
    if not budget:
        return
    used = sum(p.stat().st_size for p in source.parent.rglob('*') if p.is_file())
    # Two mono float work files plus one 24bit comparison, with headroom.
    if used + math.ceil(duration * RATE) * 11 + 64 * 1024 ** 2 > budget:
        raise ValueError('비교 음원과 처리용 임시 공간이 부족해요. 짧게 나눈 파일이나 로컬 자동 정리로 진행해 주세요.')


def clipping_ranges(path):
    """Conservative flat-top detector, including attenuated hard clipping.

    Bounded 5s chunks. A high peak alone is never counted as clipping.
    """
    args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1',
            '-protocol_whitelist', 'file,pipe', '-i', str(path), '-ar', str(RATE), '-ac', '1', '-f', 'f32le', '-']
    events, position, plateau_samples, truncated = [], 0, 0, False
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        carry = np.zeros(0, dtype=np.float32)
        while True:
            block = proc.stdout.read(RATE * 5 * 4)
            if not block:
                break
            new = np.frombuffer(block, dtype='<f4')
            x = np.concatenate((carry, new)).astype(np.float64)
            offset = position - len(carry)
            peak = float(np.max(np.abs(x))) if len(x) else 0
            rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0
            if peak >= .03 and rms and abs(float(np.mean(x))) < rms * .4:
                equal = np.abs(np.diff(x)) <= 1e-7
                hot = (np.abs(x[:-1]) >= .03) & equal
                edges = np.diff(np.r_[False, hot, False].astype(np.int8))
                runs = []
                for a, b in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
                    length = b - a + 1
                    # Longer flat tops are required below full scale, where
                    # ordinary low-level PCM quantization can round a peak.
                    if length >= (3 if abs(x[a]) >= .98 else 8):
                        runs.append((a, b + 1))
                groups = {}
                for a, b in runs:
                    height = round(abs(float(x[a])), 5)
                    groups.setdefault(height, []).append((a, b))
                runs = [r for group in groups.values() if len(group) >= 2 and sum(b - a for a, b in group) >= 12 for r in group]
                runs.sort()
                if runs:
                    for a, b in runs:
                        plateau_samples += b - a
                        lo, hi = max(0, (offset + a) / RATE - .08), (offset + b) / RATE + .08
                        if events and lo <= events[-1][1] + .1:
                            events[-1][1] = max(events[-1][1], hi)
                        elif len(events) < 60:
                            events.append([lo, hi])
                        else:
                            truncated = True
            position += len(new)
            carry = new[-32:]
        if proc.wait(timeout=3600):
            raise ValueError('클리핑 의심 구간을 읽지 못했어요.')
    duration = position / RATE
    return {'ranges': [[a, min(b, duration)] for a, b in events], 'plateauSamples': plateau_samples,
            'samples': position, 'truncated': truncated, 'needsReview': truncated or len(events) >= 60 or plateau_samples / max(1, position) > .05}


def pcm_wave_info(path, encoding=3, expected_bits=32):
    with path.open('rb') as f:
        if f.read(4) != b'RIFF':
            raise ValueError('처리용 WAV 컨테이너를 확인하지 못했어요.')
        f.read(4)
        if f.read(4) != b'WAVE':
            raise ValueError('처리용 WAV 형식을 확인하지 못했어요.')
        valid = False
        while True:
            header = f.read(8)
            if len(header) != 8:
                raise ValueError('처리용 WAV가 잘렸어요.')
            tag, size = struct.unpack('<4sI', header)
            if tag == b'fmt ':
                data = f.read(size)
                kind, channels, rate = struct.unpack_from('<HHI', data)
                bits = struct.unpack_from('<H', data, 14)[0]
                if kind == 0xfffe and len(data) >= 40:
                    kind = struct.unpack_from('<H', data, 24)[0]
                valid = kind == encoding and channels == 1 and rate == RATE and bits == expected_bits
            elif tag == b'data':
                if not valid or size % (expected_bits // 8):
                    raise ValueError('처리용 float WAV 형식이 맞지 않아요.')
                if f.tell() + size > path.stat().st_size:
                    raise ValueError('처리용 WAV 오디오가 잘렸어요.')
                return f.tell(), size // (expected_bits // 8)
            else:
                f.seek(size, 1)
            if size % 2:
                f.seek(1, 1)


def write_float(path, samples):
    data = np.asarray(samples, dtype='<f4').tobytes()
    fmt = struct.pack('<HHIIHH', 3, 1, RATE, RATE * 4, 4, 32)
    with path.open('wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVEfmt ' + struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', len(data)) + data)


def repair_regions(path, events, engine, progress=None):
    """Only generated float scratch is edited, never uploaded source data.

    Process short suspect windows with context, then explicitly blend changes
    into the scratch samples. FFmpeg timeline enable alone is insufficient to
    guarantee untouched samples outside the selected window.
    """
    offset, count = pcm_wave_info(path)
    attempts, rejected, remaining_budget = [], [], RATE * 120
    for lo, hi in events:
        start, end = max(0, round(lo * RATE)), min(count, round(hi * RATE))
        for pos in range(start, end, RATE * 8):
            stop = min(end, pos + RATE * 8)
            if remaining_budget < stop - pos:
                rejected.append([pos / RATE, stop / RATE]); continue
            remaining_budget -= stop - pos
            a, b = max(0, pos - 4800), min(count, stop + 4800)
            with path.open('rb') as f:
                f.seek(offset + a * 4); original = np.frombuffer(f.read((b - a) * 4), dtype='<f4').copy()
            raw, fixed = path.parent / 'repair-window.wav', path.parent / 'repair-fixed.wav'
            write_float(raw, original)
            if progress:
                progress('클리핑 의심 구간을 복원하고 있어요 · %.1f초' % (pos / RATE))
            engine.ff('-i', raw, '-af', 'adeclip=w=10:o=50:a=4:t=10', '-ar', RATE, '-ac', 1, '-c:a', 'pcm_f32le', fixed)
            repaired_offset, repaired_count = pcm_wave_info(fixed)
            if repaired_count != len(original):
                raise ValueError('디클립 전후 샘플 길이가 달라 복원을 중단했어요.')
            with fixed.open('rb') as f:
                f.seek(repaired_offset); repaired = np.frombuffer(f.read(repaired_count * 4), dtype='<f4')
            if (not np.all(np.isfinite(repaired)) or float(np.max(np.abs(repaired))) > max(.5, float(np.max(np.abs(original))) * 6)):
                rejected.append([pos / RATE, stop / RATE]); continue
            indices = np.arange(a, b)
            weight = np.minimum(np.clip((indices - pos) / 960, 0, 1), np.clip((stop - 1 - indices) / 960, 0, 1))
            mixed = (original + weight * (repaired - original)).astype('<f4')
            assert np.array_equal(mixed[weight == 0], original[weight == 0])
            with path.open('r+b') as f:
                f.seek(offset + a * 4); f.write(mixed.tobytes())
            attempts.append([pos / RATE, stop / RATE])
    for name in ['repair-window.wav', 'repair-fixed.wav']:
        (path.parent / name).unlink(missing_ok=True)
    return {'attemptedRanges': attempts, 'unprocessedRanges': rejected}


def cleanup_filter(reduction, floor):
    # Same amount/profile over the pass: no noise gate or per-word tracking.
    return 'highpass=f=50,afftdn=nr=%g:nf=%g:tn=0' % (reduction, max(-80, min(-20, floor)))


def cleanup_delay(root, reduction, floor, engine):
    # Detect actual installed-filter latency instead of assuming an FFmpeg version.
    raw, processed = root / 'auto-latency-input.wav', root / 'auto-latency-output.wav'
    x = np.zeros(RATE // 2, dtype=np.float32); origin = RATE // 5; x[origin] = .1
    write_float(raw, x)
    engine.ff('-i', raw, '-af', cleanup_filter(reduction, floor), '-c:a', 'pcm_f32le', processed)
    offset, count = pcm_wave_info(processed)
    with processed.open('rb') as f:
        f.seek(offset); y = np.frombuffer(f.read(count * 4), dtype='<f4')
    if not len(y) or float(np.max(np.abs(y))) < 1e-5:
        raise ValueError('클리닝 필터의 시간 지연을 확인하지 못했어요.')
    delay = int(np.argmax(np.abs(y))) - origin
    if not 0 <= delay <= RATE // 5:
        raise ValueError('클리닝 시간 지연이 예상 범위를 벗어나 출력을 중단했어요.')
    raw.unlink(); processed.unlink()
    return delay


def wave_info(path, engine, samples=None):
    data, duration = engine.probe(path)
    stream = next(s for s in data['streams'] if s['codec_type'] == 'audio')
    if int(stream['sample_rate']) != RATE or int(stream['channels']) != 1:
        raise ValueError('대사 WAV 출력 형식 검증에 실패했어요.')
    if samples is not None:
        _, frames = pcm_wave_info(path, encoding=1, expected_bits=24)
        if frames != samples:
            raise ValueError('원본과 처리본의 길이·24bit 출력 검증에 실패했어요.')
    return duration


def find_reference(root, path, duration, engine, hints=None):
    """Bounded scans; final calibration uses the CLEANED sound, not stale LUFS."""
    from speech import Analyzer
    analyzer = Analyzer()
    spans = []
    for r in hints or []:
        if r.get('ready'):
            spans.append((r['start'], min(r.get('duration', 6), duration - r['start'])))
    # At most 30 windows spread over the file when an AAF anchor isn't usable.
    spans += [(float(a), min(8., duration - float(a))) for a in np.linspace(0, max(0, duration - 8), min(30, max(1, math.ceil(duration / 8))))]
    floor, fallback = None, None
    for start, length in spans:
        if length < .4:
            continue
        clip = root / 'auto-reference.wav'
        engine.ff('-ss', start, '-i', path, '-t', length, '-ar', RATE, '-ac', 1, '-c:a', 'pcm_s24le', clip)
        info = analyzer.classify(clip, length, 0, 1)
        if floor is None and info.get('noiseFloorDbfs') is not None:
            floor = info['noiseFloorDbfs']
        if info['category'] != 'speech':
            continue
        levels = analyzer.levels(clip, info['speech'], 1, engine)
        if levels['lufs'] is None or levels['truePeakDbtp'] is None:
            continue
        candidate = {'start': start, 'duration': length, **levels}
        if levels['metric'] == 'shortTerm' and -15 <= levels['truePeakDbtp'] - 24 - levels['lufs'] <= -10:
            clip.unlink(missing_ok=True)
            return candidate, floor
        if fallback is None:
            fallback = candidate
    (root / 'auto-reference.wav').unlink(missing_ok=True)
    return fallback, floor


def render(source, engine):
    from dialogue import measure, clip_gain
    manifest = json.loads((source / 'manifest.json').read_text())
    options = json.loads((source / 'settings.json').read_text())
    item, input_path = upload(source)
    duration = manifest['duration']; samples = round(duration * RATE); duration = samples / RATE
    check_space(source, duration)
    if not filters_available():
        raise ValueError('서버에서 클리닝·디클립 필터를 찾지 못했어요.')
    def progress(text):
        engine.save(source / 'progress.json', {'stage': text})
    hints, preparation = [], None
    if item['role'] == 'aaf':
        import dialogue_preserve
        roles = {t['id']: 'dialogue' if t['role'] == 'dialogue' else 'ignore' for t in manifest['tracks']}
        fallback_tracks = not any(r == 'dialogue' for r in roles.values())
        if fallback_tracks:
            roles = {t['id']: 'dialogue' for t in manifest['tracks']}
        engine.save(source / 'settings.json', {**options, 'roles': roles, 'deduplicate': True, 'removeSilence': True, 'fades': True,
                                               'scenes': [{'start': 0, 'title': '자동 대사 정리'}]})
        if manifest.get('nativeInput'):
            import dialogue_fades
            root = source / ('render-' + uuid4().hex); root.mkdir(mode=0o700)
            rows = [{'slotId': t['slotId']} for t in manifest['tracks'] if roles[t['id']] == 'dialogue']
            with aaf2.open(str(input_path)) as f:
                dialogue_fades.preview(f, root, rows, [], engine, duration, codec='pcm_f32le', channels=1)
            prepared = root / 'mix.wav'; original_float = prepared
            selected = [t for t in manifest['tracks'] if roles[t['id']] == 'dialogue']
            hints = [{'ready': True, 'start': c['start'], 'duration': c['duration']} for t in selected for c in t['clips'] if c['duration'] >= 3][:10]
            preparation = {'retainedClips': sum(len(t['clips']) for t in selected), 'duplicates': [], 'silences': [],
                           'fades': [None] * manifest['nativeFades'], 'selectedTracks': [t['name'] for t in selected], 'nativeInput': True}
        else:
            preparation = dialogue_preserve.render_dialogue(source, engine, preview_only=True)
            root = source / preparation['renderDirectory']; prepared = root / 'mix.wav'; original_float = root / 'original.wav'
            hints = preparation['references']
    else:
        root = source / ('render-' + uuid4().hex); root.mkdir(mode=0o700)
        progress('원본 소리를 읽고 비교 음원을 준비하고 있어요.')
        prepared = root / 'mix.wav'
        engine.ff('-i', input_path, '-map', '0:a:0', '-vn', '-ar', RATE, '-ac', 1,
                  '-af', 'aresample=48000:async=1:first_pts=0,apad,atrim=end_sample=%d' % samples, '-c:a', 'pcm_f32le', prepared)
        original_float = prepared
    original = root / 'auto-original.wav'
    original_peak = measure(engine, original_float)['input_tp']
    comparison_gain = min(0., -1 - original_peak) if math.isfinite(original_peak) else 0.
    engine.ff('-i', original_float, '-af', 'volume=%fdB,apad,atrim=end_sample=%d' % (comparison_gain, samples), '-ar', RATE, '-ac', 1, '-c:a', 'pcm_s24le', original)
    if original_float != prepared:
        original_float.unlink()
    progress('클리핑 의심 구간과 배경 소리를 확인하고 있어요.')
    clipping = clipping_ranges(prepared)
    repairs = repair_regions(prepared, clipping['ranges'], engine, progress)
    _, floor = find_reference(root, prepared, duration, engine, hints)
    floor = -55 if floor is None else floor
    reduction = 3 if options.get('strength') == 'gentle' else 6
    progress('필요한 구간의 디클립과 가벼운 잡음 정리를 하고 있어요.')
    cleaned = root / 'auto-cleaning.wav'
    delay = cleanup_delay(root, reduction, floor, engine)
    engine.ff('-i', prepared, '-af', 'apad=pad_len=%d,' % delay + cleanup_filter(reduction, floor) + ',atrim=start_sample=%d:end_sample=%d,asetpts=PTS-STARTPTS,apad,atrim=end_sample=%d' % (delay, samples + delay, samples),
              '-ar', RATE, '-ac', 1, '-c:a', 'pcm_f32le', cleaned)
    prepared.unlink()
    progress('정리된 대사로 마지막 레벨을 확인하고 있어요.')
    reference, _ = find_reference(root, cleaned, duration, engine, hints)
    gain = 0.
    if reference:
        gain = max(-24., min(18., clip_gain(reference['lufs'], reference['truePeakDbtp'])))
    final = root / 'auto-clean.wav'
    engine.ff('-i', cleaned, '-af', 'volume=%fdB,aresample=192000,alimiter=limit=0.89125:level=0:latency=1,aresample=48000,apad,atrim=end_sample=%d' % (gain, samples),
              '-ar', RATE, '-ac', 1, '-c:a', 'pcm_s24le', final)
    cleaned.unlink()
    progress('원본과 처리본의 길이·피크·다운로드 파일을 검증하고 있어요.')
    wave_info(original, engine, samples); wave_info(final, engine, samples)
    measured = measure(engine, final)
    tp = measured['input_tp'] if math.isfinite(measured['input_tp']) else None
    if tp is not None and tp > -.8:
        raise ValueError('출력 피크 안전 검증에 실패했어요. 원본 파일은 그대로 보존했어요.')
    warnings = ['가벼운 일정 잡음과 클리핑 의심 구간을 정리한 결과예요. 음악·겹친 인물·심한 잔향은 분리하지 않아요.',
                '숨소리·작은 대사·액팅이 자연스러운지 원본과 비교해 주세요. 심한 왜곡은 완전히 복구되지 않을 수 있어요.',
                '비교용 원본 WAV는 원본 소리를 모노로 변환한 파일이며, 업로드 파일 자체는 수정하지 않았어요.']
    if clipping['truncated']:
        warnings.append('표시 한도를 넘는 클리핑 의심 구간은 복원을 보류했어요. 긴 파일은 짧게 나눠 확인해 주세요.')
    if clipping['needsReview']:
        warnings.append('클리핑이 심하거나 의심 구간이 많아요. 복원 결과를 꼭 원본과 비교해 주세요.')
    if repairs['unprocessedRanges']:
        warnings.append('복원 안정성 또는 처리량 제한으로 일부 의심 구간은 디클립을 보류했어요. 표시한 구간을 확인해 주세요.')
    if comparison_gain < -.01:
        warnings.append('비교용 원본은 재생 중 피크 초과를 막기 위해 음량만 %.2fdB 낮췄어요.' % -comparison_gain)
    if not reference:
        warnings.append('확실한 대사 기준을 찾지 못해 마지막 음량은 강제로 키우지 않았어요.')
    if preparation:
        warnings.append('입력 AAF의 기존 기본 페이드·게인을 반영했어요. 이미 페이드가 있는 AAF는 중복 삭제를 생략해요.' if preparation.get('nativeInput') else 'AAF는 이름으로 선택한 대사 트랙을 사용하고 완전 중복·무음을 정리했어요. 다른 마이크나 겹친 대사는 완벽히 자동 선택할 수 없어요.')
    report = {'mode': 'automaticCleanupV1', 'duration': duration, 'sampleRate': RATE, 'channels': 1, 'bitDepth': 24,
              'clippingCandidates': clipping['ranges'], 'declipAttempted': bool(repairs['attemptedRanges']), 'declipRanges': repairs['attemptedRanges'],
              'unprocessedClippingRanges': repairs['unprocessedRanges'], 'clippingNeedsReview': clipping['needsReview'] or bool(repairs['unprocessedRanges']),
              'noiseReductionDb': reduction, 'noiseProfileDbfs': floor, 'compensatedFilterDelaySamples': delay, 'finalGainDb': gain, 'comparisonGainDb': comparison_gain, 'reference': reference,
              'outputTruePeakDbtp': tp, 'framesVerified': samples, 'sourceFileModified': False,
              'preparation': {'retainedClips': preparation['retainedClips'], 'duplicates': len(preparation['duplicates']),
                              'silences': len(preparation['silences']), 'fades': len(preparation['fades']), 'selectedTracks': preparation['selectedTracks']} if preparation else None}
    engine.save(root / 'auto-report.json', report)
    result = {'mode': 'automatic', 'exportMode': 'processedWav', 'renderDirectory': root.name, 'duration': duration,
              'report': report, 'warnings': warnings, 'summary': '자동 클리닝·필요 구간 디클립 시도 · 원본 비교 · 모노 통 WAV',
              'files': ['auto-clean.wav', 'auto-original.wav', 'auto-report.json']}
    engine.save(root / 'result.json', result)
    return result
