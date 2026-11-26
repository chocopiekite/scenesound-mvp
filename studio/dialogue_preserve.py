"""Edit an original AAF copy, preserving media, SourceClips and timeline positions."""
import csv
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import statistics
import subprocess
from fractions import Fraction
from uuid import uuid4
from collections import Counter
import wave

import aaf2
from aaf2.auid import AUID
from speech import Analyzer, matching_gain

GAIN = '9d2ea894-0968-11d3-8a38-0050040ef7d2'
AMP = 'e4962321-2267-11d3-8a4c-0050040ef7d2'


def ungroup(segment):
    gain, depth = 1.0, 0
    while segment.__class__.__name__ == 'OperationGroup':
        parameters = list(segment.parameters)
        inputs = list(segment.segments)
        if (str(segment.operation.auid) != GAIN or len(inputs) != 1 or len(parameters) != 1
                or parameters[0].__class__.__name__ != 'ConstantValue' or str(parameters[0].parameterdef.auid) != AMP
                or inputs[0].length != segment.length):
            raise ValueError('고정 클립 게인 이외의 AAF 효과는 아직 원본 보존 처리할 수 없어요.')
        value = float(parameters[0].value)
        if not math.isfinite(value) or value < 0 or value > 1e6 or depth >= 20:
            raise ValueError('AAF 클립 게인 값을 확인해 주세요.')
        gain *= value
        if not math.isfinite(gain) or gain > 1e6:
            raise ValueError('AAF 누적 게인 범위를 확인해 주세요.')
        segment, depth = inputs[0], depth + 1
    return segment, gain


def resolve(segment, offset=Fraction(0), duration=None, depth=0):
    if depth > 20:
        raise ValueError('AAF 소스 참조가 너무 복잡해요.')
    segment, gain = ungroup(segment)
    if segment.__class__.__name__ == 'Sequence':
        cursor = Fraction(0)
        for child in segment.components:
            length = Fraction(child.length) / duration[1]
            if cursor <= offset and offset + duration[0] <= cursor + length:
                mob, start, inner = resolve(child, offset - cursor, duration, depth + 1)
                return mob, start, gain * inner
            cursor += length
        raise ValueError('한 클립이 여러 소스나 빈 구간을 가로지르는 AAF는 아직 지원하지 않아요.')
    if segment.__class__.__name__ != 'SourceClip' or segment.mob is None or segment.slot is None:
        raise ValueError('연결된 원본 소스가 있는 AAF 컷과 고정 게인만 지원해요.')
    slot = segment.slot
    offset += Fraction(segment.start) / Fraction(str(slot.edit_rate))
    if segment.mob.__class__.__name__ == 'SourceMob':
        if segment.mob.essence is None:
            raise ValueError('이 기능에는 원본 오디오가 내장된 AAF가 필요해요. Pro Tools에서 미디어 포함으로 내보내 주세요.')
        return segment.mob, offset, gain
    mob, start, inner = resolve(slot.segment, offset, (duration[0], Fraction(str(slot.edit_rate))), depth + 1)
    return mob, start, gain * inner


def source_path(root):
    uploads = json.loads((root / 'uploads.json').read_text())
    aafs = [u for u in uploads if u['role'] == 'aaf']
    if len(aafs) != 1 or Path(aafs[0]['file']).name != aafs[0]['file']:
        raise ValueError('원본 미디어가 포함된 AAF 하나를 선택해 주세요.')
    return root / aafs[0]['file']


