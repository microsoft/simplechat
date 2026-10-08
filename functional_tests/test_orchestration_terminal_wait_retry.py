# test_orchestration_terminal_wait_retry.py
"""A run that ends while a step still waits can be retried, and the wait runs again.

Version: 0.261.302
Implemented in: 0.261.302

A waiting run whose continuation failed as a whole kept its waiting step. The recovery
projection then reported "Required computation is still pending" and preparing a retry raised
``result_not_ready``, so the failed run could never be retried. Once the attempt has ended,
nothing will finish its wait: a retry now runs the waiting step again and reuses only completed
work. A wait in a run that can still continue keeps blocking a retry. Real leases, checkpoints
and retained results run; only storage transport and producer/model I/O are isolated.
"""

from types import SimpleNamespace

import pytest

from test_orchestration_dependency_recovery import durable  # noqa: F401
from test_orchestration_dependency_runtime import runtime  # noqa: F401
from test_orchestration_waiting_continuation import start_waiting
from test_support.versioning import assert_app_version_at_least


def _snapshot_context(run_id):
    return SimpleNamespace(
        run_id=run_id, user_message='Explain the flagged filing', memory_context={}, selected_document_ids=[],
        plan_contract_version=2, task_results={}, result_aliases={}, pending_results={},
        execution_deadline_at='2030-01-01T00:00:00+00:00', composition_profiles={},
    )


def _pending_task(runtime, run_id):
    producer = runtime.contracts.ProducerIdentity(
        'owner', 'conversation-1', run_id, 1, 'waited', 'tabular_analyze', 'tabular-analyze-v1',
    )
    return runtime.contracts.TaskResult(producer, 'reason', 'pending', ())


def _snapshot_with_wait(runtime, run_id):
    checkpoints = runtime.checkpoints
    state = checkpoints.context_state(_snapshot_context(run_id))
    state['task_results'] = {'waited': _pending_task(runtime, run_id).to_dict()}
    state['pending_results'] = {'waited': {'kind': 'native_tabular_compute', 'job_id': 'old-attempt-job'}}
    return {'state': state}


def _fail_while_waiting(durable, status='failed'):
    """End the waiting attempt the way a failed continuation publishes it."""
    start_waiting(durable)
    record = durable.read_run('run-1')
    failure = durable.runtime.schema.build_failure('recovery_changed')
    return durable.recovery._replace(record, {
        'status': status, 'outcome': status, 'failure': failure, 'failures': [failure],
        'error': failure['message'], 'execution_lease': None,
        'finalization_status': 'saved', 'message_saved': True,
    })


def test_version_includes_the_terminal_wait_retry_fix():
    assert_app_version_at_least('0.261.302')


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_an_ended_attempt_offers_retry_that_runs_its_wait_again(durable, status):
    ended = _fail_while_waiting(durable, status)
    reconciled = durable.recovery.reconcile_checkpoints(ended, lambda: True)
    states = {step['step_id']: step['status'] for step in reconciled['execution_steps']}
    assert states['failed'] == 'waiting'

    projection = durable.recovery.recovery_projection(reconciled)
    assert projection['eligible'] is True
    assert projection['reason_code'] is None
    assert projection['reused_step_ids'] == ['retained']
    assert projection['retry_step_ids'] == ['failed', 'dependent']

    payloads = durable.recovery.validate_resume(
        ended, durable.fresh_context(ended), durable.case.settings, lambda: True, source_run_id=ended['id'],
    )
    assert list(payloads) == ['retained']


def test_the_retry_reuses_completed_work_and_finishes_the_interrupted_step(durable):
    original = _fail_while_waiting(durable)
    child = durable.prepare()
    assert child['retry_of_run_id'] == 'run-1'
    assert child['retry_reused_step_ids'] == ['retained']
    assert 'pending_results' not in child and 'task_results' not in child

    child = durable.recovery._replace(child, {'status': 'running', 'execution_lease': durable.recovery.lease_fields()})
    durable.case.model.replies.extend(['Interrupted work finished this time.', 'Answer from both results.'])
    result = durable.run(child, durable.fresh_context(child))
    assert result['status'] == 'completed', result
    assert [step['step_id'] for step in result['steps'] if step.get('reused')] == ['retained']
    assert result['pending_results'] == {}
    assert result['task_results']['retained'] == original['task_results']['retained']
    parent = durable.read_run('run-1')
    assert parent['latest_attempt_run_id'] == child['id']
    assert parent['status'] == 'failed'


def test_a_wait_in_a_run_that_can_continue_still_blocks_retry(durable):
    start_waiting(durable)
    record = durable.read_run('run-1')
    assert record['status'] == 'waiting'
    reconciled = durable.recovery.reconcile_checkpoints(record, lambda: True)
    projection = durable.recovery.recovery_projection(reconciled)
    assert projection['eligible'] is False
    assert projection['reason_code'] == 'result_not_ready'
    with pytest.raises(durable.runtime.checkpoints.CheckpointError) as failure:
        durable.recovery.validate_resume(
            record, durable.fresh_context(record), durable.case.settings, lambda: True,
        )
    assert failure.value.code == 'result_not_ready'


def test_a_new_attempt_does_not_restore_an_ended_attempts_wait(runtime):
    # Restored before the new attempt reaches the step: it must not wait on the old job.
    context = _snapshot_context('run-2')
    runtime.checkpoints.restore_context(context, _snapshot_with_wait(runtime, 'run-1'))
    assert context.task_results == {} and context.pending_results == {}


def test_a_new_attempt_keeps_its_own_result_for_a_step_that_waited_before(runtime):
    # Restored after the new attempt reached the step again: its own result stands.
    context = _snapshot_context('run-2')
    own = runtime.contracts.TaskResult(
        runtime.contracts.ProducerIdentity(
            'owner', 'conversation-1', 'run-2', 2, 'waited', 'tabular_analyze', 'tabular-analyze-v1',
        ), 'reason', 'pending', (),
    )
    context.task_results['waited'] = own
    runtime.checkpoints.restore_context(context, _snapshot_with_wait(runtime, 'run-1'))
    assert context.task_results == {'waited': own}
    assert context.pending_results == {}


def test_the_same_attempt_still_restores_its_own_wait(runtime):
    context = _snapshot_context('run-1')
    runtime.checkpoints.restore_context(context, _snapshot_with_wait(runtime, 'run-1'))
    assert context.task_results['waited'] == _pending_task(runtime, 'run-1')
    assert context.pending_results == {'waited': {'kind': 'native_tabular_compute', 'job_id': 'old-attempt-job'}}
