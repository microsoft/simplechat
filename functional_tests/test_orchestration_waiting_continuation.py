# test_orchestration_waiting_continuation.py
"""Same-attempt wait continuation uses real leases, checkpoints and retained results.

Version: 0.261.127
Implemented in: 0.261.127
Only storage transport and producer/model I/O are isolated.
"""

from datetime import timedelta

import pytest

from test_orchestration_dependency_recovery import durable, fail_first
from test_orchestration_dependency_runtime import runtime
from test_support.orchestration_revisions import AtomicMemoryContainer


@pytest.fixture
def waiting(durable):
    record = durable.recovery._replace(durable.record, {'approval': {'state': 'approved'}})

    def producer(step, context, **kwargs):
        if step['step_id'] == 'failed':
            return durable.runtime.schema.build_step_result(
                status='waiting', task_result=durable.runtime.contracts.TaskResult(
                    context.result_producer(step), 'reason', 'pending', (),
                ),
                wait={
                    'kind': 'orchestration_result',
                    'input_fingerprint': context.result_input_fingerprint_for_step(step['step_id']),
                },
            )
        return durable.runtime.composition.adapter_compose(step, context, **kwargs)

    result = durable.run(record, durable.fresh_context(record), producer)
    assert result['status'] == 'waiting'
    durable.waiting_result = result
    return durable


def claim(waiting, *, submission='refresh-1', messages=None):
    record = waiting.read_run('run-1')
    return waiting.recovery.claim_waiting_continuation('run-1', 'owner', {
        'conversation_id': 'conversation-1', 'submission_id': submission,
        'expected_version': record['recovery_version'],
    }, authorize=lambda: True, message_container=messages)


def test_repeated_wait_refresh_preserves_attempt_guard_deadline_and_independent_work(waiting):
    before = waiting.read_run('run-1')
    acquired = claim(waiting)
    assert acquired['acquired'] is True
    record = acquired['record']
    assert record['attempt_index'] == before['attempt_index'] == 1
    assert record['execution_deadline_at'] == before['execution_deadline_at']
    assert record['execution_lease']['token'] == waiting.record['execution_lease']['token']
    assert record['execution_lease']['claim_id']
    result = waiting.run(record, waiting.fresh_context(record))
    assert result['status'] == 'waiting'
    assert result['task_results']['failed']['producer'] == waiting.waiting_result['task_results']['failed']['producer']
    assert result['pending_results']['failed'] == waiting.waiting_result['pending_results']['failed']
    assert len(waiting.case.model.calls) == 1
    assert len(waiting.runs.items) == 1
    assert waiting.read_run('run-1')['started_at'] == before['started_at']


def test_result_completion_does_not_get_downgraded_by_later_sibling_checkpoint(waiting):
    record = claim(waiting)['record']
    context = waiting.fresh_context(record)
    step = record['plan']['steps'][0]
    token = record['execution_lease']['token']
    original = waiting.waiting_result['pending_results']['failed']
    task = context.result_service.persist_task_result(
        producer=context.result_producer(step), role='reason', status='complete',
        outputs=[waiting.runtime.NamedOutput('answer', 'markdown-v1', 'Original work completed.', waiting.runtime.complete(1))],
        sources=[], origin='generated', guard_token=token, input_fingerprint=original['input_fingerprint'],
    )
    waiting.case.model.replies.append('Use the retained independent draft.')
    result = waiting.run(record, context)
    assert result['status'] == 'completed', result
    assert result['pending_results'] == {}
    assert result['task_results']['failed'] == task.to_dict()
    assert result['task_results']['retained'] == waiting.waiting_result['task_results']['retained']
    assert len(waiting.case.model.calls) == 2
    assert result['execution_deadline_at'] == waiting.waiting_result['execution_deadline_at']
    stored = waiting.read_run('run-1')
    assert stored['task_results'] == result['task_results']
    assert stored['pending_results'] == {}
    assert stored['execution_deadline_at'] == result['execution_deadline_at']


