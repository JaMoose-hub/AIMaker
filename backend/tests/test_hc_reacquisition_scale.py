from types import SimpleNamespace
import numpy as np
import pytest
from app.component_worker import ComponentPoseTracker
from test_hc_refinement_budget import PROFILE, QUAD


def test_image_tolerance_scales_and_is_capped():
    t=ComponentPoseTracker(PROFILE,motion_handoff=True)
    assert t._image_reacquisition_tolerance(QUAD*.3)==3
    assert 4 < t._image_reacquisition_tolerance(QUAD) < 6
    assert t._image_reacquisition_tolerance(QUAD*5)==6
    t.motion_handoff=False
    assert t._image_reacquisition_tolerance(QUAD*5)==3
    t.motion_handoff=True;t.profile=SimpleNamespace(component_id='mrd-tf240-8p-cs')
    assert t._image_reacquisition_tolerance(QUAD*5)==3


@pytest.mark.parametrize('aligned', [True,False])
def test_larger_residual_requires_image_support(aligned):
    t=ComponentPoseTracker(PROFILE,motion_handoff=True)
    seen=[]
    def compare(frame,corners,frame_id,ts,tolerance):
        seen.append(tolerance)
        return aligned and tolerance >= 4.7
    t._pose_window=SimpleNamespace(update=lambda *a,**k:None,evidence={})
    t._reacquire_motion=SimpleNamespace(compare=compare,evidence={})
    results=[]
    for i in range(4):
        results.append(t._confirm_reacquisition(QUAD+[i*4.7,0],i,i*100,np.zeros((480,640,3),np.uint8)))
    assert results[-1] is aligned
    assert all(4.7 <= v <= 6 for v in seen)
