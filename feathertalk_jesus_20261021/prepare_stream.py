"""Per-frame streaming audio windows, computed exactly as the realtime session does.

For every frame i and audio_lookahead L in AUDIO_LOOKAHEADS the encoder sees
PCM [max(0, i-100) frames .. end of frame i+L + 80 samples], then the window is
masked after i+2 (jesus_stream.mask_future). L=2 is what the last frame of
each realtime push sees; L=4 covers frames rendered earlier in a 100 ms push.
Rows i+3..i+9 are always zero, so only rows i-10..i+2 (13) are stored, fp16.
"""
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from data_utils.feather_hubert.feather_hubert import load_feather_hubert, get_feather_hubert_from_16k_speech

from jesus_stream import AUDIO_HALF_WINDOW, LOOKAHEAD, encoder_span, window_from_features

AUDIO_LOOKAHEADS = (2, 4)
ROWS = AUDIO_HALF_WINDOW + LOOKAHEAD + 1  # 13

torch.set_num_threads(4)
device = torch.device('cuda')
encoder = load_feather_hubert('/opt/FeatherTalk/feather_hubert.pth', device)
root = Path('/work/data')
manifest = json.loads((root / 'manifest.json').read_text())


@torch.inference_mode()
def encode(samples):
    hidden = get_feather_hubert_from_16k_speech(samples, encoder, device)
    return hidden[:(len(hidden) // 2) * 2].numpy().reshape(-1, 2, 1024)


started = time.perf_counter()
for row in manifest['clips']:
    dest = root / row['name']
    target = dest / 'stream_windows.npy'
    if target.exists() and np.load(target, mmap_mode='r').shape == (len(AUDIO_LOOKAHEADS), row['frames'], ROWS, 2, 1024):
        print('CACHED', row['name'], flush=True)
        continue
    wave, sr = sf.read(dest / 'audio.wav', dtype='float32')
    assert sr == 16000
    n = row['frames']
    out = np.zeros((len(AUDIO_LOOKAHEADS), n, ROWS, 2, 1024), np.float16)
    for v, audio_lookahead in enumerate(AUDIO_LOOKAHEADS):
        for i in range(n):
            left, a, b = encoder_span(i, 0, audio_lookahead)
            pcm = wave[a:b]
            if len(pcm) < b - a:  # end of utterance: the runtime's final flush pads with silence
                pcm = np.pad(pcm, (0, b - a - len(pcm)))
            window = window_from_features(encode(pcm), i, left)
            assert not window[ROWS:].any()
            out[v, i] = window[:ROWS].astype(np.float16)
    np.save(target, out)
    print('STREAM_WINDOWS', row['name'], n, f'{time.perf_counter() - started:.1f}s', flush=True)
(root / 'stream_manifest.json').write_text(json.dumps({
    'audio_lookaheads': AUDIO_LOOKAHEADS, 'runtime_lookahead_frames': LOOKAHEAD, 'rows_stored': ROWS,
    'history_frames': 100, 'seconds': time.perf_counter() - started}, indent=2))
print('STREAM_COMPLETE', flush=True)
