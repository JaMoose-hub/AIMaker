"""Compare only the Pi boundary change on identical cached observations.

Offline JPEG/primary+fallback replay, not live tracking or pin ground truth.
Does not open a camera, modify runtime configuration, or call cloud models.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.config import load_config
from app.main import _build_detector
from app.profiles.store import ProfileStore
from app.vision import yolo_profile_detector as yp
from app.vision_worker import detection_message
from app.vision.yolo_pose import BoardPoseObservation


def encode(v):
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, np.generic):
        return v.item()
    raise TypeError(type(v).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--interval-ms', type=float, default=300)
    parser.add_argument('--reference-only', action='store_true',
                        help='Replay current production detector once, including reference recovery; no boundary A/B.')
    parser.add_argument('--scene-reference-comparison', action='store_true',
                        help='Compare the bounded calibrated-reference fallback off/on; unchanged PCB gates.')
    parser.add_argument('--motion-handoff-comparison', action='store_true',
                        help='Compare reference search plus image-confirmed moving board/final J8 pin handoff.')
    parser.add_argument('--handoff-only-comparison', action='store_true',
                        help='Compare image motion handoff alone; keep scene-reference search disabled in both modes.')
    parser.add_argument('--fresh-fallback-comparison', action='store_true',
                        help='Compare fresh reference fallback on primary stale, without scene search or motion gate.')
    parser.add_argument('--pi-color-roi-comparison', action='store_true',
                        help='Compare Pi reference matching without the unrelated dark-blue PCB color crop.')
    parser.add_argument('--sift-size-comparison', type=int, default=0,
                        help='Compare full-size vs capped SIFT rescue, both without Pi color cropping.')
    parser.add_argument('--observations-from', type=Path,
                        help='Reuse primary model observations after checking config, model and every source image/time.')
    args = parser.parse_args()
    if args.out.exists() or args.interval_ms <= 0:
        parser.error('Use a new output path and positive sampling interval')
    cv2.setNumThreads(2)
    cfg = load_config(ROOT/'backend/config.yaml')
    store = ProfileStore(cfg.profile_dir)
    profile, _ = store.load('raspberry-pi-5')
    original = yp.refine_board_corners_from_pcb
    def prior(*a, **kw):
        kw.pop('boundary_evidence', None)
        return original(*a, **kw)
    report = {'limitation': __doc__, 'yolo_config':cfg.yolo_pose.model_dump(mode='json'),
              'model_sha256':hashlib.sha256(cfg.yolo_pose.model_path_for('raspberry-pi-5').read_bytes()).hexdigest(),
              'interval_ms': args.interval_ms, 'cases':[]}
    cached = json.loads(args.observations_from.read_text(encoding='utf-8')) if args.observations_from else None
    if cached and any(cached.get(k) != report[k] for k in ('yolo_config', 'model_sha256', 'interval_ms')):
        raise ValueError('Observation cache config/model/sampling mismatch')
    try:
        for name in args.case:
            root = ROOT/'runs/acceptance/2026-09-13'/name
            rows = json.loads((root/'samples.json').read_text())
            selected = []
            for row in rows:
                if not selected or row['ts_ms']-selected[-1]['ts_ms'] >= args.interval_ms:
                    selected.append(row)
            cached_rows = next((c['inputs'] for c in cached['cases'] if c['case'] == name), None) if cached else None
            if cached and (cached_rows is None or len(cached_rows) != len(selected)):
                raise ValueError(f'Observation cache case/frame mismatch: {name}')
            detector = None if cached else _build_detector(cfg,profile,store.board_dir('raspberry-pi-5'),None)
            frames, observations, inputs = [], [], []
            try:
                for index, row in enumerate(selected):
                    path = root/row['image_path']; frame = cv2.imread(str(path))
                    if frame is None:
                        raise ValueError(path)
                    # Keep paths, not gigabytes of full-resolution frames.
                    frames.append(path)
                    image_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                    if cached_rows is not None:
                        old = cached_rows[index]
                        if (old['image'], old['sha256'], old['frame_id'], old['ts_ms']) != (
                                row['image_path'], image_hash, row['frame_id'], row['ts_ms']):
                            raise ValueError(f'Observation cache content mismatch: {path}')
                        fields = old['observation']
                        if fields:
                            fields = dict(fields)
                            for key in ('corners_px', 'keypoint_confidences', 'landmarks_px'):
                                if fields.get(key) is not None:
                                    fields[key] = np.asarray(fields[key], dtype=float)
                            fields['box_xyxy'] = tuple(fields['box_xyxy'])
                        observations.append(BoardPoseObservation(**fields) if fields else None)
                    else:
                        observations.append(detector.primary._locator.locate(frame))
                    inputs.append({'image':row['image_path'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                   'frame_id':row['frame_id'],'ts_ms':row['ts_ms'],
                                   'observation':asdict(observations[-1]) if observations[-1] else None})
            finally:
                if detector is not None:
                    detector.close()
            case = {'case':name,'inputs':inputs,'modes':{}}
            modes = ([('before', original, False), ('after', original, False)] if args.handoff_only_comparison or args.fresh_fallback_comparison or args.pi_color_roi_comparison or args.sift_size_comparison
                     else [('before', original, False), ('after', original, True)] if args.scene_reference_comparison or args.motion_handoff_comparison
                     else [('current', original, False)] if args.reference_only
                     else [('before', prior, False), ('after', original, False)])
            for mode, refiner, scene_search in modes:
                yp.refine_board_corners_from_pcb = refiner
                cv2.setRNGSeed(7)
                detector = _build_detector(cfg,profile,store.board_dir('raspberry-pi-5'),None)
                detector.fresh_fallback_handoff = args.fresh_fallback_comparison and mode == 'after'
                color_roi = not (args.sift_size_comparison or (args.pi_color_roi_comparison and mode == 'after'))
                detector.fallback._tracker.params.color_roi_enabled = color_roi
                detector.fallback._tracker.params.sift_frame_max_px = args.sift_size_comparison if mode == 'after' else 0
                detector.primary.set_scene_reference_search(scene_search)
                handoff = (args.handoff_only_comparison and mode == 'after') or (args.motion_handoff_comparison and scene_search)
                detector.primary.set_motion_handoff(handoff)
                outputs=[]; elapsed=[]
                try:
                    for row,path,obs in zip(selected,frames,observations):
                        frame = cv2.imread(str(path))
                        if frame is None:
                            raise ValueError(path)
                        detector.primary._locator.locate = lambda f, value=obs: value
                        started = time.perf_counter()
                        result=detector.detect(frame,row['frame_id'],row['ts_ms'])
                        elapsed.append((time.perf_counter()-started)*1000)
                        outputs.append(detection_message(result,(frame.shape[1],frame.shape[0])))
                        outputs[-1]['motion_outline'] = result.motion_outline_px
                        outputs[-1]['source_sha256'] = inputs[len(outputs)-1]['sha256']
                        if detector.primary._image_motion_gate is not None:
                            outputs[-1]['motion_handoff_evidence'] = dict(detector.primary._image_motion_gate.evidence)
                finally:
                    detector.close()
                case['modes'][mode]={'statuses':dict(Counter(o['tracking'] for o in outputs)),
                                     'scene_reference_search': scene_search,
                                     'motion_handoff': handoff,
                                     'fresh_fallback_handoff': args.fresh_fallback_comparison and mode == 'after',
                                     'color_roi_enabled': color_roi,
                                     'sift_frame_max_px': args.sift_size_comparison if mode == 'after' else 0,
                                     'pipeline_ms_without_primary_inference': {'p50':float(np.percentile(elapsed,50)),
                                                                             'p95':float(np.percentile(elapsed,95))},
                                     'reasons':dict(Counter(str(o.get('pose_quality',{}).get('stability')) for o in outputs)),
                                     'outputs':outputs}
            report['cases'].append(case)
            print(json.dumps({'case':name, **{k:v['statuses'] for k,v in case['modes'].items()}}),flush=True)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with args.out.open('x',encoding='utf-8') as f:
            json.dump(report,f,indent=2,default=encode)
    finally:
        yp.refine_board_corners_from_pcb=original


if __name__ == '__main__':
    main()
