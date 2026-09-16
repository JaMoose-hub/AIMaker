# -*- coding: utf-8 -*-
"""Audit a YOLO detection/segmentation component dataset before training."""
from __future__ import annotations

import argparse
from pathlib import Path

from component_dataset import audit_component_dataset, format_audit_report, write_audit_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="path to YOLO data.yaml")
    parser.add_argument("--output", default="", help="optional JSON report path")
    parser.add_argument("--strict", action="store_true", help="return non-zero when audit has errors")
    parser.add_argument("--skip-duplicate-check", action="store_true")
    args = parser.parse_args()

    report = audit_component_dataset(
        args.data,
        check_duplicates=not args.skip_duplicate_check,
    )
    print(format_audit_report(report))
    if args.output:
        output = write_audit_report(report, Path(args.output))
        print(f"audit JSON: {output}")
    if args.strict and not report["ready_to_train"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

