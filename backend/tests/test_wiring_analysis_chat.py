"""Analysis timing and chat exclusion with synthetic photos and fake cloud only."""
from copy import deepcopy

from fastapi.testclient import TestClient

from app.assistant import AssistantService, SendRequest, fingerprint
from test_guided_wiring_review import _answer, _cloud
from test_shared_test_help import headers
from test_wiring_chat_flow import chat, current, act, photos


def request(published, request_id='text-during-analysis'):
    return SendRequest.model_validate(dict(request_id=request_id, text='第一側要怎麼拍？', stage='guide',
        target='wiring', design=published['design'], context=published['context'], round=0))


def enqueue(state):
    photos(state)
    act(state, 'analyse')
    return current(state)


def test_start_records_human_action_and_poll_projects_one_stable_debug_analysis(chat):
    app, state, mobile, phone, published, sid, path = chat
    session = state.debug_sessions.sessions[sid]
    invitation = next(m for m in state.assistant.read('shared-conversation')['messages'] if m.get('test_help_offer'))
    assert invitation['role'] == 'assistant'
    actions = [m for m in session['messages'] if m['role'] == 'user']
    assert actions[0]['text'].startswith('拍照檢查 ') and actions[0]['text'].endswith(' 接線。')
    assert all(m['text'] != invitation['text'] for m in actions)
    message = enqueue(state)
    started = message['wiring_flow']['started_at']
    assert isinstance(started, (int, float)) and started > 0
    assert message['wiring_flow']['kind'] == 'analysing' and not message['wiring_flow']['can_act']
    record = state.assistant.read('shared-conversation')
    assert record['jobs'] == []
    assert record['wiring_analysis'] == dict(flow_id=message['wiring_flow']['flow_id'], session_id=sid,
        review_id=message['wiring_flow']['review_id'], round=1, revision=message['wiring_flow']['revision'], started_at=started)
    before = deepcopy(session['wiring_dialogue']['events'])
    state.assistant = AssistantService(state, path / 'assistant')
    for _ in range(3):
        assert state.assistant.read('shared-conversation')['wiring_analysis'] == record['wiring_analysis']
        assert state.mobile_service.conversation(phone['session_id'])['wiring_analysis'] == record['wiring_analysis']
    assert session['wiring_dialogue']['events'] == before
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_desktop_and_phone_text_are_rejected_before_history_or_job_mutation(chat):
    app, state, mobile, phone, published, sid, path = chat
    enqueue(state)
    before = deepcopy(state.assistant.read('shared-conversation'))
    review = deepcopy(state.debug_sessions.sessions[sid]['wiring_review'])
    with TestClient(app, client=('127.0.0.1', 5000)) as client:
        result = client.post('/api/assistant/conversations/shared-conversation/messages', json=request(published).model_dump())
        assert result.status_code == 409 and result.json()['detail'] == 'wiring_analysis_in_progress'
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        result = client.post('/api/mobile/messages', headers=headers(phone), json=dict(request_id='mobile-text',
            text='我想再問一個問題', context_id=mobile.latest['context_id']))
        assert result.status_code == 409 and result.json()['detail'] == 'wiring_analysis_in_progress'
    assert state.assistant.read('shared-conversation') == before
    assert state.debug_sessions.sessions[sid]['wiring_review'] == review
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_completed_request_recovery_is_idempotent_even_during_analysis(chat):
    app, state, mobile, phone, published, sid, path = chat
    body = request(published, 'previous-completed-request')
    payload = body.model_dump()
    for key, default in (('asset_ids', []), ('inherit_media', True), ('capture_id', None),
                         ('check_scope', None), ('wire_id', None), ('source', 'desktop')):
        if payload.get(key) == default:
            payload.pop(key, None)
    record = state.assistant._load('shared-conversation')
    record['jobs'].append(dict(id='completed', request_id=body.request_id, fingerprint=fingerprint(payload), status='completed'))
    state.assistant._save(record)
    enqueue(state)
    before = state.assistant.read('shared-conversation')
    result = state.assistant.send('shared-conversation', body)
    assert result == before and result['wiring_analysis'] is not None
    assert len(result['jobs']) == 1 and not state.design_service.bridge.calls


