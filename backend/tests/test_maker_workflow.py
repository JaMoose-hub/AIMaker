import json
import pytest
from app.designs import GenerateRequest, DesignProposal, demo_design, compile_design
from app.design_prompt import build_design_prompt
from test_maker import Bridge, client, completed, proposal


def test_concept_preview_compiles_without_changing_wiring_or_hardware():
    original = demo_design()
    preview = dict(scene="Desk monitor", interaction="Move an object", screen_title="MONITOR",
                   screen_lines=["Distance pending", "Tilt pending"], accent="blue", layout="tower")
    revised = compile_design(DesignProposal.model_validate({**proposal(list(original['component_ids'])), 'preview': preview}), 'concept', current=original)
    assert revised['preview'] == preview
    assert revised['wiring'] == original['wiring']
    assert revised['bom'] == original['bom']
    assert revised['unresolved'] == original['unresolved']


@pytest.mark.parametrize('stage', ['design', 'blueprint', 'guide', 'deploy'])
def test_questions_use_cloud_schema_and_never_compile_a_design(stage):
    class AskBridge(Bridge):
        def generate(self, prompt, schema, **kwargs):
            self.prompt = prompt
            assert set(schema['properties']) == {'answer'}
            return {'answer': 'Use the specified voltage divider. Hardware has not been verified.'}
    bridge = AskBridge()
    c, app = client(bridge)
    body = dict(prompt='Explain this step', component_ids=['hc-sr04'], intent='ask',
                current={**demo_design(['hc-sr04']), 'password': 'SECRET'},
                conversation=[{'role': 'user', 'text': 'Keep the same parts'}],
                workflow={'stage': stage, 'active_wire': 'hc-sr04:echo', 'manual_confirmations': 2, 'password': 'PRIVATE'})
    response = c.post('/api/design/generate', json=body)
    assert response.status_code == 202
    job = completed(app.state.design_service, response.json()['job_id'])
    assert job['status'] == 'completed' and job['design'] is None and job['answer']
    assert stage in bridge.prompt and 'Keep the same parts' in bridge.prompt
    assert 'SECRET' not in bridge.prompt and 'PRIVATE' not in bridge.prompt
    assert 'ECHO' in bridge.prompt


def test_question_error_is_not_replaced_with_demo():
    c, app = client(Bridge(error=RuntimeError('quota unavailable')))
    response = c.post('/api/design/generate', json=dict(prompt='help', component_ids=['hc-sr04'], intent='ask'))
    job = completed(app.state.design_service, response.json()['job_id'])
    assert job['status'] == 'failed' and job['design'] is None


def test_context_limits_and_supported_modules_are_unchanged():
    c, _ = client()
    for update in ({'component_ids': ['new-sensor']}, {'workflow': {'stage': 'random'}},
                   {'conversation': [{'role': 'user', 'text': 'x'}] * 21}):
        assert c.post('/api/design/generate', json={'prompt': 'test', 'component_ids': ['hc-sr04'], **update}).status_code == 422
    body = GenerateRequest(prompt='concept', component_ids=['hc-sr04'])
    assert 'Always provide preview' in build_design_prompt(body)


def test_question_estimate_and_generation_share_context_and_schema():
    from app.designs import proposal_schema
    c, _ = client()
    body = GenerateRequest(prompt='why', component_ids=['hc-sr04'], intent='ask', workflow={'stage': 'deploy', 'code_draft': 'print(1)'})
    response = c.post('/api/ai/estimate', json=body.model_dump())
    assert response.status_code == 200
    assert response.json()['payload_bytes'] == len((build_design_prompt(body) + json.dumps(proposal_schema('ask'), ensure_ascii=False)).encode())


@pytest.mark.parametrize('mode', ['fixed', 'free'])
def test_mode_controls_old_shape_context_at_server_boundary(mode):
    old = {**demo_design(), 'title': 'OLD_CAR_TITLE', 'summary': 'OLD_CAR_SUMMARY',
           'preview': {'scene': 'OLD_CAR_SCENE'}, 'assembly': {'description': 'OLD_CAR_CHASSIS'},
           'features': ['OLD_CAR_FEATURE'], 'logic': 'OLD_CAR_LOGIC', 'password': 'PRIVATE_SECRET'}
    body = GenerateRequest(prompt='改成小恐龍', component_ids=list(old['component_ids']), current=old,
                           design_mode=mode, conversation=[{'role': 'user', 'text': 'OLD_CAR_REQUEST'}],
                           workflow={'stage': 'deploy', 'code_draft': 'OLD_CAR_CODE'})
    prompt = build_design_prompt(body)
    context = json.loads(prompt.split('Context: ')[-1])
    assert context['request'] == '改成小恐龍'
    assert context['current_design']['parameters'] == old['parameters']
    assert context['available_modules'] == old['component_ids']
    assert 'PRIVATE_SECRET' not in prompt
    if mode == 'free':
        assert 'OLD_CAR_' not in prompt
        assert 'FREE REDESIGN' in prompt and context['conversation'] == []
        assert set(context['current_design']) == {'component_ids', 'parameters'}
    else:
        assert 'FIXED REVISION' in prompt and 'OLD_CAR_CHASSIS' in prompt
        assert context['conversation'][0]['text'] == 'OLD_CAR_REQUEST'
    # Ask always retains the project and conversation in either mode.
    ask = build_design_prompt(body.model_copy(update={'intent': 'ask'}))
    assert 'OLD_CAR_TITLE' in ask and 'OLD_CAR_REQUEST' in ask and 'OLD_CAR_CODE' in ask
    assert 'PRIVATE_SECRET' not in ask


@pytest.mark.parametrize('mode', ['fixed', 'free'])
def test_design_mode_estimate_and_generation_share_prompt(mode):
    from app.designs import proposal_schema
    bridge = Bridge()
    c, app = client(bridge)
    body = GenerateRequest(prompt='new dinosaur shape', component_ids=['hc-sr04'], design_mode=mode,
                           current=demo_design(['hc-sr04']))
    estimate = c.post('/api/ai/estimate', json=body.model_dump()).json()
    assert estimate['payload_bytes'] == len((build_design_prompt(body) + json.dumps(proposal_schema(), ensure_ascii=False)).encode())
    response = c.post('/api/design/generate', json=body.model_dump())
    job = completed(app.state.design_service, response.json()['job_id'])
    assert job['status'] == 'completed' and bridge.prompt == build_design_prompt(body)
    assert job['design']['generation']['design_mode'] == mode


def test_invalid_design_mode_rejected_before_cloud_calls():
    c, _ = client()
    body = {'prompt': 'test', 'component_ids': ['hc-sr04'], 'design_mode': 'auto'}
    assert c.post('/api/design/generate', json=body).status_code == 422
    assert c.post('/api/ai/estimate', json=body).status_code == 422
