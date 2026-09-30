"""Stage-level diagnostics on the first frozen experiment; no deployment or relabeling."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import cv2
import numpy as np

from wiring_pose_data import read_label, write_json, digest
from wiring_pose_evaluation import configure_snapshot, pin_map, j8_errors, stats


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def tft_audit(parent,out):
    manifest=load(parent/"manifest.json")
    rows=[r for r in manifest["components"]["tft"]["records"] if r["positive"] and not r["derived"] and r["group"]=="tft:lit-wired-20260925"]
    cells=[]
    for row in rows:
        image=cv2.imread(str(parent/row["image"]))
        h,w=image.shape[:2]
        points=read_label(parent/row["label"])[5:].reshape(4,3)[:,:2]*[w,h]
        for i,p in enumerate(points):
            point=tuple(np.rint(p).astype(int))
            cv2.circle(image,point,5,(0,255,0),1)
            cv2.putText(image,str(i+1),point,cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,0),1)
        pad=25
        x0,y0=np.maximum(0,np.floor(points.min(0)).astype(int)-pad)
        x1,y1=np.minimum([w,h],np.ceil(points.max(0)).astype(int)+pad)
        crop=image[y0:y1,x0:x1]
        scale=min(400/crop.shape[1],320/crop.shape[0])
        crop=cv2.resize(crop,None,fx=scale,fy=scale)
        cell=np.full((350,420,3),30,np.uint8)
        cell[30:30+crop.shape[0],:crop.shape[1]]=crop
        cv2.putText(cell,Path(row["image"]).name,(3,18),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
        cells.append(cell)
    for start in range(0,len(cells),9):
        chunk=cells[start:start+9]
        while len(chunk)<9:chunk.append(np.zeros_like(cells[0]))
        target=out/"tft-label-audit"/f"review-{start//9}.jpg"
        target.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(target),np.vstack([np.hstack(chunk[i:i+3]) for i in (0,3,6)]))
    write_json(out/"tft-label-audit/sources.json",{"keys":[r["key"] for r in rows],"count":len(rows),
        "scope":"previously trained-on labels; visual semantics audit, not a new holdout"})


def tft_compare(parent,out):
    from wiring_pose_evaluation import evaluate
    config=configure_snapshot(parent)
    manifest=load(parent/"manifest.json")
    keys=set(load(out/"tft-label-audit/sources.json")["keys"])
    reports={}
    for name,model in manifest["components"]["tft"]["models"].items():
        destination=out/"evaluations/tft"/(name+"-lit-regression.json")
        if destination.exists():raise FileExistsError(destination)
        report=evaluate(parent,"tft",parent/model["onnx"],name+"-lit-regression",config,
            splits=("train",),record_keys=keys,artifact_root=out)
        reports[name]=report["summary"]
        print(name,json.dumps(report["summary"]),flush=True)
    write_json(out/"tft-clean-regression.json",{"summaries":reports,"scope":"29 historical training examples with mounting-hole labels; not held out",
        "original_quarantine_unchanged":True,"labels_changed":False,"production_changed":False})


def tft_guard(parent,out):
    from wiring_pose_evaluation import evaluate,cache_signature,evaluation_signature
    from wiring_pose_candidates import orientation_consensus
    config=configure_snapshot(parent)
    import app.vision.tft_ring_geometry as geometry
    original=geometry.orient_tft_from_panel_inset
    geometry.orient_tft_from_panel_inset=orientation_consensus(original)
    try:
        model=load(parent/"manifest.json")["components"]["tft"]["models"]["v3-last"]
        keys=set(load(out/"tft-label-audit/sources.json")["keys"])
        rows=[r for r in load(parent/"manifest.json")["components"]["tft"]["records"] if r["key"] in keys]
        overlay_sha=digest(Path(__file__).with_name("wiring_pose_candidates.py"))
        signature=cache_signature(digest(parent/model["onnx"]),
            evaluation_signature(parent,"tft",parent/model["onnx"],config,rows=rows),{"variant":"orientation-consensus-v2"},overlay_sha)
        report=evaluate(parent,"tft",parent/model["onnx"],"v3-last-orientation-consensus-v2",config,
            splits=("train",),record_keys=keys,artifact_root=out,signature=signature)
        report["candidate_overlay"]={"variant":"orientation-consensus-v2","sha256":overlay_sha}
        write_json(out/"evaluations/tft/v3-last-orientation-consensus-v2.json",report)
        print(json.dumps(report["summary"],indent=2))
    finally:geometry.orient_tft_from_panel_inset=original


def patches(parent,out):
    result=load(out/"diagnosis.json")
    rows={r["key"]:r for r in load(parent/"manifest.json")["components"]["pi"]["records"]}
    records=[r for r in result["pi_records"] if "runtime_quad/plane" in r["stages"]]
    records.sort(key=lambda r:max(r["stages"]["runtime_quad/contacts"]["error"]["pitch"]),reverse=True)
    cells=[]
    for record in records[:12]:
        row=rows[record["key"]]
        frame=cv2.imread(str(parent/row["image"]))
        h,w=frame.shape[:2]
        pins=record["stages"]["runtime_quad/plane"]["pins"]
        source=np.float32([pins[k] for k in ("3V3_P1","GND_P39","GPIO21","5V_P2")])
        target=np.float32([[24,36],[252,36],[252,48],[24,48]])
        transform=cv2.getPerspectiveTransform(source,target)
        image=cv2.warpPerspective(frame,transform,(276,100),borderValue=(255,255,255))
        truth=np.float32(row["j8_truth"]["points"])[:,:2]*[w,h]
        projected=cv2.perspectiveTransform(truth.astype(np.float32).reshape(-1,1,2),transform).reshape(-1,2)
        for i,point in enumerate(projected):
            cv2.circle(image,tuple(np.rint(point).astype(int)),2,(0,255,0),1)
        for point in target:cv2.circle(image,tuple(point.astype(int)),2,(0,128,255),1)
        image=cv2.resize(image,(828,300))
        cv2.rectangle(image,(0,0),(828,24),(15,15,15),-1)
        cv2.putText(image,record["key"]+"   green=human, orange=planar",(5,16),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
        cells.append(image)
    for start in range(0,len(cells),4):
        target=out/"j8-patches"/f"worst-{start//4}.jpg"
        target.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(target),np.vstack(cells[start:start+4]))


def height_ablation(parent,out):
    """Test existing physical z geometry offline; never declare a camera calibrated."""
    configure_snapshot(parent)
    from app.profiles.store import ProfileStore
    from app.vision.camera_model import default_camera
    from app.vision.yolo_profile_detector import _project_profile_height_on_observed_quad, solve_profile_pose
    from app.vision.eye_j8 import correct_eye_j8_from_image
    manifest=load(parent/"manifest.json")
    rows={r["key"]:r for r in manifest["components"]["pi"]["records"]}
    profile=ProfileStore(parent/"snapshot/profiles").profile("raspberry-pi-5")
    reports=[]
    for record in load(parent/"evaluations/pi/guided.json")["records"]:
        row=rows[record["key"]]
        if "j8_truth" not in row:continue
        frame=cv2.imread(str(parent/row["image"]))
        h,w=frame.shape[:2]
        truth=read_label(parent/row["label"])[5:].reshape(4,3)[:,:2]*[w,h]
        stages={}
        for name,corners in (("runtime_quad",record["post_corners"]),("human_board_oracle",truth)):
            if corners is None:continue
            camera=default_camera((w,h))
            solved=solve_profile_pose(profile.board.outline_mm,np.asarray(corners),camera)
            if solved is None:continue
            rvec,tvec,reprojection=solved
            pins,_=_project_profile_height_on_observed_quad(profile,corners,(w,h),1.,camera,rvec,tvec)
            evidence={}
            contacts=correct_eye_j8_from_image(frame,profile,pins,(w,h),diagnostic=evidence)
            for suffix,points in (("height",pins),("height_contacts",contacts)):
                stages[name+"/"+suffix]={"error":j8_errors(pin_map(points),row["j8_truth"]["points"],w,h),"pins":pin_map(points)}
        reports.append({"key":row["key"],"stages":stages})
    names=sorted({s for r in reports for s in r["stages"]})
    summary={s:{u:stats([e for r in reports if s in r["stages"] for e in r["stages"][s]["error"][u]]) for u in ("px","pitch")} for s in names}
    result={"summary":summary,"records":reports,"scope":"geometry ablation with approximate intrinsics; not calibrated, not deployed"}
    write_json(out/"height-ablation.json",result)
    print(json.dumps(summary,indent=2))


def analyze(parent, out):
    if (out/"diagnosis.json").exists():
        raise FileExistsError("Use a new follow-up directory; existing evidence is immutable")
    configure_snapshot(parent)
    from app.profiles.store import ProfileStore
    from app.vision.yolo_profile_detector import _project_profile_on_observed_quad
    from app.vision.pi5_j8_geometry import align_pi5_j8
    from app.vision.eye_j8 import correct_eye_j8_from_image

    manifest=load(parent/"manifest.json")
    profile=ProfileStore(parent/"snapshot/profiles").profile("raspberry-pi-5")
    baseline=load(parent/"evaluations/pi/guided.json")
    rows={r["key"]:r for r in manifest["components"]["pi"]["records"]}
    results=[]
    for record in baseline["records"]:
        row=rows[record["key"]]
        if "j8_truth" not in row: continue
        frame=cv2.imread(str(parent/row["image"]))
        height,width=frame.shape[:2]
        truth=read_label(parent/row["label"])[5:].reshape(4,3)[:,:2]*[width,height]
        result={"key":record["key"],"image":row["image"],"tracking":record["tracking"],"stages":{}}
        for source,corners in (("model",record["raw_corners"]),("runtime_quad",record["post_corners"]),("human_board_oracle",truth)):
            if corners is None:continue
            pins,_=_project_profile_on_observed_quad(profile,corners,(width,height),1.)
            housing=align_pi5_j8(frame,profile,pins,(width,height))
            diagnostic={}
            contacts=correct_eye_j8_from_image(frame,profile,housing,(width,height),diagnostic=diagnostic)
            contact_only_diagnostic={}
            contact_only=correct_eye_j8_from_image(frame,profile,pins,(width,height),diagnostic=contact_only_diagnostic)
            for stage,points in (("plane",pins),("housing",housing),("contacts",contacts),("contacts_only",contact_only)):
                error=j8_errors(pin_map(points),row["j8_truth"]["points"],width,height)
                result["stages"][source+"/"+stage]={"error":error,"pins":pin_map(points)}
            result[source+"_contact_evidence"]=diagnostic
            result[source+"_contact_only_evidence"]=contact_only_diagnostic
        results.append(result)
    stages=sorted({s for r in results for s in r["stages"]})
    summary={s:{unit:stats([e for r in results if s in r["stages"] for e in r["stages"][s]["error"][unit]]) for unit in ("px","pitch")} for s in stages}
    reasons={source:dict(Counter(r.get(source+"_contact_evidence",{}).get("reason","no_quad") for r in results)) for source in ("model","runtime_quad","human_board_oracle")}
    hc={}
    for name in ("v3","hc-A-seed0","hc-A-seed1"):
        report=load(parent/"evaluations/hc"/(name+".json"))
        groups=defaultdict(list)
        for row in report["records"]:groups[row["group"]].append(row)
        hc[name]={g:{"count":len(rows),"misses":sum(not r.get("matched_detection",False) for r in rows),
            "error":stats([e for r in rows for e in r.get("raw_corner_diagonal",[])])} for g,rows in groups.items()}
    payload={"parent":str(parent),"parent_manifest_sha256":digest(parent/"manifest.json"),"pi_stages":summary,"pi_contact_reasons":reasons,
        "pi_records":results,"hc_by_capture":hc,"oracle_is_diagnostic_only":True,"production_changed":False}
    write_json(out/"diagnosis.json",payload)
    print(json.dumps({"pi_stages":summary,"pi_contact_reasons":reasons,"hc_by_capture":hc},indent=2))
    return payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--patches",action="store_true")
    parser.add_argument("--height-ablation",action="store_true")
    parser.add_argument("--tft-audit",action="store_true")
    parser.add_argument("--tft-compare",action="store_true")
    parser.add_argument("--tft-guard",action="store_true")
    args=parser.parse_args()
    if args.tft_guard:tft_guard(args.parent.resolve(),args.out.resolve())
    elif args.tft_compare:tft_compare(args.parent.resolve(),args.out.resolve())
    elif args.tft_audit:tft_audit(args.parent.resolve(),args.out.resolve())
    elif args.height_ablation:height_ablation(args.parent.resolve(),args.out.resolve())
    elif args.patches:patches(args.parent.resolve(),args.out.resolve())
    else:analyze(args.parent.resolve(),args.out.resolve())


if __name__=="__main__":main()
