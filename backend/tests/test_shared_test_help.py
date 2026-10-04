"""Persistent consent buttons, synthetic test records only; no model, Pi or camera."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.assistant import AssistantService
from app.api.assistant import router as assistant_router
from app.api.mobile import router as mobile_router
from app.mobile import MobileService
from test_debug_sessions import setup as debug_setup, _context, _run
from test_mobile import Clock, RTC, Analyzer


def fixture(tmp_path):
    debug, state = debug_setup.__wrapped__(tmp_path)
    context = _context()
    state.debug_sessions = debug
    state.mobile_photo = Analyzer()
    state.assistant = AssistantService(state, tmp_path / 'assistant')
    state.assistant.create('shared-conversation', project_id=context['project']['id'])
    clock = Clock()
    mobile = MobileService(state, tmp_path / 'mobile', clock=clock, wall=clock.wall, rtc_factory=RTC)
    state.mobile_service = mobile
    published = dict(conversation_id='shared-conversation', title='Synthetic test issue', stage='guide', target='wiring', round=0,
        design=dict(prompt='Synthetic only', component_ids=context['project']['component_ids'], locale='zh-TW',
                    current=context['project'], model='fake', effort='low'),
        context=dict(debug_context={key: deepcopy(context[key]) for key in ('code', 'guide_confirmations', 'test_keys', 'guide_run')}))
    mobile.publish_context(published)
    pairing = mobile.create_pairing('shared-conversation', 'http://192.168.1.5:8100')
    phone = mobile.pair(pairing['code'], 'Synthetic phone')
    run = _run('failed-test', 'hc-sr04', context, 'finished', 'inconclusive')
    run.update(revision=context['project']['revision'], reason='no_echo', reserved=False)
    state.component_tests.runs.append(run)
    app = FastAPI()
    app.state.mobile_service = mobile
    app.state.assistant = state.assistant
    app.include_router(assistant_router)
    app.include_router(mobile_router)
    meta = dict(offer_id='offer-1', project_id=context['project']['id'], project_revision=context['project']['revision'],
        component_id='hc-sr04', guide_key=context['test_keys']['hc-sr04'], guide_run=0, context_epoch=0,
        test_id=run['id'], reason='no_echo', mode='wiring', code_hash=hashlib.sha256(context['code'].encode()).hexdigest())
    return app, state, mobile, phone, published, meta


def imported(state, meta):
    return state.assistant.import_messages('shared-conversation', 'test-help:stable-receipt',
        [dict(id='test-help-invitation', role='assistant', text='測試沒有回應。要拍照檢查接線嗎？', stage='guide', round=0)],
        'legacy-debug', meta)['messages'][-1]


def headers(phone):
    return {'Authorization': 'Bearer ' + phone['token']}


def invitation(mobile, message, op='start'):
    return dict(op=op, message_id=message['id'], offer_id=message['test_help_offer']['offer_id'], context_id=mobile.latest['context_id'])


def post(client, mobile, phone, message, op='start', **changes):
    return client.post('/api/mobile/wiring-review', headers=headers(phone), json={'invitation': {**invitation(mobile, message, op), **changes}})


def test_offer_is_exact_durable_and_shared_without_generation(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    offer = message['test_help_offer']
    assert offer['offer_id'] == 'offer-1' and offer['message_id'] == message['id']
    assert offer['state'] == 'pending' and offer['can_act'] and offer['can_dismiss']
    assert 'source_signature' not in offer and 'code_hash' not in offer
    state.assistant = AssistantService(state, tmp_path / 'assistant')
    app.state.assistant = state.assistant
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        record = client.get('/api/mobile/conversation', headers=headers(phone)).json()
        assert record['messages'][-1]['test_help_offer'] == offer
    assert not state.debug_sessions.sessions and not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_explicit_phone_start_collects_only_and_continue_preserves_review(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        response = post(client, mobile, phone, message)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['offer']['state'] == 'started' and result['offer']['reusable_review']
        assert result['review']['status'] == 'collecting' and result['review']['slots'] == dict(pi_side_a=None, pi_side_b=None, component_header=None)
        assert 'debug_session_id' not in result and 'debug_session' not in result
        session = next(iter(state.debug_sessions.sessions.values()))
        session['wiring_review']['reviews']['retained'] = dict(decision='confirmed', source='human')
        selected = deepcopy(session['wiring_review'])
        public_selected = mobile.wiring_review(phone['session_id'])['review']
        retry = post(client, mobile, phone, message).json()
        assert retry['review'] == public_selected and len(state.debug_sessions.sessions) == 1
        assert session['wiring_review'] == selected
        current = next(m for m in state.assistant.read('shared-conversation')['messages'] if m['id'] == message['id'])
        assert current['session_id'] == session['id'] and current['test_help_offer']['state'] == 'started'
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs and not state.component_tests.actions


def test_later_persists_without_a_camera_and_cannot_start_a_dismissed_offer(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    state.config.camera.source = 'unavailable'
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        response = post(client, mobile, phone, message, 'later')
        assert response.status_code == 200 and response.json()['offer']['state'] == 'dismissed'
        assert post(client, mobile, phone, message).status_code == 409
    assert state.assistant.read('shared-conversation')['messages'][-1]['test_help_offer']['state'] == 'dismissed'
    assert not state.debug_sessions.sessions and not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_new_offer_id_rearms_same_message_and_old_id_never_has_authority(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    old = imported(state, meta)
    mobile.wiring_review_invitation(phone['session_id'], invitation(mobile, old, 'later'))
    assert imported(state, meta)['test_help_offer']['state'] == 'dismissed', 'A retry cannot rearm a dismissed decision'
    latest = imported(state, {**meta, 'offer_id': 'offer-2'})
    assert latest['id'] == old['id'] and latest['test_help_offer']['state'] == 'pending'
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert post(client, mobile, phone, old).status_code == 409
        assert post(client, mobile, phone, latest).status_code == 200
    messages = state.assistant.read('shared-conversation')['messages']
    assert len([m for m in messages if m.get('test_help_offer')]) == 1
    assert len([m for m in messages if m.get('wiring_flow', {}).get('kind') == 'photo_request']) == 1


def test_retest_pass_invalidation_and_changed_source_expire_old_offer(tmp_path):
    for change in ('passed', 'new-run', 'invalidated', 'reason', 'revision'):
        app, state, mobile, phone, published, meta = fixture(tmp_path / change)
        message = imported(state, meta)
        run = state.component_tests.runs[-1]
        if change == 'passed': run['outcome'] = 'passed'
        if change == 'new-run': state.component_tests.runs.append({**run, 'id': 'newer-test'})
        if change == 'invalidated': run['invalidated'] = True
        if change == 'reason': run['reason'] = 'cancelled'
        if change == 'revision': run['revision'] += 1
        assert state.assistant.read('shared-conversation')['messages'][-1]['test_help_offer']['state'] == 'stale'
        with TestClient(app, client=('192.168.1.8', 5000)) as client:
            assert post(client, mobile, phone, message).status_code == 409
        assert not state.debug_sessions.sessions and not state.pi_execution.jobs


def test_code_wiring_round_revision_and_clear_invalidate_shared_eligibility(tmp_path):
    for change in ('code', 'guide-key', 'round', 'revision', 'epoch'):
        app, state, mobile, phone, published, meta = fixture(tmp_path / change)
        message = imported(state, meta)
        next_context = deepcopy(published)
        if change == 'code': next_context['context']['debug_context']['code'] += '\n# edited'
        if change == 'guide-key': next_context['context']['debug_context']['test_keys']['hc-sr04'] = 'new-wiring'
        if change == 'round': next_context['round'] += 1
        if change == 'revision': next_context['design']['current']['revision'] += 1
        if change == 'epoch': state.assistant.reset_context('shared-conversation', 'clear')
        mobile.publish_context(next_context)
        assert state.assistant.read('shared-conversation')['messages'][-1]['test_help_offer']['state'] == 'stale'
        with TestClient(app, client=('192.168.1.8', 5000)) as client:
            assert post(client, mobile, phone, message).status_code == 409
        assert not state.debug_sessions.sessions and not state.pi_execution.jobs


def test_pairing_scope_and_typed_actions_reject_foreign_or_forged_authority(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert client.post('/api/mobile/wiring-review', json={'invitation': invitation(mobile, message)}).status_code == 403
        assert post(client, mobile, phone, message, message_id='foreign-message').status_code == 409
        assert post(client, mobile, phone, message, context_id='foreign-context').status_code == 409
        payload = {'invitation': invitation(mobile, message), 'action': {'op': 'start', 'component_id': 'hc-sr04'}}
        assert client.post('/api/mobile/wiring-review', headers=headers(phone), json=payload).status_code == 422
        assert client.post('/api/mobile/wiring-review', headers=headers(phone), json={'invitation': invitation(mobile, message), 'asset_id': 'any-asset'}).status_code == 422
        assert post(client, mobile, phone, message, debug_session_id='foreign-session').status_code == 422
    assert not state.debug_sessions.sessions and not state.pi_execution.jobs


def test_desktop_button_uses_same_consent_record_and_returns_actual_collect_session(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    body = {key: value for key, value in invitation(mobile, message).items() if key != 'context_id'}
    with TestClient(app, client=('192.168.1.8', 5000)) as remote:
        assert remote.post('/api/assistant/conversations/shared-conversation/test-help', json=body).status_code == 403
    with TestClient(app, client=('127.0.0.1', 5000)) as local:
        response = local.post('/api/assistant/conversations/shared-conversation/test-help', json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['debug_session']['id'] == result['debug_session_id']
        assert result['debug_session']['purpose'] == 'wiring_review' and not result['debug_session']['model_busy']
    current = next(m for m in state.assistant.read('shared-conversation')['messages'] if m['id'] == message['id'])
    assert current['test_help_offer']['state'] == 'started'
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def restored_photo_history(state):
    """A previous photo-only collection, never a functional or Pi test case."""
    from app.debug_sessions import DebugSessions
    from test_guided_wiring_review import _start
    owner = state.debug_sessions
    runs = state.component_tests.runs
    state.component_tests.runs = []
    try:
        old_id, _ = _start(owner)
    finally:
        state.component_tests.runs = runs
    review = owner.sessions[old_id]['wiring_review']
    review['reviews']['historical-wire'] = dict(decision='confirmed', source='human')
    owner._save()
    state.debug_sessions = DebugSessions(state, owner.store, owner.capture_fn, autostart=False)
    return old_id


@pytest.mark.parametrize('surface', ['desktop', 'mobile'])
def test_fresh_photo_invitation_after_restart_starts_new_collect_and_keeps_history(tmp_path, surface):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    old_id = restored_photo_history(state)
    owner = state.debug_sessions
    history = deepcopy(owner.sessions[old_id])
    message = imported(state, meta)
    assert message['test_help_offer']['can_act']
    assert owner.sessions[old_id] == history, 'Availability polling must not modify photo history'
    with TestClient(app, client=('127.0.0.1', 5000)) as client:
        if surface == 'mobile':
            response = post(client, mobile, phone, message)
        else:
            response = client.post('/api/assistant/conversations/shared-conversation/test-help',
                json={key: value for key, value in invitation(mobile, message).items() if key != 'context_id'})
        assert response.status_code == 200, response.text
    new_id = next(sid for sid in owner.sessions if sid != old_id)
    assert owner.sessions[old_id]['status'] == 'stopped' and owner.sessions[old_id]['phase'] == 'superseded'
    assert owner.sessions[old_id]['wiring_review'] == history['wiring_review']
    assert owner.sessions[old_id]['messages'] == history['messages']
    assert owner.sessions[new_id]['purpose'] == 'wiring_review'
    current = next(m for m in reversed(state.assistant.read('shared-conversation')['messages'])
                   if m.get('wiring_flow', {}).get('current'))
    assert current['wiring_flow']['kind'] == 'photo_request' and current['wiring_flow']['role'] == 'pi_side_a'
    assert not owner.sessions[new_id]['wiring_review']['reviews'], 'Old human decisions cannot confirm the new collection'
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_restored_functional_or_execution_related_case_still_blocks_photo_invitation(tmp_path):
    changes = [dict(purpose='debug'), dict(job_ids=['prior-pi-job']), dict(run_ids=['prior-run']),
               dict(trial_id='prior-trial'), dict(adopted_tests=[dict(id='prior-test')]),
               dict(capture_pending=True), dict(chat_pending=True), dict(model_started_at=1)]
    for index, change in enumerate(changes):
        app, state, mobile, phone, published, meta = fixture(tmp_path / str(index))
        old_id = restored_photo_history(state)
        owner = state.debug_sessions
        owner.sessions[old_id].update(change)
        history = deepcopy(owner.sessions[old_id])
        message = imported(state, meta)
        assert not message['test_help_offer']['can_act'] and message['test_help_offer']['can_dismiss']
        with TestClient(app, client=('127.0.0.1', 5000)) as client:
            response = client.post('/api/assistant/conversations/shared-conversation/test-help',
                json={key: value for key, value in invitation(mobile, message).items() if key != 'context_id'})
            assert response.status_code == 409, response.text
        with pytest.raises(ValueError, match='restart_requires_stop'):
            owner.create(_context(), '拍照檢查', purpose='wiring_review', initial_action='collect')
        assert owner.sessions[old_id] == history and len(owner.sessions) == 1
        assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_restored_photo_with_canonical_historical_adoption_starts_fresh_collection(tmp_path):
    import json
    from app.component_testing import CAMERA_TEMPLATE_VERSION, wire_key
    from app.debug_sessions import DebugSessions
    from test_guided_wiring_review import _start
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    context = _context()
    component_id = 'mrd-tf240-8p-cs'
    historical = _run('previous-tft-pass', component_id, context, 'finished', 'passed')
    wires = [wire for wire in context['project']['wiring'] if wire['componentId'] == component_id]
    historical.update(reserved=False, revision=context['project']['revision'], evidence='user_visual_confirmation',
        template_version=CAMERA_TEMPLATE_VERSION, wiring_hash=hashlib.sha256(json.dumps(wire_key(wires)).encode()).hexdigest())
    state.component_tests.runs.append(historical)
    owner = state.debug_sessions
    old_id, _ = _start(owner, context)
    adoption = deepcopy(owner.sessions[old_id]['adopted_tests'])
    assert len(adoption) == 1 and adoption[0]['run_id'] == historical['id']
    assert adoption[0]['source'] == 'existing_component_test'
    assert adoption[0]['evidence_scope'] == 'current_configuration_historical_run'
    owner._save()
    owner = state.debug_sessions = DebugSessions(state, owner.store, owner.capture_fn, autostart=False)
    message = imported(state, meta)
    assert message['test_help_offer']['can_act']
    with TestClient(app, client=('127.0.0.1', 5000)) as client:
        response = client.post('/api/assistant/conversations/shared-conversation/test-help',
            json={key: value for key, value in invitation(mobile, message).items() if key != 'context_id'})
        assert response.status_code == 200, response.text
    assert owner.sessions[old_id]['adopted_tests'] == adoption and owner.sessions[old_id]['phase'] == 'superseded'
    current = next(m for m in reversed(state.assistant.read('shared-conversation')['messages'])
                   if m.get('wiring_flow', {}).get('current'))
    assert current['wiring_flow']['kind'] == 'photo_request' and current['wiring_flow']['role'] == 'pi_side_a'
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_restored_photo_history_requires_idle_actual_work_and_explicit_new_collection(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    old_id = restored_photo_history(state)
    owner = state.debug_sessions
    history = deepcopy(owner.sessions[old_id])
    state.pi_execution.jobs.append(dict(id='current-work', state='running'))
    message = imported(state, meta)
    assert not message['test_help_offer']['can_act']
    with pytest.raises(ValueError, match='restart_requires_stop'):
        owner.create(_context(), '拍照檢查', purpose='wiring_review', initial_action='collect')
    assert owner.sessions[old_id] == history
    state.pi_execution.jobs.clear()
    assert owner.replaceable_photo_history(owner.sessions[old_id])
    for purpose, action in [('debug', None), ('wiring_review', 'capture'), ('wiring_review', 'message')]:
        with pytest.raises(ValueError, match='restart_requires_stop'):
            owner.create(_context(), '拍照檢查', purpose=purpose, initial_action=action)
    assert owner.sessions[old_id] == history and len(owner.sessions) == 1
    assert not state.design_service.bridge.calls


def test_busy_model_blocks_start_but_does_not_block_later(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    raw = state.assistant._load('shared-conversation')
    raw['jobs'].append(dict(id='pending-model', status='running', phase='replying', epoch=0))
    state.assistant._save(raw)
    state.assistant.running.add('pending-model')
    offer = state.assistant.read('shared-conversation')['messages'][-1]['test_help_offer']
    assert not offer['can_act'] and offer['can_dismiss']
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert post(client, mobile, phone, message).status_code == 409
        assert post(client, mobile, phone, message, 'later').status_code == 200
    assert not state.debug_sessions.sessions


def test_late_workspace_change_during_create_cannot_adopt_or_start_the_wrong_review(tmp_path, monkeypatch):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    original = state.debug_sessions.create
    def changed(*args, **kwargs):
        created = original(*args, **kwargs)
        update = deepcopy(published)
        update['context']['debug_context']['code'] += '\n# changed during create'
        mobile.publish_context(update)
        return created
    monkeypatch.setattr(state.debug_sessions, 'create', changed)
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert post(client, mobile, phone, message).status_code == 409
    record = state.assistant.read('shared-conversation')
    assert record['messages'][-1]['test_help_offer']['state'] == 'stale'
    assert not record['messages'][-1].get('session_id')
    assert not next(iter(state.debug_sessions.sessions.values())).get('wiring_review')
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_simultaneous_explicit_starts_are_serialized_and_reuse_one_review(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    payload = invitation(mobile, message)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: mobile.wiring_review_invitation(phone['session_id'], deepcopy(payload)), range(2)))
    assert replies[0]['review']['id'] == replies[1]['review']['id'] and len(state.debug_sessions.sessions) == 1
    assert all(reply['offer']['state'] == 'started' for reply in replies)
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_ordinary_chat_confirmation_cannot_consume_a_test_help_offer(tmp_path, monkeypatch):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    message = imported(state, meta)
    sent = []
    monkeypatch.setattr(state.assistant, 'send', lambda cid, body: sent.append(body.text) or state.assistant.read(cid))
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        response = client.post('/api/mobile/messages', headers=headers(phone), json=dict(request_id='ordinary-answer',
            text='好', context_id=mobile.latest['context_id'], inherit_media=False))
        assert response.status_code == 202 and sent == ['好']
    assert state.assistant.read('shared-conversation')['messages'][-1]['test_help_offer']['state'] == 'pending'
    assert not state.debug_sessions.sessions and not state.pi_execution.jobs


def test_first_offer_continues_current_history_review_without_resetting_photos(tmp_path, monkeypatch):
    from test_guided_wiring_review import _start
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    owner = state.debug_sessions
    debug_id, _ = _start(owner)
    state.assistant.import_messages('shared-conversation', 'existing-review',
        [dict(id='existing-review', role='assistant', text='已收集照片。', round=0, session_id=debug_id)], 'legacy-debug')
    review = owner.sessions[debug_id]['wiring_review']
    review['slots']['pi_side_a'] = dict(capture_id='retained-photo', available=True, image_url='immutable-original',
                                      photo_acceptance=dict(capture_id='retained-photo', round=0, source='human'))
    review['reviews']['retained-wire'] = dict(decision='confirmed', source='human')
    original = deepcopy(review)
    monkeypatch.setattr(owner, 'action', lambda *args, **kwargs: pytest.fail('Continue must not restart an existing review'))
    message = imported(state, meta)
    assert message['test_help_offer']['reusable_review'] and message['test_help_offer']['review_id'] == review['id']
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        result = post(client, mobile, phone, message)
        assert result.status_code == 200, result.text
        assert result.json()['review']['id'] == original['id']
    assert owner.sessions[debug_id]['wiring_review'] == original and len(owner.sessions) == 1
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_first_continue_projection_requires_current_uncleared_history_and_full_context(tmp_path, monkeypatch):
    from test_guided_wiring_review import _start
    for source in ('current-job', 'cleared-job', 'foreign-history', 'changed-code'):
        app, state, mobile, phone, published, meta = fixture(tmp_path / source)
        owner = state.debug_sessions
        debug_id, _ = _start(owner)
        record = state.assistant._load('shared-conversation')
        if source != 'foreign-history':
            record['jobs'].append(dict(id='existing-debug', epoch=0, status='complete', debug_session_id=debug_id))
        if source == 'cleared-job':
            record['cleared_debug_sessions'] = [debug_id]
        state.assistant._save(record)
        if source == 'changed-code':
            owner.sessions[debug_id]['context']['code'] += '\n# different frozen code'
        original = deepcopy(owner.sessions[debug_id]['wiring_review'])
        monkeypatch.setattr(owner, 'action', lambda *args, **kwargs: pytest.fail('A returned active case must not be reset'))
        message = imported(state, meta)
        assert message['test_help_offer']['reusable_review'] == (source == 'current-job')
        with TestClient(app, client=('192.168.1.8', 5000)) as client:
            result = post(client, mobile, phone, message)
            assert result.status_code == (200 if source == 'current-job' else 409), result.text
        assert owner.sessions[debug_id]['wiring_review'] == original and len(owner.sessions) == 1
        assert not state.design_service.bridge.calls and not state.pi_execution.jobs
