# test_orchestration_plan_schema.py
"""
Functional test for the chat orchestration plan contract and validator.
Version: 0.261.139
Implemented in: 0.261.085
Single orchestration contract updated in: 0.261.139

Planner output is untrusted input. A plan arrives as JSON written by a language model,
and naming a capability that does not exist, using one an administrator disabled,
referencing a document the user cannot read, or producing a dependency cycle are all
normal failure modes.

The removed legacy contract repaired those plans. Gather / Reason / Render refuses them
without repair so no adapter can run work the server did not approve.
"""

import os
import sys
from copy import deepcopy

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.orchestration_research import stubbed_orchestration_imports as stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

SETTINGS = {
    'enable_user_workspace': True,
    'enable_web_search': True,
    'chat_orchestration_max_steps': 6,
    'document_action_capabilities': {
        'analyze': {'enabled': True, 'chat_max_documents': 2},
        'comparison': {'enabled': True, 'chat_max_documents': 2},
    },
}


def _binding(step_id, output='answer'):
    return {
        'version': 'orchestration-input-binding-v1',
        'step_id': step_id,
        'output_name': output,
        'existing_result': None,
    }


def _compose(step_id='draft', *, depends_on=None, inputs=None):
    return {
        'step_id': step_id,
        'capability_id': 'compose',
        'arguments': {'instruction': f'Prepare {step_id}.'},
        'depends_on': list(depends_on or []),
        'inputs': inputs or {},
        'outputs': [{'name': 'answer', 'kind': 'markdown-v1'}],
    }


def _search(step_id='find', *, document_ids=None):
    arguments = {'query': 'contracts'}
    if document_ids is not None:
        arguments['document_ids'] = list(document_ids)
    return {'step_id': step_id, 'capability_id': 'document_search', 'arguments': arguments}


def _normalize(raw, **kwargs):
    with stubbed_app_imports():
        import functions_orchestration_schema as schema

        return schema.normalize_plan(
            raw,
            'conv1',
            'user1',
            settings=kwargs.pop('settings', SETTINGS),
            available_capability_ids=kwargs.pop('available_capability_ids', ['compose', 'document_search', 'document_analyze']),
            contract_version=2,
            **kwargs,
        )


def test_legacy_plan_markers_fail_closed_without_repair():
    """Plans from the removed contract are refused, not repaired into new plans."""
    with stubbed_app_imports():
        import functions_orchestration_schema as schema

        for legacy in ({'steps': []}, {'planner_contract_version': 1, 'steps': []}, None):
            assert schema.is_legacy_plan(legacy) is True
            with pytest.raises(schema.LegacyPlanError) as failure:
                schema.plan_contract_version(legacy)
            assert failure.value.code == schema.LEGACY_PLAN_CODE

        with pytest.raises(schema.LegacyPlanError):
            schema.normalize_plan({'planner_contract_version': 1, 'steps': []}, 'conv1', 'user1', settings=SETTINGS, contract_version=1)


def test_rejects_unknown_disabled_and_unauthorized_sources_without_mutation():
    """Invalid capabilities and sources are rejected as errors, never trimmed or dropped."""
    with stubbed_app_imports():
        import functions_orchestration_schema as schema

        cases = [
            ({'planner_contract_version': 2, 'steps': [
                {'step_id': 'ghost', 'capability_id': 'not_a_capability', 'arguments': {}},
            ]}, {}, 'capability_unavailable'),
            ({'planner_contract_version': 2, 'steps': [
                {'step_id': 'read', 'capability_id': 'document_analyze', 'arguments': {
                    'analysis_prompt': 'Summarise.', 'document_ids': ['doc1'],
                }},
            ]}, {'available_capability_ids': ['compose', 'document_search']}, 'capability_unavailable'),
            ({'planner_contract_version': 2, 'steps': [
                {'step_id': 'find', 'capability_id': 'document_search', 'arguments': {
                    'query': 'contracts', 'document_ids': ['ok1', 'stolen'],
                }},
            ]}, {'authorized_document_ids': {'ok1'}}, None),
        ]
        for raw, kwargs, code in cases:
            original = deepcopy(raw)
            with pytest.raises(schema.PlanValidationError) as failure:
                _normalize(raw, **kwargs)
            if code:
                assert failure.value.code == code
            assert raw == original, 'validation must not repair planner JSON in place'


