from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import cv2
import numpy as np

from app.vision.interface import PinDetection
from app.vision.pi5_pin_stability import PinImageAnchor, PinUpdateGate
from app.vision.wire_tracer import projected_pin_pitch
from app.vision.yolo_profile_detector import _correct_pi5_j8_from_image
from app.vision import yolo_profile_detector as yp
from app.vision.yolo_pose import BoardPoseObservation
from app.profiles.store import ProfileStore


def pins(row_sep=16.0, dx=0.0, dy=0.0):
    return [PinDetection(str(i+1), 60+18*(i//2)+dx,
                         100+row_sep*(i % 2)+dy, 1.0, True, "J8", i+1)
            for i in range(40)]


def test_outer_body_width_never_doubles_j8_row_spacing():
    frame = np.full((220, 460, 3), 180, np.uint8)
    polygon = np.array([[51, 97], [56, 92], [406, 92], [411, 97],
                        [411, 119], [406, 124], [56, 124], [51, 119]])
    cv2.fillConvexPoly(frame, polygon, (30, 30, 30))
    # A connected chip widens the contour but not the full-length housing.
    cv2.rectangle(frame, (90, 60), (185, 94), (30, 30, 30), -1)
    prior = pins()
    result = _correct_pi5_j8_from_image(
        frame, SimpleNamespace(board=SimpleNamespace(id="raspberry-pi-5")), prior, (460, 220))
    assert result is not prior  # exercise successful local correction, not fallback
    for a, b in zip(result[::2], result[1::2]):
        assert abs(np.hypot(a.x-b.x, a.y-b.y) - 16) < 1e-6


def test_j8_pitch_measures_along_rows_not_separation_or_diagonals():
    assert projected_pin_pitch(pins(row_sep=16)) == 18
    assert projected_pin_pitch(pins(row_sep=32)) == 18
    # Other headers keep their established sequential numbering convention.
    row = [PinDetection(str(i), i*10, 0, 1, True, "D", i) for i in range(8)]
    assert projected_pin_pitch(row) == 10


def textured_board():
    rng = np.random.default_rng(408)
    gray = rng.integers(30, 220, (220, 460), dtype=np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def test_image_anchor_holds_only_fresh_static_texture():
    frame = textured_board()
    anchor = PinImageAnchor()
    anchor.seed(frame, pins(), [(25, 20), (435, 20), (435, 195), (25, 195)])
    assert anchor.points is not None
    assert anchor.stationary(frame.copy())
    assert anchor.fully_supported
    assert anchor.motion_px < .01 and anchor.support >= 20
    moved = cv2.warpAffine(frame, np.float32([[1, 0, 9], [0, 1, 6]]), (460, 220))
    assert not anchor.stationary(moved)
    # Return to the anchor: no accumulated optical-flow drift.
    assert anchor.stationary(frame)
    hidden = frame.copy()
    hidden[65:152, 42:425] = 127
    assert not anchor.stationary(hidden)
    assert not anchor.fully_supported
    assert not anchor.stationary(np.zeros((110, 230, 3), np.uint8))
    assert anchor.points is None


def test_image_anchor_refuses_textureless_or_short_visible_section():
    anchor = PinImageAnchor()
    blank = np.full((220, 460, 3), 125, np.uint8)
    anchor.seed(blank, pins(), [(25, 20), (435, 20), (435, 195), (25, 195)])
    assert not anchor.stationary(blank)
    blank[:, :90] = textured_board()[:, :90]
    anchor.seed(blank, pins(), [(25, 20), (435, 20), (435, 195), (25, 195)])
    assert anchor.points is None


def test_anchor_crops_1080p_without_rescaling_motion_or_trusting_occlusion():
    frame = np.full((1080, 1920, 3), 125, np.uint8)
    frame[400:620, 600:1060] = textured_board()
    target = pins(dx=600, dy=400)
    outline = [(625, 420), (1035, 420), (1035, 595), (625, 595)]
    anchor = PinImageAnchor()
    anchor.seed(frame, target, outline)
    assert anchor.points is not None
    assert anchor.gray.size < frame.shape[0] * frame.shape[1] / 4
    assert anchor.roi[0] % 4 == 0 and anchor.roi[1] % 4 == 0
    assert anchor.stationary(frame)
    moved = cv2.warpAffine(frame, np.float32([[1, 0, 3], [0, 1, 0]]), (1920, 1080))
    assert not anchor.stationary(moved)
    assert anchor.motion_px is None or anchor.motion_px > 1
    hidden = frame.copy()
    hidden[465:552, 642:1025] = 127
    assert not anchor.stationary(hidden)
    # A changed source geometry invalidates the anchor even if crop still fits.
    assert not anchor.stationary(frame[:1000])
    assert anchor.roi is None and anchor.frame_shape is None


def test_pin_gate_catches_local_jump_even_when_board_corners_are_fixed():
    gate = PinUpdateGate(2)
    base = pins()
    assert not gate.ready(pins(row_sep=32), base)
    assert gate.ready(base, base)  # jitter returned; pending large pose is discarded
    assert not gate.ready(pins(row_sep=32), base)
    assert not gate.ready(pins(dx=20), base)
    assert gate.ready(pins(dx=20.2), base)  # sustained real relocation can re-lock
    gate.reset()
    assert not gate.ready(pins(dx=20.2), base)
    invalid = [replace(p, x=float("nan")) for p in base]
    assert not gate.ready(invalid, base)


def test_pending_pin_update_must_keep_pin_identity():
    gate = PinUpdateGate()
    assert not gate.ready(pins(dx=9), pins())
    assert not gate.ready(list(reversed(pins(dx=9))), pins())
    assert not gate.ready(pins(dx=9), pins())


def test_pi5_image_anchor_and_pin_gate_reacquire_real_motion(monkeypatch):
    # Generated texture + known image translation, not physical accuracy.
    rng = np.random.default_rng(20260907)
    gray = rng.integers(30, 220, (380, 560), dtype=np.uint8)
    image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    quad = np.array([[100., 60.], [440., 60.], [440., 284.], [100., 284.]])
    class Locator:
        available = True
        observation = None
        def locate(self, _):
            return self.observation
        def close(self):
            pass
    locator = Locator()
    def observation(q):
        return BoardPoseObservation(q, .95, np.full(4, .95), (*q.min(0), *q.max(0)))
    monkeypatch.setattr(yp, "refine_board_corners_from_pcb", lambda *a, **kw: None)
    monkeypatch.setattr(yp, "_correct_pi5_j8_from_image", lambda frame, profile, pins, size: pins)
    store = ProfileStore(Path(__file__).resolve().parents[2] / "profiles")
    detector = yp.YoloProfileDetector(locator=locator, jump_confirm_frames=2,
                                      deadband_exit_confirm_frames=2,
                                      max_reprojection_error_px=12)
    detector.load(store.profile("raspberry-pi-5"), store.board_dir("raspberry-pi-5"))
    locator.observation = observation(quad)
    initial = detector.detect(image, 0, 0)
    assert initial.tracking == "locked"
    try:
        for i in range(1, 7):
            locator.observation = observation(quad + [(-1)**i * 8, (-1)**i * 5])
            result = detector.detect(image, i, i*120)
            assert result.tracking == "locked"
            assert result.pose_image_support >= 20
            assert result.pose_image_confirmed
            assert result.pins == initial.pins
        delta = np.array([24., 16.])
        moved = cv2.warpAffine(image, np.float32([[1, 0, 24], [0, 1, 16]]), (560, 380))
        locator.observation = observation(quad + delta)
        states = []
        for i in range(7, 11):
            result = detector.detect(moved, i, i*120)
            states.append(result.tracking)
            if result.tracking == "locked":
                break
        assert states == ["stale", "stale", "locked"]
        shift = np.array([result.pins[0].x-initial.pins[0].x,
                          result.pins[0].y-initial.pins[0].y])
        assert np.linalg.norm(shift-delta) < .01
        locator.observation = None
        hidden_result = detector.detect(np.zeros_like(image), 11, 1320)
        assert hidden_result.tracking == "stale"
        assert not hidden_result.pose_image_confirmed
        # Pending candidates cannot survive a detection gap.
        assert detector._pin_update_gate.count == 0
        detector._reset_temporal()
        assert detector._pin_image_anchor.gray is None
    finally:
        detector.close()
