# test_orchestration_dependency_planner.py
"""Real planner/compiler admission with an isolated model client.

Version: 0.261.140
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139
Provider I/O is replaced at client.chat.completions.create, not the compiler.
"""

from copy import deepcopy
import importlib
import json
import sys
from types import SimpleNamespace

import pytest

from test_orchestration_dependency_runtime import binding, compose, runtime
from test_support.app_stubs import stubbed_config


@pytest.fixture
def planner(runtime):
    name = "functions_orchestration_planner"
    # Its imported logging callback must not outlive the stubbed import scope.
    previous = sys.modules.pop(name, None)
    try:
        with stubbed_config(cognitive_services_scope='offline-scope'):
            yield importlib.import_module(name)
    finally:
        sys.modules.pop(name, None)
        if previous is not None:
            sys.modules[name] = previous


def invoke(planner, reply, *, contract_version=2, settings=None, edit_context=None):
    calls = []

    def create(**request):
        calls.append(deepcopy(request))
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason='stop', message=SimpleNamespace(content=json.dumps(reply), refusal=None),
            )],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=40, total_tokens=60),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    model = SimpleNamespace(deployment='offline-planner', as_planner_client=lambda: client)
    result = planner.plan_request(
        'Prepare an original short answer.', {'message': 'Prepare an original short answer.'},
        'conversation-1', 'owner', settings={'enable_user_workspace': True, **(settings or {})},
        planner_model=model, contract_version=contract_version, edit_context=edit_context,
    )
    return result, calls


def test_planner_admits_explicit_named_answer_without_terminal_respond(planner):
    result, calls = invoke(planner, {
        'kind': 'plan', 'steps': [compose()], 'final_response': binding('draft'),
    })
    kind, plan = result
    assert kind == 'plan' and plan['planner_contract_version'] == 2
    assert [step['capability_id'] for step in plan['steps']] == ['compose']
    assert plan['final_response'] == binding('draft')
    assert len(calls) == 1
    context = json.loads(calls[0]['messages'][1]['content'])
    offered = {capability['id'] for capability in context['capabilities']}
    assert 'compose' in offered and 'respond' not in offered and 'render_file' not in offered
    assert 'web_search' not in offered and 'tabular_analyze' not in offered
    assert 'not ordered phases' in calls[0]['messages'][0]['content']
    assert plan['token_usage']['total_tokens'] == 60


@pytest.mark.parametrize('invalid', ['dependency', 'version', 'disabled', 'extra_work'])
def test_invalid_plan_never_falls_back_to_a_repaired_answer(planner, invalid):
    reply = {'kind': 'plan', 'steps': [compose()]}
    settings = {}
    if invalid == 'dependency':
        reply['steps'][0]['depends_on'] = ['missing-source']
    elif invalid == 'version':
        reply['planner_contract_version'] = 1
    elif invalid == 'disabled':
        settings['chat_orchestration_enabled_capabilities'] = ['document_search']
    else:
        reply['steps'].append(compose('required-second-output'))
        settings['chat_orchestration_max_steps'] = 1
    with pytest.raises(planner.PlannerError) as failure:
        invoke(planner, reply, settings=settings)
    assert failure.value.reason == 'invalid_plan_or_missing_requirement'


def test_editor_does_not_add_legacy_terminal_rule(planner):
    edit = {'current_plan': {'planner_contract_version': 2, 'steps': [compose()]}, 'instruction': 'Keep the answer concise.'}
    result, calls = invoke(planner, {
        'kind': 'plan', 'revised_request': 'Prepare a concise original answer.',
        'steps': [compose()], 'final_response': binding('draft'),
    }, edit_context=edit)
    assert result[0] == 'plan'
    assert 'the final respond step' not in calls[0]['messages'][0]['content']
    assert edit['current_plan']['steps'][0]['capability_id'] == 'compose'


def test_planning_refuses_the_removed_earlier_contract_before_any_model_call(planner, runtime):
    def create(**request):
        raise AssertionError('The earlier contract must be refused before planning.')

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    model = SimpleNamespace(deployment='offline-planner', as_planner_client=lambda: client)
    with pytest.raises(runtime.schema.LegacyPlanError):
        planner.plan_request(
            'Prepare an original short answer.', {'message': 'Prepare an original short answer.'},
            'conversation-1', 'owner', settings={'enable_user_workspace': True},
            planner_model=model, contract_version=1,
        )
    assert 'The final step is always "respond".' not in planner.PLANNER_SYSTEM_PROMPT
