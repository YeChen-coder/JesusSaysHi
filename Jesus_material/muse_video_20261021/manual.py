"""Record a human/agent visual decision for a clip: python -I manual.py <id> <accept|reject> <note>"""
import datetime, json, sys
from pathlib import Path
p = Path(__file__).resolve().parent / 'review' / 'manual_review.json'
d = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
d[sys.argv[1]] = {'decision': sys.argv[2], 'note': sys.argv[3], 'by': 'Claude (sheet review), pending user review',
                  'at': datetime.datetime.now().isoformat(timespec='seconds')}
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
print(sys.argv[1], sys.argv[2])
