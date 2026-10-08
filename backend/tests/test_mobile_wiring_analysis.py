"""Phone analysis uses the shared dialogue and fake cloud/Pi fixtures only."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from test_guided_wiring_review import _answer, _cloud
from test_shared_test_help import headers
from test_wiring_chat_flow import chat, body, current, photos


def payload(state, **kwargs):
    request = body(state, 'analyse', **kwargs)
    return dict(action=request['action'],
                dialogue={k: request[k] for k in ('message_id', 'flow_id', 'request_id')})


def test_phone_can_explicitly_start_shared_analysis_once_and_read_result(chat):
    app, state, mobile, phone, published, sid, path = chat
    photos(state)
    session = state.debug_sessions.sessions[sid]
    original_confirmations = deepcopy(session['context']['guide_confirmations'])
    request = payload(state, request_id='phone-analysis')
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        conversation = client.get('/api/mobile/conversation', headers=headers(phone)).json()
        message = next(m for m in conversation['messages'] if m['id'] == request['dialogue']['message_id'])
        assert message['wiring_flow']['kind'] == 'analysis_request'
        assert message['wiring_flow']['can_act'] and 'analyse' in message['wiring_flow']['actions']
        assert not state.design_service.bridge.calls and not state.pi_execution.jobs
        response = client.post('/api/mobile/wiring-review', headers=headers(phone), json=request)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['review']['status'] == 'analysing' and not result['can_act']
        assert result['conversation']['wiring_analysis']['review_id'] == result['review']['id']
        revision = result['review']['revision']
        assert session['wiring_dialogue']['receipts']['phone-analysis']['state'] == 'done'
        assert client.post('/api/mobile/wiring-review', headers=headers(phone), json=request).status_code == 200
        assert session['wiring_review']['revision'] == revision
        assert not state.design_service.bridge.calls
        _cloud(state, _answer(session['context']))
        state.debug_sessions.tick(sid)
        calls = len(state.design_service.bridge.calls)
        assert calls > 0 and session['wiring_review']['status'] == 'ready'
        repeated = client.post('/api/mobile/wiring-review', headers=headers(phone), json=request)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()['review']['status'] == 'ready'
        assert repeated.json()['conversation']['wiring_analysis'] is None
        assert len(state.design_service.bridge.calls) == calls
        assert session['context']['guide_confirmations'] == original_confirmations
        assert not state.pi_execution.jobs


@pytest.mark.parametrize('invalid', ['old_question', 'revision', 'flow', 'no_dialogue', 'context'])
def test_phone_analysis_rejects_stale_or_unbound_requests(chat, invalid):
    app, state, mobile, phone, published, sid, path = chat
    old_question = deepcopy(current(state))
    photos(state)
    request = payload(state, request_id='invalid-analysis')
    if invalid == 'old_question':
        request = payload(state, message=old_question, request_id='old-photo-question')
    elif invalid == 'revision':
        request['action']['revision'] -= 1
    elif invalid == 'flow':
        request['dialogue']['flow_id'] = 'other-flow'
    elif invalid == 'no_dialogue':
        request.pop('dialogue')
    else:
        changed = deepcopy(published)
        changed['round'] += 1
        mobile.publish_context(changed)
    session = state.debug_sessions.sessions[sid]
    before = deepcopy(session['wiring_review'])
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        response = client.post('/api/mobile/wiring-review', headers=headers(phone), json=request)
        assert response.status_code == 409, response.text
    assert session['wiring_review'] == before
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs
