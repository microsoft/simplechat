# test_orchestration_checkpoint_error_mapping.py
"""Functional tests for storage uncertainty versus invalid or denied saved proof.

Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139
Real checkpoint/recovery/result services are used with isolated Cosmos/Blob faults.
No failed read can select a different result, replay a producer, or disclose SDK text.
"""

from copy import deepcopy
from types import SimpleNamespace

from azure.core.exceptions import HttpResponseError
from azure.cosmos import exceptions
import pytest

from test_orchestration_dependency_commit_recovery import committed
from test_orchestration_dependency_recovery import durable, fail_first
from test_orchestration_dependency_runtime import runtime


@pytest.fixture
def retained(durable):
    result = fail_first(durable)
    record = durable.read_run('run-1')
    store = durable.recovery.checkpoint_store(record, lambda: True)
    payload = store.load('retained')
    manifest = next(row for row in durable.case.fixture.container.items.values() if (
        row.get('record_type') == 'checkpoint_manifest' and row.get('step_id') == 'retained'
    ))
    return SimpleNamespace(
        durable=durable, result=result, record=record, store=store,
        payload=payload, manifest=manifest, container=durable.case.fixture.container,
    )


def _fault(kind):
    if kind == 'timeout':
        return TimeoutError('Private checkpoint test transport detail.')
    if kind == 'blob':
        return HttpResponseError(message='Private Blob test response detail.', status_code=503)
    return exceptions.CosmosHttpResponseError(status_code=503, message='Private Cosmos test response detail.')


def _fail_read(monkeypatch, container, item_id, error, *, occurrence=1):
    original = container.read_item
    matched = []

    def read(*args, **kwargs):
        item = kwargs.get('item', args[0] if args else None)
        if item == item_id:
            matched.append(item)
            if len(matched) == occurrence:
                raise error
        return original(*args, **kwargs)

    monkeypatch.setattr(container, 'read_item', read)
    return matched


@pytest.mark.parametrize('stage', ['presence', 'lifecycle', 'manifest', 'chunk'])
@pytest.mark.parametrize('kind', ['cosmos', 'timeout'])
def test_exact_checkpoint_read_exposes_retryable_storage_uncertainty(retained, monkeypatch, stage, kind):
    case = retained
    checkpoint_module = case.durable.runtime.checkpoints
    item_id = (
        checkpoint_module.LIFECYCLE_ID if stage == 'lifecycle'
        else f"{case.manifest['id']}:{case.manifest['digest']}:0" if stage == 'chunk'
        else case.manifest['id']
    )
    error = _fault(kind)
    matched = _fail_read(
        monkeypatch, case.container, item_id, error, occurrence=2 if stage == 'manifest' else 1,
    )
    before = deepcopy(case.container.items)
    with pytest.raises(checkpoint_module.CheckpointError) as failed:
        case.durable.recovery._completed_checkpoint(case.record, 'retained', lambda: True)
    public = case.durable.runtime.schema.safe_failure(failed.value.failure)
    assert failed.value.code == public['code'] == 'checkpoint_storage_unavailable'
    assert failed.value.__cause__ is error
    assert 'Private' not in str(failed.value) and 'Private' not in public['message']
    assert matched and case.container.items == before
    assert len(case.durable.case.model.calls) == 1


@pytest.mark.parametrize('change, expected', [
    ('missing_manifest', 'checkpoint_unavailable'),
    ('missing_lifecycle', 'checkpoint_unavailable'),
    ('missing_chunk', 'checkpoint_unavailable'),
    ('denied', 'context_unavailable'),
    ('deleted', 'context_unavailable'),
    ('identity', 'checkpoint_invalid'),
    ('binding', 'recovery_changed'),
])
def test_missing_denied_and_changed_proof_are_not_storage_outages(retained, change, expected):
    case = retained
    authorize = lambda: True
    record = deepcopy(case.record)
    if change.startswith('missing_'):
        item_id = (
            case.durable.runtime.checkpoints.LIFECYCLE_ID if change == 'missing_lifecycle'
            else f"{case.manifest['id']}:{case.manifest['digest']}:0" if change == 'missing_chunk'
            else case.manifest['id']
        )
        case.container.delete_item(item=item_id, partition_key='run-1')
    elif change == 'denied':
        authorize = lambda: False
    elif change == 'deleted':
        case.store.fence(deleted=True)
    elif change == 'identity':
        case.manifest['user_id'] = 'another-owner'
    else:
        record['execution_binding'] = 'changed-approved-inputs'
    before = deepcopy(case.container.items)
    with pytest.raises(case.durable.runtime.checkpoints.CheckpointError) as failed:
        case.durable.recovery._completed_checkpoint(record, 'retained', authorize)
    assert failed.value.code == expected
    assert case.container.items == before and len(case.durable.case.model.calls) == 1


