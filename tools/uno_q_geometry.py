"""Shared geometry constants for the Arduino UNO Q board profile tooling.

Single source of truth for pin/hole coordinates used by gen_pin_table.py,
render_reference.py and calibrate_reference.py.

Board frame (see backend/app/profiles/models.py docstring):
  origin = top-left PCB corner seen from above with USB-C on the LEFT,
  x -> right along the long edge (68.58 mm), y -> down (53.34 mm),
  z -> up from the PCB plane. Header pin openings at z = HEADER_TOP_Z_MM.

Coordinate provenance (verified 2026-07-27):
  The UNO Q keeps the exact UNO R3 form factor (shield compatible), so all
  drill coordinates below were extracted from the official Arduino UNO R3
  Eagle board file (arduino_Uno_Rev3-02-TH.brd, Eagle 6.1 XML; mirror:
  github.com/una1veritas/EagleDocs). Eagle origin is the LOWER-left corner,
  y up; converted here via y_board = 53.34 - y_eagle.

  Eagle element anchors + 1XN package pad offsets (pitch 2.54 mm):
    IOL   (D7..D0, 8 pins)  x=54.61  y=50.8  R180 -> pads 45.72 .. 63.50
    IOH   (SCL..D8, 10 pins) x=30.226 y=50.8 R180 -> pads 18.796 .. 41.656
    POWER (NC..VIN, 8 pins) x=36.83  y=2.54       -> pads 27.94 .. 45.72
    AD    (A0..A5, 6 pins)  x=57.15  y=2.54       -> pads 50.80 .. 63.50
  Net names confirmed the pin order (IOH pad10=AD5/SCL ... IOL pad1=IO0;
  POWER pad1 unconnected = NC on the R3, pad2=IOREF(+5V net on R3), ...
  pad8=VIN). On the UNO Q, POWER pad1 is BOOT (MCU_BOOT0) per the official
  ABX00162 full-pinout PDF ("BOOT IOREF RESET +3V3 +5V GND GND VIN").
  Gap D8->D7 = 4.064 mm (0.16 in); gap VIN->A0 = 5.08 mm (0.2 in).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# --- Board outline -----------------------------------------------------------
BOARD_W_MM = 68.58
BOARD_H_MM = 53.34
HEADER_TOP_Z_MM = 8.5
PITCH_MM = 2.54

TOP_ROW_Y_MM = 2.54      # Eagle y=50.8
BOTTOM_ROW_Y_MM = 50.80  # Eagle y=2.54

# PCB outline polygon in board frame (mm), from the R3 Eagle dimension layer
# (1 mm corner arcs approximated by their endpoints). Note the classic UNO
# chamfered right-edge shape.
OUTLINE_POLY_MM = [
    (1.0, 0.0),
    (64.516, 0.0),
    (66.04, 1.524),
    (66.04, 12.954),
    (68.58, 15.494),
    (68.58, 48.26),
    (66.04, 50.80),
    (66.04, 52.34),
    (65.04, 53.34),
    (1.0, 53.34),
    (0.0, 52.34),
    (0.0, 1.0),
]

# --- Mounting holes (drill dia 3.2 mm) ---------------------------------------
# Order used by calibrate_reference.py clicks: TL, TR, BR, BL.
MOUNTING_HOLES_MM = {
    "top_left": (15.24, 2.54),
    "top_right": (66.04, 17.78),
    "bottom_right": (66.04, 45.72),
    "bottom_left": (13.97, 50.80),
}
MOUNTING_HOLE_ORDER = ["top_left", "top_right", "bottom_right", "bottom_left"]
MOUNTING_HOLE_DRILL_MM = 3.2

# --- Header pin x coordinates (mm), left -> right ----------------------------
# Top row: 10-pin block | 0.16" gap | 8-pin block.
TOP_ROW_PINS = [
    # (pin_id, x_mm)
    ("SCL", 18.796),
    ("SDA", 21.336),
    ("AREF", 23.876),
    ("GND_D", 26.416),
    ("D13", 28.956),
    ("D12", 31.496),
    ("D11", 34.036),
    ("D10", 36.576),
    ("D9", 39.116),
    ("D8", 41.656),
    ("D7", 45.72),
    ("D6", 48.26),
    ("D5", 50.80),
    ("D4", 53.34),
    ("D3", 55.88),
    ("D2", 58.42),
    ("D1", 60.96),
    ("D0", 63.50),
]

# Bottom row: 8-pin power block | 0.2" gap | 6-pin analog block.
BOTTOM_ROW_PINS = [
    ("BOOT", 27.94),
    ("IOREF", 30.48),
    ("RESET", 33.02),
    ("3V3", 35.56),
    ("5V", 38.10),
    ("GND_P1", 40.64),
    ("GND_P2", 43.18),
    ("VIN", 45.72),
    ("A0", 50.80),
    ("A1", 53.34),
    ("A2", 55.88),
    ("A3", 58.42),
    ("A4", 60.96),
    ("A5", 63.50),
]


def pin_positions_mm() -> dict[str, tuple[float, float, float]]:
    """pin_id -> (x, y, z) in board mm."""
    pos: dict[str, tuple[float, float, float]] = {}
    for pin_id, x in TOP_ROW_PINS:
        pos[pin_id] = (x, TOP_ROW_Y_MM, HEADER_TOP_Z_MM)
    for pin_id, x in BOTTOM_ROW_PINS:
        pos[pin_id] = (x, BOTTOM_ROW_Y_MM, HEADER_TOP_Z_MM)
    return pos


# --- Synthetic reference image convention ------------------------------------
PX_PER_MM = 35.0
REF_WIDTH_PX = 2401   # ceil(68.58 * 35) so the whole board fits
REF_HEIGHT_PX = 1868  # ceil(53.34 * 35)
REF_IMAGE_NAME = "reference_synthetic.png"

# Pure-scale homography board-mm -> reference px for the synthetic image.
MM_TO_PX_SYNTHETIC = [
    [PX_PER_MM, 0.0, 0.0],
    [0.0, PX_PER_MM, 0.0],
    [0.0, 0.0, 1.0],
]

# --- Repo paths ---------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "profiles" / "boards" / "arduino-uno-q"
BOARD_JSON = PROFILE_DIR / "board.json"
SCHEMA_JSON = REPO_ROOT / "schemas" / "board-profile.schema.json"
BACKEND_DIR = REPO_ROOT / "backend"


def validate_board_json(path: Path = BOARD_JSON) -> None:
    """Validate board.json against BOTH the JSON schema and the pydantic model.

    Raises on failure (fail loudly). Prints a one-line summary on success.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    import jsonschema

    schema = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from app.profiles.models import BoardProfile  # noqa: PLC0415

    profile = BoardProfile.model_validate(data)
    print(
        f"[validate] OK: {path.name} - jsonschema + pydantic passed "
        f"({len(profile.pins)} pins, {len(profile.buses)} buses, "
        f"{len(profile.groups)} groups)"
    )


