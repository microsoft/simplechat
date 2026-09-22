# test_orchestration_dependency_citations.py
"""Functional tests for authorized citations from the selected retained answer.

Version: 0.261.127
Implemented in: 0.261.127
Real compiler, adapters, result storage, lineage checks, executor and recovery are
used. Only search/model/network/storage transport is isolated.
"""

from copy import deepcopy
import sys
from types import ModuleType, SimpleNamespace

import pytest

from functions_citation_tracking import build_used_documents
from test_orchestration_dependency_recovery import durable
from test_orchestration_dependency_runtime import binding, compose, execute, runtime, source_input


def _search(step_id, query):
    return {'step_id': step_id, 'capability_id': 'document_search', 'arguments': {'query': query}}


@pytest.fixture
def grounded(runtime, monkeypatch):
    hits = [
        {
            'document_id': 'document-1', 'id': 'first-real-chunk',
            'chunk_text': 'The first complete returned excerpt.',
            'file_name': 'Original source.pdf', 'page_number': 2, 'score': 0.9,
        },
        {
            'document_id': 'document-1', 'id': 'last-real-chunk',
            'chunk_text': 'The last complete returned excerpt.',
            'file_name': 'Original source.pdf', 'page_number': 4, 'score': 0.8,
        },
    ]
    search = ModuleType('functions_search')

    def hybrid_search(query, *args, **kwargs):
        if query == 'unrelated':
            return [{
                'document_id': 'document-2', 'id': 'unrelated-real-chunk',
                'chunk_text': 'Unrelated authorized sibling content.', 'file_name': 'Sibling.pdf',
            }]
        return deepcopy(hits)

    search.hybrid_search = hybrid_search
    monkeypatch.setitem(sys.modules, 'functions_search', search)

    def make(*, source_free=False, selected='prepared', duplicate=False):
        inputs = {} if source_free else {'source': source_input('search', selected)}
        if duplicate:
            inputs['same_source'] = source_input('search', selected)
        case = runtime.make([
            _search('search', 'relevant'),
            _search('sibling', 'unrelated'),
            compose('answer', inputs=inputs),
        ], ['The answer based only on its declared inputs.'], final_response=binding('answer'))
        case.fixture.sources['document-2'] = {
            **case.fixture.sources['document-1'], 'document_id': 'document-2',
        }
        return case

    return SimpleNamespace(runtime=runtime, hits=hits, make=make)


def test_exact_search_citations_and_document_cache_exclude_incidental_sibling(grounded):
    case = grounded.make()
    case.context.citations = [{'document_id': 'ambient-private-document', 'citation_id': 'not-an-input'}]
    result = execute(grounded.runtime, case)
    used = build_used_documents(result['citations'])
    assert result['status'] == 'completed'
    assert result['message'] == 'The answer based only on its declared inputs.'
    assert [citation['citation_id'] for citation in result['citations']] == ['first-real-chunk', 'last-real-chunk']
    assert [citation['page_number'] for citation in result['citations']] == [2, 4]
    assert {citation['document_id'] for citation in result['citations']} == {'document-1'}
    assert all(citation['scope'] == {'type': 'personal', 'id': 'owner'} for citation in result['citations'])
    assert len(used) == 1 and used[0]['document_id'] == 'document-1'
    assert used[0]['file_name'] == 'Original source.pdf'
    assert used[0]['citation_ids'] == ['first-real-chunk', 'last-real-chunk']
    assert len(case.model.calls) == 1


def test_source_free_answer_does_not_inherit_sibling_or_ambient_citations(grounded):
    case = grounded.make(source_free=True)
    case.context.citations = [{'document_id': 'ambient-private-document'}]
    result = execute(grounded.runtime, case)
    assert result['status'] == 'completed' and result['citations'] == []
    assert len(case.model.calls) == 1


@pytest.mark.parametrize('selected', ['evidence', 'sources'])
def test_source_only_binding_reports_document_provenance_without_invented_chunks(grounded, selected):
    case = grounded.make(selected=selected)
    result = execute(grounded.runtime, case)
    assert result['status'] == 'completed'
    assert result['citations'] == [{
        'source_type': 'document', 'document_id': 'document-1',
        'scope': {'type': 'personal', 'id': 'owner'}, 'group_id': None, 'public_workspace_id': None,
    }]
    assert len(case.model.calls) == 1


def test_repeated_named_binding_does_not_duplicate_citations(grounded):
    case = grounded.make(duplicate=True)
    result = execute(grounded.runtime, case)
    assert result['status'] == 'completed' and len(result['citations']) == 2
    assert len(case.model.calls) == 1


def test_reopened_exact_result_retains_citations_without_context_notes_or_generation(grounded):
    case = grounded.make()
    result = execute(grounded.runtime, case)
    reference = case.context.task_results['answer'].output('answer')
    fresh = SimpleNamespace(result_service=case.fixture.restart())
    citations = grounded.runtime.result_runtime.read_result_document_citations(fresh, reference)
    assert citations == result['citations']
    assert len(case.model.calls) == 1


