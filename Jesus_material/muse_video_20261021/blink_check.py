"""Count blinks in idle clips with the FeatherTalk 110-point detector (container).

Eye groups 66-77 / 78-89 of the 110-point layout; eye openness = height/width
of each group, averaged. A frame is closed when openness < 0.6 x the clip
median; a blink = a run of closed frames. Normal resting rate is ~15-20/min.
usage: python /w/blink_check.py native/x.mp4 [...]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, '/opt/FeatherTalk')
os.chdir('/opt/FeatherTalk/data_utils')
sys.path.insert(0, os.getcwd())
from get_landmark import Landmark  # noqa: E402

det = Landmark()
out = {}
for rel in sys.argv[1:]:
    path = Path('/w') / rel
    cap = cv2.VideoCapture(str(path))
    eye = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        cv2.imwrite('/tmp/b.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        pts, x, y = det.detect('/tmp/b.jpg')

        def ratio(g):
            p = pts[g]
            return (p[:, 1].max() - p[:, 1].min()) / (p[:, 0].max() - p[:, 0].min())
        eye.append((ratio(list(range(66, 78))) + ratio(list(range(78, 90)))) / 2)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    e = np.asarray(eye)
    closed = e < np.median(e) * .6
    starts = np.flatnonzero(closed[1:] & ~closed[:-1]) + 1
    if closed[0]:
        starts = np.r_[0, starts]
    seconds = len(e) / fps
    out[rel] = {'blinks': int(len(starts)), 'blink_times_s': (starts / fps).round(2).tolist(),
                'per_minute': round(len(starts) / seconds * 60, 1), 'closed_frames': int(closed.sum())}
    print(rel, json.dumps(out[rel]), flush=True)
