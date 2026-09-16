"""Paced, same-source Pi replay. No live camera or model changes."""
import json
from pathlib import Path
import cv2
from replay_motion_display import replay, ROOT

cv2.setNumThreads(2)
report=json.loads((ROOT/'runs/acceptance/2026-09-16/pi-sift-speed-960.json').read_text(encoding='utf-8'))
case=next(c for c in report['cases'] if c['case']=='S05-Pi-handheld-01')
out=ROOT/'runs/acceptance/2026-09-16/background-recovery-comparison.json'
if out.exists(): raise RuntimeError('Output exists')
results={}
hashes=None
for name, enabled in [('before',False),('after',True)]:
    result, hashes=replay(ROOT/'runs/acceptance/2026-09-13'/case['case'],
                          case['modes']['after']['outputs'],150,hashes,background=enabled,paced=True)
    results[name]=result
    print(name,json.dumps(result['summary']),flush=True)
out.write_text(json.dumps(dict(case=case['case'],results=results,
    limitation='Paced single-object replay with cached detector seeds; not physical GPIO accuracy or full-app contention.'),indent=2),encoding='utf-8')
