"""Prepare an extra idle base (e.g. a slowed copy) for inference: same steps as prepare_dynamic.py.

usage (container): python /clean/prepare_idle_variant.py /work/output/idle_waiting_slow1.3.mp4 idle_waiting_slow13
Input must already be 25 fps. Writes data/<name>/{frames,landmarks,bboxes,source_indices}.npy
(ping-pong loop) and data/<name>/info.json incl. the most open-eyed frame near the middle,
used as the fixed model reference.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from face_utils import compute_face_bbox
from native_face_match import NativeFaceMatch

src, name = Path(sys.argv[1]), sys.argv[2]
os.chdir('/opt/FeatherTalk/data_utils')
sys.path.insert(0, os.getcwd())
from get_landmark import Landmark  # noqa: E402

probe = json.loads(subprocess.check_output(['/usr/bin/ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(src)]))
v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
assert v['r_frame_rate'] == '25/1', v['r_frame_rate']
w, h = v['width'], v['height']
dec = subprocess.Popen(['/usr/bin/ffmpeg', '-v', 'error', '-i', str(src), '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                       stdout=subprocess.PIPE)
det, matcher = Landmark(), NativeFaceMatch()
images, points, boxes = [], [], []
while True:
    raw = dec.stdout.read(w * h * 3)
    if not raw:
        break
    image = np.frombuffer(raw, np.uint8).reshape(h, w, 3).copy()
    cv2.imwrite('/tmp/v.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    pts, x, y = det.detect('/tmp/v.jpg')
    pts += np.array([x, y])
    box = tuple(map(int, compute_face_bbox(pts)))
    matcher.prepare(image, pts, box)
    images.append(image)
    points.append(pts)
    boxes.append(box)
assert dec.wait() == 0
n = len(images)
P = np.asarray(points)


def ratio(g):
    p = P[:, g]
    return (p[..., 1].max(1) - p[..., 1].min(1)) / (p[..., 0].max(1) - p[..., 0].min(1))


eye = (ratio(list(range(66, 78))) + ratio(list(range(78, 90)))) / 2
mid = slice(n // 3, 2 * n // 3)
reference = int(np.arange(n)[mid][np.argmax(eye[mid])])
dst = Path('/work/data') / name
dst.mkdir(exist_ok=True)
indices = np.concatenate([np.arange(n), np.arange(n - 2, 0, -1)])
for key, arr in [('frames', images), ('landmarks', points), ('bboxes', boxes), ('source_indices', indices)]:
    np.save(dst / f'{key}.npy', np.asarray(arr))
info = {'source': str(src), 'unique_frames': n, 'loop_frames': int(len(indices)), 'loop_seconds': len(indices) / 25,
        'reference_frame': reference}
(dst / 'info.json').write_text(json.dumps(info, indent=2))
print('IDLE_VARIANT', name, json.dumps(info), flush=True)
