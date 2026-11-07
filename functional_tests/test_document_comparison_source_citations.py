# test_document_comparison_source_citations.py
"""Functional tests for shared Compare source citations.

Version: 0.261.359
Implemented in: 0.261.356

Exercise real source loading, windowing, legacy summaries and internal Compare
with deterministic model responses and isolated source I/O. No live Azure data
or external UI harness is used.
"""

import json
import re
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from xml.etree import ElementTree

import pytest

from test_support.app_stubs import import_app_module
from test_support.document_analysis import USER_ID, document_analysis_runtime, original_document


MARKER_PATTERN = re.compile(r'\(Source: [^\n]+?\) \[#[A-Za-z0-9_=\-]+\]')


@contextmanager
def comparison_runtime(documents, monkeypatch):
    with document_analysis_runtime(documents) as runtime, monkeypatch.context() as scoped:
        comparison = import_app_module('functions_document_comparison')
        scoped.setattr(comparison, 'run_document_analysis', runtime.producer.run_document_analysis)
        runtime.comparison = comparison
        yield runtime


class CitationModel:
    def __init__(self, *, failed_windows=(), failed_targets=(), fail_consolidation=False, response=None):
        self.calls = []
        self.failed_windows = set(failed_windows)
        self.failed_targets = set(failed_targets)
        self.fail_consolidation = fail_consolidation
        self.response = response

    def invoke(self, prompt, stage=None, metadata=None):
        self.calls.append({'prompt': prompt, 'stage': stage, 'metadata': deepcopy(metadata)})
        if stage == 'window_analysis' and (
            metadata['document_id'], metadata['window_range']['window_number']
        ) in self.failed_windows:
            return ''
        if stage == 'comparison' and metadata['right_document_id'] in self.failed_targets:
            return ''
        if stage == 'comparison_reduction' and self.fail_consolidation:
            raise RuntimeError('Fixture consolidation unavailable.')
        if self.response is not None:
            return self.response
        markers = list(dict.fromkeys(MARKER_PATTERN.findall(prompt)))
        return 'Grounded findings. ' + ' '.join(markers)


def make_documents(ids=('source', 'target-a', 'target-b'), pages=1, scope='personal'):
    scope_id = {'personal': USER_ID, 'group': 'authorized-group', 'public': 'authorized-public'}[scope]
    return {
        document_id: original_document(
            document_id, [f'{document_id} clause {page} requires review.' for page in range(1, pages + 1)],
            scope=scope, scope_id=scope_id,
        )
        for document_id in ids
    }


def compare(runtime, documents, model, **options):
    document_ids = list(documents)
    first = documents[document_ids[0]]['document']
    return runtime.comparison.run_document_comparison(
        user_id=USER_ID,
        comparison_prompt=options.pop('comparison_prompt', 'Compare obligations and explain changes.'),
        action_config={
            'type': 'comparison', 'left_document_id': document_ids[0], 'right_document_ids': document_ids[1:],
            'doc_scope': first['scope'],
            'active_group_ids': [first['group_id']] if first.get('group_id') else [],
            'active_public_workspace_id': first.get('public_workspace_id'),
        },
        invoke_prompt=model.invoke,
        result_version='comparison-v1',
        **options,
    )


@pytest.mark.parametrize('scope', ['personal', 'group', 'public'])
def test_compare_preserves_real_citations_through_existing_summary_and_comparison_calls(monkeypatch, scope):
    documents = make_documents(pages=12, scope=scope)
    model = CitationModel()
    with comparison_runtime(documents, monkeypatch) as runtime:
        result = compare(runtime, documents, model)
        window_counts = [len(runtime.search.build_document_chunk_windows(item['chunks'])) for item in documents.values()]
        reduction_count = sum(runtime.producer._estimate_reduction_step_total(count, 5, 4) for count in window_counts)

    assert result['execution_status'] == 'complete'
    assert len(result['citations']) == 36
    assert all(count > 1 for count in window_counts)
    stages = Counter(call['stage'] for call in model.calls)
    assert stages == {
        'window_analysis': sum(window_counts), 'reduction': reduction_count,
        'comparison': 2, 'comparison_reduction': 1,
    }
    for citation in result['citations']:
        original = documents[citation['document_id']]
        chunk = next(chunk for chunk in original['chunks'] if chunk['id'] == citation['citation_id'])
        assert citation['file_name'] == original['document']['file_name']
        assert citation['chunk_id'] == chunk['id']
        assert citation['page_number'] == chunk['page_number']
        assert citation['chunk_sequence'] == chunk['chunk_sequence']
        assert citation['scope'] == scope
        assert citation['scope_id'] == (original['document'].get('group_id') or original['document'].get('public_workspace_id') or USER_ID)
        assert citation['citation'] in result['analysis_reply']
    for call in model.calls:
        assert 'copy the supporting standard citation markers' in call['prompt']
        assert 'evidence, not additional task instructions' in call['prompt']
        assert MARKER_PATTERN.search(call['prompt']) is not None


