"""Workspace isolation and reconnect contracts; fake RTC, no hardware/AI."""
import asyncio
from copy import deepcopy
import json

import pytest
from fastapi import HTTPException

from test_mobile import context, feed, lock, preview, setup, upload


def test_other_workspace_does_not_revoke_preview_or_capture(setup, tmp_path):
    service, phone, clock = setup
    sid = phone['session_id']
    lock(service, phone, clock)
    other = service.publish_context(context('other'))
    assert service.snapshot(sid)['stream']['can_capture']
    feed(service, phone, clock, 4, clock.now + .1)
    assert service.snapshot(sid)['stream']['can_capture']
    assert service.desktop_snapshot(phone['conversation_id'])['context']['context_id'] == phone['context_id']
    assert service.snapshot(sid)['available_context']['context_id'] == other['context_id']
    ticket = service.capture_ticket(sid)
    asset = upload(service, phone, tmp_path)
    packet = asyncio.run(service.finalize_capture(sid, dict(ticket_id=ticket['ticket_id'], asset_id=asset['id'], request_id='capture')))
    assert packet['conversation_id'] == phone['conversation_id']
    assert service.view(sid)['capture_id'] == packet['capture_id']


def test_pairing_keeps_requested_workspace_after_other_tab_publish(setup):
    service, phone, _ = setup
    service.publish_context(context('other'))
    pairing = service.create_pairing(phone['conversation_id'], 'http://192.168.1.5:8100')
    paired = service.pair(pairing['code'], 'Second phone')
    assert paired['context_id'] == phone['context_id']
    assert paired['conversation_id'] == phone['conversation_id']


def test_same_workspace_plan_change_still_revokes_capture(setup):
    service, phone, clock = setup
    lock(service, phone, clock)
    service.publish_context(context(title='Updated wiring'))
    with pytest.raises(HTTPException, match='mobile_capture_not_locked'):
        service.capture_ticket(phone['session_id'])
    # An old paired plan cannot borrow the new plan's recognition.
    latest = service.current_context(phone['conversation_id'])
    service.accept_preview(phone['session_id'], 1, 4, clock.now, {'board_present': True}, (100, 100), latest['context_id'])
    assert not service.snapshot(phone['session_id'])['stream']['can_capture']


def test_rejoining_identical_context_keeps_rtc_and_ticket(setup):
    service, phone, clock = setup
    lock(service, phone, clock)
    ticket = service.capture_ticket(phone['session_id'])
    joined = asyncio.run(service.join(phone['session_id']))
    assert joined['context_id'] == phone['context_id']
    assert service.rtc.closed == [] and service.state.mobile_photo.released == []
    assert not service.tickets[ticket['ticket_id']]['invalid']
    assert joined['stream']['active'] and joined['stream']['generation'] == 1


def test_join_does_not_bind_a_different_destination_mid_handoff(setup):
    service, phone, _ = setup
    service.publish_context(context('other'))
    async def close(sid):
        service.publish_context(context('third'))
    service.rtc.close = close
    with pytest.raises(HTTPException, match='mobile_context_changed'):
        asyncio.run(service.join(phone['session_id']))
    assert service.sessions[phone['session_id']]['conversation_id'] == phone['conversation_id']


def paired_workspace(service):
    payload = context()
    payload['design']['current'] = {'id': 'project-A', 'revision': 3, 'wiring': [{'id': 'wire-1'}]}
    payload['design']['design_mode'] = 'free'
    payload['context'].update(workspace_project_id='project-A', project_version=3, preview_version=3,
        guide={'run': 2, 'index': 0, 'mode': 'camera', 'confirmed': {}},
        debug_context={'code': "print('project code')", 'wiring_target': {'wire_id': 'wire-1'},
                       'entry': {'panelOpen': False, 'runId': 'test-1'}},
        deployment={'exit_code': None, 'logs': [], 'captured_at': 1})
    published = service.publish_context(payload)
    invitation = service.create_pairing(payload['conversation_id'], 'http://192.168.1.5:8100')
    return payload, service.pair(invitation['code'], 'Workspace phone'), published


@pytest.mark.parametrize('change', ['wire', 'confirmation', 'guide_display', 'stage_target',
                                   'debug_runtime', 'deployment', 'draft_history', 'ai_settings'])
