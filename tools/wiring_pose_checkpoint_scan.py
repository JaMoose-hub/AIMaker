"""Rank saved PT checkpoints by actual localization error, not permissive pose mAP.

This is validation-set model selection, never an independent acceptance result.
No training, exports, deployment, or source-label modifications are performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from wiring_pose_data import digest, read_label, write_json
from wiring_pose_evaluation import box_iou, stats


def scan(parent, out, component, runs, budget,training_root=None):
    import torch
    from ultralytics import YOLO
    sys.path.insert(0,str(parent/"snapshot/backend"))
    from app.vision.yolo_pose import _letterbox, decode_yolo_pose_output
    import yaml

    if not torch.cuda.is_available():raise RuntimeError("CUDA required")
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    manifest=json.loads((parent/"manifest.json").read_text(encoding="utf-8"))
    spec=manifest["components"][component]
    config=yaml.safe_load((parent/"snapshot/backend/config.yaml").read_text(encoding="utf-8"))
    target=next(t for t in config["component_vision"]["components"] if t["id"]==spec["id"])
    size=spec["input_size"]
    rows=[r for r in spec["records"] if r["split"]=="val" and not r.get("exclusion")]
    inputs=[]; truth=[]; meta=[]
    for row in rows:
        frame=cv2.imread(str(parent/row["image"]))
        padded,scale,px,py=_letterbox(frame,size)
        inputs.append(np.ascontiguousarray(padded[:,:,::-1].transpose(2,0,1),dtype=np.float32)/255.)
        meta.append((frame.shape[1],frame.shape[0],scale,px,py))
        truth.append(read_label(parent/row["label"]))
    tensors=torch.from_numpy(np.stack(inputs)).cuda()
    result={"component":component,"scope":"legacy-validation checkpoint selection; not independent acceptance",
            "parent_manifest_sha256":digest(parent/"manifest.json"),"runs":{},"training_started":False}
    for run in runs:
        destination=out/"checkpoint-scan"/(run+".json")
        if destination.exists():raise FileExistsError(destination)
        reports=[]
        for epoch in range(budget):
            checkpoint=(training_root or parent)/"training"/run/"weights"/f"epoch{epoch}.pt"
            if not checkpoint.exists():break
            model=YOLO(str(checkpoint)).model.cuda().float().eval()
            model.fuse(verbose=False)
            predicted=[]
            with torch.inference_mode():
                for offset in range(0,len(rows),4):
                    output=model(tensors[offset:offset+4])
                    output=output[0] if isinstance(output,(tuple,list)) else output
                    predicted.extend(output.cpu().numpy())
            records=[]
            for row,label,tensor,(width,height,scale,px,py) in zip(rows,truth,predicted,meta):
                observation=decode_yolo_pose_output(tensor,frame_size=(width,height),input_size=size,scale=scale,pad_x=px,pad_y=py,
                    confidence_threshold=target["confidence_threshold"],keypoint_threshold=target["keypoint_threshold"],nms_iou_threshold=.45)
                record={"key":row["key"],"group":row["group"],"positive":label is not None,"detected":observation is not None,"matched":False}
                if label is not None:
                    cx,cy,bw,bh=label[1:5]*[width,height,width,height]
                    if observation is not None:
                        points=label[5:].reshape(4,3)[:,:2]*[width,height]
                        diagonal=max(float(np.linalg.norm(points[2]-points[0])),1.)
                        record.update(matched=box_iou(observation.box_xyxy,[cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2])>=.5,
                            errors_px=np.linalg.norm(observation.corners_px-points,axis=1).tolist(),
                            errors_normalized=(np.linalg.norm(observation.corners_px-points,axis=1)/diagonal).tolist())
                records.append(record)
            positive=[r for r in records if r["positive"]]
            summary={"epoch":epoch+1,"checkpoint":str(checkpoint),"sha256":digest(checkpoint),
                "misses":sum(not r["matched"] for r in positive),"false_positives":sum(r["detected"] for r in records if not r["positive"]),
                "pixels":stats([v for r in positive for v in r.get("errors_px",[])]),
                "normalized":stats([v for r in positive for v in r.get("errors_normalized",[])]),"records":records}
            reports.append(summary)
            print(run,epoch+1,"misses",summary["misses"],"p95",summary["normalized"]["p95"],flush=True)
            del model
        ranking=sorted(reports,key=lambda r:(r["misses"],r["false_positives"],r["normalized"]["p95"] if r["normalized"]["p95"] is not None else float("inf")))
        payload={"run":run,"checkpoint_count":len(reports),"winner":{k:v for k,v in ranking[0].items() if k!="records"},"epochs":reports,
            "selection_scope":result["scope"]}
        write_json(destination,payload)
        result["runs"][run]=payload["winner"]
    write_json(out/"checkpoint-scan/summary.json",result)
    print(json.dumps(result,indent=2),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--component",choices=("hc","tft"),default="hc")
    parser.add_argument("--runs",nargs="+",required=True)
    parser.add_argument("--budget",type=int,required=True)
    parser.add_argument("--training-root",type=Path)
    args=parser.parse_args()
    scan(args.parent.resolve(),args.out.resolve(),args.component,args.runs,args.budget,
         None if args.training_root is None else args.training_root.resolve())
