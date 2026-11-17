#!/usr/bin/env python3
# test_orchestration_plan_derivation_and_feedback.py
"""
Functional test for server-derived plan fields, named planner corrections and prompt scope.
Version: 0.261.454
Implemented in: 0.261.453

This test ensures that the server fills the plan fields it can determine, that a rejected
plan tells the planner what was wrong by name without logging those names, that retrieval
routing reads no request wording, and that orchestration prompts carry no scenario wording.
"""

from copy import deepcopy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_dependency_planner import planner  # noqa: E402,F401 (fixture)
from test_orchestration_dependency_runtime import binding, compose, runtime  # noqa: E402,F401 (fixture)

APPLICATION = Path(__file__).resolve().parents[1] / "application" / "single_app"
PROMPT_SOURCES = (
    "functions_orchestration_planner.py",
    "functions_orchestration_composition.py",
    "functions_orchestration_native_results.py",
)
# Wording that once patched a single test scenario into a prompt. None may return.
SCENARIO_TERMS = (
    "call sign", "presidents", "eating and drinking", "opening hours", "wednesday",
    "exercise label", "travel route", "dated monetary", "exceedance", "prior-period",
    "kind of business",
)
INTENT_PATTERN_NAMES = (
    "ACKNOWLEDGMENT_PATTERN", "TRANSFORMATION_PATTERN", "CONVERSATION_TARGET_PATTERN",
    "EXPLICIT_RETRIEVAL_PATTERN",
)


def _plan(planner, replies, monkeypatch=None):
    """Run plan_request against scripted replies; return the result, requests and log records."""
    calls, logged, pending = [], [], list(replies)

    def create(**request):
        calls.append(deepcopy(request))
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason='stop', message=SimpleNamespace(content=json.dumps(pending.pop(0)), refusal=None),
            )],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    if monkeypatch is not None:
        monkeypatch.setattr(planner, 'log_event', lambda message, **kwargs: logged.append((message, kwargs)))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    model = SimpleNamespace(deployment='offline-planner', as_planner_client=lambda: client)
    result = planner.plan_request(
        'Prepare an original short answer.', {'message': 'Prepare an original short answer.'},
        'conversation-1', 'owner', settings={'enable_user_workspace': True}, planner_model=model,
    )
    return result, calls, logged


def test_server_derives_compose_output_and_answer_selection(planner):
    step = compose()
    del step['outputs']
    (kind, plan), calls, _ = _plan(planner, [{'kind': 'plan', 'steps': [step]}])
    assert kind == 'plan' and len(calls) == 1
    assert plan['steps'][0]['outputs'] == [{'name': 'answer', 'kind': 'markdown-v1'}]
    assert plan['final_response'] == binding('draft')


def test_derivation_only_acts_when_exactly_one_value_is_valid(planner):
    schema = sys.modules['functions_orchestration_schema']
    ambiguous = {'steps': [compose('first'), compose('second')]}
    plan, derived = schema.derive_plan_defaults(ambiguous)
    assert 'final_response' not in plan and derived == []

    chained = {'steps': [
        compose('notes'),
        compose('summary', inputs={'notes': {'binding': binding('notes'), 'allow_partial': False}}),
    ]}
    plan, derived = schema.derive_plan_defaults(chained)
    assert plan['final_response'] == binding('summary') and derived == ['final_response']
    assert 'final_response' not in chained

    explicit = {'steps': [compose('first'), compose('second')], 'final_response': binding('first')}
    plan, derived = schema.derive_plan_defaults(explicit)
    assert plan['final_response'] == binding('first') and derived == []

    structured = {'steps': [compose('data', outputs=[{'name': 'data', 'kind': 'structured-v1'}])]}
    plan, derived = schema.derive_plan_defaults(structured)
    assert 'final_response' not in plan and derived == []


def test_complete_tabular_composition_drops_a_conflicting_policy(planner):
    schema = sys.modules['functions_orchestration_schema']
    step = compose()
    step['arguments'].update(
        response_policy=schema.AVAILABLE_INFORMATION_POLICY,
        tabular_requirement={'mode': 'calculation', 'document_ids': ['doc-1']},
    )
    plan, derived = schema.derive_plan_defaults({'steps': [step], 'final_response': binding('draft')})
    assert 'response_policy' not in plan['steps'][0]['arguments']
    assert 'complete_tabular_policy' in derived
    overview = compose()
    overview['arguments'].update(
        response_policy=schema.AVAILABLE_INFORMATION_POLICY,
        tabular_requirement={'mode': 'overview', 'document_ids': ['doc-1']},
    )
    plan, _ = schema.derive_plan_defaults({'steps': [overview], 'final_response': binding('draft')})
    assert plan['steps'][0]['arguments']['response_policy'] == schema.AVAILABLE_INFORMATION_POLICY


def test_rejected_arguments_are_named_to_the_planner_and_never_logged(planner, monkeypatch):
    wrong_one, wrong_two = compose('first'), compose('second')
    wrong_one['arguments']['PRIVATE_TONE_ARGUMENT'] = 'warm'
    wrong_two['arguments']['PRIVATE_LENGTH_ARGUMENT'] = 3
    wrong_two['inputs'] = {'first': {'binding': binding('first'), 'allow_partial': False}}
    (kind, plan), calls, logged = _plan(planner, [
        {'kind': 'plan', 'steps': [wrong_one, wrong_two], 'final_response': binding('second')},
        {'kind': 'plan', 'steps': [compose()], 'final_response': binding('draft')},
    ], monkeypatch)
    assert kind == 'plan' and len(calls) == 2
    correction = calls[1]['messages'][-1]['content']
    # Both failing steps are reported in one correction, with the allowed names.
    assert 'PRIVATE_TONE_ARGUMENT' in correction and 'PRIVATE_LENGTH_ARGUMENT' in correction
    assert 'allowed_arguments' in correction and '"instruction"' in correction
    assert 'PRIVATE_' not in repr(logged)


def test_unknown_step_field_and_unused_selection_are_named(planner):
    schema = sys.modules['functions_orchestration_schema']
    step = {**compose(), 'PRIVATE_FIELD': True}
    try:
        schema.validate_dependency_plan(
            {'steps': [step], 'final_response': binding('draft')}, available_capability_ids=['compose'],
        )
        raise AssertionError('The unknown step field was accepted.')
    except schema.PlanValidationError as error:
        assert error.rule == 'step_shape_invalid'
        assert error.feedback['unknown_step_fields'] == ['PRIVATE_FIELD']
        assert 'PRIVATE_FIELD' not in repr(error.diagnostics)
        assert 'PRIVATE_FIELD' in planner.plan_repair_message(error)
    try:
        schema.validate_plan_requirements(
            {'steps': [{'capability_id': 'compose', 'arguments': {}}]}, {'document_ids': ['doc-PRIVATE']},
        )
        raise AssertionError('The unused selection was accepted.')
    except schema.PlanValidationError as error:
        assert error.feedback['unused_selected_document_ids'] == ['doc-PRIVATE']
        assert 'doc-PRIVATE' not in repr(error.diagnostics) and 'doc-PRIVATE' not in str(error)


def test_retrieval_routing_reads_structured_input_not_wording(planner):
    refused = {'requires_retrieval': False}
    for wording in ('Search the web for the latest prices.', 'thanks', 'Rewrite your answer.'):
        assert planner.conversation_retrieval_allowed(refused, wording) is False
        assert planner.conversation_retrieval_allowed({'requires_retrieval': True}, wording) is True
    assert planner.conversation_retrieval_allowed(refused, 'thanks', {'document_ids': ['doc-1']}) is True
    assert planner.conversation_retrieval_allowed(refused, 'thanks', {'web_search': True}) is True
    assert planner.conversation_retrieval_allowed(None, 'thanks') is True


def test_prompt_sections_follow_the_offered_capabilities(planner):
    registry = sys.modules['functions_orchestration_registry']
    known = set(registry.all_capability_ids())
    scoped = [scope for scope, _ in planner.PLANNER_PROMPT_SECTIONS if scope is not None]
    assert scoped and all(set(scope) <= known for scope in scoped)
    assert planner.planner_system_prompt(None) == planner.PLANNER_SYSTEM_PROMPT
    assert planner.planner_system_prompt(known) == planner.PLANNER_SYSTEM_PROMPT

    compose_only = planner.planner_system_prompt(['compose'])
    assert len(compose_only) < len(planner.PLANNER_SYSTEM_PROMPT)
    for absent in ('Research depth.', 'tabular-relate-v1', 'Agents and actions.', 'Images. Generate each image'):
        assert absent not in compose_only
    for present in ('Plan bounded work', 'Answer basis.', 'Deliverables.', 'Clarifications.'):
        assert present in compose_only
    assert 'Research depth.' in planner.planner_system_prompt(['compose', 'web_search'])
    assert 'tabular-relate-v1' in planner.planner_system_prompt(['compose', 'tabular_analyze'])

    (_, _), calls, _ = _plan(planner, [{'kind': 'plan', 'steps': [compose()]}])
    assert 'Research depth.' not in calls[0]['messages'][0]['content']


def test_orchestration_prompts_hold_no_scenario_wording_or_intent_patterns():
    for name in PROMPT_SOURCES:
        source = (APPLICATION / name).read_text(encoding='utf-8')
        lowered = source.lower()
        found = [term for term in SCENARIO_TERMS if term in lowered]
        assert not found, f'{name} contains scenario wording: {found}'
    planner_source = (APPLICATION / PROMPT_SOURCES[0]).read_text(encoding='utf-8')
    assert not [name for name in INTENT_PATTERN_NAMES if name in planner_source]
    assert 're.compile(' not in planner_source


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
