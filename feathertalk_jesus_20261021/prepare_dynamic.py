"""Idle bases for inference only (never training): 25 fps frames, 110-point landmarks, bboxes, ping-pong loop.

Adapted from the QinChe prepare_dynamic.py; Muse idles are 240 frames at 24 fps,
which become 250 frames at 25 fps, so frame counts are read, not asserted.
"""
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from face_utils import compute_face_bbox
from native_face_match import NativeFaceMatch

torch.set_num_threads(4)
cv2.setNumThreads(1)
os.chdir('/opt/FeatherTalk/data_utils')
sys.path.insert(0, os.getcwd())
from get_landmark import Landmark  # noqa: E402

root = Path('/work/data')
sources = Path('/sources')
manifest = json.loads((sources / 'delivery_manifest.json').read_text(encoding='utf-8'))
selected = {x['id']: x for x in manifest['items'] if x['selected'] and x['kind'] == 'idle'}
assert set(selected) == {'idle_listening', 'idle_waiting'}
det = Landmark()
matcher = NativeFaceMatch()
rows = []
started = time.perf_counter()
for name, item in selected.items():
    source = sources / item['file']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == item['sha256']
    dest = root / name
    dest.mkdir(exist_ok=True)
    probe = json.loads(subprocess.check_output(['/usr/bin/ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)]))
    v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    w, h = v['width'], v['height']
    size = w * h * 3
    decoder = subprocess.Popen(['/usr/bin/ffmpeg', '-v', 'error', '-i', str(source), '-vf', 'fps=25', '-threads', '2',
                                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
    images, points, boxes = [], [], []
    with torch.inference_mode():
        while True:
            raw = decoder.stdout.read(size)
            if not raw:
                break
            image = np.frombuffer(raw, np.uint8).reshape(h, w, 3).copy()
            assert cv2.imwrite('/tmp/dynamic.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95])
            pts, x, y = det.detect('/tmp/dynamic.jpg')
            pts += np.array([x, y])
            box = tuple(map(int, compute_face_bbox(pts)))
            assert min(box) >= 0 and box[2] <= w and box[3] <= h
            matcher.prepare(image, pts, box)
            images.append(image)
            points.append(pts)
            boxes.append(box)
    assert decoder.wait() == 0 and len(images) >= 240
    n = len(images)
    indices = np.concatenate([np.arange(n), np.arange(n - 2, 0, -1)])
    assert np.abs(np.diff(np.r_[indices, indices[0]])).max() == 1
    for key, array in [('frames', images), ('landmarks', points), ('bboxes', boxes), ('source_indices', indices)]:
        np.save(dest / (key + '.npy'), np.asarray(array))
    row = {'id': name, 'source_sha256': item['sha256'], 'unique_frames': n, 'loop_frames': len(indices),
           'loop_seconds': len(indices) / 25, 'width': w, 'height': h, 'inference_only': True}
    rows.append(row)
    print('DYNAMIC_PREPARED', json.dumps(row), flush=True)
    del images, points, boxes
    gc.collect()
(root / 'dynamic_manifest.json').write_text(json.dumps({'candidates': rows, 'training_used_idle': False,
                                                         'seconds': time.perf_counter() - started}, indent=2))
print('DYNAMIC_PREPARE_COMPLETE', flush=True)
