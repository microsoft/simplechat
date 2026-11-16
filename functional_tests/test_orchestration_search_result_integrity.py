# test_orchestration_search_result_integrity.py
"""Lossless search retention, selected-source handoffs and historical partial safety.

Version: 0.261.341
Implemented in: 0.261.341
Search/provider I/O is isolated; envelopes, stores, readers, dependency admission,
native Analyze and checkpoint recovery use their real implementations.
"""

from copy import deepcopy
from types import ModuleType
import importlib
import json
import sys

import pytest

from test_orchestration_dependency_runtime import binding, compose, execute, runtime, source_input
from test_orchestration_internal_analysis import internal
from test_support.app_stubs import stubbed_config
from test_support.orchestration_results import source


def search_step():
    return {
        'step_id': 'search', 'capability_id': 'document_search',
        'arguments': {'query': 'approved search', 'top_n': 50},
    }


def install_search(monkeypatch, hits):
    calls = []
    module = ModuleType('functions_search')

    def hybrid_search(*args, **kwargs):
        calls.append((args, kwargs))
        return deepcopy(hits)

    module.hybrid_search = hybrid_search
    monkeypatch.setitem(sys.modules, 'functions_search', module)
    return calls


@pytest.mark.parametrize('text', ['a' * 1024, 'a' * 1025, 'é' * 900, '😀' * 1000],
                         ids=['ascii-1024', 'ascii-1025', 'multibyte', 'emoji'])
def test_full_hits_are_committed_before_bounded_previews(runtime, monkeypatch, text):
    hits = [
        {'document_id': 'document-1', 'id': f'hit-{index}', 'chunk_text': f'{text}-LAST-{index}',
         'chunk_sequence': index, 'provider_detail': {'retained': True}}
        for index in range(15)
    ]
    calls = install_search(monkeypatch, hits)
    adapters = importlib.import_module('functions_orchestration_adapters')
    original = adapters.build_narrative_evidence_envelopes
    case = runtime.make([search_step()])
    previews = []
    committed = []
    persist = case.fixture.service.persist_task_result

    def observe_commit(**kwargs):
        task = persist(**kwargs)
        committed.append(task)
        return task

    def bounded_after_commit(*args):
        assert len(committed) == 1
        task = committed[0]
        prepared = case.fixture.restart().open_result(task.output('prepared')).read_value()
        assert prepared['search_results'] == hits
        preview = original(*args)
        previews.extend(preview)
        return preview

    monkeypatch.setattr(adapters, 'build_narrative_evidence_envelopes', bounded_after_commit)
    monkeypatch.setattr(case.fixture.service, 'persist_task_result', observe_commit)
    result = execute(runtime, case)
    assert result['status'] == result['outcome'] == 'completed', result
    assert len(calls) == 1 and case.model.calls == []
    task = case.context.task_results['search']
    restarted = case.fixture.restart()
    evidence = list(restarted.open_result(task.output('evidence')).iter_items())
    prepared = restarted.open_result(task.output('prepared')).read_value()
    sources = list(restarted.open_result(task.output('sources')).iter_items())
    assert [item['text'] for item in evidence] == [hit['chunk_text'] for hit in hits]
    assert len(prepared['evidence'][0]['evidence']) == 15
    assert prepared['search_results'] == hits
    assert prepared['search_scope']['top_n_per_scope'] == 50
    assert prepared['coverage']['exhaustive_corpus_coverage'] is False
    assert prepared['coverage']['whole_document_coverage'] is False
    assert sources == [source()]
    assert all(reference.completeness.status == 'complete' for reference in task.outputs)
    assert previews[0]['coverage']['evidence_envelope_truncated'] is True
    assert len(previews[0]['evidence']) <= 10
    assert task.output('evidence').completeness.coverage.unit == 'items'
    assert task.output('sources').completeness.coverage.unit == 'sources'
    assert 'Top-N' in ' '.join(task.output('sources').completeness.limitations)


