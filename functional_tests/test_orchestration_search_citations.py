# test_orchestration_search_citations.py
"""Search content handoffs retain exact passage citations, not just document identities.

Version: 0.261.365
Implemented in: 0.261.365

The real adapters, retained readers, lineage projection and Compose execute with
offline search/model/storage transport. No external qualification harness is changed.
"""

from copy import deepcopy
from dataclasses import replace
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from test_orchestration_dependency_runtime import binding, compose, execute, runtime, source_input


__all__ = ['runtime']

HITS = [
    {
        'document_id': 'document-1', 'id': 'document-1_2', 'file_name': 'Policy.md',
        'page_number': 2, 'chunk_sequence': 2, 'chunk_text': 'Reviews are due in 10 business days.',
    },
    {
        'document_id': 'document-1', 'id': 'document-1_7', 'file_name': 'Policy.md',
        'page_number': 7, 'chunk_sequence': 7, 'chunk_text': 'The responsible owner is Rowan.',
    },
    {
        'document_id': 'document-2', 'id': 'document-2_3', 'file_name': 'Acquisitions.md',
        'page_number': 3, 'chunk_sequence': 3, 'chunk_text': 'The spending threshold is USD 125000.',
    },
]


def search_step():
    return {
        'step_id': 'search', 'capability_id': 'document_search',
        'arguments': {'query': 'What do I need to know before starting an acquisition?'},
    }


@pytest.fixture
def search_content(runtime, monkeypatch):
    calls = []
    search = ModuleType('functions_search')

    def hybrid_search(*args, **kwargs):
        calls.append((args, kwargs))
        return deepcopy(HITS)

    search.hybrid_search = hybrid_search
    monkeypatch.setitem(sys.modules, 'functions_search', search)

    def make(steps=None, replies=(), final_response=None):
        case = runtime.make(steps or [search_step()], replies, final_response=final_response)
        case.fixture.sources['document-2'] = {
            **case.fixture.sources['document-1'], 'document_id': 'document-2',
        }
        return case

    return SimpleNamespace(runtime=runtime, calls=calls, make=make)


@pytest.mark.parametrize('output', ['evidence', 'prepared'])
def test_search_content_supplies_real_copyable_passage_citations(search_content, output):
    case = search_content.make()
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    reference = case.context.task_results['search'].output(output)
    citations = search_content.runtime.composition._input_document_citations(case.context, reference)
    assert [item['citation_id'] for item in citations] == [hit['id'] for hit in HITS]
    assert [item['page_number'] for item in citations] == [2, 7, 3]
    assert [item['file_name'] for item in citations] == [hit['file_name'] for hit in HITS]
    assert all(f"[#{hit['id']}]" in item['citation'] for hit, item in zip(HITS, citations))
    if output == 'evidence':
        assert [item['evidence_id'] for item in citations] == ['excerpt-0', 'excerpt-1', 'excerpt-2']
    assert case.model.calls == [] and len(search_content.calls) == 1


@pytest.mark.parametrize('scope, scope_id', [
    ('personal', 'owner'), ('group', 'group-1'), ('public', 'public-1'), ('chat', 'conversation-1'),
])
def test_evidence_citations_use_authorized_scope_and_exact_sidecar_digest(search_content, monkeypatch, scope, scope_id):
    case = search_content.make()
    for source in case.fixture.sources.values():
        source.update(scope=scope, scope_id=scope_id)
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    reference = case.context.task_results['search'].output('evidence')
    opened = []
    open_result = case.fixture.service.open_result

    def track_sidecar(current, **kwargs):
        if current.output_name == 'prepared':
            opened.append(current)
        return open_result(current, **kwargs)

    monkeypatch.setattr(case.fixture.service, 'open_result', track_sidecar)
    citations = search_content.runtime.composition._input_document_citations(case.context, reference)
    assert len(opened) == 1
    assert opened[0].producer == reference.producer
    assert opened[0].manifest_sha256 == reference.manifest_sha256
    assert opened[0].kind == 'structured-v1'
    assert [item['citation_id'] for item in citations] == [hit['id'] for hit in HITS]
    assert all(item['scope'] == {'type': scope, 'id': scope_id} for item in citations)
    assert all(item['group_id'] == (scope_id if scope == 'group' else None) for item in citations)
    assert all(item['public_workspace_id'] == (scope_id if scope == 'public' else None) for item in citations)


