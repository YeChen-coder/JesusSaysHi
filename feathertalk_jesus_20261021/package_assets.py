"""Build the JesusSaysHi avatar asset folder for the selected epoch and idle base.

usage (container): python /clean/package_assets.py <epoch> <idle_id>
writes /package/ (mounted to JesusSaysHi/avatar_assets/jesus_20261021):
  checkpoints/epoch_<N>.pth, data/base.jpg, data/base.lms,
  data/loop_base/{frames,landmarks,bboxes,source_indices}.npy, manifest.json,
  idle.mp4 (BT.709 limited, re-encoded from the same RGB frames as the QinChe
  colour fix), poster.jpg, and release.json with every SHA256.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

epoch, idle = int(sys.argv[1]), sys.argv[2]
root = Path('/work/data')
pkg = Path('/package')
src_ck = Path('/work/checkpoints') / f'epoch_{epoch}.pth'
(pkg / 'checkpoints').mkdir(parents=True, exist_ok=True)
loop = pkg / 'data' / 'loop_base'
loop.mkdir(parents=True, exist_ok=True)
shutil.copy2(src_ck, pkg / 'checkpoints' / src_ck.name)
# The avatar runtime loads the audio encoder from /work; same file the model was trained with.
shutil.copy2('/opt/FeatherTalk/feather_hubert.pth', pkg / 'feather_hubert.pth')
for name in ['base.jpg', 'base.lms']:
    shutil.copy2(root / name, pkg / 'data' / name)
d = root / idle
for name in ['frames.npy', 'landmarks.npy', 'bboxes.npy', 'source_indices.npy']:
    shutil.copy2(d / name, loop / name)
frames = np.load(loop / 'frames.npy', mmap_mode='r')
indices = np.load(loop / 'source_indices.npy')
h, w = frames.shape[1:3]
enc = subprocess.Popen(['/usr/bin/ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
                        '-r', '25', '-i', '-',
                        '-vf', 'scale=in_range=full:out_range=limited:out_color_matrix=bt709,format=yuv420p',
                        '-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-threads', '2', '-g', '25',
                        '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                        '-an', '-movflags', '+faststart', str(loop / 'idle.mp4')], stdin=subprocess.PIPE)
for i in indices:
    enc.stdin.write(np.ascontiguousarray(frames[i][..., ::-1]).tobytes())
enc.stdin.close()
assert enc.wait() == 0
cv2.imwrite(str(loop / 'poster.jpg'), np.asarray(frames[indices[0]]), [cv2.IMWRITE_JPEG_QUALITY, 92])
(loop / 'manifest.json').write_text(json.dumps({
    'frames': int(len(indices)), 'unique_frames': int(len(frames)), 'loop_mode': 'pingpong', 'source': idle,
    'width': int(w), 'height': int(h), 'fps': 25, 'color_space': 'bt709'}, indent=2))


def sha(path):
    hasher = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


files = {str(p.relative_to(pkg)).replace('\\', '/'): sha(p) for p in sorted(pkg.rglob('*'))
         if p.is_file() and p.name != 'release.json'}
(pkg / 'release.json').write_text(json.dumps({'character': 'jesus', 'epoch': epoch, 'idle': idle,
                                              'runtime_mode': 'stream80', 'files': files}, indent=2))
print('PACKAGED', epoch, idle, json.dumps(files, indent=1), flush=True)
