from types import SimpleNamespace

import numpy as np
import pytest

from app.vision.image_motion_gate import ImageMotionGate
from test_motion_consensus import scene, shifted


def pins(dx=0):
    return [SimpleNamespace(pin_id=str(i), x=160+i*20+dx, y=140.) for i in range(6)]


def test_four_distinct_moving_images_confirm_final_pin_motion():
    frame, quad = scene()
    gate = ImageMotionGate()
    for i in range(4):
        moved, corners = shifted(frame, quad, i*12)
        accepted = gate.compare(moved, corners, pins(i*12), i, i*125)
        assert accepted == (i==3)
    assert gate.evidence['pin_delta_px'] < .5
    np.testing.assert_allclose(gate.ready_outline,corners,atol=.5)
    np.testing.assert_allclose(gate.ready_pins,[[p.x,p.y] for p in pins(36)],atol=.5)


@pytest.mark.parametrize('kind', ['wrong_pins','reordered','covered','gap','duplicate','board_wrong'])
def test_board_motion_alone_cannot_authorize_wrong_or_unseen_final_pins(kind):
    frame, quad = scene()
    gate = ImageMotionGate()
    for i in range(3):
        moved, corners = shifted(frame, quad, i*12)
        assert not gate.compare(moved, corners, pins(i*12), i, i*125)
    moved, corners = shifted(frame, quad, 36)
    current = pins(36); fid, ts = 3,375
    if kind == 'wrong_pins': current[2].x += 8
    if kind == 'reordered': current = current[::-1]
    if kind == 'covered': moved[:] = 40
    if kind == 'gap': ts = 1000
    if kind == 'duplicate': fid = 2
    if kind == 'board_wrong': corners += [15,0]
    assert not gate.compare(moved,corners,current,fid,ts)
    assert gate.evidence['count'] < 4


def test_image_aligned_mean_removes_alternating_jitter_not_real_motion():
    frame,quad=scene(); gate=ImageMotionGate()
    for i,jitter in enumerate((-2.,2.,-2.,2.)):
        moved,corners=shifted(frame,quad,i*12)
        result=gate.compare(moved,corners+[jitter,0],pins(i*12+jitter),i,i*125)
    assert result
    np.testing.assert_allclose(gate.ready_pins,[[p.x,p.y] for p in pins(36)],atol=.7)


def test_rejected_frame_clears_previously_accepted_coordinates():
    frame, quad = scene()
    gate = ImageMotionGate()
    for i in range(4):
        moved, corners = shifted(frame, quad, i*12)
        gate.compare(moved, corners, pins(i*12), i, i*125)
    assert gate.ready_pins is not None
    moved, corners = shifted(frame, quad, 48)
    moved[:] = 40
    assert not gate.compare(moved, corners, pins(48), 4, 500)
    assert gate.ready_pins is None and gate.ready_outline is None


def test_new_image_sequence_reacquires_after_occlusion_not_old_window():
    frame, quad = scene()
    gate = ImageMotionGate()
    for i in range(4):
        moved, corners = shifted(frame, quad, i*8)
        gate.compare(moved, corners, pins(i*8), i, i*100)
    assert not gate.compare(np.full_like(frame, 40), corners, pins(24), 4, 400)
    for i in range(5, 9):
        moved, corners = shifted(frame, quad, (i-5)*8)
        assert gate.compare(moved, corners, pins((i-5)*8), i, i*100) == (i == 8)