def test_duplicate_submission_cannot_dispatch_another_worker(waiting):
    before = waiting.read_run('run-1')
    data = {
        'conversation_id': 'conversation-1', 'submission_id': 'same-refresh',
        'expected_version': before['recovery_version'],
    }
    first = waiting.recovery.claim_waiting_continuation(
        'run-1', 'owner', data, authorize=lambda: True,
    )
    duplicate = waiting.recovery.claim_waiting_continuation(
        'run-1', 'owner', data, authorize=lambda: True,
    )
    assert first['acquired'] is True and duplicate['acquired'] is False
    assert first['record']['execution_lease'] == duplicate['record']['execution_lease']
    with pytest.raises(waiting.recovery.RecoveryError) as failure:
        claim(waiting, submission='another-refresh')
    assert failure.value.code == 'execution_live'


def test_expired_claim_is_replaced_without_reviving_old_writers(waiting):
    first = claim(waiting)['record']
    old = waiting.recovery.ExecutionLease(first, lambda: True)
    old_store = waiting.recovery.checkpoint_store(
        first, lambda: True, token=old.token, claim_id=old.claim_id,
    )
    expired_lease = {
        **first['execution_lease'],
        'expires_at': (waiting.recovery._now() - timedelta(seconds=1)).isoformat(),
    }
    waiting.recovery._replace(first, {'execution_lease': expired_lease})
    second = claim(waiting, submission='replacement-refresh')['record']
    assert second['execution_lease']['token'] == old.token
    assert second['execution_lease']['claim_id'] != old.claim_id
    assert second['attempt_index'] == first['attempt_index']
    with pytest.raises(waiting.runtime.checkpoints.CheckpointError):
        old.read()
    with pytest.raises(waiting.runtime.checkpoints.CheckpointError):
        old_store.save_step({'step_id': 'failed', 'status': 'failed'})
    waiting.recovery.ExecutionLease(second, lambda: True).close(release=True)


def test_publication_guard_is_reused_and_old_epoch_cannot_publish(waiting):
    messages = AtomicMemoryContainer('conversation_id')
    token = waiting.record['execution_lease']['token']
    messages.create_item(body={
        'id': waiting.recovery._publication_id('run-1'), 'conversation_id': 'conversation-1',
        'run_id': 'run-1', 'user_id': 'owner', 'token': token, 'role': 'assistant_artifact',
        'metadata': {'is_generated_chat_artifact': True, 'orchestration_publication_guard': True},
        'content': '', 'published_message_id': 'existing-status-message', 'document_digest': 'prior-digest',
    })
    stale = waiting.recovery.ExecutionLease(waiting.record, lambda: True, message_container=messages)
    record = claim(waiting, messages=messages)['record']
    lease = waiting.recovery.ExecutionLease(record, lambda: True, message_container=messages)
    try:
        lease.start()
        guard = messages.read_item(waiting.recovery._publication_id('run-1'), 'conversation-1')
        assert guard['claim_id'] == lease.claim_id and guard['token'] == token
        assert guard['published_message_id'] == 'existing-status-message'
        assert guard['document_digest'] == 'prior-digest'
        with pytest.raises(waiting.runtime.checkpoints.CheckpointError):
            stale.publish_message({})
    finally:
        lease.close(release=True)


@pytest.mark.parametrize('change', [
    'cancelled', 'unapproved', 'deleted', 'changed_attempt', 'deadline', 'missing_timezone', 'successor',
])
def test_wait_claim_never_bypasses_owner_or_budget_fences(waiting, change):
    record = waiting.read_run('run-1')
    updates = {
        'cancelled': {'cancellation_requested_at': waiting.recovery._now().isoformat()},
        'unapproved': {'approval': {'state': 'pending'}},
        'deleted': {'checkpoints_deleted': True},
        'changed_attempt': {'attempt_index': 2},
        'deadline': {'execution_deadline_at': (waiting.recovery._now() - timedelta(seconds=1)).isoformat()},
        'missing_timezone': {'execution_deadline_at': waiting.recovery._now().replace(tzinfo=None).isoformat()},
        'successor': {'latest_attempt_run_id': 'a-different-attempt'},
    }[change]
    waiting.recovery._replace(record, updates)
    with pytest.raises((waiting.recovery.RecoveryError, waiting.runtime.checkpoints.CheckpointError)):
        claim(waiting)
    current = waiting.read_run('run-1')
    assert len(waiting.case.model.calls) == 1
    if change == 'deadline':
        assert current['status'] == 'failed' and current['failure']['code'] == 'run_timeout'
    assert not current.get('continuation_submission')


