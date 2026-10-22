"""prepare -> streaming windows -> train 150 epochs -> idle bases -> evaluate/export. Stages already done are skipped by the scripts' own caches/resume."""
import json, subprocess, sys, time, traceback
from pathlib import Path
out = Path('/work/output'); out.mkdir(exist_ok=True)
status = {'started_at_unix': time.time(), 'state': 'running'}
def record(**values):
    status.update(values); tmp = out / 'status.tmp'; tmp.write_text(json.dumps(status, indent=2)); tmp.replace(out / 'status.json')
stages = [('prepare', 'prepare'), ('stream', 'prepare_stream'), ('train', 'train_jesus'), ('dynamic', 'prepare_dynamic'), ('evaluate', 'evaluate')]
try:
    for stage, script in stages:
        if (stage == 'prepare' and Path('/work/data/manifest.json').exists()) or (stage == 'dynamic' and Path('/work/data/dynamic_manifest.json').exists()):
            continue
        record(stage=stage)
        with (out / (stage + '.log')).open('a') as log:
            p = subprocess.Popen(['python', '-u', f'/clean/{script}.py'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in p.stdout:
                log.write(line); log.flush(); print(line, end='', flush=True)
            if p.wait():
                raise RuntimeError('Failed stage: ' + stage)
    record(state='complete', completed_at_unix=time.time())
except Exception as error:
    record(state='failed', error=str(error)); traceback.print_exc(); sys.exit(1)
