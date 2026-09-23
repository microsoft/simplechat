# test_orchestration_dependency_recovery.py
"""Real leases, checkpoint restart, DAG reuse and current authorization for v2.

Version: 0.261.127
Implemented in: 0.261.127
Only Cosmos/Blob transport, model responses and current source access are isolated.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_orchestration_dependency_runtime import binding, compose, runtime, source_input
from test_support.app_stubs import stubbed_config
from test_support.orchestration_revisions import AtomicMemoryContainer


@pytest.fixture
def durable(runtime):
    case = runtime.make(
        [compose('failed'), compose('retained'), compose('dependent', inputs={'draft': source_input('retained', 'answer')},
                                                     depends_on=['failed'])],
        ['Exact original retained draft.'],
        final_response=binding('dependent'),
    )
    runs = AtomicMemoryContainer('conversation_id')
    steps = case.fixture.container
    with stubbed_config(
        cosmos_orchestration_runs_container=runs, cosmos_orchestration_run_steps_container=steps,
    ):
        import functions_orchestration_recovery as recovery
        import functions_orchestration_runs as run_store

        with patch.object(run_store, 'cosmos_orchestration_runs_container', runs), patch.object(
            run_store, 'cosmos_orchestration_run_steps_container', steps,
        ):
            record = runs.create_item(body={
                'id': 'run-1', 'run_id': 'run-1', 'record_type': 'run',
                'conversation_id': 'conversation-1', 'user_id': 'owner', 'turn_id': 'turn-1',
                'plan': deepcopy(case.plan), 'status': 'running', 'attempt_index': 1,
                'user_message': case.context.user_message, 'original_user_message': case.context.user_message,
                'recovery_version': 'initial-recovery-version', 'execution_lease': recovery.lease_fields(),
            })

            def read_run(run_id):
                return runs.read_item(item=run_id, partition_key='conversation-1')

            def service():
                results = case.fixture.restart()
                results.access.read_run = read_run
                return results

            leases = []

            def fresh_context(record):
                context = runtime.executor.RunContext(
                    run_id=record['id'], plan_id=record['plan']['plan_id'],
                    conversation_id='conversation-1', user_id='owner',
                    user_message=case.context.user_message, plan_contract_version=2,
                    attempt_index=record['attempt_index'], result_service=service(),
                    resolve_source_manifest=case.fixture.resolve, invoke_prompt=case.model,
                )
                context.prompt_token_usage = case.model.usage
                return context

            def run(record, context, adapter=None):
                lease = recovery.ExecutionLease(record, lambda: True)
                leases.append(lease)
                context._result_guard_token_for_step = lambda step_id: lease.token

                def persist(kind, data):
                    if kind == 'run':
                        lease.update(data)

                result = runtime.executor.execute_plan(
                    record['plan'], context, settings=case.settings, user_id='owner',
                    get_adapter=(lambda capability: adapter) if adapter else None, persist=persist,
                    checkpoints=lambda active_context: recovery.ExecutionCheckpoints(
                        record, active_context, case.settings, lease,
                    ),
                )
                lease.close(release=True)
                return result

            def prepare(run_id='run-1'):
                current = read_run(run_id)

                def validate(source):
                    probe = fresh_context(source)
                    return recovery.validate_resume(
                        source, probe, case.settings, lambda: True, source_run_id=source['id'],
                    )

                return recovery.prepare_retry(
                    run_id, 'owner', {
                        'conversation_id': 'conversation-1', 'expected_version': current['recovery_version'],
                        'submission_id': 'same-retry-submission', 'confirm_external_effects': False,
                    }, authorize=lambda: True, validate=validate,
                )

            try:
                yield SimpleNamespace(
                    runtime=runtime, case=case, recovery=recovery, runs=runs, record=record,
                    read_run=read_run, fresh_context=fresh_context, run=run, prepare=prepare,
                )
            finally:
                for lease in leases:
                    if not lease.stopped.is_set():
                        current = read_run(lease.run_id)
                        lease.close(release=(current.get('execution_lease') or {}).get('token') == lease.token)


def fail_first(durable):
    runtime = durable.runtime
    calls = []

    def adapter(step, context, **kwargs):
        calls.append(step['step_id'])
        if step['step_id'] == 'failed':
            return runtime.schema.build_step_result(
                status='failed', failure=runtime.schema.build_failure('step_failed'),
            )
        return runtime.composition.adapter_compose(step, context, **kwargs)

    result = durable.run(durable.record, durable.fresh_context(durable.record), adapter)
    assert result['status'] == 'failed'
    assert calls == ['failed', 'retained']
    return result


def test_nonprefix_success_survives_restart_and_child_consumes_exact_retained_alias(durable):
    original = fail_first(durable)
    original_reference = original['task_results']['retained']['outputs'][0]
    child = durable.prepare()
    assert 'execution_deadline_at' not in child and 'task_results' not in child and 'message' not in child
    assert 'result_outputs' not in child and 'outputs' not in child
    child = durable.recovery._replace(child, {'status': 'running', 'execution_lease': durable.recovery.lease_fields()})
    durable.case.model.replies.extend(['Repaired independent work.', 'Answer from the original retained draft.'])
    context = durable.fresh_context(child)
    result = durable.run(child, context)
    assert result['status'] == 'completed'
    assert result['task_results']['retained']['outputs'][0] == original_reference
    assert [step['step_id'] for step in result['steps'] if step.get('reused')] == ['retained']
    assert len(durable.case.model.calls) == 3
    assert 'Exact original retained draft.' in durable.case.model.calls[-1][0][-1]['content']
    assert context.result_aliases
    assert result['execution_deadline_at'] > original['execution_deadline_at']


def test_same_attempt_restarts_without_repeating_completed_independent_producer(durable):
    original = fail_first(durable)
    current = durable.read_run('run-1')
    lease = {
        **durable.recovery.lease_fields(), 'token': durable.record['execution_lease']['token'],
    }
    current = durable.recovery._replace(current, {'status': 'running', 'execution_lease': lease})
    durable.case.model.replies.extend(['Recovered failed work.', 'Answer from the retained work.'])
    result = durable.run(current, durable.fresh_context(current))
    assert result['status'] == 'completed'
    assert [step['step_id'] for step in result['steps'] if step.get('reused')] == ['retained']
    assert result['task_results']['retained'] == original['task_results']['retained']
    assert len(durable.case.model.calls) == 3
    assert result['execution_deadline_at'] == original['execution_deadline_at']


def test_chained_retries_verify_original_receipt_without_replaying_copied_results(durable):
    original = fail_first(durable)
    child = durable.prepare()
    child = durable.recovery._replace(child, {'status': 'running', 'execution_lease': durable.recovery.lease_fields()})
    durable.case.model.replies.extend(['Recovered prerequisite.', RuntimeError('Isolated model failure')])
    failed = durable.run(child, durable.fresh_context(child))
    assert failed['status'] == 'failed'
    grandchild = durable.prepare(child['id'])
    grandchild = durable.recovery._replace(
        grandchild, {'status': 'running', 'execution_lease': durable.recovery.lease_fields()},
    )
    durable.case.model.replies.append('Final answer using exactly the original retained draft.')
    result = durable.run(grandchild, durable.fresh_context(grandchild))
    assert result['status'] == 'completed'
    assert [step['step_id'] for step in result['steps'] if step.get('reused')] == ['failed', 'retained']
    assert result['task_results']['retained'] == original['task_results']['retained']
    assert result['task_results']['failed'] == failed['task_results']['failed']
    assert len(durable.case.model.calls) == 4


@pytest.mark.parametrize('change', ['deleted', 'wrong_owner'])
def test_restart_reauthorizes_retained_producer_before_any_new_model_call(durable, change):
    fail_first(durable)
    if change == 'deleted':
        durable.case.fixture.conversation['orchestration_deleted'] = True
    else:
        durable.case.fixture.conversation['user_id'] = 'different-owner'
    with pytest.raises(durable.recovery.RecoveryError):
        durable.prepare()
    assert len(durable.case.model.calls) == 1


def test_waiting_checkpoint_blocks_manual_replay_without_calling_native_again(durable):
    runtime = durable.runtime
    calls = []

    def pending(step, context, **kwargs):
        calls.append(step['step_id'])
        return runtime.schema.build_step_result(
            status='waiting', task_result=runtime.contracts.TaskResult(
                context.result_producer(step), step['role'], 'pending', (),
            ),
            wait={'kind': 'native_compute', 'job_id': 'owned-native-handle'},
        )

    result = durable.run(durable.record, durable.fresh_context(durable.record), pending)
    assert result['status'] == 'waiting'
    record = durable.read_run('run-1')
    with pytest.raises(runtime.checkpoints.CheckpointError) as failure:
        durable.recovery.validate_resume(record, durable.fresh_context(record), durable.case.settings, lambda: True)
    assert failure.value.code == 'result_not_ready'
    assert calls == ['failed', 'retained']
    assert durable.case.model.calls == []


def test_private_result_commit_without_checkpoint_recovers_exact_completion(durable):
    runtime = durable.runtime
    context = durable.fresh_context(durable.record)

    def adapter(step, active_context, **kwargs):
        if step['step_id'] == 'failed':
            return runtime.schema.build_step_result(status='failed', failure=runtime.schema.build_failure())
        return runtime.composition.adapter_compose(step, active_context, **kwargs)

    with patch.object(
        runtime.checkpoints.CheckpointStore, 'commit',
        side_effect=runtime.checkpoints.CheckpointError('checkpoint_unavailable'),
    ):
        with pytest.raises(runtime.checkpoints.CheckpointError):
            durable.run(durable.record, context, adapter)
    task = context.task_results['retained']
    content = context.result_service.open_result(task.output('answer')).read_text()
    assert content == 'Exact original retained draft.'
    record = durable.recovery._replace(durable.read_run('run-1'), {
        'status': 'failed', 'execution_lease': None,
    })
    restored = durable.recovery.reconcile_checkpoints(record, lambda: True)
    projection = durable.recovery.recovery_projection(restored)
    assert projection['eligible'] is False
    assert projection['reason_code'] == 'result_commit_unconfirmed'
    payloads = durable.recovery.validate_resume(
        restored, durable.fresh_context(restored), durable.case.settings, lambda: True,
    )
    assert list(payloads) == ['retained']
    assert payloads['retained']['result']['task_result'] == task.to_dict()
    reconciled = durable.recovery.reconcile_checkpoints(
        restored, lambda: True, result_service=durable.fresh_context(restored).result_service,
    )
    recovered_projection = durable.recovery.recovery_projection(reconciled)
    assert recovered_projection['eligible'] is True
    assert recovered_projection['reused_step_ids'] == ['retained']
    assert len(durable.case.model.calls) == 1


def test_failed_typed_task_does_not_poison_an_independent_success_checkpoint(durable):
    runtime = durable.runtime

    def adapter(step, context, **kwargs):
        if step['step_id'] == 'failed':
            return runtime.schema.build_step_result(
                status='failed', failure=runtime.schema.build_failure(),
                task_result=runtime.contracts.TaskResult(context.result_producer(step), 'reason', 'failed', ()),
            )
        return runtime.composition.adapter_compose(step, context, **kwargs)

    result = durable.run(durable.record, durable.fresh_context(durable.record), adapter)
    assert result['status'] == 'failed'
    assert 'failed' not in result['task_results'] and 'retained' in result['task_results']
    failed_step = next(step for step in result['steps'] if step['step_id'] == 'failed')
    assert failed_step['task_result']['status'] == 'failed'
    assert failed_step['checkpoint_available'] is False
    saved_run = durable.read_run('run-1')
    assert saved_run['steps'][0]['task_result'] == failed_step['task_result']
    child = durable.prepare()
    assert child['retry_reused_step_ids'] == ['retained']
    assert len(durable.case.model.calls) == 1


def test_changed_producer_contract_blocks_reuse_without_reinterpreting_saved_results(durable, monkeypatch):
    original = fail_first(durable)
    record = durable.read_run('run-1')
    monkeypatch.setitem(durable.runtime.registry._DEPENDENCY_RESULT_CONTRACTS, 'compose', 'compose-v2')
    with pytest.raises(durable.runtime.checkpoints.CheckpointError) as failure:
        durable.recovery.validate_resume(
            record, durable.fresh_context(record), durable.case.settings, lambda: True,
            source_run_id=record['id'],
        )
    assert failure.value.code == 'recovery_changed'
    assert original['task_results']['retained']['producer']['contract_version'] == 'compose-v1'
    assert len(durable.case.model.calls) == 1
