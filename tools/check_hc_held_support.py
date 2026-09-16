"""Inspect saved held image only; no camera or configuration writes."""
import json,sys
from pathlib import Path
import cv2,numpy as np
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from app.component_worker import ComponentPoseTracker
folder=root/'runs/acceptance/2026-09-16/hc-held-diagnosis'
image=cv2.imread(str(folder/'source.jpg'))
r=json.loads((folder/'inspection.json').read_text())
q=np.asarray(r['raw_corners'])
blue=ComponentPoseTracker._blue_fraction(image,q)
hand=ComponentPoseTracker._hand_fraction(image,q)
print(dict(blue=blue,hand=hand,rings=ComponentPoseTracker._hc_transducers_visible(image,q,blue)))
