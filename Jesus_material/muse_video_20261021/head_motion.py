"""Per-frame head pose stability for native clips (runs in feathertalk-lab:local).

Uses the FeatherTalk SCRFD detector's 5 keypoints (eyes, nose, mouth corners).
All values are relative to the clip's own median pose and normalised by the
inter-ocular distance, so they do not depend on resolution.

usage (container): python /w/head_motion.py [native/x.mp4 ...]   (default: every mp4 under native/)
writes review/head_motion.json and prints one line per clip.
"""
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path('/w')
sys.path.insert(0, '/opt/FeatherTalk')
os.chdir('/opt/FeatherTalk/data_utils')
sys.path.insert(0, os.getcwd())
from detect_face import SCRFD  # noqa: E402

# Nose tip sits roughly 0.55 inter-ocular distances in front of the eye plane,
# so a horizontal nose offset of d (in eye distances) is about asin(d/0.55).
NOSE_DEPTH = 0.55

# Acceptance limits for lip-sync training material (p95-p5 spread within a clip).
# Set 2026-10-21 from the prompt test: B_still_photo (visually steady, frontal) measured
# yaw 5.2 / pitch 7.9 / roll 11.7 / shift 0.21 / scale 2.4; the rejected pilot
# speech_03 measured yaw 50 / scale 17. Jitter std is ~1 deg, so these are real motion.
# Pitch (nose-to-eye height) also moves with blinks and brow/eye expression while
# speaking: v2 speech_02 read 12 deg while its 0.5 s head sheet is visibly frontal
# and steady, so pitch/yaw are looser; shift and scale are the robust signals.
LIMITS = {'yaw_deg': 10.0, 'pitch_deg': 14.0, 'roll_deg': 12.0, 'shift_eye': 0.30, 'scale_pct': 5.0}


def measure(path, det):
    cap = cv2.VideoCapture(str(path))
    rows = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        _, indices, kps = det.detect(frame)
        if len(indices) == 0:
            rows.append(None)
            continue
        k = kps[indices[0]].reshape(5, 2).astype(np.float64)
        le, re_, nose = k[0], k[1], k[2]
        mid = (le + re_) / 2
        eye = np.linalg.norm(re_ - le)
        rows.append({
            'mid': mid, 'eye': eye,
            'roll': math.degrees(math.atan2(re_[1] - le[1], re_[0] - le[0])),
            'nx': (nose[0] - mid[0]) / eye, 'ny': (nose[1] - mid[1]) / eye,
        })
    cap.release()
    good = [r for r in rows if r]
    mid = np.array([r['mid'] for r in good])
    eye = np.array([r['eye'] for r in good])
    ref_eye = np.median(eye)
    ref_mid = np.median(mid, axis=0)
    nx = np.array([r['nx'] for r in good])
    ny = np.array([r['ny'] for r in good])
    series = {
        'yaw_deg': np.degrees(np.arcsin(np.clip((nx - np.median(nx)) / NOSE_DEPTH, -1, 1))),
        'pitch_deg': np.degrees(np.arcsin(np.clip((ny - np.median(ny)) / NOSE_DEPTH, -1, 1))),
        'roll_deg': np.array([r['roll'] for r in good]) - np.median([r['roll'] for r in good]),
        'shift_eye': np.linalg.norm(mid - ref_mid, axis=1) / ref_eye,
        'scale_pct': (eye / ref_eye - 1) * 100,
    }
    # Raw series include detector jitter (eye keypoints jump on blinks at ~55px
    # eye distance); limits apply to a 9-frame (0.375s) running median, which
    # keeps real head turns and drops single-blink spikes. noise = raw - smooth.
    noise = {}
    for key in list(series):
        raw = series[key]
        pad = np.pad(raw, 4, mode='edge')
        smooth = np.array([np.median(pad[i:i + 9]) for i in range(len(raw))])
        noise[key] = round(float(np.std(raw - smooth)), 2)
        series[key] = smooth
    spread = {}
    for key, v in series.items():
        if key == 'shift_eye':
            spread[key] = float(np.percentile(v, 95))
        else:
            spread[key] = float(np.percentile(v, 95) - np.percentile(v, 5))
    fails = [k for k, lim in LIMITS.items() if spread[k] > lim]
    return {
        'frames': len(rows), 'detected': len(good), 'eye_distance_px': float(ref_eye),
        'spread_p5_p95': {k: round(v, 2) for k, v in spread.items()},
        'max_abs': {k: round(float(np.max(np.abs(v))), 2) for k, v in series.items()},
        'jitter_std': noise, 'limits': LIMITS, 'fails': fails, 'pass': not fails and len(good) == len(rows),
    }


def main(ids):
    det = SCRFD('./scrfd_2.5g_kps.onnx', confThreshold=0.1, nmsThreshold=0.5)
    files = [ROOT / i for i in ids] if ids else sorted((ROOT / 'native').rglob('*.mp4'))
    out_path = ROOT / 'review' / 'head_motion.json'
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    for f in files:
        out[f.stem] = measure(f, det)
        r = out[f.stem]
        print(f.stem, 'PASS' if r['pass'] else 'FAIL ' + ','.join(r['fails']), r['spread_p5_p95'], flush=True)
    out_path.write_text(json.dumps(out, indent=2))


if __name__ == '__main__':
    main(sys.argv[1:])
