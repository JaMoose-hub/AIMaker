"""Real review state machine; synthetic pixels and fake cloud/Pi, no hardware."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.debug_sessions import router
from app.debug_sessions import DebugSessions
from app.guided_wiring_review import ReviewOpinion, WiringReviewAction, supported_crop
from test_debug_sessions import setup, _context


def _capture_stub(service):
    old = service.capture_fn
    def capture(*args, **kwargs):
        _, metadata = old(*args, **kwargs)
        frame = np.full((480, 640, 3), metadata["seq"] * 10 % 255, dtype=np.uint8)
        ok, encoded = cv2.imencode('.jpg', frame)
        assert ok
        raw = encoded.tobytes()
        metadata['sha256'] = hashlib.sha256(raw).hexdigest()
        return {'overview': raw}, metadata
    service.capture_fn = capture


def _start(service, context=None, purpose="wiring_review"):
    context = context or _context()
    context.setdefault('locale', 'zh-TW')
    sid = service.create(context, "核對接線", purpose=purpose, initial_action="collect", request_id="start-session")["id"]
    service.action(sid, "wiring_review", "review-start", context=context,
                   wiring_review=dict(op="start", component_id="hc-sr04"))
    return sid, context


def _act(service, sid, context, op, **values):
    r = service.get(sid)["wiring_review"]
    return service.action(sid, "wiring_review", f'{op}-{r["revision"]}-{len(service.sessions[sid]["receipts"])}', context=context,
        wiring_review=dict(op=op, review_id=r["id"], revision=r["revision"], **values))


def _photos(service, sid, context):
    for role in ("pi_side_a", "pi_side_b", "component_header"):
        _act(service, sid, context, "capture", role=role)
        _accept(service, sid, context, role)


def _accept(service, sid, context, role):
    slot = service.get(sid)['wiring_review']['slots'][role]
    _act(service, sid, context, 'accept_photo', role=role, capture_id=slot['capture_id'], sha256=slot['sha256'])


def _answer(context, unknown=False, duplicate=False, component_id='hc-sr04'):
    wires = [w for w in context["project"]["wiring"] if w["componentId"] == component_id]
    views = []
    for role in ("pi_side_a", "pi_side_b", "component_header"):
        connectors = []
        for i, w in enumerate(wires):
            module = role == 'component_header'
            color = 'yellow' if duplicate and i in (0, 3) else ['yellow', 'red', 'blue', 'green', 'orange', 'purple', 'pink'][i]
            connectors.append(dict(id=f'c{i}', position=f'position {i}', contact='covers_pin',
                wire_color=dict(name=color, visibility='clear', evidence='Visible insulation'),
                evidence='Housing and wire exit visible', breadboard=None,
                pin_id=w['componentPin'] if module else None if unknown else w['boardPin'],
                pin_evidence='Visible label/orientation' if module or not unknown else 'Pin insertion hidden',
                box=[.1, .2, .2, .4]))
        views.append(dict(role=role, connectors=connectors, limitations='Visual clues only'))
    return dict(views=views)


def _cloud(state, answer, hook=None):
    bridge = state.design_service.bridge
    def generate(prompt, schema, **kwargs):
        bridge.calls.append((prompt, kwargs))
        bridge.images.append([Path(p).read_bytes() for p in kwargs['image_paths']])
        kwargs.get('response_metadata', {}).update(model='fake-model', elapsed_ms=1)
        if hook:
            hook()
        result = deepcopy(answer)
        roles = json.loads(prompt.split('Board pin references are naming references only: ')[-1])['requested_roles']
        result['views'] = [v for v in result['views'] if v['role'] in roles]
        return result
    bridge.generate = generate


def _analyse(service, state, sid, context, answer=None):
    for role, slot in service.get(sid)['wiring_review']['slots'].items():
        if slot and not slot.get('photo_acceptance'):
            _accept(service, sid, context, role)
    _cloud(state, answer or _answer(context))
    _act(service, sid, context, "analyse")
    service.tick(sid)
    return service.get(sid)["wiring_review"]


def _with_confirmations(context, records):
    changed = deepcopy(context)
    changed['guide_confirmations'] = deepcopy(records)
    changed['test_keys'] = {}
    p = changed['project']
    for cid in p['component_ids']:
        wires = [w for w in p['wiring'] if w['componentId'] == cid]
        rows = [["|".join(str(w[k]) for k in ('componentId', 'componentPin', 'boardPin', 'connectionKind')),
                 records.get(w['id'], {}).get('at')] for w in wires]
        changed['test_keys'][cid] = json.dumps([p['id'], p['revision'], changed['guide_run'], p['catalog_version'],
            p['profile_versions'][cid], rows], ensure_ascii=False, separators=(',', ':'))
    return changed


@pytest.mark.parametrize('purpose', ['wiring_review', 'debug'])
def test_shared_entry_collects_without_cloud_or_hardware(setup, purpose):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service, purpose=purpose)
    service.tick(sid)
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs
    _photos(service, sid, context)
    result = _analyse(service, state, sid, context)
    assert result['status'] == 'ready' and len(result['results']) == 4
    assert len(state.design_service.bridge.calls) == 1
    assert len(state.design_service.bridge.images[0]) == 3
    assert all(r['comparison'] == 'similar' for r in result['results'])
    assert result['reviews'] == {} and all(r['authority'] == 'visual_advisory' for r in result['results'])
    assert service.sessions[sid]['context']['guide_confirmations'] == context['guide_confirmations']
    assert not state.pi_execution.jobs and not state.component_tests.actions


def test_photo_acceptance_is_shared_exact_source_and_not_wiring_confirmation(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    for role in ('pi_side_a', 'pi_side_b', 'component_header'):
        _act(service, sid, context, 'capture', role=role)
    before = deepcopy(service.sessions[sid]['context'])
    with pytest.raises(ValueError, match='wiring_review_photos_not_accepted'):
        _act(service, sid, context, 'analyse')
    first = service.get(sid)['wiring_review']['slots']['pi_side_a']
    with pytest.raises(ValueError, match='stale_wiring_review_photo'):
        _act(service, sid, context, 'accept_photo', role='pi_side_a', capture_id=first['capture_id'], sha256='0'*64)
    _accept(service, sid, context, 'pi_side_a')
    accepted = service.get(sid)['wiring_review']['slots']['pi_side_a']['photo_acceptance']
    assert accepted['source'] == 'human' and accepted['round'] == 1
    assert accepted['capture_id'] == first['capture_id'] and accepted['sha256'] == first['sha256']
    _act(service, sid, context, 'crop', role='pi_side_a', crop=[.1, .1, .9, .9])
    assert service.get(sid)['wiring_review']['slots']['pi_side_a']['photo_acceptance'] == accepted
    _act(service, sid, context, 'capture', role='pi_side_a')
    assert not service.get(sid)['wiring_review']['slots']['pi_side_a'].get('photo_acceptance')
    assert service.sessions[sid]['context'] == before
    assert service.get(sid)['wiring_review']['reviews'] == {}
    assert not state.pi_execution.jobs and not state.design_service.bridge.calls


def test_legacy_complete_photo_review_can_still_analyse_without_photo_receipts(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    service.sessions[sid]['wiring_review'].pop('photo_flow_version')
    for role in ('pi_side_a', 'pi_side_b', 'component_header'):
        _act(service, sid, context, 'capture', role=role)
    _cloud(state, _answer(context))
    _act(service, sid, context, 'analyse')
    service.tick(sid)
    assert service.get(sid)['wiring_review']['status'] == 'ready'
    assert len(state.design_service.bridge.calls) == 1


def test_unknown_pin_retains_colours_and_duplicate_candidates(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    result = _analyse(service, state, sid, context, _answer(context, unknown=True, duplicate=True))
    assert len(result['observations']) == 12
    assert all(c['pin_id'] is None for c in result['observations'] if c['role'] != 'component_header')
    assert all(r['comparison'] in {'ambiguous', 'unknown'} for r in result['results'])
    assert all(r['pi_candidates'] for r in result['results'])
    assert all(c['color'] != 'unknown' for c in result['observations'])


def test_adjacent_wrong_pin_candidate_is_not_rewritten_to_expected_pin(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    answer = _answer(context)
    for view in answer['views']:
        if view['role'] != 'component_header':
            view['connectors'][2]['pin_id'] = 'GPIO23'
    result = _analyse(service, state, sid, context, answer)
    row = result['results'][2]
    assert row['expected']['board_pin'] == 'GPIO18' and row['expected']['physical_pin'] == 12
    assert {c['pin_id'] for c in row['pi_candidates']} == {'GPIO23'}
    assert {c['physical_pin'] for c in row['pi_candidates']} == {16}
    assert row['comparison'] in {'ambiguous', 'unknown'} and row['same_wire'] == 'uncertain'
    assert result['reviews'] == {}


def test_retake_only_one_role_and_revision_rejects_old_tab(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    before = service.get(sid)['wiring_review']
    _act(service, sid, context, 'capture', role='pi_side_b')
    after = service.get(sid)['wiring_review']
    assert after['slots']['pi_side_a'] == before['slots']['pi_side_a']
    assert after['slots']['component_header'] == before['slots']['component_header']
    assert after['slots']['pi_side_b']['capture_id'] != before['slots']['pi_side_b']['capture_id']
    with pytest.raises(ValueError, match='stale_wiring_review'):
        service.action(sid, 'wiring_review', 'old-tab', context=context,
            wiring_review=dict(op='analyse', review_id=before['id'], revision=before['revision']))
    assert not state.design_service.bridge.calls


def test_crop_keeps_original_and_restoring_input_reuses_analysis(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    before = service.get(sid)['wiring_review']['slots']['pi_side_a']
    raw = service.images[sid][before['capture_id']]
    _analyse(service, state, sid, context)
    _act(service, sid, context, 'crop', role='pi_side_a', crop=[.1, .2, .8, .9])
    _act(service, sid, context, 'crop', role='pi_side_a', crop=None)
    _act(service, sid, context, 'analyse')
    service.tick(sid)
    assert len(state.design_service.bridge.calls) == 1
    _act(service, sid, context, 'crop', role='pi_side_a', crop=[.1, .2, .8, .9])
    r = _analyse(service, state, sid, context)
    assert len(state.design_service.bridge.images[-1]) == 2  # Changed Pi side overview + detail only.
    assert service.images[sid][before['capture_id']] == raw
    assert r['slots']['pi_side_a']['crop_source'] == 'manual'
    detail = cv2.imdecode(np.frombuffer(state.design_service.bridge.images[-1][1], np.uint8), cv2.IMREAD_COLOR)
    source = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(detail, source[96:432, 64:512])
    manifest = r['model_receipt']['image_inputs']
    assert manifest[1]['crop'] == [64, 96, 512, 432]
    assert manifest[1]['size'] == [448, 336]
    assert manifest[1]['source_sha256'] == before['sha256']
    assert manifest[1]['supplied_sha256'] == hashlib.sha256(state.design_service.bridge.images[-1][1]).hexdigest()
    assert r['model_receipt']['reused_roles'] == ['pi_side_b', 'component_header']


def test_resized_input_receipts_describe_actual_cloud_pixels(setup):
    service, state = setup
    old = service.capture_fn
    def capture(st, target, **kwargs):
        _, metadata = old(st, target, **kwargs)
        height, width = (3840, 2880) if target == 'module_header' else (2160, 3840)
        frame = np.full((height, width, 3), metadata['seq'] * 10, np.uint8)
        _, encoded = cv2.imencode('.jpg', frame)
        metadata['size'] = [width, height]
        return {'overview': encoded.tobytes()}, metadata
    service.capture_fn = capture
    sid, context = _start(service)
    _photos(service, sid, context)
    result = _analyse(service, state, sid, context)
    manifest = result['model_receipt']['image_inputs']
    assert [v['size'] for v in manifest] == [[1920, 1080], [1920, 1080], [1080, 1440]]
    assert all(v['resized'] and not v['original_pixels'] for v in manifest)
    assert manifest[2]['source_size'] == [2880, 3840]
    for row, raw in zip(manifest, state.design_service.bridge.images[-1]):
        decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        assert row['size'] == [decoded.shape[1], decoded.shape[0]]
        assert row['supplied_sha256'] == hashlib.sha256(raw).hexdigest()


def test_same_request_is_idempotent_and_stale_model_result_is_discarded(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    r = service.get(sid)['wiring_review']
    body = dict(op='analyse', review_id=r['id'], revision=r['revision'])
    service.action(sid, 'wiring_review', 'once', context=context, wiring_review=body)
    service.action(sid, 'wiring_review', 'once', context=context, wiring_review=body)
    _cloud(state, _answer(context), lambda: _act(service, sid, context, 'capture', role='pi_side_a'))
    service.tick(sid)
    result = service.get(sid)['wiring_review']
    assert result['status'] == 'collecting' and result['results'] == []
    assert len(state.design_service.bridge.calls) == 1


def test_human_reviews_are_separate_preserved_and_withdrawal_clears_test_key(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    result = _analyse(service, state, sid, context)
    first, second = [r['wire_id'] for r in result['results'][:2]]
    _act(service, sid, context, 'review', wire_id=first, decision='confirmed')
    _act(service, sid, context, 'review', wire_id=second, decision='confirmed')
    reviews = service.get(sid)['wiring_review']['reviews']
    assert set(reviews) == {first, second} and all(r['source'] == 'human' for r in reviews.values())
    assert len({r['review_revision'] for r in reviews.values()}) == 1
    records = deepcopy(context['guide_confirmations'])
    del records[first]
    changed = _with_confirmations(context, records)
    _act(service, sid, changed, 'review', wire_id=first, decision='unsure')
    assert service.get(sid)['wiring_review']['results'] == result['results']
    assert service.get(sid)['wiring_review']['reviews'][second] == reviews[second]
    assert first not in service.sessions[sid]['context']['guide_confirmations']
    assert service.sessions[sid]['context']['test_keys']['hc-sr04'] != context['test_keys']['hc-sr04']
    assert service.get(sid)['hardware_ready'] is False
    assert not state.pi_execution.jobs


def test_invalid_review_cannot_mutate_guide_and_changed_resets_only_photo_round(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    result = _analyse(service, state, sid, context)
    first, second = [r['wire_id'] for r in result['results'][:2]]
    records = deepcopy(context['guide_confirmations'])
    del records[first]
    del records[second]
    with pytest.raises(ValueError, match='invalid_human_confirmation_change'):
        _act(service, sid, _with_confirmations(context, records), 'review', wire_id=first, decision='unsure')
    assert service.sessions[sid]['context'] == context
    records = {k: v for k, v in context['guide_confirmations'].items() if k not in {r['wire_id'] for r in result['results']}}
    changed = _with_confirmations(context, records)
    _act(service, sid, changed, 'changed', component_id='hc-sr04')
    current = service.get(sid)['wiring_review']
    assert current['round'] == 2 and all(s is None for s in current['slots'].values())
    assert current['results'] == [] and current['reviews'] == {}
    assert all(not e['current'] for e in service.get(sid)['evidence'])
    assert service.sessions[sid]['context'] == changed


def test_two_repeated_no_progress_rounds_stop_cloud_retries(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    for i in range(3):
        if i:
            _act(service, sid, context, 'capture', role='pi_side_a')
        result = _analyse(service, state, sid, context, _answer(context, unknown=True))
    assert result['status'] == 'needs_human' and result['no_progress_count'] == 2
    with pytest.raises(ValueError, match='human_review_required'):
        _act(service, sid, context, 'analyse')
    with pytest.raises(ValueError, match='human_review_required'):
        _act(service, sid, context, 'capture', role='pi_side_a')
    with pytest.raises(ValueError, match='human_review_required'):
        _act(service, sid, context, 'crop', role='pi_side_a', crop=[0, 0, .8, .8])
    wire_id = result['results'][0]['wire_id']
    _act(service, sid, context, 'review', wire_id=wire_id, decision='confirmed')
    assert service.get(sid)['wiring_review']['reviews'][wire_id]['source'] == 'human'
    assert len(state.design_service.bridge.calls) == 3
    assert list(map(len, state.design_service.bridge.images)) == [3, 1, 1]


def test_component_switch_reuses_pi_slots_and_only_analyses_new_header(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    hc = _analyse(service, state, sid, context)
    first = hc['results'][0]['wire_id']
    _act(service, sid, context, 'review', wire_id=first, decision='confirmed')
    _act(service, sid, context, 'start', component_id='mrd-tf240-8p-cs')
    tft = service.get(sid)['wiring_review']
    assert tft['id'] == hc['id'] and tft['round'] == hc['round']
    assert tft['slots']['pi_side_a'] == hc['slots']['pi_side_a']
    assert tft['missing_roles'] == ['component_header']
    _act(service, sid, context, 'capture', role='component_header')
    _analyse(service, state, sid, context, _answer(context, component_id='mrd-tf240-8p-cs'))
    assert len(state.design_service.bridge.images[-1]) == 1
    _act(service, sid, context, 'start', component_id='hc-sr04')
    restored = service.get(sid)['wiring_review']
    assert restored['slots']['component_header'] == hc['slots']['component_header']
    assert restored['reviews'][first]['source'] == 'human'
    assert restored['results'] == hc['results']


def test_changed_round_never_reuses_other_components_old_photos(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    _analyse(service, state, sid, context)
    _act(service, sid, context, 'start', component_id='mrd-tf240-8p-cs')
    _act(service, sid, context, 'capture', role='component_header')
    _analyse(service, state, sid, context, _answer(context, component_id='mrd-tf240-8p-cs'))
    _act(service, sid, context, 'start', component_id='hc-sr04')
    records = {k: v for k, v in context['guide_confirmations'].items() if not k.startswith('hc-sr04:')}
    changed = _with_confirmations(context, records)
    _act(service, sid, changed, 'changed', component_id='hc-sr04')
    _act(service, sid, changed, 'start', component_id='mrd-tf240-8p-cs')
    current = service.get(sid)['wiring_review']
    assert current['round'] == 2 and current['missing_roles'] == ['pi_side_a', 'pi_side_b', 'component_header']
    assert all(not entry['current'] for entry in service.get(sid)['evidence'])
    assert service.sessions[sid]['context']['guide_confirmations'] == records
    assert service.sessions[sid]['wiring_review'].get('last_opinion') is None


def test_prepare_wiring_preserves_photos_for_human_withdrawal(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    before = _analyse(service, state, sid, context)
    service.action(sid, 'prepare_wiring', 'prepare', context=context)
    prepared = service.get(sid)['wiring_review']
    assert prepared['id'] == before['id'] and prepared['status'] == 'ready'
    assert prepared['slots'] == before['slots']
    first = prepared['results'][0]['wire_id']
    records = deepcopy(context['guide_confirmations'])
    del records[first]
    _act(service, sid, _with_confirmations(context, records), 'review', wire_id=first, decision='needs_change')
    assert service.get(sid)['wiring_review']['reviews'][first]['decision'] == 'needs_change'


def test_switching_away_from_pending_analysis_cannot_replay_it(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    _act(service, sid, context, 'analyse')
    _act(service, sid, context, 'start', component_id='mrd-tf240-8p-cs')
    _act(service, sid, context, 'start', component_id='hc-sr04')
    service.tick(sid)
    assert service.get(sid)['wiring_review']['status'] == 'collecting'
    assert not state.design_service.bridge.calls


def test_retake_keeps_human_confirmation_and_rejects_forged_partial_test_key(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    result = _analyse(service, state, sid, context)
    first = result['results'][0]['wire_id']
    _act(service, sid, context, 'review', wire_id=first, decision='confirmed')
    _act(service, sid, context, 'capture', role='pi_side_a')
    review = service.get(sid)['wiring_review']
    assert review['reviews'][first]['decision'] == 'confirmed'
    assert review['reviews'][first]['evidence_stale'] is True
    history = service.get(sid)['wiring_review_history']
    assert history[-1]['reviews'][first]['decision'] == 'confirmed'
    assert history[-1]['results'] == result['results'] and history[-1]['observations']
    assert history[-1]['slots']['pi_side_a']['capture_id'] != review['slots']['pi_side_a']['capture_id']
    assert service.sessions[sid]['context']['guide_confirmations'] == context['guide_confirmations']
    _analyse(service, state, sid, context)
    withdrawn = deepcopy(context)
    del withdrawn['guide_confirmations'][first]
    with pytest.raises(ValueError, match='invalid_human_test_key'):
        _act(service, sid, withdrawn, 'review', wire_id=first, decision='unsure')
    assert first in service.sessions[sid]['context']['guide_confirmations']


def test_restart_keeps_review_summary_but_expires_photos(setup, tmp_path):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    _analyse(service, state, sid, context)
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    review = restored.get(sid)['wiring_review']
    assert review['status'] == 'stale' and all(not s['available'] for s in review['slots'].values())
    restored.tick(sid)
    assert len(state.design_service.bridge.calls) == 1


def test_auto_crop_demands_independent_same_source_evidence():
    view = dict(name='pi_pins', frame_id=7, crop=[20, 30, 500, 400], context='visible_header_and_wire_exit')
    metadata = dict(frame_id=7, views=[view])
    assert supported_crop(metadata, 'pi_side_a', [640, 480]) is None
    view['evidence'] = dict(pin_geometry_verified=True, source_frame_id=6, source_size=[640, 480])
    assert supported_crop(metadata, 'pi_side_a', [640, 480]) is None
    view['evidence']['source_frame_id'] = 7
    assert supported_crop(metadata, 'pi_side_a', [640, 480]) == [20/640, 30/480, 500/640, 400/480]


def test_api_typed_payload_and_collect_has_no_implicit_cloud(setup):
    service, state = setup
    app = FastAPI()
    app.state.debug_sessions = service
    app.state.pi_deployer = state.pi_deployer
    app.include_router(router)
    client = TestClient(app)
    created = client.post('/api/debug/sessions', json=dict(context=_context(), symptom='核對', request_id='api-create',
        purpose='wiring_review', initial_action='collect'))
    assert created.status_code == 200
    sid = created.json()['id']
    service.tick(sid)
    assert not state.design_service.bridge.calls
    result = client.post(f'/api/debug/sessions/{sid}/actions', json=dict(action='wiring_review', context=_context(),
        request_id='api-start', wiring_review=dict(op='start', component_id='hc-sr04')))
    assert result.status_code == 200 and result.json()['wiring_review']['round'] == 1
    bad = client.post(f'/api/debug/sessions/{sid}/actions', json=dict(action='wiring_review', context=_context(),
        request_id='api-bad', wiring_review=dict(op='crop', role='pi_side_a', crop=[0, 0, 2, 1])))
    assert bad.status_code == 422


def test_api_frontend_partial_test_keys_first_confirmation_and_unsure(setup):
    service, state = setup
    _capture_stub(service)
    complete = _context()
    partial = _with_confirmations(complete, {})
    partial['locale'] = 'zh-TW'
    sid, _ = _start(service, partial)
    _photos(service, sid, partial)
    reviewed = _analyse(service, state, sid, partial)
    app = FastAPI()
    app.state.debug_sessions = service
    app.state.pi_deployer = state.pi_deployer
    app.include_router(router)
    client = TestClient(app)
    wire_id = reviewed['results'][0]['wire_id']
    confirmed = _with_confirmations(partial, {wire_id: complete['guide_confirmations'][wire_id]})
    response = client.post(f'/api/debug/sessions/{sid}/actions', json=dict(action='wiring_review', request_id='api-confirm',
        context=confirmed, wiring_review=dict(op='review', review_id=reviewed['id'], revision=reviewed['revision'],
                                             wire_id=wire_id, decision='confirmed')))
    assert response.status_code == 200, response.text
    state_review = response.json()['wiring_review']
    assert state_review['reviews'][wire_id]['source'] == 'human'
    assert state_review['reviews'][wire_id]['capture_ids']
    withdrawn = client.post(f'/api/debug/sessions/{sid}/actions', json=dict(action='wiring_review', request_id='api-unsure',
        context=partial, wiring_review=dict(op='review', review_id=state_review['id'], revision=state_review['revision'],
                                           wire_id=wire_id, decision='unsure')))
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()['wiring_review']['reviews'][wire_id]['decision'] == 'unsure'
    assert service.sessions[sid]['context']['guide_confirmations'] == {}
    assert service.sessions[sid]['context']['test_keys'] == partial['test_keys']
    assert not state.pi_execution.jobs


def test_schema_rejects_nonfinite_crop_and_extra_authority():
    with pytest.raises(ValueError):
        WiringReviewAction.model_validate(dict(op='crop', review_id='x', revision=1, role='pi_side_a', crop=[0, 0, float('nan'), 1]))
    with pytest.raises(ValueError):
        WiringReviewAction.model_validate(dict(op='review', review_id='x', revision=1, wire_id='x', decision='confirmed', source='ai'))


def test_cloud_schema_uses_provider_supported_array_items_not_tuple_prefix_items():
    schema = ReviewOpinion.model_json_schema()
    def walk(value):
        if isinstance(value, dict):
            if value.get('type') == 'array':
                assert isinstance(value.get('items'), dict), value
                assert 'prefixItems' not in value
            if value.get('type') == 'object':
                assert set(value.get('required', [])) == set(value.get('properties', {}))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(schema)