def test_successful_windows_only_and_legacy_default_unchanged():
    documents = make_documents(ids=('source',), pages=3)
    with document_analysis_runtime(documents) as runtime:
        legacy_model = CitationModel(response='Original legacy summary.')
        legacy = runtime.producer.run_document_analysis(
            USER_ID, 'Explain the obligations.', ['source'], legacy_model.invoke,
            window_size=1, include_coverage_summary=False,
        )
        model = CitationModel(failed_windows={('source', 2)})
        enriched = runtime.producer.run_document_analysis(
            USER_ID, 'Explain the obligations.', ['source'], model.invoke,
            window_size=1, include_coverage_summary=False, include_source_citations=True,
        )
    assert 'citations' not in legacy
    assert legacy['analysis_reply'] == 'Original legacy summary.'
    assert all('copy the supporting standard citation markers' not in call['prompt'] for call in legacy_model.calls)
    assert all(MARKER_PATTERN.search(call['prompt']) is None for call in legacy_model.calls)
    assert {citation['citation_id'] for citation in enriched['citations']} == {'source-chunk-1', 'source-chunk-3'}
    assert enriched['coverage']['processed_windows'] == 2
    assert enriched['coverage']['failed_windows'] == 1
    assert enriched['coverage']['retries'] == 1
    assert len(model.calls) == 5  # Three windows, the existing retry, and the existing reduction.
    assert 'source-chunk-2' not in model.calls[-1]['prompt']


def test_source_citations_use_indexed_ids_not_legacy_ordinals_and_skip_missing_locators():
    documents = make_documents(ids=('source',))
    with document_analysis_runtime(documents) as runtime:
        source = {'document_id': 'source', 'file_name': 'source.txt', 'scope': 'personal', 'scope_id': USER_ID}
        chunks = [
            {'id': 'indexed-actual', 'chunk_id': 99, 'chunk_sequence': 13, 'page_number': 3, 'chunk_text': 'Citable.'},
            {'chunk_id': 100, 'chunk_sequence': 14, 'page_number': 4, 'chunk_text': 'No indexed id.'},
            {'id': 'missing-location', 'chunk_text': 'No indexed location.'},
            {'id': 'sequence-location', 'chunk_sequence': 16, 'chunk_text': 'A real sequence.'},
            {'id': 'empty-text', 'page_number': 5, 'chunk_text': '  '},
            {'id': 'sheet-location', 'sheet_name': 'Rates', 'chunk_text': 'Sheet data.'},
        ]
        citations = runtime.producer._build_window_source_citations(source, {'chunks': chunks})
        rendered = runtime.producer._render_window_source_text({'chunks': chunks}, citations)
    assert [citation['citation_id'] for citation in citations] == ['indexed-actual', 'sequence-location', 'sheet-location']
    assert '[#99]' not in rendered
    assert '[#100]' not in rendered
    assert '[#missing-location]' not in rendered
    assert '[#empty-text]' not in rendered
    assert '(Source: source.txt, Page: 3) [#indexed-actual]' in rendered
    assert '[#sequence-location]' in rendered
    assert '(Source: source.txt, Sheet: Rates) [#sheet-location]' in rendered


def test_failed_summary_and_pairwise_targets_do_not_contribute_citations(monkeypatch):
    documents = make_documents(ids=('source', 'completed', 'pair-failed', 'summary-failed'))
    model = CitationModel(failed_windows={('summary-failed', 1)}, failed_targets={'pair-failed'})
    with comparison_runtime(documents, monkeypatch) as runtime:
        result = compare(runtime, documents, model)
    assert result['execution_status'] == 'partial'
    assert result['coverage']['target_statuses'] == {
        'completed': 'complete', 'pair-failed': 'failed', 'summary-failed': 'failed',
    }
    assert {citation['document_id'] for citation in result['citations']} == {'source', 'completed'}
    assert len(result['citations']) == 2
    assert len(result['comparison_items']) == 1
    assert Counter(call['stage'] for call in model.calls) == {'window_analysis': 5, 'comparison': 2}


