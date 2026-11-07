# test_document_analysis_work_recovery.py
"""Behavioral producer/store regressions for bounded, recoverable Analyze.

Version: 0.261.109
Implemented in: 0.261.109

Exercise the real producer, candidate collector, calculation integration and
shared result I/O. Original sources and SDK clients are isolated doubles; no
model, Azure, uploads, indexing, or application server calls occur.
"""

import importlib
import json
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from azure.core.exceptions import AzureError

from test_document_analysis_final_results import run_analysis, source_manifest_for
from test_support.document_analysis import (
    USER_ID,
    FixtureAnalysisClient,
    document_analysis_runtime,
    extract_fixture_findings,
    original_document,
)
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_workflow_result_store import FakeBlob, FakeBlobService


class AnalysisMemoryContainer(AtomicMemoryContainer):
    """Reuse the SDK-formatted transactional double with result-store query scopes."""

    def __init__(self):
        super().__init__('run_id')

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        rows = super().query_items(query, parameters, partition_key, **kwargs)
        values = {item['name'][1:]: item['value'] for item in parameters or []}
        return [
            row for row in rows
            if all(row.get(field) == value for field, value in values.items() if field != 'record_type')
            and row.get('type') == values.get('record_type')
            and row.get('item_type') == values.get('record_type')
        ]

    def delete_item(self, item, partition_key, **kwargs):
        kwargs.setdefault('etag', self.read_item(item, partition_key)['_etag'])
        return super().delete_item(item, partition_key, **kwargs)


def calculation_spec(version='tabular-transform-v2'):
    return {
        'version': version,
        'fields': [{
            'name': 'total', 'mode': 'deterministic', 'type': 'number',
            'expression': (
                {'op': 'round', 'value': {'source': 'amount'}, 'scale': 2, 'mode': 'half_up'}
                if version == 'tabular-transform-v2' else {'op': 'add', 'values': [{'source': 'amount'}, 0]}
            ),
        }],
    }


def make_checkpoints(documents, *, store=None, kind='chat', attempt='assistant-1', previous=None,
                     authorize=None, allowed=None, blob=False, operation_request=None, operation_sources=None):
    module = importlib.import_module('functions_document_analysis_checkpoints')
    storage = importlib.import_module('functions_workflow_result_store')
    access = importlib.import_module('functions_analysis_access')
    if store is None:
        store = storage.WorkflowResultStore(
            AnalysisMemoryContainer(), FakeBlobService() if blob else None, 'personal-chat',
        )

    def source_authorizer(user_id, sources, **kwargs):
        def resolve(document_ids, **context):
            current = {source['document_id']: source for source in source_manifest_for(documents)}
            result = []
            for document_id in document_ids:
                source = deepcopy(current[document_id])
                if allowed is not None and not allowed.get(document_id, True):
                    source['authorization_status'] = 'denied'
                result.append(source)
            return result

        return access.authorize_analysis_sources(user_id, sources, resolver=resolve, **kwargs)

    options = {
        'store': store, 'source_authorizer': source_authorizer,
        'authorize': authorize or (lambda: True), 'attempt_token': f'token-{attempt}',
        'operation_request': operation_request, 'operation_sources': operation_sources,
    }
    if kind == 'chat':
        checkpoints = module.analysis_checkpoints_for_chat(
            USER_ID, 'analysis-conversation', attempt, resume_message_id=previous, **options,
        )
    elif kind == 'workflow':
        checkpoints = module.analysis_checkpoints_for_workflow(
            {'id': 'real-workflow', 'user_id': USER_ID}, attempt, 'analyze-task',
            user_id=USER_ID, resume_run_id=previous, **options,
        )
    else:
        checkpoints = module.analysis_checkpoints_for_orchestration(
            USER_ID, 'analysis-conversation', attempt, 'analyze-step', resume_run_id=previous, **options,
        )
    return checkpoints


