"""Offline actual-image HC reacquisition replay; no fabricated intermediate frames."""
import argparse
import json
from pathlib import Path
import sys
import cv2
import numpy as np
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.component_worker import ComponentVisionProfile, ComponentPoseTracker, refine_component_corners_from_pcb, bound_hc_corner_refinement
from app.vision.yolo_pose import create_yolo_pose_locator, BoardPoseObservation


def main():
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--reference',action='store_true')
    p.add_argument('--rectified-reference',action='store_true',help='Compare legacy descriptors without changing the runtime profile')
    p.add_argument('--two-image-reference',action='store_true',help='Compare legacy two-image-only acquisition')
    args=p.parse_args(); folder=args.folder
    config=yaml.safe_load((ROOT/'backend/config.yaml').read_text(encoding='utf-8'))['component_vision']
    item=next(c for c in config['components'] if c['id']=='hc-sr04')
    profile=ComponentVisionProfile.load(ROOT/'backend'/item['profile_path'])
    paired = (folder/'model/frames.jsonl').exists()
    model_folder = folder/'model' if paired else folder
    rows=([json.loads(line) for line in (model_folder/'frames.jsonl').read_text().splitlines()]
          if paired else json.loads((folder/'sequence.json').read_text()))
    cache=folder/'raw-observations.json'
    if cache.exists():
        observations=json.loads(cache.read_text())
    else:
        locator=create_yolo_pose_locator(ROOT/'backend'/item['model_path'],runtime_backend=config['runtime_backend'],input_size=item['input_size'],confidence_threshold=item['confidence_threshold'],keypoint_threshold=item['keypoint_threshold'],keypoint_count=profile.keypoint_count)
        observations={}
        for row in rows:
            frame=cv2.imread(str(model_folder/row['image_path']));o=locator.locate(frame)
            observations[str(row['frame_id'])]=None if o is None else {'corners':o.corners_px.tolist(),'confidence':float(o.confidence),'keypoints':o.keypoint_confidences.tolist(),'box':list(o.box_xyxy)}
        locator.close();cache.write_text(json.dumps(observations),encoding='utf-8')
    frames={r['frame_id']:(r,True) for r in rows}
    for line in ((folder/'display/frames.jsonl').read_text().splitlines() if paired else []):
        r=json.loads(line);frames.setdefault(r['frame_id'],(r,False))
    tracker=ComponentPoseTracker(profile,motion_handoff=True);tracker._forget_pose('replay_start')
    from app.vision.reference_recovery import ReferencePoseRecovery
    from dataclasses import replace
    recovery=ReferencePoseRecovery.from_component_profile(ROOT/'backend'/item['profile_path']) if args.reference else None
    if args.rectified_reference:
        if recovery is None: p.error('--rectified-reference requires --reference')
        blue=cv2.inRange(cv2.cvtColor(recovery.reference,cv2.COLOR_BGR2HSV),np.uint8([75,35,12]),np.uint8([145,255,255]))
        recovery=ReferencePoseRecovery(recovery.reference,feature_mask=cv2.dilate(blue,np.ones((3,3),np.uint8)))
    results=[]
    for fid,(row,is_model) in sorted(frames.items()):
        frame=cv2.imread(str((model_folder if is_model else folder/'display')/row['image_path']))
        if is_model:
            ts=row['component_pose']['ts_ms'];data=observations[str(fid)]
            reference_evidence=None
            obs=None if data is None else BoardPoseObservation(np.array(data['corners']),data['confidence'],np.array(data['keypoints']),tuple(data['box']))
            if obs is not None:
                refined=refine_component_corners_from_pcb(frame,obs)
                obs,_=bound_hc_corner_refinement(profile,obs,refined,(frame.shape[1],frame.shape[0]))
                if recovery is not None:
                    matched=recovery.locate(frame,region=obs)
                    reference_evidence=dict(recovery.evidence)
                    reference_evidence['frame_id']=fid
                    if matched is not None: obs=replace(matched,source='hc_reference_sift')
            result=tracker.update(frame,obs,frame_id=fid,ts_ms=ts,
                reference_evidence=None if args.two_image_reference else reference_evidence)
            results.append({'frame_id':fid,'tracking':result.tracking,'reason':result.tracking_reason,
                'outline':None if result.outline_px is None else result.outline_px.tolist(),
                'input_source':None if obs is None else obs.source,
                'input_corners':None if obs is None else obs.corners_px.tolist(),
                'reference_evidence':reference_evidence,
                'visual_continuity':result.visual_continuity,'reacquisition':result.reacquire_evidence})
        elif tracker._pose_window is not None:
            tracker._pose_window.advance(frame,fid,row['ts_ms'])
    report={'model_frames':len(results),'locked':sum(r['tracking']=='locked' for r in results),'results':results,
            'reference_descriptor_space':None if recovery is None else recovery.descriptor_space,
            'reference_acquisition':'two_image_only' if args.two_image_reference else 'strong_current_or_two_images',
            'capture_mode':'model_and_display' if paired else 'sparse_model_images_only',
            'limitation':'Saved real frames only; offline replay omits model inference latency and has capture gaps; not pin ground truth.'}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print({k:report[k] for k in ('model_frames','locked')})


if __name__=='__main__':main()
