"""Factory + MockDetector contract tests (the surface the backend imports)."""
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import pytest

from app.vision.factory import create_detector
from app.vision.mock_detector import MockDetector
from app.vision.pipeline_detector import PipelineDetector
from app.vision.synthetic import SyntheticScene
from app.vision.yolo_profile_detector import HybridBoardDetector
from vision_fixtures.make_fixture import build_fixture

VIDEO_SIZE = (1280, 720)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return build_fixture(tmp_path_factory.mktemp("boardfix"))


def _blank_frame():
    return np.zeros((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), dtype=np.uint8)


def test_factory_kinds(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    assert isinstance(create_detector("mock", profile, profile_dir),
                      MockDetector)
    assert isinstance(create_detector("mock", profile, profile_dir,
                                      scene=scene), MockDetector)
    assert isinstance(create_detector("pipeline", profile, profile_dir),
                      PipelineDetector)
    assert isinstance(create_detector(
        "hybrid", profile, profile_dir,
        yolo_model_path=profile_dir / "missing-board-pose.onnx",
    ), HybridBoardDetector)
    with pytest.raises(ValueError):
        create_detector("nope", profile, profile_dir)


def test_mock_with_scene_returns_scene_truth(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    det = create_detector("mock", profile, profile_dir, scene=scene)
    ts_ms = 4321.0
    r = det.detect(_blank_frame(), 7, ts_ms)
    truth = scene.truth_at(ts_ms / 1000.0, 7)
    assert r.tracking == "locked"
    assert r.board_id == profile.board.id
    assert r.frame_id == 7 and r.ts_ms == ts_ms
    assert [(p.pin_id, p.x, p.y) for p in r.pins] == \
           [(p.pin_id, p.x, p.y) for p in truth.pins]
    assert r.outline_px == truth.outline_px
    det.close()


def test_mock_without_scene_canned_trajectory(fixture):
    """No scene: smooth canned pose from the profile pin table alone."""
    profile, profile_dir = fixture
    det = create_detector("mock", profile, profile_dir)
    frame = _blank_frame()
    prev = None
    for k in range(10):
        ts_ms = 1000.0 * (5.0 + k / 30.0)
        r = det.detect(frame, k, ts_ms)
        assert r.tracking == "locked"
        assert 0.0 <= r.confidence <= 1.0
        assert len(r.pins) == len(profile.pins)
        assert r.outline_px is not None and len(r.outline_px) == 4
        xy = np.array([(p.x, p.y) for p in r.pins])
        w, h = VIDEO_SIZE
        assert np.all(xy[:, 0] > 0) and np.all(xy[:, 0] < w)
        assert np.all(xy[:, 1] > 0) and np.all(xy[:, 1] < h)
        if prev is not None:
            step = np.max(np.linalg.norm(xy - prev, axis=1))
            assert step < 15.0, "canned trajectory must be smooth"
        prev = xy
    # Deterministic: same (frame_id, ts) -> same result.
    r1 = det.detect(frame, 3, 6000.0)
    r2 = det.detect(frame, 3, 6000.0)
    assert [(p.x, p.y) for p in r1.pins] == [(p.x, p.y) for p in r2.pins]
    assert r1.confidence == r2.confidence
    det.close()


def test_mock_animate_false_reports_searching_honestly(fixture):
    """mock_animate=False: a profile IS loaded, but detect() must still
    report 'searching' with no pins rather than fabricate a locked pose -
    this is the flag main.py sets for a real camera on an uncalibrated
    board, see app.main._mock_should_animate."""
    profile, profile_dir = fixture
    det = create_detector("mock", profile, profile_dir, mock_animate=False)
    r = det.detect(_blank_frame(), 0, 0.0)
    assert r.tracking == "searching"
    assert r.pins == []
    assert r.board_id == profile.board.id
    det.close()


def test_pipeline_detect_never_raises(fixture):
    """Garbage input must produce tracking='searching', never an exception."""
    profile, profile_dir = fixture
    det = create_detector("pipeline", profile, profile_dir)
    r = det.detect(_blank_frame(), 0, 0.0)
    assert r.tracking == "searching" and r.pins == []
    tiny = np.zeros((4, 4, 3), dtype=np.uint8)
    r = det.detect(tiny, 1, 33.0)
    assert r.tracking == "searching"
    det.close()
