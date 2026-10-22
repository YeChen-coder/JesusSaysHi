"""Streaming audio windows with a hard 2-frame (80 ms) lookahead, shared by training and runtime.

The released FeatherTalk visual model reads a 20-frame audio window centred on
the frame (index-10 .. index+9). The QinChe 'fast' runtime zero-pads whatever
has not arrived, while the model was trained on full-clip features, so training
and inference disagreed. Here both sides use the same rule:

* the audio encoder only sees PCM up to the end of frame index+LOOKAHEAD
  (plus the 80-sample tail the runtime already waits for), with at most
  HISTORY frames of past audio, exactly like the realtime session;
* window rows after index+LOOKAHEAD are always zero, even when more audio has
  arrived, so a frame rendered early in a batch looks like one rendered late.

User requirement (2026-10-21): look-ahead audio buffer at most 100 ms.
LOOKAHEAD = 2 frames = 80 ms at 25 fps.
"""
import numpy as np

from face_utils import gather_audio_window, AUDIO_HALF_WINDOW

FPS = 25
SAMPLES_PER_FRAME = 640  # 16 kHz / 25 fps
TAIL_SAMPLES = 80
LOOKAHEAD = 2
HISTORY = 100  # frames of past audio given to the encoder (4 s), as in the runtime


def mask_future(window, lookahead=LOOKAHEAD):
    """Zero window rows later than index+lookahead. window: [20, 2, 1024]."""
    window = np.array(window, copy=True)
    window[AUDIO_HALF_WINDOW + lookahead + 1:] = 0
    return window


def encoder_span(index, start=0, audio_lookahead=LOOKAHEAD, history=HISTORY):
    """PCM sample range [a, b) the encoder sees when frame `index` is rendered.

    `start` is the first frame of the utterance (nothing before it exists).
    `audio_lookahead` >= LOOKAHEAD: frames rendered earlier in a push batch
    were encoded with a little more future audio than the last one.
    """
    left = max(start, index - history)
    end = (index + audio_lookahead + 1) * SAMPLES_PER_FRAME + TAIL_SAMPLES
    return left, left * SAMPLES_PER_FRAME, end


def window_from_features(features, index, left):
    """Masked 20-frame window for `index` from features that start at frame `left`."""
    return mask_future(gather_audio_window(features, index - left).numpy())


class Session:
    """Realtime session: identical maths to the runtime, LOOKAHEAD fixed at 2 frames."""

    def __init__(self, engine):
        self.engine = engine
        self.pcm = np.empty(0, dtype=np.float32)
        self.next_frame = 0
        self.rows = []

    def push(self, samples, final=False):
        self.pcm = np.concatenate([self.pcm, np.asarray(samples, dtype=np.float32)])
        total = max(0, (len(self.pcm) - TAIL_SAMPLES) // SAMPLES_PER_FRAME)
        if final:
            total = len(self.pcm) // SAMPLES_PER_FRAME
            pad = max(0, total * SAMPLES_PER_FRAME + TAIL_SAMPLES - len(self.pcm))
            self.pcm = np.pad(self.pcm, (0, pad))
        eligible = total if final else max(0, total - LOOKAHEAD)
        if eligible <= self.next_frame:
            return []
        left = max(0, self.next_frame - HISTORY)
        features = self.engine.encode(self.pcm[left * SAMPLES_PER_FRAME:])
        frames = []
        for index in range(self.next_frame, eligible):
            window = window_from_features(features, index, left)
            image, prediction = self.engine.render(window)
            self.engine.sync()
            self.rows.append({'frame': index, 'received_s': len(self.pcm) / 16000, 'eof_flush': final})
            frames.append((index, image, prediction))
        self.next_frame = eligible
        return frames