@pytest.mark.parametrize('output', ['evidence', 'prepared'])
@pytest.mark.parametrize('chained', [False, True])
def test_search_content_citations_reach_composition_and_reopen_without_retrieval(search_content, output, chained):
    answer = 'Rowan owns the review. (Source: Policy.md, Page: 7) [#document-1_7]'
    steps = [
        search_step(), compose('answer', inputs={'passages': source_input('search', output)}),
    ]
    if chained:
        steps.append(compose('final', inputs={'draft': source_input('answer', 'answer')}))
    case = search_content.make(
        steps, [answer] * (2 if chained else 1), binding('final' if chained else 'answer'),
    )
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    messages = case.model.calls[0][0]
    payload = json.loads(messages[-1]['content'])
    citations = payload['inputs']['passages']['document_citations']
    assert [item['citation_id'] for item in citations] == [hit['id'] for hit in HITS]
    assert any('copy its citation value verbatim' in message['content'] for message in messages)
    if output == 'evidence':
        excerpts = {item['evidence_id']: item['text'] for item in payload['inputs']['passages']['value']}
        assert [excerpts[item['evidence_id']] for item in citations] == [hit['chunk_text'] for hit in HITS]
    assert result['message'] == answer
    reference = case.context.task_results['final' if chained else 'answer'].output('answer')
    fresh = SimpleNamespace(result_service=case.fixture.restart())
    reopened = search_content.runtime.result_runtime.read_result_document_citations(fresh, reference)
    assert reopened == result['citations']
    assert [item['citation_id'] for item in reopened] == [hit['id'] for hit in HITS]
    assert len(search_content.calls) == 1 and len(case.model.calls) == (2 if chained else 1)


def test_search_source_identities_do_not_become_passage_citations(search_content):
    case = search_content.make()
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    reference = case.context.task_results['search'].output('sources')
    citations = search_content.runtime.composition._input_document_citations(case.context, reference)
    assert citations == []


def test_missing_locations_are_not_replaced_with_invented_pages(search_content, monkeypatch):
    search = sys.modules['functions_search']
    monkeypatch.setattr(search, 'hybrid_search', lambda *args, **kwargs: [{
        'document_id': 'document-1', 'id': 'real-chunk', 'file_name': 'Policy.md',
        'chunk_text': 'A passage with no stored location.',
    }])
    case = search_content.make()
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    reference = case.context.task_results['search'].output('evidence')
    citations = search_content.runtime.composition._input_document_citations(case.context, reference)
    assert citations == []


def test_same_search_bound_as_both_content_outputs_does_not_duplicate_citations(search_content):
    case = search_content.make([
        search_step(), compose('answer', inputs={
            'passages': source_input('search', 'evidence'),
            'prepared': source_input('search', 'prepared'),
        }),
    ], ['The review takes 10 business days.'], binding('answer'))
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    assert [item['citation_id'] for item in result['citations']] == [hit['id'] for hit in HITS]


@pytest.mark.parametrize('missing', ['search_results', 'citations'])
def test_historical_search_without_locator_association_remains_provenance_only(search_content, monkeypatch, missing):
    case = search_content.make()
    persist = case.fixture.service.persist_task_result

    def persist_historical(**kwargs):
        outputs = []
        for output in kwargs['outputs']:
            if output.name == 'prepared':
                value = deepcopy(output.value)
                if missing == 'search_results':
                    value.pop('search_results')
                else:
                    value['citations'] = [
                        {**citation, 'citation_id': None}
                        for citation in value['citations']
                    ]
                    for hit in value['search_results']:
                        hit.pop('id')
                output = replace(output, value=value)
            outputs.append(output)
        return persist(**{**kwargs, 'outputs': outputs})

    monkeypatch.setattr(case.fixture.service, 'persist_task_result', persist_historical)
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    reference = case.context.task_results['search'].output('evidence')
    copyable = search_content.runtime.composition._input_document_citations(case.context, reference)
    assert copyable == []
    projected = search_content.runtime.result_runtime.read_result_document_citations(case.context, reference)
    assert {item['document_id'] for item in projected} == {'document-1', 'document-2'}
    assert case.model.calls == []


