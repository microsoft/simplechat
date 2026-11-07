# test_orchestration_executor.py
"""
Functional test for the chat orchestration step executor.
Version: 0.261.139
Implemented in: 0.261.085
Single orchestration contract updated in: 0.261.139

The executor turns a validated Gather / Reason / Render plan into retained results and a
selected final response. Its refusal behavior still matters: failed required work blocks
consumers, optional inputs may be disclosed and skipped, cancellation is honored, and work
is reauthorized before finalization. The full source-reauthorization matrix is covered by
``test_orchestration_dependency_runtime.py::test_current_access_and_cancellation_fail_closed``.
"""

import os
import socket
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.orchestration_research import document_action_policy_module  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

SETTINGS = {'enable_user_workspace': True, 'chat_orchestration_max_steps': 8}


def _binding(step_id, output='answer'):
    return {
        'version': 'orchestration-input-binding-v1',
        'step_id': step_id,
        'output_name': output,
        'existing_result': None,
    }


def _source_input(step_id, output='answer', *, optional=False):
    return {'binding': _binding(step_id, output), 'allow_partial': False, **({'optional': True} if optional else {})}


def _compose(step_id='draft', *, inputs=None, depends_on=None, optional=False):
    return {
        'step_id': step_id,
        'capability_id': 'compose',
        'arguments': {'instruction': f'Prepare {step_id}.', 'knowledge_basis': 'general_knowledge'},
        'inputs': inputs or {},
        'outputs': [{'name': 'answer', 'kind': 'markdown-v1'}],
        'depends_on': list(depends_on or []),
        'optional': optional,
    }


def _runtime(raw_steps, replies=None, *, final_response=None):
    sys.modules['functions_document_actions'] = document_action_policy_module()
    with stubbed_app_imports(), patch.object(socket.socket, 'connect', side_effect=AssertionError('external I/O')):
        import functions_orchestration_executor as executor
        import functions_orchestration_schema as schema
        from functions_orchestration_results import NamedOutput
        from test_support.orchestration_results import ResultFixture, complete

        plan = schema.normalize_plan(
            {
                'planner_contract_version': 2,
                'steps': deepcopy(raw_steps),
                'run_id': 'run-1',
                'plan_id': 'plan-1',
                'turn_id': 'turn-1',
                **({'final_response': final_response} if final_response else {}),
            },
            'conversation-1',
            'owner',
            settings=SETTINGS,
            contract_version=2,
            available_capability_ids=['compose'],
        )
        fixture = ResultFixture(blob=True)
        fixture.runs['run-1'] = {
            'id': 'run-1', 'user_id': 'owner', 'conversation_id': 'conversation-1',
            'attempt_index': 1, 'status': 'running', 'plan': deepcopy(plan),
        }
        service = fixture.restart()
        context = executor.RunContext(
            run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
            user_message='Prepare the requested content.', plan_contract_version=2,
            result_service=service, result_guard_token_for_step=lambda step_id: 'server-attempt-token',
        )
        order = []
        failures = set(replies or ()) if isinstance(replies, (set, frozenset)) else set()
        texts = replies if isinstance(replies, dict) else {}

        def adapter(step, context, *, settings, user_id, emit, cancel_requested):
            order.append(step['step_id'])
            if step['step_id'] in failures:
                return schema.build_step_result(status=schema.STEP_STATUS_FAILED, failure=schema.build_failure('step_failed'))
            producer = context.result_producer(step)
            task = context.result_service.persist_task_result(
                producer=producer,
                role='reason',
                status='complete',
                outputs=[NamedOutput('answer', 'markdown-v1', texts.get(step['step_id'], f"answer:{step['step_id']}"), complete(1))],
                sources=[],
                origin='generated',
                guard_token=context.result_guard_token_for_step(step['step_id']),
            )
            return schema.build_step_result(task_result=task)

        return SimpleNamespace(
            executor=executor, schema=schema, plan=plan, context=context,
            settings=SETTINGS, adapter=adapter, order=order,
        )


def test_steps_run_in_dependency_order_and_final_response_is_selected():
    case = _runtime([
        _compose('draft'),
        _compose('answer', inputs={'draft': _source_input('draft')}, depends_on=['draft']),
    ], {'draft': 'intermediate', 'answer': 'final answer'}, final_response=_binding('answer'))
    result = case.executor.execute_plan(
        case.plan, case.context, settings=case.settings, user_id='owner', get_adapter=lambda capability: case.adapter,
    )
    assert case.order == ['draft', 'answer']
    assert result['status'] == case.schema.PLAN_STATUS_COMPLETED
    assert result['message'] == 'final answer'
    assert result['final_response']['output_name'] == 'answer'


