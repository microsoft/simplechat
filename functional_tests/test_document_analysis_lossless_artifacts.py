#!/usr/bin/env python3
# test_document_analysis_lossless_artifacts.py
"""
Functional test for document analysis lossless artifacts.
Version: 0.241.197
Implemented in: 0.241.040
Updated in: 0.241.065
Updated in: 0.241.197

This test ensures exhaustive/table-style document analysis preserves raw window
outputs and can build both structured CSV rows and Markdown raw-note artifacts
instead of relying only on the reduced final answer. It also ensures primary
tabular generated exports suppress redundant analysis JSON/Markdown cards, and
that JSON artifacts are only created when the prompt explicitly requests JSON.
"""

import ast
import csv
import io
import json
import logging
import os
import re
import traceback
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_MODULE_PATH = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'functions_document_analysis.py',
)
WORKFLOW_RUNNER_PATH = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'functions_workflow_runner.py',
)
CONFIG_PATH = os.path.join(REPO_ROOT, 'application', 'single_app', 'config.py')


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def assert_contains(haystack, needle, label):
    if needle not in haystack:
        raise AssertionError(f'{label}: expected to find {needle!r}')


def load_module_functions(file_path, extra_globals=None):
    with open(file_path, 'r', encoding='utf-8') as handle:
        source = handle.read()

    module_ast = ast.parse(source, filename=file_path)
    selected_nodes = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef)
    ]
    compiled_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(compiled_module)

    namespace = {
        '__builtins__': __builtins__,
        'Any': Any,
        'Callable': Callable,
        'Dict': Dict,
        'List': List,
        'Optional': Optional,
        'contextmanager': contextmanager,
        'csv': csv,
        'io': io,
        'json': json,
        'logging': logging,
        'os': os,
        're': re,
    }
    if extra_globals:
        namespace.update(extra_globals)

    exec(compile(compiled_module, file_path, 'exec'), namespace)
    return namespace


def read_config_version():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as handle:
        for line in handle:
            if line.strip().startswith('VERSION = '):
                return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def build_window(window_number, page_number, chunk_sequence, text):
    return {
        'window_number': window_number,
        'window_unit': 'pages',
        'start_page': page_number,
        'end_page': page_number,
        'start_chunk_sequence': chunk_sequence,
        'end_chunk_sequence': chunk_sequence,
        'page_count': 1,
        'chunk_count': 1,
        'chunks': [
            {
                'chunk_text': text,
                'page_number': page_number,
                'chunk_sequence': chunk_sequence,
            }
        ],
    }


class FakeInvokePrompt:
    def __init__(self):
        self.calls = []

    def __call__(self, prompt_text, stage='window_analysis', metadata=None):
        metadata = metadata or {}
        self.calls.append({
            'stage': stage,
            'metadata': metadata,
            'prompt_text': prompt_text,
        })

        if stage == 'window_analysis':
            document_id = metadata.get('document_id')
            if document_id == 'doc-1':
                return (
                    '| Entity / Vendor | Service being performed or used | Amount |\n'
                    '|---|---|---:|\n'
                    '| Netflix | Enterprise subscription renewal | $385,668 |'
                )
            if document_id == 'doc-2':
                return (
                    '| Entity / Vendor | Service being performed or used | Amount |\n'
                    '|---|---|---:|\n'
                    '| Workday | ERP integration advisory | $2,626,000 |'
                )

        if stage == 'reduction' and metadata.get('reduction_scope') == 'global':
            return 'Consolidated summary: Netflix appears in licensing renewal work.'

        raise AssertionError(f'Unexpected invoke_prompt call: stage={stage!r}, metadata={metadata!r}')