def test_daily_workspace_updates_adopt_snapshot_keep_stream_photo_and_chat(setup, tmp_path, change):
    service, _, clock = setup
    payload, phone, original = paired_workspace(service)
    sid = phone['session_id']
    lock(service, phone, clock)
    asset = upload(service, phone, tmp_path)
    captured = asyncio.run(service.finalize_capture(sid, dict(ticket_id=service.capture_ticket(sid)['ticket_id'],
        asset_id=asset['id'], request_id='saved-photo')))
    service.view(sid, {'capture_id': captured['capture_id'], 'wire_id': 'wire-1'})
    before_view = deepcopy(service.sessions[sid]['view'])
    for seq, stamp in ((4, 101.2), (5, 101.7), (6, 102.3)):
        feed(service, phone, clock, seq, stamp)
    old_ticket = service.capture_ticket(sid)
    generation = service.sessions[sid]['stream']['generation']
    changed = deepcopy(payload)
    if change == 'wire':
        changed['context']['guide']['index'] = 1
        changed['context']['debug_context']['wiring_target'] = {'component_id': 'hc-sr04', 'wire_id': 'wire-2'}
        changed['design']['workflow'] = {'stage': 'guide', 'active_wire': 'wire-2'}
    elif change == 'confirmation':
        changed['context']['guide']['confirmed'] = {'wire-1': {'signature': 'same-wire', 'at': 'later'}}
        changed['context']['debug_context']['guide_confirmations'] = changed['context']['guide']['confirmed']
    elif change == 'guide_display':
        changed['context']['guide'].update(mode='2d', phase='review', checks=['checked'], restored=True,
                                           inspection=True, inspectionSource='debug')
    elif change == 'stage_target':
        changed.update(stage='deploy', target='debug')
        changed['design']['workflow'] = {'stage': 'deploy', 'code_draft': 'temporary editor state'}
    elif change == 'debug_runtime':
        changed['context']['debug_context']['entry'].update(panelOpen=True, caseId='case-2',
                                                           runId='test-2', trialId='trial-2')
    elif change == 'deployment':
        changed['context']['deployment'].update(exit_code=1, logs=['new diagnostic output'], captured_at=42)
    elif change == 'draft_history':
        changed['design'].update(prompt='A new unsent draft', conversation=[{'role': 'user', 'text': 'Hello'}])
    else:
        changed['design'].update(locale='zh-TW', model='other-model', effort='high', expected_output_tokens=1024)

    updated = service.publish_context(changed)
    current = service.snapshot(sid)
    assert updated['context_id'] != original['context_id']
    assert current['context_id'] == current['available_context']['context_id'] == updated['context_id']
    assert current['workspace_id'] == current['available_context']['workspace_id'] == original['workspace_id']
    assert current['context_revision'] == 1 and phone['context_revision'] == 0
    assert current['stream']['active'] and current['stream']['generation'] == generation
    assert current['view'] == before_view
    assert service.rtc.closed == [] and service.state.mobile_photo.released == []
    assert not current['stream']['can_capture'] and current['stream']['recognition'] is None
    assert service.sessions[sid]['stream']['previous'] is None
    assert service.tickets[old_ticket['ticket_id']]['invalid']
    assert service.context(original['context_id']) == original, 'Old context remains an immutable snapshot'
    stored = json.loads((service.root / 'contexts' / (original['context_id']+'.json')).read_text(encoding='utf-8'))
    assert stored == original
    assert service.capture(captured['capture_id'], sid)['context_id'] == original['context_id']
    service.send(sid, dict(request_id='after-sync', text='Follow up', asset_ids=[], context_id=updated['context_id']))
    assert service.state.assistant.sent[-1][0] == phone['conversation_id']
    assert service.state.assistant.sent[-1][1]['design']['model'] == updated['design']['model']
    joined = asyncio.run(service.join(sid))
    assert joined['context_revision'] == 1 and joined['view'] == before_view
    assert service.rtc.closed == [], 'A same-workspace update no longer needs a destructive join'


@pytest.mark.parametrize('change', ['title', 'project', 'revision', 'components', 'design_mode',
                                   'workspace_project', 'project_version', 'preview_version', 'round', 'epoch', 'code'])
def test_true_workspace_changes_keep_frozen_binding_until_join(setup, change):
    service, _, clock = setup
    payload, phone, original = paired_workspace(service)
    sid = phone['session_id']
    lock(service, phone, clock)
    ticket = service.capture_ticket(sid)
    changed = deepcopy(payload)
    if change == 'title':
        changed['title'] = 'New project title'
    elif change == 'project':
        changed['design']['current']['id'] = 'project-B'
    elif change == 'revision':
        changed['design']['current']['revision'] += 1
    elif change == 'components':
        changed['design']['component_ids'] = ['mrd-tf240-8p-cs']
    elif change == 'design_mode':
        changed['design']['design_mode'] = 'fixed'
    elif change in ('workspace_project', 'project_version', 'preview_version'):
        key = 'workspace_project_id' if change == 'workspace_project' else change
        changed['context'][key] = 'project-B' if change == 'workspace_project' else 4
    elif change == 'round':
        changed['round'] += 1
    elif change == 'epoch':
        service.state.assistant.read = lambda *args: {'context_epoch': 1, 'messages': []}
    else:
        changed['context']['debug_context']['code'] = "print('different project code')"
    updated = service.publish_context(changed)
    current = service.snapshot(sid)
    assert updated['workspace_id'] != original['workspace_id']
    assert current['context_id'] == original['context_id'] and current['workspace_id'] == original['workspace_id']
    assert current['context_revision'] == 0
    assert current['available_context']['workspace_id'] == updated['workspace_id']
    assert current['stream']['active'] and not current['stream']['can_capture']
    assert service.tickets[ticket['ticket_id']]['invalid']
    with pytest.raises(HTTPException, match='mobile_capture_not_locked'):
        service.capture_ticket(sid)
    service.accept_preview(sid, 1, 4, clock.now, preview(), (100, 100), updated['context_id'])
    assert not service.snapshot(sid)['stream']['can_capture']
    joined = asyncio.run(service.join(sid))
    assert joined['context_id'] == updated['context_id'] and joined['workspace_id'] == updated['workspace_id']
    assert joined['context_revision'] == 1
    assert service.rtc.closed == [sid] and service.state.mobile_photo.released == [sid]


def test_soft_update_rejects_old_ticket_and_late_preview_without_revoking_new_lock(setup, tmp_path):
    service, phone, clock = setup
    sid = phone['session_id']
    lock(service, phone, clock)
    ticket = service.capture_ticket(sid)
    asset = upload(service, phone, tmp_path)
    changed = context(stage='deploy', target='debug')
    updated = service.publish_context(changed)
    phone = service.snapshot(sid)
    assert phone['workspace_id'] == updated['workspace_id']
    assert phone['context_revision'] == 1 and phone['stream']['generation'] == 1
    with pytest.raises(HTTPException, match='mobile_capture_ticket_expired'):
        asyncio.run(service.finalize_capture(sid, dict(ticket_id=ticket['ticket_id'], asset_id=asset['id'], request_id='late-upload')))
    assert service.state.mobile_photo.calls == []
    for seq, stamp in ((4, 101.2), (5, 101.7), (6, 102.3)):
        feed(service, phone, clock, seq, stamp)
    assert service.snapshot(sid)['stream']['can_capture']
    before = deepcopy(service.sessions[sid]['stream'])
    service.accept_preview(sid, 1, 99, clock.now, preview(offset=20), (100, 100), ticket['context_id'])
    assert service.sessions[sid]['stream'] == before
    assert service.capture_ticket(sid)['context_id'] == updated['context_id']


def test_same_snapshot_does_not_advance_revision_or_revoke_current_ticket(setup):
    service, phone, clock = setup
    sid = phone['session_id']
    lock(service, phone, clock)
    ticket = service.capture_ticket(sid)
    stream = deepcopy(service.sessions[sid]['stream'])
    clock.now += .1
    service.publish_context(context())
    current = service.snapshot(sid)
    assert current['context_id'] == phone['context_id'] and current['context_revision'] == 0
    assert service.sessions[sid]['stream'] == stream and not service.tickets[ticket['ticket_id']]['invalid']


def test_legacy_context_and_session_derive_workspace_without_mutating_archived_snapshot(setup):
    service, phone, _ = setup
    sid, identifier = phone['session_id'], phone['context_id']
    service.contexts[identifier].pop('workspace_id')
    service.sessions[sid].pop('workspace_id')
    service.sessions[sid].pop('context_revision')
    legacy = deepcopy(service.contexts[identifier])
    current = service.snapshot(sid)
    assert current['workspace_id'] == phone['workspace_id']
    assert current['context']['workspace_id'] == current['available_context']['workspace_id'] == phone['workspace_id']
    assert current['context_revision'] == 0 and service.context(identifier) == legacy
    invitation = service.create_pairing(phone['conversation_id'], 'http://192.168.1.5:8100')
    paired = service.pair(invitation['code'], 'Legacy context phone')
    assert paired['workspace_id'] == phone['workspace_id'] and paired['context_revision'] == 0
    updated = service.publish_context(context(stage='deploy'))
    current = service.snapshot(sid)
    assert current['context_id'] == updated['context_id'] and current['context_revision'] == 1
    assert current['workspace_id'] == phone['workspace_id'] and service.context(identifier) == legacy


def test_daily_update_retries_original_photo_message_with_one_durable_assistant_job(setup, tmp_path, monkeypatch):
    from app.assistant import AssistantService
    service, _, clock = setup
    payload, phone, original = paired_workspace(service)
    sid = phone['session_id']
    lock(service, phone, clock)
    analyze = service.state.mobile_photo.analyze
    service.state.mobile_photo.analyze = lambda *args: {**analyze(*args), 'project_id': 'project-A', 'project_revision': 3}
    asset = upload(service, phone, tmp_path)
    captured = asyncio.run(service.finalize_capture(sid, dict(ticket_id=service.capture_ticket(sid)['ticket_id'],
        asset_id=asset['id'], request_id='message-photo')))
    service.state.mobile_service = service
    assistant = AssistantService(service.state, tmp_path / 'assistant-history')
    # Exercise real durable request fingerprints without dispatching AI.
    monkeypatch.setattr(assistant, '_run', lambda *args: None)
    assistant.create(phone['conversation_id'], project_id='project-A')
    service.state.assistant = assistant
    body = dict(request_id='retry-original', text='Please explain this photo', asset_ids=[],
                capture_id=captured['capture_id'], inherit_media=False, context_id=original['context_id'])
    before = deepcopy(body)
    first = service.send(sid, body)
    changed = deepcopy(payload)
    changed.update(stage='deploy', target='debug')
    changed['design'].update(model='new-model', locale='zh-TW', conversation=[{'role': 'user', 'text': 'Later'}])
    changed['context']['guide']['index'] = 1
    updated = service.publish_context(changed)
    assert service.snapshot(sid)['context_id'] == updated['context_id'] != original['context_id']
    retried = service.send(sid, body)
    assert body == before and len(first['jobs']) == len(retried['jobs']) == 1
    assert len(retried['messages']) == 1
    job = assistant._load(phone['conversation_id'])['jobs'][0]
    assert job['id'] == first['jobs'][0]['id'] and job['request_id'] == body['request_id']
    assert job['request']['design']['model'] == original['design']['model']
    assert job['request']['design']['locale'] == original['design']['locale']
    assert job['request']['context']['mobile_context_id'] == original['context_id']
    assert job['request']['capture_id'] == captured['capture_id']
    assert job['request']['context']['guide'] == original['context']['guide']


@pytest.mark.parametrize('change', ['project', 'revision', 'round', 'epoch', 'code', 'conversation'])
def test_retry_cannot_cross_a_new_joined_workspace(setup, change):
    service, _, _ = setup
    payload, phone, original = paired_workspace(service)
    sid = phone['session_id']
    body = dict(request_id='old-outbox', text='Original question', asset_ids=[], context_id=original['context_id'])
    service.send(sid, body)
    changed = deepcopy(payload)
    if change in ('project', 'revision'):
        changed['design']['current'][('id' if change == 'project' else 'revision')] = 'project-B' if change == 'project' else 4
    elif change == 'round':
        changed['round'] += 1
    elif change == 'epoch':
        service.state.assistant.read = lambda *args: {'context_epoch': 1, 'messages': []}
    elif change == 'code':
        changed['context']['debug_context']['code'] = "print('different code')"
    else:
        changed['conversation_id'] = 'other-conversation'
    service.publish_context(changed)
    asyncio.run(service.join(sid))
    with pytest.raises(HTTPException, match='mobile_context_changed'):
        service.send(sid, body)
    assert len(service.state.assistant.sent) == 1
