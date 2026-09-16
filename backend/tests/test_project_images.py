import base64
import copy
import json
import cv2
import numpy as np
import pytest
from app.api.design import DesignService
from app.designs import DesignProposal, GenerateRequest, compile_design, demo_design
from app.project_images import ProjectImageStore, build_image_prompt
from test_maker import Bridge, client, completed, proposal


def native_image():
    ok, png = cv2.imencode('.png', np.zeros((48, 64, 3), dtype=np.uint8))
    assert ok
    return {'type': 'imageGeneration', 'status': 'completed', 'result': base64.b64encode(png).decode()}


class ImageBridge(Bridge):
    def __init__(self):
        super().__init__()
        self.image_calls = []
        self.text_calls = 0
        self.image_error = None

    def generate(self, *args, **kwargs):
        self.text_calls += 1
        return super().generate(*args, **kwargs)

    def generate_image(self, prompt, **kwargs):
        self.image_calls.append((prompt, kwargs))
        if self.image_error:
            raise self.image_error
        return native_image()


def setup(tmp_path):
    bridge = ImageBridge()
    c, app = client(bridge)
    app.state.design_service.images = ProjectImageStore(tmp_path)
    return bridge, c, app.state.design_service


def submit(c, service, **kwargs):
    response = c.post('/api/design/generate', json=dict(prompt='Cart illustration', component_ids=['hc-sr04'], generate_image=True, **kwargs))
    assert response.status_code == 202
    return completed(service, response.json()['job_id'])


def test_real_image_contract_is_persisted_and_addressable_after_restart(tmp_path):
    b, c, service = setup(tmp_path)
    job = submit(c, service)
    image = job['design']['image']
    assert job['status'] == 'completed' and image['width'] == 64
    response = c.get(image['url'])
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    assert 'immutable' in response.headers['cache-control']
    restored = DesignService(b, ProjectImageStore(tmp_path)).get(job['id'])
    assert restored['design']['image'] == image
    record = json.loads((tmp_path / f"{image['id']}.json").read_text(encoding='utf-8'))
    assert record['prompt'] and record['design']['title'] and record['actual_cost'] is None
    assert b.text_calls == 1 and len(b.image_calls) == 1


def test_revision_uses_only_prior_saved_image_and_keeps_wiring(tmp_path):
    b, c, service = setup(tmp_path)
    first = submit(c, service)['design']
    prior = copy.deepcopy(first)
    prior.update(password='SECRET', arbitrary_url='https://private.invalid')
    second = submit(c, service, current=prior, design_mode='fixed')['design']
    assert second['image']['id'] != first['image']['id']
    prompt, options = b.image_calls[-1]
    assert options['reference'] == service.images.path(first['image']['id'])
    assert 'EDIT TARGET' in prompt and 'SECRET' not in prompt and 'private.invalid' not in prompt
    assert second['wiring'] == first['wiring']
    assert first['image'] and second['revision'] == first['revision'] + 1


def test_free_version_never_references_prior_image_but_keeps_project_identity(tmp_path):
    b, c, service = setup(tmp_path)
    first = submit(c, service)['design']
    original = copy.deepcopy(first)
    # Even a missing old file must not prevent a fresh render.
    current = {**first, 'image': {**first['image'], 'id': 'e' * 32}}
    job = submit(c, service, current=current, design_mode='free')
    second = job['design']
    assert second['image']['id'] != first['image']['id']
    prompt, options = b.image_calls[-1]
    assert options['reference'] is None and 'FREE REDESIGN' in prompt
    assert 'EDIT TARGET' not in prompt and 'reference_image' not in job
    assert second['generation']['design_mode'] == job['design_mode'] == 'free'
    assert second['id'] == first['id'] and second['revision'] == first['revision'] + 1
    assert first == original and second['wiring'] == first['wiring']


@pytest.mark.parametrize('mode', ['fixed', 'free'])
def test_image_retry_after_restart_preserves_original_design_mode(tmp_path, mode):
    b, c, service = setup(tmp_path)
    first = submit(c, service)['design']
    b.image_error = RuntimeError('quota unavailable')
    failed = submit(c, service, current=first, design_mode=mode)
    assert failed['design']['image_error']
    c.app.state.design_service = restored = DesignService(b, ProjectImageStore(tmp_path))
    b.image_error = None
    response = c.post(f"/api/design/jobs/{failed['id']}/retry-image", json={'design_mode': 'free' if mode == 'fixed' else 'fixed'})
    assert response.status_code == 202
    retried = completed(restored, response.json()['job_id'])
    assert retried['design_mode'] == retried['design']['generation']['design_mode'] == mode
    assert retried['design']['image'] and b.text_calls == 2
    assert b.image_calls[-1][1]['reference'] == (restored.images.path(first['image']['id']) if mode == 'fixed' else None)


def test_fixed_mode_without_prior_image_creates_a_base(tmp_path):
    b, c, service = setup(tmp_path)
    job = submit(c, service, design_mode='fixed')
    assert job['design']['image'] and job['design_mode'] == 'fixed'
    assert b.image_calls[-1][1]['reference'] is None
    assert 'no previous image' in b.image_calls[-1][0]