@pytest.mark.parametrize('text', ['Short exact excerpt.', 'a' * 1024, 'a' * 1025, 'é' * 513],
                         ids=['short', 'ascii-1024', 'ascii-1025', 'utf8-1026'])
def test_single_excerpt_byte_boundary_is_presentation_only(runtime, monkeypatch, text):
    install_search(monkeypatch, [{'document_id': 'document-1', 'id': 'hit', 'chunk_text': text}])
    case = runtime.make([search_step()])
    result = execute(runtime, case)
    assert result['status'] == 'completed'
    task = case.context.task_results['search']
    reader = case.fixture.restart().open_result(task.output('evidence'))
    evidence = list(reader.iter_items())
    assert evidence[0]['text'] == text
    assert task.output('sources').completeness.status == 'complete'


def test_fifty_hits_twenty_three_sources_feed_complete_only_analyze(runtime, monkeypatch):
    hits = [
        {'document_id': f'document-{index % 23}', 'id': f'hit-{index}', 'chunk_text': 'é' * 2000}
        for index in range(50)
    ]
    install_search(monkeypatch, hits)
    case = runtime.make([
        search_step(),
        {'step_id': 'analyze', 'capability_id': 'document_analyze',
         'arguments': {'analysis_prompt': 'Analyze the discovered sources.'},
         'inputs': {'sources': source_input('search', 'sources')}},
    ])
    case.fixture.sources = {f'document-{index}': source(f'document-{index}') for index in range(23)}
    observed = []

    def analyze_selected(step, context, **kwargs):
        observed.append(step['arguments']['document_ids'])
        upstream, limitations = runtime.result_runtime.source_selection_provenance(context)
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role='reason', status='complete',
            outputs=[
                runtime.NamedOutput('findings', 'records-v1', [], runtime.complete(0),
                                    (runtime.contracts.RecordColumn('finding', 'string'),)),
                runtime.NamedOutput('coverage', 'structured-v1', {
                    'source_selection_limitations': list(limitations),
                }, runtime.complete(1)),
            ],
            sources=list(case.fixture.sources.values()), origin='grounded',
            upstream=upstream, guard_token=context.result_guard_token_for_step('analyze'),
        )
        return runtime.schema.build_step_result(status='completed', task_result=task)

    result = execute(runtime, case, get_adapter=lambda name: (
        analyze_selected if name == 'document_analyze' else runtime.executor._dependency_adapter(name)
    ))
    assert result['status'] == result['outcome'] == 'completed', result
    assert observed == [[f'document-{index}' for index in range(23)]]
    assert case.context.task_results['search'].output('evidence').item_count == 50
    assert case.context.task_results['search'].output('sources').item_count == 23
    assert all(output['status'] == 'complete' for output in result['result_outputs'])
    assert result['delivery_facts'] == {'files': []}
    assert 'comprehensive' not in result['message'].lower()


def test_compose_reads_all_long_excerpts_not_the_preview(runtime, monkeypatch):
    hits = [
        {'document_id': 'document-1', 'id': f'hit-{index}', 'chunk_text': 'é' * 800 + f' LAST-{index}'}
        for index in range(12)
    ]
    install_search(monkeypatch, hits)
    case = runtime.make([
        search_step(), compose('answer', inputs={'evidence': source_input('search', 'evidence')}),
    ], ['An answer about the returned excerpts.'], final_response=binding('answer'))
    result = execute(runtime, case)
    assert result['status'] == result['outcome'] == 'completed', result
    payload = json.loads(case.model.calls[0][0][-1]['content'])
    evidence = payload['inputs']['evidence']
    assert [item['text'] for item in evidence['value']] == [hit['chunk_text'] for hit in hits]
    assert any('Top-N' in item for item in evidence['completeness']['limitations'])
    assert result['message'] == 'An answer about the returned excerpts.'
    assert result['outputs'] == [] and result['delivery_facts'] == {'files': []}


