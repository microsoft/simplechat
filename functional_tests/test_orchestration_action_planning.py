# test_orchestration_action_planning.py
"""Functional coverage for Gather action planning and opt-in.

Version: 0.261.139
Implemented in: 0.261.098
Single plan contract: 0.261.139

Exercises the real registry, planner and validator with model/storage seams mocked.
"""

import importlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_support.app_stubs import stubbed_config
from test_support.orchestration_research import document_action_policy_module


SETTINGS = {
    'enable_chat_orchestration': True,
    'enable_chat_orchestration_actions': True,
    'enable_semantic_kernel': True,
}
ACTION = {
    'action_ref': 'personal:actor:tickets',
    'id': 'tickets',
    'name': 'tickets',
    'display_name': 'Ticket lookup',
    'description': 'Look up ticket status.',
    'type': 'openapi',
    'scope_type': 'personal',
    'scope_id': 'actor',
    'scope_label': 'Personal',
}


@pytest.fixture(scope='module')
def modules():
    with stubbed_config(cognitive_services_scope='https://cognitiveservices.azure.com/.default'), patch.dict(
        sys.modules, {'functions_document_actions': document_action_policy_module()},
    ):
        yield SimpleNamespace(**{
            name: importlib.import_module(f'functions_orchestration_{name}')
            for name in ('registry', 'context', 'schema', 'planner')
        })


# Request-time services an external Gather step needs; the tests supply inert callables.
BINDINGS = {
    name: (lambda *args, **kwargs: None) for name in (
        'external_source_admission', 'external_source_preflight',
        'capture_external_source_configuration', 'external_source_authorizer',
    )
}


def bound(**context):
    return {**BINDINGS, **context}


def binding(step_id, output_name):
    return {
        'version': 'orchestration-input-binding-v1', 'step_id': step_id,
        'output_name': output_name, 'existing_result': None,
    }


def raw_plan(action_ref=ACTION['action_ref']):
    return {
        'steps': [
            {'capability_id': 'action_invoke', 'step_id': 'lookup',
             'arguments': {'action_ref': action_ref, 'task': 'Find ticket 42.'}},
            {'capability_id': 'compose', 'step_id': 'answer',
             'arguments': {'instruction': 'Report ticket 42.', 'knowledge_basis': 'sources'},
             'inputs': {'findings': {'binding': binding('lookup', 'prepared'), 'allow_partial': False}},
             'outputs': [{'name': 'answer', 'kind': 'markdown-v1'}]},
        ],
        'final_response': binding('answer', 'answer'),
    }


@pytest.mark.parametrize('flag', [
    'enable_chat_orchestration', 'enable_chat_orchestration_actions', 'enable_semantic_kernel',
])
def test_action_access_requires_every_opt_in(modules, flag):
    settings = {key: value for key, value in SETTINGS.items() if key != flag}
    ids = modules.registry.resolve_available_capability_ids(
        settings, allowed_ids=[], request_context=bound(action_catalog=[ACTION]),
    )
    assert 'action_invoke' not in ids
    assert 'compose' in ids


def test_request_catalog_and_capability_narrowing_are_required(modules):
    resolve = modules.registry.resolve_available_capability_ids
    assert 'action_invoke' in resolve(SETTINGS, request_context=bound(action_catalog=[ACTION]))
    assert 'action_invoke' not in resolve(SETTINGS, request_context=bound(action_catalog=[]))
    assert 'action_invoke' not in resolve(
        SETTINGS, allowed_ids=['compose'], request_context=bound(action_catalog=[ACTION]),
    )
    # Without the request-time source services, planning cannot offer the action at all.
    assert 'action_invoke' not in resolve(SETTINGS, request_context={'action_catalog': [ACTION]})


def test_action_lookup_does_not_evaluate_unrelated_capability_gates(modules, monkeypatch):
    checked = []
    original = modules.registry._gates_pass

    def gates(capability, settings):
        checked.append(capability['id'])
        return original(capability, settings)

    monkeypatch.setattr(modules.registry, '_gates_pass', gates)
    assert modules.registry.resolve_available_capability_ids(
        SETTINGS, candidate_ids=('action_invoke',), request_context=bound(action_catalog=[ACTION]),
    ) == ['action_invoke']
    assert checked == ['action_invoke']


def test_discovery_is_skipped_when_disabled_or_an_agent_was_selected(modules, monkeypatch):
    catalog = importlib.import_module('functions_action_catalog')

    def unexpected(*args, **kwargs):
        pytest.fail('Action discovery must not run for this request.')

    monkeypatch.setattr(catalog, 'build_accessible_action_catalog', unexpected)
    assert modules.context.resolve_action_catalog('actor', settings={}) == []
    assert modules.context.resolve_action_catalog(
        'actor', settings=SETTINGS, seeds={'agent': {'name': 'Chosen agent'}},
    ) == []


