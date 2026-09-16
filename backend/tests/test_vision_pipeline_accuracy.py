"""PipelineDetector accuracy against SyntheticScene ground truth.

Acceptance (plan M3/M4 scaled to synthetic, 1280x720):
- locks within 10 frames;
- once locked, median pin error vs truth <= 5 px, p95 <= 10 px;
- a trajectory starting 180-degrees rotated still locks with the correct
  orientation (pin identity check on D0).

Per-frame timing for the detection vs tracking paths is printed (no hard
assert) — run with ``pytest -s`` to see it on success.
"""
import math
import statistics
import sys
from types import SimpleNamespace
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import pytest
import cv2

from app.vision.factory import create_detector
from app.vision.pose_tracker import (
    _inlier_board_area_fraction,
    _unique_lowe_matches,
)
from app.vision.synthetic import SyntheticScene
from app.vision.wire_tracer import trace
from vision_fixtures.make_fixture import build_fixture

VIDEO_SIZE = (1280, 720)
VIDEO_SIZE_C920_1080 = (1920, 1080)


def test_lowe_matches_do_not_count_duplicate_reference_descriptors():
    """Repeated texture must not inflate the geometric inlier candidate set."""
    def match(query_idx: int, train_idx: int, distance: float):
        return SimpleNamespace(queryIdx=query_idx, trainIdx=train_idx,
                               distance=distance)

    # Query 0 and query 1 both prefer reference descriptor 0.  Query 0 is
    # stronger and must win; query 2 independently maps to descriptor 1.
    knn = [
        [match(0, 0, 1.0), match(0, 1, 4.0)],
        [match(1, 0, 2.0), match(1, 1, 3.0)],
        [match(2, 1, 1.0), match(2, 0, 4.0)],
    ]
    reference = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float64)
    keypoints = [SimpleNamespace(pt=(1.0, 2.0)),
                 SimpleNamespace(pt=(3.0, 4.0)),
                 SimpleNamespace(pt=(5.0, 6.0))]

    mm, px = _unique_lowe_matches(knn, reference, keypoints, (100, 200), 0.75)

    assert mm.tolist() == [[10.0, 20.0], [30.0, 40.0]]
    assert px.tolist() == [[101.0, 202.0], [105.0, 206.0]]


def test_homography_inliers_must_cover_more_than_a_local_texture_patch():
    board = (68.58, 53.34)
    broad = np.array([[5.0, 5.0], [35.0, 5.0], [35.0, 30.0],
                      [5.0, 30.0]], dtype=np.float64)
    local = np.array([[10.0, 10.0], [18.0, 10.0], [18.0, 14.0],
                      [10.0, 14.0]], dtype=np.float64)

    assert _inlier_board_area_fraction(broad, board) > 0.20
    assert _inlier_board_area_fraction(local, board) < 0.05