def test_full_search_input_still_obeys_the_selected_model_budget(runtime, monkeypatch):
    install_search(monkeypatch, [
        {'document_id': 'document-1', 'id': 'hit', 'chunk_text': 'token ' * 40000},
    ])
    case = runtime.make([
        search_step(), compose('answer', inputs={'evidence': source_input('search', 'evidence')}),
    ], ['An over-budget answer must not be requested.'], final_response=binding('answer'))
    result = execute(runtime, case)
    assert case.model.calls == []
    assert result['status'] == 'failed' and result['outcome'] == 'partial'
    assert result['steps'][1]['failure']['code'] == 'result_input_too_large'
    assert runtime.schema.failure_repeats_on_retry(result['steps'][1]['failure'])
    assert result['failure']['code'] == 'result_input_too_large'
    assert case.context.task_results['search'].status == 'complete'


@pytest.mark.parametrize('change', ['revoked', 'changed'])
def test_selected_sources_recheck_access_and_revision_before_analyze(runtime, monkeypatch, change):
    install_search(monkeypatch, [
        {'document_id': 'document-1', 'id': 'hit', 'chunk_text': '😀' * 1000},
    ])
    case = runtime.make([
        search_step(),
        {'step_id': 'analyze', 'capability_id': 'document_analyze',
         'arguments': {'analysis_prompt': 'Analyze.'},
         'inputs': {'sources': source_input('search', 'sources')}},
    ])
    called = []
    adapter = runtime.executor._dependency_adapter('document_search')

    def search_then_change(step, context, **kwargs):
        result = adapter(step, context, **kwargs)
        if change == 'revoked':
            case.fixture.denied.add('document-1')
        else:
            case.fixture.sources['document-1']['source_revision'] = 'revision-2'
        return result

    def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError('An inaccessible or changed source must not be analyzed.')

    result = execute(runtime, case, get_adapter=lambda name: (
        search_then_change if name == 'document_search' else forbidden
    ))
    assert called == []
    assert result['status'] == 'failed' and result['outcome'] == 'partial'
    assert result['steps'][1]['failure']['code'] == 'result_unavailable'
    assert result['steps'][1]['status'] == 'failed'


def test_empty_discovery_never_falls_back_to_ambient_selected_documents(runtime, monkeypatch):
    calls = install_search(monkeypatch, [])
    case = runtime.make([
        search_step(),
        {'step_id': 'analyze', 'capability_id': 'document_analyze',
         'arguments': {'analysis_prompt': 'Analyze.'},
         'inputs': {'sources': source_input('search', 'sources')}},
    ])
    case.context.selected_document_ids = ['document-1']
    analyzed = []

    def forbidden(*args, **kwargs):
        analyzed.append(True)
        raise AssertionError('An empty source set cannot silently broaden to selected documents.')

    result = execute(runtime, case, get_adapter=lambda name: (
        runtime.executor._dependency_adapter(name) if name == 'document_search' else forbidden
    ))
    assert len(calls) == 1 and analyzed == []
    assert result['steps'][1]['failure']['code'] == 'result_unavailable'
    assert result['status'] == 'failed'


@pytest.mark.parametrize('manifest_problem', ['unresolved', 'ambiguous_scope'])
def test_unverified_source_identity_never_reaches_a_preview(runtime, monkeypatch, manifest_problem):
    install_search(monkeypatch, [{'document_id': 'document-1', 'id': 'hit', 'chunk_text': 'Exact source.'}])
    case = runtime.make([search_step()])
    adapters = importlib.import_module('functions_orchestration_adapters')
    preview_calls = []
    original = adapters.build_narrative_evidence_envelopes

    def preview(*args):
        preview_calls.append(True)
        return original(*args)

    def resolve(ids):
        if manifest_problem == 'unresolved':
            return [{**source(), 'authorization_status': 'unresolved'}]
        return [
            {**source(), 'authorization_status': 'authorized'},
            {**source(), 'scope': 'group', 'scope_id': 'different-group', 'authorization_status': 'authorized'},
        ]

    case.context.resolve_source_manifest = resolve
    monkeypatch.setattr(adapters, 'build_narrative_evidence_envelopes', preview)
    result = execute(runtime, case)
    assert preview_calls == []
    assert result['status'] == result['outcome'] == 'failed'
    assert result['failure']['code'] == 'result_unavailable'
    assert case.context.task_results == {}


