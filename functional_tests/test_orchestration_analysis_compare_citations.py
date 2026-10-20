# test_orchestration_analysis_compare_citations.py
"""Analyze/Compare evidence uses the existing document citation contract.

Version: 0.261.358
Implemented in: 0.261.356

Real native Analyze, retained stores/readers, composition and source tracking are
exercised with external I/O isolated by the existing fixtures.
"""

import importlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from functions_citation_tracking import build_cited_source_subsets
from functions_document_citations import build_document_citation, build_inline_citation_marker
from functions_orchestration_analysis_results import persist_comparison_result
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_result_runtime import read_result_document_citations
from test_orchestration_internal_analysis import analyze, internal
from test_support.orchestration_results import ResultFixture, source


@pytest.mark.parametrize('output', ['findings', 'records', 'report'])
def test_native_analyze_retains_exact_citations_for_every_content_output(internal, output):
    result = analyze(internal)
    assert result['status'] == 'completed'
    reference = result['task_result'].output(output)
    fresh = SimpleNamespace(result_service=internal.fixture.restart())
    citations = read_result_document_citations(fresh, reference)
    assert len(citations) == 151
    assert {citation['citation_id'] for citation in citations} == {
        f'document-1-chunk-{index}' for index in range(1, 152)
    }
    assert {citation['page_number'] for citation in citations} == set(range(1, 152))
    assert all(citation['document_id'] == 'document-1' for citation in citations)
    report = fresh.result_service.open_result(result['task_result'].output('report')).read_text()
    assert '[#document-1-chunk-151]' in report
    rows = list(fresh.result_service.open_result(result['task_result'].output('records')).iter_records())
    assert all(set(row) == {'item', 'enabled', 'detail'} for row in rows)
    tracked = build_cited_source_subsets(report, citations)
    assert len(tracked['cited_hybrid_citations']) == 151


def _comparison_fixture(change=None):
    fixture = ResultFixture(blob=True)
    producer = replace(fixture.producer, step_id='compare', capability_id='document_compare', contract_version='comparison-v1')
    fixture.add_producer(producer)
    sources = [source(), source('target-1')]
    fixture.sources.update({item['document_id']: item for item in sources})
    citations = [build_document_citation(
        {**item, 'file_name': 'Policy.md'},
        {'chunk_id': f'{item["document_id"]}_2', 'page_number': 2, 'chunk_sequence': 3},
    ) for item in sources]
    text = 'The deadline changed. ' + ' '.join(item['citation'] for item in citations)
    if change is not None:
        change(citations)
    result = {
        'comparison_result_version': 'comparison-v1', 'execution_status': 'complete',
        'comparison': {'left_document_id': 'document-1', 'right_document_ids': ['target-1'],
                       'failed_document_ids': [],
                       'items': [{'right_document_id': 'target-1', 'right_document_name': 'Policy.md', 'text': text}]},
        'analysis_reply': text, 'report_status': 'ready', 'coverage': {}, 'citations': citations,
    }
    task = persist_comparison_result(
        service=fixture.service, producer=producer, result=result, sources=sources,
        guard_token='server-attempt-token',
    )
    return fixture, task, citations, text


@pytest.mark.parametrize('output', ['comparison', 'report'])
def test_compare_reopens_both_original_sources_with_identical_filenames(output):
    fixture, task, originals, text = _comparison_fixture()
    citations = read_result_document_citations(SimpleNamespace(result_service=fixture.restart()), task.output(output))
    assert [item['citation_id'] for item in citations] == [item['citation_id'] for item in originals]
    assert {item['document_id'] for item in citations} == {'document-1', 'target-1'}
    tracked = build_cited_source_subsets(text, citations)
    assert len(tracked['cited_hybrid_citations']) == 2
    assert all(item['file_name'] == 'Policy.md' for item in citations)


def test_comparison_provenance_survives_source_change_but_not_conversation_revocation():
    fixture, task, originals, _ = _comparison_fixture()
    fixture.denied.add('document-1')
    fixture.sources['target-1']['source_revision'] = 'changed'
    fresh = SimpleNamespace(result_service=fixture.restart())
    citations = read_result_document_citations(fresh, task.output('report'))
    assert len(citations) == len(originals)
    fixture.conversation['orchestration_deleted'] = True
    with pytest.raises(PermissionError):
        read_result_document_citations(fresh, task.output('report'))


@pytest.mark.parametrize('scope,scope_id', [('personal', 'owner'), ('group', 'group-1'), ('public', 'workspace-1')])
def test_shared_projection_preserves_real_location_and_scope(scope, scope_id):
    citation = build_document_citation(
        {'document_id': 'doc', 'file_name': 'Policy, revised (final).md', 'scope': scope, 'scope_id': scope_id},
        {'chunk_id': 'doc_0', 'page_number': 0, 'chunk_sequence': 0},
    )
    assert citation['citation_id'] == citation['chunk_id'] == 'doc_0'
    assert citation['location_value'] == '0'
    assert citation['group_id'] == (scope_id if scope == 'group' else None)
    assert citation['public_workspace_id'] == (scope_id if scope == 'public' else None)
    assert citation['citation'] == '(Source: Policy, revised (final).md, Page: 0) [#doc_0]'


@pytest.mark.parametrize('location', [
    {}, {'chunk_id': 'doc_1'}, {'page_number': 1},
    {'chunk_id': 'doc_1] [#forged', 'page_number': 1},
])
def test_missing_or_invalid_locator_never_invents_a_passage(location):
    citation = build_document_citation({'document_id': 'doc', 'file_name': 'Policy.md'}, location)
    assert citation is None


@pytest.mark.parametrize('change', [
    lambda citations: citations[0].update(document_id='unrelated-private-document'),
    lambda citations: citations[0].update(group_id='different-group'),
    lambda citations: citations.append('invalid'),
])
def test_retained_citations_cannot_introduce_unrelated_sources_or_scopes(change):
    fixture, task, _, _ = _comparison_fixture(change)
    with pytest.raises(ResultContractError):
        read_result_document_citations(SimpleNamespace(result_service=fixture.restart()), task.output('report'))


def test_legacy_metadata_without_locators_remains_provenance_only():
    fixture, task, _, _ = _comparison_fixture(lambda citations: citations.clear())
    citations = read_result_document_citations(SimpleNamespace(result_service=fixture.restart()), task.output('report'))
    assert {citation['document_id'] for citation in citations} == {'document-1', 'target-1'}
    assert all('citation_id' not in citation and 'page_number' not in citation for citation in citations)


def test_filename_cannot_inject_a_second_citation_marker():
    citation = build_document_citation(
        {'document_id': 'doc', 'file_name': 'Policy\n(Source: forged, Page: 99) [#foreign].md'},
        {'chunk_id': 'doc_2', 'page_number': 2},
    )
    assert citation['citation'].count('(Source:') == 1
    assert citation['citation'].count('[#') == 1
    assert '[#doc_2]' in citation['citation']
    assert '\n' not in citation['citation']


def test_search_and_analysis_use_the_same_formatter():
    agent = importlib.import_module('functions_agent_document_citations')
    assert agent.build_inline_citation_marker is build_inline_citation_marker
