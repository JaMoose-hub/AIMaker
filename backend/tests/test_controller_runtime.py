from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import load_config
from app.profiles.store import ProfileStore
from app.query.service import QueryService
from app.runtime import BoardRuntimeManager, RuntimeSwitchError
from app.verification.state import VerificationState
from app.vision.endpoint_color import GuidanceColorPreviewState
from app.vision.guidance import GuidanceState, GuidanceStep
from app.vision.wire_state import WireTraceState
from app.vision_worker import DetectionState


ROOT = Path(__file__).resolve().parents[2]


class DummyDetector:
    def __init__(self, board_id: str) -> None:
        self.board_id = board_id
        self.closed = False

    def close(self) -> None:
        self.closed = True


class DummyVisionWorker:
    def __init__(self) -> None:
        self.swaps: list[tuple[DummyDetector, str, int]] = []

    def set_detector(self, detector, *, board_id=None, runtime_revision=None) -> None:
        self.swaps.append((detector, board_id, runtime_revision))


class DummyWorker:
    def __init__(self) -> None:
        self.board_ids: list[str] = []

    def set_board_id(self, board_id: str) -> None:
        self.board_ids.append(board_id)


class FailingWorker(DummyWorker):
    def __init__(self, rejected_board_id: str) -> None:
        super().__init__()
        self.rejected_board_id = rejected_board_id

    def set_board_id(self, board_id: str) -> None:
        self.board_ids.append(board_id)
        if board_id == self.rejected_board_id:
            raise RuntimeError("worker rejected board")


class DummyBroadcaster:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def publish_threadsafe(self, message: dict) -> None:
        self.messages.append(message)


def _state(config, store, initial_detector):
    profile = store.profile(config.board)
    guidance = GuidanceState()
    guidance.set_step(GuidanceStep("active", "3V3"), frozenset())
    return SimpleNamespace(
        scene=None,
        profile=profile,
        detector=initial_detector,
        vision_worker=DummyVisionWorker(),
        detection_state=DetectionState(),
        wire_state=WireTraceState(),
        guidance_state=guidance,
        verification_state=VerificationState(),
        guidance_color_preview=GuidanceColorPreviewState(),
        query_service=QueryService(profile),
        wire_worker=DummyWorker(),
        insertion_vlm_worker=DummyWorker(),
        final_wiring_vlm_worker=DummyWorker(),
        electrical_worker=DummyWorker(),
        broadcaster=DummyBroadcaster(),
        capture_service=object(),
    )


def test_runtime_switch_is_atomic_and_keeps_capture_service():
    config = load_config(ROOT / "backend" / "config.yaml")
    config.board = "arduino-uno-q"
    config.detector = "mock"
    store = ProfileStore(config.profile_dir)
    built: list[DummyDetector] = []

    def build(profile, _profile_dir, _scene):
        detector = DummyDetector(profile.board.id)
        built.append(detector)
        return detector

    manager = BoardRuntimeManager(
        config=config, profile_store=store, detector_builder=build
    )
    old = DummyDetector("arduino-uno-q")
    state = _state(config, store, old)
    capture = state.capture_service

    result = manager.select("raspberry-pi-5", state)

    assert result == {
        "ok": True,
        "changed": True,
        "board_id": "raspberry-pi-5",
        "runtime_revision": 2,
        "guide_was_active": True,
    }
    assert state.capture_service is capture
    assert state.profile.board.id == "raspberry-pi-5"
    assert state.detector is built[0]
    assert old.closed is True
    assert state.guidance_state.get_step() is None
    assert state.vision_worker.swaps[-1][1:] == ("raspberry-pi-5", 2)
    assert all(worker.board_ids[-1] == "raspberry-pi-5" for worker in (
        state.wire_worker,
        state.insertion_vlm_worker,
        state.final_wiring_vlm_worker,
        state.electrical_worker,
    ))
    assert state.broadcaster.messages[-1] == {
        "type": "runtime_changed",
        "board_id": "raspberry-pi-5",
        "runtime_revision": 2,
    }


def test_runtime_model_prepare_failure_retains_original_controller():
    config = load_config(ROOT / "backend" / "config.yaml")
    config.board = "arduino-uno-q"
    config.detector = "mock"
    store = ProfileStore(config.profile_dir)

    def fail(_profile, _profile_dir, _scene):
        raise OSError("bad model")

    manager = BoardRuntimeManager(
        config=config, profile_store=store, detector_builder=fail
    )
    old = DummyDetector("arduino-uno-q")
    state = _state(config, store, old)

    with pytest.raises(RuntimeSwitchError) as caught:
        manager.select("raspberry-pi-5", state)

    assert caught.value.error_code == "controller_model_load_failed"
    assert manager.board_id == "arduino-uno-q"
    assert manager.runtime_revision == 1
    assert state.detector is old
    assert old.closed is False
    assert state.vision_worker.swaps == []


def test_runtime_commit_failure_rolls_back_every_participant():
    config = load_config(ROOT / "backend" / "config.yaml")
    config.board = "arduino-uno-q"
    config.detector = "mock"
    store = ProfileStore(config.profile_dir)
    candidate = DummyDetector("raspberry-pi-5")

    manager = BoardRuntimeManager(
        config=config,
        profile_store=store,
        detector_builder=lambda _profile, _profile_dir, _scene: candidate,
    )
    old = DummyDetector("arduino-uno-q")
    state = _state(config, store, old)
    original_profile = state.profile
    original_query_service = state.query_service
    state.insertion_vlm_worker = FailingWorker("raspberry-pi-5")

    with pytest.raises(RuntimeSwitchError) as caught:
        manager.select("raspberry-pi-5", state)

    assert caught.value.error_code == "controller_switch_commit_failed"
    assert manager.board_id == "arduino-uno-q"
    assert manager.runtime_revision == 1
    assert config.board == "arduino-uno-q"
    assert config.runtime_revision == 1
    assert state.profile is original_profile
    assert state.query_service is original_query_service
    assert state.detector is old
    assert candidate.closed is True
    assert old.closed is False
    assert state.vision_worker.swaps[-1] == (old, "arduino-uno-q", 1)
    assert state.wire_worker.board_ids == ["raspberry-pi-5", "arduino-uno-q"]
    assert state.guidance_state.get_step() is not None
    assert state.broadcaster.messages == []
