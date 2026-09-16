"""Replay one saved source frame with orientation rejection diagnostics."""
import sys
from pathlib import Path
import cv2
import json
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.component_worker import ComponentVisionProfile, orient_component_corners_from_pin_row
from app.vision.yolo_pose import create_yolo_pose_locator
from app.vision.yolo_pose import BoardPoseObservation

def trace(frame, event, arg):
    if event == 'return' and frame.f_code.co_name in (
            '_recover_fragmented_hw_boundary', 'orient_component_corners_from_pin_row'):
        print(frame.f_code.co_name, frame.f_lineno, 'accepted', arg is not None,
              {key: str(frame.f_locals[key]) for key in
               ('candidates', 'holes', 'left', 'right', 'rect') if key in frame.f_locals})
    return trace

if __name__ == '__main__':
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    locator = create_yolo_pose_locator(ROOT / 'models/hw-123-pose.onnx', runtime_backend='cuda',
        input_size=960, confidence_threshold=.15, keypoint_threshold=.15)
    try:
        frame = cv2.imread(sys.argv[1])
        observation = locator.locate(frame)
        if len(sys.argv) > 2:
            packet = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
            data = packet.get('component_pose', packet.get('message'))['pose_quality']['orientation_input']
            observation = BoardPoseObservation(np.array(data['corners']), data['confidence'],
                np.array(data['keypoint_confidences']), tuple(data['box']))
        print(observation)
        if observation is not None:
            sys.settrace(trace)
            print(orient_component_corners_from_pin_row(frame, observation, profile))
    finally:
        sys.settrace(None)
        locator.close()
