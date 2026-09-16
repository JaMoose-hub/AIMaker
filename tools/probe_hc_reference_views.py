"""Offline diagnostic: reference descriptor views, unchanged match/geometry gates."""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.yolo_pose import BoardPoseObservation


def views():
    path = ROOT / 'profiles/components/hc-sr04/vision_profile.json'
    spec = json.loads(path.read_text(encoding='utf-8'))['reference_pose']
    source = np.float32(spec['corners_px'])
    image = cv2.imread(str(path.parent / spec['image']))
    w, h = spec['rectified_size']
    canonical = np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]])
    rectified = cv2.warpPerspective(image, cv2.getPerspectiveTransform(source, canonical), (w, h))
    blue = cv2.inRange(cv2.cvtColor(rectified, cv2.COLOR_BGR2HSV),
                       np.uint8([75,35,12]), np.uint8([145,255,255]))
    base = ReferencePoseRecovery(rectified, feature_mask=cv2.dilate(blue,np.ones((3,3),np.uint8)))
    result = [('rectified', base)]
    # Preserve native capture descriptors, but store feature coordinates in
    # canonical PCB space. All candidate geometries use the same coordinates.
    x, y, rw, rh = cv2.boundingRect(source)
    native = image[y:y+rh, x:x+rw]
    polygon = np.zeros(native.shape[:2], np.uint8)
    cv2.fillConvexPoly(polygon, np.int32(source-[x, y]), 255)
    native_to_canonical = cv2.getPerspectiveTransform(np.float32(source-[x, y]), canonical)
    candidates = [('native', native, native_to_canonical, polygon)]
    for sx, sy in [(1., .65), (.65, 1.), (1., 1.4), (1.4, 1.)]:
        warped = cv2.resize(base.reference, None, fx=sx, fy=sy)
        actual_x, actual_y = warped.shape[1]/w, warped.shape[0]/h
        candidates.append((f'scale_{sx}_{sy}', warped,
                           np.diag([1/actual_x, 1/actual_y, 1.]), None))
    for name, frame, to_canonical, polygon in candidates:
        blue = cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV),
                           np.uint8([75, 35, 12]), np.uint8([145, 255, 255]))
        mask = cv2.dilate(blue, np.ones((3, 3), np.uint8))
        if polygon is not None:
            mask &= polygon
        candidate = ReferencePoseRecovery(frame, feature_mask=mask)
        points = np.float32([k.pt for k in candidate.keypoints])
        canonical_points = cv2.perspectiveTransform(points[None], to_canonical)[0]
        candidate.keypoints = [cv2.KeyPoint(float(p[0]), float(p[1]), k.size)
                               for p, k in zip(canonical_points, candidate.keypoints)]
        candidate.reference = base.reference
        result.append((name, candidate))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    candidates = views()
    raw = json.loads((args.folder/'raw-observations.json').read_text())
    rows = [json.loads(line) for line in (args.folder/'model/frames.jsonl').read_text().splitlines()]
    results = []
    for row in rows:
        data = raw[str(row['frame_id'])]
        if data is None:
            continue
        region = BoardPoseObservation(np.array(data['corners']), data['confidence'],
                                      np.array(data['keypoints']), tuple(data['box']))
        frame = cv2.imread(str(args.folder/'model'/row['image_path']))
        matches = {}
        for name, recovery in candidates:
            found = recovery.locate(frame, region)
            matches[name] = {'corners': None if found is None else found.corners_px.tolist(),
                             'evidence': dict(recovery.evidence)}
        results.append({'frame_id': row['frame_id'], 'views': matches})
    args.out.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print({name: sum(r['views'][name]['corners'] is not None for r in results) for name, _ in candidates})
    print({'any_view': sum(any(v['corners'] is not None for v in r['views'].values()) for r in results),
           'frames': len(results)})


if __name__ == '__main__':
    main()
