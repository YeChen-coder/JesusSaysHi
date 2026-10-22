"""Crops, mouth masks, landmarks and audio for the 24 selected Muse speech clips.

Adapted from the QinChe new-base prepare.py (same JPEG95 -> 110-point detector ->
compute_face_bbox -> 144 crop protocol). Differences: Jesus delivery manifest,
24 fps Muse sources, and no full-clip features (prepare_stream.py builds the
streaming windows the model is trained on).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
import torch
from face_utils import compute_face_bbox, crop_face, extract_inner
from dataset_mouth_roi import MouthRoiConfig, mouth_mask_from_landmarks

torch.set_num_threads(4)
cv2.setNumThreads(1)
os.chdir('/opt/FeatherTalk/data_utils')
sys.path.insert(0, os.getcwd())
from get_landmark import Landmark  # noqa: E402

root = Path('/work/data')
out = Path('/work/output')
source = Path('/sources')
root.mkdir(exist_ok=True)
out.mkdir(exist_ok=True)
det = Landmark()
delivery = json.loads((source / 'delivery_manifest.json').read_text(encoding='utf-8'))
selected = [x for x in delivery['items'] if x['selected'] and x['kind'] == 'speech']
assert len(selected) == 24 and all(x['ready_for_preprocessing'] for x in selected)
heldout = [x['id'] for x in selected if x['split'] == 'validation']
assert heldout == ['speech_12', 'speech_36'], heldout
rows = []
start = time.perf_counter()
framefile = root / 'frame.jpg'
for item in selected:
    file = source / item['file']
    assert hashlib.sha256(file.read_bytes()).hexdigest() == item['sha256'], item['id']
    name = item['id']
    dest = root / name
    dest.mkdir(exist_ok=True)
    normalized = root / 'normalized.mkv'
    probe = json.loads(subprocess.check_output(['/usr/bin/ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(file)]))
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    assert abs(float(video.get('start_time', 0)) - float(audio.get('start_time', 0))) <= .04
    subprocess.run(['/usr/bin/ffmpeg', '-v', 'error', '-y', '-i', str(file), '-map', '0:v:0', '-map', '0:a:0',
                    '-vf', 'fps=25', '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '18',
                    '-c:a', 'pcm_s16le', str(normalized)], check=True)
    cap = cv2.VideoCapture(str(normalized))
    crops, masks, points = [], [], []
    while True:
        ok, image = cap.read()
        if not ok:
            break
        assert cv2.imwrite(str(framefile), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        image = cv2.imread(str(framefile))
        pts, x, y = det.detect(str(framefile))
        pts = pts + np.array([x, y])
        bbox = compute_face_bbox(pts)
        assert min(bbox) >= 0 and bbox[2] <= image.shape[1] and bbox[3] <= image.shape[0]
        crops.append(extract_inner(crop_face(image, bbox)))
        masks.append(mouth_mask_from_landmarks(pts, MouthRoiConfig()).numpy().astype(np.uint8))
        points.append(pts)
    cap.release()
    n = len(crops)
    assert n > 200, (name, n)
    raw = subprocess.check_output(['/usr/bin/ffmpeg', '-v', 'error', '-i', str(normalized), '-vn', '-ac', '1',
                                   '-ar', '16000', '-f', 'f32le', '-'])
    wave = np.frombuffer(raw, dtype='<f4').copy()
    wave = np.pad(wave[:n * 640 + 80], (0, max(0, n * 640 + 80 - len(wave))))
    sf.write(dest / 'audio.wav', wave, 16000)
    for key, arr in [('crops', crops), ('masks', masks), ('landmarks', points)]:
        np.save(dest / (key + '.npy'), np.asarray(arr))
    row = dict(name=name, frames=n, split=item['split'], sha256=item['sha256'])
    rows.append(row)
    cv2.imwrite(str(out / (name + '_atlas.jpg')),
                np.concatenate([cv2.resize(crops[i], (144, 144)) for i in np.linspace(0, n - 1, 6).astype(int)], axis=1))
    print('PREPARED', json.dumps(row), flush=True)

# Inference reference: the approved still, scaled to 720 wide (independent of the idle videos).
neutral = source / 'reference.png'
assert hashlib.sha256(neutral.read_bytes()).hexdigest() == delivery['reference_sha256']
image = cv2.imread(str(neutral))
image = cv2.resize(image, (720, round(image.shape[0] * 720 / image.shape[1])), interpolation=cv2.INTER_AREA)
assert cv2.imwrite(str(root / 'base.jpg'), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
pts, x, y = det.detect(str(root / 'base.jpg'))
np.savetxt(root / 'base.lms', pts + np.array([x, y]), fmt='%d')
manifest = dict(character='Jesus', clips=rows, heldout=heldout, reference_is_inference_only=True,
                idle_videos_used_for_training=False, neutral_sha256=delivery['reference_sha256'],
                preparation_seconds=time.perf_counter() - start)
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print('PREPARE_COMPLETE', flush=True)
