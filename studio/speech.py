"""Local-only speech activity and static gain policy; no network at inference."""
import hashlib
import math
import os
from pathlib import Path
import re
import statistics
import subprocess

MODEL_SHA256 = '2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f'
MODEL_PATH = Path(os.environ.get('STUDIO_VAD_MODEL', Path(__file__).resolve().parents[1] / '.venv-studio/models/silero_vad_v5.1.2.onnx'))


def matching_gain(floor, references):
    """Do not amplify silence, guess across a scene change, or raise noise a lot."""
    if floor is None or not references:
        return 0.0, 'noiseHoldNoReference', None, False
    if max(references) - min(references) > 6:
        return 0.0, 'noiseHoldConflictingReferences', None, False
    target = statistics.median(references)
    requested = target - floor
    gain = max(-12, min(3, requested))
    return gain, 'noiseFloorMatch', target, abs(gain - requested) > .01


class Analyzer:
    def __init__(self):
        import numpy as np
        import onnxruntime as ort
        self.np = np
        if not MODEL_PATH.is_file() or hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError('음성 구분 모델을 준비하지 못했어요. 처리 서버 상태를 확인해 주세요.')
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(MODEL_PATH), sess_options=opts, providers=['CPUExecutionProvider'])

    def decode(self, path, rate=16000):
        data = subprocess.check_output(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-ar', str(rate), '-ac', '1', '-f', 'f32le', '-'], timeout=3600)
        return self.np.frombuffer(data, dtype='<f4')

    def probabilities(self, x):
        np = self.np
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, 64), dtype=np.float32)
        p = []
        for i in range(0, len(x), 512):
            a = x[i:i + 512]
            a = np.pad(a, (0, 512 - len(a))).reshape(1, 512)
            data = np.concatenate((context, a), axis=1).astype(np.float32)
            pred, state = self.session.run(None, {'input': data, 'state': state, 'sr': np.array(16000, dtype=np.int64)})
            p.append(float(pred[0, 0]))
            context = data[:, -64:]
        return np.array(p)

    def classify(self, path, duration, lead, amplitude=1):
        np = self.np
        x = self.decode(path) * amplitude
        probabilities = self.probabilities(x)
        times = np.arange(len(probabilities)) * .032 - lead
        selected = (times + .032 > 0) & (times < duration)
        pp, tt = probabilities[selected], times[selected]
        edges = np.diff(np.r_[False, pp >= .5, False].astype(np.int8))
        merged = []
        for lo, hi in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
            a, b = lo * .032, hi * .032
            if merged and a - merged[-1][1] <= .128:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        regions = [[max(0, a + float(tt[0])), min(duration, b + float(tt[0]))] for a, b in merged if b - a >= .128] if len(tt) else []
        regions = [[a, b] for a, b in regions if b > a]
        total = sum(b - a for a, b in regions)
        peakp = float(pp.max()) if len(pp) else 0
        category = 'speech' if total >= .128 and peakp >= .75 else 'noise' if peakp < .2 and total == 0 else 'review'
        signal = x[round(lead * 16000):round((lead + duration) * 16000)]
        noise = []
        for t, probability in zip(tt, pp):
            if probability >= .15 or any(t + .032 > a - .15 and t < b + .15 for a, b in regions):
                continue
            a, b = max(0, round(t * 16000)), min(len(signal), round((t + .032) * 16000))
            if b <= a:
                continue
            rms = float(np.sqrt(np.mean(signal[a:b].astype(np.float64) ** 2)))
            db = 20 * math.log10(max(rms, 1e-12))
            if -90 < db < 0:
                noise.append([max(0, float(t)), db])
        def floor(items):
            return float(np.median([z[1] for z in items])) if len(items) >= 4 else None
        if category == 'noise':
            frames = [signal[j:j + 1600] for j in range(0, len(signal) - 1599, 1600)]
            rms = np.array([20 * math.log10(max(float(np.sqrt(np.mean(a.astype(np.float64) ** 2))), 1e-12)) for a in frames])
            rms = rms[rms > -90]
            span = float(np.percentile(rms, 90) - np.percentile(rms, 10)) if len(rms) >= 3 else None
            sampled = [frames[int(i)] for i in np.linspace(0, len(frames) - 1, min(256, len(frames)))] if frames else []
            spectra = [np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2 + 1e-20 for a in sampled]
            flatness = float(np.median([np.exp(np.mean(np.log(z))) / np.mean(z) for z in spectra])) if spectra else 0
            if span is None or span > 12 or flatness < .005 or floor(noise) is None:
                category = 'review'
        profile = roomtone_profile(signal, pp, tt, regions, np)
        protected = []
        for i, probability in enumerate(probabilities):
            if probability < .15:
                continue
            a, b = float(i * .032 - lead - .15), float(i * .032 - lead + .182)
            if protected and a <= protected[-1][1]:
                protected[-1][1] = b
            else:
                protected.append([a, b])
        return {'category': category, 'speech': regions, 'speechSeconds': total, 'maxSpeechProbability': peakp,
                'roomtone': profile, 'protectedContext': protected, 'contextLead': lead,
                'contextTail': max(0, len(x) / 16000 - lead - duration),
                'noiseFloorDbfs': floor(noise), 'noiseHeadDbfs': floor([z for z in noise if z[0] <= min(1, duration)]),
                'noiseTailDbfs': floor([z for z in noise if z[0] >= max(0, duration - 1)])}

    def levels(self, path, regions, amplitude, engine):
        text = engine.ff('-i', path, '-af', 'volume=%.12f,ebur128=metadata=1:peak=true,ametadata=mode=print' % amplitude, '-f', 'null', '-')
        windows, t = {'S': [], 'M': []}, -1
        for line in text.splitlines():
            m = re.search(r'pts_time:([0-9.]+)', line)
            if m:
                t = float(m.group(1)) + .1
            m = re.search(r'lavfi\.r128\.([MS])=(-?[0-9.]+)', line)
            if not m:
                continue
            k, value = m.group(1), float(m.group(2))
            window = 3 if k == 'S' else .4
            overlap = sum(max(0, min(t, b) - max(t - window, a)) for a, b in regions)
            if t >= window - .0001 and value > -70 and overlap / window >= .6:
                windows[k].append(value)
        k = 'S' if windows['S'] else 'M'
        vals = windows[k]
        if vals:
            vals = [v for v in vals if v >= max(vals) - 10]
        level = statistics.median(vals) if vals else None
        # 4x oversampling. Only detected speech samples drive the speech peak.
        peak, position = 0.0, 0
        args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-ar', '192000', '-ac', '1', '-f', 'f32le', '-']
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
            while True:
                block = proc.stdout.read(192000 * 4)
                if not block:
                    break
                x = self.np.frombuffer(block, dtype='<f4')
                for a, b in regions:
                    lo, hi = max(0, round(a * 192000) - position), min(len(x), round(b * 192000) - position)
                    if hi > lo:
                        peak = max(peak, float(self.np.max(self.np.abs(x[lo:hi]))) * amplitude)
                position += len(x)
            if proc.wait(timeout=3600):
                raise ValueError('대사 피크를 측정하지 못했어요.')
        tp = 20 * math.log10(peak) if peak > 0 else None
        return {'lufs': level, 'metric': 'shortTerm' if k == 'S' and vals else 'momentary' if vals else 'peakOnly', 'truePeakDbtp': tp}


