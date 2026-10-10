# test_orchestration_operation_planning.py
"""Functional tests for operation intent, research inputs, and capability truth.

Version: 0.261.321
Implemented in: 0.261.321
"""

from copy import deepcopy

import pytest

from test_orchestration_action_planning import ACTION, SETTINGS, binding, modules


def operation_plan(capability='action_invoke'):
    selector = {'action_ref': ACTION['action_ref']} if capability == 'action_invoke' else {'agent_name': 'specialist'}
    return {
        'steps': [
            {'step_id': 'research', 'capability_id': 'web_search', 'arguments': {'query': 'Find the named event.'}},
            {'step_id': 'draft', 'capability_id': 'compose',
             'arguments': {'instruction': 'Prepare grounded content.', 'knowledge_basis': 'sources'},
             'inputs': {'facts': {'binding': binding('research', 'prepared'), 'allow_partial': False}},
             'outputs': [{'name': 'content', 'kind': 'markdown-v1'}]},
            {'step_id': 'operation', 'capability_id': capability,
             'arguments': {**selector, 'task': 'Perform the requested operation for the stated destination.',
                           'execution_intent': 'operate'},
             'inputs': {'content': {'binding': binding('draft', 'content'), 'allow_partial': False}}},
            {'step_id': 'answer', 'capability_id': 'compose',
             'arguments': {'instruction': 'Report actual operation outcomes.', 'knowledge_basis': 'sources'},
             'inputs': {'outcome': {'binding': binding('operation', 'prepared'), 'allow_partial': False}},
             'outputs': [{'name': 'answer', 'kind': 'markdown-v1'}]},
        ],
        'final_response': binding('answer', 'answer'),
    }


@pytest.mark.parametrize('capability', ['action_invoke', 'agent_invoke'])
def test_research_prepared_content_operation_answer_chain_is_valid(modules, capability):
    plan = modules.schema.normalize_plan(
        operation_plan(capability), 'conversation', 'actor',
        settings={**SETTINGS, 'enable_web_search': True},
        available_capability_ids=['web_search', 'compose', capability],
        actions=[ACTION], agent_names=['specialist'],
    )
    assert plan['steps'][2]['arguments']['execution_intent'] == 'operate'
    assert plan['steps'][2]['depends_on'] == ['draft']
    assert plan['steps'][1]['depends_on'] == ['research']
    assert plan['steps'][3]['depends_on'] == ['operation']


@pytest.mark.parametrize('intent', ['send', True, '', None])
def test_invalid_operation_intent_is_rejected(modules, intent):
    raw = operation_plan()
    raw['steps'][2]['arguments']['execution_intent'] = intent
    with pytest.raises(modules.schema.PlanValidationError):
        modules.schema.normalize_plan(
            raw, 'conversation', 'actor', settings=SETTINGS,
            available_capability_ids=['web_search', 'compose', 'action_invoke'], actions=[ACTION],
        )


def test_partial_or_unbound_operation_input_is_rejected(modules):
    for mutation in ({'allow_partial': True}, {'binding': binding('fabricated', 'content')}):
        raw = operation_plan()
        raw['steps'][2]['inputs']['content'].update(mutation)
        with pytest.raises(modules.schema.PlanValidationError):
            modules.schema.normalize_plan(
                raw, 'conversation', 'actor', settings=SETTINGS,
                available_capability_ids=['web_search', 'compose', 'action_invoke'], actions=[ACTION],
            )


def test_prompt_plans_supported_operations_without_keyword_routing(modules):
    prompt = modules.planner.PLANNER_SYSTEM_PROMPT
    assert 'never to perform an operation on the user' not in prompt
    assert 'execution_intent' in prompt and 'named input' in prompt
    assert 'Royally' not in prompt and 'Paul.lizer' not in prompt


def test_unknown_operation_is_not_offered_as_a_repeatable_retry(modules):
    repeats = modules.schema.failure_repeats_on_retry({'code': 'operation_recovery_required'})
    assert repeats


@pytest.mark.parametrize('action_type', ['m365_email', 'msgraph'])
def test_catalog_projects_effective_operations_and_delivery_without_secrets(action_type):
    from functions_m365_operations import orchestration_m365_capabilities

    action = {
        'type': action_type, 'enabled_functions': ['send_mail'],
        'additionalFields': {
            'm365_capabilities': {'send_mail': True},
            'msgraph_capabilities': {'send_mail': True},
            'msgraph_mail_send_mode': 'draft_delayed',
        },
        'auth': {'secret': 'NEVER_PROJECT'}, 'endpoint': 'https://private.example.test',
    }
    metadata = orchestration_m365_capabilities(deepcopy(action))
    assert len(metadata) == 1
    assert metadata[0]['function_name'] == 'send_mail'
    assert metadata[0]['execution_intent'] == 'operate'
    assert metadata[0]['delivery_mode'] == 'draft_delayed'
    assert 'NEVER_PROJECT' not in str(metadata) and 'private.example' not in str(metadata)
