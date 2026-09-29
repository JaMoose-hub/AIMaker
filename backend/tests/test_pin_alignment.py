from copy import deepcopy

import cv2
import numpy as np

from app.vision.interface import DetectionResult
from app.vision.pin_alignment import transport_pin_alignment
from app.vision.yolo_profile_detector import YoloProfileDetector
from app.vision_worker import detection_message


def alignment():
    return dict(version='pi5-contact-rows-v1', accepted=True,
                reference_center=[100., 80.], offset_px=[-18., 0.])


def test_manual_reference_rotates_and_scales_with_tracked_geometry():
    message = {'pin_alignment': alignment()}
    matrix = np.vstack([cv2.getRotationMatrix2D((100, 80), 37, 1.25), [0, 0, 1]])
    matrix[:2, 2] += [10., 7.]
    transport_pin_alignment(message, matrix)
    expected = matrix[:2, :2] @ [-18., 0.]
    np.testing.assert_allclose(message['pin_alignment']['offset_px'], expected)
    np.testing.assert_allclose(message['pin_alignment']['reference_center'], [110., 87.])


def test_rejected_or_absent_reference_is_not_invented():
    for message in ({}, {'pin_alignment': dict(accepted=False, offset_px=[0., 0.])}):
        before = deepcopy(message)
        transport_pin_alignment(message, np.eye(3))
        assert message == before


def test_held_result_and_wire_message_keep_geometry_provenance_without_aliasing():
    detector = YoloProfileDetector.__new__(YoloProfileDetector)
    detector._last_locked_result = DetectionResult(
        'raspberry-pi-5', 1, 10., 'locked', .9, pin_alignment=alignment())
    held = detector._frozen_result(frame_id=2, ts_ms=20., tracking='locked',
                                   confidence=.8, stability='deadband')
    assert held.pin_alignment == alignment()
    assert not held.pose_image_confirmed  # not fresh contact evidence
    message = detection_message(held, (640, 480))
    transport_pin_alignment(message, np.array([[2., 0, 0], [0, 2., 0], [0, 0, 1.]]))
    assert held.pin_alignment == alignment()
    assert message['pin_alignment']['offset_px'] == [-36., 0.]
