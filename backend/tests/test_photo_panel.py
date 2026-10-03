"""Photo-only LCD plane/parallax recovery; no model, camera or device calls."""
import cv2
import numpy as np
import pytest

from app.photo_panel import photo_lcd_orientation
from app.vision.yolo_pose import BoardPoseObservation


def lcd_scene(symmetric=False):
    image=np.full((464,304,3),(160,60,20),np.uint8)
    quad=np.float32([[32,32],[271,32],[271,431],[32,431]])
    lower=404 if symmetric else 381
    # Raised LCD side rails need not be axis-aligned in the PCB-hole plane.
    panel=np.int32([[23,60],[282,58],[272,lower+2],[21,lower]])
    cv2.fillConvexPoly(image,panel,(28,28,28))
    cv2.polylines(image,[panel],True,(180,180,180),2)
    observation=BoardPoseObservation(quad,.7,np.ones(4),(0,0,303,463))
    return image,observation


@pytest.mark.parametrize('flipped',[False,True])
def test_four_sloped_current_edges_disambiguate_only_the_180_degree_order(flipped):
    frame,obs=lcd_scene()
    expected=obs.corners_px.copy()
    if flipped:
        from dataclasses import replace
        obs=replace(obs,corners_px=np.roll(obs.corners_px,2,axis=0))
    evidence={}
    corrected=photo_lcd_orientation(frame,obs,evidence)
    assert corrected is not None,evidence
    np.testing.assert_allclose(corrected.corners_px,expected)
    assert evidence['verified'] and evidence['minimum_edge_support']>=.70


@pytest.mark.parametrize('kind',['no_panel','covered_side','symmetric','clipped'])
def test_missing_or_ambiguous_panel_edges_do_not_authorize_photo_pins(kind):
    frame,obs=lcd_scene(symmetric=kind=='symmetric')
    if kind=='no_panel':
        frame[:]=(160,60,20)
    elif kind=='covered_side':
        frame[100:345,:65]=(110,130,140)
    elif kind=='clipped':
        obs.corners_px[0]=[-3,30]
    evidence={}
    assert photo_lcd_orientation(frame,obs,evidence) is None,evidence
    assert not evidence['verified']