def run_saved(runtime, documents, checkpoints, **kwargs):
    return run_analysis(
        runtime, documents, work_unit_checkpoints=checkpoints,
        source_manifest=source_manifest_for(documents), **kwargs,
    )


@pytest.mark.parametrize('version', ['tabular-transform-v1', 'tabular-transform-v2'])
def test_explicit_rules_reach_authoritative_records_reports_and_exports_only(version):
    documents = {'cost': original_document('cost', ['The amount is 2.675.'])}

    def findings(prompt):
        return json.dumps({'findings': [{
            'finding_key': 'cost', 'status': 'supported',
            'values': {'amount': '2.675', 'total': 93847, 'finding': 'Declared calculation'},
            'evidence': [{'chunk_sequence': 1, 'quote': 'The amount is 2.675.'}],
        }]})

    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(
            runtime, documents, FixtureAnalysisClient(findings),
            analysis_options={'required_fields': ['total']}, transformation_spec=calculation_spec(version),
        )
        total = result['authoritative_result']['value'][0]['values']['total']
        assert total == (2.68 if version == 'tabular-transform-v2' else 2.675)
        assert runtime.results.get_document_analysis_export_rows(result)[0]['total'] == total
        assert str(total) in result['analysis_reply']
        assert '93847' not in result['analysis_reply']
        assert 'reported_value' not in json.dumps(result['analysis_validation'])
        issue = result['analysis_diagnostics']['calculations']['issues'][0]
        assert issue['reported_value'] == 93847
        assert issue['calculated_value'] == total
        assert issue['spec_version'] == version
        assert len(issue['spec_fingerprint']) == 64
        assert len(client.calls) == 1


def test_rejected_calculation_values_and_unsupported_required_structure_do_not_look_valid():
    documents = {'cost': original_document('cost', ['The amount is unavailable.'])}
    client = FixtureAnalysisClient(lambda prompt: json.dumps({'findings': [{
        'finding_key': 'cost', 'status': 'supported', 'values': {'amount': None, 'total': 93847},
        'evidence': [{'chunk_sequence': 1, 'quote': 'The amount is unavailable.'}],
    }]}))
    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(runtime, documents, client, transformation_spec=calculation_spec())
        assert result['authoritative_result']['value'] == []
        assert result['analysis_validation']['status'] == 'invalid'
        assert '93847' not in result['analysis_reply']
        assert all('values' not in item for item in result['analysis_diagnostics']['calculations']['rejected_records'])
        for unsupported in ({'row_cardinality': 'one_per_source'}, {'schema': {'total': 'number'}},
                            {'required_fields': {'total': 'number'}}, {'mode': 'table'}):
            with pytest.raises(ValueError):
                run_analysis(runtime, documents, client, analysis_options=unsupported)
        assert len(client.calls) == 1


def test_document_action_options_survive_selected_all_recent_and_legacy_round_trips():
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents):
        actions = importlib.import_module('functions_document_actions')
        for target_mode in ('selected', 'all', 'recent'):
            action = actions.normalize_document_action_config({
                'type': 'analyze', 'target_mode': target_mode, 'document_ids': ['one'],
                'analysis_options': {'required_fields': ['total']}, 'transformation_spec': calculation_spec(),
            })
            legacy = actions.build_analyze_config(action)
            restored = actions.normalize_document_action_config(legacy_analyze=legacy)
            assert action['analysis_options'] == legacy['analysis_options'] == restored['analysis_options']
        plain = actions.normalize_document_action_config({'type': 'analyze', 'document_ids': ['one']})
        assert 'analysis_options' not in plain
        assert 'analysis_options' not in actions.build_analyze_config(plain)