def build_analysis_result():
    document_windows = {
        'doc-1': [build_window(1, 1, 1, 'Netflix billing schedule')],
        'doc-2': [build_window(1, 1, 1, 'Workday implementation work order')],
    }
    document_metadata = {
        'doc-1': {'id': 'doc-1', 'file_name': 'netflix.csv', 'title': 'Netflix Billing'},
        'doc-2': {'id': 'doc-2', 'file_name': 'workday.docx', 'title': 'Workday Work Order'},
    }

    def build_document_chunk_windows(chunks, **_kwargs):
        return list(chunks)

    def get_document_chunks_payload(document_id, **_kwargs):
        windows = document_windows[document_id]
        return {
            'document': document_metadata[document_id],
            'scope': 'personal',
            'scope_id': None,
            'chunks': windows,
            'chunk_count': len(windows),
        }

    namespace = load_module_functions(
        ANALYSIS_MODULE_PATH,
        extra_globals={
            'DEFAULT_WINDOW_UNIT': 'pages',
            'DEFAULT_MAX_RETRIES_PER_WINDOW': 1,
            'DEFAULT_REDUCTION_BATCH_SIZE': 5,
            'DEFAULT_MAX_REDUCTION_ROUNDS': 4,
            'CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS': 3,
            'WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS': 10,
            'log_event': lambda *args, **kwargs: None,
            'debug_print': lambda *args, **kwargs: None,
            'normalize_search_id_list': lambda value: list(value or []),
            'normalize_search_scope': lambda value: str(value or 'all').strip() or 'all',
        },
    )
    namespace['_get_search_service_helpers'] = lambda: (
        build_document_chunk_windows,
        get_document_chunks_payload,
    )

    invoke_prompt = FakeInvokePrompt()
    result = namespace['run_document_analysis'](
        user_id='user-1',
        analysis_prompt='Develop a table to list out all vendors/entities and service being performed or used.',
        document_ids=['doc-1', 'doc-2'],
        invoke_prompt=invoke_prompt,
        include_coverage_summary=False,
        max_documents=10,
    )
    return result, invoke_prompt


def test_analysis_preserves_raw_outputs():
    print('Testing raw output preservation for exhaustive table analysis...')
    result, invoke_prompt = build_analysis_result()

    assert_equal(result['analysis_intent']['exhaustive'], True, 'analysis intent exhaustive')
    assert_equal(result['analysis_intent']['table_output_requested'], True, 'analysis intent table output')
    assert_equal(len(result['raw_analysis_items']), 2, 'raw analysis item count')
    assert_equal(len(result['document_analysis_items']), 2, 'document analysis item count')
    assert_contains(result['raw_analysis_items'][0]['text'], 'Netflix', 'first raw item')
    assert_contains(result['raw_analysis_items'][1]['text'], 'Workday', 'second raw item')

    global_reduction_calls = [
        call for call in invoke_prompt.calls
        if call['stage'] == 'reduction' and call['metadata'].get('reduction_scope') == 'global'
    ]
    assert_equal(len(global_reduction_calls), 1, 'global reduction still produces analysis summary')
    assert_contains(result['analysis_reply'], 'Netflix', 'reduced final summary')
    print('Raw output preservation verified.')


def test_lossless_artifact_helpers_build_csv_and_markdown():
    print('Testing CSV and Markdown artifact helper output...')
    result, _invoke_prompt = build_analysis_result()

    namespace = load_module_functions(
        WORKFLOW_RUNNER_PATH,
        extra_globals={
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT': 3,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ROW_COUNT': 5,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_COUNT': 5,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_LENGTH': 220,
            'debug_print': lambda *args, **kwargs: None,
            'upload_generated_analysis_artifact_for_current_user': lambda *args, **kwargs: None,
        },
    )

    intent = namespace['_get_document_analysis_artifact_intent'](
        result,
        'Develop a table to list out all vendors/entities and service being performed or used.',
    )
    assert_equal(intent['csv_artifact_recommended'], True, 'CSV artifact intent')
    assert_equal(intent['markdown_analysis_artifact_recommended'], True, 'Markdown artifact intent')

    rows = namespace['_build_document_analysis_structured_rows'](result)
    assert_equal(len(rows), 2, 'structured row count')
    assert_equal(rows[0]['Entity / Vendor'], 'Netflix', 'first CSV row entity')
    assert_equal(rows[1]['Entity / Vendor'], 'Workday', 'second CSV row entity')
    assert_equal(rows[0]['source_document'], 'netflix.csv', 'first CSV row source document')

    csv_output = namespace['_build_document_analysis_rows_csv'](rows)
    assert_contains(csv_output, 'Entity / Vendor', 'CSV header')
    assert_contains(csv_output, 'Netflix', 'CSV Netflix row')
    assert_contains(csv_output, 'Workday', 'CSV Workday row')
    assert_contains(csv_output, 'source_document', 'CSV source metadata')

    markdown_output = namespace['_build_document_analysis_markdown_artifact'](result)
    assert_contains(markdown_output, '## Final Analysis', 'Markdown final analysis section')
    assert_contains(markdown_output, '## Raw Window-Level Analysis Notes', 'Markdown raw notes section')
    assert_contains(markdown_output, 'Netflix Billing', 'Markdown first raw source')
    assert_contains(markdown_output, 'Workday Work Order', 'Markdown second raw source')

    assistant_reply = namespace['_build_document_analysis_multi_artifact_reply'](
        2,
        [{'output_format': 'csv'}, {'output_format': 'md'}],
        len(rows),
        len(result['raw_analysis_items']),
        result['analysis_reply'],
    )
    assert_contains(assistant_reply, '2 row(s)', 'assistant reply row count')
    assert_contains(assistant_reply, '2 raw analysis note(s)', 'assistant reply raw note count')
    print('Lossless artifact helper output verified.')


