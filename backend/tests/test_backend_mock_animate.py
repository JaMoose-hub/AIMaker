"""app.main._mock_should_animate: gate for MockDetector's canned trajectory.

Covers the bug this fixes - "detector: mock" left as a stand-in for a real
device camera pointed at a board with no calibrated reference yet used to
fake a "locked" animated pose over the live video (frontend read this as an
endlessly spinning pin overlay, and CalibratePanel's manual alignment guide
never appeared because it only shows when tracking != "locked").
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.main import _mock_should_animate


def _config(source: str) -> SimpleNamespace:
    return SimpleNamespace(camera=SimpleNamespace(source=source))


def _profile(reference_image: str = "reference_captured.jpg") -> SimpleNamespace:
    return SimpleNamespace(reference=SimpleNamespace(image=reference_image))


def test_synthetic_camera_always_animates(tmp_path):
    # No reference file on disk at all - still fine, this is the intended
    # no-camera demo context.
    assert _mock_should_animate(_config("synthetic"), _profile(), tmp_path, scene=None)


def test_scene_present_always_animates(tmp_path):
    # scene!=None routes detect() through scene.truth_at() regardless, but
    # the flag should still report True rather than an unrelated False.
    assert _mock_should_animate(_config("device"), _profile(), tmp_path,
                                scene=SimpleNamespace())


def test_device_camera_with_real_reference_animates(tmp_path):
    (tmp_path / "reference_captured.jpg").write_bytes(b"\xff\xd8\xff")
    assert _mock_should_animate(_config("device"), _profile(), tmp_path, scene=None)


def test_device_camera_without_reference_does_not_animate(tmp_path):
    # The exact bug scenario: real camera, board.json's reference block is
    # still the placeholder, and the image file was never written.
    assert not _mock_should_animate(_config("device"), _profile(), tmp_path, scene=None)


def test_window_camera_without_reference_does_not_animate(tmp_path):
    assert not _mock_should_animate(_config("window"), _profile(), tmp_path, scene=None)
