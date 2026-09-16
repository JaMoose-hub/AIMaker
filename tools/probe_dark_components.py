"""Read-only replay of saved component frames; no camera/runtime mutations."""
import sys
from pathlib import Path
import json
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.component_worker import (ComponentVisionProfile, ComponentPoseTracker,
    refine_component_corners_from_pcb, orient_component_corners_from_pin_row)
from app.vision.yolo_pose import create_yolo_pose_locator
from app.profiles.models import BoardProfile
from app.vision.factory import create_detector

def main():
    cases = [
        ('hc-sr04', 'hc-sr04-corner-pose-v3-robust.onnx', 768, .25, .20,
         'S02-HC-dark-center-quick-01/scene-after-sample.jpg'),
        ('hw-123', 'hw-123-pose.onnx', 960, .15, .15, 'hw-dark-placement-check.jpg'),
        ('hw-123', 'hw-123-pose.onnx', 960, .15, .15,
         'S02-HW-dark-after-fix-diagnostic-01/scene-after-sample.jpg'),
        ('hw-123', 'hw-123-pose.onnx', 960, .15, .15,
         'S02-HW-boundary-fix-live-01/scene-after-sample.jpg'),
    ]
    for name, model, size, conf, keypoint, filename in cases:
        profile = ComponentVisionProfile.load(ROOT / f'profiles/components/{name}/vision_profile.json')
        locator = create_yolo_pose_locator(ROOT / 'models' / model, runtime_backend='cuda',
            input_size=size, confidence_threshold=conf, keypoint_threshold=keypoint)
        frame = cv2.imread(str(ROOT / 'runs/acceptance/2026-09-11' / filename))
        raw = locator.locate(frame)
        report = {'component': name, 'raw_found': raw is not None}
        if raw is not None:
            refined = refine_component_corners_from_pcb(frame, raw,
                orientation_keypoint_indices=profile.orientation_keypoint_indices) or raw
            corners = refined.corners_px
            report.update(confidence=raw.confidence, box=raw.box_xyxy, raw_corners=raw.corners_px.tolist(), corners=corners.tolist(),
                hand_fraction=ComponentPoseTracker._hand_fraction(frame, corners))
            if profile.pin_row_orientation:
                oriented = orient_component_corners_from_pin_row(frame, refined, profile)
                report['orientation_verified'] = oriented is not None
        print(json.dumps(report))
        locator.close()
    profile_dir = ROOT / 'profiles/boards/raspberry-pi-5'
    profile = BoardProfile.model_validate_json((profile_dir / 'board.json').read_text(encoding='utf-8'))
    detector = create_detector('pipeline', profile, profile_dir, horizontal_fov_deg=70.42,
                               camera_calibration_path=ROOT / 'calibration/c920-1080p.json')
    frame = cv2.imread(str(ROOT / 'runs/acceptance/2026-09-11/S02-Pi-dark-center-quick-01/scene-after-sample.jpg'))
    counts = {}
    invalid = 0
    for i in range(30):
        result = detector.detect(frame, i, i*100.)
        counts[result.tracking] = counts.get(result.tracking, 0) + 1
        if result.tracking == 'locked' and result.outline_px is not None:
            quad = np.asarray(result.outline_px)
            invalid += int((quad < 0).any() or (quad >= [frame.shape[1], frame.shape[0]]).any())
    print(json.dumps({'component': 'pi-feature-fallback', 'repeated_static_frames': counts,
                      'out_of_frame_locks': invalid}))
    detector.close()

if __name__ == '__main__':
    main()