def test_historical_evidence_without_a_prepared_sidecar_remains_provenance_only(runtime):
    case = runtime.make([search_step()])
    step = case.plan['steps'][0]
    source = case.fixture.sources['document-1']
    task = case.fixture.service.persist_task_result(
        producer=case.context.result_producer(step), role='gather', status='complete',
        outputs=[runtime.NamedOutput('evidence', 'evidence-set-v1', [{
            'evidence_id': 'legacy-excerpt', 'source': source, 'text': 'An older retained excerpt.',
        }], runtime.complete(1))],
        sources=[source], origin='grounded',
        guard_token=case.context.result_guard_token_for_step('search'),
    )
    citations = runtime.composition._input_document_citations(case.context, task.output('evidence'))
    assert citations == []
    projected = runtime.result_runtime.read_result_document_citations(case.context, task.output('evidence'))
    assert projected == [{
        'source_type': 'document', 'document_id': 'document-1',
        'scope': {'type': 'personal', 'id': 'owner'}, 'group_id': None, 'public_workspace_id': None,
    }]
    assert case.model.calls == []


def test_evidence_sidecar_verifies_stored_content_digest_without_fallback(search_content):
    case = search_content.make()
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    reference = case.context.task_results['search'].output('evidence')
    producer = reference.producer
    args = producer.user_id, producer.conversation_id, producer.run_id, producer.step_id
    store = case.fixture.service.store
    manifest = store.load_committed_orchestration_result(*args, reference.manifest_sha256)
    manifest['outputs']['prepared']['content_sha256'] = '0' * 64
    token = case.context.result_guard_token_for_step('search')
    stored = store.save_orchestration(*args, manifest, guard_token=token, require_analysis_guard=True)
    store.commit_orchestration_result(*args, stored, guard_token=token)
    corrupted = replace(reference, manifest_sha256=stored['sha256'])
    with pytest.raises(search_content.runtime.contracts.ResultContractError) as failure:
        search_content.runtime.result_runtime.read_result_document_citations(case.context, corrupted)
    assert failure.value.code == 'result_content_integrity'
    assert case.model.calls == [] and len(search_content.calls) == 1


@pytest.mark.parametrize('mutation', ['shape', 'scope', 'source', 'passage', 'locator', 'count', 'page'])
def test_invalid_search_sidecar_cannot_supply_evidence_citations(search_content, monkeypatch, mutation):
    case = search_content.make()
    persist = case.fixture.service.persist_task_result

    def persist_invalid(**kwargs):
        outputs = list(kwargs['outputs'])
        index = next(index for index, output in enumerate(outputs) if output.name == 'prepared')
        value = deepcopy(outputs[index].value)
        if mutation == 'shape':
            value['citations'] = {}
        elif mutation == 'scope':
            value['citations'][0]['group_id'] = 'another-group'
        elif mutation == 'source':
            value['citations'][0]['document_id'] = 'not-in-lineage'
        elif mutation == 'passage':
            value['search_results'][0]['chunk_text'] = 'Different content from the evidence.'
        elif mutation == 'locator':
            value['citations'][0]['citation_id'] = 'not-the-returned-chunk'
        elif mutation == 'count':
            value['search_results'].pop()
        else:
            value['citations'][0]['page_number'] = 99
        outputs[index] = replace(outputs[index], value=value)
        return persist(**{**kwargs, 'outputs': outputs})

    monkeypatch.setattr(case.fixture.service, 'persist_task_result', persist_invalid)
    result = execute(search_content.runtime, case)
    assert result['status'] == 'completed', result
    reference = case.context.task_results['search'].output('evidence')
    with pytest.raises(search_content.runtime.contracts.ResultContractError):
        search_content.runtime.result_runtime.read_result_document_citations(case.context, reference)
    assert case.model.calls == []
