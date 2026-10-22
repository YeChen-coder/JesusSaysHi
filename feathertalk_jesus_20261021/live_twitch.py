"""Mouth twitch on the realtime path for arbitrary audio (container), with optional feature EMA.

Runs jesus_stream.Session (100 ms pushes, 80 ms lookahead) on the idle_waiting
base with moving references, exactly like the avatar runtime, and records each
144x144 prediction. Openness = darkness inside the average training mouth
mask (the crop is face-normalised, so the region is stable).
  zigzag = share of frames where the openness direction reverses with both
           steps > 1.5 (an open-close-open flicker), per second
  jerk   = mean |2nd difference| of openness
Real footage (speech_12/36 crops) is measured the same way as the reference.
usage: python /clean/live_twitch.py <epoch> <alpha> <wav16k> [<wav16k> ...]
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from stream_core import Engine
from face_utils import crop_face, extract_inner, mask_mouth, hwc_to_chw_tensor, reshape_audio_feat
from jesus_stream import Session

epoch, alpha = int(sys.argv[1]), float(sys.argv[2])
root = Path('/work/data')
region = np.mean([np.load(root / c / 'masks.npy').reshape(-1, 144, 144).mean(0) for c in ['speech_01', 'speech_05', 'speech_09']], 0) > .5


def series_stats(o):
    d = np.diff(o)
    rev = (np.sign(d[1:]) != np.sign(d[:-1])) & (np.abs(d[1:]) > 1.5) & (np.abs(d[:-1]) > 1.5)
    return dict(zigzag_per_s=float(rev.sum() / (len(o) / 25)), jerk=float(np.abs(np.diff(o, 2)).mean()),
                std=float(o.std()))


def openness(crops):
    gray = np.asarray(crops, np.float32).mean(-1)
    return (255 - gray)[:, region].mean(1)


d = root / 'idle_waiting'
frames = np.load(d / 'frames.npy', mmap_mode='r')
boxes = np.load(d / 'bboxes.npy')
indices = np.load(d / 'source_indices.npy')
references = [extract_inner(crop_face(f, tuple(b))) for f, b in zip(frames, boxes)]


class Probe(Engine):
    def __init__(self):
        super().__init__(f'/work/checkpoints/epoch_{epoch}.pth')
        self.inputs = torch.stack([torch.cat([hwc_to_chw_tensor(r.copy()), hwc_to_chw_tensor(mask_mouth(r.copy()))], 0)
                                   for r in references]).to(self.device)
        self.cursor = 0
        self.filtered = None
        self.preds = []

    @torch.inference_mode()
    def render(self, window):
        i = int(indices[self.cursor % len(indices)])
        audio = reshape_audio_feat(torch.from_numpy(window))[None].to(self.device)
        self.filtered = audio if self.filtered is None else alpha * audio + (1 - alpha) * self.filtered
        p = self.visual(self.inputs[i:i + 1], self.filtered)[0].cpu().numpy().transpose(1, 2, 0) * 255
        self.preds.append(p.clip(0, 255))
        self.cursor += 1
        return None, None


engine = Probe()
result = {'epoch': epoch, 'alpha': alpha,
          'real_footage': {c: series_stats(openness(np.load(root / c / 'crops.npy'))) for c in ['speech_12', 'speech_36']}}
for wav in sys.argv[3:]:
    pcm, sr = sf.read(wav, dtype='float32')
    assert sr == 16000
    engine.preds, engine.filtered, engine.cursor = [], None, 0
    session = Session(engine)
    for offset in list(range(0, len(pcm), 1600)) + [None]:
        session.push([], True) if offset is None else session.push(pcm[offset:offset + 1600])
    result[Path(wav).stem] = series_stats(openness(engine.preds))
print(json.dumps(result), flush=True)
