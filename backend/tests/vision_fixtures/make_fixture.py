"""Self-contained board fixture for vision tests.

Builds a small 8-pin BoardProfile (two header rows) and renders a
deterministic, ORB-friendly textured reference image (1200 px wide dark-blue
"PCB": colored rectangles, text glyphs, seeded speckle).

The texture is deliberately dense on the LEFT ~60% of the board and sparse
on the right, so the occlusion test can reliably break tracking by covering
the feature-rich region.

No dependency on the parallel data-layer agent: everything is generated
here.  Reuse across tests via ``build_fixture(tmp_dir)``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:  # allow running pytest from anywhere
    sys.path.insert(0, str(_BACKEND))

import cv2
import numpy as np

from app.profiles.models import BoardProfile

BOARD_W_MM = 68.58
BOARD_H_MM = 53.34
HEADER_TOP_Z_MM = 8.5
SCALE_PX_PER_MM = 17.5
REF_W = int(round(BOARD_W_MM * SCALE_PX_PER_MM))   # 1200
REF_H = int(round(BOARD_H_MM * SCALE_PX_PER_MM))   # 933

_TXT = {"zh-TW": "測試腳位", "en": "test pin"}

# id, header, index, x_mm, y_mm, capability type
_PINS = [
    ("D0", "JTOP", 0, 24.0, 2.54, "digital_io"),
    ("D1", "JTOP", 1, 29.08, 2.54, "digital_io"),
    ("D2", "JTOP", 2, 34.16, 2.54, "digital_io"),
    ("D3", "JTOP", 3, 39.24, 2.54, "pwm"),
    ("A0", "JBOT", 0, 24.0, 50.8, "adc"),
    ("A1", "JBOT", 1, 29.08, 50.8, "adc"),
    ("A2", "JBOT", 2, 34.16, 50.8, "adc"),
    ("A3", "JBOT", 3, 39.24, 50.8, "adc"),
]


def build_profile() -> BoardProfile:
    pins = []
    for pin_id, header, index, x, y, cap in _PINS:
        pins.append({
            "id": pin_id,
            "silkscreen": pin_id,
            "header": header,
            "index": index,
            "pos_mm": (x, y, HEADER_TOP_Z_MM),
            "capabilities": [{"type": cap}],
            "electrical": {"voltage": 3.3},
            "description": _TXT,
        })
    data = {
        "schema_version": "1.0",
        "board": {
            "id": "test-board",
            "name": {"zh-TW": "測試板", "en": "Test Board"},
            "vendor": "fixture",
            "mcu": {"part": "TEST-MCU"},
            "logic_voltage": 3.3,
            "five_volt_tolerant": False,
            "form_factor": "uno",
            "outline_mm": (BOARD_W_MM, BOARD_H_MM),
            "header_top_z_mm": HEADER_TOP_Z_MM,
        },
        "reference": {
            "image": "reference.png",
            "width_px": REF_W,
            "height_px": REF_H,
            "mm_to_px": [[SCALE_PX_PER_MM, 0.0, 0.0],
                         [0.0, SCALE_PX_PER_MM, 0.0],
                         [0.0, 0.0, 1.0]],
        },
        "headers": [
            {"id": "JTOP", "name": {"zh-TW": "上排", "en": "top row"},
             "side": "top"},
            {"id": "JBOT", "name": {"zh-TW": "下排", "en": "bottom row"},
             "side": "bottom"},
        ],
        "pins": pins,
    }
    return BoardProfile.model_validate(data)


def render_reference(seed: int = 7) -> np.ndarray:
    """Deterministic textured dark-blue 'PCB' reference (BGR uint8)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((REF_H, REF_W, 3), dtype=np.uint8)
    img[:] = (130, 55, 25)  # dark blue PCB (BGR) — matches the HSV ROI gate

    dense_x1 = int(REF_W * 0.60)  # texture-dense zone: left 60%

    # Colored rectangles (chips/connectors) — mostly in the dense zone.
    palette = [(200, 200, 200), (60, 200, 220), (40, 160, 60),
               (30, 100, 230), (180, 120, 40), (90, 90, 90),
               (20, 220, 250), (230, 230, 230)]
    for _ in range(42):
        w = int(rng.integers(24, 110))
        h = int(rng.integers(18, 80))
        x = int(rng.integers(int(REF_W * 0.03), dense_x1 - w))
        y = int(rng.integers(int(REF_H * 0.10), int(REF_H * 0.86) - h))
        color = palette[int(rng.integers(0, len(palette)))]
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
        cv2.rectangle(img, (x, y), (x + w, y + h),
                      (max(color[0] - 60, 0), max(color[1] - 60, 0),
                       max(color[2] - 60, 0)), 3)

    # Text glyphs (silkscreen) in the dense zone.
    words = ["UNO-Q", "TESTBRD", "3V3", "GPIO", "QWK-42", "SPI0", "I2C0",
             "PWR", "REV-C", "MADE-XY"]
    for i, word in enumerate(words):
        x = int(rng.integers(int(REF_W * 0.04), int(dense_x1 * 0.7)))
        y = int(rng.integers(int(REF_H * 0.14), int(REF_H * 0.9)))
        cv2.putText(img, word, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    1.6 + 0.25 * (i % 3), (245, 245, 245), 3, cv2.LINE_AA)

    # Medium speckle — dense zone only. The right ~40% stays essentially
    # featureless (plain PCB + fine noise) so that occluding the dense zone
    # reliably breaks feature matching (mirrors real boards' blank areas).
    for _ in range(240):
        x = int(rng.integers(6, dense_x1 - 6))
        y = int(rng.integers(6, REF_H - 6))
        r = int(rng.integers(3, 10))
        c = tuple(int(v) for v in rng.integers(120, 255, size=3))
        cv2.circle(img, (x, y), r, c, -1)

    # Header strips + gold pin holes at the profile pin positions.
    cv2.rectangle(img, (0, 0), (REF_W - 1, int(4.6 * SCALE_PX_PER_MM)),
                  (40, 30, 15), -1)
    cv2.rectangle(img, (0, REF_H - int(4.6 * SCALE_PX_PER_MM)),
                  (REF_W - 1, REF_H - 1), (40, 30, 15), -1)
    for _, _, _, x_mm, y_mm, _ in _PINS:
        cx = int(round(x_mm * SCALE_PX_PER_MM))
        cy = int(round(y_mm * SCALE_PX_PER_MM))
        cv2.circle(img, (cx, cy), 14, (40, 180, 220), -1)
        cv2.circle(img, (cx, cy), 6, (10, 10, 10), -1)

    # Fine noise for ORB richness.
    noise = rng.normal(0.0, 6.0, size=img.shape)
    img = np.clip(img.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    return img


def build_fixture(dir_path: Path) -> tuple[BoardProfile, Path]:
    """Render the fixture into ``dir_path`` and return (profile, dir)."""
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    profile = build_profile()
    ref_file = dir_path / profile.reference.image
    if not ref_file.exists():
        cv2.imwrite(str(ref_file), render_reference())
    return profile, dir_path
