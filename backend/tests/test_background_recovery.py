from concurrent.futures import Future
from threading import Event
import numpy as np
import pytest
from app.vision.background_recovery import BackgroundRecovery
from app.vision.motion_tracking import PlanarFlow
from test_motion_tracking import scene


def seeded():
    gray, quad = scene()
    flow = PlanarFlow()
    assert flow.seed(gray, quad)
    return flow, gray


def test_submission_never_waits_and_has_no_backlog(monkeypatch):
    flow, gray = seeded()
    release, entered = Event(), Event()
    def slow(self, image):
        assert self is not flow
        entered.set()
        release.wait(2)
        return np.eye(3)
    monkeypatch.setattr(PlanarFlow, '_wide_search', slow)
    worker = BackgroundRecovery()
    try:
        assert worker.propose(flow, gray, 0, True) == (None, True)
        assert entered.wait(1)
        assert worker.propose(flow, gray, 33, True) == (None, False)
        release.set()
        worker.pending[-1].result(timeout=2)
        hint, submitted = worker.propose(flow, gray, 66, False)
        assert np.array_equal(hint, np.eye(3)) and not submitted
    finally:
        release.set(); worker.close()


@pytest.mark.parametrize('mode', ['expired', 'new_anchor', 'new_flow', 'clock_reversed', 'error'])
def test_invalid_results_discarded(mode):
    flow, gray = seeded(); worker = BackgroundRecovery()
    future = Future()
    if mode == 'error': future.set_exception(RuntimeError('failed'))
    else: future.set_result(np.eye(3))
    worker.pending = (flow, flow.anchor, 100, future)
    ts = 300 if mode == 'expired' else 90 if mode == 'clock_reversed' else 130
    if mode == 'new_anchor': flow.seed(gray, flow.quad)
    if mode == 'new_flow': flow, gray = seeded()
    try:
        assert worker.propose(flow, gray, ts, False) == (None, False)
    finally: worker.close()


def test_forecast_only_changes_search_area():
    flow, gray = seeded(); worker = BackgroundRecovery()
    try:
        worker.observe(flow, 0)
        flow.quad += [6, 0]
        worker.observe(flow, 33)
        original = flow.quad.copy()
        assert np.allclose(worker.search_quad(flow, 66), original+[6, 0])
        assert np.array_equal(flow.quad, original)
        assert np.array_equal(worker.search_quad(flow, 200), original)
    finally: worker.close()


def test_background_hint_cannot_skip_current_frame_validation(monkeypatch):
    from types import SimpleNamespace
    flow, gray = seeded()
    calls = []
    flow.background_recovery = SimpleNamespace(propose=lambda *args: (np.eye(3), False))
    def reject_current(image, hint=None, **kwargs):
        assert image is gray
        calls.append(hint)
        flow.failure_reason = 'lk_support'
        return None
    monkeypatch.setattr(flow, '_lk_step', reject_current)
    assert flow.step(gray, ts_ms=33) is None
    assert len(calls) == 3
    assert calls[-1] is not None


def test_background_search_keeps_pi_feature_policy(monkeypatch):
    gray, quad = scene()
    flow = PlanarFlow(pi5_cable_guard=True)
    assert flow.seed(gray, quad)
    policies = []
    def search(clone, image):
        policies.append(clone.pi5_cable_guard)
        return np.eye(3)
    monkeypatch.setattr(PlanarFlow, '_wide_search', search)
    worker = BackgroundRecovery()
    try:
        assert worker.propose(flow, gray, 0, True) == (None, True)
        worker.pending[-1].result(timeout=2)
        assert policies == [True]
    finally:
        worker.close()
