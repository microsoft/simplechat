# test_orchestration_internal_analysis.py
"""
Real v2 adapters -> native Analyze/Compare -> saved readers -> generic result store.
Version: 0.261.127
Implemented in: 0.261.127

Source/model/Cosmos/Blob I/O is offline. Producers, native work-unit checkpoints,
saved Analyze contracts, complete readers and the M1 facade/store are real.
"""

from copy import deepcopy
from dataclasses import replace
import builtins
import importlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

# Application imports follow the standalone test path setup.
from content_screening import access as screening_access
from content_screening.contracts import ScreeningError
from functions_analysis_access import analysis_source_snapshot, authorize_analysis_sources
from functions_document_analysis_checkpoints import AnalysisWorkUnitCheckpoints
from functions_orchestration_result_contracts import RecordColumn, ResultContractError, TaskResult
from functions_orchestration_results import NamedOutput, SavedAnalysisRecordSource
from functions_orchestration_execution_policy import orchestration_file_policy
from functions_workflow_result_store import AnalysisWorkUnitConflictError, _orchestration_identity
from test_support import document_analysis as source_support
from test_support.orchestration_research import document_action_policy_module
from test_support.orchestration_results import ResultFixture, complete, source


def findings_from_original_source(prompt):
    excerpt = prompt.split('<DocumentSlice>\n', 1)[1].rsplit('\n</DocumentSlice>', 1)[0]
    findings = []
    for match in re.finditer(r'\[(?:Page (\d+), )?Chunk (\d+)\] ([^\n]+)', excerpt):
        _, chunk, quote = match.groups()
        item = int(re.search(r'Item (\d+)', quote).group(1))
        findings.append({
            'finding_key': f'item-{item:03}',
            'values': {
                'item': f'{item:03}', 'enabled': item % 2 == 0,
                'detail': {'text': f'Complete finding {item:03}. ' + 'retained detail ' * 20, 'optional': None},
            },
            'status': 'supported', 'issues': [],
            'evidence': [{'chunk_sequence': int(chunk), 'quote': quote}],
        })
    return json.dumps({'findings': findings})


