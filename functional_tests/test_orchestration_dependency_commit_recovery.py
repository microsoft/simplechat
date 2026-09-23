# test_orchestration_dependency_commit_recovery.py
"""Declared-input receipts close the v2 producer-commit/checkpoint crash window.

Version: 0.261.127
Implemented in: 0.261.127
Uses real facade, storage, checkpoint and recovery APIs with isolated external I/O.
"""

import json
import sys
from copy import deepcopy
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from test_orchestration_dependency_recovery import durable
from test_orchestration_dependency_runtime import compose, execute, runtime, source_input


@pytest.fixture(params=[False, True], ids=['cosmos', 'blob'])
def committed(durable, request):
    if not request.param:
        durable.case.fixture.blobs = None
    context = durable.fresh_context(durable.record)

    def adapter(step, active, **kwargs):
        if step['step_id'] == 'failed':
            return durable.runtime.schema.build_step_result(
                status='failed', failure=durable.runtime.schema.build_failure(),
            )
        return durable.runtime.composition.adapter_compose(step, active, **kwargs)

    with patch.object(
        durable.runtime.checkpoints.CheckpointStore, 'commit',
        side_effect=durable.runtime.checkpoints.CheckpointError('checkpoint_unavailable'),
    ):
        with pytest.raises(durable.runtime.checkpoints.CheckpointError):
            durable.run(durable.record, context, adapter)
    task = context.task_results['retained']
    record = durable.recovery._replace(
        durable.read_run('run-1'), {'status': 'failed', 'execution_lease': None},
    )
    store = durable.recovery.checkpoint_store(record, lambda: True)
    intent = store.load('retained', input_only=True)
    return SimpleNamespace(
        durable=durable, record=record, task=task, store=store, intent=intent,
        service=durable.fresh_context(record).result_service,
    )


def test_receipt_reconstruction_is_read_only_and_contains_only_original_refs(committed):
    case = committed
    before = deepcopy(case.durable.case.fixture.container.items)
    payloads = case.durable.recovery.validate_resume(
        case.record, case.durable.fresh_context(case.record), case.durable.case.settings, lambda: True,
    )
    payload = payloads['retained']
    recovered = case.service.recover_task_result(
        producer=case.task.producer, input_fingerprint=case.intent['input_fingerprint'],
    )
    missing_manifest = case.store.has_manifest('retained')
    serialized = json.dumps(case.intent)
    assert payload['result']['task_result'] == recovered.to_dict() == case.task.to_dict()
    assert payload['input_fingerprint'] == case.intent['input_fingerprint']
    assert payload['provenance'] == {'run_id': 'run-1', 'step_id': 'retained'}
    assert missing_manifest is False and case.durable.case.fixture.container.items == before
    assert 'Exact original retained draft.' not in serialized
    assert 'invoke_prompt' not in serialized and 'result_input_fingerprint_for_step' not in serialized
    assert case.durable.record['execution_lease']['token'] not in serialized
    assert len(case.durable.case.model.calls) == 1


@pytest.mark.parametrize('same_attempt', [True, False])
def test_receipt_recovery_reuses_the_original_producer_without_another_model_call(committed, same_attempt):
    case = committed
    durable = case.durable
    current = case.record if same_attempt else durable.prepare()
    lease = durable.recovery.lease_fields()
    if same_attempt:
        lease['token'] = durable.record['execution_lease']['token']
    current = durable.recovery._replace(current, {'status': 'running', 'execution_lease': lease})
    durable.case.model.replies.extend(['Recovered independent work.', 'Final answer from the retained draft.'])
    result = durable.run(current, durable.fresh_context(current))
    retained = result['task_results']['retained']
    assert result['status'] == 'completed' and len(durable.case.model.calls) == 3
    assert retained == case.task.to_dict()
    assert retained['producer']['run_id'] == 'run-1' and retained['producer']['attempt_index'] == 1
    assert next(step for step in result['steps'] if step['step_id'] == 'retained')['reused'] is True
    assert 'Exact original retained draft.' in durable.case.model.calls[-1][0][-1]['content']


