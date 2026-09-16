"""Deterministic display-policy comparison; no camera/cloud/hardware access.

Baseline = prior all-or-none pin policy on the SAME accepted flow transforms.
Not a re-run of an old model, nor a physical pin-location accuracy benchmark.
"""
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.vision.motion_tracking import MotionTrack, transform


def main():
    cv2.setNumThreads(2)
    cases = []
    for device in ('raspberry-pi-5', 'hc-sr04', 'hw-123', 'mrd-tf240-8p-cs'):
        for fraction in (.25, .4, .55):
            gray = np.full((400, 640), 40, np.uint8)
            gray[100:260, 120:360] = cv2.GaussianBlur(
                np.random.default_rng(77).integers(15,245,(160,240),dtype=np.uint8),(3,3),0)
            quad = np.float32([[120,100],[360,100],[360,260],[120,260]])
            msg = {'frame_id':0, 'ts_ms':0, 'tracking':'locked', 'confidence':.9,
                   'video_size':[640,400], 'outline':quad.tolist(),
                   'pins':[{'id':'left','x':145.,'y':125.,'v':True}, {'id':'right','x':310.,'y':205.,'v':True}]}
            msg['board_id' if device == 'raspberry-pi-5' else 'component_id'] = device
            covered = gray.copy()
            end = 120+round(240*fraction)
            covered[100:260,120:end] = np.random.default_rng(357).integers(15,245,(160,end-120),dtype=np.uint8)
            track = MotionTrack()
            track.observe(msg, gray, 1)
            case = {'device':device, 'occluded_fraction':fraction, 'frames':20,
                    'old_policy_visible_right':0, 'new_policy_visible_right':0,
                    'hidden_left_emitted':0, 'lost':0}
            errors, timings = [], []
            for i in range(1,21):
                matrix = np.float64([[1,0,i],[0,1,i*.3],[0,0,1]])
                frame = cv2.warpPerspective(covered,matrix,(640,400),borderValue=40)
                start = time.perf_counter()
                output = track.update(frame,i,i*33)
                timings.append((time.perf_counter()-start)*1000)
                if output is None:
                    case['lost'] += 1
                    continue
                case['old_policy_visible_right'] += int(not track.flow.partial)
                pins = {p['id']:p for p in output['pins']}
                case['new_policy_visible_right'] += int('right' in pins)
                case['hidden_left_emitted'] += int('left' in pins)
                if 'right' in pins:
                    expected = transform([[310,205]],matrix)[0]
                    errors.append(float(np.linalg.norm(expected-[pins['right']['x'],pins['right']['y']])))
            case['known_transform_pin_error_p95_px'] = float(np.percentile(errors,95)) if errors else None
            case['update_p95_ms'] = float(np.percentile(timings,95))
            restored = track.update(cv2.warpPerspective(gray,matrix,(640,400),borderValue=40),21,693)
            case['restored_both_next_frame'] = restored is not None and len(restored['pins']) == 2
            cases.append(case)
    print(json.dumps({'scope':'synthetic_known_transform_policy_comparison_not_physical_acceptance',
                      'cases':cases}, indent=2))
    return 0 if all(c['new_policy_visible_right'] == 20 and c['hidden_left_emitted'] == 0
                    and c['lost'] == 0 and c['restored_both_next_frame'] for c in cases) else 1


if __name__ == '__main__':
    raise SystemExit(main())