def test_primary_tabular_output_demotes_secondary_artifacts():
    print('Testing primary generated tabular output artifact presentation...')
    uploaded_artifacts = []

    def fake_upload_generated_artifact(**kwargs):
        uploaded_artifacts.append(kwargs)
        return {
            'message': {
                'id': f'artifact-{len(uploaded_artifacts)}',
                'file_name': kwargs.get('file_name'),
            }
        }

    namespace = load_module_functions(
        WORKFLOW_RUNNER_PATH,
        extra_globals={
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT': 3,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ROW_COUNT': 5,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_COUNT': 5,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_LENGTH': 220,
            'debug_print': lambda *args, **kwargs: None,
            'has_request_context': lambda: True,
            'upload_generated_analysis_artifact_for_current_user': fake_upload_generated_artifact,
        },
    )

    analysis_result = {
        'analysis_reply': json.dumps([
            {'comment_id': 'CFTC-001', 'requested_output': 'First generated object'},
            {'comment_id': 'CFTC-002', 'requested_output': 'Second generated object'},
        ]),
        'analysis_intent': {
            'exhaustive': True,
            'table_output_requested': True,
            'csv_artifact_recommended': True,
            'markdown_analysis_artifact_recommended': True,
        },
        'documents': [
            {
                'file_name': 'cftc-comment-submissions-workbook-analysis.json',
                'title': 'cftc-comment-submissions-workbook-analysis.json',
            }
        ],
        'raw_analysis_items': [
            {
                'file_name': 'cftc-comment-submissions-workbook-analysis.json',
                'text': (
                    '| comment_id | requested_output |\n'
                    '|---|---|\n'
                    '| CFTC-001 | First generated object |\n'
                    '| CFTC-002 | Second generated object |'
                ),
            }
        ],
    }
    primary_generated_outputs = [
        {
            'capability': 'tabular',
            'background_export': True,
            'export_run_id': 'run-123',
            'output_format': 'json',
            'row_count': 3539,
            'batch_count': 501,
        }
    ]

    artifact_payload = namespace['_maybe_create_document_analysis_generated_artifacts'](
        analysis_result,
        'Create a generated JSON export with one object per comment.',
        conversation_id='conversation-1',
        primary_generated_outputs=primary_generated_outputs,
    )

    artifacts = artifact_payload.get('artifacts') or []
    artifact_formats = [artifact.get('output_format') for artifact in artifacts]
    assert_equal(artifact_formats, ['csv'], 'only supporting CSV artifact remains')
    assert_equal(len(uploaded_artifacts), 1, 'uploaded artifact count')
    assert_equal(
        uploaded_artifacts[0]['file_name'],
        'cftc-comment-submissions-workbook-analysis.csv',
        'supporting CSV artifact filename',
    )

    assistant_reply = artifact_payload.get('assistant_reply') or ''
    assert_contains(assistant_reply, 'full generated JSON export is queued in the background', 'primary export reply')
    assert_contains(assistant_reply, 'supporting CSV analysis preview', 'supporting CSV reply')
    if 'Preview:' in assistant_reply:
        raise AssertionError('assistant reply should rely on artifact card previews instead of inlining a duplicate preview')
    if 'Markdown' in assistant_reply or 'raw analysis note(s) were retained' in assistant_reply:
        raise AssertionError('assistant reply should not promote secondary Markdown/raw-note artifacts when a primary export exists')

    print('Primary generated tabular output artifact presentation verified.')


