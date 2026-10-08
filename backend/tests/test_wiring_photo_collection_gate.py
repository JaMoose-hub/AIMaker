"""Three-photo collection cannot be bypassed by ordinary chat media.

Synthetic images, fake hardware and fake cloud only; no running service access.
"""
from copy import deepcopy
import hashlib

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
    bridge = state.design_service.bridge
    assert len(bridge.calls) == 2
    assert 'POC EXIT INVENTORY:' in bridge.calls[0][0]
    assert 'PIN AND ROUTE REVIEW:' in bridge.calls[1][0]
    review = state.debug_sessions.sessions[sid]['wiring_review']
    assert set(review['slots']) == set(ROLES) and not review['missing_roles']
    assert review['status'] in {'ready', 'needs_human'}
    stages = review['model_receipt']['stages']
    assert [stage['stage'] for stage in stages] == ['exit_inventory', 'pin_review']
    for (_, options), images, stage in zip(bridge.calls, bridge.images, stages):
        assert len(options['image_paths']) == len(images) == len(stage['image_inputs']) == 3
        assert {image['role'] for image in stage['image_inputs']} == set(ROLES)
        for received, metadata in zip(images, stage['image_inputs']):
            slot = review['slots'][metadata['role']]
            assert metadata['capture_id'] == slot['capture_id']
            assert metadata['source_sha256'] == slot['sha256']
            assert metadata['source_size'] == slot['size']
            assert metadata['view'] == 'overview' and metadata['crop'] is None
            assert metadata['supplied_sha256'] == hashlib.sha256(received).hexdigest()
    assert not state.pi_execution.jobs