@pytest.mark.parametrize('kind', ['chat', 'workflow', 'orchestration'])
@pytest.mark.parametrize('blob', [False, True])
def test_cancelled_real_producer_reuses_only_durably_completed_windows(kind, blob):
    documents = {'one': original_document('one', [
        'The contract uses a sole supplier.', 'An exit penalty applies.', 'The service owner is Mira.',
    ])}
    with document_analysis_runtime(documents) as runtime:
        checkpoints = make_checkpoints(documents, kind=kind, blob=blob)
        stopped = {'value': False}
        completed = []

        def activity(event):
            if event['type'] == 'window_completed':
                completed.append(event['window_range']['window_number'])
                stopped['value'] = len(completed) == 2

        first = FixtureAnalysisClient()
        with pytest.raises(runtime.cancellation.MixedSourceCancellationError):
            run_saved(runtime, documents, checkpoints, client=first, activity_callback=activity,
                      cancel_requested=lambda: stopped['value'])
        assert len(first.calls) == 2
        resumed = make_checkpoints(documents, kind=kind, store=checkpoints.store,
                                   attempt='assistant-2', previous='assistant-1')
        result, second = run_saved(runtime, documents, resumed)
        assert len(second.calls) == 1
        assert second.calls[0]['metadata']['window_range']['window_number'] == 3
        assert result['analysis_metrics']['recovery']['reused_windows'] == 2
        assert result['analysis_validation']['coverage']['completed_work_units'] == 3
        assert len(result['authoritative_result']['value']) == 3


@pytest.mark.parametrize('change', ['version', 'content', 'acl', 'request', 'rules'])
def test_changed_source_access_or_request_blocks_retry_before_a_model_call(change):
    documents = {'one': original_document('one', ['A sole supplier is used.', 'An exit penalty applies.'])}
    allowed = {'one': True}
    with document_analysis_runtime(documents) as runtime:
        first = make_checkpoints(documents, allowed=allowed)
        completed = []
        with pytest.raises(runtime.cancellation.MixedSourceCancellationError):
            run_saved(runtime, documents, first, cancel_requested=lambda: bool(completed),
                      activity_callback=lambda event: completed.append(True) if event['type'] == 'window_completed' else None)
        options = {}
        if change == 'version':
            documents['one']['document']['version'] = 2
        elif change == 'content':
            documents['one']['chunks'][0]['chunk_text'] = 'Different original content.'
        elif change == 'acl':
            allowed['one'] = False
        elif change == 'request':
            options['analysis_prompt'] = 'A materially different task.'
        else:
            options['transformation_spec'] = calculation_spec()
        second = make_checkpoints(documents, store=first.store, attempt='assistant-2',
                                  previous='assistant-1', allowed=allowed)
        client = FixtureAnalysisClient()
        with pytest.raises((PermissionError, RuntimeError)):
            run_saved(runtime, documents, second, client=client, **options)
        assert client.calls == []


def test_report_failure_then_restart_reformats_saved_values_without_extraction(monkeypatch):
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents) as runtime:
        first = make_checkpoints(documents)
        render = runtime.producer.build_document_analysis_report
        monkeypatch.setattr(runtime.producer, 'build_document_analysis_report',
                            lambda result: (_ for _ in ()).throw(ValueError('Private formatter failure')))
        initial, client = run_saved(runtime, documents, first)
        assert len(client.calls) == 1
        assert initial['analysis_validation']['presentation_status'] == 'unavailable'
        monkeypatch.setattr(runtime.producer, 'build_document_analysis_report', render)
        monkeypatch.setattr(runtime.search, 'get_document_chunks_payload',
                            lambda **kwargs: pytest.fail('Formatting must not reload original chunks.'))
        second = make_checkpoints(documents, store=first.store, attempt='assistant-2', previous='assistant-1')
        result, retry = run_saved(runtime, documents, second)
        assert retry.calls == []
        assert result['authoritative_result'] == initial['authoritative_result']
        assert result['analysis_validation']['presentation_status'] == 'ready'
        assert result['analysis_metrics']['recovery']['final_result_reused']
        assert result['analysis_metrics']['model_calls']['total'] == 0