def test_search_commit_recovers_after_restart_without_retrieval(runtime, monkeypatch):
    calls = install_search(monkeypatch, [
        {'document_id': 'document-1', 'id': 'hit', 'chunk_text': 'Full text ' * 1000},
    ])
    case = runtime.make([search_step()])
    first = execute(runtime, case)
    case.context = runtime.executor.RunContext(
        run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
        user_message='Prepare the requested content.', plan_contract_version=2,
        result_service=case.fixture.restart(), resolve_source_manifest=case.fixture.resolve,
        result_guard_token_for_step=lambda step_id: 'owned-execution-token', invoke_prompt=case.model,
    )
    again = execute(runtime, case)
    assert first['status'] == again['status'] == 'completed'
    assert first['task_results'] == again['task_results']
    assert len(calls) == 1


def test_storage_overflow_never_commits_a_shortened_search(runtime, monkeypatch):
    install_search(monkeypatch, [
        {'document_id': 'document-1', 'id': 'hit', 'chunk_text': 'Exact large data ' * 2000},
    ])
    case = runtime.make([search_step()])
    case.fixture.service.max_result_bytes = 4096
    events = []
    result = execute(runtime, case, emit=events.append)
    assert result['status'] == result['outcome'] == 'failed'
    assert result['failure']['code'] == 'search_result_too_large'
    assert runtime.schema.failure_repeats_on_retry(result['failure'])
    assert case.context.task_results == {}
    step = case.plan['steps'][0]
    recovered = case.fixture.restart().recover_task_result(
        producer=case.context.result_producer(step),
        input_fingerprint=next(
            event['input_fingerprint'] for event in events
            if event.get('type') == 'step' and event.get('phase') == 'running'
        ),
    )
    assert recovered is None


@pytest.mark.parametrize('genuinely_partial', [False, True])
def test_historical_clipped_and_partial_searches_stay_partial(runtime, monkeypatch, genuinely_partial):
    case = runtime.make([
        search_step(),
        {'step_id': 'analyze', 'capability_id': 'document_analyze',
         'arguments': {'analysis_prompt': 'Analyze.'},
         'inputs': {'sources': source_input('search', 'sources')}},
    ])
    envelopes = importlib.import_module('functions_mixed_source_orchestration')
    with stubbed_config(
        cosmos_orchestration_runs_container=case.fixture.container,
        cosmos_orchestration_run_steps_container=case.fixture.container,
    ):
        recovery = importlib.import_module('functions_orchestration_recovery')

    def historical(step, context, **kwargs):
        if step['step_id'] != 'search':
            raise AssertionError('Partial source selections cannot feed complete-only Analyze.')
        evidence = envelopes.build_narrative_evidence_envelopes(
            [{'document_id': 'document-1'}],
            [{'document_id': 'document-1', 'chunk_text': 'bounded ' * 1000}], 'relevance',
        )
        return runtime.schema.build_step_result(
            status='partial' if genuinely_partial else 'completed', evidence=evidence,
        )

    result = execute(runtime, case, get_adapter=lambda name: historical)
    assert result['steps'][1]['failure']['code'] == 'input_partial_not_accepted'
    task = case.context.task_results['search']
    before = deepcopy(task.to_dict())
    restarted = case.fixture.restart()
    with pytest.raises(runtime.contracts.ResultNotReadyError):
        restarted.open_result(task.output('sources'))
    partial_reader = restarted.open_result(task.output('sources'), allow_partial=True)
    retained_sources = list(partial_reader.iter_items())
    assert retained_sources == [source()]
    record = {
        'id': 'run-1', 'plan': case.plan, 'execution_steps': result['steps'],
        'status': 'failed', 'outcome': 'partial', 'started_at': '2026-10-16T00:00:00Z',
        'checkpoint_version': runtime.checkpoints.CHECKPOINT_VERSION, 'execution_binding': {'present': True},
    }
    for step in record['execution_steps']:
        step['checkpoint_available'] = True
    rerun, blocked = recovery._partial_dependency_recovery(record)
    projection = recovery.recovery_projection(record)
    assert rerun == set() and blocked == {'search'}
    assert projection['eligible'] is False
    assert projection['reason_code'] == 'search_result_incomplete'
    assert task.to_dict() == before
    assert 'discarded content cannot' in projection['message']
    search_only = deepcopy(record)
    search_only['plan']['steps'] = [search_only['plan']['steps'][0]]
    search_only['execution_steps'] = [search_only['execution_steps'][0]]
    search_only_projection = recovery.recovery_projection(search_only)
    assert search_only_projection['eligible'] is False
    assert search_only_projection['reason_code'] == 'search_result_incomplete'
    calls = install_search(monkeypatch, [])
    case.context = runtime.executor.RunContext(
        run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
        user_message='Prepare the requested content.', plan_contract_version=2,
        result_service=restarted, resolve_source_manifest=case.fixture.resolve,
        result_guard_token_for_step=lambda step_id: 'owned-execution-token', invoke_prompt=case.model,
    )
    resumed = execute(runtime, case)
    assert calls == []
    assert resumed['task_results']['search'] == before
    assert resumed['steps'][1]['failure']['code'] == 'input_partial_not_accepted'


