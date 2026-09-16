"""Offline four-object cost/quality replay; never alters the live camera."""
import argparse
import base64
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.motion_worker import tracking_gray
from app.vision.motion_tracking import MotionTrack, transform, warm_motion_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--unlimited-search', action='store_true', help='Omit worker per-frame scheduling for comparison.')
    args = parser.parse_args()
    packet = json.loads(args.fixture.read_text(encoding='utf-8'))
    image = cv2.imdecode(np.frombuffer(base64.b64decode(packet['image'].split(',')[1]), np.uint8), cv2.IMREAD_COLOR)
    poses = [packet['detection'], *packet['components']]
    assert len(poses) == 4 and all(p['tracking'] == 'locked' and p['frame_id'] == packet['frame_id'] for p in poses)
    gray, scale = tracking_gray(image)
    warm_started = time.perf_counter()
    warm_motion_runtime()
    warmup_ms = (time.perf_counter()-warm_started)*1000
    results = {}
    for name, fraction, targets in [('clear', 0, range(4)), ('partial_all', .4, range(4)),
                                    ('covered_pi', 1., [0]), ('covered_all', 1., range(4))]:
        covered = image.copy()
        for j in targets:
            q = np.float32(poses[j]['outline'])
            h = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]), q)
            polygon = transform([[0,0],[fraction,0],[fraction,1],[0,1]], h)
            if fraction:
                cv2.fillConvexPoly(covered, np.rint(polygon).astype(np.int32), (110,120,150))
        # Exclude image synthesis from tracking timings. First 24 frames may
        # be covered, then six clear frames verify recovery.
        frames = []
        for i in range(1, 31):
            h = np.float64([[1,0,i*.5],[0,1,i*.2],[0,0,1]])
            frame = cv2.warpPerspective(covered if i <= 24 else image, h, (image.shape[1], image.shape[0]))
            frames.append((tracking_gray(frame)[0], h))
        costs, states, paths, errors = [], Counter(), defaultdict(list), []
        recovery = []
        for repeat in range(3):
            tracks = [MotionTrack() for _ in poses]
            for track, pose in zip(tracks, poses):
                seed = deepcopy(pose)
                seed.update(frame_id=0, ts_ms=0)
                track.observe(seed, gray, scale)
                for method in ('_lk_step', '_wide_search'):
                    original = getattr(track.flow, method)
                    def timed(*a, _original=original, _name=method, **kw):
                        start = time.perf_counter()
                        try:
                            return _original(*a, **kw)
                        finally:
                            paths[_name].append((time.perf_counter()-start)*1000)
                    setattr(track.flow, method, timed)
            for i, (frame, matrix) in enumerate(frames, 1):
                start = time.perf_counter()
                searches = 0
                def claim_search():
                    nonlocal searches
                    if searches >= 1:
                        return False
                    searches += 1
                    return True
                outputs = [None] * len(tracks)
                # Same rotating priority as MotionOverlayWorker, preserving
                # output order. Geometry still uses the current replay frame.
                order = list(range(4))
                offset = (i-1) % 4
                for j in order[offset:] + order[:offset]:
                    outputs[j] = tracks[j].update(frame, i, i*33, search_budget=None if args.unlimited_search else claim_search)
                costs.append((time.perf_counter()-start)*1000)
                for pose, result in zip(poses, outputs):
                    states[f'{"covered" if i <= 24 else "clear"}:{result["tracking"] if result else "missing"}'] += 1
                    if result:
                        errors.append(float(np.max(np.linalg.norm(np.float32(result['outline'])-transform(pose['outline'],matrix),axis=1))))
                if i > 24:
                    recovery.append(sum(bool(r and r['tracking']=='locked') for r in outputs))
        results[name] = {
            'four_objects_ms_p50_p95_max': np.percentile(costs, [50,95,100]).tolist(),
            'states': dict(states), 'clear_recovery_locked_counts': recovery,
            'max_outline_error_px': max(errors, default=None),
            'paths': {key: {'calls': len(values), 'total_ms': sum(values),
                            'ms_p50_p95': np.percentile(values,[50,95]).tolist()} for key, values in paths.items()},
        }
        print(name, json.dumps(results[name]), flush=True)
    output = {'source_sha256': hashlib.sha256((ROOT/'backend/app/vision/motion_tracking.py').read_bytes()).hexdigest(),
              'opencv_threads': cv2.getNumThreads(), 'worker_search_budget': not args.unlimited_search,
              'startup_warmup_ms': warmup_ms, 'results': results,
              'limits': 'Recorded texture with synthetic masks/warps. Timings exclude camera, image synthesis, JPEG, HTTP and browser. Not a physical hand or absolute GPIO accuracy test.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
