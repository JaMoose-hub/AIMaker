"""Immutable inputs and paired, geometry-preserving wiring-pose experiments.

Only explicit empty label files are negatives. Original datasets are never edited.
Historical validation is regression evidence, not a new independent test set.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
IDS = {"pi": "raspberry-pi-5", "tft": "mrd-tf240-8p-cs", "hc": "hc-sr04"}
GUIDED = "runs/board-pose/pi5-guided-trial-20260922-175745"
TFT_RUN = "runs/pose/runs/mrd-tf240-8p-cs-pose/mrd-tf240-8p-cs-v3-lit-wired-quick"
HC_RUN = "runs/pose/runs/hc-sr04-corner-pose/hc-sr04-corner-pose-v3-robust-breadboard"
SPECS = {
    "pi": {"dataset": f"{GUIDED}/dataset", "size": 960, "epochs": 40,
           "profile": "profiles/boards/raspberry-pi-5/board.json",
           "active": "guided", "args": f"{GUIDED}/training/candidate/args.yaml",
           "models": {
               "guided": ("models/board-pose-pi5-guided-20260922.onnx", f"{GUIDED}/artifacts/pi5-guided-trial.pt"),
               "handheld-v2": ("models/board-pose-pi5-handheld-v2.onnx", "runs/pose/runs/board-pose/pi5-handheld-v2/weights/best.pt")}},
    "tft": {"dataset": "datasets/mrd-tf240-8p-corner-pose-v3-lit-wired", "size": 1280, "epochs": 40,
            "profile": "profiles/components/mrd-tf240-8p-cs/vision_profile.json",
            "active": "v3-last", "args": f"{TFT_RUN}/args.yaml",
            "models": {
                "v2": ("models/mrd-tf240-8p-cs-pose-v2-robust.onnx", "models/mrd-tf240-8p-cs-pose-v2-robust.pt"),
                "v3-best": (f"{TFT_RUN}/weights/best.onnx", f"{TFT_RUN}/weights/best.pt"),
                "v3-last": ("models/mrd-tf240-8p-cs-pose-v3-lit-wired-last.onnx", "models/mrd-tf240-8p-cs-pose-v3-lit-wired-last.pt")}},
    "hc": {"dataset": "datasets/hc-sr04-corner-pose-v3-robust", "size": 768, "epochs": 20,
           "profile": "profiles/components/hc-sr04/vision_profile.json",
           "active": "v3", "args": f"{HC_RUN}/args.yaml",
           "models": {
               "v2": ("models/hc-sr04-corner-pose-v2.onnx", "models/hc-sr04-corner-pose-v2.pt"),
               "v3": ("models/hc-sr04-corner-pose-v3-robust.onnx", "models/hc-sr04-corner-pose-v3-robust.pt")}},
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def read_label(path: Path, count: int = 4) -> np.ndarray | None:
    if not path.is_file():
        raise ValueError("missing_label")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    rows = text.splitlines()
    try:
        values = np.asarray([float(v) for v in rows[0].split()], dtype=np.float64)
    except ValueError as exc:
        raise ValueError("non_numeric_label") from exc
    if len(rows) != 1 or len(values) != 5 + count * 3 or not np.isfinite(values).all():
        raise ValueError("invalid_label_shape_or_values")
    if values[0] != 0 or np.any(values[1:5] < 0) or np.any(values[1:5] > 1) or np.any(values[3:5] <= 0):
        raise ValueError("invalid_class_or_box")
    points = values[5:].reshape(count, 3)
    if np.any(points[:, :2] < 0) or np.any(points[:, :2] > 1) or not np.isin(points[:, 2], [0, 1, 2]).all():
        raise ValueError("invalid_keypoints")
    quad = points[:4, :2].astype(np.float32)
    if not np.all(points[:4, 2] > 0):
        raise ValueError("incomplete_semantic_corners")
    if not cv2.isContourConvex(quad) or abs(cv2.contourArea(quad)) < .0001:
        raise ValueError("crossed_or_degenerate_corners")
    return values


def label_text(values: np.ndarray | None) -> str:
    return "" if values is None else "0 " + " ".join(f"{v:.9g}" for v in values[1:]) + "\n"


def source_group(path: Path, component: str, capture_lookup: dict, sha: str) -> str:
    if sha in capture_lookup:
        return capture_lookup[sha]
    match = re.search(r"(\d{8}_\d{6})", path.stem)
    if match:
        return component + ":capture:" + match.group(1)
    if path.stem.startswith(("guided_", "candidate_")):
        return "pi:guided-20260922-140333-4b7a2c"
    if component == "tft" and re.match(r"(?:rgb_|s[12]_)?frame_", path.stem):
        # These clips were recorded in the same lit/wired sitting.
        return "tft:lit-wired-20260925"
    # Unknown origins never become independent sessions just by changing a split.
    return component + ":legacy-origin-unknown"


def capture_index() -> dict[str, str]:
    found = {}
    for stem in ("pi5-guided", "pi5-handheld-train", "pi5-handheld-val", "tft-lit-wired-motion", "tft-rgb-wired-motion"):
        folder = ROOT / "datasets/live-captures" / stem
        for meta in sorted(folder.rglob("metadata.json")):
            data = json.loads(meta.read_text(encoding="utf-8"))
            group = data.get("split_group") or data.get("session") or meta.parent.name
            if stem.startswith("tft-"):
                group = "tft:lit-wired-20260925"
            for image in sorted((meta.parent / "images").glob("*")):
                if image.suffix.lower() in SUFFIXES:
                    found[digest(image)] = str(group)
    return found


def quarantine_cross_split(rows: list[dict]) -> list[dict]:
    """Exclude training collisions; keep old validation as explicitly biased regression."""
    held_hashes = {r["sha256"] for r in rows if r["split"] in ("val", "test") and not r["derived"]}
    held_groups = {r["group"] for r in rows if r["split"] in ("val", "test") and not r["derived"] and not r["group"].endswith("unknown")}
    issues = []
    for row in rows:
        if row["split"] != "train":
            continue
        if row["sha256"] in held_hashes or row["group"] in held_groups:
            row["eligible_train"] = False
            row["exclusion"] = "cross_split_source_or_capture_group"
            issues.append({"image": row["original_image"], "reason": row["exclusion"]})
    return issues


def prepare(out: Path) -> dict:
    if out.exists():
        raise ValueError(f"new experiment directory required: {out}")
    out.mkdir(parents=True)
    copied = []

    def freeze(source: Path, relative: str) -> str:
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        sha = digest(source)
        if digest(destination) != sha:
            raise ValueError(f"snapshot mismatch: {source}")
        copied.append({"source": str(source), "snapshot": relative, "sha256": sha})
        return relative

    # Freeze the actual dirty working implementation too: later runs use this code.
    for folder in ("backend/app", "schemas", "profiles/boards/raspberry-pi-5", "profiles/components/hc-sr04", "profiles/components/mrd-tf240-8p-cs"):
        for file in sorted((ROOT / folder).rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                freeze(file, "snapshot/" + file.relative_to(ROOT).as_posix())
    freeze(ROOT / "profiles/component-catalog.json", "snapshot/profiles/component-catalog.json")
    freeze(ROOT / "backend/config.yaml", "snapshot/backend/config.yaml")
    cfg = yaml.safe_load((ROOT / "backend/config.yaml").read_text(encoding="utf-8"))
    camera_file = cfg.get("camera", {}).get("calibration_path")
    if camera_file:
        p = (ROOT / "backend" / camera_file).resolve()
        if p.is_file():
            freeze(p, "snapshot/calibration/camera.json")
    recovery = (ROOT / "backend" / cfg["yolo_pose"]["pi_reference_recovery_model_path"]).resolve()
    freeze(recovery, "snapshot/models/pi-reference.onnx")
    capture_lookup = capture_index()
    j8 = {}
    migration = ROOT / "datasets/board-pose-pi5-8kpt/migration-manifest.jsonl"
    for line in migration.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if item.get("split") != "val" or not item.get("human_reviewed"):
            continue
        image = migration.parent / item["image"]
        label = migration.parent / item["label"]
        values = read_label(label, 8)
        if values is not None:
            j8[digest(image)] = {"points": values[5:].reshape(8, 3)[4:].tolist(), "source": str(label), "sha256": digest(label)}
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "root": str(ROOT), "components": {}, "independent_wired_test": False,
                "evaluation_scope": "legacy_validation_regression_and_existing_sequence_stress_only",
                "production_promotion": False}
    for component, spec in SPECS.items():
        models = {}
        for name, (onnx, checkpoint) in spec["models"].items():
            models[name] = {"onnx": freeze(ROOT / onnx, f"snapshot/models/{component}-{name}.onnx"),
                            "checkpoint": freeze(ROOT / checkpoint, f"snapshot/models/{component}-{name}.pt"),
                            "onnx_sha256": digest(ROOT / onnx), "checkpoint_sha256": digest(ROOT / checkpoint),
                            "exposure": "legacy_validation_used_in_historical_selection; wired_train_not_holdout"}
        freeze(ROOT / spec["args"], f"snapshot/args/{component}.yaml")
        rows, issues, seen = [], [], {}
        dataset = ROOT / spec["dataset"]
        for split in ("train", "val", "test"):
            for image in sorted((dataset / "images" / split).glob("*")):
                if image.suffix.lower() not in SUFFIXES:
                    continue
                label = dataset / "labels" / split / (image.stem + ".txt")
                try:
                    values = read_label(label)
                    frame = cv2.imread(str(image))
                    if frame is None:
                        raise ValueError("unreadable_image")
                except (ValueError, OSError) as exc:
                    issues.append({"image": str(image), "reason": str(exc)})
                    continue
                sha = digest(image)
                derived = "__" in image.stem
                group = source_group(image, component, capture_lookup, sha)
                key = f"{component}/{split}/{image.name}"
                frozen_image = freeze(image, f"source/{key}")
                frozen_label = freeze(label, f"source/{component}/{split}/{image.stem}.txt")
                row = {"key": key, "component": component, "split": split, "group": group,
                       "image": frozen_image, "label": frozen_label, "original_image": str(image),
                       "sha256": sha, "label_sha256": digest(label), "derived": derived,
                       "parent_stem": image.stem.split("__")[0], "positive": values is not None,
                       "eligible_train": split == "train" and not derived,
                       "width": frame.shape[1], "height": frame.shape[0],
                       "label_provenance": "existing_label_not_recertified",
                       "evaluation_role": "synthetic_stress" if derived else "legacy_regression"}
                if sha in j8:
                    row["j8_truth"] = j8[sha]
                if sha in seen:
                    other = seen[sha]
                    row["eligible_train"] = False
                    row["exclusion"] = "duplicate_image" if other["label_sha256"] == row["label_sha256"] else "conflicting_labels_for_same_image"
                    if row["exclusion"].startswith("conflicting"):
                        other["eligible_train"] = False
                        other["exclusion"] = row["exclusion"]
                    issues.append({"image": str(image), "reason": row["exclusion"]})
                else:
                    seen[sha] = row
                rows.append(row)
        issues.extend(quarantine_cross_split(rows))
        manifest["components"][component] = {"id": IDS[component], "input_size": spec["size"],
            "epochs": spec["epochs"], "active": spec["active"], "models": models, "records": rows,
            "issues": issues, "counts": {"train_original_eligible": sum(r["eligible_train"] for r in rows),
                "val": sum(r["split"] == "val" and not r.get("exclusion") for r in rows),
                "test": sum(r["split"] == "test" for r in rows),
                "j8_validation": sum("j8_truth" in r and r["split"] == "val" for r in rows)}}
    manifest["frozen_files"] = copied
    write_json(out / "manifest.json", manifest)
    apply_semantic_quarantine(out,manifest)
    for component in manifest["components"]:audit_contact_sheet(out,component)
    return manifest


def apply_semantic_quarantine(out,manifest):
    rules=json.loads(Path(__file__).with_name("wiring_pose_semantic_exclusions.json").read_text(encoding="utf-8"))
    shutil.copy2(Path(__file__).with_name("wiring_pose_semantic_exclusions.json"),out/"semantic-rules.json")
    for component,rule in rules.items():
        if component not in manifest["components"]:continue
        known={tuple(pair) for pair in rule["anchors"]}
        matches=[r["key"] for r in manifest["components"][component]["records"] if (r["sha256"],r["label_sha256"]) in known]
        if matches:
            write_json(out/"blocked"/(component+".json"),{**rule,"matched_records":matches,"production_promotion":False,
                "status":"quarantined_semantic_conflict","evidence":f"label-audits/{component}.jpg"})


def complete_support_snapshot(out):
    """Add previously omitted non-code schema dependencies before first evaluation."""
    manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
    added=[]
    support = [p for p in (ROOT/"backend/app").rglob("*") if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts]
    for source in [ROOT/"profiles/component-catalog.json", *sorted((ROOT/"schemas").rglob("*.json")), *support]:
        relative="snapshot/"+source.relative_to(ROOT).as_posix()
        destination=out/relative
        if destination.exists():continue
        if (out/"baseline-selection.json").exists():
            raise RuntimeError("cannot change the frozen snapshot after baseline selection")
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,destination)
        added.append({"source":str(source),"snapshot":relative,"sha256":digest(destination)})
    if added:
        manifest["frozen_files"].extend(added)
        write_json(out/"manifest.json",manifest)


def transform_label(values, matrix, width, height):
    """Transform box and semantic points together; outside points lose visibility."""
    if values is None:
        return None
    result = values.copy()
    points = result[5:].reshape(4, 3)
    pixel = points[:, :2] * [width, height]
    transformed = cv2.perspectiveTransform(pixel.astype(np.float32)[None], matrix)[0]
    inside = np.all((transformed >= 0) & (transformed < [width, height]), axis=1)
    points[:, :2] = np.clip(transformed / [width, height], 0, 1)
    points[~inside, 2] = 0
    cx, cy, bw, bh = result[1:5] * [width, height, width, height]
    box = np.array([[cx-bw/2, cy-bh/2], [cx+bw/2, cy-bh/2], [cx+bw/2, cy+bh/2], [cx-bw/2, cy+bh/2]], np.float32)
    box = cv2.perspectiveTransform(box[None], matrix)[0] / [width, height]
    lo, hi = np.clip(box.min(0), 0, 1), np.clip(box.max(0), 0, 1)
    result[1:5] = [*(.5*(lo+hi)), *(hi-lo)]
    return result


def mild_image(image, rng):
    alpha = float(rng.uniform(.85, 1.15))
    beta = float(rng.uniform(-12, 12))
    out = np.clip(image.astype(np.float32)*alpha+beta, 0, 255).astype(np.uint8)
    if rng.random() < .25:
        out = cv2.GaussianBlur(out, (3, 3), .6)
    return out


def targeted_image(image, values, component, rng):
    """Known synthetic occlusion is capped; TFT modification stays in central 60%."""
    out = image.copy()
    if values is None:
        return mild_image(out, rng), None, {"kind": "negative_photometric"}
    values = values.copy()
    h, w = image.shape[:2]
    quad = (values[5:].reshape(4, 3)[:, :2] * [w, h]).astype(np.float32)
    board_mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(board_mask, np.rint(quad).astype(np.int32), 255)
    canonical = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(canonical, quad)
    overlay = image.copy()
    mask = np.zeros((h, w), np.uint8)
    if component == "tft":
        inner = cv2.perspectiveTransform(np.array([[[.2,.2],[.8,.2],[.8,.8],[.2,.8]]], np.float32), matrix)[0]
        cv2.fillConvexPoly(mask, np.rint(inner).astype(np.int32), 255)
        # Texture is not a semantic annotation: retain the original rings and bezel.
        small = rng.integers(0, 256, (12, 16, 3), dtype=np.uint8)
        texture = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        cv2.line(texture, (0, int(rng.uniform(.2,.8)*h)), (w-1, int(rng.uniform(.2,.8)*h)), (245,245,245), max(2,h//50))
        overlay = texture
        kind = "screen_content_central_60_percent"
    else:
        diagonal = float(np.linalg.norm(quad[2]-quad[0]))
        color = tuple(int(v) for v in rng.choice(np.array([[30,30,180],[180,70,30],[25,180,220],[40,40,40],[100,150,195]])))
        # HC header is near one side; Pi varies across board and connector edge.
        y = float(rng.uniform(.65,.95) if component == "hc" else rng.uniform(.1,.95))
        path = cv2.perspectiveTransform(np.array([[[-.1,y],[.4,y-.15],[1.1,y+.1]]], np.float32), matrix)[0]
        width = max(2, int(diagonal * rng.uniform(.006,.016)))
        cv2.polylines(mask, [np.rint(path).astype(np.int32)], False, 255, width)
        cv2.polylines(overlay, [np.rint(path).astype(np.int32)], False, color, width)
        center = np.rint(path[1]).astype(int)
        radius = max(2,int(diagonal*.03))
        cv2.rectangle(mask, tuple(center-radius), tuple(center+radius), 255, -1)
        cv2.rectangle(overlay, tuple(center-radius), tuple(center+radius), (35,35,35), -1)
        if component == "hc":
            # Small specular streak on one transducer; geometry and labels stay fixed.
            shine = cv2.perspectiveTransform(np.array([[[float(rng.choice([.25,.75])),.4]]],np.float32),matrix)[0,0]
            center_shine = tuple(np.rint(shine).astype(int))
            axes = (max(2,int(diagonal*.04)),max(1,int(diagonal*.012)))
            cv2.ellipse(mask,center_shine,axes,-25,0,360,255,-1)
            cv2.ellipse(overlay,center_shine,axes,-25,0,360,(235,245,250),-1)
        if component == "pi" and rng.random() < .5:
            center = np.rint(quad[int(rng.integers(4))]).astype(int)
            skin = np.zeros_like(mask)
            cv2.ellipse(skin, tuple(center), (max(3,int(diagonal*.10)),max(3,int(diagonal*.05))), 0,0,360,255,-1)
            mask = cv2.bitwise_or(mask, skin)
            overlay[skin > 0] = (125,165,205)
        mask = cv2.bitwise_and(mask, board_mask)
        # A rejected candidate becomes an unoccluded sample, not an over-cap one.
        if np.count_nonzero(mask) / max(np.count_nonzero(board_mask), 1) > .20:
            mask[:] = 0
        pts = values[5:].reshape(4,3)
        for i, (x,y) in enumerate(np.rint(quad).astype(int)):
            if 0 <= x < w and 0 <= y < h and mask[y,x] and pts[i,2] > 0:
                pts[i,2] = 1
        kind = "bounded_wire_connector_occlusion"
    out[mask > 0] = overlay[mask > 0]
    return out, values, {"kind": kind, "board_covered_fraction": float(np.count_nonzero(mask & board_mask) / max(np.count_nonzero(board_mask),1))}


def balanced_indices(records, seed=0):
    """Equal group exposure, then equal source exposure; retain explicit negatives."""
    groups = defaultdict(list)
    for index, row in enumerate(records):
        groups[row["group"]].append(index)
    maximum = max(map(len, groups.values()))
    rng = np.random.default_rng(seed)
    schedule = []
    for group in sorted(groups):
        indices = groups[group]
        order = list(rng.permutation(indices))
        schedule.extend(order[i % len(order)] for i in range(maximum))
    return schedule


def audit_contact_sheet(out: Path, component: str):
    """Visual read-only audit of existing annotations, never replacement labels."""
    manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
    groups=defaultdict(list)
    for row in manifest["components"][component]["records"]:
        if row["positive"] and not row["derived"] and (row["eligible_train"] or row["split"]=="val"):
            groups[(row["split"],row["group"])].append(row)
    cells=[]
    for (split,group),rows in groups.items():
        for index in sorted({0,len(rows)//2,len(rows)-1}):
            row=rows[index]
            image=cv2.imread(str(out/row["image"]))
            values=read_label(out/row["label"])
            points=values[5:].reshape(4,3)[:,:2]*[image.shape[1],image.shape[0]]
            points=np.rint(points).astype(np.int32)
            cv2.polylines(image,[points],True,(0,255,70),2)
            for i,point in enumerate(points):
                cv2.circle(image,tuple(point),5,(0,255,70),2)
                cv2.putText(image,str(i+1),tuple(point),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,255,70),2)
            image=cv2.resize(image,(640,360))
            cv2.rectangle(image,(0,0),(640,42),(20,20,20),-1)
            cv2.putText(image,split+" "+group,(6,16),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
            cv2.putText(image,Path(row["image"]).name,(6,34),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
            cells.append(image)
    while len(cells)%3:cells.append(np.zeros_like(cells[0]))
    target=out/"label-audits"/(component+".jpg")
    target.parent.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(target),np.vstack([np.hstack(cells[i:i+3]) for i in range(0,len(cells),3)]))
    return target


def build_paired_datasets(out: Path, component: str, manifest: dict) -> dict:
    if (out/"blocked"/(component+".json")).exists():
        raise ValueError(f"semantic audit blocks dataset generation: {component}")
    spec = manifest["components"][component]
    rows = [r for r in spec["records"] if r["eligible_train"]]
    validation = [r for r in spec["records"] if r["split"] == "val" and not r.get("exclusion") and not r["derived"]]
    if len(rows) < 20 or len(validation) < 5:
        raise ValueError(f"insufficient audited data: {component}: {len(rows)} train, {len(validation)} val")
    schedule = balanced_indices(rows)
    datasets = {}
    for arm in ("A", "B"):
        base = out / "datasets" / component / arm
        if base.exists():
            raise ValueError(f"dataset already exists: {base}")
        generated = []
        for slot, index in enumerate(schedule):
            row = rows[index]
            frame = cv2.imread(str(out / row["image"]))
            values = read_label(out / row["label"])
            for variant in range(3):
                rng = np.random.default_rng(index * 1009 + variant * 97)
                result, label = frame.copy(), None if values is None else values.copy()
                metadata = {"kind": "original"}
                if variant:
                    result = mild_image(result, rng)
                    # Same affine transform in both arms. No crop of semantic corners.
                    h, w = result.shape[:2]
                    affine = cv2.getRotationMatrix2D((w/2,h/2), float(rng.uniform(-8,8)), float(rng.uniform(.85,1.0)))
                    matrix = np.vstack([affine, [0,0,1]]).astype(np.float32)
                    candidate_label = transform_label(label, matrix, w,h)
                    if candidate_label is None or np.all(candidate_label[5:].reshape(4,3)[:,2] > 0):
                        result = cv2.warpPerspective(result,matrix,(w,h),borderMode=cv2.BORDER_REFLECT_101)
                        label = candidate_label
                    metadata = {"kind": "light_photometric_affine"}
                    if arm == "B" and variant == 2:
                        result,label,metadata = targeted_image(result,label,component,rng)
                stem = f"s{slot:04d}_v{variant}"
                image_path, label_path = base / "images/train" / (stem+".jpg"), base / "labels/train" / (stem+".txt")
                image_path.parent.mkdir(parents=True,exist_ok=True)
                label_path.parent.mkdir(parents=True,exist_ok=True)
                if not cv2.imwrite(str(image_path),result,[cv2.IMWRITE_JPEG_QUALITY,95]):
                    raise OSError(image_path)
                label_path.write_text(label_text(label),encoding="utf-8")
                generated.append({"image":str(image_path.relative_to(out)), "parent":row["key"], "source_sha256":row["sha256"], "group":row["group"], **metadata})
        for row in validation:
            image_dest = base/"images/val"/Path(row["image"]).name
            label_dest = base/"labels/val"/Path(row["label"]).name
            image_dest.parent.mkdir(parents=True,exist_ok=True)
            label_dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(out/row["image"],image_dest)
            shutil.copy2(out/row["label"],label_dest)
        data = {"path":str(base.resolve()),"train":"images/train","val":"images/val","names":{0:spec["id"]},"kpt_shape":[4,3]}
        (base/"data.yaml").write_text(yaml.safe_dump(data,sort_keys=False),encoding="utf-8")
        write_json(base/"lineage.json",generated)
        datasets[arm] = {"data":str((base/"data.yaml").resolve()),"train":len(generated),"val":len(validation),"groups":dict(Counter(rows[i]["group"] for i in schedule))}
    write_json(out/"datasets"/component/"paired.json",datasets)
    shutil.copy2(Path(__file__),out/"datasets"/component/"generator.py")
    return datasets
