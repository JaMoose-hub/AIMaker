"""Known-transform stress replay, using one same-frame live packet as texture.

Only reads the live API. No camera controls, hardware motion or deployment.
"""
import argparse
import base64
import json
from pathlib import Path
import sys
import time

import cv2
import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.motion_worker import tracking_gray
from app.vision.motion_tracking import MotionTrack, transform


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--objects', nargs='+', default=['raspberry-pi-5', 'hc-sr04'])
    args = parser.parse_args()
    if not args.fixture.exists():
        deadline = time.monotonic() + 15
        with httpx.Client(base_url='http://127.0.0.1:8100', timeout=2) as client:
            while True:
                response = client.get('/api/tracking/frame')
                if response.status_code == 200:
                    packet = response.json()
                    poses = [packet['detection'], *packet['components']]
                    locked = {p.get('component_id', p.get('board_id')) for p in poses
                              if p['tracking'] == 'locked' and p['frame_id'] == packet['frame_id']}
                    if set(args.objects) <= locked:
                        break
                if time.monotonic() > deadline:
                    raise RuntimeError(f'No simultaneous locked seed for {args.objects}; do not invent poses.')
        args.fixture.parent.mkdir(parents=True, exist_ok=True)
        args.fixture.write_text(json.dumps(packet), encoding='utf-8')
    packet = json.loads(args.fixture.read_text(encoding='utf-8'))
    image = cv2.imdecode(np.frombuffer(base64.b64decode(packet['image'].split(',')[1]), np.uint8), cv2.IMREAD_COLOR)
    gray, scale = tracking_gray(image)
    results = []
    for pose in [packet['detection'], *packet['components']]:
        key = pose.get('component_id', pose.get('board_id'))
        if key not in args.objects or pose['tracking'] != 'locked' or pose['frame_id'] != packet['frame_id']:
            continue
        quad = np.asarray(pose['outline'], np.float32)
        centre = tuple(quad.mean(0))
        for dx, angle, blur in [(60, 0, 0), (120, 0, 0), (200, 0, 0), (80, 12, 0), (80, 0, 25)]:
            tracker = MotionTrack()
            seed = {**pose, 'frame_id': 0, 'ts_ms': 0}
            tracker.observe(seed, gray, scale)
            affine = cv2.getRotationMatrix2D(centre, angle, 1)
            affine[:, 2] += [dx, 0]
            matrix = np.vstack([affine, [0, 0, 1]])
            sharp = cv2.warpPerspective(image, matrix, (image.shape[1], image.shape[0]))
            changed = cv2.GaussianBlur(sharp, (blur, blur), 0) if blur else sharp
            output = []
            for i, frame in enumerate([changed, sharp, sharp], start=1):
                start = time.perf_counter()
                result = tracker.update(tracking_gray(frame)[0], i, i * 33)
                cost = (time.perf_counter() - start) * 1000
                error = (float(np.max(np.linalg.norm(np.asarray(result['outline']) - transform(quad, matrix), axis=1)))
                         if result is not None and result.get('outline') is not None else None)
                output.append({'state': result['tracking'] if result else 'missing', 'error_px': error,
                               'processing_ms': round(cost, 2),
                               'reason': getattr(tracker, 'failure_reason', None)})
            results.append({'object': key, 'translation_px': dx, 'rotation_deg': angle,
                            'blur_kernel': blur, 'frames': output})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