def test_normalized_plan_identifies_action_safely_with_server_owned_roles(modules):
    plan = modules.schema.normalize_plan(
        raw_plan(), 'conversation', 'actor', settings=SETTINGS,
        available_capability_ids=['action_invoke', 'compose'],
        actions=[{**ACTION, 'auth': {'api_key': 'PRIVATE_CONFIG'}, 'endpoint': 'PRIVATE_HOST'}],
    )
    assert [step['role'] for step in plan['steps']] == ['gather', 'reason']
    assert plan['steps'][1]['depends_on'] == ['lookup']
    assert plan['inputs']['actions'] == [{
        'action_ref': ACTION['action_ref'], 'display_name': 'Ticket lookup', 'scope_label': 'Personal',
    }]
    assert 'PRIVATE_' not in json.dumps(plan)


@pytest.mark.parametrize('actions,ref', [(None, ACTION['action_ref']), ([ACTION], 'forged')])
def test_unoffered_actions_are_refused_rather_than_dropped(modules, actions, ref):
    with pytest.raises(modules.schema.PlanValidationError, match='selected action is unavailable'):
        modules.schema.normalize_plan(
            raw_plan(ref), 'conversation', 'actor', settings=SETTINGS, actions=actions,
            available_capability_ids=['action_invoke', 'compose'],
        )


def test_planner_passes_both_action_and_agent_catalogs_to_validation(modules, monkeypatch):
    plan = raw_plan()
    plan['steps'].insert(1, {
        'capability_id': 'agent_invoke', 'step_id': 'specialist',
        'arguments': {'agent_name': 'specialist', 'task': 'Separate specialist task.'},
    })
    plan['steps'][-1]['inputs']['specialist'] = {
        'binding': binding('specialist', 'prepared'), 'allow_partial': False,
    }
    monkeypatch.setattr(modules.planner, 'resolve_planner_client', lambda settings: (None, 'planner'))
    monkeypatch.setattr(modules.planner, '_call_planner', lambda *args, **kwargs: (json.dumps(plan), None))
    context = modules.context.build_planner_context(
        'Gather findings.', agents=[{'name': 'specialist'}], actions=[ACTION],
    )
    kind, result = modules.planner.plan_request(
        'Gather findings.', context, 'conversation', 'actor', settings=SETTINGS,
        request_context=bound(action_catalog=[ACTION], agent_catalog=[{'name': 'specialist'}]),
    )
    assert kind == 'plan'
    assert {step['capability_id'] for step in result['steps']} == {
        'action_invoke', 'agent_invoke', 'compose',
    }
    assert result['inputs']['actions'][0]['action_ref'] == ACTION['action_ref']


def test_elicitation_retry_keeps_request_gates(modules, monkeypatch):
    replies = iter([json.dumps({'kind': 'elicitation'}), json.dumps(raw_plan())])
    supplied = []

    def complete(_client, _deployment, messages, *args, **kwargs):
        assert kwargs['require_complete_response'] is True
        supplied.append(json.loads(messages[1]['content']))
        return next(replies), None

    monkeypatch.setattr(modules.planner, 'resolve_planner_client', lambda settings: (None, 'planner'))
    monkeypatch.setattr(modules.planner, '_call_planner', complete)

    def reject(*args, **kwargs):
        raise modules.schema.PlanValidationError('Unrenderable question')

    monkeypatch.setattr(modules.planner, 'normalize_elicitation', reject)
    context = modules.context.build_planner_context('Look up ticket 42.', actions=[ACTION])
    with pytest.raises(modules.planner.PlannerError):
        modules.planner.plan_request(
            'Look up ticket 42.', context, 'conversation', 'actor', settings=SETTINGS,
            request_context=bound(action_catalog=[]),
        )
    assert len(supplied) == 2
    assert all('action_invoke' not in item['capability_availability']['available'] for item in supplied)


def test_done_frame_carries_tool_citations_and_artifacts_in_existing_channels():
    with stubbed_config():
        events = importlib.import_module('functions_orchestration_events')
        citation = {'tool_name': 'tickets.lookup', 'function_name': 'lookup', 'function_result': {'status': 'open'}}
        artifact = {'file_name': 'result.csv', 'url': '/api/artifacts/result'}
        event = events.build_run_done_event(
            'conversation', agent_citations=[citation], artifacts=[artifact],
        )
        payload = json.loads(event.removeprefix('data:').strip())
        assert payload['agent_citations'] == [citation]
        assert payload['web_search_citations'] == []
        assert payload['hybrid_citations'] == []
        assert payload['generated_artifacts'] == [artifact]
        assert payload['augmented'] is True


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