def inventory(f, engine):
    comps = list(f.content.toplevel())
    if len(comps) != 1:
        raise ValueError('최상위 Composition이 하나인 AAF가 필요해요.')
    tracks, rows, empty, duration = [], [], 0, Fraction(0)
    for slot in comps[0].slots:
        if str(slot.media_kind).lower() != 'sound':
            continue
        if slot.segment.__class__.__name__ != 'Sequence' or int(slot['Origin'].value or 0):
            raise ValueError('Origin이 0인 일반 오디오 트랙 AAF를 사용해 주세요.')
        rate = Fraction(str(slot.edit_rate))
        length = Fraction(slot.segment.length) / rate
        if length > engine.MAX_DURATION:
            raise ValueError('AAF 타임라인은 %d분까지 지원해요.' % (engine.MAX_DURATION // 60))
        duration = max(duration, length)
        tid, clips, cursor, index = 't%d' % len(tracks), [], 0, 0
        for ci, component in enumerate(slot.segment.components):
            seconds = Fraction(component.length) / rate
            if component.__class__.__name__ == 'Filler':
                cursor += component.length
                continue
            leaf, top_gain = ungroup(component)
            if leaf.__class__.__name__ != 'SourceClip' or leaf.length != component.length:
                raise ValueError('클립을 재합성하지 않고 보존할 수 있는 AAF 컷만 지원해요.')
            if component.__class__.__name__ == 'OperationGroup' and list(component.segments)[0].__class__.__name__ != 'SourceClip':
                raise ValueError('여러 겹의 클립 효과는 원본 보존 처리할 수 없어요.')
            mob, start, effective_gain = resolve(component, duration=(seconds, rate))
            stream = engine.open_pcm_stream(mob.essence)
            layout = engine.pcm_layout(mob.descriptor, stream)
            stream.close()
            first, frames = round(start * layout[0]), round(seconds * layout[0])
            if first < 0 or frames < 1 or first + frames > layout[3]:
                raise ValueError('AAF의 원본 오디오 구간 범위를 확인해 주세요.')
            row = {'track': tid, 'name': str(slot.name or '오디오 %d' % slot.slot_id)[:100], 'slotId': slot.slot_id,
                   'componentIndex': ci, 'clip': index + 1, 'start': float(Fraction(cursor) / rate), 'duration': float(seconds),
                   'sourceId': str(mob.mob_id), 'sourceStart': str(start), 'first': first, 'frames': frames,
                   'layout': layout, 'sourceGain': effective_gain, 'topGain': top_gain}
            rows.append(row)
            clips.append({'start': row['start'], 'duration': row['duration'], 'componentIndex': ci})
            index += 1
            cursor += component.length
        if clips:
            tracks.append({'id': tid, 'slotId': slot.slot_id, 'name': str(slot.name or '오디오 %d' % slot.slot_id)[:100], 'role': 'original' if re.search(r'\bOMF\b|\bGUIDE\b|\bDIA\s*B\b|\bWALLA\b',str(slot.name or ''),re.I) else 'dialogue', 'clips': clips})
        else:
            empty += 1
    if not tracks or len(tracks) > engine.MAX_TRACKS or len(rows) > engine.MAX_CLIPS or sum(r['duration'] for r in rows) > engine.MAX_SECONDS:
        raise ValueError('AAF 트랙·클립 수 또는 사용 구간 합계가 처리 한도를 초과했어요.')
    return comps[0], tracks, rows, float(duration), empty


def inspect_job(root, engine):
    with aaf2.open(str(source_path(root)), 'r') as f:
        comp, tracks, rows, duration, empty = inventory(f, engine)
        result = {'name': str(comp.name or 'SceneSound')[:100], 'duration': duration, 'video': None, 'tracks': tracks,
                  'emptyTracks': empty, 'preserveAaf': True, 'warnings': ['원본 트랙·개별 클립을 유지해요. 선택하지 않은 트랙은 AAF에 그대로 남아요.']}
    engine.save(root / 'manifest.json', result)
    return result


def digest_stream(essence, engine):
    digest = hashlib.sha256()
    stream = engine.open_pcm_stream(essence)
    while True:
        block = stream.read(4 * 1024 * 1024)
        if not block:
            break
        digest.update(block)
    stream.close()
    return digest.hexdigest()


def snapshot(comp):
    result = []
    for slot in comp.slots:
        if str(slot.media_kind).lower() != 'sound':
            # The original copy leaves non-audio content untouched.
            result.append({'id': slot.slot_id, 'name': slot.name, 'kind': str(slot.media_kind), 'length': slot.length})
            continue
        components = []
        for c in slot.segment.components:
            leaf, _ = ungroup(c)
            data = {'kind': leaf.__class__.__name__, 'length': leaf.length}
            if leaf.__class__.__name__ == 'SourceClip':
                data.update(start=leaf.start, source=str(leaf.mob_id), slot=leaf.slot_id)
            components.append(data)
        result.append({'id': slot.slot_id, 'name': slot.name, 'kind': str(slot.media_kind), 'rate': str(slot.edit_rate),
                       'origin': slot['Origin'].value, 'length': slot.length, 'components': components})
    return result


def extract(mob, row, path, engine, context=False):
    rate, channels, width, available, data_offset = row['layout']
    first, frames = row['first'], row['frames']
    lead = min(first, round(.32 * rate)) if context else 0
    count = min(available - first + lead, frames + lead + (round(.32 * rate) if context else 0))
    stream = engine.open_pcm_stream(mob.essence)
    stream.seek(data_offset + (first - lead) * channels * width)
    remaining, digest, silent = count * channels * width, hashlib.sha256(), True
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
        while remaining:
            block = stream.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError('AAF에 내장된 원본 오디오가 잘렸어요.')
            wav.writeframesraw(block)
            digest.update(block)
            silent = silent and not any(block)
            remaining -= len(block)
    stream.close()
    return digest.hexdigest(), silent, lead / rate


def render_dialogue(source, engine):
    from dialogue import clip_gain, measure
    root = source / ('render-' + uuid4().hex)
    root.mkdir(mode=0o700)
    settings = json.loads((source / 'settings.json').read_text())
    original = source_path(source)
    output = root / 'dialogue-clips.aaf'
    def progress(stage):
        engine.save(source / 'progress.json', {'stage': stage})
    progress('원본 AAF 구조와 내장 미디어를 확인하고 있어요.')
    analyzer = Analyzer()
    duplicates, silences, adjustments, seen, cache, dry, wet, removed = [], [], [], {}, {}, [], [], set()
    with aaf2.open(str(original), 'r') as f:
        comp, tracks, rows, duration, empty = inventory(f, engine)
        before = snapshot(comp)
        # Guard expected copy/metadata allocation before a sparse file can jump
        # beyond the free public worker's actual temporary volume budget.
        budget = int(os.environ.get('STUDIO_STORAGE_BUDGET_BYTES', 0))
        if budget:
            used = sum(p.stat().st_size for p in source.parent.rglob('*') if p.is_file())
            allocation = max(original.stat().st_size, len(f.cfb.fat) * f.cfb.sector_size)
            if used + allocation + duration * 48000 * 8 > budget - 64 * 1024 ** 2:
                raise ValueError('원본 AAF 사본과 비교 음원을 만들 임시 공간이 부족해요. 이 파일은 로컬 대사 도구에서 처리해 주세요.')
        source_mobs = {str(m.mob_id): m for m in f.content.sourcemobs()}
        # All embedded streams, including unused handles, remain byte-identical.
        media_hashes = {str(e.mob_id): digest_stream(e, engine) for e in f.content.essencedata}
        selected = [r for r in rows if settings['roles'].get(r['track']) == 'dialogue']
        if not selected:
            raise ValueError('처리할 대사 트랙을 하나 이상 선택해 주세요.')
        for i, row in enumerate(selected):
            progress('대사·배경 소리를 구분하고 있어요 · %d/%d' % (i + 1, len(selected)))
            mob = source_mobs[row['sourceId']]
            path, context = root / 'used.wav', root / 'context.wav'
            pcm_hash, silent, _ = extract(mob, row, path, engine)
            key = (Fraction(str(row['start'])), Fraction(str(row['duration'])), pcm_hash, tuple(row['layout'][:3]), row['sourceGain'])
            record = {'track': row['name'], 'clip': row['clip'], 'start': row['start'], 'duration': row['duration']}
            # Silence removal and duplicate removal have separate switches.
            if settings.get('removeSilence', True) and silent:
                silences.append(record)
                removed.add((row['slotId'], row['componentIndex']))
                continue
            if settings.get('deduplicate', True) and key in seen:
                duplicates.append({**record, 'keptTrack': seen[key]})
                removed.add((row['slotId'], row['componentIndex']))
                continue
            seen[key] = row['name']
            _, _, lead = extract(mob, row, context, engine, context=True)
            cache_key = (pcm_hash, digest_file(context), row['sourceGain'])
            if cache_key not in cache:
                info = analyzer.classify(context, row['duration'], lead, row['sourceGain'])
                gain, limited = 0.0, False
                level = {'lufs': None, 'metric': None, 'truePeakDbtp': None}
                if info['category'] == 'speech':
                    level = analyzer.levels(path, info['speech'], row['sourceGain'], engine)
                    lufs, peak = level['lufs'], level['truePeakDbtp']
                    if lufs is not None and peak is not None:
                        gain = clip_gain(lufs, peak)
                    elif peak is not None:
                        gain = -12.5 - peak
                    # Constant clip gain cannot reduce a loud non-speech event
                    # separately. Protect that clip and report the conflict.
                    total_peak = measure(engine, path)['input_tp']
                    if row['sourceGain'] > 0 and math.isfinite(total_peak):
                        total_peak += 20 * math.log10(row['sourceGain'])
                        if total_peak + gain > -1:
                            gain, limited = -1 - total_peak, True
                    if row['topGain'] > 0:
                        gain = max(-144 - 20 * math.log10(row['topGain']), min(36 - 20 * math.log10(row['topGain']), gain))
                cache[cache_key] = {**info, 'before': level, 'finalGainDb': gain, 'speechSafetyLimited': limited}
            item = {**row, **cache[cache_key]}
            item['method'] = 'speechWindows' if item['category'] == 'speech' else 'preserveUncertain' if item['category'] == 'review' else 'noiseHoldNoReference'
            adjustments.append(item)
        path.unlink(missing_ok=True)
        context.unlink(missing_ok=True)
        scenes = settings.get('scenes') or [{'start': 0, 'title': '전체'}]
        def scene(row):
            return sum(row['start'] >= s['start'] for s in scenes) - 1
        for row in adjustments:
            if row['category'] != 'noise':
                continue
            start, end = row['start'], row['start'] + row['duration']
            candidates = [x for x in adjustments if x['slotId'] == row['slotId'] and scene(x) == scene(row) and x['category'] == 'speech']
            # A duplicate anchor may have moved to a different original track.
            # Use only retained, actually audible references.
            previous = [x for x in candidates if 0 <= start - x['start'] - x['duration'] <= 5.001]
            following = [x for x in candidates if 0 <= x['start'] - end <= 5.001]
            references = []
            for side, group in [('before', previous), ('after', following)]:
                if not group:
                    continue
                ref = max(group, key=lambda x: x['start']) if side == 'before' else min(group, key=lambda x: x['start'])
                floor = ref['noiseTailDbfs'] if side == 'before' else ref['noiseHeadDbfs']
                if floor is not None:
                    references.append(floor + ref['finalGainDb'])
            gain, method, target, limited = matching_gain(row['noiseFloorDbfs'], references)
            row.update(finalGainDb=gain, method=method, noiseTargetDbfs=target, noiseMatchLimited=limited)
        progress('원본 클립의 위치를 유지하며 게인 정보와 비교 음원을 만들고 있어요.')
        for row in adjustments:
            row['after'] = {'lufs': row['before']['lufs'] + row['finalGainDb'] if row['before']['lufs'] is not None else None,
                            'truePeakDbtp': row['before']['truePeakDbtp'] + row['finalGainDb'] if row['before']['truePeakDbtp'] is not None else None,
                            'metric': row['before']['metric']}
        # Preview PCM is separate from original media in the AAF. Never feed a
        # denoised or resampled preview back into the AAF exporter.
        by_position = {(r['slotId'], r['componentIndex']): r for r in adjustments}
        for i, row in enumerate(selected):
            path = root / 'used.wav'
            extract(source_mobs[row['sourceId']], row, path, engine)
            name = 'dry-%d.wav' % i
            engine.ff('-i', path, '-ar', 48000, '-ac', 2, '-c:a', 'pcm_s16le', root / name)
            base_gain = 20 * math.log10(row['sourceGain']) if row['sourceGain'] > 0 else -144
            dry.append({'file': name, 'start': row['start'], 'gain': base_gain})
            item = by_position.get((row['slotId'], row['componentIndex']))
            if item:
                wet.append({'file': name, 'start': row['start'], 'gain': base_gain + item['finalGainDb']})
        path.unlink(missing_ok=True)
        engine.mix(root, dry, 'original.wav', duration, limit=False)
        engine.mix(root, wet, 'mix.wav', duration, limit=False)
    # Clone on APFS; bounded stream copy elsewhere. The input is never opened rw.
    if sys_platform() == 'darwin':
        subprocess.run(['/bin/cp', '-c', str(original), str(output)], check=True)
    else:
        shutil.copyfile(original, output)
    progress('완전 중복·완전 무음을 정리하고 클립 게인만 기록하고 있어요.')
    expected = json.loads(json.dumps(before))
    empty_slots = set()
    for slot in expected:
        if slot['kind'].lower() != 'sound':
            continue
        for i, component in enumerate(slot['components']):
            if (slot['id'], i) in removed:
                slot['components'][i] = {'kind': 'Filler', 'length': component['length']}
        if not any(c['kind'] != 'Filler' for c in slot['components']):
            empty_slots.add(slot['id'])
    expected = [s for s in expected if s['id'] not in empty_slots]
    with aaf2.open(str(output), 'rw') as f:
        comp = next(f.content.toplevel())
        slots = {s.slot_id: s for s in comp.slots}
        try:
            op = f.dictionary.lookup_operationdef(AUID(GAIN))
            if op is None:
                raise LookupError('missing gain definition')
        except Exception:
            op = f.create.OperationDef(GAIN, 'Audio Gain')
            op.media_kind = 'sound'
            op['IsTimeWarp'].value = False
            op['NumberInputs'].value = 1
            op['OperationCategory'].value = 'OperationCategory_Effect'
            f.dictionary.register_def(op)
        try:
            param = f.dictionary.lookup_parameterdef(AUID(AMP))
            if param is None:
                raise LookupError('missing amplitude definition')
        except Exception:
            param = f.create.ParameterDef(AMP, 'Amplitude', typedef='Rational')
            f.dictionary.register_def(param)
        if not any(p.auid == param.auid for p in op.parameters):
            op.parameters.append(param)
        for row in selected:
            seq = slots[row['slotId']].segment
            component = seq.components[row['componentIndex']]
            if (row['slotId'], row['componentIndex']) in removed:
                seq.components[row['componentIndex']] = f.create.Filler(media_kind='sound', length=component.length)
                continue
            item = by_position[row['slotId'], row['componentIndex']]
            amplitude = row['topGain'] * 10 ** (item['finalGainDb'] / 20)
            rational = Fraction(amplitude).limit_denominator(max(1, min(1000000, int(2000000000 / max(1, amplitude)))))
            item['exportAmplitude'] = str(rational)
            if component.__class__.__name__ == 'OperationGroup':
                list(component.parameters)[0].value = str(rational)
            else:
                group = f.create.OperationGroup(op, length=component.length, media_kind='sound')
                group.segments.append(component.copy())
                group.parameters.append(f.create.ConstantValue(param, str(rational)))
                seq.components[row['componentIndex']] = group
        for i in range(len(comp.slots) - 1, -1, -1):
            if comp.slots[i].slot_id in empty_slots:
                comp.slots.pop(i)
    progress('원본 미디어와 남은 클립의 위치·게인을 다시 확인하고 있어요.')
    with aaf2.open(str(output), 'r') as f:
        comp = next(f.content.toplevel())
        if snapshot(comp) != expected:
            raise ValueError('원본 클립 배치 검증에 실패해 AAF를 제공하지 않았어요.')
        if {str(e.mob_id): digest_stream(e, engine) for e in f.content.essencedata} != media_hashes:
            raise ValueError('원본 미디어 일치 검증에 실패해 AAF를 제공하지 않았어요.')
        slots = {s.slot_id: s for s in comp.slots}
        for row in adjustments:
            _, value = ungroup(slots[row['slotId']].segment.components[row['componentIndex']])
            if abs(value - float(Fraction(row['exportAmplitude']))) > 1e-9:
                raise ValueError('클립 게인 저장 검증에 실패했어요.')
    for entry in root.glob('dry-*.wav'):
        entry.unlink()
    before_levels = [r['before']['lufs'] for r in adjustments if r['category'] == 'speech' and r['before']['lufs'] is not None]
    after_levels = [r['after']['lufs'] for r in adjustments if r['category'] == 'speech' and r['after']['lufs'] is not None]
    for r in adjustments:
        peak = r['after']['truePeakDbtp']
        r['peakReached'] = peak is not None and -15.15 <= peak <= -9.85
        r['loudnessReached'] = r['after']['lufs'] is not None and abs(r['after']['lufs'] + 24) <= .5
        r['targetReached'] = r['category'] == 'speech' and r['peakReached'] and r['loudnessReached']
        r['needsReview'] = (r['category'] == 'review' or r.get('speechSafetyLimited', False) or r.get('noiseMatchLimited', False)
                            or 'Hold' in r['method'] or (r['category'] == 'speech' and not r['targetReached']))
    report = {'normalizationMode': 'preservedClipGainV1', 'exportMode': 'preservedClipGain', 'targetLufs': -24, 'peakRangeDbtp': [-15, -10],
              'duplicates': duplicates, 'silences': silences, 'removedEmptyTracks': len(empty_slots), 'removedDuplicateTracks': 0,
              'originalClips': len(rows), 'retainedClips': len(rows) - len(removed), 'processedClips': len(adjustments),
              'categories': dict(Counter(r['category'] for r in adjustments)), 'noiseMatched': sum(r['method'] == 'noiseFloorMatch' for r in adjustments),
              'needsReview': sum(r['needsReview'] for r in adjustments), 'adjustments': adjustments, 'scenes': scenes,
              'clipBeforeLufs': statistics.median(before_levels) if before_levels else None,
              'clipAfterLufs': statistics.median(after_levels) if after_levels else None,
              'targetReached': all(not r['needsReview'] for r in adjustments), 'mediaStreamsVerified': len(media_hashes),
              'sourcePreserved': True, 'clipPositionsVerified': True, 'sceneRegrouping': False}
    engine.save(root / 'dialogue-report.json', report)
    with (root / 'dialogue-review.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['트랙', '클립', '시작 초', '구분', '게인 dB', '방식', '확인 필요'])
        for r in adjustments:
            writer.writerow([r['name'], r['clip'], r['start'], {'speech': '대사 후보', 'noise': '배경 노이즈 후보', 'review': '확인 필요'}[r['category']], round(r['finalGainDb'], 3), r['method'], r['needsReview']])
    result_tracks = []
    for track in tracks:
        if track['slotId'] in empty_slots:
            continue
        result_tracks.append({**track, 'role': 'dialogue' if settings['roles'].get(track['id']) == 'dialogue' else 'original',
                              'clips': [c for c in track['clips'] if (track['slotId'], c['componentIndex']) not in removed]})
    warnings = ['AAF는 원본 미디어·개별 클립·소스·위치를 유지하고 클립 게인 정보만 바꿔요. 원본 업로드 파일은 수정하지 않아요.',
                '완전 중복은 같은 위치·길이·원본 PCM·게인이 같은 경우만 제외하고, 완전 무음은 모든 샘플이 0인 경우만 제외해요.',
                '대사·배경 구분은 로컬 모델의 제안이에요. 속삭임·숨소리·웃음·음악 등은 청취로 확인해 주세요.',
                '노이즈는 같은 트랙의 가까운 배경 RMS를 참고해 −12~+3dB 범위에서 맞춰요. 기준이 없거나 서로 다르면 원래 게인을 유지해요.',
                '대사 구간 피크를 우선하며 클립 게인은 일정해요. 큰 잡음과 대사가 섞이면 안전 제한으로 목표에 못 미칠 수 있어요.',
                'Pro Tools에서 Import Clip Gain을 켜세요. WAV는 비교 미리 듣기용이며 AAF의 원본 오디오를 대체하지 않아요.',
                '씬별 트랙 재배치는 하지 않아요. 원본 트랙 배치를 유지해요.']
    result = {'mode': 'dialogue', 'exportMode': 'preservedClipGain', 'renderDirectory': root.name, 'duration': duration,
              'tracks': result_tracks, 'assets': [], 'roles': settings['roles'], 'report': report, 'warnings': warnings,
              'summary': '원본 클립 보존 · 중복·완전 무음 정리 · 음성/배경별 클립 게인',
              'files': ['dialogue-clips.aaf', 'dialogue-review.csv', 'dialogue-report.json']}
    for src, dst in [('mix.wav', 'dialogue-approved.wav'), ('original.wav', 'dialogue-original.wav')]:
        (root / src).replace(source / dst)
    engine.save(root / 'result.json', result)
    engine.save(source / 'dialogue-approved.json', result)
    return result


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def sys_platform():
    import sys
    return sys.platform