def test_success_clock_includes_queue_and_finishes_without_restarting_on_retake(chat, monkeypatch):
    app, state, mobile, phone, published, sid, path = chat
    photos(state)
    clock = [1000.0]
    monkeypatch.setattr('app.guided_wiring_review.time.time', lambda: clock[0])
    act(state, 'analyse')
    analysis = current(state)
    assert analysis['wiring_flow']['started_at'] == 1000
    context = state.debug_sessions.sessions[sid]['context']
    def in_model():
        # pending has been consumed by tick; status still authoritatively busy.
        assert not state.debug_sessions.sessions[sid]['wiring_review']['pending']
        assert state.assistant.read('shared-conversation')['wiring_analysis']['started_at'] == 1000
    _cloud(state, _answer(context), hook=in_model)
    clock[0] = 1005.0
    state.debug_sessions.tick(sid)
    completed = state.assistant.read('shared-conversation')
    assert completed['wiring_analysis'] is None and current(state)['wiring_flow']['elapsed_ms'] == 5000
    historical = next(m for m in completed['messages'] if m['id'] == analysis['id'])
    assert historical['wiring_flow']['elapsed_ms'] == 5000
    clock[0] = 1010.0
    act(state, 'capture', role='pi_side_b')
    for _ in range(2):
        record = state.assistant.read('shared-conversation')
        old = next(m for m in record['messages'] if m['id'] == analysis['id'])
        assert old['wiring_flow']['started_at'] == 1000 and old['wiring_flow']['elapsed_ms'] == 5000
        assert record['wiring_analysis'] is None
    assert len(state.design_service.bridge.calls) == 1 and not state.pi_execution.jobs


def test_failure_clock_stops_and_only_explicit_retry_gets_new_start(chat, monkeypatch):
    app, state, mobile, phone, published, sid, path = chat
    photos(state)
    clock = [2000.0]
    monkeypatch.setattr('app.guided_wiring_review.time.time', lambda: clock[0])
    calls = []
    def fail(*args, **kwargs):
        calls.append(True)
        raise RuntimeError('synthetic analysis failure')
    state.design_service.bridge.generate = fail
    act(state, 'analyse')
    clock[0] = 2008.0
    state.debug_sessions.tick(sid)
    for _ in range(2):
        assert state.assistant.read('shared-conversation')['wiring_analysis'] is None
        assert current(state)['wiring_flow']['elapsed_ms'] == 8000
    assert current(state)['wiring_flow']['kind'] == 'error' and len(calls) == 1
    clock[0] = 2011.0
    act(state, 'analyse')
    assert current(state)['wiring_flow']['started_at'] == 2011
    assert current(state)['wiring_flow']['elapsed_ms'] is None
    assert len(calls) == 1 and not state.pi_execution.jobs


def test_foreign_cleared_and_restarted_scope_cannot_leak_busy_or_invent_timestamp(chat):
    app, state, mobile, phone, published, sid, path = chat
    enqueue(state)
    session = state.debug_sessions.sessions[sid]
    session['wiring_review']['analysis_started_at'] = None  # Legacy in-flight state has no trustworthy clock.
    assert state.assistant.read('shared-conversation')['wiring_analysis']['started_at'] is None
    state.assistant.create('foreign-conversation', project_id='foreign')
    assert state.assistant.read('foreign-conversation')['wiring_analysis'] is None
    session['phase'] = 'backend_restarted'
    assert state.assistant.read('shared-conversation')['wiring_analysis'] is None
    session['phase'] = 'wiring_review_analysing'
    state.assistant.reset_context('shared-conversation', 'clear')
    assert state.assistant.read('shared-conversation')['wiring_analysis'] is None
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs
