# test_document_analysis_attempt_fences.py
"""Functional regressions for atomic Analyze attempt Stop/retry/delete fences.

Version: 0.261.109
Implemented in: 0.261.109

Use the existing transactional Cosmos and Blob doubles. Fence changes deliberately
race payload manifests and initializer upgrades; no model or Azure service calls.
"""

import importlib
from copy import deepcopy

import pytest

from test_document_analysis_final_results import source_manifest_for
from test_document_analysis_work_recovery import make_checkpoints, run_saved
from test_support.document_analysis import USER_ID, document_analysis_runtime, original_document
from test_workflow_result_store import FakeBlob


def fixture_documents():
    return {'one': original_document('one', ['A sole supplier is used.', 'An exit penalty applies.'])}


def conflict_type():
    return importlib.import_module('functions_workflow_result_store').AnalysisWorkUnitConflictError


@pytest.mark.parametrize('blob', [False, True])
def test_required_guard_blocks_unregistered_save_and_prepared_save_is_fenced(blob):
    documents = fixture_documents()
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents, blob=blob)
        store = checkpoint.store
        with pytest.raises(conflict_type()) as failure:
            store.save_chat(
                USER_ID, 'analysis-conversation', 'assistant-1', {'final': 'private values'},
                require_analysis_guard=True,
            )
        assert failure.value.code == 'analysis_work_missing'
        assert store.container.items == {}
        checkpoint.prepare()
        reference = store.save_chat(
            USER_ID, 'analysis-conversation', 'assistant-1', {'final': 'private values'},
            guard_token=checkpoint.token, require_analysis_guard=True,
        )
        assert store.load_chat(USER_ID, 'analysis-conversation', 'assistant-1', reference)['final'] == 'private values'
        with pytest.raises(conflict_type()):
            store.save_chat(
                USER_ID, 'analysis-conversation', 'assistant-1', {'final': 'other worker'},
                guard_token='another-worker', require_analysis_guard=True,
            )
        checkpoint.cancel()
        assert store.load_chat(USER_ID, 'analysis-conversation', 'assistant-1', reference)['final'] == 'private values'
        with pytest.raises(conflict_type()) as stopped:
            store.save_chat(
                USER_ID, 'analysis-conversation', 'assistant-1', {'late': 'cannot save'},
                require_analysis_guard=True,
            )
        assert stopped.value.code == 'analysis_work_cancelled'


@pytest.mark.parametrize('blob', [False, True])
@pytest.mark.parametrize('operation', ['stop', 'retry', 'delete'])
def test_guard_changes_racing_a_final_manifest_prevent_stale_publication(blob, operation, monkeypatch):
    documents = fixture_documents()
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents, blob=blob)
        checkpoint.prepare()
        store = checkpoint.store
        successor = make_checkpoints(documents, store=store, attempt='assistant-2', previous='assistant-1')

        def fence():
            if operation == 'stop':
                checkpoint.cancel()
            elif operation == 'retry':
                successor.prepare()
            else:
                store.fence_analysis_attempt(checkpoint.binding)

        if blob:
            upload = FakeBlob.upload_blob

            def upload_then_fence(self, **kwargs):
                result = upload(self, **kwargs)
                fence()
                return result

            monkeypatch.setattr(FakeBlob, 'upload_blob', upload_then_fence)
        else:
            store.container.before_batch = fence
        with pytest.raises(conflict_type()):
            store.save_chat(
                USER_ID, 'analysis-conversation', 'assistant-1', {'late': 'private values'},
                require_analysis_guard=True,
            )
        assert not any(
            row.get('record_kind') == 'manifest' for row in store.container.items.values()
        )
        guard = store._analysis_guard(checkpoint.binding, required=True)
        assert guard['token'] is None
        assert guard.get('deleted') if operation == 'delete' else not guard.get('deleted')


@pytest.mark.parametrize('operation', ['stop', 'delete'])
def test_stop_or_delete_wins_over_a_delayed_initializer_upgrade(operation):
    documents = fixture_documents()
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents)
        checkpoint.prepare()
        store = checkpoint.store
        store.container.before_replace = (
            checkpoint.cancel if operation == 'stop'
            else lambda: store.fence_analysis_attempt(checkpoint.binding)
        )
        with pytest.raises(conflict_type()):
            checkpoint.initialize({'prompt': 'Analyze'}, source_manifest_for(documents))
        guard = store._analysis_guard(checkpoint.binding, required=True)
        assert guard['token'] is None
        assert guard.get('request_registered') is not True
        assert not any(row.get('record_kind') in {'source', 'unit', 'final'} for row in store.container.items.values())


def test_stop_before_registration_blocks_old_worker_but_allows_verified_fresh_retry():
    documents = fixture_documents()
    with document_analysis_runtime(documents) as runtime:
        old = make_checkpoints(documents)
        old.store.cancel_analysis_attempt(old.binding)
        with pytest.raises(conflict_type()):
            old.prepare()
        with pytest.raises(conflict_type()):
            old.initialize({'prompt': 'Analyze'}, source_manifest_for(documents))
        resumed = make_checkpoints(documents, store=old.store, attempt='assistant-2', previous='assistant-1')
        resumed.prepare()
        result, client = run_saved(runtime, documents, resumed)
        assert len(client.calls) == 2
        assert result['analysis_validation']['status'] == 'valid'


def test_prepared_intermediate_retry_does_not_lose_completed_ancestor_units():
    documents = fixture_documents()
    with document_analysis_runtime(documents) as runtime:
        first = make_checkpoints(documents)
        first.prepare()
        completed = []
        with pytest.raises(runtime.cancellation.MixedSourceCancellationError):
            run_saved(
                runtime, documents, first, cancel_requested=lambda: bool(completed),
                activity_callback=lambda event: completed.append(True) if event['type'] == 'window_completed' else None,
            )
        assert first.store._analysis_guard(first.binding)['stopped']
        intermediate = make_checkpoints(documents, store=first.store, attempt='assistant-2', previous='assistant-1')
        intermediate.prepare()
        intermediate.cancel()
        resumed = make_checkpoints(documents, store=first.store, attempt='assistant-3', previous='assistant-2')
        resumed.prepare()
        result, client = run_saved(runtime, documents, resumed)
        assert len(client.calls) == 1
        assert result['analysis_metrics']['recovery']['reused_windows'] == 1
        assert result['analysis_validation']['coverage']['completed_work_units'] == 2


def test_preparation_is_not_permission_to_create_window_checkpoints():
    documents = fixture_documents()
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents)
        checkpoint.prepare()
        before = deepcopy(checkpoint.store.container.items)
        with pytest.raises(conflict_type()):
            checkpoint.store.claim_analysis_unit(checkpoint.binding, 'window-1', token=checkpoint.token)
        with pytest.raises(conflict_type()):
            checkpoint.store.write_analysis_checkpoint(
                checkpoint.binding, 'source', 'one', {'source': {}}, token=checkpoint.token,
            )
        assert checkpoint.store.container.items == before


def test_current_conversation_authorization_is_rechecked_after_preparation():
    documents = fixture_documents()
    deleted = {'value': False}
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents, authorize=lambda: not deleted['value'])
        create = checkpoint.store.container.create_item

        def create_then_delete(body):
            saved = create(body)
            deleted['value'] = True
            return saved

        checkpoint.store.container.create_item = create_then_delete
        with pytest.raises(PermissionError):
            checkpoint.prepare()
        assert not any(row.get('record_kind') == 'manifest' for row in checkpoint.store.container.items.values())
        assert checkpoint.store._analysis_guard(checkpoint.binding)['stopped']


def test_unregistered_checkpoint_cannot_cancel_an_unauthorized_identity():
    documents = fixture_documents()
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents, authorize=lambda: False)
        with pytest.raises(PermissionError):
            checkpoint.cancel()
        assert checkpoint.store.container.items == {}


def test_initial_producer_stop_revokes_an_already_prepared_guard_without_loading_sources():
    documents = fixture_documents()
    with document_analysis_runtime(documents) as runtime:
        checkpoint = make_checkpoints(documents)
        checkpoint.prepare()
        with pytest.raises(runtime.cancellation.MixedSourceCancellationError):
            run_saved(runtime, documents, checkpoint, cancel_requested=lambda: True)
        assert runtime.source_reads == []
        guard = checkpoint.store._analysis_guard(checkpoint.binding)
        assert guard['stopped'] and guard['token'] is None
        with pytest.raises(conflict_type()):
            checkpoint.store._save(checkpoint.binding, {'late': True}, require_analysis_guard=True)


@pytest.mark.parametrize('reason, code', [
    ('cancelled', 'analysis_work_cancelled'), ('timed_out', 'analysis_work_timeout'),
    ('disconnected', 'analysis_work_disconnected'), ('failed', 'analysis_work_stopped'),
])
def test_stop_reason_remains_distinct_without_deleting_completed_data(reason, code):
    documents = fixture_documents()
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents)
        checkpoint.prepare()
        checkpoint.cancel(reason)
        with pytest.raises(conflict_type()) as failure:
            checkpoint.store._save(checkpoint.binding, {'late': True}, require_analysis_guard=True)
        assert failure.value.code == code
        guard = checkpoint.store._analysis_guard(checkpoint.binding)
        assert guard['stop_reason'] == reason
        assert not guard['deleted']
