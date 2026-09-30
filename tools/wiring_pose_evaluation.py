"""Offline CUDA comparison against frozen inputs and the frozen production workers."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np

from wiring_pose_data import IDS, SPECS, digest, read_label, write_json


def configure_snapshot(out: Path):
    backend = str((out / "snapshot/backend").resolve())
    if "app" in sys.modules and not str(sys.modules["app"].__file__).startswith(backend):
        raise RuntimeError("run evaluation in a fresh process using the frozen backend")
    sys.path.insert(0, backend)
    from app.config import load_config
    config = load_config(out / "snapshot/backend/config.yaml")
    config.profile_dir = out / "snapshot/profiles"
    config.yolo_pose.pi_reference_recovery_model_path = out / "snapshot/models/pi-reference.onnx"
    config.camera.calibration_path = out / "snapshot/calibration/camera.json" if (out / "snapshot/calibration/camera.json").is_file() else None
    config.yolo_pose.board_8pt_model_paths = {}
    for target in config.component_vision.components:
        target.profile_path = config.profile_dir / "components" / target.id / "vision_profile.json"
    return config


def stats(values):
    finite = [float(v) for v in values if v is not None and np.isfinite(v)]
    return {"count":len(finite), "median":float(np.median(finite)) if finite else None,
            "p95":float(np.percentile(finite,95)) if finite else None}


def compare_tensors(expected,actual,rtol=.001,atol=.01):
    same_shape=expected.shape==actual.shape
    valid=same_shape and expected.size>0 and np.isfinite(expected).all() and np.isfinite(actual).all()
    return {"same_shape":same_shape,"max_abs_error":float(np.max(np.abs(expected-actual))) if valid else None,
            "allclose":bool(valid and np.allclose(expected,actual,rtol=rtol,atol=atol))}


def box_iou(a,b):
    a,b=np.asarray(a,float),np.asarray(b,float)
    intersection=float(np.prod(np.maximum(0,np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2]))))
    area_a=float(np.prod(np.maximum(0,a[2:]-a[:2])))
    area_b=float(np.prod(np.maximum(0,b[2:]-b[:2])))
    return intersection/max(area_a+area_b-intersection,1e-12)


def quad_iou(a,b):
    if a is None or b is None:return 0.
    a,b=np.asarray(a,np.float32),np.asarray(b,np.float32)
    if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():return 0.
    a,b=cv2.convexHull(a),cv2.convexHull(b)
    area_a,area_b=cv2.contourArea(a),cv2.contourArea(b)
    if min(area_a,area_b)<=1e-9:return 0.
    intersection=float(cv2.intersectConvexConvex(a,b)[0])
    return intersection/max(area_a+area_b-intersection,1e-12)


def compare_decoded_outputs(expected,actual,options):
    from app.vision.yolo_pose import decode_yolo_pose_output
    size=options["input_size"]
    decode=lambda tensor:decode_yolo_pose_output(tensor,frame_size=(size,size),scale=1.,pad_x=0.,pad_y=0.,**options)
    a,b=decode(expected),decode(actual)
    if a is None or b is None:
        return {"passed":a is None and b is None,"same_detection_presence":a is None and b is None,
                "max_corner_delta_px":None,"confidence_delta":None}
    delta=float(np.max(np.linalg.norm(a.corners_px-b.corners_px,axis=1)))
    confidence=abs(float(a.confidence)-float(b.confidence))
    return {"passed":delta<=.5 and confidence<=.002,"same_detection_presence":True,
            "max_corner_delta_px":delta,"confidence_delta":confidence}


def cache_signature(model_sha, frame_sha, options, runtime_sha):
    text = json.dumps([model_sha,frame_sha,options,runtime_sha],sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def evaluation_signature(out,component,model,config,rows=None):
    manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
    if rows is None:
        rows=[r for r in manifest["components"][component]["records"] if r["split"]=="val" and not r.get("exclusion")]
    inputs=[(r["key"],digest(out/r["image"]),digest(out/r["label"]),r.get("j8_truth")) for r in rows]
    runtime=[(r["snapshot"],digest(out/r["snapshot"])) for r in manifest["frozen_files"] if r["snapshot"].startswith("snapshot/") and not r["snapshot"].startswith("snapshot/models/")]
    return cache_signature(digest(model),inputs,{"runtime":config.model_dump(mode="json"),"metric_schema":4},runtime)


def evaluate_if_needed(out,component,model,name,config):
    signature=evaluation_signature(out,component,model,config)
    dest=out/"evaluations"/component/(name+".json")
    if dest.exists():
        existing=json.loads(dest.read_text(encoding="utf-8"))
        if existing.get("evaluation_signature")==signature:
            return existing
    return evaluate(out,component,model,name,config,signature=signature)


def unwrap(locator):
    return getattr(locator, "original", locator)


def require_cuda(locator):
    base = unwrap(locator)
    diagnostics = base.diagnostics() if hasattr(base,"diagnostics") else {}
    if diagnostics.get("actual_backend") != "cuda":
        raise RuntimeError(f"CUDA comparison rejected fallback: {diagnostics}")
    return diagnostics


class RuntimeAdapter:
    """Use the real worker body synchronously. Never start FastAPI or a camera."""
    def __init__(self, out, component, model, config, state=None):
        from app.main import _build_component_pose_worker, _build_detector
        from app.profiles.store import ProfileStore
        from app.component_worker import ComponentPoseState
        self.component, self.config = component, config.model_copy(deep=True)
        self.post_corners, self.last_result = None, None
        self.worker = self.detector = None
        if component == "pi":
            self.config.yolo_pose.model_path = model
            self.config.yolo_pose.board_model_paths[IDS[component]] = model
            self.config.yolo_pose.runtime_backend = "cuda"
            store = ProfileStore(self.config.profile_dir)
            self.profile = store.profile(IDS[component])
            self.detector = _build_detector(self.config,self.profile,store.board_dir(IDS[component]),None)
            self.primary = getattr(self.detector,"primary",self.detector)
            self.locator = unwrap(self.primary._locator)
            self.confidence = self.config.yolo_pose.confidence_threshold_for(IDS[component])
            self.keypoint = self.config.yolo_pose.keypoint_threshold
        else:
            self.config.component_vision.runtime_backend = "cuda"
            target = next(t for t in self.config.component_vision.components if t.id == IDS[component])
            target.model_path = model
            self.worker = _build_component_pose_worker(config=self.config,target=target,bus=None,
                component_pose_state=state or ComponentPoseState(),broadcaster=SimpleNamespace(publish_threadsafe=lambda _:None))
            self.profile = self.worker._profile
            self.locator = unwrap(self.worker._locator)
            self.confidence = target.confidence_threshold
            self.keypoint = target.keypoint_threshold
            # Scheduling is replaced by recorded timestamps; geometry remains production code.
            self.worker._wait_with_reacquisition_frames = lambda last_seq, remaining_s=None:last_seq
            update = self.worker._tracker.update
            def capture(frame, observation, **kwargs):
                self.post_corners = None if observation is None else observation.corners_px.copy()
                result = update(frame,observation,**kwargs)
                self.semantic_outline = None if result.outline_px is None else np.asarray(result.outline_px).copy()
                return result
            self.worker._tracker.update = capture
            publish = self.worker._publish_result
            def capture_result(result,slot=None):
                self.last_result = result
                publish(result,slot)
            self.worker._publish_result = capture_result
        self.diagnostics = require_cuda(self.locator)

    def reset(self):
        if self.worker:
            self.worker.reset_tracking()
        else:
            self.detector.reset_for_camera(horizontal_fov_deg=self.config.camera.horizontal_fov_deg,
                camera_calibration_path=self.config.camera.calibration_path,
                use_camera_calibration=self.config.camera.source != "xreal")

    def process(self, frame, frame_id=0, ts_ms=0.):
        self.post_corners, self.last_result = None,None
        if self.detector:
            result = self.detector.detect(frame,frame_id,ts_ms)
            self.post_corners = None if result.outline_px is None else np.asarray(result.outline_px)
            self.last_result = result
            return result
        from app.capture.bus import FrameSlot
        used = False
        self.worker._stop = threading.Event()
        def next_frame(**kwargs):
            nonlocal used
            if used:
                self.worker._stop.set()
                return None
            used = True
            return FrameSlot(frame,frame_id,ts_ms,frame_id)
        self.worker._bus = SimpleNamespace(get_latest=next_frame)
        self.worker._run()
        if self.last_result is None:
            raise RuntimeError("production worker swallowed an exception; no frame result")
        return self.last_result

    def raw_pins(self,corners,size):
        if self.component == "pi":
            from app.vision.yolo_profile_detector import _project_profile_on_observed_quad
            pins,_ = _project_profile_on_observed_quad(self.profile,corners,size,1.)
        else:
            from app.component_worker import project_component_pins
            pins = project_component_pins(self.profile,corners,1.,size)
        return pins

    def close(self):
        if self.worker:
            self.worker.stop()
        else:
            self.detector.close()


def pin_map(pins):
    return {getattr(p,"pin_id",getattr(p,"id",None)):[float(p.x),float(p.y)] for p in pins}


def j8_errors(pins, truth, width, height):
    ids = ["3V3_P1","5V_P2","GPIO21","GND_P39"]
    values = np.asarray(truth,dtype=float)
    expected = values[:,:2]*[width,height]
    pitch = float(np.mean([np.linalg.norm(expected[0]-expected[1]),np.linalg.norm(expected[2]-expected[3])]))
    known = values[:,2] > 0
    if not all(k in pins for k in ids) or not known.any() or pitch <= 0:
        return None
    error = np.linalg.norm(np.asarray([pins[k] for k in ids])-expected,axis=1)[known]
    return {"px":error.tolist(),"pitch":(error/pitch).tolist(),"pitch_px":pitch}


def summarize(records):
    positive = [r for r in records if r["positive"]]
    negative = [r for r in records if not r["positive"]]
    detected = [r for r in positive if r.get("matched_detection",r["raw_detected"])]
    j8_rows = [r for r in positive if r.get("has_j8_truth")]
    def flatten(field):
        return [v for r in positive for v in r.get(field,[])]
    return {"positive":len(positive),"negative":len(negative),"detected":len(detected),
        "missed":len(positive)-len(detected),"false_positive":sum(r["raw_detected"] for r in negative),
        "wrong_object_predictions":sum(r["raw_detected"] and not r.get("matched_detection",True) for r in positive),
        "detection_rate":len(detected)/len(positive) if positive else None,
        "raw_corner_px":stats(flatten("raw_corner_px")),"raw_corner_diagonal":stats(flatten("raw_corner_diagonal")),
        "post_corner_px":stats(flatten("post_corner_px")),"post_corner_diagonal":stats(flatten("post_corner_diagonal")),
        "raw_j8_px":stats(flatten("raw_j8_px")),"raw_j8_pitch":stats(flatten("raw_j8_pitch")),
        "runtime_j8_px":stats(flatten("runtime_j8_px")),"runtime_j8_pitch":stats(flatten("runtime_j8_pitch")),
        "j8_truth_images":len(j8_rows),"j8_raw_localized":sum(bool(r.get("raw_j8_px")) for r in j8_rows),
        "raw_localization_success":sum(r.get("raw_localization_pass",False) for r in positive)/len(positive) if positive else None,
        "runtime_locked":sum(r["tracking"]=="locked" for r in records),
        "runtime_pin_frames":sum(bool(r.get("runtime_pins")) for r in records),
        "post_localized_positive":sum(bool(r.get("runtime_j8_px") if r.get("has_j8_truth") else r.get("post_corner_px"))
                                      and quad_iou(r.get("post_corners"),r.get("truth_corners"))>=.5 for r in positive),
        "post_emitted_positive":sum(bool(r.get("runtime_j8_px") if r.get("has_j8_truth") else r.get("post_corner_px")) for r in positive),
        "locate_ms":stats([r.get("locate_ms") for r in records]),
        "pipeline_ms":stats([r.get("pipeline_ms") for r in records])}


def evaluate(out, component, model, name, config, splits=("val",),signature=None,negative_only=False,
             *,record_keys=None,artifact_root=None):
    manifest = json.loads((out/"manifest.json").read_text(encoding="utf-8"))
    spec = manifest["components"][component]
    rows = [r for r in spec["records"] if r["split"] in splits and not r.get("exclusion")]
    if record_keys is not None:
        rows=[r for r in rows if r["key"] in record_keys]
        if {r["key"] for r in rows}!=set(record_keys):raise ValueError("requested evaluation subset includes missing or excluded records")
    if not rows:raise ValueError("empty evaluation subset")
    if negative_only:
        rows = list({r["sha256"]:r for r in rows if not r["positive"] and not r["derived"]}.values())
    adapter = RuntimeAdapter(out,component,model,config)
    records = []
    try:
        for n,row in enumerate(rows):
            frame = cv2.imread(str(out/row["image"]))
            label = read_label(out/row["label"])
            height,width = frame.shape[:2]
            adapter.reset()
            start = time.perf_counter()
            raw = adapter.locator.locate(frame)
            locate_ms = (time.perf_counter()-start)*1000
            require_cuda(adapter.locator)
            start = time.perf_counter()
            result = adapter.process(frame,n,float(n*1000))
            pipeline_ms = (time.perf_counter()-start)*1000
            r = {"key":row["key"],"image":row["image"],"image_sha256":row["sha256"],
                 "group":row["group"],"positive":label is not None,"raw_detected":raw is not None,
                 "tracking":result.tracking,"locate_ms":locate_ms,"pipeline_ms":pipeline_ms,
                 "raw_corners":None if raw is None else raw.corners_px.tolist(),
                 "raw_box":None if raw is None else list(raw.box_xyxy),
                 "post_corners":None if adapter.post_corners is None else adapter.post_corners.tolist(),
                 "runtime_pins":pin_map(result.pins),"has_j8_truth":"j8_truth" in row,
                 "runtime_visible_pins":pin_map([p for p in result.pins if getattr(p,"visible",True)]),
                 "runtime_reason":getattr(result,"tracking_reason",None) or getattr(result,"pose_stability_state",None),
                 "scope":"state_reset_per_still; runtime acquisition may suppress pins"}
            if label is not None:
                cx,cy,bw,bh=label[1:5]*[width,height,width,height]
                r["truth_box"]=[cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2]
                r["box_iou"]=0. if raw is None else box_iou(raw.box_xyxy,r["truth_box"])
                r["matched_detection"]=bool(raw is not None and r["box_iou"]>=.5)
                truth = label[5:].reshape(4,3)
                points = truth[:,:2]*[width,height]
                known = truth[:,2] > 0
                diagonal = max(float(np.linalg.norm(points[2]-points[0])),1.)
                r["truth_corners"] = points.tolist()
                for stage,corners in (("raw",None if raw is None else raw.corners_px),("post",adapter.post_corners)):
                    if corners is not None:
                        errors = np.linalg.norm(corners-points,axis=1)[known]
                        r[stage+"_corner_px"] = errors.tolist()
                        r[stage+"_corner_diagonal"] = (errors/diagonal).tolist()
                r["raw_localization_pass"] = bool(r["matched_detection"] and max(r["raw_corner_diagonal"]) <= .02)
                if "j8_truth" in row:
                    j8_ids=["3V3_P1","5V_P2","GPIO21","GND_P39"]
                    r["truth_j8"]={k:(np.asarray(v[:2])*[width,height]).tolist() for k,v in zip(j8_ids,row["j8_truth"]["points"])}
                    for stage,pins in (("raw",{} if raw is None else pin_map(adapter.raw_pins(raw.corners_px,(width,height)))),("runtime",r["runtime_pins"])):
                        if stage=="raw":r["raw_j8_pins"]={k:v for k,v in pins.items() if k in j8_ids}
                        errors = j8_errors(pins,row["j8_truth"]["points"],width,height)
                        if errors:
                            r[stage+"_j8_px"] = errors["px"]
                            r[stage+"_j8_pitch"] = errors["pitch"]
                            if stage == "raw":
                                r["raw_localization_pass"] = bool(r["matched_detection"] and np.median(errors["pitch"]) <= .25 and np.percentile(errors["pitch"],95) <= .5)
            records.append(r)
    finally:
        adapter.close()
    report = {"component":component,"name":name,"model":str(model),"model_sha256":digest(model),
              "evaluation_signature":signature or evaluation_signature(out,component,model,config,rows=rows),
              "evaluated_splits":list(splits),"subset_explicit":record_keys is not None,
              "negative_only_training_exposed_stress":negative_only,
              "backend":adapter.diagnostics,"thresholds":{"confidence":adapter.confidence,"keypoint":adapter.keypoint},
              "summary":summarize(records),"records":records,"independent_wired_test":False,"positive_match_iou":.5,"post_match_quad_iou":.5,"metric_schema":4,
              "limitations":["Legacy validation was used in historical selection.",
                             "Raw Pi pin error is the planar model/profile projection; runtime pins include subsequent geometry gates.",
                             "Component stills use the production worker without a contemporaneous peer component; joint replay tests peer gates.",
                             "Still pipeline results reset state per image; not a temporal or live FPS benchmark."]}
    write_json((artifact_root or out)/("negative-stress" if negative_only else "evaluations")/component/(name+".json"),report)
    return report


def score(report):
    s=report["summary"]
    field="raw_j8_pitch" if report["component"]=="pi" else "raw_corner_diagonal"
    error=s[field]["p95"]
    # Never win just by refusing difficult frames. Detection constraints come first.
    return (s["missed"],s["false_positive"],error if error is not None else float("inf"))


def gate(baseline,candidate):
    # Recompute both sides from saved coordinates when migrating metrics.
    # Wrong-object output is not localization coverage; preserve its emitted
    # count separately so abstention is visible, not hidden by the gate.
    for report in (baseline,candidate):
        if "records" in report:report["summary"]=summarize(report["records"])
    b,c=baseline["summary"],candidate["summary"]
    for report, summary in ((baseline,b),(candidate,c)):
        if "post_localized_positive" not in summary and "records" in report:
            summary["post_localized_positive"] = summarize(report["records"])["post_localized_positive"]
    field="raw_j8_pitch" if candidate["component"]=="pi" else "raw_corner_diagonal"
    bp,cp=b[field]["p95"],c[field]["p95"]
    improvement=None if bp is None or cp is None or bp<=0 else 1-cp/bp
    checks={"misses_not_increased":c["missed"]<=b["missed"],
            "false_positives_not_increased":c["false_positive"]<=b["false_positive"],
            "localization_success_not_lower":c["raw_localization_success"] is not None and c["raw_localization_success"]>=b["raw_localization_success"],
            "p95_improves_15_percent":improvement is not None and improvement>=.15}
    post_field="runtime_j8_pitch" if candidate["component"]=="pi" else "post_corner_diagonal"
    post_base,post_candidate=b.get(post_field,{}).get("p95"),c.get(post_field,{}).get("p95")
    post_improvement=None if post_base is None or post_candidate is None or post_base<=0 else 1-post_candidate/post_base
    # A better raw model is not enough when production geometry cancels its benefit.
    checks["production_p95_improves_15_percent"] = post_improvement is not None and post_improvement>=.15
    checks["production_coverage_not_lower"] = c.get("post_localized_positive",0)>=b.get("post_localized_positive",0)
    return {"checks":checks,"p95_improvement":improvement,"regression_gate_passed":all(checks.values()),
            "production_p95_improvement":post_improvement,
            "negative_evidence_available":b["negative"]>0,"independent_wired_acceptance":"not_available",
            "production_promotion":False}


def comparison_images(out,component,baseline,candidate,limit=8,*,artifact_root=None):
    by_key={r["key"]:r for r in baseline["records"]}
    ranked=sorted(candidate["records"],key=lambda r: (not r["raw_detected"],max(r.get("raw_corner_diagonal",[0]))),reverse=True)
    paths=[]
    for i,row in enumerate(ranked[:limit]):
        panels=[]
        for title,result in (("BASELINE",by_key[row["key"]]),("CANDIDATE",row)):
            frame=cv2.imread(str(out/result["image"]))
            scale=np.array([640/frame.shape[1],360/frame.shape[0]])
            frame=cv2.resize(frame,(640,360))
            for key,color,prefix,offset in (("truth_corners",(60,220,60),"G",(3,16)),
                                            ("raw_corners",(0,170,255),"R",(3,31)),
                                            ("post_corners",(255,180,0),"P",(3,-7))):
                if result.get(key) is not None:
                    pts=np.rint(np.asarray(result[key])*scale).astype(np.int32)
                    cv2.polylines(frame,[pts],True,color,2)
                    for j,p in enumerate(pts):
                        anchor=tuple(np.clip(p+offset,[0,14],[608,354]))
                        label=prefix+str(j+1)
                        cv2.putText(frame,label,anchor,cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,0),3)
                        cv2.putText(frame,label,anchor,cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
            for key,color in (("truth_j8",(60,220,60)),("raw_j8_pins",(0,170,255)),("runtime_pins",(255,180,0))):
                for pin,point in result.get(key,{}).items():
                    if pin in result.get("truth_j8",{}):
                        cv2.circle(frame,tuple(np.rint(np.asarray(point)*scale).astype(int)),3,color,1)
            cv2.rectangle(frame,(0,0),(640,45),(20,20,20),-1)
            cv2.putText(frame,title+" "+str(result["tracking"]),(8,20),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
            cv2.putText(frame,"G=label (green) R=model (orange) P=postprocess (blue)",(8,39),cv2.FONT_HERSHEY_SIMPLEX,.4,(230,230,230),1)
            panels.append(frame)
        path=(artifact_root or out)/"comparisons"/component/candidate["name"]/f"case-{i+1:02d}.jpg"
        path.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(path),np.hstack(panels))
        paths.append(str(path.relative_to(artifact_root or out)))
    return paths