def test_disabled_and_failed_required_dependencies_are_skipped():
    disabled = _runtime([
        {**_compose('extra'), 'enabled': False},
        _compose('answer'),
    ], final_response=_binding('answer'))
    result = disabled.executor.execute_plan(
        disabled.plan, disabled.context, settings=disabled.settings, user_id='owner', get_adapter=lambda capability: disabled.adapter,
    )
    statuses = {step['step_id']: step['status'] for step in result['steps']}
    assert statuses['extra'] == disabled.schema.STEP_STATUS_SKIPPED
    assert statuses['answer'] == disabled.schema.STEP_STATUS_COMPLETED

    failed = _runtime([
        _compose('draft'),
        _compose('answer', inputs={'draft': _source_input('draft')}, depends_on=['draft']),
    ], {'draft'}, final_response=_binding('answer'))
    result = failed.executor.execute_plan(
        failed.plan, failed.context, settings=failed.settings, user_id='owner', get_adapter=lambda capability: failed.adapter,
    )
    statuses = {step['step_id']: step['status'] for step in result['steps']}
    assert statuses['draft'] == failed.schema.STEP_STATUS_FAILED
    assert statuses['answer'] == failed.schema.STEP_STATUS_SKIPPED
    assert 'answer' not in failed.order


def test_optional_input_producer_failure_does_not_block_general_knowledge_answer():
    case = _runtime([
        _compose('source', optional=True),
        _compose('answer', inputs={'maybe': _source_input('source', optional=True)}, depends_on=['source']),
    ], {'source'}, final_response=_binding('answer'))
    result = case.executor.execute_plan(
        case.plan, case.context, settings=case.settings, user_id='owner', get_adapter=lambda capability: case.adapter,
    )
    assert case.order == ['source', 'answer']
    statuses = {step['step_id']: step['status'] for step in result['steps']}
    assert statuses['source'] == case.schema.STEP_STATUS_FAILED
    assert statuses['answer'] == case.schema.STEP_STATUS_COMPLETED
    assert result['status'] == case.schema.PLAN_STATUS_COMPLETED


def test_cancellation_stops_before_work_and_missing_adapter_fails_closed():
    cancelled = _runtime([_compose('draft')], final_response=_binding('draft'))
    result = cancelled.executor.execute_plan(
        cancelled.plan, cancelled.context, settings=cancelled.settings, user_id='owner',
        cancel_requested=lambda: True, get_adapter=lambda capability: cancelled.adapter,
    )
    assert cancelled.order == []
    assert result['status'] == cancelled.schema.PLAN_STATUS_CANCELLED

    missing = _runtime([_compose('draft')], final_response=_binding('draft'))
    result = missing.executor.execute_plan(
        missing.plan, missing.context, settings=missing.settings, user_id='owner', get_adapter=lambda capability: None,
    )
    assert result['status'] == missing.schema.PLAN_STATUS_FAILED
    assert result['steps'][0]['status'] == missing.schema.STEP_STATUS_FAILED
    assert result['steps'][0]['failure']['code']


def test_legacy_or_mismatched_contract_refuses_before_execution():
    case = _runtime([_compose('draft')], final_response=_binding('draft'))
    legacy = deepcopy(case.plan)
    legacy.pop('planner_contract_version', None)
    with pytest.raises(case.schema.LegacyPlanError):
        case.executor.execute_plan(legacy, case.context, settings=case.settings, user_id='owner')

    case.context.plan_contract_version = 1
    with pytest.raises(Exception):
        case.executor.execute_plan(case.plan, case.context, settings=case.settings, user_id='owner')


def _run_script():
    assert_app_version_at_least('0.261.139')
    tests = [
        test_steps_run_in_dependency_order_and_final_response_is_selected,
        test_disabled_and_failed_required_dependencies_are_skipped,
        test_optional_input_producer_failure_does_not_block_general_knowledge_answer,
        test_cancellation_stops_before_work_and_missing_adapter_fails_closed,
        test_legacy_or_mismatched_contract_refuses_before_execution,
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