@pytest.mark.parametrize('operation', ['presence', 'load'])
def test_direct_checkpoint_store_storage_failure_is_retryable_uncertainty(retained, monkeypatch, operation):
    case = retained
    module = case.durable.runtime.checkpoints
    store = module.CheckpointStore(
        case.container, run_id='run-1', conversation_id='conversation-1', user_id='owner',
        turn_id='turn-1', authorize=lambda: True,
    )
    item_id = case.manifest['id'] if operation == 'presence' else module.LIFECYCLE_ID
    error = _fault('cosmos')
    _fail_read(monkeypatch, case.container, item_id, error)
    with pytest.raises(module.CheckpointError) as failed:
        if operation == 'presence':
            store.has_manifest('retained')
        else:
            store.load('retained')
    # The removed earlier contract reported checkpoint_unavailable here; one code remains.
    assert failed.value.code == 'checkpoint_storage_unavailable'
    assert failed.value.__cause__ is error


def test_conversation_authorizer_uncertainty_is_not_converted_to_denial(retained):
    case = retained
    error = TimeoutError('Private current-identity service detail.')

    def authorize():
        raise error

    with pytest.raises(TimeoutError) as failed:
        case.durable.recovery._completed_checkpoint(case.record, 'retained', authorize)
    assert failed.value is error
    assert len(case.durable.case.model.calls) == 1


def test_whole_run_retry_retains_storage_code_and_503_without_a_child(retained, monkeypatch):
    case = retained
    error = _fault('cosmos')
    _fail_read(monkeypatch, case.container, case.manifest['id'], error)
    before = deepcopy(case.durable.runs.items)
    with pytest.raises(case.durable.recovery.RecoveryError) as failed:
        case.durable.prepare()
    assert failed.value.code == 'checkpoint_storage_unavailable'
    assert failed.value.status_code == 503
    assert failed.value.recovery['reason_code'] == 'checkpoint_storage_unavailable'
    assert case.durable.runs.items == before and len(case.durable.case.model.calls) == 1
    child = case.durable.prepare()
    assert child['retry_of_run_id'] == 'run-1' and child['attempt_index'] == 2
    assert child['retry_reused_step_ids'] == ['retained']
    assert len(case.durable.runs.items) == 2 and len(case.durable.case.model.calls) == 1


@pytest.mark.parametrize('kind', ['cosmos', 'timeout'])
def test_inherited_run_storage_outage_does_not_become_access_denied(retained, monkeypatch, kind):
    case = retained
    child = case.durable.prepare()
    error = _fault(kind)
    matched = _fail_read(monkeypatch, case.durable.runs, 'run-1', error)
    with pytest.raises(case.durable.runtime.checkpoints.CheckpointError) as failed:
        case.durable.recovery._completed_checkpoint(child, 'retained', lambda: True)
    assert failed.value.code == 'checkpoint_storage_unavailable'
    assert failed.value.__cause__ is error and matched
    assert len(case.durable.case.model.calls) == 1


@pytest.mark.parametrize('kind', ['cosmos', 'timeout', 'blob'])
def test_receipt_storage_failure_preserves_infrastructure_classification(committed, monkeypatch, kind):
    case = committed
    durable = case.durable
    receipt = next(row for row in durable.case.fixture.container.items.values() if (
        row.get('key', '').startswith(durable.runtime.contracts.RESULT_RECEIPT_VERSION)
        and (row.get('binding') or {}).get('producer', {}).get('step_id') == 'retained'
    ))
    error = _fault(kind)
    matched = _fail_read(monkeypatch, durable.case.fixture.container, receipt['id'], error)
    before = deepcopy(durable.case.fixture.container.items)
    with pytest.raises(durable.runtime.checkpoints.CheckpointError) as failed:
        durable.recovery.validate_resume(
            case.record, durable.fresh_context(case.record), durable.case.settings, lambda: True,
        )
    assert failed.value.code == 'checkpoint_storage_unavailable'
    assert matched and durable.case.fixture.container.items == before
    assert len(durable.case.model.calls) == 1


@pytest.mark.parametrize('kind', ['cosmos', 'timeout', 'blob'])
def test_full_retained_result_recheck_preserves_storage_failure(retained, monkeypatch, kind):
    case = retained
    commit = next(row for row in case.container.items.values() if (
        row.get('key', '').startswith('orchestration-task-result-v1:')
    ))
    context = case.durable.fresh_context(case.record)
    error = _fault(kind)
    matched = _fail_read(monkeypatch, case.container, commit['id'], error)
    with pytest.raises(case.durable.runtime.checkpoints.CheckpointError) as failed:
        case.durable.recovery._validate_payload_sources(
            case.payload, context, case.durable.case.settings, 'owner',
        )
    assert failed.value.code == 'checkpoint_storage_unavailable'
    assert matched and len(case.durable.case.model.calls) == 1
