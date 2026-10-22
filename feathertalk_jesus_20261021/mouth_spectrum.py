"""How fast does the mouth change? Temporal spectrum of the mouth patch (container).

Mouth region (average training mouth mask) of each 144x144 frame -> grayscale
-> PCA (first 8 components, i.e. the main mouth-shape changes) -> spectrum of
each component over time. Reported: share of temporal energy above 6 Hz and
above 9 Hz (25 fps -> Nyquist 12.5 Hz). Speech articulation lives mostly
below ~6-7 Hz, so a larger high-band share = mouth "twitching".
Real footage crops are measured the same way (they are landmark-aligned per
frame, so head motion is largely removed).
usage: python /clean/mouth_spectrum.py <epoch> <variant> <wav16k> [...]
variant: live (moving references, like the runtime) | fixed (one reference) |
         fixed_ema<a> (fixed reference + feature EMA a)
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from stream_core import Engine
from face_utils import crop_face, extract_inner, mask_mouth, hwc_to_chw_tensor, reshape_audio_feat
from jesus_stream import Session

epoch, variant = int(sys.argv[1]), sys.argv[2]
alpha = float(variant[len('fixed_ema'):]) if variant.startswith('fixed_ema') else 1.
root = Path('/work/data')
region = np.mean([np.load(root / c / 'masks.npy').reshape(-1, 144, 144).mean(0) for c in ['speech_01', 'speech_05', 'speech_09']], 0) > .3


def high_share(frames):
    x = np.asarray(frames, np.float32).mean(-1)[:, region]
    x = x - x.mean(0)
    u, s, vt = np.linalg.svd(x, full_matrices=False)
    comps = u[:, :8] * s[:8]
    spec = np.abs(np.fft.rfft(comps - comps.mean(0), axis=0)) ** 2
    freq = np.fft.rfftfreq(len(comps), 1 / 25)
    total = spec[freq > .5].sum()
    return dict(above6hz=round(float(spec[freq > 6].sum() / total), 3),
                above9hz=round(float(spec[freq > 9].sum() / total), 3))


d = root / os.getenv('SPEC_IDLE', 'idle_waiting')
FIXED = int(os.getenv('SPEC_FIXED', '-1'))
frames = np.load(d / 'frames.npy', mmap_mode='r')
boxes = np.load(d / 'bboxes.npy')
indices = np.load(d / 'source_indices.npy')
refs = [extract_inner(crop_face(f, tuple(b))) for f, b in zip(frames, boxes)]


class Probe(Engine):
    def __init__(self):
        super().__init__(f'/work/checkpoints/epoch_{epoch}.pth')
        self.inputs = torch.stack([torch.cat([hwc_to_chw_tensor(r.copy()), hwc_to_chw_tensor(mask_mouth(r.copy()))], 0)
                                   for r in refs]).to(self.device)

    def reset(self):
        self.cursor, self.filtered, self.preds = 0, None, []

    @torch.inference_mode()
    def render(self, window):
        i = int(indices[self.cursor % len(indices)]) if variant == 'live' else (FIXED if FIXED >= 0 else int(indices[0]))
        a = reshape_audio_feat(torch.from_numpy(window))[None].to(self.device)
        self.filtered = a if self.filtered is None else alpha * a + (1 - alpha) * self.filtered
        self.preds.append((self.visual(self.inputs[i:i + 1], self.filtered)[0].cpu().numpy().transpose(1, 2, 0) * 255).clip(0, 255))
        self.cursor += 1
        return None, None


result = {'epoch': epoch, 'variant': variant,
          'real_footage': {c: high_share(np.load(root / c / 'crops.npy')) for c in ['speech_12', 'speech_36', 'speech_01']}}
engine = Probe()
for wav in sys.argv[3:]:
    pcm, sr = sf.read(wav, dtype='float32')
    engine.reset()
    session = Session(engine)
    for offset in list(range(0, len(pcm), 1600)) + [None]:
        session.push([], True) if offset is None else session.push(pcm[offset:offset + 1600])
    result[Path(wav).parent.name if Path(wav).stem == 'audio' else Path(wav).stem] = high_share(engine.preds)
print(json.dumps(result), flush=True)
