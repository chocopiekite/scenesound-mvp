"""Move original source references, never baked/mixed PCM, into scene lanes."""
from fractions import Fraction
import re

ROLES = {'dialogue', 'walla', 'original', 'ignore'}


def default_role(name):
    if re.search(r'\bDIA\s*B\b|\bWALLA\b|왈라', name, re.I): return 'walla'
    if re.search(r'\bOMF\b|\bGUIDE\b|비교', name, re.I): return 'original'
    return 'dialogue'


def allocate(rows, scenes, duration):
    pools, lanes = {}, []
    for row in sorted(rows, key=lambda r: (r['timelineTicks'] / Fraction(r['editRate']), r['slotId'], r['componentIndex'])):
        start, end = row['start'], row['start'] + row['duration']
        overlaps = [max(0., min(end, scenes[i + 1]['start'] if i + 1 < len(scenes) else duration) - max(start, s['start'])) for i, s in enumerate(scenes)]
        scene = max(range(len(scenes)), key=lambda i: overlaps[i])
        role = row['layoutRole']; signature = (scene, role, row['editRate'], row['layout'][1])
        pool = pools.setdefault(signature, [])
        lane = next((a for a in pool if a['endTick'] <= row['timelineTicks']), None)
        if lane is None:
            number = len(pool) + 1
            prefix = 'DIA B' if role == 'walla' else 'DIA'
            name = '%s S%02d%s' % (prefix, scene + 1, ' AUX %d' % (number - 1) if number > 1 else '')
            if any(x['name'] == name for x in lanes): name += ' · %sch/%s' % (row['layout'][1], row['editRate'])
            lane = {'id': 'scene-%d' % len(lanes), 'name': name, 'sceneIndex': scene, 'role': role,
                    'rate': row['editRate'], 'endTick': 0, 'rows': [], 'auxiliary': number > 1}
            pool.append(lane); lanes.append(lane)
        if len(lanes) > 256: raise ValueError('겹침을 보존하는 데 필요한 트랙이 256개를 넘었어요. 씬·트랙 분류를 확인해 주세요.')
        row.update(inputKey='%s:%s' % (row['slotId'], row['componentIndex']), sceneIndex=scene,
                   sceneTitle=scenes[scene]['title'], crossesScene=sum(x > 1 / 48000 for x in overlaps) > 1,
                   laneName=lane['name'], auxiliary=lane['auxiliary'])
        lane['rows'].append(row); lane['endTick'] = row['timelineTicks'] + row['lengthTicks']
    return lanes


def sound_slot(f,comp,rate):
    slot=comp.create_timeline_slot(rate,slot_id=max([s.slot_id for s in comp.slots]+[0])+1)
    slot.segment=f.create.Sequence(media_kind='sound')
    return slot


def backups(f, tracks, selected):
    """Called before any edit. Retain raw original gain on OMF comparison lanes."""
    from dialogue_preserve import snapshot
    comp = next(f.content.toplevel()); existing = {s.slot_id:s for s in comp.slots}
    # An explicitly retained OMF/guide already serves as the user's comparison.
    have_guide = any(default_role(t['name']) == 'original' and t['slotId'] not in selected for t in tracks)
    if not have_guide:
        for t in tracks:
            if t['slotId'] not in selected: continue
            src = existing[t['slotId']]; slot = sound_slot(f,comp,src.edit_rate)
            slot.name = ('OMF COMPARE · ' + t['name'])[:100]
            slot.segment = src.segment.copy(); slot['Origin'].value = src['Origin'].value
    ids = {s.slot_id for s in comp.slots if s.slot_id not in selected and str(s.media_kind).lower() == 'sound' and any(c.__class__.__name__!='Filler' for c in s.segment.components)}
    return [s for s in snapshot(comp) if s['id'] in ids]


def move(f, lanes, duration):
    comp = next(f.content.toplevel()); old = {s.slot_id:s for s in comp.slots}; source_slots = set()
    tracks = []
    for lane in lanes:
        slot = sound_slot(f,comp,Fraction(lane['rate'])); slot.name = lane['name']; cursor = 0; clips = []
        for row in lane['rows']:
            source_slots.add(row['slotId'])
            c = old[row['slotId']].segment.components[row['componentIndex']].copy()
            if row['timelineTicks'] > cursor: slot.segment.components.append(f.create.Filler(media_kind='sound', length=row['timelineTicks'] - cursor))
            ci = len(slot.segment.components); slot.segment.components.append(c)
            clips.append({'start':row['start'],'duration':row['duration'],'name':row['sourceName'],'componentIndex':ci,
                          'inputKey':row['inputKey'],'clip':row['clip'],'waveform':row.get('waveform',[])})
            row.update(slotId=slot.slot_id, componentIndex=ci)
            cursor = row['timelineTicks'] + row['lengthTicks']
        end = max(cursor, round(Fraction(str(duration)) * Fraction(lane['rate'])))
        if end > cursor: slot.segment.components.append(f.create.Filler(media_kind='sound',length=end-cursor))
        slot.segment.length=end
        tracks.append({'id':lane['id'],'slotId':slot.slot_id,'name':slot.name,'role':lane['role'],
                       'sceneIndex':lane['sceneIndex'],'auxiliary':lane['auxiliary'],'clips':clips})
    for i in range(len(comp.slots)-1,-1,-1):
        if comp.slots[i].slot_id in source_slots: comp.slots.pop(i)
    return tracks
