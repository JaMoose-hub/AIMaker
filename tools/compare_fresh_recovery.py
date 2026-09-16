"""Same-source replay of a fresh, source-paired recovery seed; no live changes."""
import json
import cv2
from replay_motion_display import replay, ROOT
cv2.setNumThreads(2)
source=ROOT/'runs/acceptance/2026-09-16/pi-sift-speed-960.json'
report=json.loads(source.read_text(encoding='utf-8'))
out=ROOT/'runs/acceptance/2026-09-16/fresh-recovery-comparison.json'
if out.exists(): raise RuntimeError('Output exists')
results=[]
for case in report['cases']:
    modes={}; hashes=None
    for name, enabled in [('before',False),('after',True)]:
        result, hashes=replay(ROOT/'runs/acceptance/2026-09-13'/case['case'],
            case['modes']['after']['outputs'],150,hashes,fresh_recovery=enabled)
        modes[name]=result
        print(case['case'], name, json.dumps(result['summary']),flush=True)
    results.append(dict(case=case['case'],modes=modes))
out.write_text(json.dumps(dict(results=results,limitation='Cached seeds, simulated 150ms delay; no physical GPIO ground truth.'),indent=2),encoding='utf-8')
