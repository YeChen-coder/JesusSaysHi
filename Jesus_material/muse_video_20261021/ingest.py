"""Move one Muse download into native/<id>.mp4 unchanged and record it.

usage: python -I ingest.py <item_id> <downloaded_file> <muse_thread_url>
Refuses to overwrite an existing native file.
"""
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'generation_results_muse.json'


def probe(path):
    try:
        # No host ffprobe; use the project's FeatherTalk image, offline and read-only.
        out = subprocess.run(
            ['docker', 'run', '--rm', '--network', 'none', '-v', f'{path.resolve().parent}:/v:ro',
             'feathertalk-lab:local', '/usr/bin/ffprobe', f'/v/{path.name}',
             '-v', 'error', '-show_entries',
             'stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels:format=duration',
             '-of', 'json'], capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except (OSError, subprocess.CalledProcessError) as e:
        return {'error': str(e)}


def main(item_id, downloaded, thread_url):
    plan = json.loads((ROOT / 'generation_plan.json').read_text(encoding='utf-8'))
    item = next((i for i in plan['items'] if i['id'] == item_id), None)
    if item is None:  # prompt experiment, kept apart from the training set
        item = {'prompt_file': f'prompts/experiments/{item_id}.txt',
                'output_file': f'native/experiments/{item_id}.mp4'}
        assert (ROOT / item['prompt_file']).exists(), item['prompt_file']
    src = Path(downloaded)
    dst = ROOT / item['output_file']
    if dst.exists():
        sys.exit(f'{dst} already exists')
    src_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    size = src.stat().st_size
    dst.parent.mkdir(exist_ok=True)
    shutil.move(str(src), dst)
    dst_sha = hashlib.sha256(dst.read_bytes()).hexdigest()
    assert dst_sha == src_sha and dst.stat().st_size == size
    results = json.loads(RESULTS.read_text(encoding='utf-8')) if RESULTS.exists() else {'items': []}
    results['items'] = [r for r in results['items'] if r['id'] != item_id]
    results['items'].append({
        'id': item_id,
        'muse_thread': thread_url,
        'prompt_file': item['prompt_file'],
        'prompt_sent': (ROOT / item['prompt_file']).read_text(encoding='utf-8').strip(),
        'reference_sha256': plan['reference_sha256'],
        'downloaded_name': src.name,
        'native_file': item['output_file'],
        'bytes': size,
        'sha256': dst_sha,
        'probe': probe(dst),
        'ingested_at': datetime.datetime.now().isoformat(timespec='seconds'),
    })
    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results['items'][-1]['probe']), dst_sha)


if __name__ == '__main__':
    main(*sys.argv[1:4])