def test_real_analyze_preserves_search_selection_coverage(internal, monkeypatch):
    executor = importlib.import_module('functions_orchestration_executor')
    schema = importlib.import_module('functions_orchestration_schema')
    hits = [
        {'document_id': 'document-1', 'id': f'hit-{index}', 'chunk_text': 'é' * 1800}
        for index in range(12)
    ]
    install_search(monkeypatch, hits)
    settings = {'enable_user_workspace': True}
    plan = schema.normalize_plan(
        {'run_id': 'run-1', 'steps': [
            search_step(),
            {'step_id': 'analyze', 'capability_id': 'document_analyze',
             'arguments': {'analysis_prompt': 'Retain all original findings.'},
             'inputs': {'sources': source_input('search', 'sources')}},
        ]},
        'conversation-1', 'owner', settings=settings, contract_version=2,
        available_capability_ids=['document_search', 'document_analyze'],
    )
    internal.fixture.runs['run-1']['plan'] = plan
    context = executor.RunContext(
        run_id='run-1', plan_id=plan['plan_id'], conversation_id='conversation-1', user_id='owner',
        user_message='Analyze the discovered documents.', plan_contract_version=2,
        result_service=internal.fixture.service, resolve_source_manifest=internal.fixture.resolve,
        invoke_prompt=internal.context.invoke_prompt,
        result_guard_token_for_step=lambda step_id: (
            internal.checkpoints[step_id].token if step_id == 'analyze' else 'owned-search-token'
        ),
    )
    context.analysis_checkpoint_factory = internal.context.analysis_checkpoint_factory
    result = executor.execute_plan(plan, context, settings=settings, user_id='owner')
    assert result['status'] == result['outcome'] == 'completed', result
    restarted = internal.fixture.restart()
    task = context.task_results['analyze']
    findings = list(restarted.open_result(task.output('findings')).iter_records())
    coverage = restarted.open_result(task.output('coverage')).read_value()
    assert len(findings) == 151
    assert any('Top-N' in item for item in task.output('findings').completeness.limitations)
    assert any('Top-N' in item for item in coverage['source_selection_limitations'])
    manifest = restarted.store.load_committed_orchestration_result(
        'owner', 'conversation-1', 'run-1', 'analyze', task.output('findings').manifest_sha256,
    )
    assert manifest['lineage']['upstream'] == [context.task_results['search'].output('sources').to_dict()]
    assert internal.hooks.call_count == 0
