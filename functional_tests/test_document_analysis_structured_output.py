# test_document_analysis_structured_output.py
"""
Functional test for analysis structured output preservation.
Version: 0.241.023
Implemented in: 0.241.117

This test ensures document analysis preserves one structured JSON
result per analyzed document instead of making a lossy global reduction call
that can collapse a large per-comment analysis into only a few final objects.
"""

import ast
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'functions_document_analysis.py',
)
CONFIG_PATH = os.path.join(REPO_ROOT, 'application', 'single_app', 'config.py')


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


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
        'json': json,
        'logging': logging,
        're': re,
    }
    if extra_globals:
        namespace.update(extra_globals)

    exec(compile(compiled_module, file_path, 'exec'), namespace)
    return namespace


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


def read_config_version():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as handle:
        for line in handle:
            if line.strip().startswith('VERSION = '):
                return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


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
            window_number = (metadata.get('window_range') or {}).get('window_number')
            responses = {
                ('doc-1', 1): """```json
[
  {
    "comment_id": "doc-1.json",
    "classification": "substantive",
    "themes": ["public_interest"],
    "attachment_priority_review": false,
    "response_treatment": "individual response",
    "campaign_candidate": false,
    "campaign_signals": [],
    "substantive_score": {
      "total": 2,
      "used_values": ["concrete_recommendation", "economic_or_policy_reasoning"]
    },
    "confidence": 0.94,
    "reason": "Single-window comment preserved from document one."
  }
]
```""",
                ('doc-2', 1): """```json
[
  {
    "comment_id": "doc-2.json",
    "classification": "non_substantive",
    "themes": ["other"],
    "attachment_priority_review": false,
    "response_treatment": "no action needed",
    "campaign_candidate": false,
    "campaign_signals": [],
    "substantive_score": {
      "total": 0,
      "used_values": []
    },
    "confidence": 0.88,
    "reason": "Single-window comment preserved from document two."
  }
]
```""",
                ('doc-3', 1): """```json
[
  {
    "comment_id": "doc-3.json",
    "classification": "substantive",
    "themes": ["market_surveillance"],
    "attachment_priority_review": false,
    "response_treatment": "individual response",
    "campaign_candidate": false,
    "campaign_signals": [],
    "substantive_score": {
      "total": 2,
      "used_values": ["legal_or_regulatory_analysis", "technical_or_operational_detail"]
    },
    "confidence": 0.9,
    "reason": "First half of the multi-window document."
  }
]
```""",
                ('doc-3', 2): """```json
[
  {
    "comment_id": "doc-3.json",
    "classification": "substantive",
    "themes": ["consumer_protection"],
    "attachment_priority_review": false,
    "response_treatment": "individual response",
    "campaign_candidate": false,
    "campaign_signals": [],
    "substantive_score": {
      "total": 1,
      "used_values": ["evidence_examples_or_data"]
    },
    "confidence": 0.9,
    "reason": "Second half of the multi-window document."
  }
]
```""",
            }
            return responses[(document_id, window_number)]

        if stage == 'reduction' and metadata.get('reduction_scope') == 'document':
            document_name = metadata.get('document_name')
            responses = {
                'doc-3.json': """```json
[
  {
    "comment_id": "doc-3.json",
    "classification": "substantive",
    "themes": ["market_surveillance", "consumer_protection"],
    "attachment_priority_review": false,
    "response_treatment": "individual response",
    "campaign_candidate": false,
    "campaign_signals": [],
    "substantive_score": {
      "total": 3,
      "used_values": [
        "legal_or_regulatory_analysis",
        "technical_or_operational_detail",
        "evidence_examples_or_data"
      ]
    },
    "confidence": 0.96,
    "reason": "Merged document-level result that preserves both windows."
  }
]
```""",
            }
            return responses[document_name]

        if stage == 'reduction' and metadata.get('reduction_scope') == 'global':
            raise AssertionError('Global reduction should be skipped for structured JSON output requests.')

        raise AssertionError(f'Unexpected invoke_prompt call: stage={stage!r}, metadata={metadata!r}')


