"""Build-time only; pinned official model, never downloads user media."""
import hashlib
from pathlib import Path
import sys
from urllib.request import urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'studio'))
from speech import MODEL_PATH, MODEL_SHA256
if not MODEL_PATH.is_file() or hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA256:
    data = urlopen('https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx', timeout=60).read()
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise RuntimeError('VAD model integrity check failed')
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_bytes(data)
print('Pinned speech model ready')