@pytest.mark.parametrize('source_count', [1, 10, 100, 300, 500])
@pytest.mark.parametrize('concurrency', [1, 3])
def test_sources_and_isolated_model_submissions_are_bounded(source_count, concurrency, monkeypatch):
    documents = {
        f'source-{index}': original_document(f'source-{index}', [
            'The service owner is Mira.', 'Reviews take place every quarter.',
        ])
        for index in range(source_count)
    }
    retained = []
    peak = [0]
    active = [0]
    lock = threading.Lock()

    class TrackedPayload(dict):
        pass

    with document_analysis_runtime(documents) as runtime, ThreadPoolExecutor(max_workers=4) as executor:
        getter = runtime.search.get_document_chunks_payload

        def get_source(**kwargs):
            assert not any(item() is not None for item in retained), 'An earlier original source is retained.'
            payload = TrackedPayload(getter(**kwargs))
            retained.append(weakref.ref(payload))
            return payload

        def factory(metadata):
            captured = deepcopy(metadata)

            def invoke(prompt, **kwargs):
                assert kwargs['metadata']['document_id'] == captured['document_id']
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                try:
                    time.sleep(0.001)
                    return extract_fixture_findings(prompt)
                finally:
                    with lock:
                        active[0] -= 1
            return invoke

        monkeypatch.setattr(runtime.search, 'get_document_chunks_payload', get_source)
        result, _ = run_analysis(
            runtime, documents, max_documents=source_count,
            max_window_concurrency=concurrency, invoke_prompt_factory=factory, executor=executor,
        )
        assert result['analysis_validation']['coverage']['completed_sources'] == source_count
        assert result['analysis_metrics']['model_calls']['extraction'] == source_count * 2
        assert result['analysis_metrics']['execution']['peak_loaded_sources'] == 1
        assert result['analysis_metrics']['execution']['peak_buffered_source_chunks'] == 2
        assert peak[0] <= concurrency
        assert result['analysis_metrics']['execution']['peak_in_flight_windows'] == peak[0]
        assert len(result['authoritative_result']['value']) == source_count
        assert all(record['values'] == {'owner': 'Mira', 'review_frequency': 'quarterly'}
                   for record in result['authoritative_result']['value'])


def test_concurrency_without_isolation_is_rejected_before_loading_sources():
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents) as runtime:
        with pytest.raises(ValueError):
            run_analysis(runtime, documents, max_window_concurrency=2)
        assert runtime.source_reads == []


@pytest.mark.parametrize('kind', ['chat', 'workflow', 'orchestration'])
def test_conditional_claims_successors_and_deleted_attempts_fence_stale_completion(kind):
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents):
        first = make_checkpoints(documents, kind=kind)
        request = {'prompt': 'An explicit request'}
        first.initialize(request, source_manifest_for(documents))
        claim = first.store.claim_analysis_unit(first.binding, 'window-1', token=first.token)
        conflict = importlib.import_module('functions_workflow_result_store').AnalysisWorkUnitConflictError
        with pytest.raises(conflict):
            first.store.claim_analysis_unit(first.binding, 'window-1', token=first.token)
        second = make_checkpoints(documents, kind=kind, store=first.store,
                                  attempt='assistant-2', previous='assistant-1')
        second.initialize(request, source_manifest_for(documents))
        before = deepcopy(first.store.container.items)
        with pytest.raises(conflict):
            first.store.finish_analysis_unit(first.binding, claim, {'late': 'private data'}, token=first.token)
        assert first.store.container.items == before
        concurrent_retry = make_checkpoints(documents, kind=kind, store=first.store,
                                            attempt='assistant-3', previous='assistant-1')
        with pytest.raises(conflict):
            concurrent_retry.initialize(request, source_manifest_for(documents))
        second.store.fence_analysis_attempt(second.binding)
        with pytest.raises(conflict):
            second.initialize(request, source_manifest_for(documents))
        with pytest.raises(conflict):
            second.store._save(second.binding, {'late': 'private data'})


