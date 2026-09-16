from types import SimpleNamespace

import numpy as np
import pytest

from app.vision import pose_tracker as module


@pytest.mark.parametrize('shape,cap,expected', [((1080,1920),960,(540,960)),
    ((1920,1080),960,(960,540)), ((400,600),960,(400,600)), ((1080,1920),0,(1080,1920))])
def test_resize_maps_matches_back_before_geometry(monkeypatch, shape, cap, expected):
    tracker = module.PoseTracker.__new__(module.PoseTracker)
    tracker.params = module.TrackerParams(sift_frame_max_px=cap)
    observed = []
    def extract(image, mask):
        observed.append(image.shape)
        return [SimpleNamespace(pt=(10.,20.))]*25, np.zeros((25,128),np.float32)
    tracker._sift = SimpleNamespace(detectAndCompute=extract)
    tracker._sift_ref = (np.zeros((25,2)), np.zeros((25,128),np.float32))
    monkeypatch.setattr(module, '_unique_lowe_matches',
        lambda *a: (np.zeros((25,2)), np.tile([10.,20.], (25,1))))
    mm, xy = tracker._match_features_sift(np.zeros(shape,np.uint8), (100,50))
    assert observed == [expected]
    scale = min(1.,cap/max(shape)) if cap else 1.
    np.testing.assert_allclose(xy, np.tile(np.array([10.,20.])/scale+[100,50],(25,1)))
    assert tracker.params.min_inliers == 25
    assert tracker.params.max_reproj_px == 3.


def test_empty_image_features_do_not_create_a_pose():
    tracker = module.PoseTracker.__new__(module.PoseTracker)
    tracker.params = module.TrackerParams(sift_frame_max_px=960)
    tracker._sift = SimpleNamespace(detectAndCompute=lambda *a:([],None))
    tracker._sift_ref = (np.zeros((25,2)), np.zeros((25,128),np.float32))
    assert tracker._match_features_sift(np.zeros((1080,1920),np.uint8),(0,0)) is None
