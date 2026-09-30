"""Isolated 4/8-point GPIO regression. Never publishes weights or camera settings."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import time

import cv2
import numpy as np

from wiring_pose_data import ROOT, digest, read_label, write_json
from wiring_pose_evaluation import (RuntimeAdapter, configure_snapshot, pin_map,
    j8_errors, stats, box_iou, quad_iou, require_cuda)

PIN_IDS=("3V3_P1","5V_P2","GPIO21","GND_P39")
ORDER=["board_TL","board_TR","board_BR","board_BL","J8_P1","J8_P2","J8_P40","J8_P39"]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def header_shape(prediction,truth):
    """Only four human endpoints; no interpolated pin is promoted to ground truth."""
    p,t=np.asarray(prediction,float),np.asarray(truth,float)
    if p.shape!=(4,2) or t.shape!=(4,2) or not np.isfinite(p).all() or not np.isfinite(t).all():
        return None
    angles=[]
    for start,end in ((0,3),(1,2)):
        a,b=p[end]-p[start],t[end]-t[start]
        if min(np.linalg.norm(a),np.linalg.norm(b))<1e-6:return None
        angles.append(float(abs(np.degrees(np.arctan2(a[0]*b[1]-a[1]*b[0],np.dot(a,b))))))
    t_pitch=np.mean([np.linalg.norm(t[0]-t[1]),np.linalg.norm(t[2]-t[3])])
    if t_pitch<1e-6:return None
    signed=lambda q:float(cv2.contourArea(q.astype(np.float32),oriented=True))
    return {"row_angle_deg":angles,
        "pitch_ratio":float(np.mean([np.linalg.norm(p[0]-p[1]),np.linalg.norm(p[2]-p[3])])/t_pitch),
        "crossed_or_reversed":not cv2.isContourConvex(p.astype(np.float32)) or signed(p)*signed(t)<=0}


def prepare(parent,out):
    if out.exists():raise FileExistsError("new isolated experiment directory required")
    out.mkdir(parents=True)
    frozen=[]
    def freeze(source,relative):
        dest=out/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
        sha=digest(source)
        if digest(dest)!=sha:raise ValueError("snapshot mismatch")
        frozen.append({"source":str(source),"path":relative,"sha256":sha})
        return relative
    original=load(parent/"manifest.json")
    active=original["components"]["pi"]["models"][original["components"]["pi"]["active"]]
    models={"four-current":{"onnx":str(parent/active["onnx"]),"count":4}}
    for name in ("pilot","synth-pilot","synth-negative-pilot"):
        stem="pi5-8kpt-"+name
        onnx=freeze(ROOT/"models"/("board-pose-"+stem+".onnx"),"models/"+stem+".onnx")
        pt=freeze(ROOT/"runs/board-pose"/stem/"weights/best.pt","models/"+stem+".pt")
        freeze(ROOT/"runs/board-pose"/stem/"args.yaml","history/"+stem+"-args.yaml")
        models[name]={"onnx":str(out/onnx),"checkpoint":str(out/pt),"count":8}
    migration=ROOT/"datasets/board-pose-pi5-8kpt/migration-manifest.jsonl"
    freeze(migration,"data/migration-manifest.jsonl")
    originals={}
    for line in migration.read_text(encoding="utf-8").splitlines():
        r=json.loads(line)
        if not r.get("human_reviewed") or r["keypoint_order"]!=ORDER:raise ValueError("unreviewed or ambiguous label")
        originals[(r["split"],r["image"])]=r
    rows=[]
    for (split,_),r in originals.items():
        if split not in ("train","val"):continue
        image,label=migration.parent/r["image"],migration.parent/r["label"]
        values=read_label(label,count=8)
        if values is None or not np.all(values[5:].reshape(8,3)[:,2]>0):raise ValueError("incomplete reviewed eight-point label")
        rows.append({"split":split,"image":freeze(image,"data/"+r["image"]),
            "label":freeze(label,"data/"+r["label"]),"sha256":digest(image),"label_sha256":digest(label),
            "session":r["session_id"],"positive":True,"human_reviewed":True})
    train={r["sha256"] for r in rows if r["split"]=="train"}
    val={r["sha256"] for r in rows if r["split"]=="val"}
    if train & val:raise ValueError("cross-split identical images")
    if {r["session"] for r in rows if r["split"]=="train"} & {r["session"] for r in rows if r["split"]=="val"}:
        raise ValueError("cross-split annotation sessions; capture provenance remains legacy/unknown")
    expected=[r for r in original["components"]["pi"]["records"] if r["split"]=="val" and not r.get("exclusion")]
    val_rows={r["sha256"]:r for r in rows if r["split"]=="val"}
    if set(val_rows)!={r["sha256"] for r in expected}:raise ValueError("validation differs from frozen four-point benchmark")
    for r in expected:
        if r["j8_truth"]["sha256"]!=val_rows[r["sha256"]]["label_sha256"]:raise ValueError("manual J8 truth changed")
    negative=ROOT/"datasets/board-pose-pi5-8kpt-synth-v5"
    for label in sorted((negative/"labels/train").glob("*.txt")):
        if label.read_text(encoding="utf-8").strip():continue
        images=list((negative/"images/train").glob(label.stem+".*"))
        if len(images)!=1:raise ValueError("negative source missing or ambiguous")
        image=images[0]
        if digest(image) in train|val:raise ValueError("negative conflicts with positive")
        rows.append({"split":"negative-stress","positive":False,"sha256":digest(image),
            "image":freeze(image,"negatives/images/"+image.name),"label":freeze(label,"negatives/labels/"+label.name),
            "training_exposed":True})
    payload={"parent":str(parent),"parent_sha256":digest(parent/"manifest.json"),"models":models,"records":rows,
        "frozen":frozen,"counts":dict(Counter(r["split"] for r in rows)),"keypoint_order":ORDER,
        "source_config_sha256":digest(ROOT/"backend/config.yaml"),"production_changed":False,
        "evaluation_scope":"legacy validation previously used for model selection; not independent wired acceptance"}
    write_json(out/"manifest.json",payload)
    print(json.dumps(payload["counts"]),flush=True)


def measure(pins,row,width,height):
    if not all(k in pins for k in PIN_IDS):return None
    values=np.asarray(row["j8_truth"]["points"])
    errors=j8_errors(pins,values,width,height)
    return {**errors,**header_shape([pins[k] for k in PIN_IDS],values[:,:2]*[width,height])}


def summary(records):
    positives=[r for r in records if r["positive"]]
    stages={}
    for stage in ("raw","runtime","anchored_diagnostic"):
        values=[r[stage] for r in positives if r.get(stage)]
        stages[stage]={"frames":len(values),"px":stats([v for r in values for v in r["px"]]),
            "pitch":stats([v for r in values for v in r["pitch"]]),
            "row_angle_deg":stats([v for r in values for v in r["row_angle_deg"]]),
            "crossed_or_reversed":sum(r["crossed_or_reversed"] for r in values),
            "pitch_ratio":stats([r["pitch_ratio"] for r in values]),
            "successful_frames":sum(bool(r.get(stage) and r["matched"] and np.median(r[stage]["pitch"])<=.25
                and np.percentile(r[stage]["pitch"],95)<=.5) for r in positives)}
    return {"positive":len(positives),"misses":sum(not r["matched"] for r in positives),
        "negative":sum(not r["positive"] for r in records),
        "false_positive":sum(not r["positive"] and r["detected"] for r in records),"stages":stages,
        "runtime_modes":dict(Counter(r.get("pose_mode") for r in positives)),
        "pipeline_ms":stats([r.get("pipeline_ms") for r in positives])}


def evaluate(parent,out,names):
    config=configure_snapshot(parent)
    from app.vision.yolo_profile_detector import _anchor_profile_header_from_landmarks
    manifest=load(out/"manifest.json")
    models={**manifest["models"],**(load(out/"candidates.json") if (out/"candidates.json").exists() else {})}
    source=load(parent/"manifest.json")
    rows=[r for r in source["components"]["pi"]["records"] if r["split"]=="val" and not r.get("exclusion")]
    for name in names:
        dest=out/"evaluations"/(name+".json")
        if dest.exists():raise FileExistsError(dest)
        model=models[name]
        cfg=config.model_copy(deep=True)
        cfg.yolo_pose.board_8pt_model_paths={"raspberry-pi-5":Path(model["onnx"])} if model["count"]==8 else {}
        adapter=RuntimeAdapter(parent,"pi",Path(model["onnx"]),cfg)
        records=[]
        try:
            for index,row in enumerate(rows):
                frame=cv2.imread(str(parent/row["image"]))
                h,w=frame.shape[:2]
                adapter.reset()
                raw=adapter.locator.locate(frame)
                started=time.perf_counter()
                result=adapter.process(frame,index,float(index*1000))
                elapsed=(time.perf_counter()-started)*1000
                label=read_label(parent/row["label"])
                cx,cy,bw,bh=label[1:5]*[w,h,w,h]
                matched=bool(raw is not None and box_iou(raw.box_xyxy,[cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2])>=.5)
                truth=label[5:].reshape(4,3)[:,:2]*[w,h]
                record={"key":row["key"],"image":str(parent/row["image"]),"positive":True,
                    "detected":raw is not None,"matched":matched,"pose_mode":getattr(result,"pose_mode",None),
                    "tracking":result.tracking,"pipeline_ms":elapsed,
                    "truth_j8":(np.asarray(row["j8_truth"]["points"])[:,:2]*[w,h]).tolist(),
                    "truth_corners":truth.tolist(),"raw":None,"runtime":None,"anchored_diagnostic":None}
                runtime=pin_map(result.pins)
                record["runtime_pins"]=runtime
                record["runtime"]=measure(runtime,row,w,h)
                record["runtime_matches_board"]=quad_iou(adapter.post_corners,truth)>=.5
                if raw is not None:
                    record["raw_corners"]=raw.corners_px.tolist()
                    base=adapter.raw_pins(raw.corners_px,(w,h))
                    if model["count"]==8:
                        record["landmarks"]=raw.landmarks_px.tolist()
                        record["keypoint_confidences"]=raw.keypoint_confidences.tolist()
                        supported=bool(np.all(np.asarray(raw.keypoint_confidences)[4:]>=adapter.keypoint))
                        points={k:p.tolist() for k,p in zip(PIN_IDS,raw.landmarks_px[4:])} if supported else {}
                        anchored=_anchor_profile_header_from_landmarks(adapter.profile,base,raw,(w,h),keypoint_threshold=adapter.keypoint)
                        record["anchored_diagnostic"]=measure(pin_map(anchored),row,w,h)
                        record["anchor_applied"]=anchored is not base
                    else:points=pin_map(base)
                    record["raw_pins"]=points
                    record["raw"]=measure(points,row,w,h)
                records.append(record)
            for row in manifest["records"]:
                if row["positive"]:continue
                if read_label(out/row["label"],count=8) is not None:raise ValueError("negative is not empty")
                raw=adapter.locator.locate(cv2.imread(str(out/row["image"])))
                records.append({"key":row["image"],"positive":False,"detected":raw is not None})
            backend=require_cuda(adapter.locator)
        finally:adapter.close()
        report={"name":name,"model":model,"model_sha256":digest(Path(model["onnx"])),"records":records,
            "summary":summary(records),"backend":backend,"config":cfg.model_dump(mode="json"),
            "parent_manifest_sha256":digest(parent/"manifest.json"),"experiment_manifest_sha256":digest(out/"manifest.json"),
            "calibrated_pnp_enabled":False,"production_changed":False,"scope":manifest["evaluation_scope"],
            "anchored_diagnostic":"existing bounded 2D endpoint correction on raw board plane; not production output"}
        write_json(dest,report)
        print(name,json.dumps(report["summary"]),flush=True)


def audit_images(parent,out):
    manifest=load(out/"manifest.json")
    rows=[r for r in manifest["records"] if not r["positive"]]
    for start in range(0,len(rows),20):
        cells=[]
        for row in rows[start:start+20]:
            frame=cv2.imread(str(out/row["image"]))
            frame=cv2.resize(frame,(320,180))
            cv2.rectangle(frame,(0,0),(320,23),(20,20,20),-1)
            cv2.putText(frame,Path(row["image"]).stem.replace("negative__","")[:44],(3,16),cv2.FONT_HERSHEY_SIMPLEX,.35,(255,255,255),1)
            cells.append(frame)
        while len(cells)<20:cells.append(np.zeros_like(cells[0]))
        dest=out/"audit"/f"negatives-{start//20}.jpg"
        dest.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(dest),np.vstack([np.hstack(cells[i:i+4]) for i in range(0,20,4)]))


def parity(parent,out,name):
    import onnxruntime as ort
    from wiring_pose_evaluation import compare_tensors,compare_decoded_outputs
    config=configure_snapshot(parent)
    candidate=load(out/"candidates.json")[name]
    config.yolo_pose.board_8pt_model_paths={"raspberry-pi-5":Path(candidate["onnx"])}
    adapter=RuntimeAdapter(parent,"pi",Path(candidate["onnx"]),config)
    directory=Path(candidate["onnx"]).parent
    try:
        strict=ort.InferenceSession(candidate["onnx"],providers=[("CUDAExecutionProvider",{"use_tf32":0}),"CPUExecutionProvider"])
        if strict.get_providers()[0]!="CUDAExecutionProvider":raise RuntimeError("parity CUDA unavailable")
        inputs=np.load(directory/"pt-parity.npz")
        checks=[]
        for index in range(2):
            blob,expected=inputs[f"input_{index}"],inputs[f"output_{index}"]
            exact=strict.run(None,{strict.get_inputs()[0].name:blob})[0]
            actual=adapter.locator._session.run(None,{adapter.locator._input_name:blob})[0]
            # Eight-point parity must include J8, not only the first four corners.
            from app.vision.yolo_pose import decode_yolo_pose_output
            options=adapter.locator._decode_options
            size=options["input_size"]
            decode=lambda x:decode_yolo_pose_output(x,frame_size=(size,size),scale=1.,pad_x=0.,pad_y=0.,**options)
            a,b=decode(expected),decode(actual)
            delta=float(np.max(np.linalg.norm(a.landmarks_px-b.landmarks_px,axis=1))) if a is not None and b is not None else None
            decoded=compare_decoded_outputs(expected,actual,options)
            passed=bool(decoded["passed"] and (delta<=.5 if delta is not None else a is None and b is None))
            checks.append({"tensor":compare_tensors(expected,exact),"decoded":decoded,"all_eight_max_delta_px":delta,"all_eight_passed":passed})
        report={"passed":all(r["tensor"]["allclose"] and r["all_eight_passed"] for r in checks),"checks":checks,
            "onnx_sha256":digest(Path(candidate["onnx"])),"checkpoint_sha256":digest(Path(candidate["checkpoint"]))}
        write_json(directory/"parity.json",report)
        print(json.dumps(report),flush=True)
    finally:adapter.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","evaluate","audit-images","parity"))
    parser.add_argument("--parent",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--models",nargs="+",default=["four-current","pilot","synth-pilot","synth-negative-pilot"])
    args=parser.parse_args()
    parent,out=args.parent.resolve(),args.out.resolve()
    if args.action=="prepare":prepare(parent,out)
    elif args.action=="evaluate":evaluate(parent,out,args.models)
    elif args.action=="audit-images":audit_images(parent,out)
    else:parity(parent,out,args.models[0])
