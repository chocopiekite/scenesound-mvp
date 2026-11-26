"""Reference speech first; other clips follow that reference's roomtone."""
import math


def key(row):
    return '%s:%s' % (row['slotId'], row['componentIndex'])


def scene_index(row, scenes):
    return max(0, sum(row['start'] >= s['start'] for s in scenes) - 1)


def color_similarity(a, b):
    x, y = a['bands'], b['bands']
    denom = math.sqrt(sum(v * v for v in x) * sum(v * v for v in y))
    return sum(i * j for i, j in zip(x, y)) / denom if denom else 0


def reference_gain(row):
    before = row['before']
    profile = row.get('roomtone')
    if (row['category'] != 'speech' or before.get('metric') != 'shortTerm'
            or before.get('lufs') is None or before.get('truePeakDbtp') is None
            or row['duration'] < 3 or not profile or row['topGain'] <= 0):
        return None
    gain = -24 - before['lufs']
    if not -15 <= before['truePeakDbtp'] + gain <= -10:
        return None
    if row.get('totalPeakDbtp') is None or row['totalPeakDbtp'] + gain > -1:
        return None
    if not -144 <= 20 * math.log10(row['topGain']) + gain <= 36:
        return None
    return gain


def apply(rows, scenes, settings):
    references = []
    for row in rows:
        row.update(finalGainDb=0., method='preserveUncertain', referenceKey=None)
    for i, scene in enumerate(scenes):
        end = scenes[i + 1]['start'] if i + 1 < len(scenes) else float('inf')
        group = [r for r in rows if scene_index(r, scenes) == i and r['start'] + r['duration'] <= end + 1e-6]
        requested = settings.get('referenceClips', {}).get(str(i))
        candidates = [r for r in group if reference_gain(r) is not None and (not requested or key(r) == requested)]
        if not candidates:
            for r in group:
                r['method'] = 'referenceUnavailable'
            references.append({'sceneIndex': i, 'title': scene['title'], 'ready': False,
                               'reason': '선택한 기준 클립이 목표/룸톤 조건을 만족하지 않아요.' if requested else '3초 숏텀·피크·룸톤 조건을 함께 만족하는 기준 후보가 없어요.'})
            continue
        # Prefer sustained speech and a modest change, never a quiet outlier
        # selected only because it happens to contain some roomtone.
        anchor = max(candidates, key=lambda r: (r['speechSeconds'], -abs(reference_gain(r))))
        gain = reference_gain(anchor)
        target = anchor['roomtone']['calibrationDbfs'] + gain
        refkey = key(anchor)
        anchor.update(finalGainDb=gain, method='referenceSpeech', referenceKey=refkey)
        reference = {'sceneIndex': i, 'title': scene['title'], 'ready': True, 'key': refkey,
                     'name': anchor.get('sourceName', anchor['name']), 'track': anchor['name'], 'clip': anchor['clip'],
                     'start': anchor['start'], 'duration': anchor['duration'], 'gainDb': gain, 'before': anchor['before'],
                     'after': {'lufs': -24., 'truePeakDbtp': anchor['before']['truePeakDbtp'] + gain, 'metric': 'shortTerm'},
                     'roomtoneDbfs': target}
        references.append(reference)
        for row in group:
            if row is anchor:
                continue
            row['referenceKey'] = refkey
            if row['category'] == 'review' or not row.get('roomtone'):
                row['method'] = 'roomtoneUnavailable'
                continue
            similarity = color_similarity(anchor['roomtone'], row['roomtone'])
            row['roomtoneSimilarity'] = similarity
            if similarity < .9:
                row['method'] = 'roomtoneDifferent'
                continue
            wanted = target - row['roomtone']['calibrationDbfs']
            gain = max(-12., min(6. if row['category'] == 'speech' else 3., wanted))
            peak = row.get('totalPeakDbtp')
            if peak is not None and peak + gain > -1:
                gain = -1 - peak
                row['speechSafetyLimited'] = True
            if row['topGain'] > 0:
                gain = max(-144 - 20 * math.log10(row['topGain']), min(36 - 20 * math.log10(row['topGain']), gain))
            row.update(finalGainDb=gain, method='referenceRoomtone', roomtoneTargetDbfs=target,
                       roomtoneMatchLimited=abs(gain - wanted) > .01,
                       roomtoneValidationGapDb=(row['roomtone']['validationDbfs'] + gain
                           - anchor['roomtone']['validationDbfs'] - reference['gainDb']))
    return references
