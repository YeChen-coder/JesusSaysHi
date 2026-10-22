"""Automatic QC for native clips (runs in feathertalk-lab:local, offline).

Per clip: container metadata, head motion (head_motion.py limits), and for
speech the local Whisper-tiny wording check over the full clip plus the last
3 s, which is where Muse used to repeat the final clause.
Writes review/qc.json; prints one verdict line per clip. Visual identity and
lip sync still need a human look/listen.

usage (container): python /w/check.py <id> [<id> ...]
mounts: /w = batch dir, /opt/FeatherTalk = upstream (ro), /whisper = Whisper-tiny cache (ro)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, '/w')
import head_motion  # noqa: E402  (chdirs into the FeatherTalk tree)

ROOT = Path('/w')


def words(s):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", s.lower())


def wer(ref, hyp):
    prev = list(range(len(hyp) + 1))
    for i, x in enumerate(ref, 1):
        cur = [i]
        for j, y in enumerate(hyp, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1] / max(1, len(ref))


class Asr:
    def __init__(self):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        self.p = WhisperProcessor.from_pretrained('/whisper', local_files_only=True)
        self.m = WhisperForConditionalGeneration.from_pretrained('/whisper', local_files_only=True).eval()

    def __call__(self, audio):
        i = self.p(audio, sampling_rate=16000, return_tensors='pt', return_attention_mask=True)
        with self.torch.inference_mode():
            o = self.m.generate(i.input_features, attention_mask=i.attention_mask, max_new_tokens=128,
                                forced_decoder_ids=self.p.get_decoder_prompt_ids(language='en', task='transcribe'))
        return self.p.batch_decode(o, skip_special_tokens=True)[0].strip()


def probe(path):
    out = subprocess.run(['/usr/bin/ffprobe', '-v', 'error', '-show_entries',
                          'stream=codec_type,width,height,r_frame_rate,nb_frames:format=duration', '-of', 'json', str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def main(ids):
    plan = {i['id']: i for i in json.loads((ROOT / 'generation_plan.json').read_text())['items']}
    det = head_motion.SCRFD('./scrfd_2.5g_kps.onnx', confThreshold=0.1, nmsThreshold=0.5)
    asr = None
    qc_path = ROOT / 'review' / 'qc.json'
    qc = json.loads(qc_path.read_text()) if qc_path.exists() else {}
    for item_id in ids:
        item = plan[item_id]
        path = ROOT / item['output_file']
        meta = probe(path)
        v = next(s for s in meta['streams'] if s['codec_type'] == 'video')
        problems = []
        if (v['width'], v['height']) != (768, 1152):
            problems.append(f"size {v['width']}x{v['height']}")
        if not any(s['codec_type'] == 'audio' for s in meta['streams']):
            problems.append('no audio')
        head = head_motion.measure(path, det)
        if not head['pass']:
            problems.append('head ' + ','.join(head['fails']) if head['fails'] else 'face missing in some frames')
        row = {'id': item_id, 'size': [v['width'], v['height']], 'duration': float(meta['format']['duration']),
               'head': head['spread_p5_p95']}
        subprocess.run(['/usr/bin/ffmpeg', '-v', 'error', '-y', '-i', str(path), '-ac', '1', '-ar', '16000', '/tmp/a.wav'],
                       check=True)
        audio, sr = sf.read('/tmp/a.wav', dtype='float32')
        rms = [float(np.sqrt(np.mean(audio[i:i + sr // 4] ** 2))) for i in range(0, len(audio), sr // 4)]
        voiced = [i / 4 for i, r in enumerate(rms) if r > 0.01]
        row['voiced_s'] = [voiced[0], voiced[-1] + 0.25] if voiced else None
        if item['kind'] == 'speech':
            asr = asr or Asr()
            full = asr(audio)
            tail = asr(audio[-3 * sr:])
            ref = words(item['dialogue'])
            hyp = words(full)
            row.update(transcript=full, tail_transcript=tail, wer=round(wer(ref, hyp), 3))
            # Repetition: transcript clearly longer than the line, or the tail
            # text appears twice in the full transcript.
            tail_w = ' '.join(words(tail)[-4:])
            if len(hyp) > len(ref) + 3 or (tail_w and ' '.join(hyp).count(tail_w) > 1):
                problems.append('repeated words')
            if row['wer'] > 0.25:
                problems.append(f"wording wer {row['wer']}")
        else:
            if voiced and voiced[-1] - voiced[0] > 1.0 and max(rms) > 0.05:
                problems.append('idle has loud audio (speech?)')
        row['problems'] = problems
        row['auto_pass'] = not problems
        qc[item_id] = row
        print(item_id, 'PASS' if not problems else 'FAIL ' + '; '.join(problems), row['head'], row.get('transcript', ''), flush=True)
    qc_path.write_text(json.dumps(qc, indent=2))


if __name__ == '__main__':
    main(sys.argv[1:])
