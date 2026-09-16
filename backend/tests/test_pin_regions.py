"""Fixed deterministic occlusion replay, NOT physical wiring acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import cv2
import numpy as np
import pytest

from app.vision.motion_tracking import MotionTrack, transform
from app.vision.pin_regions import PinRegions
from test_motion_tracking import scene, pose


def two_pins(quad, device):
    msg = pose(quad)
    msg['pins'] = [{'id': 'left', 'x': 145., 'y': 125., 'v': True},
                   {'id': 'right', 'x': 310., 'y': 205., 'v': True}]
    if device != 'raspberry-pi-5':
        msg.pop('board_id')
        msg['component_id'] = device
    return msg


@pytest.mark.parametrize('device', ['raspberry-pi-5', 'hc-sr04', 'hw-123', 'mrd-tf240-8p-cs'])
@pytest.mark.parametrize('fraction', [.25, .4, .55])
def test_partial_hand_keeps_current_supported_pin_and_restores_hidden_pin(device, fraction):
    clear, quad = scene()
    covered = clear.copy()
    end = 120 + round(240*fraction)
    covered[100:260, 120:end] = np.random.default_rng(357).integers(15, 245, (160, end-120), dtype=np.uint8)
    message = two_pins(quad, device)
    original = deepcopy(message)
    track = MotionTrack()
    track.observe(message, clear, 1)
    reference = track.pin_regions
    for i in range(1, 21):
        matrix = np.float64([[1, 0, i], [0, 1, i*.3], [0, 0, 1]])
        current = cv2.warpPerspective(covered, matrix, (640, 400), borderValue=40)
        result = track.update(current, i, i*33)
        assert result is not None and result['tracking'] == 'locked'
        assert [p['id'] for p in result['pins']] == ['right']
        assert result['pose_quality']['partial'] and not result['pose_quality']['outline_only']
        assert result['pose_quality']['object_supported']
        assert result['pose_quality']['hidden_pin_count'] == 1
        assert track.pin_regions is reference, 'never learn the obstruction from flow refresh'
        expected = transform([[310, 205]], matrix)[0]
        actual = np.array([result['pins'][0]['x'], result['pins'][0]['y']])
        assert np.linalg.norm(actual-expected) < 1.5
    restored = track.update(cv2.warpPerspective(clear, matrix, (640,400), borderValue=40), 21, 693)
    assert [p['id'] for p in restored['pins']] == ['left', 'right']
    assert message == original


def test_local_changes_hide_pin_even_when_global_flow_is_not_partial():
    clear, quad = scene()
    msg = two_pins(quad, 'raspberry-pi-5')
    track = MotionTrack()
    track.observe(msg, clear, 1)
    covered = clear.copy()
    covered[116:135, 136:155] = 100
    output = track.update(covered, 1, 33)
    assert output and [p['id'] for p in output['pins']] == ['right']
    assert output['pose_quality']['hidden_pin_count'] == 1
    # Flow refresh must not replace the independent local appearance reference.
    reference = track.pin_regions
    for i in range(2, 20):
        output = track.update(covered, i, i*33)
        assert [p['id'] for p in output['pins']] == ['right']
        assert track.pin_regions is reference


def test_textureless_and_out_of_frame_regions_are_not_declared_supported():
    gray, quad = scene()
    pins = [{'id': 'blank', 'x': 50., 'y': 50.}, {'id': 'edge', 'x': 2., 'y': 2.}]
    region = PinRegions(gray, quad, pins, 1)
    reports = region.check(gray, quad, 1)
    assert reports['blank']['reason'] == 'low_texture'
    assert reports['edge']['reason'] == 'outside_frame'
    assert not any(r['supported'] for r in reports.values())


def test_semantic_expiry_still_suppresses_all_pins_despite_local_matches():
    gray, quad = scene()
    track = MotionTrack(lease_ms=100, outline_lease_ms=400)
    track.observe(two_pins(quad, 'raspberry-pi-5'), gray, 1)
    output = track.update(gray, 1, 150)
    assert output['pins'] == [] and output['pose_quality']['object_supported']
    assert output['pose_quality']['reason'] == 'awaiting_model_confirmation'
    assert track.update(gray, 2, 500) is None
    assert track.pin_regions is None


def test_total_occlusion_returns_no_old_coordinates():
    gray, quad = scene()
    track = MotionTrack()
    track.observe(two_pins(quad, 'hc-sr04'), gray, 1)
    assert track.update(np.full_like(gray, 95), 1, 33) is None


@pytest.mark.parametrize('device', ['hc-sr04', 'hw-123', 'mrd-tf240-8p-cs'])
def test_component_reference_refresh_requires_material_hand_and_three_frames(device):
    gray, quad = scene()
    track = MotionTrack()
    msg = two_pins(quad, device)
    track.observe(msg, gray, 1)
    changed = gray.copy()
    changed[116:135, 136:155] = 100
    track.update(changed, 1, 33)
    assert track.message['pose_quality']['hidden_pin_count'] == 1
    ref = track.pin_regions
    for i in range(1, 4):
        current = deepcopy(msg)
        current.update(frame_id=i, ts_ms=i*33)
        current['pose_quality'] = {'stability': 'deadband', 'hand_fraction': 0,
                                  'visible_fraction': .7, 'visibility_baseline': .75}
        bad = deepcopy(current)
        bad['pose_quality']['hand_fraction'] = .2
        assert not track.needs_source_image(bad)
        assert track.needs_source_image(current)
        track.observe(current, changed, 1)
        track.update(changed, i+1, (i+1)*33)
        if i < 3:
            assert track.pin_regions is ref
    assert track.rebase_count == 1 and track.pin_regions is not ref


@pytest.mark.parametrize('device,min_coverage', [('raspberry-pi-5', .98), ('hc-sr04', 1.)])
def test_recorded_texture_clear_transform_retention(device, min_coverage):
    # Separate from true pin-location accuracy: only checks that the region
    # matcher does not reject most pins under known image transforms.
    from app.motion_worker import tracking_gray
    root = Path(__file__).resolve().parents[2] / 'runs/diagnostics/component-recovery-20260909-restart2'
    if not (root / f'{device}-source.jpg').exists():
        pytest.skip('Optional recorded camera fixture is not installed')
    image = cv2.imread(str(root / f'{device}-source.jpg'))
    message = json.loads((root / f'{device}-pose.json').read_text())
    message.update(frame_id=0, ts_ms=0)
    gray, scale = tracking_gray(image)
    track = MotionTrack()
    track.observe(message, gray, scale)
    centre = np.asarray(message['outline'], np.float32).mean(0)
    visible = 0
    for i in range(1,21):
        matrix = cv2.getRotationMatrix2D(tuple(centre), i*.6, 1+i*.002)
        matrix[:, 2] += [i*2, -i]
        frame, _ = tracking_gray(cv2.warpAffine(image, matrix, (image.shape[1],image.shape[0])))
        result = track.update(frame, i, i*33)
        assert result is not None
        visible += len(result['pins'])
    assert visible / (20*len(message['pins'])) >= min_coverage
