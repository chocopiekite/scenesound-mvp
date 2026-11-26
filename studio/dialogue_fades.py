"""Bounded native AAF fades. Original media is immutable; only handles extend."""
from fractions import Fraction
import math
import numpy as np
from aaf2.auid import AUID
from dialogue_reference import key, scene_index

DISSOLVE = '0c3bea41-fc05-11d2-8a29-0050040ef7d2'
LEVEL = 'e4962320-2267-11d3-8a4c-0050040ef7d2'
LINEAR = '5b6c85a4-0ede-11d3-80a9-006008143e6f'
POWER = 'c09153f7-bd18-4e5a-ad09-cbdd654fa001'


def pcm(f, row, start, end, engine):
    rate, channels, width, available, offset = row['layout']
    first = row['first'] + round((start - row['start']) * rate)
    frames = round((end - start) * rate)
    if first < 0 or first + frames > available or frames < 1:
        raise ValueError('페이드 원본 핸들 범위를 확인해 주세요.')
    mob = next(m for m in f.content.sourcemobs() if str(m.mob_id) == row['sourceId'])
    stream = engine.open_pcm_stream(mob.essence)
    stream.seek(offset + first * channels * width)
    data = stream.read(frames * channels * width)
    stream.close()
    if len(data) != frames * channels * width:
        raise ValueError('페이드 원본 오디오가 잘렸어요.')
    return data


