"""Saved-image analysis never reads a webcam frame or changes live state."""
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from app.mobile_photo import MobilePhotoAnalyzer
from app.vision.yolo_pose import BoardPoseObservation
from test_photo_wiring import Geometry


def test_photo_analysis_is_fresh_and_preserves_exact_image_identity(tmp_path):
    image = np.random.default_rng(2).integers(20, 230, (180, 240, 3), dtype=np.uint8)
    path = tmp_path / "normalized.jpg"
    assert cv2.imwrite(str(path), image)
    saved = path.read_bytes()
    decoded = cv2.imread(str(path))
    corners = np.float32([[20,20], [220,20], [220,160], [20,160]])
    observation = BoardPoseObservation(corners, .95, np.ones(4), (20,20,220,160))
    locator = SimpleNamespace(locate=Mock(return_value=observation), close=Mock())
    state = SimpleNamespace(frame_bus=Mock(), source=Mock(), vision_worker=Mock())
    geometries = []
    def geometry():
        instance = Geometry()
        geometries.append(instance)
        return instance
    analyzer = MobilePhotoAnalyzer(state, contexts={"raspberry-pi-5": SimpleNamespace(_locator=locator)}, geometry_factory=geometry)
    context = dict(conversation_id="chat", design={"current": dict(id="project", revision=3, component_ids=["ignored"]), "component_ids":["ignored"]})
    first = analyzer.analyze(dict(id="photo", analysis_path=str(path)), context, dict(session_id="phone", generation=7))
    second = analyzer.analyze(dict(id="photo", analysis_path=str(path)), context, dict(session_id="phone", generation=8))
    assert first["video_size"] == [240,180]
    assert first["image_sha256"] == hashlib.sha256(saved).hexdigest()
    assert first["project_revision"] == 3 and first["runtime_revision"] == 7
    assert second["capture_id"] != first["capture_id"] and len(geometries) == 2
    assert locator.locate.call_count == 2
    np.testing.assert_array_equal(locator.locate.call_args.args[0], decoded)
    assert state.frame_bus.mock_calls == state.source.mock_calls == state.vision_worker.mock_calls == []
    analyzer.close()
    locator.close.assert_not_called()  # borrowed owner remains alive


def test_preview_quality_is_local_to_detected_targets():
    locator = SimpleNamespace(locate=Mock(return_value=None))
    analyzer = MobilePhotoAnalyzer(SimpleNamespace(), contexts={"raspberry-pi-5": SimpleNamespace(_locator=locator)})
    context = dict(design={"component_ids": ["ignored"]})
    frame = np.zeros((180,240,3), np.uint8)
    finding = analyzer.preview(frame, context, {"sample_seq":1})
    assert not finding["board_present"] and finding["reason"] == "find_board"
    corners = np.float32([[20,20], [220,20], [220,160], [20,160]])
    locator.locate.return_value = BoardPoseObservation(corners,.9,np.ones(4),(20,20,220,160))
    blurred = analyzer.preview(frame, context, {"sample_seq":2})
    assert blurred["board_present"] and blurred["framed"] and not blurred["sharp"]
    assert blurred["reason"] == "improve_focus_or_light"


def test_runtime_owner_replacement_refreshes_borrowed_models_without_closing_them(tmp_path, monkeypatch):
    profile = SimpleNamespace(board="pi")
    old, new = SimpleNamespace(close=Mock()), SimpleNamespace(close=Mock())
    primary = SimpleNamespace(_profile=profile, _locator=old)
    workers = [SimpleNamespace(_profile=SimpleNamespace(component_id=cid), _locator=SimpleNamespace(close=Mock()))
        for cid in ("hc-sr04", "mrd-tf240-8p-cs")]
    state = SimpleNamespace(detector=primary, component_workers=workers,
        profile_store=SimpleNamespace(profile=lambda cid:profile, board_dir=lambda cid:tmp_path), config=SimpleNamespace())
    monkeypatch.setattr("app.mobile_photo._canonical_reference_board", lambda *args:None)
    analyzer = MobilePhotoAnalyzer(state)
    first = analyzer._models()
    primary._locator = new
    refreshed = analyzer._models()
    assert first["raspberry-pi-5"]._locator is old
    assert refreshed["raspberry-pi-5"]._locator is new
    assert refreshed is analyzer._models()
    analyzer.close()
    old.close.assert_not_called()
    new.close.assert_not_called()
