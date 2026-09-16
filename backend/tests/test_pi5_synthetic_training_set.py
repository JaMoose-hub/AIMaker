from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from build_pi5_synthetic_training_set import build_dataset  # noqa: E402


LABEL = (
    "0 0.5 0.5 0.5 0.5 "
    "0.25 0.25 2 0.75 0.25 2 0.75 0.75 2 0.25 0.75 2 "
    "0.36 0.66 2 0.39 0.66 2 0.64 0.66 2 0.67 0.66 2\n"
)


def _write_split(root: Path, split: str, stem: str) -> bytes:
    image_dir = root / "images" / split
    label_dir = root / "labels" / split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    image = np.full((96, 128, 3), 190, dtype=np.uint8)
    cv2.rectangle(image, (32, 24), (96, 72), (35, 82, 48), -1)
    cv2.line(image, (64, 72), (64, 92), (35, 45, 145), 3, cv2.LINE_AA)
    assert cv2.imwrite(str(image_dir / f"{stem}.jpg"), image)
    raw = LABEL.encode("utf-8")
    (label_dir / f"{stem}.txt").write_bytes(raw)
    return raw


def test_build_keeps_validation_unchanged_and_only_expands_train(tmp_path):
    source = tmp_path / "source"
    train_label = _write_split(source, "train", "train_board")
    val_label = _write_split(source, "val", "val_board")
    output = tmp_path / "output"

    summary = build_dataset(
        source=source,
        output=output,
        seed=17,
        preview_count=1,
    )

    assert summary["source_counts"] == {"train": 1, "val": 1, "test": 0}
    assert summary["generated"] == 2
    assert summary["final_counts"] == {"train": 3, "val": 1, "test": 0}
    assert len(list((output / "images" / "train").glob("*.jpg"))) == 3
    assert len(list((output / "labels" / "train").glob("*.txt"))) == 3
    assert (output / "labels" / "train" / "train_board.txt").read_bytes() == train_label
    assert (output / "labels" / "val" / "val_board.txt").read_bytes() == val_label
    assert len(list((output / "images" / "val").glob("*.jpg"))) == 1
    assert (output / ".synthetic-review" / "review-01.jpg").is_file()
    assert (output / ".synthetic-review" / "masks" / "train_board.png").is_file()