@pytest.fixture
def internal(monkeypatch):
    monkeypatch.setattr(source_support, 'USER_ID', 'owner')
    documents = {
        document_id: source_support.original_document(
            document_id, [f'Item {index:03} contains original source detail.' for index in range(count)],
        )
        for document_id, count in (('document-1', 151), ('target-1', 2), ('target-2', 2))
    }
    for document in documents.values():
        document['document']['_etag'] = 'revision-1'
    fixture = ResultFixture(blob=True)
    fixture.sources = {
        key: {**source(key), 'source_kind': 'narrative', 'file_name': value['document']['file_name']}
        for key, value in documents.items()
    }
    analyze_producer = fixture.producer
    compare_producer = replace(analyze_producer, step_id='compare', capability_id='document_compare',
                               contract_version='comparison-v1')
    fixture.add_producer(compare_producer)
    producers = {producer.step_id: producer for producer in (analyze_producer, compare_producer)}
    state = {
        'cancelled': False, 'mode': 'analyze', 'calls': [], 'failed_targets': set(),
        'input_fingerprints': {},
    }
    model = source_support.FixtureAnalysisClient(findings_from_original_source)
    hooks = Mock(side_effect=AssertionError('Internal Reason invoked a managed file hook.'))
    managed_io = SimpleNamespace(**{
        name: hooks for name in (
            'upload_generated_analysis_artifact_for_current_user', 'upload_generated_analysis_artifact_for_user',
            'upload_generated_document_for_current_user', 'upload_generated_chat_artifact_for_current_user',
            'upload_generated_analysis_artifact_stream_for_user', 'upload_generated_file_artifact_stream_for_user',
            'commit_generated_chat_artifact_publication_for_user',
        )
    })

    def invoke(prompt, stage=None, metadata=None):
        state['calls'].append({'stage': stage, 'metadata': deepcopy(metadata)})
        if state['mode'] == 'analyze':
            return model.invoke_prompt(prompt, stage=stage, metadata=metadata)
        if stage in {'window_analysis', 'document_reduction', 'reduction'}:
            return 'Complete source-summary text. Item 000 contains original source detail.'
        if stage == 'comparison':
            target = metadata['right_document_id']
            if target in state['failed_targets']:
                raise RuntimeError('Private provider error must never become a successful comparison.')
            return f'## Comparison {target}\n' + 'Complete comparison finding.\n' * 240 + f'LAST-{target}'
        if stage == 'comparison_reduction':
            return '# Full comparison report\n' + 'Consolidated finding.\n' * 350 + 'LAST-REPORT'
        raise AssertionError(f'Unexpected producer stage: {stage}')

    def authorize_saved(user_id, binding):
        producer = producers[binding['step_id']]
        if user_id != producer.user_id or binding != {
            'kind': 'orchestration', 'user_id': producer.user_id, 'conversation_id': producer.conversation_id,
            'run_id': producer.run_id, 'step_id': producer.step_id,
        }:
            raise PermissionError('Invalid fixture producer.')
        fixture.service.access.authorize_producer(producer)

    checkpoints = {
        step_id: AnalysisWorkUnitCheckpoints(
            fixture.service.store,
            _orchestration_identity(producer.user_id, producer.conversation_id, producer.run_id, step_id),
            user_id='owner', authorize=lambda producer=producer: fixture.service.access.authorize_producer(
                producer, for_write=True,
            ),
            source_authorizer=lambda user_id, sources, **kwargs: authorize_analysis_sources(
                user_id, sources, resolver=fixture.resolve, **kwargs,
            ),
        )
        for step_id, producer in producers.items()
    }
    # These are actual owning lifecycle tokens, prepared before adapter execution.
    for checkpoint in checkpoints.values():
        checkpoint.prepare()

    with source_support.document_analysis_runtime(documents) as native:
        monkeypatch.setitem(sys.modules, 'functions_document_actions', document_action_policy_module())
        adapters = importlib.import_module('functions_orchestration_adapters')
        comparison = importlib.import_module('functions_document_comparison')
        saved = importlib.import_module('functions_saved_analysis')
        access = importlib.import_module('functions_analysis_access')
        monkeypatch.setattr(comparison, 'run_document_analysis', native.producer.run_document_analysis)
        monkeypatch.setattr(access, 'resolve_authorized_source_manifest', fixture.resolve)
        monkeypatch.setattr(screening_access, '_read_authorized_document', fixture.metadata)
        monkeypatch.setattr(saved, '_authorize_orchestration_producer', authorize_saved)
        monkeypatch.setattr(saved, '_orchestration_save', lambda user_id, conversation_id, run_id, step_id, value, **kwargs:
                            fixture.service.store.save_orchestration(
                                user_id, conversation_id, run_id, step_id, value,
                                guard_token=kwargs['guard_token'], require_analysis_guard=True,
                            ))
        monkeypatch.setattr(saved, '_orchestration_load', fixture.service.store.load_orchestration)
        monkeypatch.setitem(sys.modules, 'functions_simplechat_operations', managed_io)
        context = SimpleNamespace(
            plan_contract_version=2, run_id='run-1', conversation_id='conversation-1', user_id='owner',
            user_message='Analyze the selected documents.', invoke_prompt=invoke,
            resolve_source_manifest=fixture.resolve, result_service=fixture.service,
            result_producer=lambda step: producers[step['step_id']],
            result_guard_token_for_step=lambda step_id: checkpoints[step_id].token,
            result_input_fingerprint_for_step=lambda step_id: state['input_fingerprints'][step_id],
            analysis_checkpoint_factory=lambda step_id: checkpoints[step_id],
        )
        yield SimpleNamespace(
            adapters=adapters, comparison=comparison, saved=saved, native=native, fixture=fixture,
            context=context, state=state, checkpoints=checkpoints, hooks=hooks, model=model,
        )


@pytest.fixture
def producer_effects(internal, monkeypatch):
    observed = []
    for owner, method in (
        (internal.context, 'analysis_checkpoint_factory'),
        (internal.checkpoints['analyze'], 'prepare'),
        (internal.checkpoints['analyze'], 'cancel'),
        (internal.fixture.service.store, 'prepare_orchestration_result'),
        (internal.fixture.service.store, 'commit_orchestration_result'),
    ):
        spy = Mock(wraps=getattr(owner, method))
        monkeypatch.setattr(owner, method, spy)
        observed.append(spy)
    return observed


def producer_step(runtime, step_id, capability_id, arguments):
    # The fixture owns the input boundary; use the actual runtime digest algorithm.
    checkpoints = importlib.import_module('functions_orchestration_checkpoints')
    capability = runtime.adapters.get_capability(capability_id, contract_version=2)
    step = {
        'step_id': step_id, 'capability_id': capability_id, 'arguments': arguments,
        'role': 'reason', 'enabled': True, 'optional': False, 'depends_on': [], 'inputs': {},
        'outputs': [{'name': name, 'kind': kind} for name, kind in capability['result_outputs'].items()],
    }
    if runtime.context.plan_contract_version == 2:
        runtime.context.execution_manifest = deepcopy(list(runtime.fixture.sources.values()))
        value = checkpoints.step_input_fingerprint(step, runtime.context, None, settings={})
        runtime.state['input_fingerprints'][step_id] = value
    return step


def analyze(runtime, **arguments):
    runtime.state['mode'] = 'analyze'
    step = producer_step(runtime, 'analyze', 'document_analyze', {
        'document_ids': ['document-1'], 'analysis_prompt': 'Retain all original findings.', **arguments,
    })
    return runtime.adapters.run_document_analyze(
        step, runtime.context, settings={}, user_id='owner', emit=None,
        cancel_requested=lambda: runtime.state['cancelled'],
    )


