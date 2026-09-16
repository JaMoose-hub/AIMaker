"""Controlled masks over captured camera texture; never drives real hardware."""
import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.motion_worker import tracking_gray
from app.vision.motion_tracking import MotionTrack, transform


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    packet = json.loads(args.fixture.read_text(encoding='utf-8'))
    image = cv2.imdecode(np.frombuffer(base64.b64decode(packet['image'].split(',')[1]), np.uint8), cv2.IMREAD_COLOR)
    gray, scale = tracking_gray(image)
    results = []
    for pose in [packet['detection'], *packet['components']]:
        if pose['tracking'] != 'locked' or pose['frame_id'] != packet['frame_id']:
            continue
        quad = np.float32(pose['outline'])
        base = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]), quad)
        for fraction in [.15, .25, .40, .55, .75, 1.0]:
            tracker = MotionTrack()
            seed = deepcopy(pose)
            seed.update(frame_id=0, ts_ms=0)
            tracker.observe(seed, gray, scale)
            covered = image.copy()
            polygon = transform([[0,0],[fraction,0],[fraction,1],[0,1]], base)
            cv2.fillConvexPoly(covered, np.rint(polygon).astype(np.int32), (110,120,150))
            frames = []
            for i in range(1, 7):
                # Five 200ms frames maintain an obstruction for one second.
                # The final clear image must independently support recovery.
                matrix = np.float64([[1,0,i*2],[0,1,i],[0,0,1]])
                moved = cv2.warpPerspective(covered if i < 6 else image, matrix, (image.shape[1], image.shape[0]))
                result = tracker.update(tracking_gray(moved)[0], i, i*200)
                frames.append({
                    'tracking': result['tracking'] if result else 'missing',
                    'pins': len(result['pins']) if result else 0,
                    'error_px': float(np.max(np.linalg.norm(np.float32(result['outline']) - transform(quad, matrix), axis=1))) if result else None,
                    'quality': result.get('pose_quality') if result else {'reason': tracker.failure_reason},
                })
            results.append({'object': pose.get('component_id', pose.get('board_id')), 'mask_fraction': fraction, 'frames': frames})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding='utf-8')
    for r in results:
        print(r['object'], r['mask_fraction'], [f['tracking'] for f in r['frames']],
              'max_error', round(max([f['error_px'] for f in r['frames'] if f['error_px'] is not None], default=0), 2))


if __name__ == '__main__':
    main()
