"""Replay saved source frames through real MotionTrack + PinRegions.

Detector messages are delayed by an explicit, simulated 150ms by default.
This exercises the native observe/update ordering and same-frame geometry, but
not browser rendering, four-worker contention, real latency or physical pin
accuracy. Missing/covered intervals stay in the denominator, not deleted.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.motion_worker import tracking_gray
from app.vision.motion_tracking import MotionTrack


def replay(case, seeds, delay_ms, expected_hashes=None, background=False, paced=False, fresh_recovery=False):
    cv2.setRNGSeed(7)
    samples = json.loads((case/'samples.json').read_text(encoding='utf-8'))
    by_id = {row['frame_id']:row for row in samples}
    for seed in seeds:
        row = by_id[seed['frame_id']]
        if row['ts_ms'] != seed['ts_ms'] or 'motion_outline' not in seed or 'source_sha256' not in seed:
            raise ValueError('Need source-paired seeds exported by current worker replay')
        if hashlib.sha256((case/row['image_path']).read_bytes()).hexdigest() != seed['source_sha256']:
            raise ValueError('Source seed image hash changed')
    track = MotionTrack()
    track.fresh_recovery_enabled = fresh_recovery
    from app.vision.background_recovery import BackgroundRecovery
    recovery = BackgroundRecovery() if background else None
    replay_started = time.perf_counter()
    cursor = 0
    latest = None
    image_cache = {}
    hashes, outputs, costs = [], [], []
    for index, row in enumerate(samples):
        if paced:
            time.sleep(max(0, (row['ts_ms']-samples[0]['ts_ms'])/1000-(time.perf_counter()-replay_started)))
        path = case/row['image_path']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = {'frame_id':row['frame_id'], 'ts_ms':row['ts_ms'], 'image':row['image_path'], 'sha256':digest}
        if expected_hashes is not None and identity != expected_hashes[index]:
            raise ValueError('A/B source frames differ')
        hashes.append(identity)
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(path)
        gray, scale = tracking_gray(image)
        image_cache[row['frame_id']] = (gray, scale)
        while cursor < len(seeds) and seeds[cursor]['ts_ms']+delay_ms <= row['ts_ms']:
            latest = seeds[cursor]
            cursor += 1
        started = time.perf_counter()
        if latest is not None and 0 <= row['ts_ms']-latest['ts_ms'] <= 750 and latest['frame_id'] > track.seen_seed:
            source_gray, source_scale = (image_cache[latest['frame_id']] if track.needs_source_image(latest) else (gray,scale))
            track.observe(deepcopy(latest), source_gray, source_scale)
        track.flow.background_recovery = recovery
        result = track.update(gray, row['frame_id'], row['ts_ms'], search_budget=lambda: True)
        if recovery is not None and result is not None and result['tracking'] == 'locked' and not result.get('pose_quality', {}).get('partial'):
            recovery.observe(track.flow, row['ts_ms'])
        costs.append((time.perf_counter()-started)*1000)
        if result is not None and (result['frame_id'] != row['frame_id'] or result['ts_ms'] != row['ts_ms']):
            raise ValueError('Display image/pose mismatch')
        outputs.append({'frame_id':row['frame_id'], 'ts_ms':row['ts_ms'],
                        'tracking':result['tracking'] if result else 'searching',
                        'outline':result.get('outline') if result else None,
                        'pins':result.get('pins',[]) if result else [],
                        'quality':result.get('pose_quality',{}) if result else {'reason':track.failure_reason or 'awaiting_model_lock'}})
        while len(image_cache) > 40:
            del image_cache[next(iter(image_cache))]
    if recovery is not None:
        recovery.close()
    visible = [len(o['pins']) for o in outputs]
    summary = {'frames':len(outputs), 'frames_with_pins':sum(n>0 for n in visible),
               'frames_with_outline':sum(o['outline'] is not None for o in outputs),
               'statuses':dict(Counter(o['tracking'] for o in outputs)),
               'reasons':dict(Counter(str(o['quality'].get('reason')) for o in outputs)),
               'pin_counts':dict(Counter(visible)), 'same_frame_mismatches':0,
               'single_object_processing_ms_p95':float(np.percentile(costs,95)),
               'simulated_detector_delay_ms':delay_ms}
    return {'summary':summary, 'outputs':outputs}, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT/'runs/acceptance/2026-09-13')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--delay-ms', type=float, default=150)
    args = parser.parse_args()
    if args.out.exists() or not 0 <= args.delay_ms <= 500:
        parser.error('Use a new output path and delay between 0 and 500ms')
    cv2.setNumThreads(2)
    report = json.loads(args.report.read_text(encoding='utf-8'))
    cases, frame_hashes = [], {}
    for entry in report['results']:
        summary = entry['summary']
        case = summary['case']
        result, hashes = replay(args.source_root/case, entry['outputs'], args.delay_ms, frame_hashes.get(case))
        frame_hashes[case] = hashes
        result['summary'].update(case=case, component_id=summary['component_id'],
                                 motion_handoff=summary.get('motion_handoff',False),
                                 visual_continuity=summary.get('visual_continuity',False))
        print(json.dumps(result['summary']), flush=True)
        cases.append(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump({'limitations':__doc__, 'source_report':str(args.report),
                   'source_report_sha256':hashlib.sha256(args.report.read_bytes()).hexdigest(),
                   'frame_hashes':frame_hashes, 'results':cases}, handle, indent=2)


if __name__ == '__main__':
    main()