def test_structured_analyze_skips_lossy_global_reduction():
    print('Testing structured analysis preservation...')

    document_windows = {
        'doc-1': [build_window(1, 1, 1, 'Doc 1 window 1')],
        'doc-2': [build_window(1, 1, 1, 'Doc 2 window 1')],
        'doc-3': [
            build_window(1, 1, 1, 'Doc 3 window 1'),
            build_window(2, 2, 2, 'Doc 3 window 2'),
        ],
    }
    document_metadata = {
        'doc-1': {'id': 'doc-1', 'file_name': 'doc-1.json', 'title': 'Document 1'},
        'doc-2': {'id': 'doc-2', 'file_name': 'doc-2.json', 'title': 'Document 2'},
        'doc-3': {'id': 'doc-3', 'file_name': 'doc-3.json', 'title': 'Document 3'},
    }

    def build_document_chunk_windows(chunks, **_kwargs):
        return list(chunks)

    def get_document_chunks_payload(document_id, **_kwargs):
        windows = document_windows[document_id]
        return {
            'document': document_metadata[document_id],
            'scope': 'group',
            'scope_id': 'scope-1',
            'chunks': windows,
            'chunk_count': sum(window.get('chunk_count', 0) for window in windows),
        }

    namespace = load_module_functions(
        MODULE_PATH,
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
    analysis_prompt = (
        'Treat each standalone document as one comment. '
        'Return one JSON array containing one object per comment. '
        'Each object must contain exactly these fields: comment_id, classification, themes, '
        'attachment_priority_review, response_treatment, campaign_candidate, campaign_signals, '
        'substantive_score, confidence, and reason. Return only valid JSON in a code block.'
    )

    result = namespace['run_document_analysis'](
        user_id='user-1',
        analysis_prompt=analysis_prompt,
        document_ids=['doc-1', 'doc-2', 'doc-3'],
        invoke_prompt=invoke_prompt,
        include_coverage_summary=False,
        max_documents=10,
    )

    parsed_output = json.loads(namespace['_clean_json_code_fence'](result['analysis_reply']))
    assert_equal(len(parsed_output), 3, 'structured analysis result count')
    assert_equal(
        [entry.get('comment_id') for entry in parsed_output],
        ['doc-1.json', 'doc-2.json', 'doc-3.json'],
        'structured analysis comment ordering',
    )

    document_reduction_calls = [
        call for call in invoke_prompt.calls
        if call['stage'] == 'reduction' and call['metadata'].get('reduction_scope') == 'document'
    ]
    global_reduction_calls = [
        call for call in invoke_prompt.calls
        if call['stage'] == 'reduction' and call['metadata'].get('reduction_scope') == 'global'
    ]
    assert_equal(len(document_reduction_calls), 1, 'document reduction call count')
    assert_equal(len(global_reduction_calls), 0, 'global reduction call count')
    assert_equal(result['coverage']['document_count'], 3, 'coverage document count')
    assert_equal(result['coverage']['processed_windows'], 4, 'coverage processed windows')
    print('Structured analysis preservation passed.')
    return True


def test_version_alignment():
    print('Testing version alignment...')
    assert_equal(read_config_version(), '0.241.023', 'config version')
    print('Version alignment passed.')
    return True


def run_tests():
    print('Running analysis structured output tests...')
    print('=' * 72)

    tests = [
        test_structured_analyze_skips_lossy_global_reduction,
        test_version_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n{test.__name__}:')
        try:
            results.append(test())
        except Exception as exc:
            print(f'FAILED: {exc}')
            results.append(False)

    passed = sum(bool(result) for result in results)
    print(f'\nResults: {passed}/{len(results)} tests passed')
    return passed == len(results)


if __name__ == '__main__':
    raise SystemExit(0 if run_tests() else 1)