def test_homography_cull_rejects_local_patch_even_with_valid_board_quad(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    detector = create_detector("pipeline", profile, profile_dir)
    try:
        # Prime the tracker so its frame dimensions and camera model are live.
        for k in range(3):
            detector.detect(scene.frame_at(k * 0.1), k, k * 100.0)
        tracker = detector.tracker
        assert tracker is not None

        # Twenty-five exact correspondences occupy only a small repeated-texture
        # patch, but the candidate homography extrapolates to a valid board-sized
        # quad. The spatial gate must reject it before PnP.
        xs = np.linspace(10.0, 18.0, 5)
        ys = np.linspace(10.0, 14.0, 5)
        grid_x, grid_y = np.meshgrid(xs, ys)
        mm = np.column_stack([grid_x.ravel(), grid_y.ravel()])
        H = np.array([[8.0, 0.0, 220.0],
                      [0.0, 8.0, 110.0],
                      [0.0, 0.0, 1.0]], dtype=np.float64)
        homogeneous = (H @ np.column_stack([mm, np.ones(len(mm))]).T).T
        px = homogeneous[:, :2] / homogeneous[:, 2:3]

        assert tracker._homography_cull(mm, px) is None
    finally:
        detector.close()


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return build_fixture(tmp_path_factory.mktemp("boardfix"))


def _run(detector, scene, times):
    """Feed frames, return (results, truths, timing rows)."""
    results, truths, timing = [], [], []
    for i, t in enumerate(times):
        frame = scene.frame_at(t)
        r = detector.detect(frame, i, t * 1000.0)
        results.append(r)
        truths.append(scene.truth_at(t, i))
        tracker = detector.tracker
        if tracker is not None:
            timing.append((tracker.last_path, tracker.last_step_ms))
    return results, truths, timing


def _pin_errors(result, truth):
    truth_by_id = {p.pin_id: p for p in truth.pins}
    errs = []
    for pin in result.pins:
        tp = truth_by_id[pin.pin_id]
        if tp.visible:
            errs.append(float(np.hypot(pin.x - tp.x, pin.y - tp.y)))
    return errs


def _report_timing(label, timing):
    for path in ("detect", "track"):
        ms = [m for p, m in timing if p == path]
        if ms:
            print(f"[timing] {label}: {path} path n={len(ms)} "
                  f"mean={statistics.mean(ms):.1f}ms "
                  f"median={statistics.median(ms):.1f}ms "
                  f"max={max(ms):.1f}ms")


def test_pipeline_accuracy_over_trajectory(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    detector = create_detector("pipeline", profile, profile_dir)

    # ~40 frames spread over 6 s of trajectory: yaw sweeps ~36 deg and the
    # tilt rises from 0 to ~10 deg (includes clearly tilted views).
    times = [k * 0.15 for k in range(41)]
    results, truths, timing = _run(detector, scene, times)
    _report_timing("accuracy", timing)

    first_locked = next((i for i, r in enumerate(results)
                         if r.tracking == "locked"), None)
    assert first_locked is not None and first_locked < 10, \
        f"did not lock within 10 frames (first lock: {first_locked})"

    errs = []
    for r, tr in zip(results[first_locked:], truths[first_locked:]):
        if r.tracking == "locked":
            errs.extend(_pin_errors(r, tr))
    assert errs, "no locked frames after first lock"
    med = float(np.median(errs))
    p95 = float(np.percentile(errs, 95))
    print(f"[accuracy] pin error: median={med:.2f}px p95={p95:.2f}px "
          f"n={len(errs)}")
    assert med <= 5.0, f"median pin error {med:.2f}px > 5px"
    assert p95 <= 10.0, f"p95 pin error {p95:.2f}px > 10px"

    detector.close()


def test_pipeline_locks_on_180_degree_rotation(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE, yaw0_deg=180.0)
    detector = create_detector("pipeline", profile, profile_dir)

    times = [k * 0.15 for k in range(25)]
    results, truths, timing = _run(detector, scene, times)
    _report_timing("rot180", timing)

    first_locked = next((i for i, r in enumerate(results)
                         if r.tracking == "locked"), None)
    assert first_locked is not None and first_locked < 10

    # Orientation check: pin D0 must be at the truth's (rotated) end of the
    # board. A flipped lock would put it ~a board-length away.
    checked = 0
    for r, tr in zip(results[first_locked:], truths[first_locked:]):
        if r.tracking != "locked":
            continue
        d0 = next(p for p in r.pins if p.pin_id == "D0")
        d0_t = next(p for p in tr.pins if p.pin_id == "D0")
        err = float(np.hypot(d0.x - d0_t.x, d0.y - d0_t.y))
        assert err <= 10.0, f"D0 off by {err:.1f}px — wrong orientation?"
        checked += 1
    assert checked >= 5

    detector.close()


@pytest.mark.parametrize(
    "yaw0_deg,video_size",
    [(90.0, VIDEO_SIZE), (270.0, VIDEO_SIZE_C920_1080)],
)
def test_pipeline_accuracy_on_quarter_turns_and_output_sizes(
    fixture, yaw0_deg, video_size,
):
    """Quarter-turn orientation must survive the source-size change.

    The UI and wire tracer consume source-frame coordinates, so a pose that
    locks at one resolution but flips or drifts after a 90/270-degree turn is
    still an accuracy failure.  Keep one case at the synthetic demo size and
    one on the physical C920 1080p path.
    """
    profile, profile_dir = fixture
    scene = SyntheticScene(
        profile, profile_dir, video_size, yaw0_deg=yaw0_deg,
        horizontal_fov_deg=70.42,
    )
    detector = create_detector(
        "pipeline", profile, profile_dir, horizontal_fov_deg=70.42,
    )
    try:
        results, truths, _ = _run(
            detector, scene, [k * 0.15 for k in range(18)],
        )
        first_locked = next(
            (i for i, result in enumerate(results)
             if result.tracking == "locked"),
            None,
        )
        assert first_locked is not None and first_locked < 10

        errors = []
        checked = 0
        for result, truth in zip(results[first_locked:], truths[first_locked:]):
            if result.tracking != "locked":
                continue
            errors.extend(_pin_errors(result, truth))
            predicted = next(pin for pin in result.pins if pin.pin_id == "D0")
            expected = next(pin for pin in truth.pins if pin.pin_id == "D0")
            assert math.hypot(predicted.x - expected.x,
                              predicted.y - expected.y) <= 10.0
            checked += 1
        assert errors and checked >= 5
        median = float(np.median(errors))
        p95 = float(np.percentile(errors, 95))
        assert median <= 5.0
        assert p95 <= 10.0
        if yaw0_deg == 270.0 and video_size == VIDEO_SIZE_C920_1080:
            # This is the motion-lag tuning sentinel for the physical 1080p
            # path. The general acceptance gate is intentionally broader,
            # but beta=30 should keep this worst orientation below the
            # tighter 3.5px/7px regression budget.
            assert median <= 3.5, f"270-degree median {median:.2f}px > 3.5px"
            assert p95 <= 7.0, f"270-degree p95 {p95:.2f}px > 7px"
    finally:
        detector.close()


def test_pipeline_accuracy_on_1080p_c920_fov_path(fixture):
    """The physical deployment intrinsics must have a matching regression.

    This is still synthetic and cannot prove the lens or lighting, but it
    catches accidentally routing the 1080p device through the generic 0.9W
    camera model.
    """
    profile, profile_dir = fixture
    fov = 70.42
    scene = SyntheticScene(
        profile, profile_dir, VIDEO_SIZE_C920_1080,
        horizontal_fov_deg=fov,
    )
    detector = create_detector(
        "pipeline", profile, profile_dir, horizontal_fov_deg=fov,
    )

    results, truths, _ = _run(detector, scene, [k * 0.15 for k in range(21)])
    first_locked = next((i for i, r in enumerate(results)
                         if r.tracking == "locked"), None)
    assert first_locked is not None and first_locked < 10
    errors = []
    for result, truth in zip(results[first_locked:], truths[first_locked:]):
        if result.tracking == "locked":
            errors.extend(_pin_errors(result, truth))
    assert errors
    assert float(np.median(errors)) <= 5.0
    assert float(np.percentile(errors, 95)) <= 10.0
    detector.close()


def test_pipeline_pose_feeds_wire_trace_with_canonical_pin_identity(fixture):
    """The detector's projected pins must remain usable by wire tracing.

    This is intentionally an integration regression rather than another
    isolated snap test: the board pose is recovered from the rendered image,
    then a wire is overlaid on that same source frame and traced with the
    detector's pin projection and exclusion polygon.
    """
    profile, profile_dir = fixture
    scene = SyntheticScene(
        profile, profile_dir, VIDEO_SIZE_C920_1080,
        horizontal_fov_deg=70.42,
    )
    detector = create_detector(
        "pipeline", profile, profile_dir, horizontal_fov_deg=70.42,
    )
    try:
        for frame_id in range(8):
            ts_s = 0.1 * frame_id
            base = scene.frame_at(ts_s)
            detection = detector.detect(base, frame_id, ts_s * 1000.0)
            if detection.tracking != "locked":
                continue

            truth = scene.truth_at(ts_s, frame_id)
            target = next(pin for pin in truth.pins if pin.pin_id == "D0")
            frame = base.copy()
            start = (round(target.x), round(target.y))
            end = (max(0, start[0] - 240), max(0, start[1] - 220))
            cv2.line(frame, start, end, (0, 0, 235), 10, cv2.LINE_AA)

            result = trace(
                frame,
                detection.pins,
                frame_id,
                ts_s * 1000.0,
                detection.tracking,
                colors=["red"],
                board_outline=detection.wire_exclusion_px,
            )
            resolved = {
                endpoint.pin_id
                for wire in result.wires
                for endpoint in (wire.endpoint_a, wire.endpoint_b)
                if endpoint.kind == "pin"
            }
            assert "D0" in resolved
            return
    finally:
        detector.close()

    raise AssertionError("pipeline did not lock during the integration replay")


def test_pipeline_accuracy_on_30_degree_oblique_pose(fixture):
    """A deliberately oblique board must keep the 3-D pin projection honest."""
    profile, profile_dir = fixture
    scene = SyntheticScene(
        profile, profile_dir, VIDEO_SIZE_C920_1080,
        horizontal_fov_deg=70.42,
    )

    # Keep the board centred, then apply a fixed 30-degree tilt around the
    # camera x axis.  The fixture's normal trajectory only reaches ~12
    # degrees, so this is a separate perspective/height-parallax regression.
    yaw = math.radians(25.0)
    tilt = math.radians(30.0)
    rz, _ = cv2.Rodrigues(np.array([0.0, 0.0, yaw], dtype=np.float64))
    rx, _ = cv2.Rodrigues(np.array([tilt, 0.0, 0.0], dtype=np.float64))
    rotation = rx @ rz
    centre_cam = np.array([0.0, 0.0, 200.0], dtype=np.float64)
    centre_board = np.array([
        profile.board.outline_mm[0] / 2.0,
        profile.board.outline_mm[1] / 2.0,
        0.0,
    ])
    translation = centre_cam - rotation @ centre_board
    fixed_rvec, _ = cv2.Rodrigues(rotation)
    fixed_rvec = fixed_rvec.reshape(3)
    fixed_tvec = translation.reshape(3)
    scene.pose_at = lambda _t: (fixed_rvec, fixed_tvec)

    detector = create_detector(
        "pipeline", profile, profile_dir, horizontal_fov_deg=70.42,
    )
    try:
        results, truths, _ = _run(
            detector, scene, [k * 0.1 for k in range(12)],
        )
        first_locked = next(
            (i for i, result in enumerate(results)
             if result.tracking == "locked"),
            None,
        )
        assert first_locked is not None and first_locked < 10

        errors = []
        for result, truth in zip(results[first_locked:], truths[first_locked:]):
            if result.tracking == "locked":
                errors.extend(_pin_errors(result, truth))
        assert errors
        assert float(np.median(errors)) <= 5.0
        assert float(np.percentile(errors, 95)) <= 10.0
    finally:
        detector.close()


def test_pipeline_accuracy_on_60_degree_side_oblique_pose(fixture):
    """The SIFT rescue path must retain a strong side-oblique lock.

    At this angle the board is heavily foreshortened and the normal ORB path
    loses enough descriptors to miss the 25-inlier floor.  The fallback may
    widen its descriptor ratio, but the accepted homography/PnP gates remain
    unchanged, so this test still measures the resulting pin geometry.
    """
    profile, profile_dir = fixture
    scene = SyntheticScene(
        profile, profile_dir, VIDEO_SIZE_C920_1080,
        horizontal_fov_deg=70.42,
    )
    yaw = math.radians(25.0)
    tilt = math.radians(60.0)
    rz, _ = cv2.Rodrigues(np.array([0.0, 0.0, yaw], dtype=np.float64))
    rx, _ = cv2.Rodrigues(np.array([tilt, 0.0, 0.0], dtype=np.float64))
    rotation = rx @ rz
    centre_cam = np.array([0.0, 0.0, 200.0], dtype=np.float64)
    centre_board = np.array([
        profile.board.outline_mm[0] / 2.0,
        profile.board.outline_mm[1] / 2.0,
        0.0,
    ])
    translation = centre_cam - rotation @ centre_board
    fixed_rvec, _ = cv2.Rodrigues(rotation)
    fixed_rvec = fixed_rvec.reshape(3)
    fixed_tvec = translation.reshape(3)
    scene.pose_at = lambda _t: (fixed_rvec, fixed_tvec)

    detector = create_detector(
        "pipeline", profile, profile_dir, horizontal_fov_deg=70.42,
    )
    try:
        results, truths, _ = _run(
            detector, scene, [k * 0.1 for k in range(12)],
        )
        first_locked = next(
            (i for i, result in enumerate(results)
             if result.tracking == "locked"),
            None,
        )
        assert first_locked is not None and first_locked < 10

        errors = []
        for result, truth in zip(results[first_locked:], truths[first_locked:]):
            if result.tracking == "locked":
                errors.extend(_pin_errors(result, truth))
        assert errors
        assert float(np.median(errors)) <= 5.0
        assert float(np.percentile(errors, 95)) <= 10.0
    finally:
        detector.close()


def test_pipeline_sift_rescue_does_not_lock_on_non_board_texture(fixture):
    """The wider rescue descriptor ratio must not create a false board lock."""
    profile, profile_dir = fixture
    detector = create_detector(
        "pipeline", profile, profile_dir, horizontal_fov_deg=70.42,
    )
    rng = np.random.default_rng(42)
    frame = np.full((1080, 1920, 3), (25, 55, 130), dtype=np.uint8)
    # Deliberately satisfy the dark-blue ROI gate, but replace the board with
    # deterministic unrelated texture.  This exercises the same SIFT rescue
    # path that the severe-oblique test uses.
    frame[330:710, 600:1320] = rng.integers(
        0, 256, size=(380, 720, 3), dtype=np.uint8,
    )
    try:
        results = [
            detector.detect(frame, i, i * 100.0)
            for i in range(12)
        ]
        assert all(result.tracking != "locked" for result in results)
    finally:
        detector.close()
