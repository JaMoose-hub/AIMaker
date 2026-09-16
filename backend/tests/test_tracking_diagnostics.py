import numpy as np

from app.vision.tracking_diagnostics import TrackingDiagnostics
from app.vision.motion_tracking import PlanarFlow


def test_transitions_bounded_and_repeated_loss_counted():
    diag = TrackingDiagnostics()
    p = dict(frame_id=1, ts_ms=33, components=[], detection=dict(
        board_id='raspberry-pi-5', tracking='searching',
        pose_quality=dict(reason='lk_support', model_source=dict(age_ms=80))))
    for i in range(100):
        p['frame_id'] = i
        result = diag.record(p, 40, 33)
    assert result['reason_frames'] == {'lk_support': 100}
    assert result['over_budget_frames'] == 100
    assert len(result['transitions']) == 1
    assert result['transitions'][0]['model_age_ms'] == 80
    for i in range(100):
        p['detection']['tracking'] = str(i)
        result = diag.record(p, 10, 33)
    assert len(result['transitions']) == 24
    assert result['over_budget_frames'] == 100


def test_clear_anchor_recovery_skips_expensive_search(monkeypatch):
    flow = PlanarFlow()
    flow.gray = np.zeros((32, 32), np.uint8)
    flow.points = np.ones((20, 1, 2), np.float32)
    calls = []
    def lk(gray, hint=None, **kwargs):
        calls.append(kwargs.get('anchored', False))
        return np.eye(3) if kwargs.get('anchored') else None
    monkeypatch.setattr(flow, '_lk_step', lk)
    monkeypatch.setattr(flow, '_wide_search', lambda _: (_ for _ in ()).throw(AssertionError('unneeded search')))
    assert np.array_equal(flow.step(flow.gray, ts_ms=33), np.eye(3))
    assert calls == [False, True]
    assert flow.recovered and not flow.search_ran
