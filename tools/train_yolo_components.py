# -*- coding: utf-8 -*-
"""Audit, train, evaluate, and export a reusable YOLO component model."""
from __future__ import annotations

import argparse
from datetime import datetime
from math import isfinite
from pathlib import Path
import shutil
import tempfile
from typing import Any

from component_dataset import (
    audit_component_dataset,
    format_audit_report,
    normalized_training_yaml,
)
from component_model_package import manifest_path_for, write_model_manifest


def _metric_values(metrics: Any) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, value in dict(getattr(metrics, "results_dict", {}) or {}).items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(number):
            values[str(key)] = round(number, 6)
    return values


def _backup_output(output: Path) -> Path | None:
    manifest = manifest_path_for(output)
    if not output.exists() and not manifest.exists():
        return None
    backup_dir = (
        output.parent / "backups" / "component-training" /
        datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    backup_dir.mkdir(parents=True, exist_ok=False)
    if output.exists():
        shutil.copy2(output, backup_dir / output.name)
    if manifest.exists():
        shutil.copy2(manifest, backup_dir / manifest.name)
    return backup_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="YOLO data.yaml")
    parser.add_argument("--task", choices=("auto", "detect", "segment"), default="auto")
    parser.add_argument("--model", default="", help="base .pt model; inferred when empty")
    parser.add_argument("--output", required=True, help="destination raw ONNX")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0", help="0, 1, cpu, or empty for auto")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--project", default="runs/components")
    parser.add_argument("--name", default="component-model")
    parser.add_argument(
        "--augmentation",
        choices=("standard", "small-parts", "occlusion-robust"),
        default="occlusion-robust",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument(
        "--accept-ultralytics-license",
        action="store_true",
        help="confirm AGPL-3.0 compliance or an applicable Enterprise license",
    )
    args = parser.parse_args()

    if not args.accept_ultralytics_license:
        raise SystemExit(
            "Ultralytics training/models are AGPL-3.0 by default. Confirm the "
            "project license, then rerun with --accept-ultralytics-license."
        )
    if args.epochs <= 0 or args.imgsz < 320 or args.batch <= 0 or args.workers < 0:
        raise SystemExit("epochs/batch must be positive, imgsz >= 320, workers >= 0")

    report = audit_component_dataset(args.data)
    print(format_audit_report(report), flush=True)
    if not report["ready_to_train"]:
        raise SystemExit("dataset audit failed; fix the listed errors before training")
    task = report["task"] if args.task == "auto" else args.task
    if task != report["task"]:
        raise SystemExit(
            f"selected task={task} does not match dataset annotations={report['task']}"
        )
    model_source = args.model.strip() or (
        "yolo11n-seg.pt" if task == "segment" else "yolo11n.pt"
    )

    output = Path(args.output).expanduser().resolve()
    if output.suffix.lower() != ".onnx":
        raise SystemExit("--output must end in .onnx")
    if output.exists() and not args.overwrite:
        raise SystemExit(f"refusing to overwrite existing model: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        import ultralytics
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("run this tool with .venv-training; ultralytics is missing") from exc

    project = Path(args.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    backup_dir = _backup_output(output) if args.overwrite else None
    with tempfile.TemporaryDirectory(prefix="component-training-") as temp_dir:
        normalized_yaml = normalized_training_yaml(
            report, Path(temp_dir) / "components-resolved.yaml"
        )
        model = YOLO(model_source)
        if getattr(model, "task", task) != task:
            raise SystemExit(
                f"base model task={getattr(model, 'task', None)} does not match {task}"
            )
        train_args: dict[str, Any] = {
            "data": str(normalized_yaml),
            "epochs": args.epochs,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "workers": args.workers,
            "patience": args.patience,
            "project": str(project),
            "name": args.name,
            "exist_ok": False,
            "pretrained": True,
            "seed": 0,
            "deterministic": True,
            # Physical boards are not mirror images. Arbitrary in-plane
            # rotation is valid, but left/right and up/down mirroring is not.
            "fliplr": 0.0,
            "flipud": 0.0,
            "degrees": 180.0,
            "translate": 0.10,
            "scale": 0.45,
            "perspective": 0.0005,
            "mosaic": 0.25,
            "mixup": 0.0,
            "erasing": 0.15,
            "close_mosaic": 10,
        }
        if task == "segment":
            train_args.update(copy_paste=0.05, overlap_mask=True, mask_ratio=4)
        if args.augmentation == "small-parts":
            train_args.update(
                translate=0.08,
                scale=0.25,
                perspective=0.0002,
                mosaic=0.15,
                erasing=0.10,
            )
            if task == "segment":
                train_args["copy_paste"] = 0.0
        elif args.augmentation == "occlusion-robust":
            train_args.update(
                translate=0.15,
                scale=0.40,
                perspective=0.0005,
                mosaic=0.20,
                erasing=0.35,
            )
            if task == "segment":
                train_args["copy_paste"] = 0.10
        if args.device.strip():
            train_args["device"] = args.device.strip()

        print(
            f"training task={task} model={model_source} images={report['total_images']} "
            f"classes={len(report['class_names'])}",
            flush=True,
        )
        model.train(**train_args)
        best = Path(model.trainer.best).resolve()
        best_model = YOLO(str(best))
        evaluation_split = "test" if report["splits"]["test"]["images"] else "val"
        metrics: dict[str, float] = {}
        if not args.skip_evaluation:
            print(f"evaluating split={evaluation_split}", flush=True)
            validation = best_model.val(
                data=str(normalized_yaml),
                split=evaluation_split,
                imgsz=args.imgsz,
                batch=args.batch,
                device=args.device.strip() or None,
                plots=True,
            )
            metrics = _metric_values(validation)
        exported = Path(
            best_model.export(
                format="onnx",
                imgsz=args.imgsz,
                dynamic=False,
                simplify=True,
                nms=False,
                opset=12,
            )
        ).resolve()

    temporary_output = output.with_suffix(output.suffix + ".tmp")
    shutil.copy2(exported, temporary_output)
    temporary_output.replace(output)
    manifest = write_model_manifest(
        output,
        {
            "task": task,
            "class_names": report["class_names"],
            "input_size": args.imgsz,
            "base_model": model_source,
            "best_checkpoint": str(best),
            "dataset_yaml": report["data_yaml"],
            "dataset_fingerprint": report["fingerprint"],
            "dataset_counts": {
                split: report["splits"][split]["images"]
                for split in ("train", "val", "test")
            },
            "evaluation_split": evaluation_split,
            "metrics": metrics,
            "augmentation": args.augmentation,
            "ultralytics_version": ultralytics.__version__,
            "license": "AGPL-3.0-or-Enterprise-confirmed-by-operator",
        },
    )
    print(f"best checkpoint: {best}", flush=True)
    print(f"runtime ONNX: {output}", flush=True)
    print(f"model manifest: {manifest}", flush=True)
    if backup_dir is not None:
        print(f"previous output backup: {backup_dir}", flush=True)
    if metrics:
        print("metrics:", flush=True)
        for key, value in sorted(metrics.items()):
            print(f"  {key}: {value}", flush=True)


if __name__ == "__main__":
    main()
