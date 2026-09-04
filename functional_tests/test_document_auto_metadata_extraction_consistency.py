#!/usr/bin/env python3
# test_document_auto_metadata_extraction_consistency.py
"""
Functional test for document auto metadata extraction consistency.
Version: 0.241.111
Implemented in: 0.241.110

This test ensures upload processing runs final metadata extraction consistently
for all supported file types and preserves public workspace scope for media files.
"""

import ast
import os
import re
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
FUNCTIONS_DOCUMENTS_FILE = os.path.join(SINGLE_APP_ROOT, 'functions_documents.py')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def parse_functions_documents():
    source = read_file(FUNCTIONS_DOCUMENTS_FILE)
    return ast.parse(source, filename=FUNCTIONS_DOCUMENTS_FILE), source


def get_function(module_ast, function_name):
    functions = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert functions, f'Missing function: {function_name}'
    return functions[-1]


def call_name(call_node):
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    if isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return None


def has_keyword(call_node, keyword_name, expected_value=None):
    for keyword in call_node.keywords:
        if keyword.arg != keyword_name:
            continue
        if expected_value is None:
            return True
        if isinstance(keyword.value, ast.Constant):
            return keyword.value.value == expected_value
        return False
    return False


def test_dispatcher_owns_final_metadata_extraction():
    """Verify the upload dispatcher runs one final metadata pass for every processor."""
    print('Testing centralized upload metadata extraction...')

    module_ast, source = parse_functions_documents()
    dispatcher = get_function(module_ast, 'process_document_upload_background')
    dispatcher_calls = [node for node in ast.walk(dispatcher) if isinstance(node, ast.Call)]
    dispatcher_call_names = [call_name(call) for call in dispatcher_calls]

    assert '_run_final_metadata_extraction' in dispatcher_call_names, (
        'Upload dispatcher must run final metadata extraction after file processing'
    )
    assert '_resolve_processing_complete_status' in dispatcher_call_names, (
        'Upload dispatcher must resolve final status from metadata extraction result'
    )

    processors_with_legacy_auto_extract = {
        'process_html',
        'process_md',
        'process_json',
        'process_tabular',
        'process_visio',
        'process_di_document',
        'process_video_document',
        'process_audio_document',
    }
    for processor_name in processors_with_legacy_auto_extract:
        processor_calls = [
            call for call in dispatcher_calls
            if call_name(call) == processor_name
        ]
        assert processor_calls, f'Dispatcher should call {processor_name}'
        assert any(
            has_keyword(call, 'auto_extract_metadata', False)
            or 'processor_args_without_auto_metadata' in ast.unparse(call)
            for call in processor_calls
        ), f'Dispatcher should suppress processor-local extraction for {processor_name}'

    required_extensions = [
        "file_ext == '.txt'",
        "file_ext == '.xml'",
        "file_ext in ('.yaml', '.yml')",
        "file_ext == '.log'",
        "file_ext == '.docm'",
    ]
    missing_extensions = [snippet for snippet in required_extensions if snippet not in source]
    assert not missing_extensions, f'Missing dispatcher branches: {missing_extensions}'

    print('Centralized upload metadata extraction passed')
    return True


def test_final_status_preserves_metadata_outcome():
    """Verify final status keeps metadata extraction outcomes visible."""
    print('Testing final metadata status resolution...')

    module_ast, _ = parse_functions_documents()
    resolver = get_function(module_ast, '_resolve_processing_complete_status')
    isolated_module = ast.Module(body=[resolver], type_ignores=[])
    namespace = {}
    exec(compile(isolated_module, FUNCTIONS_DOCUMENTS_FILE, 'exec'), namespace)
    resolve_status = namespace['_resolve_processing_complete_status']

    assert resolve_status(1, '.txt', ('.png',), ('.csv',), 'extracted') == (
        'Processing complete - final metadata extracted'
    )
    assert resolve_status(1, '.txt', ('.png',), ('.csv',), 'no_new_info') == (
        'Processing complete - metadata extraction yielded no new info'
    )
    assert resolve_status(1, '.txt', ('.png',), ('.csv',), 'warning') == (
        'Processing complete (metadata extraction warning)'
    )
    assert resolve_status(0, '.png', ('.png',), ('.csv',), 'skipped_no_chunks') == (
        'Processing complete - no text found in image'
    )
    assert resolve_status(0, '.csv', ('.png',), ('.csv',), 'skipped_no_chunks') == (
        'Processing complete - no data rows found or file empty'
    )

    print('Final metadata status resolution passed')
    return True


def test_public_workspace_media_scope_is_preserved():
    """Verify audio/video processing keeps public workspace chunks in public scope."""
    print('Testing public workspace media scope...')

    module_ast, source = parse_functions_documents()
    save_video_chunk = get_function(module_ast, 'save_video_chunk')
    save_video_args = [arg.arg for arg in save_video_chunk.args.args]
    assert 'public_workspace_id' in save_video_args, 'Video chunk saving must accept public_workspace_id'
    assert 'CLIENTS["search_client_public"]' in source, 'Video chunks must use the public search client when scoped public'
    assert 'chunk["public_workspace_id"] = public_workspace_id' in source, 'Video chunks must store public_workspace_id'

    process_audio = get_function(module_ast, 'process_audio_document')
    audio_calls = [node for node in ast.walk(process_audio) if isinstance(node, ast.Call)]
    save_chunk_calls = [call for call in audio_calls if call_name(call) == 'save_chunks']
    assert save_chunk_calls, 'Audio processing should save transcript chunks'
    assert any(has_keyword(call, 'public_workspace_id') for call in save_chunk_calls), (
        'Audio transcript chunks must pass public_workspace_id to save_chunks'
    )

    update_document = get_function(module_ast, 'update_document')
    update_calls = [node for node in ast.walk(update_document) if isinstance(node, ast.Call)]
    get_all_chunk_calls = [call for call in update_calls if call_name(call) == 'get_all_chunks']
    assert any(has_keyword(call, 'public_workspace_id') for call in get_all_chunk_calls), (
        'Metadata-to-chunk sync must retrieve chunks using public scope'
    )
    update_chunk_calls = [call for call in update_calls if call_name(call) == 'update_chunk_metadata']
    assert update_chunk_calls, 'Metadata-to-chunk sync should update search chunks'
    assert '"public_workspace_id": public_workspace_id' in source, (
        'Metadata-to-chunk sync must pass public scope into update_chunk_metadata'
    )

    print('Public workspace media scope passed')
    return True


def test_config_version_bumped_for_auto_metadata_fix():
    """Verify config.py version was bumped for this fix."""
    print('Testing config version bump...')

    config_source = read_file(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    assert version_match, 'Could not find VERSION in config.py'
    assert version_match.group(1) == '0.241.111', 'Expected config.py version 0.241.111'

    print('Config version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_dispatcher_owns_final_metadata_extraction,
        test_final_status_preserves_metadata_outcome,
        test_public_workspace_media_scope_is_preserved,
        test_config_version_bumped_for_auto_metadata_fix,
    ]

    results = []
    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            results.append(test())
        except Exception as test_error:
            print(f'Test failed: {test_error}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)