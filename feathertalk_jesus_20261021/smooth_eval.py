"""Causal mouth smoothing study (container): audio-feature EMA and half-rate visual inference.

Same idea as SpecterSaysHi/feathertalk_refresh_20261004/mouth_motion_experiment.py
(alpha 1/.5/.3, stride 1/2), measured on the held-out clips with the exact
realtime windows (80 ms lookahead) and the selected checkpoint.
Per setting, mouth openness series (darkness inside the real mouth mask):
  twitch  = mean |2nd difference| of openness, relative to the real footage
  r, lag  = correlation with the footage at the best lag (+ = mouth late)
  amp     = std of openness relative to the footage
usage: python /clean/smooth_eval.py [epoch]
"""
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import torch
from face_utils import mask_mouth, load_face_crop, extract_inner
from inference import load_model

EPOCH = int(sys.argv[1]) if len(sys.argv) > 1 else 60
dev = torch.device('cuda')
root = Path('/work/data')
keep = torch.from_numpy(mask_mouth(np.ones((144, 144, 3), np.uint8)).transpose(2, 0, 1).astype(np.float32)).to(dev)
base = torch.from_numpy(extract_inner(load_face_crop(str(root / 'base.jpg'), str(root / 'base.lms'))).transpose(2, 0, 1).copy()).float().to(dev) / 255
net = load_model(f'/work/checkpoints/epoch_{EPOCH}.pth', dev)


def openness(crops, masks):
    gray = crops.astype(np.float32).mean(-1)
    return ((255 - gray) * masks).sum((1, 2)) / masks.sum((1, 2))


def lagged(p, g):
    a = (p - p.mean()) / (p.std() + 1e-6)
    b = (g - g.mean()) / (g.std() + 1e-6)
    out = {}
    for lag in range(-3, 6):
        x, y = (a[lag:], b[:len(b) - lag]) if lag >= 0 else (a[:lag], b[-lag:])
        out[lag] = float(np.mean(x * y))
    best = max(out, key=out.get)
    return out[0], best, out[best]


clips = {}
for name in ['speech_12', 'speech_36']:
    d = root / name
    gt = np.load(d / 'crops.npy')
    m = np.load(d / 'masks.npy').reshape(len(gt), 144, 144).astype(np.float32)
    w = np.load(d / 'stream_windows.npy')[0]
    w = np.concatenate([w, np.zeros((len(w), 7, 2, 1024), np.float16)], 1).astype(np.float32).reshape(len(gt), 40, 1024)
    clips[name] = (gt, m, w)

rows = []
for alpha, stride in itertools.product([1., .7, .5, .3], [1, 2]):
    per = {}
    for name, (gt, m, w) in clips.items():
        filtered = None
        latest = None
        preds = []
        with torch.inference_mode():
            for i in range(len(gt)):
                audio = torch.from_numpy(w[i]).to(dev)[None]
                filtered = audio if filtered is None else alpha * audio + (1 - alpha) * filtered
                if latest is None or i % stride == 0:
                    t = torch.from_numpy(gt[i].transpose(2, 0, 1).copy()).float().to(dev)[None] / 255
                    latest = net(torch.cat([base[None], t * keep], 1), filtered)
                preds.append((latest[0].cpu().numpy().transpose(1, 2, 0) * 255).clip(0, 255))
        p = openness(np.asarray(preds), m)
        g = openness(gt.astype(np.float32), m)
        r0, lag, rb = lagged(p, g)
        per[name] = dict(twitch=float(np.abs(np.diff(p, 2)).mean() / np.abs(np.diff(g, 2)).mean()),
                         r_lag0=r0, best_lag=lag, r_best=rb, amp=float(p.std() / g.std()))
    row = dict(alpha=alpha, stride=stride, **{k: round(float(np.mean([v[k] for v in per.values()])), 3)
                                              for k in ['twitch', 'r_lag0', 'r_best', 'amp']},
               best_lag=[v['best_lag'] for v in per.values()], per_clip=per)
    rows.append(row)
    print(json.dumps({k: row[k] for k in ['alpha', 'stride', 'twitch', 'r_lag0', 'r_best', 'best_lag', 'amp']}), flush=True)
Path('/work/output/smoothing_study.json').write_text(json.dumps({'epoch': EPOCH, 'rows': rows}, indent=2))
