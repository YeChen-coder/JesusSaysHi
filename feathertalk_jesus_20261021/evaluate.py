"""Rank checkpoints, measure lip sync on held-out clips, export review videos with the realtime path.

1. Every saved checkpoint (epoch >= 50) is scored on held-out speech_12/36 with
   the exact realtime audio windows (audio_lookahead 2): mouth-masked L1, and a
   sync check: per-frame mouth darkness (inside the ground-truth mouth mask)
   of prediction vs real footage -> Pearson r at lag 0 and the best lag in
   [-5, 5] frames (positive lag = prediction late).
2. The best few (and the last epoch) are exported through jesus_stream.Session
   (100 ms pushes, 80 ms lookahead) on the idle_waiting base with the approved
   NativeFaceMatch: held-out speech_12, speech_36 and an unseen voice (novel).
Writes output/evaluation.json and output/eval/<epoch>/*.mp4.
"""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
import torch
from stream_core import Engine
from face_utils import crop_face, extract_inner, mask_mouth, hwc_to_chw_tensor, reshape_audio_feat, load_face_crop
from inference import load_model
from native_face_match import NativeFaceMatch
from jesus_stream import Session

torch.set_num_threads(4)
cv2.setNumThreads(1)
device = torch.device('cuda')
root = Path('/work/data')
out = Path('/work/output')
ckdir = Path('/work/checkpoints')
metrics_dir = out
# Smoke-test overrides: EVAL_MIN_EPOCH, EVAL_OUT (a scratch output dir), EVAL_AUDIO_SECONDS.
MIN_EPOCH = int(os.getenv('EVAL_MIN_EPOCH', '50'))
if os.getenv('EVAL_OUT'):
    out = Path(os.environ['EVAL_OUT'])
    out.mkdir(parents=True, exist_ok=True)
AUDIO_SECONDS = float(os.getenv('EVAL_AUDIO_SECONDS', '0'))
EXPORT_TOP = 3
FIXED_REF = int(os.environ['EVAL_FIXED_REF']) if os.getenv('EVAL_FIXED_REF') else None
NOVEL = Path('/novel/novel_audio.wav')

manifest = json.loads((root / 'manifest.json').read_text())
val_clips = [c for c in manifest['clips'] if c['split'] == 'validation']
keep = torch.from_numpy(mask_mouth(np.ones((144, 144, 3), np.uint8)).transpose(2, 0, 1).astype(np.float32)).to(device)
base = torch.from_numpy(extract_inner(load_face_crop(str(root / 'base.jpg'), str(root / 'base.lms'))).transpose(2, 0, 1).copy()).float().to(device) / 255
val = []
for c in val_clips:
    d = root / c['name']
    windows = np.load(d / 'stream_windows.npy')[0]  # audio_lookahead 2
    w = np.concatenate([windows, np.zeros((len(windows), 7, 2, 1024), np.float16)], 1).astype(np.float32)
    masks = np.load(d / 'masks.npy')
    masks = masks.reshape(len(masks), 144, 144)  # stored as [n, 1, 144, 144]
    val.append(dict(name=c['name'], gt=np.load(d / 'crops.npy'), masks=masks, windows=w))


def darkness(crops, masks):
    gray = crops.astype(np.float32).mean(-1)
    m = masks.astype(np.float32)
    return ((255 - gray) * m).sum((1, 2)) / np.maximum(m.sum((1, 2)), 1)


def sync(pred_series, gt_series):
    a = (pred_series - pred_series.mean()) / (pred_series.std() + 1e-6)
    b = (gt_series - gt_series.mean()) / (gt_series.std() + 1e-6)
    lags = {}
    for lag in range(-5, 6):  # pred[t] vs gt[t - lag]
        if lag >= 0:
            x, y = a[lag:], b[:len(b) - lag]
        else:
            x, y = a[:lag], b[-lag:]
        lags[lag] = float(np.mean(x * y))
    best = max(lags, key=lags.get)
    return dict(r_lag0=lags[0], best_lag=best, r_best=lags[best])


@torch.inference_mode()
def score(checkpoint):
    net = load_model(str(checkpoint), device)
    net.eval()
    num = den = 0.
    per_clip = {}
    for clip in val:
        preds = []
        for i in range(0, len(clip['gt']), 16):
            target = torch.from_numpy(clip['gt'][i:i + 16].transpose(0, 3, 1, 2).copy()).float().to(device) / 255
            audio = torch.from_numpy(clip['windows'][i:i + 16]).to(device).reshape(-1, 40, 1024)
            pred = net(torch.cat([base[None].expand(len(target), -1, -1, -1), target * keep], 1), audio)
            masks = torch.from_numpy(clip['masks'][i:i + 16]).float().to(device)
            num += float(((pred - target).abs() * masks[:, None]).sum())
            den += float(masks.sum() * 3)
            preds.append((pred.cpu().numpy().transpose(0, 2, 3, 1) * 255).clip(0, 255).astype(np.uint8))
        pred = np.concatenate(preds)
        per_clip[clip['name']] = sync(darkness(pred, clip['masks']), darkness(clip['gt'], clip['masks']))
    del net
    torch.cuda.empty_cache()
    return dict(mouth_l1=num / den, sync=per_clip,
                mean_r_lag0=float(np.mean([v['r_lag0'] for v in per_clip.values()])))


started = time.perf_counter()
rows = []
for path in sorted(ckdir.glob('epoch_*.pth'), key=lambda p: int(p.stem.split('_')[1])):
    epoch = int(path.stem.split('_')[1])
    if epoch < MIN_EPOCH:
        continue
    row = dict(epoch=epoch, file=path.name, **score(path))
    rows.append(row)
    print('SCORED', json.dumps({k: row[k] for k in ['epoch', 'mouth_l1', 'mean_r_lag0']}), flush=True)