def test_schema_arguments_are_strict_instead_of_coerced_or_repaired():
    """Bad types, unknown fields, and missing required arguments stop the plan."""
    with stubbed_app_imports():
        import functions_orchestration_schema as schema

        invalid_steps = [
            {'step_id': 'find', 'capability_id': 'document_search', 'arguments': {'query': 'q', 'top_n': '5'}},
            {'step_id': 'find', 'capability_id': 'document_search', 'arguments': {'query': 'q', 'smuggled': True}},
            {'step_id': 'find', 'capability_id': 'document_search', 'arguments': {}},
        ]
        for step in invalid_steps:
            with pytest.raises(schema.PlanValidationError):
                _normalize({'planner_contract_version': 2, 'steps': [step]})


def test_dependency_cycles_and_step_budgets_are_refused():
    """Dependency structure is compiled or rejected; it is not reordered into validity."""
    with stubbed_app_imports():
        import functions_orchestration_schema as schema

        cyclic = {'planner_contract_version': 2, 'steps': [
            _compose('a', depends_on=['b']),
            _compose('b', depends_on=['a']),
        ]}
        with pytest.raises(schema.PlanValidationError) as failure:
            _normalize(cyclic)
        assert failure.value.code == 'result_binding_cycle'

        too_long = {
            'planner_contract_version': 2,
            'steps': [_compose(f's{i}') for i in range(4)],
        }
        with pytest.raises(schema.PlanValidationError) as failure:
            _normalize(too_long, available_capability_ids=['compose'], settings={**SETTINGS, 'chat_orchestration_max_steps': 3})
        assert failure.value.code == 'result_step_limit'


def test_edits_narrow_dependency_plans_and_preserve_final_response():
    """A user edit may remove work, but not the producer selected as the answer."""
    plan = _normalize({
        'planner_contract_version': 2,
        'steps': [
            _search('find', document_ids=['doc1', 'doc2']),
            _compose('draft', depends_on=['find'], inputs={'sources': {
                'binding': _binding('find', 'prepared'), 'allow_partial': False,
            }}),
        ],
        'final_response': _binding('draft'),
    }, authorized_document_ids={'doc1', 'doc2'})

    with stubbed_app_imports():
        import functions_orchestration_schema as schema

        schema.apply_plan_edits(plan, {'removed_document_ids': {'find': ['doc2']}})
        find = next(step for step in plan['steps'] if step['step_id'] == 'find')
        assert find['arguments']['document_ids'] == ['doc1']
        assert plan['approval']['edited'] is True

        original = deepcopy(plan)
        with pytest.raises(schema.PlanValidationError):
            schema.apply_plan_edits(plan, {'disabled_step_ids': ['draft']})
        assert plan == original


def test_approval_mode_decides_initial_status():
    """Auto-approval runs on arrival; timed and manual both wait."""
    with stubbed_app_imports():
        import functions_orchestration_schema as schema

        body = {
            'planner_contract_version': 2,
            'steps': [_compose('draft')],
            'final_response': _binding('draft'),
        }
        auto = schema.normalize_plan(
            deepcopy(body), 'c', 'u', settings=SETTINGS, approval_mode='auto',
            available_capability_ids=['compose'], contract_version=2,
        )
        assert auto['status'] == schema.PLAN_STATUS_APPROVED
        assert auto['approval']['state'] == schema.APPROVAL_STATE_APPROVED

        for mode in ('manual', 'timed'):
            waiting = schema.normalize_plan(
                deepcopy(body), 'c', 'u', settings=SETTINGS, approval_mode=mode,
                available_capability_ids=['compose'], contract_version=2,
            )
            assert waiting['status'] == schema.PLAN_STATUS_AWAITING_APPROVAL
            assert waiting['approval']['state'] == schema.APPROVAL_STATE_PENDING

        unknown = schema.normalize_plan(
            deepcopy(body), 'c', 'u', settings=SETTINGS, approval_mode='nonsense',
            available_capability_ids=['compose'], contract_version=2,
        )
        assert unknown['approval']['mode'] == 'manual'


def _run_script():
    assert_app_version_at_least('0.261.139')
    tests = [
        test_legacy_plan_markers_fail_closed_without_repair,
        test_rejects_unknown_disabled_and_unauthorized_sources_without_mutation,
        test_schema_arguments_are_strict_instead_of_coerced_or_repaired,
        test_dependency_cycles_and_step_budgets_are_refused,
        test_edits_narrow_dependency_plans_and_preserve_final_response,
        test_approval_mode_decides_initial_status,
    ]
    passed = 0
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            passed += 1
            print('Test passed!')
        except Exception as exc:
            print(f'Test failed: {exc}')
            import traceback
            traceback.print_exc()
    print(f"\nResults: {passed}/{len(tests)} tests passed")
    return passed == len(tests)


if __name__ == '__main__':
    sys.exit(0 if _run_script() else 1)