def test_lost_claim_acknowledgment_reconciles_exact_submission(waiting, monkeypatch):
    original = waiting.runs.replace_item
    failed = []

    def replace_then_lose_ack(*args, **kwargs):
        result = original(*args, **kwargs)
        if (kwargs.get('body') or {}).get('continuation_submission') and not failed:
            failed.append(True)
            raise RuntimeError('Private storage response was lost.')
        return result

    monkeypatch.setattr(waiting.runs, 'replace_item', replace_then_lose_ack)
    acquired = claim(waiting)
    assert acquired['acquired'] is True and failed == [True]
    assert acquired['record']['execution_lease']['claim_id']


def test_racing_claims_have_one_cas_winner(waiting, monkeypatch):
    original = waiting.runs.replace_item
    winner = []

    def concurrent_replace(*args, **kwargs):
        if (kwargs.get('body') or {}).get('continuation_submission') and not winner:
            winner.append(None)
            winner[0] = claim(waiting, submission='winning-refresh')
        return original(*args, **kwargs)

    monkeypatch.setattr(waiting.runs, 'replace_item', concurrent_replace)
    with pytest.raises(waiting.recovery.RecoveryError):
        claim(waiting, submission='losing-refresh')
    assert winner[0]['acquired'] is True
    current = waiting.read_run('run-1')
    assert current['continuation_submission']['submission_id'] == 'winning-refresh'
    assert current['execution_lease'] == winner[0]['record']['execution_lease']


def test_partial_claim_fencing_failure_can_be_taken_over_after_expiry(waiting, monkeypatch):
    original = waiting.runtime.checkpoints.CheckpointStore.adopt_claim
    calls = []

    def fail_first_adoption(store, previous_claim_id):
        calls.append(previous_claim_id)
        if len(calls) == 1:
            raise RuntimeError('Isolated checkpoint transport failure.')
        return original(store, previous_claim_id)

    monkeypatch.setattr(waiting.runtime.checkpoints.CheckpointStore, 'adopt_claim', fail_first_adoption)
    with pytest.raises(RuntimeError, match='checkpoint transport'):
        claim(waiting)
    interrupted = waiting.read_run('run-1')
    with pytest.raises(waiting.recovery.RecoveryError) as failure:
        claim(waiting, submission='too-soon')
    assert failure.value.code == 'execution_live'
    waiting.recovery._replace(interrupted, {
        'execution_lease': {
            **interrupted['execution_lease'],
            'expires_at': (waiting.recovery._now() - timedelta(seconds=1)).isoformat(),
        },
    })
    recovered = claim(waiting, submission='fence-recovery')
    assert recovered['acquired'] is True
    assert recovered['record']['execution_lease']['token'] == interrupted['execution_lease']['token']
    result = waiting.run(recovered['record'], waiting.fresh_context(recovered['record']))
    assert result['status'] == 'waiting' and len(waiting.case.model.calls) == 1


def test_wait_claim_does_not_revive_a_revoked_publication_guard(waiting):
    messages = AtomicMemoryContainer('conversation_id')
    waiting.recovery.fence_publication(waiting.read_run('run-1'), messages)
    with pytest.raises(waiting.recovery.RecoveryError) as failure:
        claim(waiting, messages=messages)
    assert failure.value.code == 'ownership_lost'
    current = waiting.read_run('run-1')
    assert not current.get('continuation_submission')


def test_persisted_deadline_terminates_even_an_unreleased_continuation_claim(waiting):
    acquired = claim(waiting)['record']
    waiting.recovery._replace(acquired, {
        'execution_deadline_at': (waiting.recovery._now() - timedelta(seconds=1)).isoformat(),
    })
    with pytest.raises(waiting.recovery.RecoveryError) as failure:
        claim(waiting, submission='deadline-event')
    assert failure.value.code == 'run_timeout'
    current = waiting.read_run('run-1')
    assert current['status'] == 'failed' and current['execution_lease'] is None
    assert len(waiting.case.model.calls) == 1


def test_cancellation_after_run_cas_finishes_without_dispatch(waiting, monkeypatch):
    original = waiting.runs.replace_item
    injected = []

    def cancel_after_claim(*args, **kwargs):
        result = original(*args, **kwargs)
        if (kwargs.get('body') or {}).get('continuation_submission') and not injected:
            injected.append(True)
            cancelled = {**result, 'cancellation_requested_at': waiting.recovery._now().isoformat()}
            original(
                item=cancelled['id'], body=cancelled, etag=cancelled['_etag'],
                match_condition=waiting.recovery.MatchConditions.IfNotModified,
            )
        return result

    monkeypatch.setattr(waiting.runs, 'replace_item', cancel_after_claim)
    with pytest.raises(waiting.recovery.RecoveryError) as failure:
        claim(waiting)
    assert failure.value.code == 'user_cancelled'
    current = waiting.read_run('run-1')
    assert current['status'] == 'cancelled' and current['execution_lease'] is None
    assert len(waiting.case.model.calls) == 1


