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
            item = {'file': name, 'start': clip['start'], 'duration': clip['duration'], 'track': track['id'], 'clip': clip, 'level': measure(engine, root / name)}
            retained.append(item)
            clips.append(clip)
        if clips:
            cleaned_tracks.append({**track, 'clips': clips})
    usable = [x['level']['input_i'] for x in retained if math.isfinite(x['level']['input_i'])]
    if not usable:
        raise ValueError('선택한 대사에 측정 가능한 소리가 없어요. 무음 트랙인지 확인해 주세요.')
    reference = statistics.median(usable)
    inputs, adjustments = [], []
    for i, item in enumerate(retained):
        level = item['level']['input_i']
        gain = max(-6, min(6, reference - level)) if math.isfinite(level) else 0
        fade = min(.003, item['duration'] / 4)
        filters = ['volume=%fdB' % gain]
        if settings.get('clean', True):
            filters += ['highpass=f=65', 'afftdn=nr=6:nf=-50:tn=1']
        filters += ['afade=t=in:d=%f' % fade, 'afade=t=out:st=%f:d=%f' % (max(0, item['duration'] - fade), fade)]
        name = 'clean-%d.wav' % i
        engine.ff('-i', root / item['file'], '-af', ','.join(filters), '-ar', 48000, '-ac', 2, '-c:a', 'pcm_f32le', root / name)
        inputs.append({'file': name, 'start': item['start']})
        adjustments.append({'track': item['track'], 'start': item['start'], 'gainDb': round(gain, 2)})
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
            pieces.append({'file': name, 'start': lo})
            clips.append({'start': lo, 'duration': hi - lo})
        if pieces:
            name = 'scene-%02d-pre.wav' % (i + 1)
            engine.mix(root, pieces, name, duration, limit=False, codec='pcm_f32le')
            stems.append({'id': 'scene-%02d' % (i + 1), 'name': scene['title'], 'role': 'dialogue', 'file': name, 'gain': 0, 'clips': clips})
    engine.mix(root, [{'file': t['file']} for t in stems], 'dialogue-pre.wav', duration, limit=False, codec='pcm_f32le')
    before = measure(engine, root / 'original.wav')
    measured = measure(engine, root / 'dialogue-pre.wav')
    if not math.isfinite(measured['input_i']):
        raise ValueError('대사 보정 후 측정 가능한 소리가 없어요.')
    # A shared linear gain preserves the exact relation between the bus and scene stems.
    # Never secretly apply a different limiter to each exported track.
    peak = max([measured['input_tp']] + [measure(engine, root / t['file'])['input_tp'] for t in stems])
    gain = min(-24 - measured['input_i'], -2 - peak)
    for t in stems:
        t['export'] = t['id'] + '.wav'
        engine.ff('-i', root / t['file'], '-af', 'volume=%fdB' % gain, '-ar', 48000, '-ac', 2, '-c:a', 'pcm_s16le', root / t['export'])
        t['waveform'] = engine.waveform(root / t['export'], duration)
    engine.mix(root, [{'file': t['export']} for t in stems], 'mix.wav', duration, limit=False)
    after = measure(engine, root / 'mix.wav')
    reached = math.isfinite(after['input_i']) and abs(after['input_i'] + 24) <= .5 and after['input_tp'] <= -1.8
    report = {'targetLufs': -24, 'beforeLufs': finite(before['input_i']), 'afterLufs': finite(after['input_i']), 'truePeakDbtp': finite(after['input_tp']), 'targetReached': reached, 'duplicates': duplicates, 'removedEmptyTracks': manifest.get('emptyTracks', 0), 'removedDuplicateTracks': len(selected) - len(cleaned_tracks), 'adjustments': adjustments, 'deduplicate': settings.get('deduplicate', True), 'scenes': scenes, 'sceneTracks': len(stems), 'busGainDb': round(gain, 2)}
    warnings = ['동일 위치·길이·디코딩 PCM이 일치하는 클립만 중복 제외했어요. 다른 마이크·서로 다른 동시 대사는 유지해요.', '원래 타이밍과 겹쳐 말하는 구간을 유지해요. 클립 간 보정은 ±6dB, 원본 클립 페이드는 최대 3ms, 씬 트랙 경계 페이드는 최대 5ms예요.', '트랙 이름으로 대사를 제안해요. 음성 인식이나 마이크 자동 선택은 하지 않아요.']
    if not reached:
        warnings.append('피크를 보호하면서 씬별 트랙의 합을 유지하기 위해 보정량을 제한했어요. −24 LUFS 목표 허용 오차(±0.5 LU) 또는 피크 기준을 충족하지 못했으니 측정값을 확인해 주세요.')
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
            slot.segment.components.append(mob.create_source_clip(source_clip.slot_id))
            slot.segment.length = round(duration * 48000)
    result = {'mode': 'dialogue', 'renderDirectory': root.name, 'duration': duration, 'tracks': tracks, 'assets': [], 'report': report, 'warnings': warnings, 'summary': '대사 중복 정리와 전체 −24 LUFS 보정', 'files': ['mix.wav', 'original.wav', 'dialogue-report.json', 'SceneSound.aaf'] + [t['export'] for t in tracks]}
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
