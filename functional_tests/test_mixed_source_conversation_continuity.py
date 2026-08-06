#!/usr/bin/env python3
# test_mixed_source_conversation_continuity.py
"""
Functional test for Phase 5 mixed-source conversation continuity.
Version: 0.250.107
Implemented in: 0.250.068; updated in 0.250.107

This test ensures #1060 preserves compact source continuity only as a
reauthorization hint for #1055 and prerequisite phases #1056, #1057, #1058,
and #1059. It verifies explicit selections, source-version changes, failed
coverage, and privacy bounds without persisting source content or locators.
"""

import ast
import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
METADATA_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'functions_conversation_metadata.py')
SETTINGS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'functions_settings.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')


def _read_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def _load_route_helpers():
    source = _read_file(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    target_names = {
        '_build_mixed_source_continuity_refs',
        '_build_reauthorized_continuity_decision',
    }
    nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    ]
    assert len(nodes) == len(target_names)
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), ROUTE_FILE, 'exec'), namespace)
    return namespace


def test_compact_continuity_preserves_terminal_contract_only():
    """Persist source identity, order, engine, coverage, and references without content."""
    print('Testing compact continuity metadata...')
    helpers = _load_route_helpers()
    build_refs = helpers['_build_mixed_source_continuity_refs']
    refs = build_refs(
        [{
            'document_id': 'table-1', 'scope': 'group', 'scope_id': 'group-1',
            'source_kind': 'tabular', 'source_version': 'v1',
            'authorization_status': 'authorized', 'source_role': 'target',
            'storage_locator': {'blob_path': 'never-persisted'},
        }],
        [{
            'document_id': 'table-1', 'engine': 'tabular', 'status': 'failed',
            'coverage': {'partial_coverage': True, 'raw_content': 'never-persisted'},
            'citations': [{'id': 'citation-1'}], 'generated_artifacts': [{'id': 'artifact-1'}],
        }],
        'history',
    )
    assert refs == [{
        'document_id': 'table-1', 'scope': 'group', 'scope_id': 'group-1',
        'source_role': 'target', 'requested_order': 0, 'source_kind': 'tabular',
        'engine': 'tabular', 'source_version': 'v1', 'status': 'failed',
        'coverage': {'partial_coverage': True, 'evidence_envelope_truncated': False, 'failed': True},
        'selection_origin': 'history', 'action_mode': 'chat',
        'citation_count': 1, 'artifact_count': 1, 'group_id': 'group-1',
    }]
    serialized = repr(refs)
    for prohibited_value in ('never-persisted', 'storage_locator', 'raw_content', 'blob_path'):
        assert prohibited_value not in serialized
    print('PASS: compact continuity metadata')


def test_explicit_selection_overrides_and_history_requires_reauthorization():
    """A current selection wins; stale, revoked, and changed history requires new execution."""
    print('Testing selection precedence and reauthorization...')
    decide = _load_route_helpers()['_build_reauthorized_continuity_decision']
    prior_refs = [
        {'document_id': 'narrative-1', 'source_version': 'v1'},
        {'document_id': 'table-1', 'source_version': 'v1'},
    ]
    explicit = decide(prior_refs, [], explicit_selection=True)
    assert explicit['selection_origin'] == 'selected'
    assert explicit['prior_source_count'] == 0

    history = decide(prior_refs, [
        {'document_id': 'narrative-1', 'source_version': 'v1', 'authorization_status': 'authorized'},
        {'document_id': 'table-1', 'source_version': 'v2', 'authorization_status': 'authorized'},
        {'document_id': 'revoked-upload', 'source_version': 'v1', 'authorization_status': 'unresolved'},
    ], explicit_selection=False)
    assert history['selection_origin'] == 'history'
    assert history['reauthorized_source_count'] == 2
    assert history['source_version_changed_count'] == 1
    assert history['requires_native_execution'] is True
    assert history['unavailable_source_count'] == 0
    print('PASS: selection precedence and reauthorization')


def test_flag_and_standard_streaming_wiring_are_present():
    """Both Chat paths retain flag-off rollback and only use fresh manifest results."""
    print('Testing flag and Chat parity wiring...')
    settings_source = _read_file(SETTINGS_FILE)
    route_source = _read_file(ROUTE_FILE)
    metadata_source = _read_file(METADATA_FILE)
    config_source = _read_file(CONFIG_FILE)
    assert "'enable_mixed_source_conversation_continuity': False" in settings_source
    assert 'def is_mixed_source_conversation_continuity_enabled(settings):' in settings_source
    assert route_source.count('is_mixed_source_conversation_continuity_enabled(settings)') == 5
    assert route_source.count('_build_reauthorized_continuity_decision(') == 4
    assert route_source.count('_build_mixed_source_continuity_refs(') == 3
    assert route_source.count("selection_mode='history'") == 0
    assert route_source.count("'history',") >= 2
    assert 'source_continuity_refs=None' in metadata_source
    assert 'source_continuity_refs=source_continuity_refs' in metadata_source
    assert 'VERSION = "0.250.107"' in config_source
    print('PASS: flag and Chat parity wiring')


if __name__ == '__main__':
    tests = [
        test_compact_continuity_preserves_terminal_contract_only,
        test_explicit_selection_overrides_and_history_requires_reauthorization,
        test_flag_and_standard_streaming_wiring_are_present,
    ]
    for test in tests:
        test()
    print(f'Completed {len(tests)}/{len(tests)} Phase 5 continuity checks.')