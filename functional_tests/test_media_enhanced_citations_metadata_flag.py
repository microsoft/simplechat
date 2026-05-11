#!/usr/bin/env python3
# test_media_enhanced_citations_metadata_flag.py
"""
Functional test for media enhanced citation metadata normalization.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures blob-backed audio and video documents are marked as
enhanced citations in stored metadata so workspace badges match chat behavior.
"""

import ast
import os
import re
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
FUNCTIONS_DOCUMENTS_FILE = os.path.join(SINGLE_APP_ROOT, 'functions_documents.py')
ROUTE_FILE = os.path.join(SINGLE_APP_ROOT, 'route_enhanced_citations.py')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_normalization_helpers():
    """Compile the normalization helpers directly from source for focused validation."""
    source = read_file(FUNCTIONS_DOCUMENTS_FILE)
    module_ast = ast.parse(source, filename=FUNCTIONS_DOCUMENTS_FILE)

    helper_names = {
        '_has_persisted_blob_reference',
        '_normalize_document_enhanced_citations',
    }
    helper_nodes = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]

    missing_helpers = helper_names.difference({node.name for node in helper_nodes})
    assert not missing_helpers, f'Missing normalization helpers: {sorted(missing_helpers)}'

    isolated_module = ast.Module(body=helper_nodes, type_ignores=[])
    namespace = {'ARCHIVED_REVISION_BLOB_PATH_MODE': 'archived_revision'}
    exec(compile(isolated_module, FUNCTIONS_DOCUMENTS_FILE, 'exec'), namespace)
    return namespace['_normalize_document_enhanced_citations']


def test_blob_backed_documents_normalize_to_enhanced():
    """Verify legacy and current blob-backed documents normalize to enhanced citations."""
    print('🔍 Testing blob-backed document normalization...')

    normalize_document = load_normalization_helpers()

    current_blob_doc = {'id': 'audio-doc', 'blob_path': 'user/audio.mp3'}
    normalized_current = normalize_document(dict(current_blob_doc))
    assert normalized_current['enhanced_citations'] is True, 'Current blob path should normalize to enhanced citations'

    archived_blob_doc = {
        'id': 'video-doc',
        'blob_path': None,
        'blob_path_mode': 'archived_revision',
        'archived_blob_path': 'user/family/video.mp4',
    }
    normalized_archived = normalize_document(dict(archived_blob_doc))
    assert normalized_archived['enhanced_citations'] is True, 'Archived blob path should normalize to enhanced citations'

    text_only_doc = {'id': 'text-doc', 'blob_path': None, 'archived_blob_path': None}
    normalized_text = normalize_document(dict(text_only_doc))
    assert normalized_text['enhanced_citations'] is False, 'Documents without persisted blob references should stay standard'

    print('✅ Blob-backed document normalization passed')
    return True


def test_blob_upload_persists_enhanced_flag():
    """Verify uploads stamp the document metadata with enhanced_citations=True."""
    print('🔍 Testing blob upload metadata stamping...')

    source = read_file(FUNCTIONS_DOCUMENTS_FILE)
    required_snippets = [
        'current_document["enhanced_citations"] = True',
        '"enhanced_citations": False,',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing upload/create metadata snippets: {missing}'

    print('✅ Blob upload metadata stamping passed')
    return True


def test_document_reads_use_normalized_enhanced_flag():
    """Verify document list/detail reads expose normalized enhanced citation state."""
    print('🔍 Testing document read normalization and enhanced citation metadata route...')

    documents_source = read_file(FUNCTIONS_DOCUMENTS_FILE)
    route_source = read_file(ROUTE_FILE)

    required_document_snippets = [
        '_normalize_document_enhanced_citations(_choose_current_document(family_documents))',
        'return jsonify(_normalize_document_enhanced_citations(document_results[0])), 200',
        'return _normalize_document_enhanced_citations(document_items[0]) if document_items else None',
    ]
    missing_document_snippets = [
        snippet for snippet in required_document_snippets if snippet not in documents_source
    ]
    assert not missing_document_snippets, (
        'Missing document normalization snippets: '
        f'{missing_document_snippets}'
    )

    route_snippet = '"enhanced_citations": bool(raw_doc.get("enhanced_citations", False))'
    assert route_snippet in route_source, 'Enhanced citation metadata route should use normalized per-document flag'
    assert 'bool(blob_path)' not in route_source, 'Metadata route should no longer infer enhanced citations from a derived blob path'

    print('✅ Document read normalization passed')
    return True


def test_config_version_bumped_for_media_citation_fix():
    """Verify config.py version was bumped for this fix."""
    print('🔍 Testing config version bump...')

    config_source = read_file(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    assert version_match, 'Could not find VERSION in config.py'
    assert version_match.group(1) == '0.241.007', 'Expected config.py version 0.241.007'

    print('✅ Config version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_blob_backed_documents_normalize_to_enhanced,
        test_blob_upload_persists_enhanced_flag,
        test_document_reads_use_normalized_enhanced_flag,
        test_config_version_bumped_for_media_citation_fix,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)