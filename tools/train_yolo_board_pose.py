# -*- coding: utf-8 -*-
"""Train an ordered board YOLO Pose model (4 or 8 keypoints) and export ONNX.

Ultralytics is intentionally not a backend runtime dependency.  Install and
use it only after confirming that AGPL-3.0 or an Enterprise license is
appropriate for the project.  The produced ONNX is consumed by OpenCV DNN.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile

import yaml


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _resolved_data_yaml(source: Path, destination: Path) -> Path:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    root = Path(payload["path"])
    if not root.is_absolute():
        root = (source.parent / root).resolve()
    payload["path"] = str(root)
    destination.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return destination


def _sample_count(data_yaml: Path, split: str) -> int:
    payload = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    root = Path(payload["path"])
    if not root.is_absolute():
        root = (data_yaml.parent / root).resolve()
    relative = payload.get(split)
    if not relative:
        return 0
    image_dir = root / str(relative)
    if not image_dir.is_dir():
        return 0
    return sum(
        1
        for path in image_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="training/board-pose.yaml")
    parser.add_argument("--model", required=True, help="Ultralytics pose base model or checkpoint")
    parser.add_argument("--output", default="models/board-pose.onnx")
    parser.add_argument(
        "--checkpoint-output",
        default="",
        help="optional stable path that receives the best PyTorch checkpoint",
    )
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default=None)
    parser.add_argument("--project", default="runs/board-pose")
    parser.add_argument("--name", default="uno-q-pose")
    parser.add_argument(
        "--augmentation",
        choices=(
            "standard",
            "small-dataset",
            "distance-robust",
            "handheld",
            "component-profile",
        ),
        default="standard",
        help=(
            "small-dataset keeps photometric augmentation but disables mosaic "
            "and geometric transforms that can crop or distort board corners; "
            "distance-robust adds scale/translation without mirror or perspective; "
            "handheld adds full in-plane rotation plus restrained scale/translation "
            "without mirror, mosaic, or corner-erasing transforms; component-profile "
            "matches the validated four-corner photoresistor augmentation policy"
        ),
    )
    parser.add_argument(
        "--pose-weight",
        type=float,
        default=None,
        help="optional Ultralytics pose-loss weight (for example 30)",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=100,
        help="early-stopping patience; use 0 to disable",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--accept-ultralytics-license", action="store_true",
        help="confirm AGPL-3.0 compliance or an applicable Enterprise license",
    )
    args = parser.parse_args()

    if not args.accept_ultralytics_license:
        raise SystemExit(
            "Ultralytics training/models are AGPL-3.0 by default. Confirm the "
            "project's open-source or Enterprise-license path, then rerun with "
            "--accept-ultralytics-license."
        )
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "ultralytics is not installed. Use a separate training environment "
            "after the license decision (for example: python -m pip install ultralytics)."
        ) from exc

    data_path = Path(args.data).resolve()
    if not data_path.is_file():
        raise SystemExit(f"pose data YAML not found: {data_path}")
    train_count = _sample_count(data_path, "train")
    val_count = _sample_count(data_path, "val")
    if train_count < 20 or val_count < 5:
        raise SystemExit(
            "not enough pose data: "
            f"train={train_count} (need >=20), val={val_count} (need >=5)"
        )
    output = Path(args.output).resolve()
    if output.exists() and not args.overwrite:
        raise SystemExit(f"refusing to overwrite existing model: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_output = (
        Path(args.checkpoint_output).resolve() if args.checkpoint_output else None
    )
    if checkpoint_output is not None:
        if checkpoint_output.exists() and not args.overwrite:
            raise SystemExit(
                f"refusing to overwrite existing checkpoint: {checkpoint_output}"
            )
        checkpoint_output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="board-pose-data-") as temp_dir:
        resolved_data = _resolved_data_yaml(
            data_path, Path(temp_dir) / "board-pose-resolved.yaml"
        )
        model = YOLO(args.model)
        train_args = dict(
            data=str(resolved_data),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            project=args.project,
            name=args.name,
            # Semantic board corners must never be trained on physically
            # impossible mirror images. Rotation/perspective remain enabled.
            fliplr=0.0,
            flipud=0.0,
            degrees=180.0,
            perspective=0.0005,
            patience=args.patience,
        )
        if args.augmentation == "small-dataset":
            train_args.update(
                degrees=0.0,
                translate=0.0,
                scale=0.0,
                shear=0.0,
                perspective=0.0,
                mosaic=0.0,
                mixup=0.0,
                copy_paste=0.0,
                erasing=0.0,
            )
        elif args.augmentation == "distance-robust":
            # The capture set fills most of the frame.  This restrained affine
            # policy teaches the detector to handle a board roughly half that
            # size without corrupting semantic keypoint order or introducing
            # the severe corner crops seen with mosaic/perspective training.
            train_args.update(
                degrees=5.0,
                translate=0.12,
                scale=0.55,
                shear=0.0,
                perspective=0.0,
                mosaic=0.0,
                mixup=0.0,
                copy_paste=0.0,
                erasing=0.0,
            )
        elif args.augmentation == "handheld":
            # Teach semantic TL/TR/BR/BL through arbitrary in-plane board
            # rotation while preserving one complete physical board per image.
            # Horizontal/vertical flips stay disabled because a mirrored PCB is
            # not a valid view and would swap component-side semantics.
            train_args.update(
                degrees=180.0,
                translate=0.10,
                scale=0.30,
                shear=0.0,
                perspective=0.0003,
                mosaic=0.0,
                mixup=0.0,
                copy_paste=0.0,
                erasing=0.0,
            )
        elif args.augmentation == "component-profile":
            # Match the photoresistor production contract: the model learns
            # semantic PCB corners while fixed pin geometry stays in a profile.
            train_args.update(
                degrees=180.0,
                translate=0.18,
                scale=0.55,
                shear=1.5,
                perspective=0.0005,
                mosaic=0.25,
                mixup=0.0,
                copy_paste=0.0,
                erasing=0.15,
            )
        if args.pose_weight is not None:
            if args.pose_weight <= 0.0:
                raise SystemExit("--pose-weight must be positive")
            train_args["pose"] = args.pose_weight
        if args.device:
            train_args["device"] = args.device
        model.train(**train_args)
        best = Path(model.trainer.best).resolve()
        exported = Path(
            YOLO(str(best)).export(
                format="onnx",
                imgsz=args.imgsz,
                dynamic=False,
                simplify=True,
                nms=False,
                opset=12,
            )
        ).resolve()
    shutil.copy2(exported, output)
    if checkpoint_output is not None:
        shutil.copy2(best, checkpoint_output)
    print(f"best checkpoint: {best}")
    if checkpoint_output is not None:
        print(f"stable checkpoint: {checkpoint_output}")
    print(f"runtime ONNX: {output}")


if __name__ == "__main__":
    main()