def test_json_artifact_requires_explicit_json_request():
    print('Testing JSON artifact opt-in behavior for document analysis...')
    uploaded_artifacts = []

    def fake_upload_generated_artifact(**kwargs):
        uploaded_artifacts.append(kwargs)
        return {
            'message': {
                'id': f'artifact-{len(uploaded_artifacts)}',
                'file_name': kwargs.get('file_name'),
            }
        }

    namespace = load_module_functions(
        WORKFLOW_RUNNER_PATH,
        extra_globals={
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT': 3,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ROW_COUNT': 5,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_COUNT': 5,
            'DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_LENGTH': 220,
            'debug_print': lambda *args, **kwargs: None,
            'has_request_context': lambda: True,
            'upload_generated_analysis_artifact_for_current_user': fake_upload_generated_artifact,
        },
    )

    analysis_result = {
        'analysis_reply': json.dumps([
            {
                'situation': 'SWA881 and JZA610 are converging with 973 ft vertical separation.',
                'recommended_action': 'Issue immediate traffic and safety instructions based on the controlling rules.',
            }
        ]),
        'documents': [
            {
                'file_name': '14-cfr-part-91-general-operating-and-flight-rules.pdf',
                'title': '14 CFR Part 91 General Operating and Flight Rules',
            }
        ],
    }

    artifact_payload = namespace['_maybe_create_document_analysis_generated_artifacts'](
        analysis_result,
        'How do we handle a situation like this?',
        conversation_id='conversation-1',
    )

    assert_equal(len(uploaded_artifacts), 1, 'implicit JSON-shaped upload count')
    assert_equal(uploaded_artifacts[0]['output_format'], 'md', 'implicit JSON-shaped artifact format')
    assert_equal(
        uploaded_artifacts[0]['file_name'],
        '14-cfr-part-91-general-operating-and-flight-rules-analysis.md',
        'implicit JSON-shaped artifact filename',
    )
    assistant_reply = artifact_payload.get('assistant_reply') or ''
    assert_contains(assistant_reply, 'downloadable MD artifact', 'implicit JSON-shaped assistant reply')
    if 'downloadable JSON artifact' in assistant_reply:
        raise AssertionError('Implicit JSON-shaped analysis should not promote a JSON artifact')

    uploaded_artifacts.clear()
    explicit_artifact_payload = namespace['_maybe_create_document_analysis_generated_artifacts'](
        analysis_result,
        'Please create a JSON file for this answer.',
        conversation_id='conversation-1',
    )

    assert_equal(len(uploaded_artifacts), 1, 'explicit JSON upload count')
    assert_equal(uploaded_artifacts[0]['output_format'], 'json', 'explicit JSON artifact format')
    assert_equal(
        uploaded_artifacts[0]['file_name'],
        '14-cfr-part-91-general-operating-and-flight-rules-analysis.json',
        'explicit JSON artifact filename',
    )
    explicit_assistant_reply = explicit_artifact_payload.get('assistant_reply') or ''
    assert_contains(explicit_assistant_reply, 'downloadable JSON artifact', 'explicit JSON assistant reply')
    print('JSON artifact opt-in behavior verified.')


def test_version_alignment():
    print('Testing version alignment...')
    assert_equal(read_config_version(), '0.241.197', 'config version')
    print('Version alignment verified.')


def run_tests():
    tests = [
        test_analysis_preserves_raw_outputs,
        test_lossless_artifact_helpers_build_csv_and_markdown,
        test_primary_tabular_output_demotes_secondary_artifacts,
        test_json_artifact_requires_explicit_json_request,
        test_version_alignment,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    return success


if __name__ == '__main__':
    raise SystemExit(0 if run_tests() else 1)
