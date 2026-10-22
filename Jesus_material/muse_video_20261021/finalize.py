"""Write delivery_manifest.json from the plan, Muse results, auto QC and manual review.

usage: python -I finalize.py
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Visual notes from the per-second face sheets (review/faces_A.jpg, faces_B.jpg);
# these clips are usable but the user should judge them.
IDENTITY_NOTES = {
    'speech_05': 'hair renders lighter/warmer brown than the reference',
    'speech_27': 'hair renders lighter/redder brown, warmer overall colour',
    'speech_29': 'hair renders lighter brown',
    'speech_35': 'beard renders noticeably greyer (looks older)',
}


def load(name, default):
    p = ROOT / name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def main():
    plan = load('generation_plan.json', {})
    results = {r['id']: r for r in load('generation_results_muse.json', {'items': []})['items']}
    qc = load('review/qc.json', {})
    manual = load('review/manual_review.json', {})
    rows = []
    for item in plan['items']:
        path = ROOT / item['output_file']
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        res = results[item['id']]
        assert res['sha256'] == sha, item['id']
        q = qc.get(item['id'], {})
        m = manual.get(item['id'])
        auto = q.get('auto_pass', False)
        accepted = auto or (m or {}).get('decision') == 'accept'
        rows.append({
            'id': item['id'], 'kind': item['kind'], 'split': item['split'], 'dialogue': item['dialogue'],
            'file': item['output_file'], 'sha256': sha, 'bytes': path.stat().st_size,
            'muse_thread': res['muse_thread'], 'prompt_file': item['prompt_file'],
            'auto_qc': {'pass': auto, 'problems': q.get('problems'), 'head': q.get('head'),
                        'transcript': q.get('transcript'), 'voiced_s': q.get('voiced_s')},
            'manual': m, 'identity_note': IDENTITY_NOTES.get(item['id']),
            'selected': accepted,
            'ready_for_preprocessing': accepted and item['kind'] == 'speech',
        })
    speech = [r for r in rows if r['kind'] == 'speech']
    manifest = {
        'batch': 'muse_video_20261021', 'plan_version': plan['version'],
        'reference': plan['reference'], 'reference_sha256': plan['reference_sha256'],
        'counts': {
            'speech_selected': sum(r['selected'] for r in speech),
            'train': sum(r['selected'] and r['split'] == 'train' for r in speech),
            'validation': sum(r['selected'] and r['split'] == 'validation' for r in speech),
            'idle_selected': sum(r['selected'] for r in rows if r['kind'] == 'idle'),
            'auto_pass': sum(r['auto_qc']['pass'] for r in rows),
            'manual_accept_marginal': sum(bool(r['manual']) and not r['auto_qc']['pass'] for r in rows),
        },
        'not_in_set': ['native/v1_pilot/*', 'native/experiments/*', 'native/rejected/*'],
        'caveats': [
            'auto QC = head motion + Whisper-tiny wording; lip sync was not measured, only viewed on sheets',
            'identity notes are from 1 fps face sheets and need the user\'s judgement',
            'idle clips are inference bases only, not training data',
        ],
        'items': rows,
    }
    (ROOT / 'delivery_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest['counts']))
    for r in rows:
        if not r['selected'] or r['identity_note'] or r['manual']:
            print(r['id'], 'selected' if r['selected'] else 'NOT SELECTED', '|', r['identity_note'] or '', '|', (r['manual'] or {}).get('note', '')[:60])


if __name__ == '__main__':
    main()