def test_image_failure_preserves_text_and_manual_retry_does_not_regenerate_text(tmp_path):
    b, c, service = setup(tmp_path)
    b.image_error = RuntimeError('quota unavailable')
    job = submit(c, service)
    assert job['design']['image_error'] == 'quota unavailable'
    assert job['design']['image_required'] and not job['design'].get('image')
    b.image_error = None
    response = c.post(f"/api/design/jobs/{job['id']}/retry-image", json={})
    assert response.status_code == 202
    retried = completed(service, response.json()['job_id'])
    assert retried['design']['image'] and 'image_error' not in retried['design']
    assert retried['design']['revision'] == job['design']['revision']
    assert b.text_calls == 1 and len(b.image_calls) == 2
    assert c.post(f"/api/design/jobs/{retried['id']}/retry-image", json={}).status_code == 409


def test_question_and_estimates_never_generate_images(tmp_path):
    b, c, service = setup(tmp_path)
    request = dict(prompt='cart', component_ids=['hc-sr04'], generate_image=True)
    estimate = c.post('/api/ai/estimate', json=request).json()
    assert estimate['image_generation']['requested']
    assert not estimate['image_generation']['included_in_estimate']
    assert estimate['image_generation']['estimated_cost'] is None
    assert not b.image_calls and not b.text_calls
    b.generate = lambda *args, **kwargs: {'answer': 'No new electronics.'}
    job = submit(c, service, intent='ask')
    assert job['answer'] and not b.image_calls


@pytest.mark.parametrize('kind', ['motor', 'battery', 'servo', 'new-sensor'])
def test_structural_scope_never_admits_functional_modules(kind):
    with pytest.raises(ValueError):
        DesignProposal.model_validate({**proposal(), 'assembly': {'description': 'cart', 'parts': [{'kind': kind, 'quantity': 1, 'purpose': 'x'}]}})


def test_passive_parts_do_not_change_gpio_code_requirements_or_electronic_bom():
    raw = proposal()
    base = compile_design(DesignProposal.model_validate(raw), 'base')
    raw['assembly'] = {'description': 'Transparent passive four-wheel cart', 'parts': [
        {'kind': 'wheel', 'quantity': 4, 'purpose': 'Passive wheels'},
        {'kind': 'acrylic-panel', 'quantity': 2, 'purpose': 'Visible mounting'}]}
    cart = compile_design(DesignProposal.model_validate(raw), 'car')
    for key in ['wiring', 'code', 'requirements', 'bom', 'unresolved']:
        assert cart[key] == base[key]
    prompt = build_image_prompt(cart)
    assert 'four-wheel cart' in prompt and 'No motors' in prompt and 'HC-SR04' in prompt


@pytest.mark.parametrize('item', [{'result': 'not base64'}, {'result': base64.b64encode(b'<svg/>').decode()}, {'result': '', 'savedPath': 'C:/Windows/win.ini'}])
def test_store_rejects_non_images_and_arbitrary_native_paths(tmp_path, item):
    with pytest.raises((ValueError, OSError)):
        ProjectImageStore(tmp_path).save(item, prompt='test', model='test', effort='low')


def test_job_recovery_never_automatically_retries_after_backend_restart(tmp_path):
    store = ProjectImageStore(tmp_path)
    job = {'id': '12345678-1234-1234-1234-123456789012', 'status': 'generating'}
    store.save_job(job)
    assert store.load_job(job['id'])['status'] == 'failed'
    with pytest.raises(ValueError):
        store.path('../private')


def test_prompt_disambiguates_imu_from_pir_without_adding_a_module():
    prompt = build_image_prompt(demo_design())
    assert 'FLAT IMU/gyroscope PCB' in prompt
    assert 'NOT a PIR' in prompt and 'NO white dome' in prompt


@pytest.mark.parametrize('failure', ['missing-image', 'quota', 'reroute', None])
def test_native_bridge_accepts_only_completed_image_events(tmp_path, failure):
    from collections import deque
    from types import SimpleNamespace
    from app.codex_bridge import CodexBridge
    b = CodexBridge()
    b._workspace = SimpleNamespace(name=str(tmp_path))
    b._start = lambda: None
    b._load_models = ImageBridge().models
    calls = []
    events = deque()
    def rpc(method, params, **kwargs):
        calls.append((method, params))
        if method == 'account/read':
            return {'account': {'type': 'chatgpt'}}
        if method == 'modelProvider/capabilities/read':
            return {'imageGeneration': True}
        if method == 'thread/start':
            assert params['sandbox'] == 'read-only'
            assert params['config']['features.shell_tool'] is False
            assert params['config']['features.image_generation'] is True
            return {'thread': {'id': 'thread'}, 'model': 'gpt-5.6-luna'}
        if method == 'turn/start':
            assert params['input'][1] == {'type': 'localImage', 'path': str((tmp_path / 'prior.png').resolve())}
            if failure == 'reroute':
                events.append({'method': 'model/rerouted', 'params': {'threadId': 'thread', 'toModel': 'different'}})
            if failure != 'missing-image':
                events.append({'method': 'item/completed', 'params': {'threadId': 'thread', 'item': {**native_image(), 'failure': {'type': 'usageLimitExceeded'} if failure == 'quota' else None}}})
            events.append({'method': 'item/completed', 'params': {'threadId': 'thread', 'item': {'type': 'agentMessage', 'text': 'fake.png'}}})
            events.append({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'status': 'completed'}}})
            return {'turn': {'id': 'turn'}}
        return {}
    b._rpc = rpc
    b._next = lambda *args: events.popleft()
    if failure:
        with pytest.raises(RuntimeError):
            b.generate_image('draw', model='gpt-5.6-luna', effort='low', reference=tmp_path / 'prior.png')
        assert any(method == 'turn/interrupt' for method, _ in calls)
    else:
        assert b.generate_image('draw', model='gpt-5.6-luna', effort='low', reference=tmp_path / 'prior.png')['result']