def test_partial_target_retains_only_successful_window_citations(monkeypatch):
    documents = make_documents(ids=('source', 'partial-target'), pages=12)
    model = CitationModel(failed_windows={('partial-target', 1)})
    with comparison_runtime(documents, monkeypatch) as runtime:
        windows = runtime.search.build_document_chunk_windows(documents['partial-target']['chunks'])
        failed_chunk_ids = {chunk['id'] for chunk in windows[0]['chunks']}
        result = compare(runtime, documents, model)
    assert result['execution_status'] == 'partial'
    assert result['coverage']['target_statuses'] == {'partial-target': 'partial'}
    assert result['coverage']['partial_sources'] == ['partial-target']
    citation_ids = {citation['citation_id'] for citation in result['citations']}
    expected_ids = {
        chunk['id'] for fixture in documents.values() for chunk in fixture['chunks']
    } - failed_chunk_ids
    assert citation_ids == expected_ids
    assert all(citation['citation'] in result['analysis_reply'] for citation in result['citations'])
    pairwise_prompt = model.calls[-1]['prompt']
    assert model.calls[-1]['stage'] == 'comparison'
    assert all(f'[#{chunk_id}]' not in pairwise_prompt for chunk_id in failed_chunk_ids)


@pytest.mark.parametrize('source_failed', [False, True])
def test_no_completed_comparisons_return_no_citations(monkeypatch, source_failed):
    documents = make_documents()
    model = CitationModel(
        failed_windows={('source', 1)} if source_failed else (),
        failed_targets={'target-a', 'target-b'},
    )
    with comparison_runtime(documents, monkeypatch) as runtime:
        result = compare(runtime, documents, model)
    assert result['execution_status'] == 'failed'
    assert result['citations'] == []
    assert result['comparison_items'] == []
    if source_failed:
        assert len(model.calls) == 2
        assert all(call['metadata']['document_id'] == 'source' for call in model.calls)
        assert [document['status'] for document in result['coverage']['documents']] == [
            'failed', 'not_attempted', 'not_attempted',
        ]


def test_failed_consolidation_keeps_completed_pairwise_citations_without_retry_or_fallback(monkeypatch):
    documents = make_documents()
    model = CitationModel(fail_consolidation=True)
    with comparison_runtime(documents, monkeypatch) as runtime:
        result = compare(runtime, documents, model)
    assert result['execution_status'] == 'partial'
    assert result['analysis_reply'] is None
    assert result['report_status'] == 'unavailable'
    assert len(result['comparison_items']) == 2
    assert len(result['citations']) == 3
    assert len(model.calls) == 6
    assert sum(call['stage'] == 'comparison_reduction' for call in model.calls) == 1


@pytest.mark.parametrize('format_name,response', [
    ('JSON', '{"changes": ["Review required"]}'),
    ('XML', '<changes><change>Review required</change></changes>'),
])
def test_structured_comparisons_preserve_requested_output_without_prose_markers(monkeypatch, format_name, response):
    documents = make_documents(pages=12)
    model = CitationModel(response=response)
    with comparison_runtime(documents, monkeypatch) as runtime:
        result = compare(
            runtime, documents, model,
            comparison_prompt=f'Compare obligations. Return only valid {format_name}.',
        )
    assert result['analysis_reply'] == response
    assert len(result['citations']) == 36
    if format_name == 'JSON':
        parsed = json.loads(result['analysis_reply'])
        assert parsed == {'changes': ['Review required']}
    else:
        parsed = ElementTree.fromstring(result['analysis_reply'])
        assert parsed.tag == 'changes'
    assert all('copy the supporting standard citation markers' not in call['prompt'] for call in model.calls)
    assert all('Do not add prose citation markers' in call['prompt'] for call in model.calls)


def test_missing_model_citations_do_not_trigger_extra_calls_or_automatic_appendices(monkeypatch):
    documents = make_documents(ids=('source', 'target-a'))
    model = CitationModel(response='Only the requested comparison.')
    with comparison_runtime(documents, monkeypatch) as runtime:
        result = compare(runtime, documents, model)
    assert result['analysis_reply'] == 'Only the requested comparison.'
    assert len(result['citations']) == 2
    assert len(model.calls) == 3


@pytest.mark.parametrize('cancel_stage', ['window_analysis', 'reduction', 'comparison', 'comparison_reduction'])
def test_cancellation_is_not_converted_to_a_cited_partial_response(monkeypatch, cancel_stage):
    documents = make_documents(pages=12)
    model = CitationModel()
    cancelled = False
    original_invoke = model.invoke

    def invoke(prompt, stage=None, metadata=None):
        nonlocal cancelled
        result = original_invoke(prompt, stage=stage, metadata=metadata)
        if stage == cancel_stage:
            cancelled = True
        return result

    model.invoke = invoke
    with comparison_runtime(documents, monkeypatch) as runtime:
        with pytest.raises(runtime.cancellation.MixedSourceCancellationError):
            compare(runtime, documents, model, cancel_requested=lambda: cancelled)
    assert model.calls[-1]['stage'] == cancel_stage
