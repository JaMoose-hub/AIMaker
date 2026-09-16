"""CLI for review-safe Pose prelabelling from reviewed planar examples."""
from __future__ import annotations

import argparse
from pathlib import Path

from pose_labeling import PoseLabelDataset
from pose_registration import ReviewedPoseRegistrar


ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Pose data.yaml path")
    parser.add_argument(
        "--splits",
        nargs="+",
        default=["train", "val"],
        choices=("train", "val", "test"),
        help="Target splits",
    )
    parser.add_argument(
        "--source-splits",
        nargs="+",
        default=["train", "val"],
        choices=("train", "val", "test"),
        help="Splits searched for reviewed source labels",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write accepted prelabels as auto_pending; default is dry-run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = PoseLabelDataset(Path(args.data).expanduser().resolve())
    registrar = ReviewedPoseRegistrar(dataset)

    def progress(current: int, total: int, image: Path, status: str) -> None:
        print(f"[{current:>3}/{total}] {status:<15} {image.name}")

    summary = registrar.prelabel_unlabelled(
        target_splits=args.splits,
        source_splits=args.source_splits,
        apply=args.apply,
        progress=progress,
    )
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode}: accepted={summary.saved}, existing={summary.skipped_existing}, "
        f"no_registration={summary.no_registration}, failed={summary.failed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
