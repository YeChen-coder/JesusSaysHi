"""Jesus FeatherTalk visual model: QinChe/Gentleman recipe on streaming (80 ms lookahead) audio windows.

Same Model, losses, batch (8 adjacent pairs), random training-frame reference
and FP32 as the approved QinChe baseline. Changes:
* audio windows come from prepare_stream.py, i.e. exactly what the realtime
  session will feed (rows after i+2 zero), instead of full-clip features;
  each training sample randomly uses the audio_lookahead=2 or 4 encoding;
* 150 epochs: lr 1e-3 (1-60), 3e-4 (61-110), 1e-4 (111-150);
* validation (held-out speech_12/36, audio_lookahead=2) every 5 epochs, a
  checkpoint every 5 epochs from 50, and resumable last.pth.
"""
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from model import Model
from train import compute_total_loss, save_checkpoint
from face_utils import mask_mouth, load_face_crop, extract_inner

EPOCHS = 150
P_LOOKAHEAD_2 = .6


def lr_for(epoch):  # 0-based
    return .001 if epoch < 60 else .0003 if epoch < 110 else .0001


torch.set_num_threads(4)
torch.backends.cudnn.benchmark = True
torch.cuda.set_per_process_memory_fraction(.6)
device = torch.device('cuda')
root = Path('/work/data')
out = Path('/work/output')
checkpoints = Path('/work/checkpoints')
checkpoints.mkdir(exist_ok=True)
out.mkdir(exist_ok=True)
manifest = json.loads((root / 'manifest.json').read_text())
arrays = {}
pairs = {}
for split in ['train', 'validation']:
    crops, masks, windows, pair = [], [], [], []
    n = 0
    for row in manifest['clips']:
        if row['split'] != split:
            continue
        p = root / row['name']
        count = row['frames']
        crops.append(np.load(p / 'crops.npy'))
        masks.append(np.load(p / 'masks.npy'))
        windows.append(np.load(p / 'stream_windows.npy'))
        pair.extend(range(n, n + count - 1))  # adjacent pairs never cross clips
        n += count
    gt = torch.from_numpy(np.concatenate(crops).transpose(0, 3, 1, 2).copy())
    mk = torch.from_numpy(np.concatenate(masks))
    aw = torch.from_numpy(np.concatenate(windows, axis=1)).to(device)  # [2, n, 13, 2, 1024] fp16
    arrays[split] = (gt, mk, aw)
    pairs[split] = np.asarray(pair)
ROWS = arrays['train'][2].shape[2]
keep = torch.from_numpy(mask_mouth(np.ones((144, 144, 3), np.uint8)).transpose(2, 0, 1).astype(np.float32)).to(device)
base = torch.from_numpy(extract_inner(load_face_crop(str(root / 'base.jpg'), str(root / 'base.lms'))).transpose(2, 0, 1).copy()).float().to(device) / 255


def audio_for(split, ids, variant):
    aw = arrays[split][2]
    w = aw[variant.to(device), ids].float()  # [k, 13, 2, 1024]
    w = torch.cat([w, w.new_zeros(len(ids), 20 - ROWS, 2, 1024)], 1)
    return w.reshape(-1, 40, 1024)


def batch(split, ids, variant):
    gt, mk, _ = arrays[split]
    cpu = torch.as_tensor(ids, dtype=torch.long).flatten()
    return gt[cpu].to(device).float() / 255, mk[cpu].to(device).float(), audio_for(split, cpu.to(device), variant.flatten())


net = Model().to(device)
opt = torch.optim.Adam(net.parameters(), lr=.001)
recipe = dict(initialization='random Model; seed 42', batch_pairs=8, precision='float32', epochs=EPOCHS,
              schedule=[dict(epochs='1-60', lr=.001), dict(epochs='61-110', lr=.0003), dict(epochs='111-150', lr=.0001)],
              loss=dict(full=1, mouth=4, temporal=.5, temporal_mouth=4, perceptual=0, mouth_gradient=.5, temporal_lowpass_kernel=5),
              audio=f'streaming windows (jesus_stream.py): history 100 frames, rows after i+2 zero; audio_lookahead 2 (p={P_LOOKAHEAD_2}) or 4 per sample',
              references='random training frame, same reference for adjacent pair',
              validation='held-out speech_12, speech_36; mouth-masked L1; audio_lookahead 2')
(out / 'recipe.json').write_text(json.dumps(recipe, indent=2))

