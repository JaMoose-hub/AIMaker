from __future__ import annotations

import base64
from types import SimpleNamespace

import cv2
import numpy as np

from app.verification.visual_worker import (
    InsertionVlmWorker,
    _full_frame_image,
    _insertion_views_image,
    insertion_evidence,
)
from app.verification.final_worker import FinalWiringVlmWorker
from app.verification.state import VerificationState
from app.vlm.models import InsertionUnderstanding


def _result(board_state="inserted_target", component_state="inserted_target", same="likely"):
    return InsertionUnderstanding.model_validate({
        "schema_version": "1.0",
        "authority": "visual_advisory",
        "board_endpoint": {
            "state": board_state,
            "confidence": 0.94,
            "evidence": "board evidence",
        },
        "component_endpoint": {
            "state": component_state,
            "confidence": 0.91,
            "evidence": "component evidence",
        },
        "same_wire": same,
        "same_wire_confidence": 0.86,
        "note": "",
    })


def test_two_target_insertions_become_visual_pass_but_are_reliability_capped():
    item = insertion_evidence(_result(), now_ms=1000.0)
    assert item.status == "pass"
    assert item.score == 0.86
    assert item.method == "vlm_insertion"
    assert item.fresh_until_ms == 0.0


def test_adjacent_pin_is_not_a_vlm_pass_when_geometry_is_skipped():
    item = insertion_evidence(
        _result(board_state="inserted_adjacent"), now_ms=1000.0
    )
    assert item.status == "fail"
    assert item.score == 0.86
    assert item.reason == "vlm_adjacent_pin"


def test_empty_connector_remains_a_failure_even_if_other_endpoint_looks_adjacent():
    item = insertion_evidence(
        _result(board_state="inserted_adjacent", component_state="empty"),
        now_ms=1000.0,
    )
    assert item.status == "fail"
    assert item.reason == "vlm_connector_missing"


def test_occlusion_abstains_instead_of_guessing():
    item = insertion_evidence(
        _result(component_state="occluded", same="uncertain"), now_ms=1000.0
    )
    assert item.status == "uncertain"
    assert item.reason == "vlm_occluded"


def test_full_frame_image_preserves_complete_camera_frame():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    encoded = _full_frame_image(frame)
    image = cv2.imdecode(
        np.frombuffer(base64.b64decode(encoded), dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert image is not None
    assert image.shape[:2] == (720, 1280)


def test_insertion_vlm_falls_back_to_a_raw_snapshot_without_pose_lock():
    worker = InsertionVlmWorker(object(), VerificationState(), "arduino-uno-q")
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    step = SimpleNamespace(
        step_id="photoresistor-vcc",
        expected_pin_id="3V3",
        expected_role="VCC",
        component_id="photoresistor-module",
    )

    assert worker.submit(step, frame, None, None) is True
    image = cv2.imdecode(
        np.frombuffer(worker.preview_jpeg() or b"", dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert image is not None
    assert image.shape[:2] == (720, 1280)
    assert worker.diagnostics()["last_outcome"]["capture_mode"] == "full_frame"


def test_final_vlm_falls_back_to_a_raw_snapshot_without_pose_lock():
    worker = FinalWiringVlmWorker(object(), "arduino-uno-q")
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    assert worker.submit(frame, None, None, step_id="photoresistor-ao") is True
    image = cv2.imdecode(
        np.frombuffer(worker.preview_jpeg() or b"", dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert image is not None
    assert image.shape[:2] == (720, 1280)
    assert worker.diagnostics()["last_outcome"]["capture_mode"] == "full_frame"


def test_insertion_views_include_full_context_and_dynamic_detail_panels():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    encoded = _insertion_views_image(
        frame,
        (240.0, 360.0),
        (1000.0, 360.0),
        np.array([[180.0, 300.0], [300.0, 300.0], [300.0, 430.0], [180.0, 430.0]]),
        np.array([[960.0, 280.0], [1040.0, 280.0], [1040.0, 440.0], [960.0, 440.0]]),
        "3V3",
        "VCC",
    )
    image = cv2.imdecode(
        np.frombuffer(base64.b64decode(encoded), dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert image is not None
    assert image.shape[:2] == (360, 1956)
