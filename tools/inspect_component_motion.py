"""Read-only same-image model/geometry/feature diagnostics for a component."""
import argparse
import json
from pathlib import Path
import sys

import cv2
import httpx
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.component_worker import (
    ComponentVisionProfile, orient_component_corners_from_pin_row,
    refine_component_corners_from_pcb, refine_component_corners_from_mounting_holes,
    project_component_outline, project_component_pins,
)
from app.motion_worker import tracking_gray
from app.vision.yolo_pose import create_yolo_pose_locator
from app.vision.motion_tracking import PlanarFlow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('component_id')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    image_path = args.out / 'source.jpg'
    if not image_path.exists():
        response = httpx.get('http://127.0.0.1:8100/frame.jpg', timeout=5)
        response.raise_for_status()
        image_path.write_bytes(response.content)
    image = cv2.imread(str(image_path))
    config = yaml.safe_load((ROOT / 'backend/config.yaml').read_text(encoding='utf-8'))['component_vision']
    item = next(c for c in config['components'] if c['id'] == args.component_id)
    profile = ComponentVisionProfile.load(ROOT / 'backend' / item['profile_path'])
    locator = create_yolo_pose_locator(
        ROOT / 'backend' / item['model_path'], runtime_backend=config['runtime_backend'],
        input_size=item['input_size'], confidence_threshold=item['confidence_threshold'],
        keypoint_threshold=item['keypoint_threshold'], keypoint_count=profile.keypoint_count,
    )
    observation = locator.locate(image)
    report = {'component': args.component_id, 'detected': observation is not None}
    if observation is not None:
        report.update(raw_corners=observation.corners_px.tolist(), confidence=float(observation.confidence))
        if profile.corner_refinement == 'blue_pcb':
            observation = refine_component_corners_from_pcb(image, observation) or observation
        elif profile.corner_refinement == 'mounting_holes':
            observation = refine_component_corners_from_mounting_holes(image, observation) or observation
        report['refined_corners'] = observation.corners_px.tolist()
        # Save all candidate row locations for diagnosis; do not call them valid.
        annotated = image.copy()
        for shift in range(4) if profile.pin_row_orientation else [0]:
            pins = project_component_pins(profile, np.roll(observation.corners_px, shift, axis=0), .5,
                                          (image.shape[1], image.shape[0]))
            for p in pins:
                cv2.circle(annotated, (round(p.x), round(p.y)), 3, [(0,0,255),(0,255,0),(255,0,0),(0,255,255)][shift], 1)
        cv2.imwrite(str(args.out / 'candidate-rows.jpg'), annotated)
        if profile.pin_row_orientation:
            observation = orient_component_corners_from_pin_row(image, observation, profile)
        report['orientation_verified'] = observation is not None
        if observation is not None:
            gray, scale = tracking_gray(image)
            quad = project_component_outline(profile, observation.corners_px)
            flow = PlanarFlow()
            report['flow_can_seed'] = flow.seed(gray, np.float32(quad) * scale)
            report['feature_count'] = len(flow.points) if flow.points is not None else 0
            report['verified_corners'] = observation.corners_px.tolist()
    locator.close()
    (args.out / 'inspection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
