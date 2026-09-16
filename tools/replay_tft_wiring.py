"""Replay saved TFT model-source frames; no live camera or wiring operations."""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import cv2
import numpy as np
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.component_worker import ComponentPoseTracker,ComponentVisionProfile,ComponentPoseWorker,ComponentPoseState,refine_component_corners_from_mounting_holes
from app.capture.bus import FrameBus
from app.vision.yolo_pose import create_yolo_pose_locator,BoardPoseObservation
from app.vision.tft_ring_geometry import refine_tft_rings


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder',type=Path)
    p.add_argument('--candidate-geometry',action='store_true')
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    cv2.setNumThreads(2)
    rows=json.loads((args.folder/'sequence.json').read_text())
    cfg=yaml.safe_load((ROOT/'backend/config.yaml').read_text(encoding='utf-8'))['component_vision']
    spec=next(c for c in cfg['components'] if c['id']=='mrd-tf240-8p-cs')
    profile=ComponentVisionProfile.load(ROOT/'backend'/spec['profile_path'])
    cache=args.folder/'candidate-observations-008.json'
    if cache.exists():
        raw=json.loads(cache.read_text())
    else:
        locator=create_yolo_pose_locator(ROOT/'backend'/spec['model_path'],runtime_backend=cfg['runtime_backend'],
            input_size=spec['input_size'],confidence_threshold=.08,keypoint_threshold=spec['keypoint_threshold'],keypoint_count=4)
        raw={}
        for row in rows:
            obs=locator.locate(cv2.imread(str(args.folder/row['image_path'])))
            raw[str(row['frame_id'])]=None if obs is None else {'corners':obs.corners_px.tolist(),
                'confidence':obs.confidence,'keypoints':obs.keypoint_confidences.tolist(),'box':list(obs.box_xyxy)}
        locator.close()
        cache.write_text(json.dumps(raw),encoding='utf-8')
    tracker=ComponentPoseTracker(profile,motion_handoff=True)
    tracker._forget_pose('replay_start')
    results=[]
    worker=ComponentPoseWorker(bus=FrameBus(),state=ComponentPoseState(),publish=lambda _:None,
        model_path='unused',profile_path=ROOT/'backend'/spec['profile_path'],locator=SimpleNamespace(),
        webcam_motion_handoff=True,confidence_threshold=spec['confidence_threshold']) if args.candidate_geometry else None
    if worker is not None:
        tracker=worker._tracker
    for row in rows:
        frame=cv2.imread(str(args.folder/row['image_path']))
        fid=row['frame_id'];ts=row['component_pose']['ts_ms'];data=raw[str(fid)]
        obs=None if data is None else BoardPoseObservation(np.array(data['corners']),data['confidence'],
                                                           np.array(data['keypoints']),tuple(data['box']))
        weak=obs is not None and obs.confidence < spec['confidence_threshold']
        evidence={}
        started=time.perf_counter()
        if weak and not args.candidate_geometry:
            obs=None
        if worker is not None:
            obs,evidence=worker._refine_tft_candidate(frame,obs,fid,ts)
        elif obs is not None:
            refined=refine_tft_rings(frame,obs,evidence)
            if refined is not None and (not weak or evidence.get('screen_supported')):
                obs=refined
            elif weak:
                obs=None
            elif obs is not None:
                obs=refine_component_corners_from_mounting_holes(frame,obs) or obs
        result=tracker.update(frame,obs,frame_id=fid,ts_ms=ts)
        results.append({'frame_id':fid,'tracking':result.tracking,'reason':result.tracking_reason,
            'cv_tracker_ms':(time.perf_counter()-started)*1000,
            'candidate_score':None if data is None else data['confidence'],'weak_candidate':weak,
            'input_source':None if obs is None else obs.source,
            'input_corners':None if obs is None else obs.corners_px.tolist(),
            'outline':None if result.outline_px is None else result.outline_px.tolist(),
            'geometry':evidence,'continuity':result.visual_continuity})
    report={'frames':len(results),'locked':sum(r['tracking']=='locked' for r in results),
            'candidate_geometry':args.candidate_geometry,'results':results,
            'limitation':'Model-source-only replay, no display intermediates/inference latency; not GPIO ground truth.'}
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print({k:report[k] for k in ('frames','locked','candidate_geometry')})


if __name__=='__main__':main()