@pytest.mark.parametrize('blob', [False, True])
def test_deletion_fences_interrupted_payload_writes_and_keeps_only_tombstones(blob, monkeypatch):
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents):
        checkpoints = make_checkpoints(documents, blob=blob)
        checkpoints.initialize({'prompt': 'Analyze'}, source_manifest_for(documents))
        store = checkpoints.store
        claim = store.claim_analysis_unit(checkpoints.binding, 'window-1', token=checkpoints.token)

        def delete():
            store.delete_chat_results(USER_ID, 'analysis-conversation', 'assistant-1')

        if blob:
            upload = FakeBlob.upload_blob

            def upload_after_delete(self, **kwargs):
                delete()
                return upload(self, **kwargs)

            monkeypatch.setattr(FakeBlob, 'upload_blob', upload_after_delete)
        else:
            store.container.before_batch = delete
        conflict = importlib.import_module('functions_workflow_result_store').AnalysisWorkUnitConflictError
        with pytest.raises(conflict):
            store.finish_analysis_unit(checkpoints.binding, claim, {'source_passage': 'private'}, token=checkpoints.token)
        assert all(row['record_kind'] == 'lifecycle' and row['deleted'] for row in store.container.items.values())
        if blob:
            assert store.blob_client.records == {}


def test_lost_unit_completion_acknowledgement_resumes_the_committed_payload(monkeypatch):
    documents = {'one': original_document('one', ['A sole supplier is used.', 'An exit penalty applies.'])}
    with document_analysis_runtime(documents) as runtime:
        checkpoints = make_checkpoints(documents)
        execute = checkpoints.store.container.execute_item_batch
        lost = []

        def execute_and_lose_ack(batch_operations, **kwargs):
            result = execute(batch_operations, **kwargs)
            if not lost and any(
                operation[0] == 'replace' and isinstance(operation[1][-1], dict)
                and operation[1][-1].get('status') == 'completed' for operation in batch_operations
            ):
                lost.append(True)
                raise AzureError('Private lost acknowledgement')
            return result

        monkeypatch.setattr(checkpoints.store.container, 'execute_item_batch', execute_and_lose_ack)
        client = FixtureAnalysisClient()
        with pytest.raises(AzureError):
            run_saved(runtime, documents, checkpoints, client=client)
        assert len(client.calls) == 1
        second = make_checkpoints(documents, store=checkpoints.store,
                                  attempt='assistant-2', previous='assistant-1')
        result, retry = run_saved(runtime, documents, second)
        assert len(retry.calls) == 1
        assert result['analysis_metrics']['recovery']['reused_windows'] == 1
        assert result['analysis_validation']['coverage']['completed_work_units'] == 2


def test_per_document_calls_share_real_task_binding_without_reusing_a_different_document():
    documents = {
        'one': original_document('one', ['A sole supplier is used.']),
        'two': original_document('two', ['An exit penalty applies.']),
    }
    request = {'prompt': 'Explain the risks in these documents.', 'analysis_mode': 'per_document'}
    with document_analysis_runtime(documents) as runtime:
        checkpoint = make_checkpoints(
            documents, kind='workflow', operation_request=request, operation_sources=source_manifest_for(documents),
        )
        initial = {}
        for document_id, document in documents.items():
            result, client = run_saved(runtime, {document_id: document}, checkpoint)
            initial[document_id] = result['authoritative_result']
            assert len(client.calls) == 1
            assert {record['document_id'] for record in initial[document_id]['value']} == {document_id}
        resumed = make_checkpoints(
            documents, kind='workflow', store=checkpoint.store, attempt='assistant-2', previous='assistant-1',
            operation_request=request, operation_sources=source_manifest_for(documents),
        )
        for document_id, document in documents.items():
            result, client = run_saved(runtime, {document_id: document}, resumed)
            assert client.calls == []
            assert result['authoritative_result'] == initial[document_id]