start_epoch = 0
history = []
resume = checkpoints / 'last.pth'
if resume.exists():
    state = torch.load(resume, map_location=device)
    net.load_state_dict(state['model'])
    opt.load_state_dict(state['optimizer'])
    start_epoch = state['epoch'] + 1
    rng = state['rng']
    torch.set_rng_state(rng['torch'])
    torch.cuda.set_rng_state(rng['cuda'])
    np.random.set_state(rng['numpy'])
    random.setstate(rng['python'])
    history = json.loads((out / 'training_metrics.json').read_text())['history'][:start_epoch]
    print('RESUMED_AT', start_epoch + 1, flush=True)
else:
    torch.manual_seed(42)
    np.random.seed(42)
    random.seed(42)
    net = Model().to(device)
    opt = torch.optim.Adam(net.parameters(), lr=.001)


@torch.inference_mode()
def validate():
    net.eval()
    num = den = 0.
    total = len(arrays['validation'][0])
    for i in range(0, total, 8):
        ids = np.arange(i, min(i + 8, total))
        target, masks, audio = batch('validation', ids, torch.zeros(len(ids), dtype=torch.long))
        pred = net(torch.cat([base[None].expand(len(target), -1, -1, -1), target * keep], 1), audio)
        num += float(((pred - target).abs() * masks).sum())
        den += float(masks.sum() * 3)
    return dict(mouth_l1=num / den)


def save_state(path, epoch):
    torch.save({'epoch': epoch, 'model': net.state_dict(), 'optimizer': opt.state_dict(),
                'rng': {'torch': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state(),
                        'numpy': np.random.get_state(), 'python': random.getstate()}}, path)


report = dict(recipe=recipe, train_frames=len(arrays['train'][0]), validation_frames=len(arrays['validation'][0]),
              training_complete=False, history=history)
started = time.perf_counter()
for epoch in range(start_epoch, EPOCHS):
    lr = lr_for(epoch)
    for group in opt.param_groups:
        group['lr'] = lr
    net.train()
    begin = time.perf_counter()
    order = np.random.permutation(pairs['train'])
    losses = []
    for offset in range(0, len(order), 8):
        ids = order[offset:offset + 8]
        pair = np.stack([ids, ids + 1], 1)
        variant = (torch.rand(len(ids)) >= P_LOOKAHEAD_2).long()[:, None].expand(-1, 2)  # same encoding for a pair
        target, masks, audio = batch('train', pair, variant)
        refs = torch.randint(len(arrays['train'][0]), (len(ids),))
        reference = arrays['train'][0][refs].to(device).float() / 255
        reference = reference[:, None].expand(-1, 2, -1, -1, -1).flatten(0, 1)
        pred = net(torch.cat([reference, target * keep], 1), audio).reshape(len(ids), 2, 3, 144, 144)
        loss, parts = compute_total_loss(pred, target.reshape_as(pred), masks.reshape(len(ids), 2, 1, 144, 144),
                                         torch.nn.L1Loss(), lambda x, y: x.new_zeros(()), 4., .5, 4., 0., .5, 5)
        assert torch.isfinite(loss), 'Nonfinite loss'
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        losses.append(parts)
        if offset % 800 == 0:
            (out / 'training_progress.json').write_text(json.dumps(dict(
                epoch=epoch + 1, epochs=EPOCHS, pairs_done=min(offset + 8, len(order)), pairs=len(order),
                learning_rate=lr, seconds=time.perf_counter() - begin)))
    torch.cuda.synchronize()
    row = dict(epoch=epoch + 1, learning_rate=lr, seconds=time.perf_counter() - begin,
               **{k: float(np.mean([p[k] for p in losses])) for k in losses[0]})
    if (epoch + 1) % 5 == 0:
        row['validation'] = validate()
        if epoch + 1 >= 50 or (epoch + 1) % 10 == 0:
            save_checkpoint(str(checkpoints / f'epoch_{epoch + 1}.pth'), net, opt, epoch)
        save_state(resume, epoch)
    history.append(row)
    report.update(epoch=epoch + 1, elapsed_seconds_this_run=time.perf_counter() - started,
                  peak_cuda_mb=torch.cuda.max_memory_allocated() / 2 ** 20)
    (out / 'training_metrics.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(row), flush=True)
report.update(training_complete=True)
(out / 'training_metrics.json').write_text(json.dumps(report, indent=2))
print('TRAINING_COMPLETE', flush=True)
