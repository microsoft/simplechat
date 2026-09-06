# test_orchestration_action_planning.py
"""Functional coverage for knowledge-phase action planning and opt-in.

Version: 0.261.098
Implemented in: 0.261.098

Exercises the real registry, planner and validator with model/storage seams mocked.
"""

import ast
import importlib
import json
import sys
from types import SimpleNamespace

import pytest

from test_support.app_stubs import APP_ROOT, stubbed_config


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


@pytest.fixture
def modules():
    with stubbed_config(cognitive_services_scope='https://cognitiveservices.azure.com/.default'):
        yield SimpleNamespace(**{
            name: importlib.import_module(f'functions_orchestration_{name}')
            for name in ('registry', 'context', 'schema', 'planner')
        })


def raw_plan(action_ref=ACTION['action_ref']):
    return {
        'steps': [
            {'capability_id': 'action_invoke', 'step_id': 'lookup',
             'arguments': {'action_ref': action_ref, 'task': 'Find ticket 42.'}},
            {'capability_id': 'respond', 'step_id': 'answer',
             'arguments': {}, 'depends_on': ['lookup']},
        ],
    }


@pytest.mark.parametrize('flag', [
    'enable_chat_orchestration', 'enable_chat_orchestration_actions', 'enable_semantic_kernel',
])
def test_action_access_requires_every_opt_in(modules, flag):
    settings = {key: value for key, value in SETTINGS.items() if key != flag}
    ids = modules.registry.resolve_available_capability_ids(
        settings, allowed_ids=[], request_context={'action_catalog': [ACTION]},
    )
    assert 'action_invoke' not in ids
    assert 'respond' in ids


def test_request_catalog_and_capability_narrowing_are_required(modules):
    resolve = modules.registry.resolve_available_capability_ids
    assert 'action_invoke' in resolve(SETTINGS, request_context={'action_catalog': [ACTION]})
    assert 'action_invoke' not in resolve(SETTINGS, request_context={'action_catalog': []})
    assert 'action_invoke' not in resolve(
        SETTINGS, allowed_ids=['respond'], request_context={'action_catalog': [ACTION]},
    )


def test_action_lookup_does_not_evaluate_unrelated_capability_gates(modules, monkeypatch):
    checked = []
    original = modules.registry._gates_pass

    def gates(capability, settings):
        checked.append(capability['id'])
        return original(capability, settings)

    monkeypatch.setattr(modules.registry, '_gates_pass', gates)
    assert modules.registry.resolve_available_capability_ids(
        SETTINGS, candidate_ids=('action_invoke',), request_context={'action_catalog': [ACTION]},
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


def test_short_action_requests_reach_planning_without_changing_disabled_fast_path(modules):
    question = 'Ticket 42 status?'
    context = modules.context.build_planner_context(question, actions=[ACTION])
    assert modules.planner.triage_request(question, context) != 'trivial'
    assert modules.planner.triage_request(question, {}) == 'trivial'


def test_normalized_plan_identifies_action_safely_and_keeps_phase_order(modules):
    plan = modules.schema.normalize_plan(
        raw_plan(), 'conversation', 'actor', settings=SETTINGS,
        actions=[{**ACTION, 'auth': {'api_key': 'PRIVATE_CONFIG'}, 'endpoint': 'PRIVATE_HOST'}],
    )
    assert [step['phase'] for step in plan['steps']] == ['knowledge', 'reasoning']
    assert plan['inputs']['actions'] == [{
        'action_ref': ACTION['action_ref'], 'display_name': 'Ticket lookup', 'scope_label': 'Personal',
    }]
    assert 'PRIVATE_' not in json.dumps(plan)


@pytest.mark.parametrize('actions,ref', [(None, ACTION['action_ref']), ([ACTION], 'forged')])
def test_unoffered_actions_are_removed_with_visible_errors(modules, actions, ref):
    plan = modules.schema.normalize_plan(
        raw_plan(ref), 'conversation', 'actor', settings=SETTINGS, actions=actions,
    )
    assert all(step['capability_id'] != 'action_invoke' for step in plan['steps'])
    assert plan['validation']['errors']
    assert plan['inputs']['actions'] == []


def test_planner_passes_both_action_and_agent_catalogs_to_validation(modules, monkeypatch):
    plan = raw_plan()
    plan['steps'].insert(1, {
        'capability_id': 'agent_invoke',
        'arguments': {'agent_name': 'specialist', 'task': 'Separate specialist task.'},
    })
    monkeypatch.setattr(modules.planner, 'resolve_planner_client', lambda settings: (None, 'planner'))
    monkeypatch.setattr(modules.planner, '_call_planner', lambda *args: (json.dumps(plan), None))
    context = modules.context.build_planner_context(
        'Gather findings.', agents=[{'name': 'specialist'}], actions=[ACTION],
    )
    kind, result = modules.planner.plan_request(
        'Gather findings.', context, 'conversation', 'actor', settings=SETTINGS,
        request_context={'action_catalog': [ACTION], 'agent_catalog': [{'name': 'specialist'}]},
    )
    assert kind == 'plan'
    assert {step['capability_id'] for step in result['steps']} == {
        'action_invoke', 'agent_invoke', 'respond',
    }
    assert result['inputs']['actions'][0]['action_ref'] == ACTION['action_ref']


def test_elicitation_retry_keeps_request_gates(modules, monkeypatch):
    replies = iter([json.dumps({'kind': 'elicitation'}), json.dumps(raw_plan())])
    monkeypatch.setattr(modules.planner, 'resolve_planner_client', lambda settings: (None, 'planner'))
    monkeypatch.setattr(modules.planner, '_call_planner', lambda *args: (next(replies), None))

    def reject(*args, **kwargs):
        raise modules.schema.PlanValidationError('Unrenderable question')

    monkeypatch.setattr(modules.planner, 'normalize_elicitation', reject)
    context = modules.context.build_planner_context('Look up ticket 42.', actions=[ACTION])
    _, result = modules.planner.plan_request(
        'Look up ticket 42.', context, 'conversation', 'actor', settings=SETTINGS,
        request_context={'action_catalog': []},
    )
    assert all(step['capability_id'] != 'action_invoke' for step in result['steps'])


def test_route_combines_answer_and_action_usage_without_dropping_either():
    tree = ast.parse((APP_ROOT / 'route_backend_orchestration.py').read_text(encoding='utf-8'))
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name in ('_combined_token_usage', '_sum_token_usage')
    ]
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<usage-helper>', 'exec'), namespace)
    action_usage = {
        'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
        'agent_breakdown': [{'agent': 'specialist', 'usage': {'total_tokens': 15}}],
    }
    assert namespace['_combined_token_usage'](
        {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}, action_usage,
    ) == {
        'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20,
        'agent_breakdown': action_usage['agent_breakdown'],
    }
    assert action_usage['total_tokens'] == 15


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