def test_500_source_workflow_uses_configured_limits_and_real_durable_task_binding():
    documents = {
        f'source-{index}': original_document(f'source-{index}', ['A sole supplier is used.'])
        for index in range(500)
    }
    with document_analysis_runtime(documents) as runtime:
        actions = importlib.import_module('functions_document_actions')
        assert actions.get_document_action_max_documents('analyze', 'chat') == 3
        assert actions.get_document_action_max_documents('analyze', 'workflow') == 10
        limit = actions.get_document_action_max_documents('analyze', 'workflow', settings={
            'document_action_capabilities': {'analyze': {'workflow_max_documents': 500}},
        })
        checkpoints = make_checkpoints(documents, kind='workflow')
        result, client = run_saved(runtime, documents, checkpoints, max_documents=limit)
        assert len(client.calls) == 500
        assert len(result['authoritative_result']['value']) == 500
        assert result['analysis_metrics']['execution']['peak_loaded_sources'] == 1
        assert result['analysis_metrics']['execution']['peak_in_flight_windows'] == 1
        assert result['analysis_validation']['coverage']['completed_sources'] == 500
        assert all(
            row['run_id'] == 'assistant-1' and row['workflow_id'] == 'real-workflow'
            and row['task_id'] == 'analyze-task' for row in checkpoints.store.container.items.values()
        )


def test_concurrent_unit_claims_admit_one_worker_without_replacing_its_completed_values():
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents):
        checkpoint = make_checkpoints(documents)
        checkpoint.initialize({'prompt': 'Analyze'}, source_manifest_for(documents))
        conflict = importlib.import_module('functions_workflow_result_store').AnalysisWorkUnitConflictError

        def claim():
            try:
                return checkpoint.store.claim_analysis_unit(checkpoint.binding, 'window-1', token=checkpoint.token)
            except conflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(lambda _: claim(), range(2)))
        admitted = [claim for claim in claims if claim]
        assert len(admitted) == 1
        reference = checkpoint.store.finish_analysis_unit(
            checkpoint.binding, admitted[0], {'accepted_value': 1}, token=checkpoint.token,
        )
        with pytest.raises(ValueError):
            checkpoint.store.finish_analysis_unit(
                checkpoint.binding, admitted[0], {'accepted_value': 2}, token=checkpoint.token,
            )
        current = checkpoint.store.read_analysis_checkpoint(checkpoint.binding, 'unit', 'window-1')
        assert current['reference'] == reference
        assert checkpoint.store._load(checkpoint.binding, reference) == {'accepted_value': 1}


def test_chat_and_orchestration_checkpoint_cleanup_remain_distinct_lifecycles():
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents):
        chat = make_checkpoints(documents)
        orchestration = make_checkpoints(documents, kind='orchestration', store=chat.store)
        for checkpoint in (chat, orchestration):
            checkpoint.initialize({'prompt': 'Analyze'}, source_manifest_for(documents))
        chat_reference = chat.store.save_chat(USER_ID, 'analysis-conversation', 'assistant-1', {'value': 'chat'})
        orchestration_reference = chat.store.save_orchestration(
            USER_ID, 'analysis-conversation', 'assistant-1', 'analyze-step', {'value': 'orchestration'},
        )
        chat.store.delete_orchestration_results(USER_ID, 'analysis-conversation', 'assistant-1')
        assert chat.store.load_chat(USER_ID, 'analysis-conversation', 'assistant-1', chat_reference) == {'value': 'chat'}
        with pytest.raises(Exception):
            chat.store.load_orchestration(
                USER_ID, 'analysis-conversation', 'assistant-1', 'analyze-step', orchestration_reference,
            )
        chat.store.delete_chat_results(USER_ID, 'analysis-conversation')
        assert all(row.get('deleted') for row in chat.store.container.items.values())


