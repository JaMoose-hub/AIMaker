"""Read-only live sample + known-transform replay of captured camera texture.

Does not move hardware, change camera settings or write deployment state.
"""
import argparse
import base64
import copy
from collections import Counter
import json
from pathlib import Path
import sys
import time

import cv2
import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.motion_worker import TRACKED_COMPONENT_IDS, tracking_gray
from app.vision.motion_tracking import MotionTrack, transform


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--record-frames', action='store_true',
                        help='Save every delivered image with its sample metadata; adds disk I/O, not a clean performance benchmark.')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.record_frames:
        (args.out / 'frames').mkdir(exist_ok=False)
    samples, seeds, statuses = [], {}, Counter()
    body_statuses, body_frame_errors = Counter(), 0
    failure_counts = Counter()
    after, started = -1, time.monotonic()
    with httpx.Client(base_url='http://127.0.0.1:8100', timeout=2) as client:
        while time.monotonic() - started < args.seconds:
            response = client.get('/api/tracking/frame', params={'after': after})
            if response.status_code == 204:
                continue
            response.raise_for_status()
            packet = response.json()
            after = packet['seq']
            sample = {k: packet[k] for k in ('seq', 'frame_id', 'ts_ms', 'processing_ms')}
            sample['received_ms'] = time.monotonic() * 1000
            if args.record_frames:
                name = f'frames/{len(samples):06d}.jpg'
                (args.out / name).write_bytes(base64.b64decode(packet['image'].split(',')[1]))
                sample['image_path'] = name
                sample['recorded_detection'] = packet['detection']
                sample['recorded_components'] = packet['components']
            sample['board'] = packet['detection']['tracking']
            sample['board_quality'] = packet['detection'].get('pose_quality')
            sample['timing_ms'] = packet.get('timing_ms')
            sample['recovery_searches'] = packet.get('recovery_searches')
            sample['recovery_deferred'] = packet.get('recovery_deferred')
            for message in [packet['detection'], *packet['components']]:
                key = message.get('component_id', message.get('board_id'))
                statuses[f'{key}:{message["tracking"]}'] += 1
                body = message.get('body')
                if body is not None and (body.get('frame_id') != packet['frame_id']
                        or not 0 <= body.get('age_ms', -1) <= 650):
                    body_frame_errors += 1
                body_found = bool(body and body.get('outline')
                    and body.get('frame_id') == packet['frame_id']
                    and 0 <= body.get('age_ms', -1) <= 650)
                found = body_found or bool(message['tracking'] == 'locked' and message.get('outline'))
                body_statuses[f'{key}:{"found" if found else "missing"}'] += 1
                # Keep bounded same-frame failure evidence too. Previously a
                # completely failed run saved no image, making root-cause
                # replay impossible. Never substitute a later /frame.jpg.
                quality = message.get('pose_quality') or {}
                reason = quality.get('reason') or 'unspecified'
                failure_key = (key, message['tracking'], reason)
                if (key in ('raspberry-pi-5', *TRACKED_COMPONENT_IDS)
                        and message['tracking'] != 'locked'
                        and message['frame_id'] == packet['frame_id']
                        and failure_counts[failure_key] < 2):
                    failure_counts[failure_key] += 1
                    index = sum(failure_counts.values())
                    image_bytes = base64.b64decode(packet['image'].split(',')[1])
                    (args.out / f'failure-{index:03d}-source.jpg').write_bytes(image_bytes)
                    (args.out / f'failure-{index:03d}-pose.json').write_text(json.dumps({
                        'seq': packet['seq'], 'frame_id': packet['frame_id'],
                        'object_id': key, 'message': message,
                        'limitation': 'Paired display image; upstream model source may be an older frame.',
                    }, indent=2), encoding='utf-8')
                if (key in ('raspberry-pi-5', *TRACKED_COMPONENT_IDS)
                        and message['tracking'] == 'locked'
                        and message['frame_id'] == packet['frame_id'] and key not in seeds):
                    image = cv2.imdecode(np.frombuffer(base64.b64decode(packet['image'].split(',')[1]), np.uint8), cv2.IMREAD_COLOR)
                    seeds[key] = (image, message)
                    cv2.imwrite(str(args.out / f'{key}-source.jpg'), image)
                    (args.out / f'{key}-pose.json').write_text(json.dumps(message, indent=2), encoding='utf-8')
            sample['components'] = {m['component_id']: {
                'tracking': m['tracking'], 'frame_id': m['frame_id'],
                'quality': m.get('pose_quality'),
            } for m in packet['components']}
            samples.append(sample)
    elapsed = time.monotonic() - started
    replays = {}
    for key, (image, message) in seeds.items():
        # Replay uses its own timeline; never rewrite the recorded packet.
        message = copy.deepcopy(message)
        gray, scale = tracking_gray(image)
        message['frame_id'], message['ts_ms'] = 0, 0
        original_quad = np.asarray(message['outline'], np.float32)
        tracker = MotionTrack()
        tracker.observe(message, gray, scale)
        centre = original_quad.mean(0)
        errors, lost = [], 0
        for i in range(1, 21):
            affine = cv2.getRotationMatrix2D(tuple(centre), i * .6, 1 + i * .002)
            affine[:, 2] += [i * 2, -i]
            matrix = np.vstack([affine, [0, 0, 1]])
            moved = cv2.warpPerspective(image, matrix, (image.shape[1], image.shape[0]))
            moved_gray, _ = tracking_gray(moved)
            result = tracker.update(moved_gray, i, i * 33)
            if result is None:
                lost += 1
            else:
                errors.append(float(np.max(np.linalg.norm(np.asarray(result['outline']) - transform(original_quad, matrix), axis=1))))
        replays[key] = {'frames': 20, 'lost': lost, 'max_outline_error_px': max(errors) if errors else None}
    stats = {
        'elapsed_s': elapsed, 'packets': len(samples), 'delivered_hz': len(samples) / elapsed,
        'recorded_frames': bool(args.record_frames),
        'recording_limitations': 'Delivered JPEG sequence, not every camera frame or lossless model-source image. Disk I/O may affect measured throughput.' if args.record_frames else None,
        'statuses': dict(statuses), 'known_transform_replay': replays,
        'body_statuses': dict(body_statuses), 'body_frame_errors': body_frame_errors,
        'body_limitations': 'Body-available state proportions, not independent accuracy trials. Boxes must also be visually checked against objects.',
        'processing_ms_p50_p95': np.percentile([s['processing_ms'] for s in samples], [50, 95]).tolist() if samples else None,
        'capture_to_response_ms_p50_p95': np.percentile([s['received_ms'] - s['ts_ms'] for s in samples], [50, 95]).tolist() if samples else None,
        'limitations': 'Replay warps captured texture, not a physical handheld or absolute pin-accuracy test. FPS counts same-frame packets, not successful locks.',
    }
    (args.out / 'samples.json').write_text(json.dumps(samples, indent=2), encoding='utf-8')
    (args.out / 'summary.json').write_text(json.dumps(stats, indent=2), encoding='utf-8')
    print(json.dumps(stats, indent=2))


if __name__ == '__main__':
    main()
