"""Shared chat orchestration with fake hardware/cloud and synthetic pixels only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.assistant import AssistantService
from app.assistant import SendRequest
from app.debug_sessions import DebugSessions
from test_shared_test_help import fixture, imported, headers, post
from test_guided_wiring_review import _capture_stub, _cloud, _answer, _with_confirmations
from test_mobile_wiring_review import _upload


@pytest.fixture
def chat(tmp_path):
    app, state, mobile, phone, published, meta = fixture(tmp_path)
    _capture_stub(state.debug_sessions)
    message = imported(state, meta)
    start = state.mobile_service.test_help_action('shared-conversation',
        dict(op='start', message_id=message['id'], offer_id=meta['offer_id']))
    return app, state, mobile, phone, published, start['debug_session_id'], tmp_path


def current(state):
    return next(m for m in reversed(state.assistant.read('shared-conversation')['messages'])
                if m.get('wiring_flow', {}).get('current'))


def body(state, op, *, message=None, request_id=None, context=None, **fields):
    message = message or current(state)
    flow = message['wiring_flow']
    result = dict(request_id=request_id or 'chat-' + flow['event_id'] + '-' + op,
                  message_id=message['id'], flow_id=flow['flow_id'],
                  action=dict(op=op, review_id=flow['review_id'], revision=flow['revision'], **fields))
    if context is not None:
        result['context'] = context
    return result


def act(state, op, **fields):
    return state.assistant.wiring_flow_action('shared-conversation', body(state, op, **fields))


def photos(state):
    for role in ('pi_side_a', 'pi_side_b', 'component_header'):
        assert current(state)['wiring_flow']['role'] == role
        act(state, 'capture', role=role)


def analysed(state, sid):
    photos(state)
    context = state.debug_sessions.sessions[sid]['context']
    _cloud(state, _answer(context))
    act(state, 'analyse')
    state.debug_sessions.tick(sid)
    return context


def test_start_is_true_persistent_chat_without_capture_or_model(chat):
    app, state, mobile, phone, published, sid, path = chat
    message = current(state)
    assert message['role'] == 'assistant'
    assert message['wiring_flow']['kind'] == 'photo_request'
    assert message['wiring_flow']['role'] == 'pi_side_a'
    assert message['wiring_flow']['actions'] == ['capture']
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs
    assert state.debug_sessions.sessions[sid]['evidence'] == []
    before = state.assistant.read('shared-conversation')['messages']
    state.assistant = AssistantService(state, path / 'assistant')
    assert state.assistant.read('shared-conversation')['messages'] == before
    assert state.assistant.read('shared-conversation')['messages'] == before
    assert not state.design_service.bridge.calls and state.debug_sessions.sessions[sid]['evidence'] == []


def test_three_submitted_photos_select_pixels_and_advance_once(chat):
    app, state, mobile, phone, published, sid, path = chat
    original_context = deepcopy(state.debug_sessions.sessions[sid]['context'])
    first = current(state)
    request = body(state, 'capture', role='pi_side_a')
    result = state.assistant.wiring_flow_action('shared-conversation', request)
    slot = result['debug_session']['wiring_review']['slots']['pi_side_a']
    assert slot['photo_acceptance']['source'] == 'human'
    assert slot['photo_acceptance']['capture_id'] == slot['capture_id']
    assert slot['photo_acceptance']['sha256'] == slot['sha256']
    assert state.assistant.wiring_flow_action('shared-conversation', request)['debug_session']['wiring_review'] == result['debug_session']['wiring_review']
    assert current(state)['wiring_flow']['role'] == 'pi_side_b'
    for role in ('pi_side_b', 'component_header'):
        act(state, 'capture', role=role)
    record = state.assistant.read('shared-conversation')
    photo_messages = [m for m in record['messages'] if m.get('wiring_flow', {}).get('kind') == 'photo']
    assert len(photo_messages) == 3
    assert all(m['role'] == 'user' and not m['wiring_flow']['actions'] for m in photo_messages)
    assert current(state)['wiring_flow']['kind'] == 'analysis_request'
    assert state.debug_sessions.sessions[sid]['context'] == original_context
    assert not state.debug_sessions.sessions[sid]['wiring_review']['reviews']
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs
    with pytest.raises(Exception, match='stale_wiring_dialogue'):
        state.assistant.wiring_flow_action('shared-conversation', body(state, 'capture', message=first,
            request_id='old-question-new-request', role='pi_side_a'))


def test_exact_role_identity_epoch_and_forged_import_are_rejected(chat):
    app, state, mobile, phone, published, sid, path = chat
    request = body(state, 'capture', role='pi_side_b')
    with pytest.raises(Exception, match='wiring_dialogue_role_mismatch'):
        state.assistant.wiring_flow_action('shared-conversation', request)
    assert not state.debug_sessions.sessions[sid]['evidence']
    source = current(state)
    before = state.assistant.read('shared-conversation')['total']
    forged = state.assistant.import_messages('shared-conversation', 'forged-flow',
        [dict(id='forged', role='assistant', text='fake', wiring_flow=source['wiring_flow'])], 'legacy-debug')
    assert forged['total'] == before and not any(m['text'] == 'fake' for m in forged['messages'])
    state.assistant.reset_context('shared-conversation', 'clear')
    with pytest.raises(Exception, match='stale_wiring_dialogue'):
        state.assistant.wiring_flow_action('shared-conversation', body(state, 'capture', message=source, role='pi_side_a'))
    assert not state.debug_sessions.sessions[sid]['evidence']


def test_analysis_then_one_wire_decisions_preserve_human_authority(chat):
    app, state, mobile, phone, published, sid, path = chat
    context = analysed(state, sid)
    assert current(state)['wiring_flow']['kind'] == 'wire_review'
    assert '照片分析完成' in current(state)['text']
    assert len(state.design_service.bridge.calls) == 1
    assert not state.pi_execution.jobs
    rows = state.debug_sessions.sessions[sid]['wiring_review']['results']
    confirmations = deepcopy(context['guide_confirmations'])
    for row in rows:
        message = current(state)
        assert message['wiring_flow']['wire_id'] == row['wire_id']
        wire = next(w for w in context['project']['wiring'] if w['id'] == row['wire_id'])
        confirmations[wire['id']] = dict(signature='|'.join(str(wire[k]) for k in
            ('componentId', 'componentPin', 'boardPin', 'connectionKind')), at='2026-10-04T12:00:00Z')
        context = _with_confirmations(context, confirmations)
        act(state, 'review', wire_id=row['wire_id'], decision='confirmed', context=context)
    assert current(state)['wiring_flow']['kind'] == 'complete'
    assert '4／4' in current(state)['text']
    assert state.debug_sessions.sessions[sid]['context']['guide_confirmations'] == confirmations
    assert all(v['source'] == 'human' for v in state.debug_sessions.sessions[sid]['wiring_review']['reviews'].values())
    decisions = [m for m in state.assistant.read('shared-conversation')['messages']
                 if m.get('wiring_flow', {}).get('kind') == 'human_decision']
    assert len(decisions) == 4 and all(m['role'] == 'user' and not m['wiring_flow']['actions'] for m in decisions)
    assert len(state.design_service.bridge.calls) == 1 and not state.pi_execution.jobs


def test_retake_and_crop_only_change_selected_pixels(chat):
    app, state, mobile, phone, published, sid, path = chat
    analysed(state, sid)
    before = deepcopy(state.debug_sessions.sessions[sid]['wiring_review']['slots'])
    act(state, 'capture', role='pi_side_b')
    slots = state.debug_sessions.sessions[sid]['wiring_review']['slots']
    assert slots['pi_side_a'] == before['pi_side_a'] and slots['component_header'] == before['component_header']
    assert slots['pi_side_b']['capture_id'] != before['pi_side_b']['capture_id']
    assert current(state)['wiring_flow']['kind'] == 'analysis_request'
    act(state, 'crop', role='pi_side_b', crop=[.1, .1, .9, .9])
    assert slots['pi_side_b']['crop'] == [.1, .1, .9, .9]
    assert slots['pi_side_b']['photo_acceptance']['capture_id'] == slots['pi_side_b']['capture_id']
    assert len(state.design_service.bridge.calls) == 1
    assert not state.pi_execution.jobs


def test_phone_chat_capture_shares_history_but_not_analysis_or_decisions(chat):
    app, state, mobile, phone, published, sid, path = chat
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        message = current(state)
        request = body(state, 'capture', role='pi_side_a')
        asset = _upload(client, phone, 'chat-phone-photo')
        payload = dict(action=request['action'], asset_id=asset['id'], dialogue={k: request[k] for k in ('message_id', 'flow_id', 'request_id')})
        response = client.post('/api/mobile/wiring-review', headers=headers(phone), json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        slot = result['review']['slots']['pi_side_a']
        assert slot['photo_acceptance']['source'] == 'human'
        assert any(m.get('wiring_flow', {}).get('kind') == 'photo' for m in result['conversation']['messages'])
        photo = next(m for m in result['conversation']['messages'] if m.get('wiring_flow', {}).get('kind') == 'photo')
        assert photo['wiring_flow']['image_url'].startswith('/api/mobile/wiring-review/evidence/')
        assert client.get(photo['wiring_flow']['image_url'], headers=headers(phone)).status_code == 200
        assert client.post('/api/mobile/wiring-review', headers=headers(phone), json=payload).status_code == 200
        for op in ('analyse', 'review', 'changed'):
            request = body(state, op, **({'wire_id': 'anything', 'decision': 'confirmed'} if op == 'review' else {}))
            response = client.post('/api/mobile/wiring-review', headers=headers(phone), json=dict(action=request['action'],
                dialogue={k: request[k] for k in ('message_id', 'flow_id', 'request_id')}))
            assert response.status_code == 403
        assert len(state.debug_sessions.sessions[sid]['evidence']) == 1
        assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_two_devices_only_commit_one_distinct_photo_submission(chat):
    app, state, mobile, phone, published, sid, path = chat
    request = body(state, 'capture', role='pi_side_a')
    alternative = {**request, 'request_id': 'second-device'}
    def send(payload):
        try:
            state.assistant.wiring_flow_action('shared-conversation', payload)
            return 'done'
        except Exception:
            return 'stale'
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(send, (request, alternative)))
    assert sorted(outcomes) == ['done', 'stale']
    assert len(state.debug_sessions.sessions[sid]['evidence']) == 1
    assert current(state)['wiring_flow']['role'] == 'pi_side_b'


def test_software_restart_keeps_chat_history_without_replaying_photos(chat):
    app, state, mobile, phone, published, sid, path = chat
    act(state, 'capture', role='pi_side_a')
    before = state.assistant.read('shared-conversation')['total']
    owner = state.debug_sessions
    state.debug_sessions = DebugSessions(state, store=owner.store, autostart=False)
    after = state.assistant.read('shared-conversation')
    assert after['total'] == before
    assert all(not m.get('wiring_flow', {}).get('can_act') for m in after['messages'])
    assert not state.debug_sessions.images
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_declared_wiring_change_starts_new_round_and_preserves_readonly_photos(chat):
    app, state, mobile, phone, published, sid, path = chat
    context = analysed(state, sid)
    before = deepcopy(state.debug_sessions.sessions[sid]['wiring_review'])
    affected = {w['id'] for w in context['project']['wiring'] if w['componentId'] == 'hc-sr04'}
    context = _with_confirmations(context, {k: v for k, v in context['guide_confirmations'].items() if k not in affected})
    act(state, 'changed', component_id='hc-sr04', scope='component', context=context)
    after = state.debug_sessions.sessions[sid]['wiring_review']
    assert after['round'] == before['round'] + 1
    assert not any(after['slots'].values()) and after['reviews'] == {} and after['results'] == []
    assert current(state)['wiring_flow']['kind'] == 'photo_request'
    assert current(state)['wiring_flow']['role'] == 'pi_side_a'
    record = state.assistant.read('shared-conversation')
    old_photos = [m for m in record['messages'] if m.get('wiring_flow', {}).get('kind') == 'photo']
    assert len(old_photos) == 3 and all(not m['wiring_flow']['can_act'] for m in old_photos)
    assert all(not e['current'] for e in state.debug_sessions.sessions[sid]['evidence'])
    assert len(state.design_service.bridge.calls) == 1 and not state.pi_execution.jobs


def test_analysis_error_is_a_message_without_unrequested_retry(chat):
    app, state, mobile, phone, published, sid, path = chat
    photos(state)
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic cloud error')
    state.design_service.bridge.generate = fail
    act(state, 'analyse')
    state.debug_sessions.tick(sid)
    message = current(state)
    assert message['wiring_flow']['kind'] == 'error'
    before = len(state.debug_sessions.sessions[sid]['wiring_dialogue']['events'])
    assert state.assistant.read('shared-conversation')
    assert len(state.debug_sessions.sessions[sid]['wiring_dialogue']['events']) == before
    assert not state.pi_execution.jobs


def test_normal_text_question_does_not_advance_guidance_or_inherit_old_media(chat, monkeypatch):
    app, state, mobile, phone, published, sid, path = chat
    before = deepcopy(state.debug_sessions.sessions[sid]['wiring_review'])
    prompt_id = current(state)['wiring_flow']['event_id']
    record = state.assistant._load('shared-conversation')
    record['active_media'] = dict(asset_ids=['old-unrelated-media'], capture_id=None, epoch=0, round=0)
    state.assistant._save(record)
    calls = []
    state.pi_deployer.snapshot = lambda: dict(connected=False, logs=[])
    def reply(prompt, schema, **kwargs):
        calls.append((prompt, kwargs))
        return dict(answer='請讓插接底部與出線顏色清楚入鏡。')
    state.design_service.bridge.generate = reply
    class ImmediateThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr('app.assistant.threading.Thread', ImmediateThread)
    body = SendRequest.model_validate(dict(request_id='ordinary-question', text='第一側要怎麼拍？', stage='guide',
        target='wiring', design=published['design'], context={**published['context'], 'debug_session_id': sid}, round=0))
    result = state.assistant.send('shared-conversation', body)
    assert result['jobs'][-1]['status'] == 'completed', result['jobs'][-1].get('error')
    assert result['messages'][-1]['text'] == '請讓插接底部與出線顏色清楚入鏡。'
    assert len(calls) == 1 and not calls[0][1].get('image_paths')
    assert current(state)['wiring_flow']['event_id'] == prompt_id
    assert state.debug_sessions.sessions[sid]['wiring_review'] == before
    assert not state.debug_sessions.sessions[sid]['evidence'] and not state.pi_execution.jobs


def test_summary_prioritises_different_and_uncertain_wires(chat):
    app, state, mobile, phone, published, sid, path = chat
    photos(state)
    context = state.debug_sessions.sessions[sid]['context']
    opinion = _answer(context)
    wires = [w for w in context['project']['wiring'] if w['componentId'] == 'hc-sr04']
    for view in opinion['views']:
        if view['role'] != 'component_header':
            view['connectors'][2]['wire_color']['name'] = 'orange'
        view['connectors'][3]['wire_color'] = dict(name='unknown', visibility='not_visible', evidence='Hidden colour')
    _cloud(state, opinion)
    act(state, 'analyse')
    state.debug_sessions.tick(sid)
    message = current(state)
    assert message['wiring_flow']['wire_id'] == wires[2]['id']
    assert '照片分析完成' in message['text'] and '不能判定接錯' in message['text']
    assert message['wiring_flow']['result']['diagnosis']['status'] == 'uncertain'
    assert '1 條異色' not in message['text']
    assert len(state.design_service.bridge.calls) == 1


def test_prepare_wiring_keeps_the_exact_chat_question_and_legacy_capture_stays_separate(chat):
    app, state, mobile, phone, published, sid, path = chat
    context = analysed(state, sid)
    question = current(state)
    state.debug_sessions.action(sid, 'prepare_wiring', 'prepare-current-flow', context=context)
    assert current(state)['wiring_flow'] == question['wiring_flow']
    # The ordinary session route still requires an explicit accept operation.
    review = state.debug_sessions.sessions[sid]['wiring_review']
    state.debug_sessions.action(sid, 'wiring_review', 'legacy-capture', context=context,
        wiring_review=dict(op='capture', role='pi_side_b', review_id=review['id'], revision=review['revision']))
    assert 'photo_acceptance' not in state.debug_sessions.sessions[sid]['wiring_review']['slots']['pi_side_b']
    assert len(state.design_service.bridge.calls) == 1 and not state.pi_execution.jobs


def test_desktop_flow_route_is_loopback_only_and_hidden_refs_are_bounded(chat):
    app, state, mobile, phone, published, sid, path = chat
    payload = body(state, 'capture', role='pi_side_a')
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert client.post('/api/assistant/conversations/shared-conversation/wiring-flow', json=payload).status_code == 403
    with TestClient(app, client=('127.0.0.1', 5000)) as client:
        bad = {**payload, 'message_id': 'does-not-exist'}
        assert client.post('/api/assistant/conversations/shared-conversation/wiring-flow', json=bad).status_code == 409
        good = client.post('/api/assistant/conversations/shared-conversation/wiring-flow', json=payload)
        assert good.status_code == 200, good.text
        assert good.json()['debug_session_id'] == sid
    assert len(state.debug_sessions.sessions[sid]['evidence']) == 1
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_continue_keeps_exact_question_photos_and_history(chat):
    app, state, mobile, phone, published, sid, path = chat
    act(state, 'capture', role='pi_side_a')
    before = state.assistant.read('shared-conversation')
    invitation = next(m for m in before['messages'] if m.get('test_help_offer'))
    review = deepcopy(state.debug_sessions.sessions[sid]['wiring_review'])
    result = mobile.test_help_action('shared-conversation', dict(op='start', message_id=invitation['id'],
        offer_id=invitation['test_help_offer']['offer_id']))
    assert [m for m in result['conversation']['messages'] if m.get('wiring_flow')] == [
        m for m in before['messages'] if m.get('wiring_flow')]
    assert state.debug_sessions.sessions[sid]['wiring_review'] == review
    assert len(state.debug_sessions.sessions) == 1 and len(state.debug_sessions.sessions[sid]['evidence']) == 1
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_unsure_withdraws_only_current_wire_and_records_the_human_answer(chat):
    app, state, mobile, phone, published, sid, path = chat
    context = analysed(state, sid)
    question = current(state)
    wire_id = question['wiring_flow']['wire_id']
    confirmations = {k: v for k, v in context['guide_confirmations'].items() if k != wire_id}
    changed = _with_confirmations(context, confirmations)
    state.debug_sessions.action(sid, 'prepare_wiring', 'prepare-unsure', context=context)
    act(state, 'review', wire_id=wire_id, decision='unsure', context=changed)
    session = state.debug_sessions.sessions[sid]
    assert session['context']['guide_confirmations'] == confirmations
    assert session['wiring_review']['reviews'][wire_id]['decision'] == 'unsure'
    answer = next(m for m in state.assistant.read('shared-conversation')['messages']
                  if m.get('wiring_flow', {}).get('kind') == 'human_decision')
    assert answer['role'] == 'user' and answer['text'] == '仍無法確定'
    assert current(state)['wiring_flow']['wire_id'] != wire_id
    assert not state.pi_execution.jobs and len(state.design_service.bridge.calls) == 1


def test_lost_human_ack_is_recovered_by_exact_readonly_receipt(chat):
    app, state, mobile, phone, published, sid, path = chat
    context = analysed(state, sid)
    before = deepcopy(state.debug_sessions.sessions[sid]['binding'])
    wire_id = current(state)['wiring_flow']['wire_id']
    after = _with_confirmations(context, {k: v for k, v in context['guide_confirmations'].items() if k != wire_id})
    request = body(state, 'review', wire_id=wire_id, decision='unsure', context=after, request_id='lost-human-ack')
    state.assistant.wiring_flow_action('shared-conversation', request)  # Deliberately discard the acknowledgement.
    with TestClient(app, client=('127.0.0.1', 5000)) as client:
        response = client.get('/api/assistant/conversations/shared-conversation/wiring-flow/receipts/lost-human-ack')
        assert response.status_code == 200
        recovered = response.json()
    assert recovered['receipt_state'] == 'done'
    receipt = recovered['guide_receipt']
    assert receipt['request_id'] == 'lost-human-ack' and receipt['op'] == 'review'
    assert receipt['before_binding'] == before
    assert receipt['after_binding'] == state.debug_sessions.sessions[sid]['binding']
    assert receipt['guide_confirmations'] == after['guide_confirmations'] and receipt['test_keys'] == after['test_keys']
    assert receipt['wire_id'] == wire_id and receipt['decision'] == 'unsure'
    count = len(state.debug_sessions.sessions[sid]['wiring_dialogue']['events'])
    retry = state.assistant.wiring_flow_action('shared-conversation', request)
    assert retry['request_id'] == 'lost-human-ack' and retry['guide_receipt'] == receipt
    assert len(state.debug_sessions.sessions[sid]['wiring_dialogue']['events']) == count
    assert len(state.design_service.bridge.calls) == 1 and not state.pi_execution.jobs


def test_receipt_reads_never_promote_photo_or_old_foreign_scope(chat):
    app, state, mobile, phone, published, sid, path = chat
    request = body(state, 'capture', role='pi_side_a', request_id='photo-only')
    response = state.assistant.wiring_flow_action('shared-conversation', request)
    assert response['guide_receipt'] is None
    assert state.assistant.wiring_flow_receipt('shared-conversation', 'photo-only')['guide_receipt'] is None
    flow = state.debug_sessions.sessions[sid]['wiring_dialogue']
    flow['receipts']['in-flight'] = dict(signature='synthetic', state='pending')
    state.debug_sessions._save()
    assert state.assistant.wiring_flow_receipt('shared-conversation', 'in-flight')['receipt_state'] == 'pending'
    assert state.assistant.wiring_flow_receipt('shared-conversation', 'unknown')['receipt_state'] == 'missing'
    state.assistant.create('foreign-conversation', project_id='foreign-project')
    assert state.assistant.wiring_flow_receipt('foreign-conversation', 'photo-only')['receipt_state'] == 'missing'
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert client.get('/api/assistant/conversations/shared-conversation/wiring-flow/receipts/photo-only').status_code == 403
    state.assistant.reset_context('shared-conversation', 'clear')
    assert state.assistant.wiring_flow_receipt('shared-conversation', 'photo-only')['receipt_state'] == 'missing'
    assert len(state.debug_sessions.sessions[sid]['evidence']) == 1
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_changed_round_receipt_is_explicit_and_restart_cannot_replay_it(chat):
    app, state, mobile, phone, published, sid, path = chat
    context = analysed(state, sid)
    old_round = state.debug_sessions.sessions[sid]['wiring_review']['round']
    affected = {w['id'] for w in context['project']['wiring'] if w['componentId'] == 'hc-sr04'}
    after = _with_confirmations(context, {k: v for k, v in context['guide_confirmations'].items() if k not in affected})
    request = body(state, 'changed', scope='component', component_id='hc-sr04', context=after,
        request_id='human-changed-wiring')
    reply = state.assistant.wiring_flow_action('shared-conversation', request)
    receipt = reply['guide_receipt']
    assert receipt['op'] == 'changed' and receipt['decision'] is None
    assert receipt['round'] == old_round + 1 and receipt['guide_confirmations'] == after['guide_confirmations']
    assert receipt['context_fingerprint'] and receipt['context_epoch'] == 0
    owner = state.debug_sessions
    state.debug_sessions = DebugSessions(state, store=owner.store, autostart=False)
    assert state.assistant.wiring_flow_receipt('shared-conversation', 'human-changed-wiring')['receipt_state'] == 'missing'
    assert not state.debug_sessions.images and not state.pi_execution.jobs
    assert len(state.design_service.bridge.calls) == 1
