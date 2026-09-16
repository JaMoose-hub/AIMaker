"""Tests for POST /api/calibrate (docs/api-contract.md §6).

Uses the same build_app() injection seams as test_backend_core.py, plus a
synthetic textured board profile (reused from tests/vision_fixtures, which
already renders a deterministic ORB/SIFT-rich "PCB" image for the CV
accuracy tests) written to disk as a real board.json + reference image, so
ProfileStore / PipelineDetector.load() see a fully realistic on-disk layout.

Unlike test_backend_core.py this does NOT poison app.vision.factory /
app.vision.synthetic imports: the whole point of /api/calibrate is to build
a real PipelineDetector and hot-swap the running VisionWorker onto it, so
the real factory must be exercised.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.config import AppConfig, ComponentVisionConfig
from app.main import build_app
from app.vision.mock_detector import MockDetector
from app.vision.pipeline_detector import PipelineDetector
from app.vision.reference_calibration import reference_scale_report
from vision_fixtures.make_fixture import build_profile, render_reference

BOARD_ID = "test-board"
REF_W, REF_H = 1200, 933  # vision_fixtures.make_fixture's rendered size


class ReplayFrameSource:
    """FrameSource that emits a fixed BGR frame repeatedly."""

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._frame_id = 0
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self):
        time.sleep(0.005)
        self._frame_id += 1
        return self._frame, self._frame_id, time.monotonic() * 1000.0

    def close(self) -> None:
        self.closed = True


class NullFrameSource:
    """FrameSource that never produces a frame (empty FrameBus)."""

    def open(self) -> None:
        pass

    def read(self):
        time.sleep(0.01)
        return None

    def close(self) -> None:
        pass


@pytest.fixture()
def board_dir(tmp_path) -> Path:
    """A real on-disk board profile: board.json + a rich-texture reference
    image (reused from vision_fixtures so ORB/SIFT finds thousands of
    features, well above the 200-feature insufficient_features floor)."""
    d = tmp_path / BOARD_ID
    d.mkdir()
    profile = build_profile()
    (d / "board.json").write_text(
        json.dumps(profile.model_dump(mode="json", exclude_none=True),
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ok = cv2.imwrite(str(d / profile.reference.image), render_reference())
    assert ok
    return d


def make_config(profile_dir: Path, **overrides) -> AppConfig:
    values = dict(
        server={"host": "127.0.0.1", "port": 8100},
        camera={"source": "synthetic", "device_index": 0,
                "width": REF_W, "height": REF_H, "fps": 30},
        detector="mock",
        component_vision=ComponentVisionConfig(),
        board=BOARD_ID,
        profile_dir=profile_dir,
        frontend_dist=profile_dir / "no-such-dist",
        default_locale="zh-TW",
        jpeg_quality=70,
        detection_hz=60,
    )
    values.update(overrides)
    return AppConfig(**values)


def make_app(profile_dir: Path, source):
    return build_app(make_config(profile_dir), source=source)


def aligned_corners(w_px: float = REF_W, h_px: float = REF_H,
                    margin: float = 0.05) -> list[list[float]]:
    """TL, TR, BR, BL corners inset by ``margin`` (keeps the quad's area
    fraction comfortably inside [1%, 95%] of the frame)."""
    return [
        [w_px * margin, h_px * margin],
        [w_px * (1 - margin), h_px * margin],
        [w_px * (1 - margin), h_px * (1 - margin)],
        [w_px * margin, h_px * (1 - margin)],
    ]


def small_valid_corners() -> list[list[float]]:
    """A convex board-sized quad that is visible but below the scale gate."""
    return [[500.0, 388.0], [700.0, 388.0], [700.0, 544.0], [500.0, 544.0]]


def _wait_for_frame(app, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while app.state.frame_bus.latest_seq == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app.state.frame_bus.latest_seq > 0, "no frame arrived in time"


# ---------------------------------------------------------------- success ----

def test_reference_scale_report_rejects_underscaled_pin_lattice():
    report = reference_scale_report(
        np.array([[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 1.0]]),
        [("J", 0, 0.0, 0.0), ("J", 1, 2.54, 0.0)],
    )
    assert report["status"] == "reject"
    assert report["pitch_px"] == pytest.approx(12.7)
    assert report["px_per_mm"] == pytest.approx(5.0)


def test_calibrate_success_hot_swaps_pipeline_detector(board_dir):
    reference = cv2.imread(str(board_dir / "reference.png"))
    app = make_app(board_dir.parent, source=ReplayFrameSource(reference))

    with TestClient(app) as client:
        _wait_for_frame(app)
        old_detector = app.state.vision_worker._detector
        assert isinstance(old_detector, MockDetector)  # config.detector == "mock"

        r = client.post("/api/calibrate", json={"corners_px": aligned_corners()})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["detector"] == "pipeline"
        assert isinstance(body["reference_features"], int)
        assert body["reference_features"] >= 200
        assert "message" not in body

        # the running worker now serves a freshly-loaded PipelineDetector.
        new_detector = app.state.vision_worker._detector
        assert new_detector is not old_detector
        assert isinstance(new_detector, PipelineDetector)

    # on-disk state updated + backed up.
    raw = json.loads((board_dir / "board.json").read_text(encoding="utf-8"))
    assert raw["reference"]["image"] == "reference_captured.jpg"
    assert raw["reference"]["width_px"] == REF_W
    assert raw["reference"]["height_px"] == REF_H
    assert (board_dir / "reference_captured.jpg").is_file()
    assert (board_dir / "features.npz").is_file()
    assert len(list(board_dir.glob("board.json.bak-*"))) == 1
    assert len(list(board_dir.glob("reference.png.bak-*"))) == 1


# -------------------------------------------------------------- malformed ----

def test_calibrate_wrong_point_count_is_corners_invalid(board_dir):
    app = make_app(board_dir.parent, source=ReplayFrameSource(
        cv2.imread(str(board_dir / "reference.png"))))
    with TestClient(app) as client:
        r = client.post("/api/calibrate", json={"corners_px": aligned_corners()[:3]})
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "ok": False,
            "error": "corners_invalid",
            "error_code": "corners_invalid",
            "params": {},
        }


def test_calibrate_non_numeric_corners_is_422(board_dir):
    app = make_app(board_dir.parent, source=ReplayFrameSource(
        cv2.imread(str(board_dir / "reference.png"))))
    with TestClient(app) as client:
        r = client.post("/api/calibrate", json={
            "corners_px": [[1, 2], [3, 4], ["not-a-number", 6], [7, 8]]
        })
        assert r.status_code == 422


def test_calibrate_missing_field_is_422(board_dir):
    app = make_app(board_dir.parent, source=ReplayFrameSource(
        cv2.imread(str(board_dir / "reference.png"))))
    with TestClient(app) as client:
        r = client.post("/api/calibrate", json={})
        assert r.status_code == 422


# -------------------------------------------------------------- degenerate ----

def test_calibrate_collinear_corners_is_corners_invalid(board_dir):
    app = make_app(board_dir.parent, source=ReplayFrameSource(
        cv2.imread(str(board_dir / "reference.png"))))
    with TestClient(app) as client:
        collinear = [[100.0, 300.0], [400.0, 300.0], [700.0, 300.0], [900.0, 300.0]]
        r = client.post("/api/calibrate", json={"corners_px": collinear})
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["error"] == "corners_invalid"


def test_calibrate_sliver_area_is_corners_invalid(board_dir):
    app = make_app(board_dir.parent, source=ReplayFrameSource(
        cv2.imread(str(board_dir / "reference.png"))))
    with TestClient(app) as client:
        # A hairline-thin quad: convex, but area << 1% of the frame.
        sliver = [[100.0, 300.0], [1100.0, 300.0], [1100.0, 301.0], [100.0, 301.0]]
        r = client.post("/api/calibrate", json={"corners_px": sliver})
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["error"] == "corners_invalid"


# ----------------------------------------------------------------- no_frame ----

def test_calibrate_no_frame_available(board_dir):
    app = make_app(board_dir.parent, source=NullFrameSource())
    with TestClient(app) as client:
        r = client.post("/api/calibrate", json={"corners_px": aligned_corners()})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "no_frame"
        assert body["error_code"] == "no_frame"
        assert body["params"] == {}


# ------------------------------------------------------ insufficient_features ----

def test_calibrate_underscaled_capture_is_rejected_before_writing(board_dir):
    reference = cv2.imread(str(board_dir / "reference.png"))
    app = make_app(board_dir.parent, source=ReplayFrameSource(reference))

    board_json_before = (board_dir / "board.json").read_text(encoding="utf-8")

    with TestClient(app) as client:
        _wait_for_frame(app)
        r = client.post("/api/calibrate", json={"corners_px": small_valid_corners()})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "insufficient_scale"
        assert body["pitch_px"] < body["min_pitch_px"]
        assert body["px_per_mm"] < body["min_px_per_mm"]

    assert (board_dir / "board.json").read_text(encoding="utf-8") == board_json_before
    assert not list(board_dir.glob("board.json.bak-*"))
    assert not list(board_dir.glob("reference_captured.jpg"))


def test_calibrate_blank_frame_is_insufficient_features_and_leaves_disk_untouched(board_dir):
    blank = np.full((REF_H, REF_W, 3), 60, np.uint8)  # flat color, no texture
    app = make_app(board_dir.parent, source=ReplayFrameSource(blank))

    board_json_before = (board_dir / "board.json").read_text(encoding="utf-8")
    ref_image_before = (board_dir / "reference.png").read_bytes()

    with TestClient(app) as client:
        _wait_for_frame(app)
        r = client.post("/api/calibrate", json={"corners_px": aligned_corners()})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "insufficient_features"
        assert body["error_code"] == "insufficient_features"
        assert body["params"] == {}

    # nothing on disk changed: no backup, no new reference image, board.json
    # byte-identical to before the (failed) calibration attempt.
    assert (board_dir / "board.json").read_text(encoding="utf-8") == board_json_before
    assert (board_dir / "reference.png").read_bytes() == ref_image_before
    assert not (board_dir / "reference_captured.jpg").exists()
    assert not list(board_dir.glob("board.json.bak-*"))
    assert not list(board_dir.glob("reference.png.bak-*"))
