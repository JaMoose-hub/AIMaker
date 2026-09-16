from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.scene_reference_search import SceneReferenceSearch
from app.vision.yolo_profile_detector import YoloProfileDetector
from test_reference_recovery import texture


def scene():
    ref = texture()
    frame = np.full((480, 640, 3), 25, np.uint8)
    frame[100:340, 150:470] = ref
    return ref, frame


def test_verified_reference_reacquires_without_detector_roi_and_never_holds_blank():
    ref, frame = scene()
    search = SceneReferenceSearch(ReferencePoseRecovery(ref))
    observation = search.locate(frame, 1, 100)
    assert observation is not None and observation.source == 'reference_sift'
    assert search.evidence['scope'] == 'scene_reference'
    expected = np.float32([[150,100],[469,100],[469,339],[150,339]])
    assert np.max(np.linalg.norm(observation.corners_px - expected, axis=1)) < 2
    cv2.line(frame, (260,85), (270,345), (20,130,240), 12)
    assert search.locate(frame, 2, 200) is not None
    assert search.evidence['scope'] == 'local_reference'
    assert search.locate(np.full_like(frame, 25), 3, 300) is None
    assert not search.evidence['accepted']


def test_global_search_is_throttled_and_duplicate_frames_cannot_repeat_it():
    calls = []
    matcher = SimpleNamespace(evidence={'accepted':False})
    matcher.locate = lambda frame, region: calls.append(region) or None
    search = SceneReferenceSearch(matcher)
    frame = np.zeros((480,640,3), np.uint8)
    for frame_id, ts in ((1,0),(1,0),(2,100),(3,499),(4,500)):
        assert search.locate(frame, frame_id, ts) is None
    assert len(calls) == 2
    assert calls[0].confidence == 0  # Window cannot masquerade as a detection.
    assert not hasattr(calls[0], 'corners_px')


@pytest.mark.parametrize('change', ['resolution', 'time', 'camera'])
def test_reset_discards_local_reference_window(change):
    ref, frame = scene()
    search = SceneReferenceSearch(ReferencePoseRecovery(ref))
    assert search.locate(frame, 10, 1000) is not None
    if change == 'resolution':
        frame = np.zeros((500,650,3), np.uint8)
    elif change == 'camera':
        search.reset()
    result = search.locate(frame, 1 if change == 'time' else 11, 0 if change == 'time' else 1100)
    assert (result is None) == (change == 'resolution')
    assert search.evidence['scope'] == 'scene_reference'


def test_eye_and_disabled_paths_never_invoke_scene_matcher():
    detector = object.__new__(YoloProfileDetector)
    detector._scene_reference = SimpleNamespace(locate=lambda *a: pytest.fail('Unexpected image search'))
    detector._scene_reference_enabled = False
    detector._yolo_only = False
    assert detector._recover_scene_reference(None, 1, 0) is None
    detector._scene_reference_enabled = True
    detector._yolo_only = True
    assert detector._recover_scene_reference(None, 1, 0) is None


def test_candidate_is_lazy_and_can_be_disabled_without_replacing_models():
    locator = SimpleNamespace(available=True)
    detector = YoloProfileDetector(locator=locator)
    assert not detector._scene_reference_enabled and detector._scene_reference is None
    detector._profile = SimpleNamespace(board=SimpleNamespace(id='raspberry-pi-5'))
    detector._reference_board_bgr = texture()
    detector.set_scene_reference_search(True)
    assert detector._scene_reference is not None and detector._locator is locator
    detector.set_scene_reference_search(False)
    assert detector._scene_reference is None and detector._locator is locator


def test_non_pi_profile_cannot_create_scene_search():
    detector = YoloProfileDetector(locator=SimpleNamespace(available=True))
    detector._profile = SimpleNamespace(board=SimpleNamespace(id='arduino-uno-q'))
    detector._reference_board_bgr = texture()
    detector.set_scene_reference_search(True)
    assert detector._scene_reference is None