def compare(runtime, **arguments):
    runtime.state['mode'] = 'compare'
    step = producer_step(runtime, 'compare', 'document_compare', {
        'left_document_id': 'document-1', 'right_document_ids': ['target-1', 'target-2'],
        'comparison_prompt': 'Compare all selected targets.', **arguments,
    })
    return runtime.adapters.run_document_compare(
        step, runtime.context, settings={}, user_id='owner', emit=None,
        cancel_requested=lambda: runtime.state['cancelled'],
    )


def test_analyze_retains_last_finding_evidence_and_full_report_after_restart_without_files(internal):
    result = analyze(internal, allow_generated_files=True, result_version='legacy')
    assert result['status'] == 'completed', result
    task = TaskResult.from_dict(json.loads(json.dumps(result['task_result'].to_dict())))
    restarted = internal.fixture.restart()
    findings = list(restarted.open_result(task.output('findings')).iter_records())
    rows = list(restarted.open_result(task.output('records')).iter_records())
    report = restarted.open_result(task.output('report')).read_text()
    coverage = restarted.open_result(task.output('coverage')).read_value()
    assert task.status == 'complete'
    assert len(findings) == len(rows) == 151
    assert {row['item'] for row in rows} == {f'{index:03}' for index in range(151)}
    assert any(unit['record']['values']['item'] == '150' and unit['evidence'] for unit in findings)
    assert 'Complete finding 150.' in report
    assert len(report) > 4000
    assert coverage['validation']['coverage']['completed_sources'] == 1
    assert coverage['report_available'] is True
    assert internal.hooks.call_count == 0
    assert result['artifacts'] == []
    assert 'Complete finding 150' not in json.dumps(task.to_dict())
    assert not any(row.get('role') == 'file' for row in internal.fixture.container.items.values())
    original_calls = len(internal.model.calls)
    repeated = analyze(internal)
    assert repeated['status'] == 'completed', repeated
    assert len(internal.model.calls) == original_calls


def test_flexible_native_values_are_not_padded_into_an_invented_schema(internal):
    original = internal.model.response_builder

    def varying_values(prompt):
        payload = json.loads(original(prompt))
        for item in payload['findings']:
            if item['values']['item'] == '150':
                item['values'] = {'distinct': ['last', None, False]}
        return json.dumps(payload)

    internal.model.response_builder = varying_values
    result = analyze(internal)
    assert result['status'] == 'completed', result
    task = result['task_result']
    rows = list(internal.fixture.restart().open_result(task.output('findings')).iter_records())
    assert task.status == 'complete'
    assert any(row['record']['values'] == {'distinct': ['last', None, False]} for row in rows)
    assert 'records' not in {output.output_name for output in task.outputs}


def test_native_partial_findings_stay_partial_and_cannot_make_a_complete_child(internal):
    original = internal.model.response_builder

    def unresolved(prompt):
        payload = json.loads(original(prompt))
        for item in payload['findings']:
            if item['values']['item'] in {'149', '150'}:
                item['finding_key'] = 'conflicting-finding'
        return json.dumps(payload)

    internal.model.response_builder = unresolved
    result = analyze(internal)
    task = result['task_result']
    assert result['status'] == 'partial'
    assert task.status == 'partial'
    with pytest.raises(ResultContractError):
        internal.fixture.restart().open_result(task.output('findings'))
    reader = internal.fixture.restart().open_result(task.output('findings'), allow_partial=True)
    rows = list(reader.iter_records())
    recovered = internal.fixture.restart().recover_task_result(
        producer=task.producer, input_fingerprint=internal.state['input_fingerprints']['analyze'],
    )
    assert len(rows) == 149
    assert recovered == task
    assert all(output.completeness.status == 'partial' for output in task.outputs)
    child = internal.fixture.consumer()
    with pytest.raises(ResultContractError) as rejected:
        internal.fixture.service.persist_task_result(
            producer=child, role='reason', status='complete',
            outputs=[NamedOutput('report', 'text-v1', 'Not complete', complete(1))],
            sources=[], origin='grounded', guard_token=internal.checkpoints['analyze'].token,
            upstream=[task.output('findings')], allow_partial_inputs=True,
        )
    assert rejected.value.code == 'result_partial_promoted'


def test_report_failure_is_not_saved_as_a_complete_internal_report(internal, monkeypatch):
    def unavailable(_result):
        raise ValueError('Offline report formatter unavailable.')

    monkeypatch.setattr(internal.native.producer, 'build_document_analysis_report', unavailable)
    result = analyze(internal)
    assert result['status'] == 'completed', result
    task = result['task_result']
    assert task.output('findings').item_count == 151
    assert 'report' not in {output.output_name for output in task.outputs}
    coverage = internal.fixture.restart().open_result(task.output('coverage')).read_value()
    assert coverage['report_available'] is False
    assert internal.hooks.call_count == 0


