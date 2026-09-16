"""Offline regression on saved photos; never counts body boxes as GPIO success."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.profiles.store import ProfileStore
from app.component_worker import ComponentVisionProfile, project_component_pins
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.yolo_pose import create_yolo_pose_locator
from app.vision.yolo_profile_detector import YoloProfileDetector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    photo_root = ROOT/'runs/acceptance/2026-09-13'
    positives = [photo_root/name/'frames/000000.jpg' for name in (
        'S04-wired-body-before', 'S04-wired-body-after',
        'S04-wired-body-independent', 'S04-gpio-restore-before')]
    negatives = list(photo_root.glob('*-empty-placement-01.jpg'))
    for name in ('S02-gray-empty-01', 'S02-pattern-empty-01', 'S02-white-empty-01', 'S02-clutter-empty-01'):
        negatives.extend(sorted((photo_root/name/'frames').glob('*.jpg'))[::80][:3])
    board = ProfileStore(ROOT/'profiles/boards').profile('raspberry-pi-5')
    detector = YoloProfileDetector(model_path=ROOT/'models/board-pose-pi5-handheld-v2.onnx',
        reference_recovery_model_path=ROOT/'models/board-pose-pi5.onnx',
        runtime_backend='cuda', confidence_threshold=.30, max_reprojection_error_px=12)
    hw_profile_path = ROOT/'profiles/components/hw-123/vision_profile.json'
    hw = ComponentVisionProfile.load(hw_profile_path)
    recovery = ReferencePoseRecovery.from_component_profile(hw_profile_path)
    locator = create_yolo_pose_locator(ROOT/'models/hw-123-pose.onnx', runtime_backend='cuda',
        input_size=960, confidence_threshold=.3, keypoint_threshold=.25)
    rows = []
    try:
        for path in [*positives, *negatives]:
            if not path.exists():
                continue
            frame = cv2.imread(str(path))
            # Reset temporal history: every photograph must establish its own pose.
            detector.load(board, ROOT/'profiles/boards/raspberry-pi-5')
            result = detector.detect(frame, len(rows), time.time()*1000)
            observation = recovery.locate(frame, locator.locate(frame))
            pins = [] if observation is None else project_component_pins(hw, observation.corners_px,
                observation.confidence, (frame.shape[1], frame.shape[0]))
            rows.append({'file': str(path.relative_to(ROOT)), 'objects_present': path in positives,
                'pi': {'tracking': result.tracking, 'pins': len(result.pins),
                       'reference': result.reference_evidence, 'outline': result.outline_px},
                'hw': {'pins': len(pins), 'reference': dict(recovery.evidence)}})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'photos': len(rows), 'present': sum(r['objects_present'] for r in rows),
            'pi_positive_locks': sum(r['objects_present'] and r['pi']['pins'] == 40 for r in rows),
            'hw_positive_locks': sum(r['objects_present'] and r['hw']['pins'] == 8 for r in rows),
            'empty_false_pins': sum(not r['objects_present'] and bool(r['pi']['pins'] or r['hw']['pins']) for r in rows)}, indent=2))
    finally:
        detector.close()
        locator.close()


if __name__ == '__main__':
    main()