@pytest.mark.parametrize('interruption', ['timeout', 'disconnect'])
def test_timeout_and_disconnect_are_not_reported_as_user_stop(interruption):
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents) as runtime:
        checkpoints = make_checkpoints(documents)

        def invoke(*args, **kwargs):
            if interruption == 'timeout':
                raise TimeoutError('Private provider timeout')
            raise GeneratorExit('Disconnected stream')

        if interruption == 'disconnect':
            with pytest.raises(GeneratorExit):
                run_saved(runtime, documents, checkpoints, invoke_prompt=invoke)
        else:
            result, _ = run_saved(runtime, documents, checkpoints, invoke_prompt=invoke)
            unit = result['analysis_validation']['coverage']['work_units'][0]
            assert unit['status'] == 'failed' and unit['failure_code'] == 'analysis_window_timeout'
            assert result['analysis_validation']['status'] == 'invalid'
            assert result['analysis_metrics']['model_calls']['total'] == 1
        resumed = make_checkpoints(documents, store=checkpoints.store, attempt='assistant-2', previous='assistant-1')
        result, client = run_saved(runtime, documents, resumed)
        assert len(client.calls) == 1
        assert result['analysis_validation']['status'] == 'valid'


def test_stop_cancels_queued_invocations_and_observes_only_started_calls():
    documents = {'one': original_document('one', [
        'A sole supplier is used.', 'An exit penalty applies.', 'The service owner is Mira.',
    ])}
    release = threading.Event()
    entered = threading.Event()
    submitted = []
    invoked = []
    with document_analysis_runtime(documents) as runtime, ThreadPoolExecutor(max_workers=1) as pool:
        checkpoint = make_checkpoints(documents)

        class ExistingExecutor:
            def submit(self, *args, **kwargs):
                future = pool.submit(*args, **kwargs)
                submitted.append(future)
                return future

        def factory(metadata):
            def invoke(prompt, **kwargs):
                invoked.append(metadata['work_unit_id'])
                entered.set()
                assert release.wait(timeout=5)
                return extract_fixture_findings(prompt)
            return invoke

        try:
            with pytest.raises(runtime.cancellation.MixedSourceCancellationError) as failure:
                run_saved(
                    runtime, documents, checkpoint, max_window_concurrency=3,
                    invoke_prompt_factory=factory, executor=ExistingExecutor(),
                    cancel_requested=lambda: len(submitted) == 3 and entered.is_set(),
                )
            metrics = failure.value.analysis_metrics
            assert metrics['model_calls']['extraction'] == 1
            assert metrics['execution']['interruption_status'] == 'cancelled'
            assert metrics['execution']['cancelled_before_start'] == 2
            assert len(invoked) == 1
            assert all(future.cancelled() for future in submitted[1:])
            assert all(row.get('status') != 'completed' for row in checkpoint.store.container.items.values())
        finally:
            release.set()
        submitted[0].result(timeout=5)
        assert len(invoked) == 1
        assert all(row.get('status') != 'completed' for row in checkpoint.store.container.items.values())


def test_collaboration_storage_owner_is_not_used_as_the_requesters_source_authority():
    documents = {'one': original_document('one', ['A sole supplier is used.'])}
    with document_analysis_runtime(documents) as runtime:
        seed = make_checkpoints(documents)
        module = importlib.import_module('functions_document_analysis_checkpoints')
        checked_users = []

        def authorize_sources(user_id, sources, **kwargs):
            checked_users.append(user_id)
            assert user_id == USER_ID
            return seed.source_authorizer(user_id, sources, **kwargs)

        checkpoint = module.analysis_checkpoints_for_chat(
            'original-conversation-owner', 'analysis-conversation', 'real-assistant',
            actor_user_id=USER_ID, authorize=lambda: True, store=seed.store,
            source_authorizer=authorize_sources,
        )
        result, _ = run_saved(runtime, documents, checkpoint)
        assert result['analysis_validation']['status'] == 'valid'
        assert checked_users and set(checked_users) == {USER_ID}
        assert checkpoint.binding['user_id'] == 'original-conversation-owner'