def test_missing_full_report_cannot_fall_back_to_a_summary(internal, monkeypatch):
    original = internal.native.producer._complete_document_analysis

    def omit_full_text(*args, **kwargs):
        result = original(*args, **kwargs)
        result.pop('analysis_reply')
        result['reply'] = 'A short presentation summary, not the full report.'
        return result

    monkeypatch.setattr(internal.native.producer, '_complete_document_analysis', omit_full_text)
    result = analyze(internal)
    assert result['status'] == 'failed', result
    assert not result.get('task_result')
    assert internal.hooks.call_count == 0


def test_saved_record_source_rejects_an_incompatible_declared_projection(internal):
    result = analyze(internal)
    reader, _ = internal.saved.load_orchestration_analysis_input(
        'owner', result['saved_analyses'][0], bounded=True,
    )
    projection = SavedAnalysisRecordSource(reader, columns=(RecordColumn('not_a_native_field', 'string'),))
    with pytest.raises(ResultContractError) as rejected:
        list(projection.iter_records())
    assert rejected.value.code == 'result_schema_invalid'


@pytest.mark.parametrize('change', ['revoked', 'screened', 'revision'])
def test_completed_native_and_generic_data_recheck_sources_after_restart(internal, change):
    result = analyze(internal)
    if change == 'revoked':
        internal.fixture.denied.add('document-1')
    elif change == 'screened':
        internal.fixture.held.add('document-1')
    else:
        internal.fixture.sources['document-1']['source_revision'] = 'new-revision'
    with pytest.raises((PermissionError, ScreeningError)):
        internal.fixture.restart().open_result(result['task_result'].output('findings'))
    assert internal.hooks.call_count == 0


def test_comparison_retains_every_target_and_full_report_without_files(internal):
    result = compare(internal)
    assert result['status'] == 'completed', result
    task = TaskResult.from_dict(result['task_result'].to_dict())
    restarted = internal.fixture.restart()
    comparison = restarted.open_result(task.output('comparison')).read_value()
    report = restarted.open_result(task.output('report')).read_text()
    assert task.status == 'complete'
    assert comparison['left_document_id'] == 'document-1'
    assert comparison['right_document_ids'] == ['target-1', 'target-2']
    assert comparison['failed_document_ids'] == []
    assert comparison['items'][-1]['text'].endswith('LAST-target-2')
    assert report.endswith('LAST-REPORT') and len(report) > 4000
    assert result['artifacts'] == []
    assert internal.hooks.call_count == 0


@pytest.mark.parametrize('failed_targets,status', [
    ({'target-1'}, 'partial'), ({'target-1', 'target-2'}, 'failed'),
])
def test_failed_comparison_targets_never_become_successful_failure_paragraphs(internal, failed_targets, status):
    internal.state['failed_targets'] = failed_targets
    result = compare(internal)
    task = result['task_result']
    assert task.status == status
    assert task.output('comparison').item_count == 2 - len(failed_targets)
    assert all(output.completeness.status == status for output in task.outputs)
    if status == 'failed':
        assert result['status'] == 'failed'
        assert 'report' not in {output.output_name for output in task.outputs}
        with pytest.raises(ResultContractError):
            internal.fixture.restart().open_result(task.output('comparison'), allow_partial=True)
    else:
        assert result['status'] == 'partial'
        reader = internal.fixture.restart().open_result(task.output('comparison'), allow_partial=True)
        value = reader.read_value()
        details = internal.fixture.restart().open_result(task.output('coverage'), allow_partial=True).read_value()
        assert value['failed_document_ids'] == ['target-1']
        assert value['items'][0]['right_document_id'] == 'target-2'
        assert details['failures'][0]['document_id'] == 'target-1'
        assert 'Private provider error' not in json.dumps(details)
    assert internal.hooks.call_count == 0


@pytest.mark.parametrize('operation', [analyze, compare])
def test_cancelled_attempt_does_not_publish_or_claim_a_result(internal, operation):
    original = internal.context.invoke_prompt

    def stop_after_provider(*args, **kwargs):
        value = original(*args, **kwargs)
        internal.state['cancelled'] = True
        return value

    internal.context.invoke_prompt = stop_after_provider
    result = operation(internal)
    assert result['status'] == 'cancelled', result
    assert not result.get('task_result')
    assert internal.hooks.call_count == 0


@pytest.mark.parametrize('operation', [analyze, compare])
def test_result_guard_failure_is_not_success(internal, operation, monkeypatch):
    def reject(*args, **kwargs):
        raise AnalysisWorkUnitConflictError('analysis_attempt_changed')

    monkeypatch.setattr(internal.fixture.service.store, 'commit_orchestration_result', reject)
    result = operation(internal)
    assert result['status'] == 'failed', result
    assert not result.get('task_result')
    assert internal.hooks.call_count == 0


def test_missing_server_guard_fails_before_analysis_even_when_model_arguments_supply_one(internal):
    internal.context.result_guard_token_for_step = lambda step_id: None
    result = analyze(internal, guard_token='model-invented-token')
    assert result['status'] == 'failed', result
    assert internal.state['calls'] == []
    assert internal.hooks.call_count == 0


