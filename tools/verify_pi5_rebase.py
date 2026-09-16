"""Offline aged-display-template replay on a captured, paired Pi image/pose.

No live API/settings/hardware writes. Models are NOT rerun: the recorded pose
is a semantic fixture; the independent J8 image check actually runs each frame.
We explicitly seed that independent anchor more recently than the display
anchor to reproduce their differing ages. This is not physical occlusion proof.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.motion_worker import tracking_gray
from app.profiles.store import ProfileStore
from app.vision.interface import PinDetection
from app.vision.motion_tracking import MotionTrack
from app.vision.pi5_pin_stability import PinImageAnchor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    image = cv2.imread(str(args.fixture / 'raspberry-pi-5-source.jpg'))
    message = json.loads((args.fixture / 'raspberry-pi-5-pose.json').read_text(encoding='utf-8'))
    assert image is not None and message['tracking'] == 'locked'
    assert message['board_id'] == 'raspberry-pi-5' and len(message['pins']) == 40
    profile, _ = ProfileStore(ROOT / 'profiles').load('raspberry-pi-5')
    metadata = {p.id: p for p in profile.pins}
    pins = [PinDetection(p['id'], p['x'], p['y'], p['c'], p['v'],
                         metadata[p['id']].header, metadata[p['id']].index)
            for p in message['pins']]
    original_gray, scale = tracking_gray(image)
    changed = cv2.GaussianBlur(image, (11, 11), 0)
    changed_gray, _ = tracking_gray(changed)
    anchor = PinImageAnchor()
    # Explicitly model a newer, independently acquired clear J8 anchor.
    anchor.seed(changed, pins, message['outline'])

    def pose(i, evidence=False):
        result = deepcopy(message)
        result.update(frame_id=i, ts_ms=i * 33)
        result['pose_quality'] = {'image_confirmed': True} if evidence else {}
        return result

    tracks = {name: MotionTrack() for name in ('control_no_image_evidence', 'guarded_rebase')}
    samples = []
    for track in tracks.values():
        track.observe(pose(0), original_gray, scale)
        output = track.update(changed_gray, 1, 33)
        assert output['tracking'] == 'stale' and not output['pins']
    initial_support = tracks['guarded_rebase'].flow.support_ratio
    for i in range(1, 13):
        stationary = anchor.stationary(changed)
        assert stationary and anchor.fully_supported
        for name, track in tracks.items():
            track.observe(pose(i, name == 'guarded_rebase' and anchor.fully_supported), changed_gray, scale)
            output = track.update(changed_gray, i + 1, (i + 1) * 33)
            samples.append({'frame_id': i + 1, 'path': name, 'tracking': output['tracking'],
                            'pins': len(output['pins']), 'support_ratio': track.flow.support_ratio,
                            'rebase_count': track.rebase_count, 'j8_support': anchor.support})
    control, recovered = tracks.values()
    assert control.rebase_count == 0 and control.flow.partial
    assert recovered.rebase_count == 1 and not recovered.flow.partial
    assert samples[-1]['pins'] == 40

    # A persistent opaque region is deliberately synthetic, not a detected hand.
    covered = changed.copy()
    cv2.fillConvexPoly(covered, np.asarray(message['outline'], np.int32), (90, 90, 90))
    covered_gray, _ = tracking_gray(covered)
    hidden_frames = 0
    for i in range(13, 33):
        anchor.stationary(covered)
        assert not anchor.fully_supported
        output = recovered.update(covered_gray, i + 1, (i + 1) * 33)
        # Even repeated semantic locks may not authorize a refresh by themselves.
        recovered.observe(pose(i + 1), covered_gray, scale)
        assert output is None or not output['pins']
        assert recovered.rebase_count == 1
        hidden_frames += 1
    report = {
        'fixture': str(args.fixture.resolve()), 'initial_display_support': initial_support,
        'frames': samples, 'rebase_count': recovered.rebase_count,
        'control_rebase_count': control.rebase_count, 'covered_frames_without_pins': hidden_frames,
        'limitations': 'Recorded image with synthetic blur/occlusion; semantic pose replayed, not a fresh model result. Independent J8 anchor deliberately seeded on newer clear texture. Not physical motion, occlusion or absolute pin accuracy validation.',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'frames'}, indent=2))


if __name__ == '__main__':
    main()