def clean(data, width, strict):
    if width == 3:
        b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        x = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
        x = ((x ^ 0x800000) - 0x800000).astype(np.float64) / 8388608
    else:
        x = np.frombuffer(data, dtype='<i%d' % width).astype(np.float64) / 2 ** (width * 8 - 1)
    chunks = np.array_split(x, max(1, min(16, len(x) // 512)))
    rms = np.array([max(float(np.sqrt(np.mean(a * a))), 1e-12) for a in chunks])
    span = float(np.ptp(20 * np.log10(rms)))
    floor = float(np.sqrt(np.mean(x * x)))
    crest = 20 * math.log10(max(float(np.max(np.abs(x))), 1e-12) / max(floor, 1e-12))
    if floor < 1e-9 or span > (6 if strict else 12) or crest > (18 if strict else 20):
        return False
    if strict:
        spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2 + 1e-20
        if float(np.exp(np.mean(np.log(spectrum))) / np.mean(spectrum)) < .003:
            return False
    return True


def plan(f, rows, scenes, engine, enabled=True):
    plans, skipped = [], []
    if not enabled:
        return plans, skipped
    slots = {}
    for row in rows:
        slots.setdefault(row['slotId'], []).append(row)
    for group in slots.values():
        group.sort(key=lambda r: r['timelineTicks'])
        last_end = -1
        for left, right in zip(group, group[1:]):
            record = {'left': key(left), 'right': key(right), 'start': right['start']}
            rate = Fraction(left['editRate'])
            cut = right['timelineTicks']
            if (left['timelineTicks'] + left['lengthTicks'] != cut or left['componentIndex'] + 1 != right['componentIndex']
                    or left['editRate'] != right['editRate'] or left['topRate'] != left['editRate'] or right['topRate'] != right['editRate']
                    or tuple(left['layout'][:3]) != tuple(right['layout'][:3]) or left['layout'][1] != 1
                    or not left.get('referenceKey') or left.get('referenceKey') != right.get('referenceKey')
                    or left['method'] not in ['referenceSpeech', 'referenceRoomtone', 'roomtoneDifferent'] or right['method'] not in ['referenceSpeech', 'referenceRoomtone', 'roomtoneDifferent']):
                continue
            si = scene_index(left, scenes)
            scene_end = scenes[si + 1]['start'] if si + 1 < len(scenes) else float('inf')
            if scene_index(right, scenes) != si or right['start'] + right['duration'] > scene_end + 1e-6:
                continue
            lo = max(cut - math.floor(.6 * rate), left['timelineTicks'] + math.ceil(.1 * rate),
                     cut - math.floor(right.get('contextLead', 0) * rate), last_end)
            hi = min(cut + math.floor(.6 * rate), cut + right['lengthTicks'] - math.ceil(.1 * rate),
                     cut + math.floor(left.get('contextTail', 0) * rate))
            protected = [(r['start'] + a, r['start'] + b) for r in [left, right] for a, b in r.get('protectedContext', [[0, r['duration']]])]
            unsafe = False
            for a, b in protected:
                a, b = math.floor(a * rate), math.ceil(b * rate)
                if a <= cut <= b:
                    unsafe = True
                    break
                if b <= cut:
                    lo = max(lo, b + math.ceil(.01 * rate))
                elif a >= cut:
                    hi = min(hi, a - math.ceil(.01 * rate))
            if unsafe or not lo < cut < hi or hi - lo < math.ceil(.04 * rate):
                skipped.append({**record, 'reason': '대사·숨·불확실 구간을 보호할 페이드 여유가 부족해요.'})
                continue
            start, end = float(Fraction(lo) / rate), float(Fraction(hi) / rate)
            a, b = pcm(f, left, start, end, engine), pcm(f, right, start, end, engine)
            same = a == b
            if not clean(a, left['layout'][2], not same) or not clean(b, right['layout'][2], not same):
                skipped.append({**record, 'reason': '액팅·불안정한 배경일 수 있어 자동 핸들 확장을 보류했어요.'})
                continue
            plans.append({**record, 'slotId': left['slotId'], 'tick': lo, 'lengthTicks': hi - lo, 'cutPoint': cut - lo,
                          'duration': end - start, 'start': start, 'end': end,
                          'curve': 'equalGain' if same else 'equalPower', 'samePcm': same, 'needsReview': not same})
            last_end = hi
    return plans, skipped


def definitions(f):
    op = f.dictionary.lookup_operationdef(AUID(DISSOLVE))
    if op is None:
        op = f.create.OperationDef(DISSOLVE, 'Mono Audio Dissolve')
        op.media_kind = 'sound'; op['NumberInputs'].value = 2; op['IsTimeWarp'].value = False
        f.dictionary.register_def(op)
    param = f.dictionary.lookup_parameterdef(AUID(LEVEL))
    if param is None:
        param = f.create.ParameterDef(LEVEL, 'Level', typedef='Rational')
        f.dictionary.register_def(param)
    if not any(p.auid == param.auid for p in op.parameters):
        op.parameters.append(param)
    for uid, name in [(LINEAR, 'Linear'), (POWER, 'Power')]:
        if f.dictionary.lookup_interperlationdef(AUID(uid)) is None:
            f.dictionary.register_def(f.create.InterpolationDef(uid, name))
    return op, param


def apply(f, rows, plans):
    from dialogue_preserve import ungroup
    if not plans:
        return
    op, param = definitions(f)
    comp = next(f.content.toplevel())
    lookup = {(r['slotId'], r['componentIndex']): r for r in rows}
    incoming = {p['right']: p for p in plans}; outgoing = {p['left']: p for p in plans}
    for slot in comp.slots:
        if slot.slot_id not in {p['slotId'] for p in plans}:
            continue
        old = slot.segment
        seq = f.create.Sequence(media_kind='sound', length=old.length)
        for ci, c in enumerate(old.components):
            row = lookup.get((slot.slot_id, ci))
            item = c.copy()
            if row is not None:
                inc, out = incoming.get(key(row)), outgoing.get(key(row))
                lo = inc['tick'] if inc else row['timelineTicks']
                hi = out['tick'] + out['lengthTicks'] if out else row['timelineTicks'] + row['lengthTicks']
                leaf, _ = ungroup(item)
                leaf.start += lo - row['timelineTicks']; leaf.length = hi - lo; item.length = hi - lo
            seq.components.append(item)
            fade = outgoing.get(key(row)) if row is not None else None
            if fade:
                tr = f.create.Transition('sound', length=fade['lengthTicks']); tr.cutpoint = fade['cutPoint']
                group = f.create.OperationGroup(op, length=fade['lengthTicks'], media_kind='sound')
                curve = f.create.VaryingValue(param, AUID(LINEAR if fade['samePcm'] else POWER))
                curve.add_keyframe(0, 0); curve.add_keyframe(1, 1)
                group.parameters.append(curve); tr['OperationGroup'].value = group
                seq.components.append(tr)
        slot.segment = seq


def verify(comp, rows, plans):
    from dialogue_preserve import ungroup
    incoming = {p['right']: p for p in plans}; outgoing = {p['left']: p for p in plans}
    byslot = {}
    for row in rows:
        byslot.setdefault(row['slotId'], []).append(row)
    for slot in comp.slots:
        if slot.slot_id not in byslot:
            continue
        expected = sorted(byslot[slot.slot_id], key=lambda r: r['timelineTicks'])
        clips = [(t, c) for _, t, c in slot.segment.positions() if c.__class__.__name__ not in ['Filler', 'Transition']]
        if len(clips) != len(expected):
            raise ValueError('원본 개별 클립 수 검증에 실패했어요.')
        for row, (tick, c) in zip(expected, clips):
            inc, out = incoming.get(key(row)), outgoing.get(key(row))
            lo = inc['tick'] if inc else row['timelineTicks']
            hi = out['tick'] + out['lengthTicks'] if out else row['timelineTicks'] + row['lengthTicks']
            leaf, gain = ungroup(c)
            if (tick != lo or c.length != hi - lo or str(leaf.mob_id) != row['topSourceId'] or leaf.slot_id != row['topSourceSlot']
                    or leaf.start - tick != row['topSourceStart'] - row['timelineTicks']
                    or abs(gain - float(Fraction(row['exportAmplitude']))) > 1e-9):
                raise ValueError('원본 클립의 소스·게인·싱크 검증에 실패했어요.')
        got = [(t, c) for _, t, c in slot.segment.positions() if c.__class__.__name__ == 'Transition']
        wanted = sorted([p for p in plans if p['slotId'] == slot.slot_id], key=lambda p: p['tick'])
        if len(got) != len(wanted):
            raise ValueError('AAF 페이드 수 검증에 실패했어요.')
        for (t, c), plan in zip(got, wanted):
            group = c['OperationGroup'].value; curve = list(group.parameters)[0]
            if (t != plan['tick'] or c.length != plan['lengthTicks'] or c.cutpoint != plan['cutPoint']
                    or str(group.operation.auid) != DISSOLVE
                    or str(curve.interpolationdef.auid) != (LINEAR if plan['samePcm'] else POWER)
                    or [(float(p.time), float(p.value)) for p in curve['PointList'].value] != [(0, 0), (1, 1)]):
                raise ValueError('AAF 페이드 곡선 검증에 실패했어요.')


def preview(f, root, rows, plans, engine, duration):
    """Read the final AAF, including handles/curves, for browser A/B parity."""
    from dialogue_preserve import resolve, extract
    selected = {r['slotId'] for r in rows}
    tracks, temporary = [], []
    comp = next(f.content.toplevel())
    for slot in comp.slots:
        if slot.slot_id not in selected:
            continue
        rate = Fraction(str(slot.edit_rate)); items = list(slot.segment.positions())
        fades = {i: (t, c) for i, t, c in items if c.__class__.__name__ == 'Transition'}
        for i, tick, c in items:
            if c.__class__.__name__ in ['Transition', 'Filler']:
                continue
            mob, start, gain = resolve(c, duration=(Fraction(c.length) / rate, rate))
            stream = engine.open_pcm_stream(mob.essence); layout = engine.pcm_layout(mob.descriptor, stream); stream.close()
            raw = root / 'preview-source.wav'
            row = {'layout': layout, 'first': round(start * layout[0]), 'frames': round(Fraction(c.length) / rate * layout[0])}
            extract(mob, row, raw, engine)
            filters = ['volume=%.12f' % gain]
            for neighbor, kind in [(i - 1, 'in'), (i + 1, 'out')]:
                if neighbor not in fades:
                    continue
                at, tr = fades[neighbor]; curve = list(tr['OperationGroup'].value.parameters)[0]
                shape = 'tri' if str(curve.interpolationdef.auid) == LINEAR else 'squ'
                filters.append('afade=t=%s:st=%.12f:d=%.12f:curve=%s' % (kind, float(Fraction(at - tick) / rate), float(Fraction(tr.length) / rate), shape))
            name = 'wet-%d.wav' % len(tracks)
            engine.ff('-i', raw, '-af', ','.join(filters), '-ar', 48000, '-ac', 2, '-c:a', 'pcm_s16le', root / name)
            tracks.append({'file': name, 'start': float(Fraction(tick) / rate), 'gain': 0}); temporary.append(root / name)
    engine.mix(root, tracks, 'mix.wav', duration, limit=False)
    (root / 'preview-source.wav').unlink(missing_ok=True)
    for path in temporary:
        path.unlink(missing_ok=True)
