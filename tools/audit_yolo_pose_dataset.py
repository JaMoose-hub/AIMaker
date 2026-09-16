# -*- coding: utf-8 -*-
"""Audit a single-class YOLO Pose dataset before Board Vision training."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

from component_dataset import label_root_for
from pose_labeling import PoseLabelDataset


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def audit(
    data_yaml: Path,
    *,
    min_train: int,
    min_val: int,
    min_test: int,
    min_negative: int,
    require_reviewed: bool,
) -> tuple[dict[str, Any], list[str]]:
    dataset = PoseLabelDataset(data_yaml)
    issues: list[str] = []
    split_report: dict[str, dict[str, int]] = {}
    digest_splits: dict[str, set[str]] = defaultdict(set)
    total_negatives = 0
    total_pending = 0
    total_unreviewed = 0

    if len(dataset.class_names) != 1:
        issues.append(
            f"expected one Pose class, found {len(dataset.class_names)}"
        )

    for split in ("train", "val", "test"):
        images = dataset.images(split)
        image_root = dataset.image_roots.get(split)
        labeled = positive = negative = invalid = pending = unreviewed = 0
        expected_labels: set[Path] = set()

        for image in images:
            digest_splits[_digest(image)].add(split)
            label = dataset.label_path(image, split)
            expected_labels.add(label.resolve())
            if not label.is_file():
                issues.append(f"{split}: missing label for {image.name}")
                continue
            labeled += 1
            try:
                annotations = dataset.load(image, split)
            except Exception as exc:
                invalid += 1
                issues.append(f"{split}: invalid label {label.name}: {exc}")
                continue
            if not annotations:
                negative += 1
            elif len(annotations) == 1:
                positive += 1
            else:
                invalid += 1
                issues.append(
                    f"{split}: {label.name} contains {len(annotations)} instances; expected 1"
                )
            status = dataset.review.status(dataset.key(image, split))
            if status == "auto_pending":
                pending += 1
            if status not in ("reviewed", "negative"):
                unreviewed += 1

        if image_root is not None:
            label_root = label_root_for(image_root)
            if label_root.is_dir():
                for label in label_root.rglob("*.txt"):
                    if label.resolve() not in expected_labels:
                        issues.append(f"{split}: label without image {label.name}")

        split_report[split] = {
            "images": len(images),
            "labeled": labeled,
            "positive": positive,
            "negative": negative,
            "invalid": invalid,
            "auto_pending": pending,
            "unreviewed": unreviewed,
        }
        total_negatives += negative
        total_pending += pending
        total_unreviewed += unreviewed

    minimums = {"train": min_train, "val": min_val, "test": min_test}
    for split, minimum in minimums.items():
        actual = split_report[split]["images"]
        if actual < minimum:
            issues.append(f"{split}: need at least {minimum} images, found {actual}")
    if total_negatives < min_negative:
        issues.append(
            f"need at least {min_negative} negative images, found {total_negatives}"
        )
    if require_reviewed and total_unreviewed:
        issues.append(
            f"{total_unreviewed} labels are not reviewed "
            "(allowed statuses: reviewed, negative)"
        )

    duplicate_content = {
        digest: sorted(split_names)
        for digest, split_names in digest_splits.items()
        if len(split_names) > 1
    }
    if duplicate_content:
        issues.append(
            "identical image content crosses train/val/test "
            f"({len(duplicate_content)} image(s))"
        )

    report: dict[str, Any] = {
        "dataset": str(dataset.dataset_root),
        "data_yaml": str(dataset.data_yaml),
        "class_names": dataset.class_names,
        "keypoint_count": dataset.keypoint_count,
        "keypoint_names": dataset.keypoint_names,
        "splits": split_report,
        "total_negatives": total_negatives,
        "auto_pending": total_pending,
        "unreviewed": total_unreviewed,
        "duplicate_content_across_splits": len(duplicate_content),
        "minimums": {
            **minimums,
            "negative": min_negative,
        },
        "ready": not issues,
        "issues": issues,
    }
    return report, issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--min-train", type=int, default=20)
    parser.add_argument("--min-val", type=int, default=5)
    parser.add_argument("--min-test", type=int, default=0)
    parser.add_argument("--min-negative", type=int, default=0)
    parser.add_argument("--require-reviewed", action="store_true")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    if min(args.min_train, args.min_val, args.min_test, args.min_negative) < 0:
        raise SystemExit("minimum counts cannot be negative")

    report, issues = audit(
        args.data.resolve(),
        min_train=args.min_train,
        min_val=args.min_val,
        min_test=args.min_test,
        min_negative=args.min_negative,
        require_reviewed=args.require_reviewed,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
