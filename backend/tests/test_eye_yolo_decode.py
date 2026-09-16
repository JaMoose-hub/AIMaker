"""Score-first decoding must exactly preserve the original decoder result."""
from dataclasses import asdict

import numpy as np
import pytest

from app.vision.eye_yolo_decode import prefilter_class_scores
from app.vision.yolo_pose import decode_yolo_pose_output


def assert_same(first, second):
    if first is None:
        assert second is None
        return
    assert second is not None
    for name, value in asdict(first).items():
        np.testing.assert_equal(value, asdict(second)[name])


@pytest.mark.parametrize('layout', ['channels', 'rows', 'batch'])
@pytest.mark.parametrize('keypoints,classes,class_id', [(4,1,0),(4,4,2),(8,1,0)])
@pytest.mark.parametrize('candidates', [0,1,17,80])
def test_sparse_dense_multiclass_and_landmark_outputs_are_identical(layout, keypoints, classes, class_id, candidates):
    rng = np.random.default_rng(91)
    channels = 4 + classes + keypoints*3
    rows = np.zeros((250,channels),np.float32)
    rows[:,:4] = rng.uniform([200,200,50,50],[600,500,180,180],(250,4))
    rows[:,4:4+classes] = rng.uniform(0,.1,(250,classes))
    rows[:candidates,4+class_id] = rng.uniform(.3,.9,candidates)
    points = rows[:,4+classes:].reshape(-1,keypoints,3)
    points[:,:,:2] = rng.uniform([100,100],[700,600],(250,keypoints,2))
    points[:,:,2] = .9
    # Ties, exactly-at-threshold scores, invalid boxes, missing keypoints,
    # and NaN/Inf values must retain the same original-decoder behavior.
    rows[1:3,4+class_id] = .6
    rows[3,4+class_id] = .3
    rows[4,4+class_id] = np.nan
    rows[5,4+class_id] = np.inf
    rows[6,2] = -1
    points[7,0,2] = .1
    points[8,1,0] = np.nan
    points[9,2,1] = np.inf
    output = rows if layout == 'rows' else rows.T
    if layout == 'batch':
        output = output[None]
    kwargs = dict(frame_size=(1920,1080), input_size=960,scale=.5,pad_x=0,pad_y=210,
                  num_classes=classes,class_id=class_id,keypoint_count=keypoints,
                  confidence_threshold=.3,keypoint_threshold=.35,nms_iou_threshold=.45)
    filtered = prefilter_class_scores(output,**kwargs)
    assert_same(decode_yolo_pose_output(output,**kwargs),decode_yolo_pose_output(filtered,**kwargs))


def test_low_score_zero_candidates_and_invalid_layout_keep_validation():
    raw = np.zeros((1,17,18900),np.float32)
    filtered = prefilter_class_scores(raw)
    assert filtered.shape == (17,0)
    malformed = np.zeros((2,17,100),np.float32)
    assert prefilter_class_scores(malformed) is malformed


def test_cuda_locator_filter_is_eye_opt_in(monkeypatch):
    from app.vision import cuda_pose
    locator = cuda_pose.CudaYoloPoseLocator.__new__(cuda_pose.CudaYoloPoseLocator)
    locator._fallback = None
    locator._session = object()
    locator._preprocessor = object()
    locator._decode_options = dict(input_size=960,confidence_threshold=.45,keypoint_threshold=.35,
                                   nms_iou_threshold=.45,num_classes=1,class_id=0,keypoint_count=4)
    locator.inference_count = 0
    locator.inference_ms = 0.
    raw = np.zeros((1,17,18900),np.float32)
    locator._run_preprocessed = lambda frame: (raw,1.,0.,0.)
    shapes = []
    monkeypatch.setattr(cuda_pose,'decode_yolo_pose_output',lambda output,**kwargs: shapes.append(output.shape))
    frame = np.zeros((100,100,3),np.uint8)
    for enabled in [False,True,False]:
        locator.set_yolo_only(enabled)
        locator.locate(frame)
    assert shapes == [(1,17,18900),(17,0),(1,17,18900)]


def test_board_configures_both_existing_locators_on_eye_entry_and_exit():
    from pathlib import Path
    from types import SimpleNamespace
    from app.profiles.store import ProfileStore
    from app.vision.yolo_profile_detector import YoloProfileDetector
    states = [[],[]]
    primary = SimpleNamespace(available=True,set_yolo_only=states[0].append)
    reference = SimpleNamespace(available=True,set_yolo_only=states[1].append)
    detector = YoloProfileDetector(locator=primary)
    root = Path(__file__).resolve().parents[2]
    detector.load(ProfileStore(root/'profiles').profile('raspberry-pi-5'), root/'profiles/boards/raspberry-pi-5')
    detector._reference_recovery = SimpleNamespace(roi_locator=reference,set_scale_recovery=lambda enabled:None)
    detector.set_yolo_only(True)
    detector.set_yolo_only(False)
    assert states == [[True,False],[True,False]]
