"""Bounded offline full-scene reference-matching probe; never changes runtime.

Uses existing calibrated/reviewed assets, not new training or automatic labels.
Reference match acceptance is not independent GPIO/contact ground truth.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.config import load_config
from app.main import _build_detector
from app.profiles.store import ProfileStore
from app.vision.reference_recovery import ReferencePoseRecovery


def legacy_reference(dataset, name, size):
    path = ROOT/'datasets'/dataset/'images/train'/f'{name}.jpg'
    label = ROOT/'datasets'/dataset/'labels/train'/f'{name}.txt'
    frame = cv2.imread(str(path))
    if frame is None:
        raise ValueError(path)
    values = np.asarray(label.read_text().split(), float)
    corners = values[5:].reshape(-1, 3)[:4, :2]*[frame.shape[1], frame.shape[0]]
    w, h = size
    canonical = np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
    rectified = cv2.warpPerspective(frame, cv2.getPerspectiveTransform(corners.astype(np.float32), canonical), size)
    return ReferencePoseRecovery(rectified), {'image': str(path.relative_to(ROOT)),
        'label': str(label.relative_to(ROOT)), 'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'label_sha256': hashlib.sha256(label.read_bytes()).hexdigest(),
        'note': 'Existing legacy labels, not fresh independent pin truth'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists(): p.error('Use a new output path')
    cv2.setNumThreads(2); cv2.setRNGSeed(7)
    cfg=load_config(ROOT/'backend/config.yaml')
    store=ProfileStore(cfg.profile_dir); profile,_=store.load('raspberry-pi-5')
    detector=_build_detector(cfg,profile,store.board_dir('raspberry-pi-5'),None)
    references={'raspberry-pi-5':detector.primary._reference_recovery,
        'hw-123':ReferencePoseRecovery.from_component_profile(ROOT/'profiles/components/hw-123/vision_profile.json')}
    provenance={}
    references['hc-sr04'],provenance['hc-sr04']=legacy_reference(
        'hc-sr04-corner-pose-v2','hc_sr04_live_20260831_170256_0001',(400,200))
    references['mrd-tf240-8p-cs'],provenance['mrd-tf240-8p-cs']=legacy_reference(
        'mrd-tf240-8p-corner-pose-v1','mrd_tf240_train_20260901_113936_0001',(320,480))
    suite=ROOT/'runs/acceptance/2026-09-15/webcam-robustness-v1/suite.json'
    manifest=json.loads(suite.read_text())
    results=[]
    try:
        for name in manifest['tuning_cases']+manifest['regression_cases']:
            case=ROOT/manifest['source_root']/name
            samples=json.loads((case/'samples.json').read_text())
            indices=[0,len(samples)//2,len(samples)-1]
            for index in indices:
                sample=samples[index]; path=case/sample['image_path']; frame=cv2.imread(str(path))
                if frame is None: raise ValueError(path)
                row={'case':name,'index':index,'image':str(path.relative_to(ROOT)),
                     'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'parts':{}}
                for cid,reference in references.items():
                    region=SimpleNamespace(box_xyxy=(0,0,frame.shape[1],frame.shape[0]),confidence=0.)
                    obs=reference.locate(frame,region)
                    row['parts'][cid]={'accepted':obs is not None,'evidence':dict(reference.evidence),
                                      'corners':obs.corners_px.tolist() if obs is not None else None}
                results.append(row)
            print(json.dumps({'case':name,'accepted_of_3':{cid:sum(r['parts'][cid]['accepted'] for r in results[-3:]) for cid in references}}),flush=True)
    finally:
        detector.close()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as f:
        json.dump({'limitations':__doc__,'provenance':provenance,'results':results},f,indent=2)


if __name__=='__main__': main()
