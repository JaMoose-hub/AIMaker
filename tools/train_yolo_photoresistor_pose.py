# -*- coding: utf-8 -*-
"""Train the four-corner photoresistor YOLO Pose model and export raw ONNX."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile

import yaml


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
    image_dir = root / payload[split]
    return sum(
        1
        for suffix in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")
        for _ in image_dir.glob(suffix)
    ) if image_dir.is_dir() else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="training/photoresistor-pose.yaml")
    parser.add_argument("--model", default="yolo11n-pose.pt")
    parser.add_argument("--output", default="models/photoresistor-pose.onnx")
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--imgsz", type=int, default=768)
    parser.add_argument("--batch", type=int, default=12)
    parser.add_argument("--device", default=None)
    parser.add_argument("--project", default="runs/photoresistor-pose")
    parser.add_argument("--name", default="photoresistor-pose")
    parser.add_argument("--patience", type=int, default=60)
    parser.add_argument("--pose-weight", type=float, default=20.0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--accept-ultralytics-license",
        action="store_true",
        help="confirm AGPL-3.0 compliance or an applicable Enterprise license",
    )
    args = parser.parse_args()

    if not args.accept_ultralytics_license:
        raise SystemExit(
            "Ultralytics training/models are AGPL-3.0 by default. Rerun with "
            "--accept-ultralytics-license after confirming the license path."
        )
    if args.pose_weight <= 0.0:
        raise SystemExit("--pose-weight must be positive")

    data_path = Path(args.data).resolve()
    train_count = _sample_count(data_path, "train")
    val_count = _sample_count(data_path, "val")
    if train_count < 20 or val_count < 5:
        raise SystemExit(
            "not enough photoresistor pose data: "
            f"train={train_count} (need >=20), val={val_count} (need >=5)"
        )

    output = Path(args.output).resolve()
    if output.exists() and not args.overwrite:
        raise SystemExit(f"refusing to overwrite existing model: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("ultralytics is not installed in this Python environment") from exc

    with tempfile.TemporaryDirectory(prefix="photoresistor-pose-data-") as temp_dir:
        resolved_data = _resolved_data_yaml(
            data_path, Path(temp_dir) / "photoresistor-pose-resolved.yaml"
        )
        model = YOLO(args.model)
        train_args = dict(
            data=str(resolved_data),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            project=args.project,
            name=args.name,
            patience=args.patience,
            pose=args.pose_weight,
            # The corner names are semantic. Mirroring would silently swap
            # their physical identity and later project VCC/GND/AO incorrectly.
            fliplr=0.0,
            flipud=0.0,
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
    print(f"best checkpoint: {best}")
    print(f"runtime ONNX: {output}")


if __name__ == "__main__":
    main()
