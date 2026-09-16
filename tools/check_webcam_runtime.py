"""Read-only runtime snapshot: decoded Webcam image, paired poses, settings.

Does not select a camera, set controls, inspect Eye images or call cloud models.
"""
import argparse
import base64
import json
from pathlib import Path

import cv2
import httpx
import numpy as np


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():
        parser.error('Use a new snapshot directory')
    with httpx.Client(base_url='http://127.0.0.1:8100',timeout=10) as client:
        response=client.get('/api/inference/status');response.raise_for_status()
        inference=response.json()
        if inference.get('eye') and inference['eye'].get('active',True):
            raise RuntimeError('Eye worker present/active; do not capture or switch it')
        response=client.get('/api/camera/focus');response.raise_for_status()
        controls=response.json()
        response=client.get('/api/tracking/frame');response.raise_for_status()
        packet=response.json()
    raw=base64.b64decode(packet['image'].split(',',1)[1])
    image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError('No decoded camera image')
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    messages=[packet['detection'],*packet['components']]
    mismatch=sum(m['frame_id']!=packet['frame_id'] for m in messages)
    report={'frame_id':packet['frame_id'],'seq':packet['seq'],'shape':list(image.shape),
            'mean_brightness':float(gray.mean()),'p99_brightness':float(np.percentile(gray,99)),
            'same_frame_mismatches':mismatch,'inference':inference,'camera_controls':controls,
            'messages':messages,'limitation':__doc__}
    args.out.mkdir(parents=True)
    (args.out/'source.jpg').write_bytes(raw)
    (args.out/'snapshot.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('frame_id','shape','mean_brightness','p99_brightness','same_frame_mismatches')}))
    print(json.dumps([{'id':c['id'],'backend':c['actual_backend'],'webcam_motion_handoff':c.get('webcam_motion_handoff')}
                      for c in inference['components']]))


if __name__=='__main__':
    main()
