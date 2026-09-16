# -*- coding: utf-8 -*-
"""Audit Pi 5 8-keypoint counts, labels, negatives, and split leakage."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
TARGET_POSITIVES = {"train": 320, "val": 80, "test": 40}
TARGET_NEGATIVES = 50
EXPECTED_LABEL_VALUES = 1 + 4 + 8 * 3


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def audit(root: Path, strict: bool = False) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    splits: dict[str, dict[str, int]] = {}
    digest_splits: dict[str, set[str]] = defaultdict(set)
    total_negatives = 0
    for split in ("train", "val", "test"):
        image_dir = root / "images" / split
        label_dir = root / "labels" / split
        images = sorted(
            path for path in image_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ) if image_dir.is_dir() else []
        positives = negatives = invalid = 0
        image_stems = {path.stem for path in images}
        label_stems = {path.stem for path in label_dir.glob("*.txt")} if label_dir.is_dir() else set()
        for missing in sorted(image_stems - label_stems):
            issues.append(f"{split}: missing label for {missing}")
        for extra in sorted(label_stems - image_stems):
            issues.append(f"{split}: label without image {extra}")
        for image in images:
            digest_splits[_digest(image)].add(split)
            label = label_dir / f"{image.stem}.txt"
            text = label.read_text(encoding="utf-8").strip() if label.is_file() else ""
            if not text:
                negatives += 1
                continue
            rows = [row for row in text.splitlines() if row.strip()]
            try:
                values = [float(value) for value in rows[0].split()] if len(rows) == 1 else []
            except ValueError:
                values = []
            if (
                len(values) != EXPECTED_LABEL_VALUES
                or int(values[0]) != 0
                or any(not 0.0 <= value <= 1.0 for value in values[1:5])
                or any(
                    not 0.0 <= values[index] <= 1.0
                    for index in range(5, len(values), 3)
                )
                or any(
                    not 0.0 <= values[index] <= 1.0
                    for index in range(6, len(values), 3)
                )
                or any(values[index] not in (0.0, 1.0, 2.0) for index in range(7, len(values), 3))
            ):
                invalid += 1
                issues.append(f"{split}: invalid 8-keypoint label {label.name}")
            else:
                positives += 1
        total_negatives += negatives
        splits[split] = {
            "images": len(images),
            "positive": positives,
            "negative": negatives,
            "invalid": invalid,
        }
        if strict and positives != TARGET_POSITIVES[split]:
            issues.append(
                f"{split}: expected {TARGET_POSITIVES[split]} positive images, "
                f"found {positives}"
            )

    duplicate_hashes = {
        digest: sorted(split_names)
        for digest, split_names in digest_splits.items()
        if len(split_names) > 1
    }
    if duplicate_hashes:
        issues.append(
            f"identical image content crosses splits ({len(duplicate_hashes)} digest(s))"
        )

    sessions: dict[str, set[str]] = defaultdict(set)
    manifest = root / "migration-manifest.jsonl"
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            session = str(record.get("session_id", "")).strip()
            split = str(record.get("split", "")).strip()
            if session and split:
                sessions[session].add(split)
    leaked_sessions = {
        session: sorted(split_names)
        for session, split_names in sessions.items()
        if len(split_names) > 1
    }
    if leaked_sessions:
        issues.append(
            "capture session crosses train/val/test: "
            + ", ".join(f"{key}={value}" for key, value in leaked_sessions.items())
        )
    if strict and total_negatives < TARGET_NEGATIVES:
        issues.append(
            f"expected at least {TARGET_NEGATIVES} negative images, found {total_negatives}"
        )
    report: dict[str, object] = {
        "dataset": str(root),
        "kpt_shape": [8, 3],
        "splits": splits,
        "total_negatives": total_negatives,
        "duplicate_content_across_splits": len(duplicate_hashes),
        "session_leakage": leaked_sessions,
        "strict_positive_targets": TARGET_POSITIVES,
        "issues": issues,
        "ready": not issues,
    }
    return report, issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/board-pose-pi5-8kpt"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    report, issues = audit(args.dataset.resolve(), strict=args.strict)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