def test_recovered_receipt_survives_chained_retry_before_the_first_checkpoint(committed):
    durable = committed.durable
    child = durable.prepare()
    child = durable.recovery._replace(child, {'status': 'running', 'execution_lease': durable.recovery.lease_fields()})
    durable.case.model.replies.extend(['Recovered prerequisite.', RuntimeError('Provider unavailable.')])
    failed = durable.run(child, durable.fresh_context(child))
    assert failed['status'] == 'failed'
    grandchild = durable.prepare(child['id'])
    grandchild = durable.recovery._replace(
        grandchild, {'status': 'running', 'execution_lease': durable.recovery.lease_fields()},
    )
    durable.case.model.replies.append('Completed using the original retained output.')
    result = durable.run(grandchild, durable.fresh_context(grandchild))
    assert result['status'] == 'completed' and len(durable.case.model.calls) == 4
    assert result['task_results']['retained'] == committed.task.to_dict()


@pytest.mark.parametrize('missing', ['intent', 'receipt'])
def test_missing_exact_proof_never_replays_an_interrupted_producer(committed, missing):
    fixture = committed.durable.case.fixture
    if missing == 'intent':
        row = next(row for row in fixture.container.items.values() if (
            row.get('record_type') == 'checkpoint_input_manifest' and row.get('step_id') == 'retained'
        ))
    else:
        row = next(row for row in fixture.container.items.values() if (
            row.get('key', '').startswith(committed.durable.runtime.contracts.RESULT_RECEIPT_VERSION)
            and (row.get('binding') or {}).get('producer', {}).get('step_id') == 'retained'
        ))
    fixture.container.delete_item(item=row['id'], partition_key='run-1')
    with pytest.raises(committed.durable.runtime.checkpoints.CheckpointError) as failed:
        committed.durable.recovery.validate_resume(
            committed.record, committed.durable.fresh_context(committed.record),
            committed.durable.case.settings, lambda: True,
        )
    assert failed.value.code == 'result_commit_unconfirmed'
    with pytest.raises(committed.durable.recovery.RecoveryError):
        committed.durable.prepare()
    assert len(committed.durable.case.model.calls) == 1
    assert len(committed.durable.runs.items) == 1


@pytest.mark.parametrize('change', ['receipt_digest', 'owner', 'attempt', 'deleted', 'contract', 'settings'])
def test_receipt_recovery_rejects_corruption_or_changed_identity_without_replay(committed, change, monkeypatch):
    durable = committed.durable
    settings = deepcopy(durable.case.settings)
    if change == 'receipt_digest':
        row = next(row for row in durable.case.fixture.container.items.values() if (
            row.get('key', '').startswith(durable.runtime.contracts.RESULT_RECEIPT_VERSION)
            and (row.get('binding') or {}).get('producer', {}).get('step_id') == 'retained'
        ))
        row['reference']['sha256'] = 'f' * 64
    elif change == 'owner':
        durable.case.fixture.conversation['user_id'] = 'another-owner'
    elif change == 'attempt':
        durable.recovery._replace(durable.read_run('run-1'), {'attempt_index': 2})
    elif change == 'deleted':
        durable.case.fixture.conversation['orchestration_deleted'] = True
    elif change == 'contract':
        monkeypatch.setitem(durable.runtime.registry._DEPENDENCY_RESULT_CONTRACTS, 'compose', 'compose-v2')
    else:
        settings['chat_orchestration_step_timeout_seconds'] = 99
    with pytest.raises((durable.runtime.checkpoints.CheckpointError, durable.recovery.RecoveryError)):
        durable.recovery.validate_resume(
            committed.record, durable.fresh_context(committed.record), settings, lambda: True,
        )
    assert len(durable.case.model.calls) == 1


