import numpy as np
import pytest
from app.vision.image_pose_window import ImagePoseWindow
from test_motion_consensus import scene, shifted


def test_intermediate_frames_bridge_motion_but_do_not_count_as_model_votes():
    image, quad = scene()
    window = ImagePoseWindow()
    assert window.update(image, quad, 0, 0) is None
    result = None
    for i in range(1, 25):
        frame, corners = shifted(image, quad, i*8)
        if i % 8:
            before = len(window.samples)
            assert window.advance(frame, i, i*33)
            assert len(window.samples) == before
        else:
            result = window.update(frame, corners, i, i*33)
            if i < 24:
                assert result is None
    assert result is not None
    np.testing.assert_allclose(result, corners, atol=2)
    assert window.evidence['count'] == 4
    assert window.evidence['bridge_frames'] == 21


@pytest.mark.parametrize('bad', ['blank', 'duplicate', 'gap', 'resize'])
def test_intermediate_failure_discards_consensus(bad):
    frame, quad = scene()
    window = ImagePoseWindow()
    window.update(frame, quad, 1, 100)
    image, fid, ts = frame.copy(), 2, 133
    if bad == 'blank': image[:] = 50
    if bad == 'duplicate': fid, ts = 1, 100
    if bad == 'gap': ts = 700
    if bad == 'resize': image = image[:200,:200]
    assert not window.advance(image, fid, ts)
    assert not window.samples and window.flow is None
    assert window.update(frame, quad, 3, 800) is None


def test_intermediate_images_cannot_initialize_without_model():
    frame, _ = scene()
    window = ImagePoseWindow()
    assert not window.advance(frame, 1, 100)
    assert window.flow is None and not window.samples