def test_unavailable_wait_is_not_resurrected_by_an_older_success_checkpoint(waiting, monkeypatch):
    record = claim(waiting)['record']
    context = waiting.fresh_context(record)
    original = context.result_service.recover_task_result

    def deny_original_result(*, producer, input_fingerprint):
        if producer.step_id == 'failed':
            raise waiting.runtime.composition.ResultUnavailableError('result_external_source_unavailable')
        return original(producer=producer, input_fingerprint=input_fingerprint)

    monkeypatch.setattr(context.result_service, 'recover_task_result', deny_original_result)
    result = waiting.run(record, context)
    assert result['status'] == 'failed'
    assert result['steps'][0]['status'] == 'failed'
    assert 'failed' not in result['task_results']
    assert result['pending_results'] == {}
    assert len(waiting.case.model.calls) == 1


def test_a_retry_child_continues_its_own_wait_not_its_parent_attempt(durable):
    fail_first(durable)
    child = durable.prepare()
    child = durable.recovery._replace(child, {
        'status': 'running', 'approval': {'state': 'approved'},
        'execution_lease': durable.recovery.lease_fields(),
    })

    def wait_once(step, context, **kwargs):
        assert step['step_id'] == 'failed'
        return durable.runtime.schema.build_step_result(
            status='waiting',
            task_result=durable.runtime.contracts.TaskResult(context.result_producer(step), 'reason', 'pending', ()),
            wait={
                'kind': 'orchestration_result',
                'input_fingerprint': context.result_input_fingerprint_for_step(step['step_id']),
            },
        )

    initial = durable.run(child, durable.fresh_context(child), wait_once)
    assert initial['status'] == 'waiting'
    child = durable.read_run(child['id'])
    claimed = durable.recovery.claim_waiting_continuation(child['id'], 'owner', {
        'conversation_id': 'conversation-1', 'submission_id': 'child-refresh',
        'expected_version': child['recovery_version'],
    }, authorize=lambda: True)
    record = claimed['record']
    resumed = durable.run(record, durable.fresh_context(record))
    assert resumed['status'] == 'waiting'
    assert resumed['task_results']['failed'] == initial['task_results']['failed']
    assert resumed['task_results']['failed']['producer']['run_id'] == child['id']
    assert record['attempt_index'] == 2
    assert resumed['task_results']['retained']['producer']['run_id'] == 'run-1'
    assert len(durable.case.model.calls) == 1


def test_render_admission_requires_an_initialized_service(runtime):
    for service in (None, True, {'enabled': True}, lambda: None):
        available = runtime.registry.resolve_available_capability_ids(
            {}, contract_version=2, candidate_ids={'render_file'},
            request_context={'rendering_service': service},
        )
        assert 'render_file' not in available
    capability = runtime.registry.get_capability('render_file', contract_version=2)
    assert capability['role'] == 'render' and capability['result_outputs'] == {}
    assert capability['required_result_inputs'] == ('source',)


def test_each_step_persists_current_reference_state_without_erasing_other_retained_work(waiting, monkeypatch):
    snapshots = []
    original = waiting.recovery.ExecutionCheckpoints.save_step

    def observe_saved_step(checkpoints, record):
        original(checkpoints, record)
        snapshots.append(waiting.read_run(record['run_id']))

    monkeypatch.setattr(waiting.recovery.ExecutionCheckpoints, 'save_step', observe_saved_step)
    claimed = claim(waiting)['record']
    result = waiting.run(claimed, waiting.fresh_context(claimed))
    assert result['status'] == 'waiting'
    assert len(snapshots) == 3
    for record in snapshots:
        assert record['task_results'] == waiting.waiting_result['task_results']
        assert record['pending_results'] == waiting.waiting_result['pending_results']
        assert record['execution_deadline_at'] == waiting.waiting_result['execution_deadline_at']
        assert record['task_results']['retained']['outputs'][0]['content_sha256']
    assert len(waiting.case.model.calls) == 1
