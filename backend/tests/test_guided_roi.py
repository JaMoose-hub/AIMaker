from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

from app.vision.guidance import GuidanceStep
from app.vision.guided_roi import GuidedRoiVerifier, _change_fraction
from app.vision.interface import PinDetection


BOARD_CENTER = (90.0, 100.0)
COMPONENT_CENTER = (250.0, 100.0)
STEP = GuidanceStep(
    step_id="photoresistor-vcc",
    expected_pin_id="3V3",
    expected_role="VCC",
    component_id="photoresistor-module",
)


def _scene() -> np.ndarray:
    frame = np.full((220, 340, 3), 92, dtype=np.uint8)
    for y in range(0, frame.shape[0], 8):
        frame[y:y + 3] = 108
    for x in range(0, frame.shape[1], 10):
        frame[:, x:x + 2] = 78
    return frame


def _detection():
    return SimpleNamespace(
        tracking="locked",
        pins=[PinDetection("3V3", *BOARD_CENTER, confidence=0.9, visible=True)],
    )


def _component(tracking="locked"):
    pin = SimpleNamespace(id="VCC", x=COMPONENT_CENTER[0], y=COMPONENT_CENTER[1], visible=True)
    return SimpleNamespace(
        component_id="photoresistor-module", tracking=tracking, pins=(pin,)
    )


def _add_connector(frame: np.ndarray, center: tuple[float, float]) -> None:
    cv2.rectangle(
        frame,
        (int(center[0] - 7), int(center[1] - 9)),
        (int(center[0] + 7), int(center[1] + 9)),
        (0, 0, 245),
        -1,
    )


def test_both_stable_endpoint_changes_become_visual_candidate() -> None:
    verifier = GuidedRoiVerifier(stable_hits=2)
    baseline = _scene()
    assert verifier.update(STEP, baseline, _detection(), _component())["status"] == "baseline"

    connected = baseline.copy()
    _add_connector(connected, BOARD_CENTER)
    _add_connector(connected, COMPONENT_CENTER)
    # First changed frame is intentionally rejected as motion. Two stable
    # frames must follow before the visual candidate can be published.
    assert verifier.update(STEP, connected, _detection(), _component())["status"] == "uncertain"
    assert verifier.update(STEP, connected, _detection(), _component())["status"] == "pending"
    result = verifier.update(STEP, connected, _detection(), _component())
    assert result["status"] == "candidate"
    assert result["reason"] == "both_endpoints_changed"
    assert result["board_change"] >= 0.08
    assert result["component_change"] >= 0.08


def test_one_changed_endpoint_never_becomes_candidate() -> None:
    verifier = GuidedRoiVerifier(stable_hits=1)
    baseline = _scene()
    verifier.update(STEP, baseline, _detection(), _component())
    one_end = baseline.copy()
    _add_connector(one_end, BOARD_CENTER)
    verifier.update(STEP, one_end, _detection(), _component())
    result = verifier.update(STEP, one_end, _detection(), _component())
    assert result["status"] == "pending"
    assert result["reason"] == "board_endpoint_only"


def test_global_exposure_shift_is_not_a_connector() -> None:
    verifier = GuidedRoiVerifier(stable_hits=1)
    baseline = _scene()
    verifier.update(STEP, baseline, _detection(), _component())
    brighter = np.clip(baseline.astype(np.int16) + 28, 0, 255).astype(np.uint8)
    result = verifier.update(STEP, brighter, _detection(), _component())
    assert result["status"] != "candidate"


def test_small_detector_jitter_is_aligned_before_change_measurement() -> None:
    patch = _scene()[70:131, 60:121]
    shifted = cv2.warpAffine(
        patch,
        np.float32([[1, 0, 3], [0, 1, -2]]),
        (patch.shape[1], patch.shape[0]),
        borderMode=cv2.BORDER_REFLECT_101,
    )
    assert _change_fraction(patch, shifted) < 0.10


def test_short_component_tracker_hold_keeps_frozen_pin_pose_usable() -> None:
    verifier = GuidedRoiVerifier()
    result = verifier.update(STEP, _scene(), _detection(), _component("stale"))
    assert result["status"] == "baseline"
    assert result["reason"] == "baseline_captured"


def test_warm_desk_or_yellow_wire_fraction_does_not_fake_hand_occlusion() -> None:
    """A minority of skin-band pixels is common in the real desk scene."""
    verifier = GuidedRoiVerifier()
    frame = _scene()
    # Typical warm BGR value inside the broad YCrCb skin range.  Cover about
    # 24% of the 25x25 endpoint patch: above the old 0.16 gate, but well below
    # the measured 0.73 real-hand patch.
    cv2.rectangle(frame, (78, 88), (83, 112), (80, 120, 180), -1)

    result = verifier.update(STEP, frame, _detection(), _component())

    assert result["status"] == "baseline"
    assert result["reason"] == "baseline_captured"


def test_real_hand_sized_skin_region_still_blocks_baseline() -> None:
    verifier = GuidedRoiVerifier()
    frame = _scene()
    cv2.rectangle(frame, (78, 88), (96, 112), (80, 120, 180), -1)

    result = verifier.update(STEP, frame, _detection(), _component())

    assert result["status"] == "uncertain"
    assert result["reason"] == "hand_occlusion"
