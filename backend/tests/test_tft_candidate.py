from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.capture.bus import FrameBus
from app.component_worker import ComponentPoseState, ComponentPoseWorker
from app.vision import cuda_pose, yolo_pose
from test_cuda_pose import fake_ort
from test_tft_ring_geometry import panel
from test_motion_consensus import observation


ROOT=Path(__file__).resolve().parents[2]


def worker(component='mrd-tf240-8p-cs'):
    locator=SimpleNamespace(locate=lambda frame: None, locate_candidate=lambda frame, threshold: None)
    return ComponentPoseWorker(bus=FrameBus(),state=ComponentPoseState(),publish=lambda _:None,
        model_path='unused',profile_path=ROOT/f'profiles/components/{component}/vision_profile.json',
        locator=locator,webcam_motion_handoff=True,confidence_threshold=.2)


def test_weak_model_pose_never_falls_back_to_raw_geometry():
    w=worker();frame,quad=panel(missing=True)
    result,evidence=w._refine_tft_candidate(frame,replace(observation(quad),confidence=.1),1,100)
    assert result is None
    assert evidence['fallback']=='unverified_candidate_rejected'


def test_strong_current_model_retains_existing_partial_ring_fallback():
    w=worker();frame,quad=panel(missing=True)
    result,evidence=w._refine_tft_candidate(frame,observation(quad),1,100)
    assert result is not None
    assert evidence['fallback']=='current_model_pose_requires_consensus'


def test_weak_pose_requires_four_holes_and_panel_then_reset_clears_recovery():
    w=worker();frame,quad=panel()
    result,evidence=w._refine_tft_candidate(frame,replace(observation(quad),confidence=.1),1,100)
    assert result is not None and evidence['screen_supported']
    assert result.confidence==.1  # Do not inflate model confidence.
    w.reset_tracking()
    assert w._refine_tft_candidate(frame,None,2,200)[0] is None


@pytest.mark.parametrize('component',['hc-sr04','hw-123','mrd-tf240-8p-cs'])
def test_candidate_calls_are_webcam_tft_only(component):
    w=worker(component);calls=[]
    w._locator.locate=lambda frame: calls.append('normal')
    w._locator.locate_candidate=lambda frame, threshold: calls.append(threshold)
    frame=np.zeros((100,200,3),np.uint8)
    w._locate(frame)
    assert calls==([.08] if component=='mrd-tf240-8p-cs' else ['normal'])
    calls.clear()
    w.set_yolo_only(True)
    w._locate(frame)
    assert .08 not in calls
    w.set_yolo_only(False)
    assert w._tft_rings._last is None


def test_cuda_candidate_is_one_forward_without_mutating_default_gate(monkeypatch):
    calls=fake_ort(monkeypatch)
    thresholds=[]
    monkeypatch.setattr(cuda_pose,'decode_yolo_pose_output',lambda *a,**kw: thresholds.append(kw['confidence_threshold']))
    locator=cuda_pose.CudaYoloPoseLocator('test.onnx',input_size=320,confidence_threshold=.2)
    frame=np.zeros((240,320,3),np.uint8)
    locator.locate_candidate(frame,.08)
    locator.locate(frame)
    assert thresholds==[.08,.2]
    assert calls['runs']==3  # Warmup + exactly one per call.
    assert locator._decode_options['confidence_threshold']==.2


def test_opencv_candidate_is_one_forward_without_mutating_default_gate(monkeypatch):
    calls=[];thresholds=[]
    net=SimpleNamespace(setInput=lambda _:None,forward=lambda: calls.append('forward'))
    monkeypatch.setattr(yolo_pose.cv2.dnn,'readNetFromONNX',lambda _:net)
    monkeypatch.setattr(yolo_pose,'decode_yolo_pose_output',lambda *a,**kw: thresholds.append(kw['confidence_threshold']))
    locator=yolo_pose.OpenCvYoloPoseLocator('test.onnx',input_size=320,confidence_threshold=.2)
    locator._net=net
    frame=np.zeros((240,320,3),np.uint8)
    locator.locate_candidate(frame,.08);locator.locate(frame)
    assert calls==['forward','forward'] and thresholds==[.08,.2]
    assert locator.confidence_threshold==.2
