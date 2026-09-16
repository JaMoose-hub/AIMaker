import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.vision.reference_recovery import ReferencePoseRecovery
from test_reference_recovery import texture


def make_profile(tmp_path, space):
    reference = texture()
    src = np.float32([[0,0],[319,0],[319,239],[0,239]])
    dst = np.float32([[110,80],[430,65],[400,280],[95,320]])
    capture = cv2.warpPerspective(reference, cv2.getPerspectiveTransform(src,dst), (640,480))
    cv2.imwrite(str(tmp_path/'capture.png'),capture)
    path = tmp_path/'vision_profile.json'
    spec = {'image':'capture.png','corners_px':dst.tolist(),'rectified_size':[320,240]}
    if space is not None:
        spec['descriptor_space'] = space
    path.write_text(json.dumps({'reference_pose':spec}),encoding='utf-8')
    return path, capture, dst


@pytest.mark.parametrize('rotation',range(4))
def test_native_descriptors_recover_canonical_semantics(tmp_path,rotation):
    path, capture, corners = make_profile(tmp_path,'native')
    recovery = ReferencePoseRecovery.from_component_profile(path)
    center = np.float32([320,240])
    angle = rotation*np.pi/2
    matrix = np.float32([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    expected = (corners-center)@matrix.T+center
    transform = cv2.getPerspectiveTransform(corners,np.float32(expected))
    frame = cv2.warpPerspective(capture,transform,(640,480))
    region = SimpleNamespace(box_xyxy=tuple(np.r_[expected.min(0),expected.max(0)]),confidence=.9)
    found = recovery.locate(frame,region)
    assert found is not None, recovery.evidence
    np.testing.assert_allclose(found.corners_px,expected,atol=2)
    assert recovery.evidence['descriptor_space']=='native'


@pytest.mark.parametrize('kind',['blank','mirror','patch'])
def test_native_reference_rejects_unverified_geometry(tmp_path,kind):
    path,capture,_ = make_profile(tmp_path,'native')
    recovery = ReferencePoseRecovery.from_component_profile(path)
    frame = np.zeros_like(capture)
    if kind=='mirror':
        frame=capture[:,::-1].copy()
    elif kind=='patch':
        frame[100:155,150:205]=capture[100:155,150:205]
    found=recovery.locate(frame,SimpleNamespace(box_xyxy=(50,40,550,400),confidence=.9))
    assert found is None


def test_default_reference_keeps_rectified_path(tmp_path):
    path,_,_ = make_profile(tmp_path,None)
    assert ReferencePoseRecovery.from_component_profile(path).descriptor_space=='rectified'
    path,_,_ = make_profile(tmp_path,'unsupported')
    with pytest.raises(ValueError,match='descriptor_space'):
        ReferencePoseRecovery.from_component_profile(path)


def test_only_hc_profile_opts_in_native():
    root=Path(__file__).resolve().parents[2]/'profiles/components'
    for path in root.glob('*/vision_profile.json'):
        spec=json.loads(path.read_text(encoding='utf-8')).get('reference_pose') or {}
        assert (spec.get('descriptor_space')=='native') == (path.parent.name=='hc-sr04')
