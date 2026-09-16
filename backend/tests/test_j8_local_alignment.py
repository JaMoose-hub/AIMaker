import cv2
import numpy as np

from app.vision.pin_regions import PinRegions


def fixture():
    gray = np.random.default_rng(67).integers(25, 225, (240, 480), dtype=np.uint8)
    pins = [{'id': str(i), 'x': 60.+(i//2)*18, 'y': 100.+(i%2)*18, 'v': True}
            for i in range(40)]
    quad = np.float32([[25, 25], [450, 25], [450, 210], [25, 210]])
    return gray, pins, quad


def move(gray, dx):
    return cv2.warpAffine(gray, np.float32([[1, 0, dx], [0, 1, 0]]),
                          (gray.shape[1], gray.shape[0]))


def test_common_small_shift_restores_pins_at_measured_location():
    gray, pins, quad = fixture()
    old = PinRegions(gray, quad, pins, 1)
    new = PinRegions(gray, quad, pins, 1, align_header=True)
    current = move(gray, 2)
    assert sum(p['supported'] for p in old.check(current, quad, 1).values()) == 0
    assert all(p['supported'] for p in new.check(current, quad, 1).values())
    np.testing.assert_allclose(new.offset_px, [2, 0])
    # Always compare against the clean source, never integrate or learn drift.
    for _ in range(5):
        new.check(current, quad, 1)
        np.testing.assert_allclose(new.offset_px, [2, 0])
    new.check(gray, quad, 1)
    np.testing.assert_allclose(new.offset_px, [0, 0])


def test_local_alignment_does_not_reveal_covered_contacts():
    gray, pins, quad = fixture()
    new = PinRegions(gray, quad, pins, 1, align_header=True)
    current = move(gray, 2)
    current[85:135, 195:285] = 100
    report = new.check(current, quad, 1)
    assert sum(p['supported'] for p in report.values()) >= 24
    assert not report['20']['supported']
    np.testing.assert_allclose(new.offset_px, [2, 0])


def test_large_shift_full_occlusion_and_small_visible_patch_fail_closed():
    gray, pins, quad = fixture()
    new = PinRegions(gray, quad, pins, 1, align_header=True)
    for current in (move(gray, 18), np.full_like(gray, 100)):
        assert not any(p['supported'] for p in new.check(current, quad, 1).values())
        np.testing.assert_allclose(new.offset_px, [0, 0])
    current = np.full_like(gray, 100)
    shifted = move(gray, 2)
    current[85:135, 45:160] = shifted[85:135, 45:160]
    assert not any(p['supported'] for p in new.check(current, quad, 1).values())
    np.testing.assert_allclose(new.offset_px, [0, 0])


def test_nearby_pin_spacing_limits_search_and_default_stays_legacy():
    gray, pins, quad = fixture()
    pins = [dict(p, x=100.+(i//2)*6, y=100.+(i%2)*6) for i,p in enumerate(pins)]
    new = PinRegions(gray, quad, pins, 1, align_header=True)
    assert not any(p['supported'] for p in new.check(move(gray, 2), quad, 1).values())
    assert not PinRegions(gray, quad, pins, 1).align_header


def test_output_moves_with_local_match_without_accumulating_offset(monkeypatch):
    from app.vision.motion_tracking import MotionTrack
    from test_motion_tracking import scene, pose
    gray, quad = scene()
    msg = pose(quad)
    track = MotionTrack()
    track.observe(msg, gray, 1)
    original = [(p['x'], p['y']) for p in msg['pins']]
    def supported(*args):
        track.pin_regions.offset_px = np.array([1.5, 0.])
        return {p['id']: {'supported': True} for p in msg['pins']}
    monkeypatch.setattr(track.pin_regions, 'check', supported)
    for i in range(1, 4):
        output = track.update(gray, i, i*33)
        np.testing.assert_allclose([(p['x'], p['y']) for p in output['pins']],
                                   np.array(original)+[1.5, 0], atol=.02)
    assert [(p['x'], p['y']) for p in msg['pins']] == original
