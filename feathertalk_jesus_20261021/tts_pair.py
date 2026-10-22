"""Same OpenAI voice ('ash', speed .85 like the live app), one Chinese and one English passage, 24 kHz PCM16.

Run from the JesusSaysHi root with the project venv: .venv/Scripts/python.exe feathertalk_jesus_20261021/tts_pair.py
Writes feathertalk_jesus_20261021/output/tts_{zh,en}_24k.pcm and .wav (16 kHz copy for offline export).
"""
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import load_settings  # noqa: E402
from openai import OpenAI  # noqa: E402

load_settings()
client = OpenAI()
out = Path(__file__).resolve().parent / 'output'
TEXT = {
    'zh': '我明白你现在心里有些乱。你不用急着做决定，先把今天发生的事情慢慢告诉我，我们一起看看哪一步最重要，然后一点一点往前走。',
    'en': 'I understand that your heart feels unsettled right now. You do not need to decide anything yet. Tell me slowly what happened today, and we will look together at which step matters most.',
}
for lang, text in TEXT.items():
    pcm = client.audio.speech.create(model='gpt-4o-mini-tts', voice='ash', input=text, speed=.85,
                                     response_format='pcm').content
    (out / f'tts_{lang}_24k.pcm').write_bytes(pcm)
    samples = np.frombuffer(pcm, np.int16).astype(np.float32)
    idx = np.arange(0, len(samples), 1.5)
    s16 = np.interp(idx, np.arange(len(samples)), samples).astype(np.int16)
    with wave.open(str(out / f'tts_{lang}_16k.wav'), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(s16.tobytes())
    print(lang, f'{len(samples) / 24000:.1f}s')
