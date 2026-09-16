from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from add_pi5_negative_samples import add_negative_samples  # noqa: E402


LABEL = (
    "0 0.5 0.5 0.5 0.5 "
    "0.25 0.25 2 0.75 0.25 2 0.75 0.75 2 0.25 0.75 2 "
    "0.36 0.66 2 0.39 0.66 2 0.64 0.66 2 0.67 0.66 2\n"
)


def _write_image(path: Path, color: tuple[int, int, int], index: int) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.full((72, 112, 3), color, dtype=np.uint8)
    cv2.circle(image, (18 + index * 7, 28 + index * 3), 11, (20, 20, 20), -1)
    cv2.line(image, (5, 60 - index), (105, 10 + index), (30, 180, 230), 3)
    assert cv2.imwrite(str(path), image)
    return path.read_bytes()


def _write_base(root: Path) -> tuple[bytes, bytes]:
    train = root / "images" / "train" / "board.jpg"
    val = root / "images" / "val" / "val.jpg"
    train_bytes = _write_image(train, (40, 80, 50), 0)
    val_bytes = _write_image(val, (50, 90, 60), 1)
    for split, stem in (("train", "board"), ("val", "val")):
        label = root / "labels" / split / f"{stem}.txt"
        label.parent.mkdir(parents=True, exist_ok=True)
        label.write_text(LABEL, encoding="utf-8")
    return train_bytes, val_bytes


def _write_candidates(root: Path, color: tuple[int, int, int], count: int) -> None:
    for index in range(count):
        _write_image(root / f"candidate_{index:02d}.jpg", color, index)


def test_adds_empty_train_labels_and_preserves_validation(tmp_path):
    source = tmp_path / "source"
    _, val_bytes = _write_base(source)
    uno = tmp_path / "uno"
    sensor = tmp_path / "sensor"
    wiring = tmp_path / "wiring"
    _write_candidates(uno, (120, 60, 30), 4)
    _write_candidates(sensor, (90, 80, 40), 4)
    _write_candidates(wiring, (80, 70, 100), 4)
    output = tmp_path / "output"

    summary = add_negative_samples(
        source=source,
        output=output,
        uno_source=uno,
        sensor_source=sensor,
        wiring_source=wiring,
        uno_count=2,
        sensor_count=1,
        wiring_count=1,
    )

    assert summary["added_negatives"] == 4
    assert summary["category_counts"] == {
        "photoresistor": 1,
        "uno_q": 2,
        "wiring_hand": 1,
    }
    assert summary["final_counts"] == {"train": 5, "val": 1, "test": 0}
    assert summary["empty_train_labels"] == 4
    assert summary["image_label_parity"] is True
    assert summary["unique_negative_hashes"] is True
    assert summary["negative_hash_overlap_with_base"] is False
    assert summary["val_unchanged"] is True
    assert (output / "images" / "val" / "val.jpg").read_bytes() == val_bytes
    negative_labels = list((output / "labels" / "train").glob("negative__*.txt"))
    assert len(negative_labels) == 4
    assert all(path.read_bytes() == b"" for path in negative_labels)
    assert (output / ".negative-review" / "review-01.jpg").is_file()
    assert (output / ".negative-review" / "manifest.jsonl").is_file()