def roomtone_profile(signal, probabilities, times, regions, np):
    """Bounded 100ms clean windows; disjoint calibration/validation frames."""
    count = len(signal) // 1600
    if count < 4:
        return None
    indices = sorted(set(np.linspace(0, count - 1, min(512, count), dtype=int).tolist()
                         + list(range(min(10, count))) + list(range(max(0, count - 10), count))))
    frames = []
    for i in indices:
        a, b = i * .1, (i + 1) * .1
        if any(a < hi + .15 and b > lo - .15 for lo, hi in regions):
            continue
        lo = max(0, int(np.searchsorted(times, a - .032, side='right')))
        hi = int(np.searchsorted(times, b, side='left'))
        if hi <= lo or float(np.max(probabilities[lo:hi])) >= .15:
            continue
        x = signal[i * 1600:(i + 1) * 1600].astype(np.float64)
        db = 20 * math.log10(max(float(np.sqrt(np.mean(x * x))), 1e-12))
        if not -90 < db < -25:
            continue
        power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        freq = np.fft.rfftfreq(len(x), 1 / 16000)
        bands = [float(np.sum(power[(freq >= lo) & (freq < hi)])) for lo, hi in [(80, 250), (250, 1000), (1000, 4000), (4000, 8000)]]
        frames.append((db, bands))
    if len(frames) < 4:
        return None
    median = float(np.median([x[0] for x in frames]))
    frames = [x for x in frames if abs(x[0] - median) < 6]
    if len(frames) < 4:
        return None
    bands = np.median([x[1] for x in frames], axis=0)
    bands /= max(float(np.sum(bands)), 1e-20)
    return {'calibrationDbfs': float(np.median([x[0] for x in frames[::2]])),
            'validationDbfs': float(np.median([x[0] for x in frames[1::2]])),
            'frames': len(frames), 'bands': bands.tolist()}
