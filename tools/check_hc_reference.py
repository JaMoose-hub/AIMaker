"""Evaluate a separate captured PCB reference against the held sequence."""
import json
import sys
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.yolo_pose import BoardPoseObservation

source=ROOT/'runs/acceptance/2026-09-16/hc-motion-inspection-02/source.jpg'
image=cv2.imread(str(source))
# Manually inspected PCB boundary, not the raised transducer rims.
corners=np.float32([[1285,635],[858,606],[868,420],[1297,446]])
matrix=cv2.getPerspectiveTransform(corners,np.float32([[0,0],[479,0],[479,209],[0,209]]))
reference=cv2.warpPerspective(image,matrix,(480,210))
blue=cv2.inRange(cv2.cvtColor(reference,cv2.COLOR_BGR2HSV),np.uint8([75,35,12]),np.uint8([145,255,255]))
mask=cv2.dilate(blue,np.ones((3,3),np.uint8))
recovery=ReferencePoseRecovery(reference,feature_mask=mask)
folder=ROOT/'runs/acceptance/2026-09-16/hc-synchronized-held-01'
raw=json.loads((folder/'raw-observations.json').read_text())
out=[]
for line in (folder/'model/frames.jsonl').read_text().splitlines():
    row=json.loads(line);data=raw[str(row['frame_id'])]
    region=BoardPoseObservation(np.array(data['corners']),data['confidence'],np.array(data['keypoints']),tuple(data['box']))
    found=recovery.locate(cv2.imread(str(folder/'model'/row['image_path'])),region)
    out.append({'frame_id':row['frame_id'],'corners':None if found is None else found.corners_px.tolist(),'evidence':dict(recovery.evidence)})
(folder/'reference-trial.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print({'reference_features':len(recovery.keypoints),'matched':sum(r['corners'] is not None for r in out),'total':len(out)})
