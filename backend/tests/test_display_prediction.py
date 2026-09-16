from copy import deepcopy
import pytest
from app.vision.display_prediction import DisplayPrediction


def pose(ts, x):
    return dict(frame_id=ts, ts_ms=ts, tracking='locked', video_size=[640,480], confidence=.9,
        outline=[[x,100],[x+200,100],[x+200,240],[x,240]],
        pins=[dict(id='GND', x=x+10,y=110,v=True)],
        pose_quality=dict(object_supported=True, partial=False))


def lost(ts, reason='lk_support'):
    return dict(frame_id=ts, ts_ms=ts, tracking='searching', pins=[], outline=None,
                pose_quality=dict(reason=reason))


def test_prediction_is_bounded_and_does_not_mutate_observation():
    p=DisplayPrediction()
    a,b=pose(0,100),pose(33,106)
    original=deepcopy(b)
    p.apply(a);p.apply(b)
    result=p.apply(lost(66))
    assert result['pins'][0]['x'] == pytest.approx(122)
    assert result['tracking']=='stale'
    assert result['pose_quality']['recovering']
    assert result['pose_quality']['predicted']
    assert b==original and p.latest==original
    assert p.apply(lost(154))['outline'] is None


@pytest.mark.parametrize('reason',['pin_orientation_unverified','frame_gap','source_absent_no_pin_support','recovery_timeout'])
def test_hard_loss_never_predicts(reason):
    p=DisplayPrediction();p.apply(pose(0,100));p.apply(pose(33,106))
    assert p.apply(lost(66,reason))['outline'] is None
    assert p.apply(lost(80))['outline'] is None


def test_reacquisition_returns_actual_coordinates():
    p=DisplayPrediction();p.apply(pose(0,100));p.apply(pose(33,106))
    p.apply(lost(66))
    measured=pose(99,103)
    assert p.apply(measured) is measured


def test_component_predictions_have_independent_history_and_expiry():
    from app.motion_worker import PREDICTED_COMPONENT_IDS
    assert set(PREDICTED_COMPONENT_IDS)=={'hc-sr04','mrd-tf240-8p-cs'}
    predictors={key:DisplayPrediction() for key in PREDICTED_COMPONENT_IDS}
    for key,x in [('hc-sr04',100),('mrd-tf240-8p-cs',300)]:
        a,b=pose(0,x),pose(33,x+6)
        a['component_id']=b['component_id']=key
        predictors[key].apply(a);predictors[key].apply(b)
        result=predictors[key].apply(dict(lost(66),component_id=key))
        assert result['component_id']==key
        assert result['pins'][0]['x']==pytest.approx(x+22)
        assert result['pose_quality']['predicted']
    assert predictors['hc-sr04'].apply(lost(154))['outline'] is None
    assert predictors['mrd-tf240-8p-cs'].latest is not None