def test_comparison_partial_source_windows_are_not_complete_coverage(internal, monkeypatch):
    original_analysis = internal.comparison.run_document_analysis
    original_invoke = internal.context.invoke_prompt

    def bounded_summary(**kwargs):
        return original_analysis(**kwargs, window_size=1, max_retries_per_window=0)

    def incomplete_window(prompt, stage=None, metadata=None):
        if (
            stage == 'window_analysis' and metadata['document_id'] == 'target-1'
            and metadata['window_range']['window_number'] == 2
        ):
            raise RuntimeError('Offline target window failure.')
        return original_invoke(prompt, stage=stage, metadata=metadata)

    monkeypatch.setattr(internal.comparison, 'run_document_analysis', bounded_summary)
    internal.context.invoke_prompt = incomplete_window
    result = compare(internal)
    assert result['status'] == 'partial', result
    task = result['task_result']
    value = internal.fixture.restart().open_result(task.output('comparison'), allow_partial=True).read_value()
    details = internal.fixture.restart().open_result(task.output('coverage'), allow_partial=True).read_value()
    assert len(value['items']) == 2 and value['failed_document_ids'] == []
    assert details['coverage']['partial_sources'] == ['target-1']
    assert details['coverage']['target_statuses']['target-1'] == 'partial'


def test_comparison_reduction_failure_keeps_all_pairwise_text_but_no_fake_report(internal):
    original = internal.context.invoke_prompt

    def fail_reduction(*args, **kwargs):
        if kwargs.get('stage') == 'comparison_reduction':
            raise RuntimeError('Offline reduction failure.')
        return original(*args, **kwargs)

    internal.context.invoke_prompt = fail_reduction
    result = compare(internal)
    task = result['task_result']
    value = internal.fixture.restart().open_result(task.output('comparison'), allow_partial=True).read_value()
    assert result['status'] == 'partial'
    assert task.status == 'partial' and len(value['items']) == 2
    assert value['items'][-1]['text'].endswith('LAST-target-2')
    assert 'report' not in {output.output_name for output in task.outputs}
    assert internal.hooks.call_count == 0


