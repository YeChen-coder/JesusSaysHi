"""Drive the running JesusSaysHi avatar like the voice loop does and measure it (host Python).

usage: python realtime_check.py <pcm24k_s16le_file> [ws://127.0.0.1:19388] [out.json]
1. a viewer connects (/view?protocol=2), a publisher (/publish?source=test)
   sends 8-byte timestamp + 24 kHz PCM16 in 100 ms packets at wall-clock pace;
2. records first-frame latency (first packet -> first frame), frame count vs
   audio duration, and that the avatar returns to idle after the audio;
3. a second utterance is interrupted halfway with {"type":"reset"} and must
   reach reset/idle, then a third short utterance must render again.
"""
import asyncio
import json
import struct
import sys
import time

import websockets

PACKET = 2400 * 2  # 100 ms of 24 kHz PCM16


async def run(pcm, url):
    events = []
    t0 = None

    async def viewer():
        async with websockets.connect(url + '/view?protocol=2', max_size=None) as ws:
            async for message in ws:
                if isinstance(message, str):
                    data = json.loads(message)
                    events.append((time.perf_counter(), data.get('type'), data.get('index')))

    task = asyncio.create_task(viewer())
    await asyncio.sleep(1)

    async def utterance(ws, audio, stop_after=None):
        nonlocal t0
        start = time.perf_counter()
        sent = 0
        for i in range(0, len(audio), PACKET):
            if stop_after is not None and time.perf_counter() - start >= stop_after:
                await ws.send(json.dumps({'type': 'reset'}))
                return start, sent
            await ws.send(struct.pack('<d', time.time()) + audio[i:i + PACKET])
            sent += 1
            target = start + sent * .1
            await asyncio.sleep(max(0, target - time.perf_counter()))
        return start, sent

    async def wait_for(kinds, after, timeout=5):
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            for t, kind, _ in events:
                if t >= after and kind in kinds:
                    return t
            await asyncio.sleep(.02)
        return None

    report = {}
    async with websockets.connect(url + '/publish?source=test', max_size=None) as ws:
        start, sent = await utterance(ws, pcm)
        end_sent = time.perf_counter()
        idle_at = await wait_for({'idle', 'reset'}, end_sent, 5)
        frames = [(t, i) for t, k, i in events if k == 'frame' and t >= start and (idle_at is None or t <= idle_at)]
        audio_s = len(pcm) / 48000
        report['utterance'] = {
            'audio_seconds': audio_s, 'packets': sent,
            'first_frame_ms': (frames[0][0] - start) * 1000 if frames else None,
            'frames': len(frames), 'expected_frames': round(audio_s * 25),
            'last_frame_after_audio_end_ms': (frames[-1][0] - end_sent) * 1000 if frames else None,
            'returned_to_idle_ms': (idle_at - end_sent) * 1000 if idle_at else None,
        }
        # frame pacing: gaps between consecutive frames while speaking
        gaps = [b[0] - a[0] for a, b in zip(frames, frames[1:])]
        if gaps:
            gaps.sort()
            report['utterance']['frame_gap_ms_p50'] = gaps[len(gaps) // 2] * 1000
            report['utterance']['frame_gap_ms_p95'] = gaps[int(len(gaps) * .95)] * 1000
        await asyncio.sleep(1)
        start2, _ = await utterance(ws, pcm, stop_after=2.0)
        reset_at = await wait_for({'reset', 'idle'}, start2 + 2.0, 3)
        report['interrupt'] = {'reset_after_ms': (reset_at - start2 - 2.0) * 1000 if reset_at else None}
        await asyncio.sleep(1)
        start3, _ = await utterance(ws, pcm[:48000 * 2])
        third = [t for t, k, _ in events if k == 'frame' and t >= start3]
        report['after_interrupt'] = {'frames': len(third), 'first_frame_ms': (third[0] - start3) * 1000 if third else None}
        await asyncio.sleep(1.5)
    task.cancel()
    return report


def main():
    pcm = open(sys.argv[1], 'rb').read()
    url = sys.argv[2] if len(sys.argv) > 2 else 'ws://127.0.0.1:19388'
    report = asyncio.run(run(pcm, url))
    text = json.dumps(report, indent=2)
    print(text)
    if len(sys.argv) > 3:
        open(sys.argv[3], 'w').write(text)


if __name__ == '__main__':
    main()