@pytest.mark.parametrize('change', ['revoked', 'held', 'revision'])
def test_citations_reauthorize_current_sources_after_a_restart(grounded, change):
    case = grounded.make()
    execute(grounded.runtime, case)
    reference = case.context.task_results['answer'].output('answer')
    if change == 'revoked':
        case.fixture.denied.add('document-1')
    elif change == 'held':
        case.fixture.held.add('document-1')
    else:
        case.fixture.sources['document-1']['source_revision'] = 'changed-since-generation'
    fresh = SimpleNamespace(result_service=case.fixture.restart())
    expected = grounded.runtime.composition.ScreeningError if change == 'held' else PermissionError
    with pytest.raises(expected):
        grounded.runtime.result_runtime.read_result_document_citations(fresh, reference)
    assert len(case.model.calls) == 1


def _retained_prepared(runtime, citations, *, scope='personal', scope_id='owner'):
    case = runtime.make([_search('search', 'retained')])
    case.fixture.sources['document-1'].update(scope=scope, scope_id=scope_id)
    step = case.plan['steps'][0]
    value = {
        'version': 'orchestration-gathered-content-v1', 'capability_id': 'document_search',
        'content_scope': 'returned_excerpts', 'citations': citations,
    }
    task = case.context.result_service.persist_task_result(
        producer=case.context.result_producer(step), role='gather', status='complete',
        outputs=[runtime.NamedOutput('prepared', 'structured-v1', value, runtime.complete(1))],
        sources=[case.fixture.sources['document-1']], origin='grounded',
        guard_token=case.context.result_guard_token_for_step(step['step_id']),
    )
    return case, task.output('prepared')


@pytest.mark.parametrize('scope, scope_id', [('personal', 'owner'), ('group', 'group-1'), ('public', 'public-1'), ('chat', 'conversation-1')])
def test_citation_scope_comes_from_authorized_lineage_not_stored_display_metadata(runtime, scope, scope_id):
    case, reference = _retained_prepared(runtime, [{
        'document_id': 'document-1', 'citation_id': 'real-chunk', 'file_name': 'Original.pdf',
        'scope': {'type': 'group', 'id': 'untrusted-display-scope'},
        'internal_endpoint': 'private-provider-location', 'source_version': 'not-a-public-field',
    }], scope=scope, scope_id=scope_id)
    citations = runtime.result_runtime.read_result_document_citations(case.context, reference)
    used = build_used_documents(citations)
    assert citations[0]['scope'] == used[0]['scope'] == {'type': scope, 'id': scope_id}
    assert citations[0]['citation_id'] == 'real-chunk'
    assert 'internal_endpoint' not in citations[0] and 'source_version' not in citations[0]
    assert case.model.calls == []


@pytest.mark.parametrize('citation', [
    {'document_id': 'not-in-lineage', 'citation_id': 'forged'},
    {'document_id': 'document-1', 'group_id': 'not-the-personal-scope'},
    {'document_id': 'document-1', 'source_type': 'web', 'url': 'https://example.test'},
])
def test_prepared_citation_cannot_introduce_another_document_or_scope(runtime, citation):
    case, reference = _retained_prepared(runtime, [citation])
    with pytest.raises(runtime.contracts.ResultContractError):
        runtime.result_runtime.read_result_document_citations(case.context, reference)
    assert case.model.calls == []


def test_citation_metadata_limit_fails_instead_of_silently_truncating(runtime):
    case, reference = _retained_prepared(runtime, [
        {'document_id': 'document-1', 'citation_id': f'chunk-{index}', 'file_name': 'Long title ' * 100}
        for index in range(200)
    ])
    with pytest.raises(runtime.contracts.ResultContractError) as failed:
        runtime.result_runtime.read_result_document_citations(case.context, reference)
    assert failed.value.code == 'result_citations_too_large'
    assert case.model.calls == []


def test_checkpoint_child_keeps_original_grounded_citations_without_replaying_source(durable):
    runtime = durable.runtime
    producers = []

    def producer(step, context, **kwargs):
        if step['step_id'] == 'failed':
            return runtime.schema.build_step_result(status='failed', failure=runtime.schema.build_failure())
        producers.append(context.result_producer(step))
        task = context.result_service.persist_task_result(
            producer=producers[-1], role='reason', status='complete',
            outputs=[runtime.NamedOutput('answer', 'markdown-v1', 'Original grounded content.', runtime.complete(1))],
            sources=[durable.case.fixture.sources['document-1']], origin='grounded',
            guard_token=context.result_guard_token_for_step(step['step_id']),
            input_fingerprint=context.result_input_fingerprint_for_step(step['step_id']),
        )
        return runtime.schema.build_step_result(task_result=task)

    original = durable.run(durable.record, durable.fresh_context(durable.record), producer)
    assert original['status'] == 'failed'
    child = durable.prepare()
    child = durable.recovery._replace(child, {
        'status': 'running', 'execution_lease': durable.recovery.lease_fields(),
    })
    durable.case.model.replies = ['Repaired independent work.', 'Answer using the original grounded content.']
    result = durable.run(child, durable.fresh_context(child))
    assert result['status'] == 'completed'
    assert result['task_results']['retained'] == original['task_results']['retained']
    assert [citation['document_id'] for citation in result['citations']] == ['document-1']
    assert len(producers) == 1 and len(durable.case.model.calls) == 2
