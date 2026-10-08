"""Synthetic frozen photos and fake cloud/Pi only; no live hardware acceptance."""
from copy import deepcopy

import pytest

from app.guided_wiring_review import saved_wiring_photos_current
from test_debug_sessions import setup
from test_guided_wiring_review import _capture_stub, _start, _photos, _act, _cloud, _answer
from test_wiring_chat_flow import chat, photos, act, current


def prepared(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    return service, state, sid, context


@pytest.mark.parametrize('change', ['runtime', 'identity', 'unavailable'])
def test_selected_three_photos_analyse_after_live_camera_changes(setup, change):
    service, state, sid, context = prepared(setup)
    if change == 'runtime':
        state.runtime_manager.snapshot().runtime_revision += 1
    elif change == 'identity':
        state.source.current_index += 1
    else:
        def unavailable():
            raise ValueError('camera_source_unavailable')
        service._camera = unavailable
    public = service.get(sid)
    assert public['camera_current'] is False and public['wiring_photos_current'] is True
    originals = deepcopy(public['wiring_review']['slots'])
    _cloud(state, _answer(context))
    _act(service, sid, context, 'analyse')
    service.tick(sid)
    result = service.get(sid)
    assert result['wiring_review']['status'] == 'ready'
    assert result['wiring_review']['slots'] == originals
    assert len(state.design_service.bridge.calls) == 2
    assert not state.pi_execution.jobs and not state.component_tests.actions


@pytest.mark.parametrize('during_model', [False, True])
def test_context_refresh_for_camera_only_preserves_selected_originals_and_analysis(setup, during_model):
    service, state, sid, context = prepared(setup)
    before = deepcopy(service.get(sid)['wiring_review']['slots'])
    changed = False
    def refresh():
        nonlocal changed
        if changed:
            return
        changed = True
        state.source.current_index += 1
        service.action(sid, 'context_changed', 'camera-refresh', context=context)
    if not during_model:
        refresh()
    _cloud(state, _answer(context), refresh if during_model else None)
    _act(service, sid, context, 'analyse')
    service.tick(sid)
    result = service.get(sid)
    assert result['wiring_review']['status'] == 'ready'
    assert result['wiring_review']['slots'] == before
    assert result['wiring_photos_current'] and result['camera_current']
    assert all(entry['current'] and entry['available'] for entry in result['evidence'])


@pytest.mark.parametrize('damage', ['unaccepted', 'missing_evidence', 'hash_mismatch', 'expired'])
def test_camera_exception_requires_three_exact_accepted_available_originals(setup, damage):
    service, state, sid, context = prepared(setup)
    session = service.sessions[sid]
    slot = session['wiring_review']['slots']['pi_side_b']
    entry = next(entry for entry in session['evidence'] if entry['id'] == slot['capture_id'])
    if damage == 'unaccepted':
        slot.pop('photo_acceptance')
    elif damage == 'missing_evidence':
        session['evidence'].remove(entry)
    elif damage == 'hash_mismatch':
        entry['sha256'] = 'f' * 64
    else:
        entry['available'] = False
    assert not saved_wiring_photos_current(session)
    state.source.current_index += 1
    service.action(sid, 'context_changed', 'invalid-camera-refresh', context=context)
    result = service.get(sid)
    assert result['wiring_review']['status'] == 'stale'
    assert result['wiring_review']['error'] == 'camera_changed'
    assert not state.design_service.bridge.calls


def test_live_capture_and_hardware_phases_still_require_current_camera(setup):
    service, state, sid, context = prepared(setup)
    state.source.current_index += 1
    with pytest.raises(ValueError, match='camera_changed'):
        _act(service, sid, context, 'capture', role='pi_side_a')
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_saved_photos_do_not_authorise_live_test_camera_changes(setup):
    service, state, sid, context = prepared(setup)
    service.sessions[sid]['phase'] = 'tft_visual'
    assert not service.get(sid)['wiring_photos_current']
    state.source.current_index += 1
    service.tick(sid)
    assert service.get(sid)['phase'] == 'camera_changed'
    assert service.get(sid)['wiring_review']['status'] == 'stale'


def test_project_code_change_still_discards_inflight_photo_result(setup):
    service, state, sid, context = prepared(setup)
    changed = deepcopy(context)
    changed['code'] += '\n# explicit changed draft\n'
    once = False
    def refresh():
        nonlocal once
        if not once:
            once = True
            service.action(sid, 'context_changed', 'code-refresh', context=changed)
    _cloud(state, _answer(context), refresh)
    _act(service, sid, context, 'analyse')
    service.tick(sid)
    result = service.get(sid)
    assert result['wiring_review']['status'] == 'stale'
    assert result['wiring_review']['error'] == 'context_changed'
    assert result['wiring_review']['results'] == [] and not result['model_busy']
    assert not state.pi_execution.jobs


def test_interruption_posts_a_current_error_and_stops_the_original_chat_clock(chat):
    app, state, mobile, phone, published, sid, path = chat
    photos(state)
    act(state, 'analyse')
    before = current(state)
    assert before['wiring_flow']['kind'] == 'analysing'
    session = state.debug_sessions.sessions[sid]
    changed = deepcopy(session['context'])
    changed['code'] += '\n# explicit changed draft\n'
    state.debug_sessions.action(sid, 'context_changed', 'interrupt-code-change', context=changed)
    conversation = state.assistant.read('shared-conversation')
    assert conversation['wiring_analysis'] is None
    error = current(state)
    assert error['wiring_flow']['kind'] == 'error'
    assert 'Analysis did not complete' in error['text'] or '沒有完成分析' in error['text']
    assert 'context' not in error['text'] or 'context_changed' not in error['text']
    historical = next(message for message in conversation['messages'] if message['id'] == before['id'])
    assert historical['wiring_flow']['current'] is False
    assert historical['wiring_flow']['elapsed_ms'] is not None
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs
