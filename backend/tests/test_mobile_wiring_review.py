"""Paired conversational photo collection, fake cloud/Pi and synthetic pixels."""
from copy import deepcopy
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.api.mobile import router
from app.mobile import MobileService
from app.mobile_https import phone_route
from app.capture.phone import PhoneFrameSource
from test_debug_sessions import setup as debug_setup
from test_guided_wiring_review import _start, _cloud, _answer
from test_mobile import Clock, RTC, Analyzer


class LinkedAssistant:
    def __init__(self, debug_id, project_id):
        self.record = dict(id='phone-conversation', project_id=project_id, context_epoch=0,
                           messages=[dict(session_id=debug_id, epoch=0)], jobs=[])

    def read(self, cid, before=None, limit=50):
        assert cid == self.record['id']
        return deepcopy(self.record)


@pytest.fixture
def review_setup(tmp_path):
    debug, state = debug_setup.__wrapped__(tmp_path)
    debug_id, context = _start(debug)
    state.debug_sessions = debug
    state.mobile_photo = Analyzer()
    state.assistant = LinkedAssistant(debug_id, context['project']['id'])
    clock = Clock()
    mobile = MobileService(state, tmp_path / 'mobile', clock=clock, wall=clock.wall, rtc_factory=RTC)
    published = dict(conversation_id='phone-conversation', title='Review project', stage='guide', target='wiring', round=0,
        design=dict(prompt='Inspect wiring', component_ids=context['project']['component_ids'], locale='zh-TW',
                    current=context['project'], model='fake', effort='low'),
        context=dict(debug_context={k: deepcopy(context[k]) for k in ('code', 'guide_confirmations', 'test_keys', 'guide_run')}))
    mobile.publish_context(published)
    pairing = mobile.create_pairing('phone-conversation', 'http://192.168.1.5:8100')
    phone = mobile.pair(pairing['code'], 'Test phone')
    app = FastAPI()
    app.state.mobile_service = mobile
    app.state.assistant = state.assistant
    app.include_router(router)
    return app, mobile, phone, debug, debug_id, context, published


def _headers(phone):
    return {'Authorization': 'Bearer ' + phone['token']}


def _pixels(color='red'):
    data = BytesIO()
    Image.new('RGB', (96, 72), color).save(data, 'JPEG')
    return data.getvalue()


def _upload(client, phone, name, color='red'):
    response = client.post('/api/mobile/assets', headers=_headers(phone), data={'upload_id': name},
                           files={'file': ('photo.jpg', _pixels(color), 'image/jpeg')})
    assert response.status_code == 200
    return response.json()


def _get(client, phone):
    response = client.get('/api/mobile/wiring-review', headers=_headers(phone))
    assert response.status_code == 200
    return response.json()


def _action(client, phone, op, **fields):
    current = _get(client, phone)['review']
    asset_id = fields.pop('asset_id', None)
    payload = dict(action=dict(op=op, review_id=current['id'], revision=current['revision'], **fields))
    if asset_id is not None:
        payload['asset_id'] = asset_id
    return client.post('/api/mobile/wiring-review', headers=_headers(phone), json=payload)


def _capture(client, phone, role, upload_name=None):
    asset = _upload(client, phone, upload_name or role)
    response = _action(client, phone, 'capture', role=role, asset_id=asset['id'])
    assert response.status_code == 200, response.text
    return response.json()['review']['slots'][role]


def _accept(client, phone, role):
    slot = _get(client, phone)['review']['slots'][role]
    response = _action(client, phone, 'accept_photo', role=role, capture_id=slot['capture_id'], sha256=slot['sha256'])
    assert response.status_code == 200, response.text
    return response.json()


def test_phone_route_whitelist_exposes_only_paired_review_operations():
    assert phone_route('/api/mobile/wiring-review', 'GET')
    assert phone_route('/api/mobile/wiring-review', 'POST')
    assert phone_route('/api/mobile/wiring-review/evidence/capture-1', 'GET')
    assert not phone_route('/api/mobile/wiring-review/evidence/capture-1', 'POST')
    assert not phone_route('/api/debug/sessions/anything/actions', 'POST')
    assert not phone_route('/api/mobile/wiring-review/evidence/../capture', 'GET')


def test_pairing_resolves_linked_review_without_context_or_session_id_changes(review_setup):
    app, mobile, phone, debug, debug_id, context, published = review_setup
    original_context_id = mobile.latest['context_id']
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert client.get('/api/mobile/wiring-review').status_code == 403
        snapshot = _get(client, phone)
        assert snapshot['review']['photo_flow_version'] == 2 and snapshot['can_act']
        assert 'binding' not in snapshot and 'jobs' not in snapshot and 'context' not in snapshot
        assert snapshot['review']['component_id'] == 'hc-sr04'
        mobile.state.assistant.record['messages'] = []
        assert _get(client, phone) == dict(review=None, can_act=False)
    assert mobile.latest['context_id'] == original_context_id
    assert debug.sessions[debug_id]['context'] == context


