import cv2
import numpy as np
from pathlib import Path
from types import SimpleNamespace

from app.vision.pose_tracker import PoseTracker, TrackerParams


def tracker(enabled):
    item = PoseTracker.__new__(PoseTracker)
    item.params = TrackerParams(color_roi_enabled=enabled)
    item._failed_detects = 0
    return item


def scene():
    image = np.full((480, 640, 3), 150, np.uint8)
    image[40:160, 40:200] = (255, 70, 20)  # unrelated blue module
    image[220:440, 320:600] = (30, 130, 30)  # green board
    return image


def test_color_crop_can_be_disabled_without_changing_legacy_defaults():
    assert TrackerParams().color_roi_enabled
    image = scene()
    assert tracker(True)._roi_gate(image) is not None
    assert tracker(False)._roi_gate(image) is None


def test_disabled_color_crop_allows_sift_to_search_green_board_too():
    image = scene()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    item = tracker(False)
    seen = []
    item._match_features = lambda *args: None
    item._match_features_sift = lambda roi, offset: seen.append((roi.shape, offset))
    assert item._detect_step(gray, image) is None
    assert seen == [(gray.shape, (0, 0))]
    # Retain the existing rescue retry budget, not SIFT on every missed frame.
    for _ in range(3):
        assert item._detect_step(gray, image) is None
    assert len(seen) == 1


def test_factory_disables_color_crop_only_for_pi_hybrid(monkeypatch):
    from app.vision import factory
    monkeypatch.setattr(factory, 'YoloProfileDetector', lambda **kw: SimpleNamespace())
    monkeypatch.setattr(factory, 'PipelineDetector', lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(factory, 'HybridBoardDetector', lambda primary, fallback:
        SimpleNamespace(primary=primary, fallback=fallback, load=lambda *args: None))
    for board in ('raspberry-pi-5', 'arduino-uno-q'):
        detector = factory.create_detector('hybrid',
            SimpleNamespace(board=SimpleNamespace(id=board)), Path('.'), yolo_model_path='unused')
        if board == 'raspberry-pi-5':
            assert not detector.fallback.params.color_roi_enabled
            assert detector.fallback.params.sift_frame_max_px == 960
        else:
            assert detector.fallback.params is None
