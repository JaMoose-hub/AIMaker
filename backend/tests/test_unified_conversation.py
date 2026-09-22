import copy
import pytest
from pydantic import ValidationError
from app.api.design import DesignService
from app.design_prompt import build_design_prompt
from app.designs import ConversationReply, GenerateRequest, demo_design, proposal_schema
from app.project_images import ProjectImageStore
from test_maker import client, completed, proposal
from test_project_images import ImageBridge


class ChatBridge(ImageBridge):
    def __init__(self, action, data=None):
        super().__init__()
        self.reply = dict(action=action, answer="A short explanation", proposal=data)

    def generate(self, *args, **kwargs):
        super().generate(*args, **kwargs)
        return copy.deepcopy(self.reply)


def run(tmp_path, action, data=None, **body):
    bridge = ChatBridge(action, data)
    c, app = client(bridge)
    service = app.state.design_service
    service.images = ProjectImageStore(tmp_path)
    response = c.post('/api/design/generate', json=dict(prompt='Please help', intent='auto', generate_image=True,
        component_ids=['hc-sr04'], **body))
    assert response.status_code == 202
    return bridge, service, completed(service, response.json()['job_id'])


def test_answer_and_clarification_never_compile_or_generate_images(tmp_path):
    b, service, job = run(tmp_path, 'answer', current=demo_design(['hc-sr04']))
    assert job['status'] == 'completed' and job['answer']
    assert job['design'] is None and not b.image_calls
    assert b.text_calls == 1
    restored = DesignService(b, ProjectImageStore(tmp_path)).get(job['id'])
    assert restored['answer'] == job['answer'] and restored['design'] is None


@pytest.mark.parametrize('action,mode', [('revise','fixed'), ('redesign','free')])
def test_auto_design_selects_image_continuity_without_mutating_approved_project(tmp_path, action, mode):
    # Missing previous image is fine for fresh rendering; revisions without an image create a new one.
    current = demo_design(['hc-sr04'])
    original = copy.deepcopy(current)
    b, service, job = run(tmp_path, action, proposal(), current=current)
    assert job['status'] == 'completed'
    assert 'answer' not in job and job['explanation']
    assert job['design_mode'] == mode == job['design']['generation']['design_mode']
    assert job['design']['id'] == current['id'] and current == original
    assert job['design']['wiring'] == current['wiring']
    assert len(b.image_calls) == 1 and job['design']['image']
    assert ('FREE REDESIGN' in b.image_calls[0][0]) == (mode == 'free')


@pytest.mark.parametrize('reply', [dict(action='answer',answer='x',proposal=proposal()),
    dict(action='revise',answer='x',proposal=None),dict(action='deploy',answer='x',proposal=None)])
def test_inconsistent_or_executable_actions_are_rejected(reply):
    with pytest.raises(ValidationError):
        ConversationReply.model_validate(reply)


def test_auto_schema_prompt_and_estimate_keep_question_boundary(tmp_path):
    body = GenerateRequest(prompt='What does this sensor do?', intent='auto', component_ids=['hc-sr04'],
        generate_image=True, current={'password':'SECRET','title':'existing'},
        conversation=[{'role':'user','text':'keep the screen'}])
    prompt = build_design_prompt(body)
    assert 'SECRET' not in prompt and 'keep the screen' in prompt
    assert 'ambiguous requests: action=answer' in prompt
    assert 'proposal=null' in prompt and 'explicit request' in prompt
    schema=proposal_schema('auto')
    assert set(schema['required']) == {'action','answer','proposal'}
    assert schema['additionalProperties'] is False
    assert set(schema['$defs']['DesignProposal']['required']) == set(schema['$defs']['DesignProposal']['properties'])
    estimate=DesignService(ChatBridge('answer'),ProjectImageStore(tmp_path)).estimate(body)
    assert estimate['image_generation']['conditional'] is True
    assert estimate['image_generation']['requested'] is False


def test_demo_is_local_and_does_not_call_ai():
    b=ChatBridge('answer')
    c,_=client(b)
    demo=c.get('/api/design/demo').json()
    assert demo['source']=='demo' and len(demo['component_ids'])==2
    assert b.text_calls==0 and not b.image_calls


@pytest.mark.parametrize('action', ['revise', 'redesign'])
def test_auto_reuses_prior_image_only_for_local_revisions(tmp_path, action):
    b = ChatBridge('redesign', proposal())
    c, app = client(b)
    service = app.state.design_service
    service.images = ProjectImageStore(tmp_path)
    body = dict(prompt='Create a cart', intent='auto', generate_image=True, component_ids=['hc-sr04'])
    first_id = c.post('/api/design/generate', json=body).json()['job_id']
    first = completed(service, first_id)['design']
    b.reply['action'] = action
    second_id = c.post('/api/design/generate', json={**body, 'current':first}).json()['job_id']
    second = completed(service, second_id)
    assert second['status'] == 'completed'
    assert b.image_calls[-1][1]['reference'] == (service.images.path(first['image']['id']) if action == 'revise' else None)
    assert second['design']['revision'] == first['revision'] + 1