@pytest.mark.parametrize('change', ['revoked', 'screened'])
def test_comparison_source_access_change_during_execution_blocks_commit(internal, change):
    original = internal.context.invoke_prompt

    def change_access(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get('stage') == 'comparison':
            target = 'target-2'
            if change == 'revoked':
                internal.fixture.denied.add(target)
            else:
                internal.fixture.held.add(target)
        return result

    internal.context.invoke_prompt = change_access
    result = compare(internal)
    assert result['status'] == 'failed', result
    assert not result.get('task_result')
    assert internal.hooks.call_count == 0


@pytest.mark.parametrize('operation', [analyze, compare])
def test_cancel_probe_failure_is_an_explicit_failure_not_permission_to_continue(internal, operation):
    class BrokenCancellation:
        def __bool__(self):
            raise RuntimeError('Offline cancellation store failed.')

    internal.state['cancelled'] = BrokenCancellation()
    result = operation(internal)
    assert result['status'] == 'failed', result
    assert internal.state['calls'] == []


def test_native_compute_selection_is_not_routed_to_a_legacy_file_producer(internal):
    internal.fixture.sources['document-1']['source_kind'] = 'tabular'
    result = analyze(internal)
    assert result['status'] == 'failed', result
    assert internal.state['calls'] == []
    assert internal.hooks.call_count == 0


def test_v1_compare_and_standalone_return_shape_are_unchanged(internal):
    internal.state['mode'] = 'compare'
    standalone = internal.comparison.run_document_comparison(
        'owner', 'Compare both targets.',
        {'type': 'comparison', 'left_document_id': 'document-1',
         'right_document_ids': ['target-1', 'target-2'], 'doc_scope': 'all'},
        internal.context.invoke_prompt, conversation_id='conversation-1',
    )
    assert set(standalone) == {
        'reply', 'analysis_reply', 'coverage', 'documents',
        'left_document', 'right_documents', 'comparison_items',
    }
    assert standalone['analysis_reply'].endswith('LAST-REPORT')
    internal.context.plan_contract_version = 1
    legacy = compare(internal)
    assert legacy['status'] == 'completed', legacy
    assert 'task_result' not in legacy
    assert len(legacy['evidence']) == 3


def test_standalone_markdown_recommendation_only_changes_inside_server_scope(internal):
    producer = internal.native.producer
    ordinary = producer._build_analysis_intent('List every item as a table.')
    with orchestration_file_policy(allow_generated_files=False):
        internal_intent = producer._build_analysis_intent('List every item as a table.')
    restored = producer._build_analysis_intent('List every item as a table.')
    assert ordinary == restored
    assert ordinary['csv_artifact_recommended'] is True
    assert ordinary['markdown_analysis_artifact_recommended'] is True
    assert internal_intent['csv_artifact_recommended'] is False
    assert internal_intent['markdown_analysis_artifact_recommended'] is False


@pytest.mark.parametrize('operation,step_id,capability_id', [
    (analyze, 'analyze', 'document_analyze'),
    (compare, 'compare', 'document_compare'),
])
def test_real_runtime_retains_and_round_trips_all_available_native_outputs(
    internal, operation, step_id, capability_id,
):
    runtime = importlib.import_module('functions_orchestration_result_runtime')
    result = operation(internal)
    capability = runtime.get_capability(capability_id, contract_version=2)
    step = {
        'step_id': step_id, 'capability_id': capability_id,
        'outputs': [{'name': name, 'kind': kind} for name, kind in capability['result_outputs'].items()],
    }
    accepted = runtime.validate_task_outputs(step, internal.context, result['task_result'])
    encoded = runtime.encode_step_result(result, retained_only=True)
    decoded = runtime.decode_step_result(json.loads(json.dumps(encoded)))
    reader = internal.fixture.restart().open_result(decoded['task_result'].output('report'))
    text = reader.read_text()
    assert accepted == decoded['task_result']
    assert len(text) > 4000
    assert internal.hooks.call_count == 0


def test_versioned_compose_is_lazy_and_legacy_lookup_stays_unchanged(internal, monkeypatch):
    original_import = builtins.__import__
    composition_imports = []

    def track_import(name, *args, **kwargs):
        if name == 'functions_orchestration_composition':
            composition_imports.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', track_import)
    registry = dict(internal.adapters.ADAPTER_REGISTRY)
    legacy_compose = internal.adapters.get_adapter('compose')
    keyword_lookup = internal.adapters.get_adapter(name='compose')
    unknown = internal.adapters.get_adapter('unknown', contract_version=2)
    legacy = {name: internal.adapters.get_adapter(name) for name in registry}
    explicit_legacy = {name: internal.adapters.get_adapter(name=name, contract_version=1) for name in registry}
    dependency = {
        name: internal.adapters.get_adapter(name=name, contract_version=2)
        for name in registry if name != 'respond'
    }
    dependency_respond = internal.adapters.get_adapter(name='respond', contract_version=2)
    assert legacy_compose is keyword_lookup is unknown is None
    assert legacy == explicit_legacy == registry
    assert dependency == {name: adapter for name, adapter in registry.items() if name != 'respond'}
    assert dependency_respond is None
    assert not composition_imports

    compose = internal.adapters.get_adapter(name='compose', contract_version=2)
    assert compose is sys.modules['functions_orchestration_composition'].adapter_compose
    assert composition_imports == ['functions_orchestration_composition']
    assert 'compose' not in internal.adapters.ADAPTER_REGISTRY
    assert internal.adapters.ADAPTER_REGISTRY == registry


def test_unsupported_adapter_contracts_do_not_fall_back_to_legacy(internal):
    for contract_version in (None, 0, 3, '2', True):
        adapters = [
            internal.adapters.get_adapter(name=name, contract_version=contract_version)
            for name in ('document_analyze', 'respond', 'compose')
        ]
        assert adapters == [None, None, None]


@pytest.mark.parametrize('operation,failed_targets,expected_status', [
    (analyze, (), 'complete'),
    (compare, (), 'complete'),
    (compare, ('target-1',), 'partial'),
    (compare, ('target-1', 'target-2'), 'failed'),
])
def test_adapters_pass_server_input_fingerprints_to_real_commit_recovery(
    internal, operation, failed_targets, expected_status, monkeypatch,
):
    persisted = Mock(wraps=internal.fixture.service.persist_task_result)
    monkeypatch.setattr(internal.fixture.service, 'persist_task_result', persisted)
    internal.state['failed_targets'] = set(failed_targets)
    result = operation(internal)
    assert result['status'] == ('completed' if expected_status == 'complete' else expected_status), result
    task = result['task_result']
    fingerprint = internal.state['input_fingerprints'][task.producer.step_id]
    recovered = internal.fixture.restart().recover_task_result(
        producer=task.producer, input_fingerprint=fingerprint,
    )
    assert task.status == expected_status
    persisted.assert_called_once()
    if expected_status == 'failed':
        manifest = internal.fixture.service.store.load_committed_orchestration_result(
            task.producer.user_id, task.producer.conversation_id, task.producer.run_id,
            task.producer.step_id, task.outputs[0].manifest_sha256,
        )
        assert recovered is None
        assert manifest['status'] == 'failed'
        assert 'input_fingerprint' not in persisted.call_args.kwargs
    else:
        assert recovered == task
        assert persisted.call_args.kwargs['input_fingerprint'] == fingerprint
    assert internal.hooks.call_count == 0


@pytest.mark.parametrize('operation', [analyze, compare])
@pytest.mark.parametrize('invalid', [None, False, '', 'd' * 63, 'D' * 64, {'digest': 'd' * 64}])
def test_invalid_owner_fingerprint_cannot_fall_back_to_model_arguments(
    internal, producer_effects, operation, invalid,
):
    internal.context.result_input_fingerprint_for_step = lambda step_id: invalid
    result = operation(internal, input_fingerprint='e' * 64)
    assert result['status'] == 'failed', result
    assert not result.get('task_result')
    assert internal.state['calls'] == []
    assert internal.hooks.call_count == 0
    for effect in producer_effects:
        effect.assert_not_called()


@pytest.mark.parametrize('operation', [analyze, compare])
def test_missing_owner_fingerprint_stops_before_producer_work(internal, producer_effects, operation):
    del internal.context.result_input_fingerprint_for_step
    result = operation(internal)
    assert result['status'] == 'failed', result
    assert not result.get('task_result')
    assert internal.state['calls'] == []
    for effect in producer_effects:
        effect.assert_not_called()


@pytest.mark.parametrize('failure', ['wrong_step', 'unbound'])
@pytest.mark.parametrize('operation', [analyze, compare])
def test_rejected_owner_fingerprint_has_no_checkpoint_or_result_effects(
    internal, producer_effects, operation, failure,
):
    def fingerprint(step_id):
        raise ResultContractError(
            'result_input_changed' if failure == 'wrong_step' else 'result_input_fingerprint_required',
        )

    internal.context.result_input_fingerprint_for_step = fingerprint
    result = operation(internal)
    assert result['status'] == 'failed'
    assert internal.state['calls'] == []
    for effect in producer_effects:
        effect.assert_not_called()


def test_analyze_captures_owner_fingerprint_once_before_checkpoint_preparation(internal, monkeypatch):
    getter = Mock(wraps=internal.context.result_input_fingerprint_for_step)
    monkeypatch.setattr(internal.context, 'result_input_fingerprint_for_step', getter)
    original_prepare = internal.checkpoints['analyze'].prepare

    def prepare():
        getter.assert_called_once_with('analyze')
        monkeypatch.setattr(
            internal.context, 'result_input_fingerprint_for_step',
            Mock(side_effect=AssertionError('The captured owner digest must not be resolved again.')),
        )
        return original_prepare()

    monkeypatch.setattr(internal.checkpoints['analyze'], 'prepare', prepare)
    result = analyze(internal)
    assert result['status'] == 'completed', result
    fingerprint = internal.state['input_fingerprints']['analyze']
    recovered = internal.fixture.restart().recover_task_result(
        producer=result['task_result'].producer, input_fingerprint=fingerprint,
    )
    assert recovered == result['task_result']
    getter.assert_called_once_with('analyze')


@pytest.mark.parametrize('operation,step_id', [(analyze, 'analyze'), (compare, 'compare')])
def test_exact_adapter_commit_survives_lost_completion_acknowledgement(internal, operation, step_id, monkeypatch):
    original = internal.fixture.service.store.commit_orchestration_result
    committed = []

    def lose_acknowledgement(*args, **kwargs):
        original(*args, **kwargs)
        committed.append(kwargs['input_fingerprint'])
        raise RuntimeError('Offline loss after authoritative commit.')

    monkeypatch.setattr(internal.fixture.service.store, 'commit_orchestration_result', lose_acknowledgement)
    result = operation(internal)
    calls = len(internal.state['calls'])
    fingerprint = internal.state['input_fingerprints'][step_id]
    producer = internal.context.result_producer({'step_id': step_id})
    restarted = internal.fixture.restart()
    recovered = restarted.recover_task_result(producer=producer, input_fingerprint=fingerprint)
    report = restarted.open_result(recovered.output('report')).read_text()
    assert result['status'] == 'failed', result
    assert not result.get('task_result')
    assert committed == [fingerprint]
    assert recovered.status == 'complete'
    if operation is analyze:
        assert 'Complete finding 150.' in report
    else:
        assert report.endswith('LAST-REPORT')
    assert len(internal.state['calls']) == calls
    assert internal.hooks.call_count == 0


@pytest.mark.parametrize('capability_id,named_sources', [
    ('document_analyze', False), ('document_compare', False), ('document_analyze', True),
])
@pytest.mark.parametrize('lose_ack', [False, True])
def test_executor_owned_digest_recovers_native_results_without_repeating_work(
    internal, monkeypatch, capability_id, named_sources, lose_ack,
):
    runtime = importlib.import_module('functions_orchestration_executor')
    schema = importlib.import_module('functions_orchestration_schema')
    settings = {'enable_user_workspace': True}
    step_id = 'analyze' if capability_id == 'document_analyze' else 'compare'
    internal.state['mode'] = step_id
    arguments = (
        {'document_ids': ['document-1'], 'analysis_prompt': 'Retain all original findings.'}
        if step_id == 'analyze' else {
            'left_document_id': 'document-1', 'right_document_ids': ['target-1', 'target-2'],
            'comparison_prompt': 'Compare all selected targets.',
        }
    )
    aliases = {}
    inputs = {}
    adapted_inputs = []
    if named_sources:
        prior = replace(
            internal.fixture.producer, run_id='prior-run', step_id='gather',
            capability_id='document_search', contract_version='orchestration-gathered-content-v1',
        )
        internal.fixture.add_producer(prior)
        checkpoint = AnalysisWorkUnitCheckpoints(
            internal.fixture.service.store,
            _orchestration_identity(prior.user_id, prior.conversation_id, prior.run_id, prior.step_id),
            user_id=prior.user_id,
            authorize=lambda: internal.fixture.service.access.authorize_producer(prior, for_write=True),
        )
        checkpoint.prepare()
        sources = analysis_source_snapshot([internal.fixture.sources['document-1']])
        gathered = internal.fixture.service.persist_task_result(
            producer=prior, role='gather', status='complete', sources=sources,
            origin='grounded', guard_token=checkpoint.token,
            outputs=[NamedOutput('sources', 'source-set-v1', sources, complete(len(sources)))],
        )
        aliases['selected_sources'] = gathered.output('sources')
        inputs['sources'] = {
            'binding': {
                'version': 'orchestration-input-binding-v1', 'step_id': None,
                'output_name': None, 'existing_result': 'selected_sources',
            },
            'allow_partial': False,
        }
        arguments.pop('document_ids')

    def observe_adapter(name):
        adapter = internal.adapters.get_adapter(name, contract_version=2)

        def invoke(step, context, **kwargs):
            checkpoints = importlib.import_module('functions_orchestration_checkpoints')
            adapted_inputs.append({
                'arguments': deepcopy(step['arguments']),
                'owning_fingerprint': context.result_input_fingerprint_for_step(step['step_id']),
                'adapted_fingerprint': checkpoints.step_input_fingerprint(
                    step, context, None, settings=kwargs['settings'],
                ),
            })
            return adapter(step, context, **kwargs)

        return invoke

    plan = schema.normalize_plan(
        {'run_id': 'run-1', 'steps': [
            {'step_id': step_id, 'capability_id': capability_id, 'arguments': arguments, 'inputs': inputs},
        ]},
        'conversation-1', 'owner', settings=settings, contract_version=2,
        available_capability_ids=[capability_id], existing_results=aliases,
    )
    internal.fixture.runs['run-1']['plan'] = plan

    def execute(service):
        context = runtime.RunContext(
            run_id='run-1', plan_id=plan['plan_id'], conversation_id='conversation-1', user_id='owner',
            user_message='Retain all requested findings.', plan_contract_version=2,
            result_service=service, resolve_source_manifest=internal.fixture.resolve,
            result_aliases=aliases,
            invoke_prompt=internal.context.invoke_prompt,
            result_guard_token_for_step=internal.context.result_guard_token_for_step,
        )
        context.analysis_checkpoint_factory = internal.context.analysis_checkpoint_factory
        events = []
        result = runtime.execute_plan(
            plan, context, settings=settings, user_id='owner', emit=events.append,
            **({'get_adapter': observe_adapter} if named_sources else {}),
        )
        return result, context, events

    if lose_ack:
        original = internal.fixture.service.store.commit_orchestration_result

        def commit_then_disconnect(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Offline loss after authoritative commit.')

        monkeypatch.setattr(internal.fixture.service.store, 'commit_orchestration_result', commit_then_disconnect)
    first, context, events = execute(internal.fixture.service)
    calls = len(internal.state['calls'])
    fingerprint = next(
        event['input_fingerprint'] for event in events
        if event.get('type') == 'step' and event.get('phase') == 'running'
    )
    restarted = internal.fixture.restart()
    recovered = restarted.recover_task_result(
        producer=context.result_producer(plan['steps'][0]), input_fingerprint=fingerprint,
    )
    retried, _, _ = execute(restarted)
    task = TaskResult.from_dict(retried['task_results'][step_id])
    report = restarted.open_result(task.output('report')).read_text()
    assert first['status'] == ('failed' if lose_ack else 'completed'), first
    assert retried['status'] == 'completed', retried
    assert recovered == task
    assert len(report) > 4000
    assert calls > 0 and len(internal.state['calls']) == calls
    assert internal.hooks.call_count == 0
    assert first['artifacts'] == retried['artifacts'] == []
    if named_sources:
        assert len(adapted_inputs) == 1
        assert 'document_ids' not in plan['steps'][0]['arguments']
        assert adapted_inputs[0]['arguments']['document_ids'] == ['document-1']
        assert adapted_inputs[0]['owning_fingerprint'] == fingerprint
        assert adapted_inputs[0]['adapted_fingerprint'] != fingerprint
        wrong_receipt = restarted.recover_task_result(
            producer=task.producer, input_fingerprint=adapted_inputs[0]['adapted_fingerprint'],
        )
        assert wrong_receipt is None