@pytest.mark.parametrize('status', ['complete', 'partial'])
@pytest.mark.parametrize('access_change', [None, 'revoked', 'held', 'revision'])
def test_partial_and_grounded_receipts_keep_completeness_and_current_access(durable, status, access_change):
    runtime = durable.runtime

    def producer(step, context, **kwargs):
        if step['step_id'] == 'failed':
            return runtime.schema.build_step_result(status='failed', failure=runtime.schema.build_failure())
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role='reason', status=status,
            outputs=[runtime.NamedOutput(
                'answer', 'markdown-v1', 'Retained authorized source findings.', runtime.complete(1, status=status),
            )],
            sources=[durable.case.fixture.sources['document-1']], origin='grounded',
            guard_token=context.result_guard_token_for_step(step['step_id']),
            input_fingerprint=context.result_input_fingerprint_for_step(step['step_id']),
        )
        return runtime.schema.build_step_result(task_result=task)

    context = durable.fresh_context(durable.record)
    with patch.object(
        runtime.checkpoints.CheckpointStore, 'commit',
        side_effect=runtime.checkpoints.CheckpointError('checkpoint_unavailable'),
    ):
        with pytest.raises(runtime.checkpoints.CheckpointError):
            durable.run(durable.record, context, producer)
    record = durable.recovery._replace(durable.read_run('run-1'), {'status': 'failed', 'execution_lease': None})
    if access_change == 'revoked':
        durable.case.fixture.denied.add('document-1')
    elif access_change == 'held':
        durable.case.fixture.held.add('document-1')
    elif access_change == 'revision':
        durable.case.fixture.sources['document-1']['source_revision'] = 'changed'
    if access_change is not None:
        with pytest.raises(runtime.checkpoints.CheckpointError) as failure:
            durable.recovery.validate_resume(record, durable.fresh_context(record), durable.case.settings, lambda: True)
        assert failure.value.code == 'result_unavailable'
    else:
        payloads = durable.recovery.validate_resume(
            record, durable.fresh_context(record), durable.case.settings, lambda: True,
        )
        task = payloads['retained']['result']['task_result']
        assert task == context.task_results['retained'].to_dict()
        assert task['status'] == task['outputs'][0]['completeness']['status'] == status
        assert payloads['retained']['result']['status'] == ('completed' if status == 'complete' else 'partial')
    assert durable.case.model.calls == []


def test_commit_then_lost_adapter_return_is_recovered_before_retry(durable, monkeypatch):
    # The real store commits, but the producer never receives its TaskResult descriptor.
    from functions_workflow_result_store import WorkflowResultStore

    original = WorkflowResultStore.commit_orchestration_result

    def lost_acknowledgment(store, *args, **kwargs):
        original(store, *args, **kwargs)
        raise RuntimeError('Private commit acknowledgment transport detail.')

    with monkeypatch.context() as scoped:
        scoped.setattr(WorkflowResultStore, 'commit_orchestration_result', lost_acknowledgment)
        result = durable.run(durable.record, durable.fresh_context(durable.record))
    assert result['status'] == 'failed' and result['task_results'] == {}
    assert 'Private commit acknowledgment' not in result['message']
    child = durable.prepare()
    assert child['retry_reused_step_ids'] == ['failed']
    child = durable.recovery._replace(child, {'status': 'running', 'execution_lease': durable.recovery.lease_fields()})
    durable.case.model.replies.extend(['Second independent draft.', 'Final requested content.'])
    completed = durable.run(child, durable.fresh_context(child))
    assert completed['status'] == 'completed' and len(durable.case.model.calls) == 4
    assert completed['task_results']['failed']['producer']['run_id'] == 'run-1'