def sanity_check_geometry() -> None:
    """Assert the documented invariants of the coordinate table."""
    pos = pin_positions_mm()
    assert len(TOP_ROW_PINS) == 18 and len(BOTTOM_ROW_PINS) == 14
    assert len(pos) == 32, f"expected 32 pins, got {len(pos)}"
    # Rows sit one pitch from their edges.
    assert abs(TOP_ROW_Y_MM - PITCH_MM) < 1e-9
    assert abs(BOTTOM_ROW_Y_MM - (BOARD_H_MM - PITCH_MM)) < 1e-9
    # Everything inside the outline.
    for pid, (x, y, _z) in pos.items():
        assert 0 < x < BOARD_W_MM and 0 < y < BOARD_H_MM, pid
    # 2.54 pitch inside each block, with the documented gaps.
    xs_top = [x for _p, x in TOP_ROW_PINS]
    for i in range(1, 10):
        assert abs(xs_top[i] - xs_top[i - 1] - PITCH_MM) < 1e-9
    assert abs(xs_top[10] - xs_top[9] - 4.064) < 1e-9  # 0.16 in gap
    for i in range(11, 18):
        assert abs(xs_top[i] - xs_top[i - 1] - PITCH_MM) < 1e-9
    xs_bot = [x for _p, x in BOTTOM_ROW_PINS]
    for i in range(1, 8):
        assert abs(xs_bot[i] - xs_bot[i - 1] - PITCH_MM) < 1e-9
    assert abs(xs_bot[8] - xs_bot[7] - 5.08) < 1e-9  # 0.2 in gap
    for i in range(9, 14):
        assert abs(xs_bot[i] - xs_bot[i - 1] - PITCH_MM) < 1e-9
    # Known anchors from the Eagle file.
    assert abs(pos["SCL"][0] - 18.796) < 1e-9
    assert abs(pos["D0"][0] - 63.50) < 1e-9
    assert abs(pos["A5"][0] - 63.50) < 1e-9
    assert abs(pos["VIN"][0] - 45.72) < 1e-9


sanity_check_geometry()
