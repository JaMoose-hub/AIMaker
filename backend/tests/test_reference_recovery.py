from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.vision.reference_recovery import ReferencePoseRecovery, _mutual_ratio_matches


def texture():
    rng = np.random.default_rng(1024)
    image = np.full((240, 320, 3), 40, np.uint8)
    for _ in range(600):
        p = tuple(rng.integers([5, 5], [315, 235]).tolist())
        color = tuple(rng.integers(60, 255, 3).tolist())
        cv2.circle(image, p, int(rng.integers(1, 5)), color, -1)
    return image


def region():
    # Deliberately no corners: a bounding box cannot carry semantic pin order.
    return SimpleNamespace(box_xyxy=(90, 50, 450, 350), confidence=.9)


@pytest.mark.parametrize('turn', range(4))
def test_recovery_establishes_semantic_order_under_wire_occlusion(turn):
    reference = texture()
    frame = np.full((480, 640, 3), 25, np.uint8)
    src = np.float32([[0, 0], [319, 0], [319, 239], [0, 239]])
    dst = np.roll(np.float32([[110, 80], [410, 70], [430, 320], [100, 330]]), turn, axis=0)
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(reference, matrix, (640, 480))
    mask = cv2.warpPerspective(np.full(reference.shape[:2], 255, np.uint8), matrix, (640, 480))
    frame[mask > 0] = warped[mask > 0]
    cv2.line(frame, (170, 65), (350, 340), (20, 160, 240), 12)
    recovery = ReferencePoseRecovery(reference)
    observation = recovery.locate(frame, region())
    assert observation is not None, recovery.evidence
    assert observation.source == 'reference_sift'
    assert np.max(np.linalg.norm(observation.corners_px-dst, axis=1)) < 2
    assert recovery.evidence['coverage'] >= .18


@pytest.mark.parametrize('kind', ['blank', 'mirror', 'local_patch'])
def test_recovery_rejects_missing_or_unverified_semantics(kind):
    reference = texture()
    frame = np.full((480, 640, 3), 25, np.uint8)
    if kind == 'mirror':
        frame[80:320, 110:430] = reference[:, ::-1]
    elif kind == 'local_patch':
        frame[90:150, 120:180] = reference[10:70, 10:70]
    recovery = ReferencePoseRecovery(reference)
    assert recovery.locate(frame, region()) is None
    assert not recovery.evidence['accepted']


def test_component_reference_is_runtime_asset_not_test_dependency():
    path = Path(__file__).resolve().parents[2] / 'profiles/components/hw-123/vision_profile.json'
    recovery = ReferencePoseRecovery.from_component_profile(path)
    assert recovery is not None and len(recovery.keypoints) > 50
    hc = ReferencePoseRecovery.from_component_profile(path.parent.parent/'hc-sr04/vision_profile.json')
    assert hc is not None and hc.descriptors is not None


def test_evidence_does_not_leak_between_frames():
    recovery = ReferencePoseRecovery(texture())
    recovery.evidence = {'accepted': True, 'inliers': 100}
    assert recovery.locate(np.zeros((480, 640, 3), np.uint8)) is None
    assert recovery.evidence['accepted'] is False
    assert 'inliers' not in recovery.evidence


@pytest.mark.parametrize('seed', [2, 17, 42])
@pytest.mark.parametrize('kind', ['matches', 'duplicates', 'unrelated', 'single_neighbor'])
def test_subset_reverse_matching_is_identical_to_full_brute_force(seed, kind):
    rng = np.random.default_rng(seed)
    reference = rng.integers(0, 180, (120, 128)).astype(np.float32)
    frame = rng.integers(0, 180, (160, 128)).astype(np.float32)
    if kind in ('matches', 'duplicates'):
        frame[::4] = reference[::3] + rng.integers(-3, 4, (40, 128))
    if kind == 'duplicates':
        frame[1::4] = frame[::4]
        reference[1::3] = reference[::3]
    if kind == 'single_neighbor':
        frame = frame[:1]
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    pairs = matcher.knnMatch(reference, frame, k=2)
    reverse = {m.queryIdx: m.trainIdx for m in matcher.match(frame, reference)}
    expected = [a for pair in pairs if len(pair) == 2 for a, b in [pair]
                if a.distance < .72*b.distance and reverse.get(a.trainIdx) == a.queryIdx]
    actual = _mutual_ratio_matches(reference, frame)
    signature = lambda matches: [(m.queryIdx, m.trainIdx, m.distance) for m in matches]
    assert signature(actual) == signature(expected)