def test_phone_upload_select_next_and_analysis_are_separate_shared_actions(review_setup, monkeypatch):
    app, mobile, phone, debug, debug_id, context, published = review_setup
    original_context_id = mobile.latest['context_id']
    sid = phone['session_id']
    generation = asyncio.run(mobile.start_stream(sid))['generation']
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        first = _capture(client, phone, 'pi_side_a')
        assert first['source'] == 'phone_upload' and 'camera_id' not in first and 'photo_acceptance' not in first
        assert first['crop'] is None and first['crop_source'] == 'none'
        asset_id = first['provenance']['asset_id']
        assert debug.images[debug_id][first['capture_id']] == mobile.assets.path(asset_id).read_bytes()
        original = mobile.assets.root / asset_id / 'original.bin'
        assert original.read_bytes() == _pixels()
        assert client.get(first['image_url'], headers=_headers(phone)).status_code == 200
        assert client.get(first['image_url']).status_code == 403
        accepted = _accept(client, phone, 'pi_side_a')['review']['slots']['pi_side_a']['photo_acceptance']
        assert accepted['source'] == 'human' and accepted['round'] == 1
        assert debug.get(debug_id)['wiring_review']['slots']['pi_side_a']['photo_acceptance'] == accepted
        _capture(client, phone, 'pi_side_b')
        _capture(client, phone, 'component_header')
        assert _action(client, phone, 'analyse').status_code == 409
        _accept(client, phone, 'pi_side_b')
        _accept(client, phone, 'component_header')
        assert not mobile.state.design_service.bridge.calls and not mobile.state.pi_execution.jobs
        _cloud(mobile.state, _answer(context))
        assert _action(client, phone, 'analyse').status_code == 200
        assert not _get(client, phone)['can_act']
        assert _action(client, phone, 'analyse').status_code == 409
        # Slow cloud work must not take the native receipt lock in either POC
        # stage. This uses synthetic photos and a fake model, never hardware.
        bridge = mobile.state.design_service.bridge
        generate = bridge.generate
        stages = [(threading.Event(), threading.Event()) for _ in range(2)]
        call_index = 0

        def slow_generate(*args, **kwargs):
            nonlocal call_index
            entered, release = stages[call_index]
            call_index += 1
            entered.set()
            assert release.wait(3)
            return generate(*args, **kwargs)

        monkeypatch.setattr(bridge, 'generate', slow_generate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            analysis = pool.submit(debug.tick, debug_id)
            try:
                for seq, (entered, release) in enumerate(stages, 1):
                    assert entered.wait(2)
                    pool.submit(mobile.on_receive, sid, generation, seq, mobile.clock(), mobile.wall(), (960, 540)).result(timeout=.5)
                    release.set()
            finally:
                for _, release in stages:
                    release.set()
            analysis.result(timeout=2)
        assert _get(client, phone)['review']['status'] == 'ready'
    assert len(mobile.state.design_service.bridge.calls) == 2
    receipt = debug.get(debug_id)['wiring_review']['model_receipt']
    assert [stage['stage'] for stage in receipt['stages']] == ['exit_inventory', 'pin_review']
    assert not mobile.state.pi_execution.jobs
    assert debug.sessions[debug_id]['context']['guide_confirmations'] == context['guide_confirmations']
    assert mobile.latest['context_id'] == original_context_id
    debug.action(debug_id, 'stop', 'explicit-stop', context=context)
    stream = mobile.snapshot(sid)['stream']
    assert stream['active'] and stream['generation'] == generation and stream['received_frames'] == 2
    assert not mobile.rtc.closed


def test_phone_cannot_confirm_wires_change_round_or_import_another_pairings_asset(review_setup):
    app, mobile, phone, debug, debug_id, context, published = review_setup
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        asset = _upload(client, phone, 'first-phone')
        pairing = mobile.create_pairing('phone-conversation', 'http://192.168.1.5:8100')
        other = mobile.pair(pairing['code'], 'Second phone')
        assert _action(client, other, 'capture', role='pi_side_a', asset_id=asset['id']).status_code == 403
        assert _action(client, phone, 'review', wire_id=context['project']['wiring'][0]['id'], decision='confirmed').status_code == 403
        assert _action(client, phone, 'changed', component_id='hc-sr04').status_code == 403
        assert _action(client, phone, 'start', component_id='hc-sr04').status_code == 403
        assert client.post('/api/mobile/wiring-review', headers=_headers(phone), json={'session_id': debug_id,
            'action': {'op': 'capture', 'review_id': 'random', 'revision': 1, 'role': 'pi_side_a'}, 'asset_id': asset['id']}).status_code == 422
    assert not debug.get(debug_id)['wiring_review']['slots']['pi_side_a']


def test_retake_and_context_change_reject_old_selection_and_evidence(review_setup):
    app, mobile, phone, debug, debug_id, context, published = review_setup
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        first = _capture(client, phone, 'pi_side_a')
        _accept(client, phone, 'pi_side_a')
        assert _action(client, phone, 'crop', role='pi_side_a', crop=[.1, .1, .9, .9]).status_code == 200
        assert _get(client, phone)['review']['slots']['pi_side_a']['photo_acceptance']
        next_photo = _capture(client, phone, 'pi_side_a', 'retake')
        assert not next_photo.get('photo_acceptance')
        assert client.get(first['image_url'], headers=_headers(phone)).status_code == 404
        response = _action(client, phone, 'accept_photo', role='pi_side_a', capture_id=first['capture_id'], sha256=first['sha256'])
        assert response.status_code == 409
        updated = deepcopy(published)
        updated['round'] += 1
        mobile.publish_context(updated)
        assert _get(client, phone) == dict(review=None, can_act=False)
        assert client.get(next_photo['image_url'], headers=_headers(phone)).status_code == 409


@pytest.mark.parametrize('mutation', ['context', 'camera', 'cloud_reply'])
def test_import_rechecks_guards_after_image_decode_before_commit(review_setup, monkeypatch, mutation):
    app, mobile, phone, debug, debug_id, context, published = review_setup
    import app.guided_wiring_review as module
    original_decode = module._decode
    def change_context(raw):
        frame = original_decode(raw)
        if mutation == 'context':
            updated = deepcopy(published)
            updated['round'] += 1
            mobile.publish_context(updated)
        elif mutation == 'camera':
            mobile.state.source = PhoneFrameSource(phone['session_id'], 2, [1920, 1080])
            mobile.state.config.camera.source = 'phone'
        else:
            debug.sessions[debug_id]['phase'] = 'replying'
        return frame
    monkeypatch.setattr(module, '_decode', change_context)
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        asset = _upload(client, phone, 'racing-photo')
        assert _action(client, phone, 'capture', role='pi_side_a', asset_id=asset['id']).status_code == 409
    assert debug.get(debug_id)['wiring_review']['slots']['pi_side_a'] is None
    assert debug.images[debug_id] == {}
    assert debug.get(debug_id)['budget']['captures'] == 0


def test_stopped_phone_publisher_still_collects_without_live_frames_or_pose_gate(review_setup):
    import asyncio
    app, mobile, phone, debug, debug_id, context, published = review_setup
    source = PhoneFrameSource(phone['session_id'], 1, [1920, 1080])
    mobile.state.source = source
    mobile.state.config.camera.source = 'phone'
    debug.sessions[debug_id]['camera'] = debug._camera()
    old_camera = deepcopy(debug.sessions[debug_id]['camera'])
    asyncio.run(mobile.start_stream(phone['session_id']))
    asyncio.run(mobile.stop_stream(phone['session_id']))
    assert mobile.state.source is source and debug._camera() == old_camera
    assert not mobile.snapshot(phone['session_id'])['stream']['can_capture']
    assert source.read() is None
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        assert _get(client, phone)['can_act']
        _capture(client, phone, 'pi_side_a')
        _accept(client, phone, 'pi_side_a')
        assert _get(client, phone)['can_act']
    assert debug.sessions[debug_id]['status'] == 'awaiting_capture'
    assert not mobile.state.design_service.bridge.calls and not mobile.state.pi_execution.jobs


def test_actual_camera_selection_change_disables_collection_without_auto_model_calls(review_setup):
    app, mobile, phone, debug, debug_id, context, published = review_setup
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        slot = _capture(client, phone, 'pi_side_a')
        mobile.state.source = PhoneFrameSource(phone['session_id'], 2, [1920, 1080])
        mobile.state.config.camera.source = 'phone'
        assert _get(client, phone)['can_act'] is False
        assert _action(client, phone, 'accept_photo', role='pi_side_a', capture_id=slot['capture_id'], sha256=slot['sha256']).status_code == 409
    assert not mobile.state.design_service.bridge.calls and not mobile.state.pi_execution.jobs


@pytest.mark.parametrize('pending', ['replying', 'observing_photo', 'observing_tft', 'repair_analysing', 'chat_pending', 'capture_pending'])
def test_pending_chat_or_capture_blocks_all_phone_collection_actions(review_setup, pending):
    app, mobile, phone, debug, debug_id, context, published = review_setup
    with TestClient(app, client=('192.168.1.8', 5000)) as client:
        slot = _capture(client, phone, 'pi_side_a')
        asset = _upload(client, phone, 'next-photo')
        session = debug.sessions[debug_id]
        if pending.endswith('_pending'):
            session[pending] = True
        else:
            session['phase'] = pending
        assert _get(client, phone)['can_act'] is False
        assert _action(client, phone, 'accept_photo', role='pi_side_a', capture_id=slot['capture_id'], sha256=slot['sha256']).status_code == 409
        assert _action(client, phone, 'crop', role='pi_side_a', crop=[.1, .1, .9, .9]).status_code == 409
        assert _action(client, phone, 'capture', role='pi_side_a', asset_id=asset['id']).status_code == 409
        assert _action(client, phone, 'analyse').status_code == 409
    assert debug.get(debug_id)['wiring_review']['slots']['pi_side_a']['capture_id'] == slot['capture_id']
    assert not mobile.state.design_service.bridge.calls
