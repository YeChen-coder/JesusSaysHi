"""Re-time the idle_waiting loop so he blinks every ~2-4 s instead of every ~1.4 s (host Python).

The native runtime plays idle frames by an index timeline (source_indices), so
the blink rate can be set without regenerating video. The walk moves exactly
one frame per step (no jump cuts), stays in frames LO..HI, crosses a blink
span only when the next blink is due, and otherwise turns around at the open
frame before it. The loop is the walk plus its mirror (ping-pong), ending
mid-run far from a blink so the mirrored half keeps the spacing.
Writes data/idle_waiting_slowblink/ (frames/landmarks/bboxes shared by copy).
usage: python slow_blink_timeline.py
"""
import json
import random
import shutil
from pathlib import Path

import numpy as np

root = Path(__file__).resolve().parent / 'data'
src = root / 'idle_waiting'
dst = root / 'idle_waiting_slowblink'
LO, HI = 14, 178                                # open run 14-47 .. open run 152-178
BLINKS = [(48, 56), (83, 96), (147, 151)]       # spans inside LO..HI (5-14 frames)
HALF = 300                                      # 12 s walk -> 24 s loop
rng = random.Random(7)


def blink_at(f):
    return next((b for b in BLINKS if b[0] <= f <= b[1]), None)


pos, step = 120, 1
since, due = 0, 35  # first blink soon after the loop start
path = [pos]
while len(path) < HALF or blink_at(pos) or since < 50 or any(abs(pos - b[0]) < 6 or abs(pos - b[1]) < 6 for b in BLINKS):
    nxt = pos + step
    if nxt < LO or nxt > HI:
        step = -step
        nxt = pos + step
    b = blink_at(nxt)
    if b and not blink_at(pos):  # about to enter a blink span
        if since >= due:
            since, due = -(b[1] - b[0] + 1), rng.randint(55, 95)  # 2.2-3.8 s
        else:
            step = -step
            nxt = pos + step
    pos = nxt
    since += 1
    path.append(pos)
    assert len(path) < 2000
loop = np.array(path + path[-2:0:-1])
assert np.abs(np.diff(np.r_[loop, loop[0]])).max() == 1
dst.mkdir(exist_ok=True)
for name in ['frames.npy', 'landmarks.npy', 'bboxes.npy']:
    if not (dst / name).exists():
        shutil.copy2(src / name, dst / name)
np.save(dst / 'source_indices.npy', loop)
starts = [i for i in range(1, len(loop)) if blink_at(loop[i]) and not blink_at(loop[i - 1])]
info = {'loop_frames': int(len(loop)), 'seconds': len(loop) / 25, 'blinks': len(starts),
        'per_minute': round(len(starts) / (len(loop) / 25) * 60, 1),
        'blink_times_s': [round(s / 25, 2) for s in starts], 'range': [LO, HI], 'blink_spans': BLINKS}
(dst / 'timeline.json').write_text(json.dumps(info, indent=2))
print(json.dumps(info))
