# test_fact_memory_history_context_leak_fix.py
#!/usr/bin/env python3
"""
Functional test for fact-memory history context leak fix.
Version: 0.241.128
Implemented in: 0.241.128

This test ensures saved instruction/fact memory citations stay available as
citations without being replayed as prior tool-result text in follow-up model
history.
"""

import ast
import copy
import json
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.128',
    'FACT_MEMORY_HISTORY_CONTEXT_LEAK_FIX.md',
)
TARGET_FUNCTIONS = {
    '_truncate_history_citation_text',
    '_serialize_history_citation_value',
    '_build_agent_citation_history_lines',
    '_build_document_citation_history_lines',
    '_build_web_citation_history_lines',
    'build_assistant_history_content_with_citations',
}


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_history_helpers():
    route_source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(route_source, filename=ROUTE_FILE)
    selected_nodes = [
        copy.deepcopy(node)
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]
    found_function_names = {node.name for node in selected_nodes}
    assert found_function_names == TARGET_FUNCTIONS, (
        f'Expected helpers {sorted(TARGET_FUNCTIONS)}, '
        f'found {sorted(found_function_names)}'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {'json': json}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace


def build_instruction_memory_citation():
    return {
        'tool_name': 'Instruction Memory',
        'function_name': 'apply_instructions',
        'plugin_name': 'fact_memory',
        'function_arguments': {
            'memory_type': 'instruction',
            'applied_count': 1,
        },
        'function_result': {
            'facts': [{
                'id': 'instruction-1',
                'value': 'Write in a warm, confident, helpful style.',
                'memory_type': 'instruction',
            }],
        },
        'success': True,
    }


def build_fact_memory_recall_citation():
    return {
        'tool_name': 'Fact Memory Recall',
        'function_name': 'search_facts',
        'plugin_name': 'fact_memory',
        'function_arguments': {
            'query': 'who am i?',
            'search_mode': 'embedding',
            'memory_type': 'fact',
        },
        'function_result': {
            'facts': [{
                'id': 'fact-1',
                'value': "Paul's title is Principal Cloud Solution Architect.",
                'memory_type': 'fact',
            }],
        },
        'success': True,
    }


def build_tabular_citation():
    return {
        'tool_name': 'TabularProcessingPlugin.get_distinct_values [Legal]',
        'function_name': 'get_distinct_values',
        'plugin_name': 'TabularProcessingPlugin',
        'function_arguments': {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'sheet_name': 'Legal',
            'column': 'Location',
        },
        'function_result': {
            'filename': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'selected_sheet': 'Legal',
            'column': 'Location',
            'distinct_count': 2,
            'returned_values': 2,
            'values': [
                'https://sharepoint.example/sites/legal-a',
                'https://sharepoint.example/sites/legal-b',
            ],
        },
        'success': True,
    }


def test_fact_memory_citations_are_excluded_from_history_text():
    """Verify fact-memory-only citations do not create prior tool-result history text."""
    print('Testing fact-memory citations are excluded from assistant history text...')

    namespace = load_history_helpers()
    build_content = namespace['build_assistant_history_content_with_citations']
    base_content = 'Given the team capacity constraints, set up a call to discuss options.'

    rendered_history_content = build_content(
        {
            'agent_citations': [
                build_instruction_memory_citation(),
                build_fact_memory_recall_citation(),
            ],
            'hybrid_citations': [],
            'web_search_citations': [],
        },
        base_content,
    )

    assert rendered_history_content == base_content
    assert 'Prior tool results' not in rendered_history_content
    assert 'Instruction Memory' not in rendered_history_content
    assert 'Fact Memory Recall' not in rendered_history_content

    print('Fact-memory citations are excluded from assistant history text')
    return True


def test_tabular_history_grounding_still_survives_fact_memory_filtering():
    """Verify useful tabular citations still support follow-up grounding."""
    print('Testing tabular citations survive fact-memory filtering...')

    namespace = load_history_helpers()
    build_content = namespace['build_assistant_history_content_with_citations']

    rendered_history_content = build_content(
        {
            'agent_citations': [
                build_instruction_memory_citation(),
                build_fact_memory_recall_citation(),
                build_tabular_citation(),
            ],
            'hybrid_citations': [],
            'web_search_citations': [],
        },
        'There are 2 distinct Legal locations.',
    )

    assert 'Supporting citation context from this assistant turn' in rendered_history_content
    assert 'Internal grounding context only.' in rendered_history_content
    assert 'Prior tool results:' in rendered_history_content
    assert 'TabularProcessingPlugin.get_distinct_values [Legal]' in rendered_history_content
    assert 'https://sharepoint.example/sites/legal-a' in rendered_history_content
    assert 'Instruction Memory' not in rendered_history_content
    assert 'Fact Memory Recall' not in rendered_history_content
    assert 'warm, confident, helpful style' not in rendered_history_content
    assert "Paul's title" not in rendered_history_content

    print('Tabular citations survive fact-memory filtering')
    return True


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert read_config_version() == '0.241.128'
    assert 'Fixed/Implemented in version: **0.241.128**' in fix_doc_content
    assert 'fact-memory citations' in fix_doc_content.lower()
    assert 'Prior tool results' in fix_doc_content
    assert 'application/single_app/route_backend_chats.py' in fix_doc_content

    print('Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_fact_memory_citations_are_excluded_from_history_text,
        test_tabular_history_grounding_still_survives_fact_memory_filtering,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
