"""Three-photo collection cannot be bypassed by ordinary chat media.

Synthetic images, fake hardware and fake cloud only; no running service access.
"""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.assistant import SendRequest
from test_guided_wiring_review import _answer, _cloud
from test_mobile_wiring_review import _upload
from test_shared_test_help import headers
from test_wiring_chat_flow import chat, current, act


ROLES = ('pi_side_a', 'pi_side_b', 'component_header')


@pytest.mark.parametrize('photo_count', [0, 1, 2, 3])
def test_generic_phone_photo_cannot_start_analysis_during_collection(chat, photo_count):
    app, state, mobile, phone, published, sid, path = chat
    for role in ROLES[:photo_count]:
        act(state, 'capture', role=role)
        assert not state.design_service.bridge.calls
    before = deepcopy(state.assistant.read('shared-conversation'))
    review = deepcopy(state.debug_sessions.sessions[sid]['wiring_review'])
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        asset = _upload(client, phone, 'generic-photo-during-collection')
        response = client.post('/api/mobile/messages', headers=headers(phone), json=dict(
            request_id='generic-photo', text='', asset_ids=[asset['id']],
            inherit_media=False, context_id=mobile.latest['context_id']))
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == 'wiring_photo_collection_in_progress'
    assert state.assistant.read('shared-conversation') == before
    assert state.debug_sessions.sessions[sid]['wiring_review'] == review
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


@pytest.mark.parametrize('media', [{'asset_ids': ['ordinary-photo']}, {'capture_id': 'ordinary-capture'}])
def test_desktop_media_cannot_bypass_the_same_collection_gate(chat, media):
    app, state, mobile, phone, published, sid, path = chat
    act(state, 'capture', role='pi_side_a')
    before = deepcopy(state.assistant.read('shared-conversation'))
    body = SendRequest.model_validate(dict(request_id='desktop-photo', text='分析這張照片',
        stage='guide', target='wiring', design=published['design'], context=published['context'],
        round=0, inherit_media=False, **media))
    with pytest.raises(Exception) as error:
        state.assistant.send('shared-conversation', body)
    assert error.value.status_code == 409
    assert error.value.detail == 'wiring_photo_collection_in_progress'
    assert state.assistant.read('shared-conversation') == before
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_guided_photos_advance_without_model_then_explicit_analysis_uses_all_three(chat):
    app, state, mobile, phone, published, sid, path = chat
    for index, role in enumerate(ROLES):
        assert current(state)['wiring_flow']['role'] == role
        act(state, 'capture', role=role)
        state.debug_sessions.tick(sid)
        review = state.debug_sessions.sessions[sid]['wiring_review']
        assert sum(slot is not None for slot in review['slots'].values()) == index + 1
        assert review['status'] == 'collecting'
        assert not state.design_service.bridge.calls
    assert current(state)['wiring_flow']['kind'] == 'analysis_request'
    context = state.debug_sessions.sessions[sid]['context']
    _cloud(state, _answer(context))
    act(state, 'analyse')
    state.debug_sessions.tick(sid)
    assert len(state.design_service.bridge.calls) == 1
    review = state.debug_sessions.sessions[sid]['wiring_review']
    assert set(review['slots']) == set(ROLES) and not review['missing_roles']
    assert review['status'] in {'ready', 'needs_human'}
    assert not state.pi_execution.jobs
