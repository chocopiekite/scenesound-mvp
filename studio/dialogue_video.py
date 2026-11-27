"""Bounded video-only proxies for semantic scene proposals, no AAF audio export."""
import json, math

def prepare(root, engine):
    manifest=json.loads((root/'manifest.json').read_text())
    if not manifest.get('video'): raise ValueError('씬을 분석할 참조 영상을 먼저 연결해 주세요.')
    duration=manifest['duration']; parts=[]; count=math.ceil(duration/600)
    for i in range(count):
        start=i*duration/count; length=duration/count; name='dialogue-scene-%03d.mp4'%i
        engine.save(root/'progress.json',{'stage':'씬 분석용 영상을 준비하고 있어요 · %d/%d'%(i+1,count)})
        engine.ff('-ss',start,'-i',root/manifest['video'],'-map','0:v:0','-map','0:a:0?',
                  '-vf','scale=w=min(960\\,iw):h=min(960\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2',
                  '-c:v','libx264','-preset','ultrafast','-crf',27,'-maxrate','1500k','-bufsize','3000k',
                  '-c:a','aac','-b:a','96k','-t',length,'-movflags','+faststart',root/name)
        parts.append({'file':name,'start':start,'duration':length})
    engine.save(root/'scene-proxies.json',parts)
    return {'duration':duration,'analysisSegments':parts,'analysisVideo':parts[0]['file']}