def test_declared_fingerprint_survives_source_set_expansion_and_gather_retention(runtime, monkeypatch):
    case = runtime.make([
        {'step_id': 'search', 'capability_id': 'document_search', 'arguments': {'query': 'Find sources.'}},
        {'step_id': 'analyze', 'capability_id': 'document_analyze',
         'arguments': {'analysis_prompt': 'Read exactly the gathered sources.'},
         'inputs': {'sources': source_input('search', 'sources')}},
    ])
    search = ModuleType('functions_search')
    search.hybrid_search = lambda *args, **kwargs: [
        {'document_id': 'document-1', 'id': 'hit-1', 'chunk_text': 'Complete returned excerpt.'},
    ]
    monkeypatch.setitem(sys.modules, 'functions_search', search)
    observed = {}

    def analyze(step, context, **kwargs):
        observed['document_ids'] = step['arguments']['document_ids']
        observed['bound'] = context.result_input_fingerprint_for_step(step['step_id'])
        observed['expanded'] = runtime.checkpoints.step_input_fingerprint(
            step, context, None, settings=case.settings,
        )
        with pytest.raises(runtime.contracts.ResultContractError):
            context.result_input_fingerprint_for_step('other-step')
        return runtime.schema.build_step_result(status='failed', failure=runtime.schema.build_failure())

    result = execute(
        runtime, case, get_adapter=lambda capability: (
            analyze if capability == 'document_analyze' else runtime.executor._dependency_adapter(capability)
        ),
    )
    expected = runtime.checkpoints.step_input_fingerprint(
        case.plan['steps'][1], case.context, None, settings=case.settings,
    )
    gather_fingerprint = runtime.checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, None, settings=case.settings,
    )
    recovered = case.fixture.restart().recover_task_result(
        producer=case.context.result_producer(case.plan['steps'][0]), input_fingerprint=gather_fingerprint,
    )
    assert result['status'] == 'failed' and observed['document_ids'] == ['document-1']
    assert observed['bound'] == expected and observed['expanded'] != expected
    assert recovered == case.context.task_results['search']
    assert {reference.output_name for reference in recovered.outputs} == {'sources', 'evidence', 'prepared'}
    assert case.model.calls == []


def test_same_producer_exact_receipt_is_checked_before_any_adapter_work(runtime):
    case = runtime.make([compose()], ['Prepare exactly once.'])
    original = execute(runtime, case)
    case.context.task_results.clear()
    repeated = execute(
        runtime, case,
        get_adapter=lambda capability: pytest.fail('Committed work must not call its producer again.'),
    )
    assert original['task_results'] == repeated['task_results']
    assert original['message'] == repeated['message']
    assert len(case.model.calls) == 1


def test_input_checkpoint_storage_failure_stops_before_producer_work(durable):
    durable.case.fixture.container.fail_batch_at = 1
    try:
        with pytest.raises(durable.runtime.checkpoints.CheckpointError):
            durable.run(durable.record, durable.fresh_context(durable.record))
    finally:
        durable.case.fixture.container.fail_batch_at = None
    receipts = [
        row for row in durable.case.fixture.container.items.values()
        if row.get('key', '').startswith(durable.runtime.contracts.RESULT_RECEIPT_VERSION)
    ]
    assert receipts == [] and durable.case.model.calls == []


def test_input_checkpoints_share_cleanup_and_permanent_deletion_fences(committed):
    committed.service.store.delete_orchestration_results('owner', 'conversation-1', 'run-1')
    committed.store.delete_payloads()
    rows = [
        row for (partition, _), row in committed.durable.case.fixture.container.items.items()
        if partition == 'run-1' and row.get('record_type')
    ]
    assert len(rows) == 1 and rows[0]['record_type'] == 'checkpoint_lifecycle'
    assert rows[0]['deleted'] is True and rows[0]['token'] is None
    with pytest.raises(committed.durable.runtime.checkpoints.CheckpointError) as failed:
        committed.store.load('retained', input_only=True)
    assert failed.value.code == 'context_unavailable'
    assert len(committed.durable.case.model.calls) == 1


@pytest.mark.parametrize('value', [None, '', 'a' * 63, 'A' * 64, 2])
def test_producer_fingerprint_accessor_rejects_missing_or_invalid_server_values(runtime, value):
    context = runtime.executor.RunContext(
        plan_contract_version=2, result_input_fingerprint_for_step=lambda step_id: value,
    )
    with pytest.raises(runtime.contracts.ResultContractError):
        context.result_input_fingerprint_for_step('draft')
