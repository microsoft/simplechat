# test_orchestration_dependency_native_failure.py
"""Real native Compare failures remain diagnostic-only through the v2 executor.

Version: 0.261.127
Implemented in: 0.261.127
Only source, model and storage I/O are isolated by the shared native fixture.
"""

import json

import pytest

from test_orchestration_internal_analysis import internal


def test_all_failed_native_compare_survives_runtime_handoff_without_consumable_results(internal):
    # Import the executor after the fixture installs the native I/O/bootstrap boundary.
    from functions_orchestration_executor import RunContext, execute_plan
    from functions_orchestration_result_contracts import ResultContractError, TaskResult
    from functions_orchestration_schema import normalize_plan

    internal.state.update(mode='compare', failed_targets={'target-1', 'target-2'})
    settings = {'enable_user_workspace': True}
    plan = normalize_plan({
        'run_id': 'run-1', 'steps': [{
            'step_id': 'compare', 'capability_id': 'document_compare', 'arguments': {
                'left_document_id': 'document-1', 'right_document_ids': ['target-1', 'target-2'],
                'comparison_prompt': 'Compare every selected target.',
            },
        }],
    }, 'conversation-1', 'owner', settings=settings, contract_version=2,
        available_capability_ids=['document_compare'])
    internal.fixture.runs['run-1']['plan'] = plan
    context = RunContext(
        run_id='run-1', plan_id=plan['plan_id'], conversation_id='conversation-1', user_id='owner',
        user_message='Compare every selected target.', plan_contract_version=2,
        result_service=internal.fixture.service, resolve_source_manifest=internal.fixture.resolve,
        invoke_prompt=internal.context.invoke_prompt,
        result_guard_token_for_step=internal.context.result_guard_token_for_step,
    )
    context.analysis_checkpoint_factory = internal.context.analysis_checkpoint_factory
    events = []
    result = execute_plan(plan, context, settings=settings, user_id='owner', emit=events.append)
    assert result['status'] == result['outcome'] == 'failed'
    step = result['steps'][0]
    task = TaskResult.from_dict(step['task_result'])
    assert task.status == 'failed'
    assert {reference.output_name for reference in task.outputs} == {'comparison', 'coverage'}
    assert all(reference.completeness.status == 'failed' for reference in task.outputs)
    assert step['checkpoint_available'] is False
    assert result['task_results'] == {} and context.task_results == {}
    assert result['outputs'] == []
    assert all(output['status'] == 'unavailable' and 'reference' not in output for output in result['result_outputs'])
    assert any(event.get('task_result') == task.to_dict() for event in events)
    assert result['artifacts'] == [] and internal.hooks.call_count == 0
    assert 'Private provider error' not in json.dumps(result)
    assert not any(call['stage'] == 'orchestration_compose' for call in internal.state['calls'])
    reader_service = internal.fixture.restart()
    for reference in task.outputs:
        with pytest.raises(ResultContractError):
            reader_service.open_result(reference, allow_partial=True)
