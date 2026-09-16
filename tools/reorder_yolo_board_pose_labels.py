# -*- coding: utf-8 -*-
"""Safely reorder YOLO Pose keypoints using an audited permutation map.

The permutation for each image is one-based and maps the desired semantic
order (profile TL, TR, BR, BL) to the four points in the original label.
For example, ``[3, 4, 1, 2]`` means new TL=old point 3, new TR=old point 4,
new BR=old point 1, and new BL=old point 2.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil


def _reorder_label(text: str, permutation: list[int]) -> str:
    values = text.split()
    if len(values) != 17:
        raise ValueError(f"expected 17 YOLO Pose values, got {len(values)}")
    if sorted(permutation) != [1, 2, 3, 4]:
        raise ValueError(f"invalid permutation: {permutation}")
    points = [values[5 + index * 3:8 + index * 3] for index in range(4)]
    reordered = values[:5]
    for old_index in permutation:
        reordered.extend(points[old_index - 1])
    return " ".join(reordered) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="datasets/board-pose")
    parser.add_argument("--split", default="train")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mapping")
    source.add_argument(
        "--uniform-permutation",
        nargs=4,
        type=int,
        metavar=("TL", "TR", "BR", "BL"),
        help="apply one audited one-based keypoint permutation to every label",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.dataset).resolve()
    label_dir = root / "labels" / args.split
    manifest_path = root / "capture-manifest.jsonl"
    label_paths = sorted(label_dir.glob("*.txt"))
    label_stems = {path.stem for path in label_paths}
    mapping_path = Path(args.mapping).resolve() if args.mapping else None
    if mapping_path is not None:
        mapping_doc = json.loads(mapping_path.read_text(encoding="utf-8"))
        permutations: dict[str, list[int]] = mapping_doc["permutations"]
        mapping_name = mapping_path.name
    else:
        permutation = list(args.uniform_permutation)
        if sorted(permutation) != [1, 2, 3, 4]:
            raise SystemExit(f"invalid uniform permutation: {permutation}")
        permutations = {stem: permutation for stem in label_stems}
        mapping_name = "uniform-" + "-".join(str(value) for value in permutation)
    mapping_stems = set(permutations)
    if label_stems != mapping_stems:
        missing = sorted(label_stems - mapping_stems)
        extra = sorted(mapping_stems - label_stems)
        raise SystemExit(f"mapping mismatch; missing={missing}, extra={extra}")

    rewritten = {
        path: _reorder_label(path.read_text(encoding="utf-8"), permutations[path.stem])
        for path in label_paths
    }
    manifest_records = []
    if manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            stem = Path(record.get("image", "")).stem
            if record.get("split") == args.split and stem in permutations:
                if "semantic_reorder" in record:
                    raise SystemExit(f"manifest record already reordered: {stem}")
                corners = record.get("corners_px")
                if not isinstance(corners, list) or len(corners) != 4:
                    raise SystemExit(f"manifest has invalid corners: {stem}")
                permutation = permutations[stem]
                record["corners_px"] = [corners[index - 1] for index in permutation]
                record["semantic_reorder"] = {
                    "permutation_1_based": permutation,
                    "mapping": mapping_name,
                }
            manifest_records.append(record)

    print(f"validated {len(rewritten)} labels for split={args.split}")
    if not args.apply:
        print("dry run only; pass --apply to create backups and rewrite labels")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = label_dir.with_name(f"{args.split}.pre-semantic-reorder-{stamp}")
    shutil.copytree(label_dir, backup_dir)
    manifest_backup = None
    if manifest_path.is_file():
        manifest_backup = manifest_path.with_name(
            f"capture-manifest.pre-semantic-reorder-{stamp}.jsonl"
        )
        shutil.copy2(manifest_path, manifest_backup)

    for path, text in rewritten.items():
        path.write_text(text, encoding="utf-8")
    if manifest_records:
        manifest_path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n"
                    for record in manifest_records),
            encoding="utf-8",
        )

    print(f"rewrote {len(rewritten)} labels")
    print(f"label backup: {backup_dir}")
    if manifest_backup is not None:
        print(f"manifest backup: {manifest_backup}")


if __name__ == "__main__":
    main()
