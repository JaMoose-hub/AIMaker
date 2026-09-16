"""Replay saved JPEG sequences through the production component worker.

Caches raw model observations so before/after changes see identical inputs.
This is offline development evidence, not live FPS, pin truth or cloud testing.
"""
from __future__ import annotations

import argparse
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.capture.bus import FrameSlot
from app.component_worker import ComponentPoseState
from app.config import load_config
from app.main import _build_component_pose_worker
from app.vision.yolo_pose import BoardPoseObservation


def encode(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def decode(value):
    if value is None:
        return None
    return BoardPoseObservation(
        np.asarray(value["corners_px"], dtype=float), value["confidence"],
        np.asarray(value["keypoint_confidences"], dtype=float), tuple(value["box_xyxy"]),
        np.asarray(value["landmarks_px"], dtype=float) if value["landmarks_px"] is not None else None,
    )


class ReplayStop(threading.Event):
    def wait(self, timeout=None):
        # Source timestamps, not sleeping, drive production temporal checks.
        return self.is_set()


def replay(case, cid, cache_path, config, interval_ms, visual_continuity=False, motion_handoff=False):
    cv2.setRNGSeed(7)
    target = next(t for t in config.component_vision.components if t.id == cid)
    samples = json.loads((case / "samples.json").read_text(encoding="utf-8"))
    selected = []
    for sample in samples:
        if not selected or sample["ts_ms"] - selected[-1]["ts_ms"] >= interval_ms:
            selected.append(sample)
    outputs, inputs = [], []
    signatures = {"component": config.component_vision.model_dump(mode="json"),
                  "model_sha256": hashlib.sha256(target.model_path.read_bytes()).hexdigest(),
                  "interval_ms": interval_ms}
    cached = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else None
    if cached and (cached["signature"] != signatures or len(cached["inputs"]) != len(selected)):
        raise ValueError("Cache settings/count differ from this replay")
    worker = _build_component_pose_worker(config=config, target=target, bus=None,
        component_pose_state=ComponentPoseState(),
        broadcaster=SimpleNamespace(publish_threadsafe=outputs.append))
    locator = worker._locator
    # Explicit A/B modes, even when the normal builder opts in Webcam parts.
    worker._tracker.visual_continuity = None
    if visual_continuity or motion_handoff:
        from app.vision.pose_continuity import PoseContinuity
        worker._tracker.visual_continuity = PoseContinuity()
    worker._tracker.motion_handoff = motion_handoff
    publish = worker._publish_result
    def capture_result(result, slot):
        publish(result, slot)
        # Match MotionOverlayWorker's semantic seed, including the raw quad
        # that can corroborate flow while the worker deliberately holds pins.
        outputs[-1]['motion_outline'] = result.motion_outline_px.tolist() if result.motion_outline_px is not None else None
        outputs[-1]['source_sha256'] = inputs[-1]['sha256']
    worker._publish_result = capture_result
    cursor = [-1]

    def locate(frame):
        entry = inputs[-1]
        if cached:
            observation = decode(cached["inputs"][cursor[0]]["observation"])
        else:
            observation = locator.locate(frame)
        entry["observation"] = asdict(observation) if observation is not None else None
        return observation

    def next_frame(**kwargs):
        cursor[0] += 1
        if cursor[0] >= len(selected):
            worker._stop.set()
            return None
        sample = selected[cursor[0]]
        path = case / sample["image_path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = {"image_path": sample["image_path"], "sha256": digest,
                    "frame_id": sample["frame_id"], "ts_ms": sample["ts_ms"]}
        if cached and any(cached["inputs"][cursor[0]][key] != value for key, value in identity.items()):
            raise ValueError("Cached observation is not paired with this image/timestamp")
        inputs.append(identity)
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError(f"Unreadable frame: {path}")
        return FrameSlot(frame, sample["frame_id"], sample["ts_ms"], cursor[0])

    worker._stop = ReplayStop()
    worker._bus = SimpleNamespace(get_latest=next_frame)
    worker._locator = SimpleNamespace(locate=locate)
    started = time.perf_counter()
    try:
        worker._run()
    finally:
        locator.close()
    if len(outputs) != len(selected):
        raise RuntimeError(f"Worker failed on {len(selected)-len(outputs)} frames")
    if not cached:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("x", encoding="utf-8") as handle:
            json.dump({"signature": signatures, "inputs": inputs}, handle, default=encode)
    summary = {"case": case.name, "component_id": cid, "frames": len(outputs),
               "raw_cache_reused": cached is not None,
               "visual_continuity": visual_continuity,
               "motion_handoff": motion_handoff,
               "statuses": dict(Counter(o["tracking"] for o in outputs)),
               "reasons": dict(Counter(o["pose_quality"]["reason"] or "accepted" for o in outputs)),
               "stability": dict(Counter(o["pose_quality"]["stability"] for o in outputs)),
               "offline_elapsed_s": round(time.perf_counter()-started, 3)}
    print(json.dumps(summary), flush=True)
    return {"summary": summary, "outputs": outputs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", required=True, help="component_id=sequence_directory")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval-ms", type=float, default=300)
    parser.add_argument("--visual-continuity", action="store_true",
                        help="Offline opt-in to the Webcam visual-continuity candidate; no runtime changes")
    parser.add_argument("--compare-continuity", action="store_true",
                        help="Replay baseline then candidate against exactly the same cached raw model observations")
    parser.add_argument("--compare-handoff", action="store_true", help="Compare original vs image-aligned acquisition and continuation")
    parser.add_argument("--motion-handoff", action="store_true", help="Opt-in offline acquisition/continuation candidate")
    args = parser.parse_args()
    if args.out.exists() or args.interval_ms <= 0:
        parser.error("Use a new output path and positive sample interval")
    cv2.setNumThreads(2)
    config = load_config(ROOT / "backend/config.yaml")
    results = []
    for spec in args.case:
        cid, path = spec.split("=", 1)
        case = Path(path).resolve()
        cache_path = args.cache_dir / f"{case.name}-{cid}.json"
        modes = ([(False, False), (False, True)] if args.compare_handoff else
                 [(False, False), (True, False)] if args.compare_continuity else
                 [(args.visual_continuity, args.motion_handoff)])
        for enabled, handoff in modes:
            results.append(replay(case, cid, cache_path, config, args.interval_ms, enabled, handoff))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump({"limitations": "Saved JPEG/model/worker replay only; not live display, independent pin truth or electrical/cloud verification.",
                   "results": results}, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
