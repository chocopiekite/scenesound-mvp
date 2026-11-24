"""Dialogue-only pass. Exact PCM duplicates at identical sample positions only.
Original AAF and uploaded audio are immutable; every pass creates a new render.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import wave
import zipfile
from uuid import uuid4


def measure(engine, path):
    text = engine.ff('-i', path, '-af', 'loudnorm=I=-24:TP=-2:LRA=50:print_format=json', '-f', 'null', '-')
    matches = re.findall(r'\{\s*"input_i".*?\}', text, re.S)
    if not matches:
        raise ValueError('대사 라우드니스를 측정하지 못했어요.')
    data = json.loads(matches[-1])
    return {key: float(data[key]) for key in ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']}


def finite(value):
    return value if math.isfinite(value) else None


def clip_level(engine, path, duration):
    """Median valid 3 s S windows; short clips explicitly use 400 ms M.
    EBU metadata timestamps mark the beginning of each 100 ms frame.
    Exclude the warm-up window and silence, not the original file's timing.
    """
    text = engine.ff('-i', path, '-af', 'ebur128=metadata=1:peak=true,ametadata=mode=print', '-f', 'null', '-')
    metric, window = ('S', 3.0) if duration >= 3 else ('M', .4)
    values, timestamp = [], -1
    for line in text.splitlines():
        t = re.search(r'pts_time:([0-9.]+)', line)
        if t:
            timestamp = float(t.group(1))
        m = re.search(r'lavfi\.r128\.' + metric + r'=(-?[0-9.]+)', line)
        if m and timestamp + .1001 >= window:
            value = float(m.group(1))
            if math.isfinite(value) and value > -70:
                values.append(value)
    # Do not let long quiet gaps determine the gain or amplify digital silence.
    active = [v for v in values if v >= max(values) - 10] if values else []
    return {'lufs': statistics.median(active) if active else None,
            'metric': 'shortTerm' if metric == 'S' else 'momentary',
            'windowSeconds': window, 'samples': len(active),
            'truePeakDbtp': finite(measure(engine, path)['input_tp'])}


def clip_gain(level, peak):
    if level is None or peak is None:
        return 0.0
    # Constant gain preserves performance dynamics. Peak range wins on conflict.
    return max(-15 - peak, min(-10 - peak, -24 - level))


def render_dialogue(source, engine):
    manifest = json.loads((source / 'manifest.json').read_text())
    settings = json.loads((source / 'settings.json').read_text())
    root = source / ('render-' + uuid4().hex)
    root.mkdir(mode=0o700)
    duration = manifest['duration']
    selected = [t for t in manifest['tracks'] if settings['roles'].get(t['id']) == 'dialogue']
    if not selected:
        raise ValueError('대사 트랙을 하나 이상 선택해 주세요.')
    seen, duplicates, original, retained = {}, [], [], []
    cleaned_tracks = []
    for track in selected:
        clips = []
        for i, clip in enumerate(track['clips']):
            name = '%s-%d-raw.wav' % (track['id'], i)
            engine.ff('-ss', clip['sourceStart'], '-i', source / clip['file'], '-t', clip['duration'], '-vn', '-ar', 48000, '-ac', 2, '-c:a', 'pcm_s16le', root / name)
            original.append({'file': name, 'start': clip['start']})
            with wave.open(str(root / name), 'rb') as w:
                digest = hashlib.sha256(w.readframes(w.getnframes())).hexdigest()
            key = (round(clip['start'] * 48000), round(clip['duration'] * 48000), digest)
            if settings.get('deduplicate', True) and key in seen:
                duplicates.append({'track': track['name'], 'clip': i + 1, 'start': clip['start'], 'duration': clip['duration'], 'keptTrack': seen[key]})
                continue
            seen[key] = track['name']
            item = {'file': name, 'start': clip['start'], 'duration': clip['duration'], 'track': track['id'], 'clip': clip}
            retained.append(item)
            clips.append(clip)
        if clips:
            cleaned_tracks.append({**track, 'clips': clips})
    adjustments = []
    for i, item in enumerate(retained):
        fade = min(.003, item['duration'] / 4)
        filters = []
        if settings.get('clean', True):
            filters += ['highpass=f=65', 'afftdn=nr=6:nf=-50:tn=1']
        filters += ['afade=t=in:d=%f' % fade, 'afade=t=out:st=%f:d=%f' % (max(0, item['duration'] - fade), fade)]
        prepared = root / ('prepared-%d.wav' % i)
        engine.ff('-i', root / item['file'], '-af', ','.join(filters), '-ar', 48000, '-ac', 2, '-c:a', 'pcm_f32le', prepared)
        before_clip = clip_level(engine, prepared, item['duration'])
        gain = clip_gain(before_clip['lufs'], before_clip['truePeakDbtp'])
        name = 'clean-%d.wav' % i
        engine.ff('-i', prepared, '-af', 'volume=%fdB' % gain, '-ar', 48000, '-ac', 2, '-c:a', 'pcm_f32le', root / name)
        after_clip = clip_level(engine, root / name, item['duration'])
        adjustments.append({'track': item['track'], 'clip': item['clip'], 'start': item['start'], 'duration': item['duration'],
                            'gainDb': round(gain, 3), 'before': before_clip, 'after': after_clip})
        prepared.unlink()
    if not any(a['before']['lufs'] is not None for a in adjustments):
        raise ValueError('선택한 대사에 측정 가능한 소리가 없어요. 무음 또는 0.4초보다 짧은 클립인지 확인해 주세요.')
    engine.mix(root, original, 'original.wav', duration)
    scenes = settings.get('scenes') or [{'start': 0, 'title': '씬 1'}]
    stems = []
    for i, scene in enumerate(scenes):
        start, end = scene['start'], scenes[i + 1]['start'] if i + 1 < len(scenes) else duration
        pieces, clips = [], []
        for index, item in enumerate(retained):
            lo, hi = max(start, item['start']), min(end, item['start'] + item['duration'])
            if hi <= lo:
                continue
            name = 'scene-%d-part-%d.wav' % (i, index)
            fade = min(.005, (hi - lo) / 4)
            engine.ff('-ss', lo - item['start'], '-i', root / ('clean-%d.wav' % index), '-t', hi - lo,
                      '-af', 'afade=t=in:d=%f,afade=t=out:st=%f:d=%f' % (fade, hi - lo - fade, fade),
                      '-ar', 48000, '-ac', 2, '-c:a', 'pcm_f32le', root / name)
            pieces.append({'file': name, 'start': lo - start})
            clips.append({'start': lo, 'duration': hi - lo})
        if pieces:
            name = 'scene-%02d-pre.wav' % (i + 1)
            engine.mix(root, pieces, name, end - start, limit=False, codec='pcm_f32le')
            stems.append({'id': 'scene-%02d' % (i + 1), 'name': scene['title'], 'role': 'dialogue', 'file': name, 'gain': 0, 'start': start, 'duration': end - start, 'clips': clips})
    engine.mix(root, [{'file': t['file'], 'start': t['start']} for t in stems], 'dialogue-pre.wav', duration, limit=False, codec='pcm_f32le')
    before = measure(engine, root / 'original.wav')
    measured = measure(engine, root / 'dialogue-pre.wav')
    if not math.isfinite(measured['input_i']):
        raise ValueError('대사 보정 후 측정 가능한 소리가 없어요.')
    # No integrated-loudness normalization after clip gains. Only protect the
    # summed mix against clipping when many different recordings overlap.
    peak = max([measured['input_tp']] + [measure(engine, root / t['file'])['input_tp'] for t in stems])
    gain = min(0, -1 - peak)
    for t in stems:
        t['export'] = t['id'] + '.wav'
        engine.ff('-i', root / t['file'], '-af', 'volume=%fdB' % gain, '-ar', 48000, '-ac', 2, '-c:a', 'pcm_s16le', root / t['export'])
        t['waveform'] = engine.waveform(root / t['export'], t['duration'])
    engine.mix(root, [{'file': t['export'], 'start': t['start']} for t in stems], 'mix.wav', duration, limit=False)
    after = measure(engine, root / 'mix.wav')
    for a in adjustments:
        # Shared safety attenuation applies equally to scene WAV, AAF and mix.
        a['after']['lufs'] = a['after']['lufs'] + gain if a['after']['lufs'] is not None else None
        a['after']['truePeakDbtp'] = a['after']['truePeakDbtp'] + gain if a['after']['truePeakDbtp'] is not None else None
        a['finalGainDb'] = round(a['gainDb'] + gain, 3)
        a['loudnessReached'] = a['after']['lufs'] is not None and abs(a['after']['lufs'] + 24) <= .5
        a['peakReached'] = a['after']['truePeakDbtp'] is not None and -15.15 <= a['after']['truePeakDbtp'] <= -9.85
        a['targetReached'] = a['loudnessReached'] and a['peakReached']
    reached = all(a['targetReached'] for a in adjustments)
    report = {'normalizationMode': 'clipStaticShortTerm', 'targetLufs': -24, 'peakRangeDbtp': [-15, -10],
              'representative': 'median of valid 3s windows; silence below -70 LUFS and windows >10 LU below maximum excluded',
              'beforeLufs': finite(before['input_i']), 'afterLufs': finite(after['input_i']),
              'truePeakDbtp': finite(after['input_tp']), 'targetReached': reached,
              'clipBeforeLufs': statistics.median([a['before']['lufs'] for a in adjustments if a['before']['lufs'] is not None]),
              'clipAfterLufs': statistics.median([a['after']['lufs'] for a in adjustments if a['after']['lufs'] is not None]),
              'shortClipCount': sum(a['before']['metric'] == 'momentary' for a in adjustments),
              'needsReview': sum(not a['targetReached'] for a in adjustments),
              'duplicates': duplicates, 'removedEmptyTracks': manifest.get('emptyTracks', 0),
              'removedDuplicateTracks': len(selected) - len(cleaned_tracks), 'adjustments': adjustments,
              'deduplicate': settings.get('deduplicate', True), 'scenes': scenes, 'sceneTracks': len(stems), 'busGainDb': round(gain, 3)}
    warnings = ['동일 위치·길이·디코딩 PCM이 일치하는 클립만 중복 제외해요. 다른 마이크·동시 대사는 유지해요.',
                '클립별 대표 숏텀(3초 유효 구간 중앙값)을 −24 LUFS로 조절해요. 클립 내 게인은 일정하며 컴프레서·리미터를 적용하지 않아요.',
                '트루피크 −15~−10 dBTP 범위를 우선해요. 정적 게인으로 두 기준이 충돌하면 LUFS가 목표에서 벗어날 수 있어요.',
                '3초 미만은 모멘터리(400ms) 대표값으로 보완해 별도 표시해요. 400ms 미만·무음은 측정 불가로 남겨요.',
                '클립 페이드는 최대 3ms, 씬 경계 페이드는 최대 5ms예요. 경계와 겹친 대사는 실제 출력에서 다시 확인해 주세요.',
                '트랙 이름으로 대사를 제안하며 음성 인식이나 마이크 자동 선택은 하지 않아요.']
    if gain < 0:
        warnings.append('겹친 대사의 합산 피크가 커서 출력 전체에 %.2f dB 감쇠를 적용했어요. 클립 목표도 다시 확인해 주세요.' % gain)
    if not reached:
        warnings.append('두 목표를 동시에 충족하지 못했거나 측정할 수 없는 클립 %d개가 있어요. 클립별 측정 내역을 확인해 주세요.' % report['needsReview'])
    engine.save(root / 'dialogue-report.json', report)
    engine.save(root / 'manifest.json', manifest)
    tracks = stems
    import aaf2
    with aaf2.open(str(root / 'SceneSound.aaf'), 'w') as f:
        comp = f.create.CompositionMob('SceneSound dialogue scenes')
        comp.usage = 'Usage_TopLevel'
        f.content.mobs.append(comp)
        for t in tracks:
            mob = f.create.MasterMob(t['name'])
            f.content.mobs.append(mob)
            source_clip = mob.import_audio_essence(str(root / t['export']), edit_rate=48000)
            slot = comp.create_sound_slot(48000)
            slot.name = t['name']
            begin = round(t['start'] * 48000)
            if begin:
                slot.segment.components.append(f.create.Filler(media_kind='sound', length=begin))
            clip = mob.create_source_clip(source_clip.slot_id)
            slot.segment.components.append(clip)
            end = round(duration * 48000) - begin - clip.length
            if end > 0:
                slot.segment.components.append(f.create.Filler(media_kind='sound', length=end))
            slot.segment.length = round(duration * 48000)
    result = {'mode': 'dialogue', 'renderDirectory': root.name, 'duration': duration, 'tracks': tracks, 'assets': [], 'report': report, 'warnings': warnings, 'summary': '대사 중복 정리 · 클립별 숏텀 −24 LUFS 및 트루피크 −15~−10 dBTP 보정', 'files': ['mix.wav', 'original.wav', 'dialogue-report.json', 'SceneSound.aaf'] + [t['export'] for t in tracks]}
    engine.save(root / 'result.json', result)
    with zipfile.ZipFile(root / 'SceneSound.zip', 'w', zipfile.ZIP_STORED) as z:
        for name in result['files']:
            z.write(root / name, name)
    # Stable hand-off copy; effects passes do not overwrite these source files.
    for filename, destination in [('mix.wav', 'dialogue-approved.wav'), ('original.wav', 'dialogue-original.wav'), ('SceneSound.aaf', 'dialogue-scenes.aaf'), ('SceneSound.zip', 'dialogue-package.zip')]:
        temp = source / (destination + '.tmp')
        shutil.copyfile(root / filename, temp)
        temp.replace(source / destination)
    engine.save(source / 'dialogue-approved.json', {**result, 'roles': settings['roles']})
    return result