by_l1 = sorted(rows, key=lambda r: r['mouth_l1'])
export_epochs = sorted({r['epoch'] for r in by_l1[:EXPORT_TOP]} | {max(r['epoch'] for r in rows)})
if os.getenv('EVAL_EXPORT_EPOCHS'):  # explicit list, e.g. the selected epoch
    export_epochs = [int(x) for x in os.environ['EVAL_EXPORT_EPOCHS'].split(',')]

# ---- realtime-path exports on the idle_waiting base ----
d = root / os.getenv('EVAL_IDLE', 'idle_waiting')
frames = np.load(d / 'frames.npy', mmap_mode='r')
points = np.load(d / 'landmarks.npy')
boxes = np.load(d / 'bboxes.npy')
indices = np.load(d / 'source_indices.npy')
references = [extract_inner(crop_face(f, tuple(b))) for f, b in zip(frames, boxes)]
matcher = NativeFaceMatch()
prepared = [matcher.prepare(f, p, b) for f, p, b in zip(frames, points, boxes)]
height, width = frames.shape[1:3]


class IdleEngine(Engine):
    def __init__(self, checkpoint):
        super().__init__(str(checkpoint))
        self.cursor = 0
        self.inputs = torch.stack([torch.cat([hwc_to_chw_tensor(r.copy()), hwc_to_chw_tensor(mask_mouth(r.copy()))], 0)
                                   for r in references]).to(self.device)

    @torch.inference_mode()
    def render(self, window):
        i = int(indices[self.cursor % len(indices)])
        m = FIXED_REF if FIXED_REF is not None else i  # model reference; compositing stays on frame i
        audio = reshape_audio_feat(torch.from_numpy(window)).unsqueeze(0).to(self.device)
        prediction = (self.visual(self.inputs[m:m + 1], audio)[0].cpu().numpy().transpose(1, 2, 0) * 255).clip(0, 255).astype(np.uint8)
        frame = np.array(frames[i])
        x1, y1, x2, y2 = map(int, boxes[i])
        frame[y1:y2, x1:x2] = matcher.apply(prediction, references[i], prepared[i])
        self.cursor += 1
        return frame, prediction


def writer(file, audio):
    return subprocess.Popen(['/usr/bin/ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                             '-s', f'{width}x{height}', '-r', '25', '-i', '-', '-i', str(audio),
                             '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p',
                             '-c:a', 'aac', '-shortest', '-movflags', '+faststart', str(file)], stdin=subprocess.PIPE)


audios = {c['name']: root / c['name'] / 'audio.wav' for c in val_clips}
if NOVEL.exists():
    audios['novel'] = NOVEL
if os.getenv('EVAL_AUDIOS'):  # explicit 16 kHz wavs instead of the held-out set
    audios = {Path(x).stem: Path(x) for x in os.environ['EVAL_AUDIOS'].split(',')}
exports = []
for epoch in export_epochs:
    engine = IdleEngine(ckdir / f'epoch_{epoch}.pth')
    dest = out / 'eval' / f'epoch_{epoch}'
    dest.mkdir(parents=True, exist_ok=True)
    for name, wav in audios.items():
        pcm, sr = sf.read(wav, dtype='float32')
        assert sr == 16000
        if AUDIO_SECONDS:
            pcm = pcm[:int(AUDIO_SECONDS * sr)]
        padded = dest / f'{name}.wav'
        sf.write(padded, np.r_[np.zeros(16000, np.float32), pcm, np.zeros(32000, np.float32)], sr)
        w = writer(dest / f'{name}.mp4', padded)
        matcher.field = None
        engine.cursor = 0
        for _ in range(25):  # 1 s idle before speech
            w.stdin.write(np.ascontiguousarray(frames[indices[engine.cursor % len(indices)]]).tobytes())
            engine.cursor += 1
        session = Session(engine)
        shots = []
        for offset in list(range(0, len(pcm), 1600)) + [None]:  # 100 ms pushes
            got = session.push([], True) if offset is None else session.push(pcm[offset:offset + 1600])
            for index, image, _ in got:
                w.stdin.write(image.tobytes())
                if index % 25 == 12 and len(shots) < 10:
                    x1, y1, x2, y2 = map(int, boxes[indices[(engine.cursor - 1) % len(indices)]])
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    shots.append(cv2.resize(image[max(0, cy - 150):cy + 90, max(0, cx - 120):cx + 120], (160, 160)))
        for _ in range(50):
            w.stdin.write(np.ascontiguousarray(frames[indices[engine.cursor % len(indices)]]).tobytes())
            engine.cursor += 1
        w.stdin.close()
        assert w.wait() == 0
        if shots:
            cv2.imwrite(str(dest / f'{name}_sheet.jpg'), np.concatenate(shots, 1))
        exports.append(dict(epoch=epoch, audio=name, file=str((dest / f'{name}.mp4').relative_to(out)),
                            sha256=hashlib.sha256((dest / f'{name}.mp4').read_bytes()).hexdigest()))
        print('EXPORTED', epoch, name, flush=True)
    del engine
    torch.cuda.empty_cache()

report = dict(
    method='held-out speech_12/36 with realtime windows (audio_lookahead 2, rows after i+2 zero); sync = mouth darkness '
           'inside the ground-truth mouth mask, prediction vs footage; exports via jesus_stream.Session, 100 ms pushes',
    ranked_by_mouth_l1=[{k: r[k] for k in ['epoch', 'mouth_l1', 'mean_r_lag0']} for r in by_l1],
    rows=rows, exported_epochs=export_epochs, exports=exports, seconds=time.perf_counter() - started)
(out / 'evaluation.json').write_text(json.dumps(report, indent=2))
print('EVALUATION_COMPLETE', flush=True)
