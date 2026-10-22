"""Mouth-motion amplitude per checkpoint on held-out clips (container).

ratio = std(predicted mouth darkness) / std(real mouth darkness) inside the
ground-truth mouth mask, same realtime windows as evaluate.py. ~1 means the
mouth opens as much as in the footage; well below 1 = mumbling/under-articulated.
usage: python /clean/amplitude.py 50 60 70 100 150
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
from face_utils import mask_mouth, load_face_crop, extract_inner
from inference import load_model

device = torch.device('cuda')
root = Path('/work/data')
manifest = json.loads((root / 'manifest.json').read_text())
keep = torch.from_numpy(mask_mouth(np.ones((144, 144, 3), np.uint8)).transpose(2, 0, 1).astype(np.float32)).to(device)
base = torch.from_numpy(extract_inner(load_face_crop(str(root / 'base.jpg'), str(root / 'base.lms'))).transpose(2, 0, 1).copy()).float().to(device) / 255


def darkness(crops, masks):
    gray = crops.astype(np.float32).mean(-1)
    return ((255 - gray) * masks).sum((1, 2)) / np.maximum(masks.sum((1, 2)), 1)


out = {}
for epoch in map(int, sys.argv[1:]):
    net = load_model(f'/work/checkpoints/epoch_{epoch}.pth', device)
    row = {}
    for c in [c for c in manifest['clips'] if c['split'] == 'validation']:
        d = root / c['name']
        gt = np.load(d / 'crops.npy')
        masks = np.load(d / 'masks.npy').reshape(len(gt), 144, 144).astype(np.float32)
        w = np.load(d / 'stream_windows.npy')[0]
        w = np.concatenate([w, np.zeros((len(w), 7, 2, 1024), np.float16)], 1).astype(np.float32)
        preds = []
        with torch.inference_mode():
            for i in range(0, len(gt), 16):
                t = torch.from_numpy(gt[i:i + 16].transpose(0, 3, 1, 2).copy()).float().to(device) / 255
                a = torch.from_numpy(w[i:i + 16]).to(device).reshape(-1, 40, 1024)
                p = net(torch.cat([base[None].expand(len(t), -1, -1, -1), t * keep], 1), a)
                preds.append((p.cpu().numpy().transpose(0, 2, 3, 1) * 255).clip(0, 255).astype(np.uint8))
        pd, gd = darkness(np.concatenate(preds), masks), darkness(gt, masks)
        row[c['name']] = round(float(pd.std() / gd.std()), 3)
    out[epoch] = row
    print(epoch, row, flush=True)
Path('/work/output/amplitude.json').write_text(json.dumps(out, indent=2))
