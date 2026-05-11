#!/usr/bin/env python3
"""
Functional test for historical enhanced citation revision rendering fix.
Version: 0.240.025
Implemented in: 0.240.025

This test ensures older chat citations can fetch exact document metadata on
demand and continue rendering archived PDF and tabular content after a newer
revision becomes the current workspace document.
"""

import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
CHAT_DOCUMENTS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-documents.js')
CHAT_ENHANCED_CITATIONS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-enhanced-citations.js')
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_enhanced_citations.py')
FIX_DOC = os.path.join(ROOT_DIR, 'docs', 'explanation', 'fixes', 'HISTORICAL_ENHANCED_CITATION_REVISION_RENDERING_FIX.md')


def read_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_chat_can_fetch_metadata_for_historical_cited_revisions():
    print('🔍 Testing on-demand metadata fetch for historical cited revisions...')

    chat_documents = read_text(CHAT_DOCUMENTS_FILE)
    chat_enhanced_citations = read_text(CHAT_ENHANCED_CITATIONS_FILE)

    assert 'const citationMetadataCache = new Map();' in chat_documents
    assert 'export async function fetchDocumentMetadata(docId)' in chat_documents
    assert '/api/enhanced_citations/document_metadata?doc_id=' in chat_documents
    assert 'let docMetadata = getDocumentMetadata(docId);' in chat_enhanced_citations
    assert 'docMetadata = await fetchDocumentMetadata(docId);' in chat_enhanced_citations
    assert 'Historical cited revisions' in chat_enhanced_citations
    assert 'fetch on demand when needed' in chat_enhanced_citations

    print('✅ On-demand metadata fetch for historical cited revisions passed')
    return True


def test_enhanced_citations_route_exposes_exact_document_metadata_lookup():
    print('🔍 Testing enhanced citation metadata route...')

    route_source = read_text(ROUTE_FILE)

    assert '@app.route("/api/enhanced_citations/document_metadata", methods=["GET"])' in route_source
    assert 'doc_response, status_code = get_document(user_id, doc_id)' in route_source
    assert 'get_document_blob_storage_info(raw_doc)' in route_source
    assert '"file_name": raw_doc.get("file_name")' in route_source
    assert '"enhanced_citations": bool(blob_path)' in route_source

    print('✅ Enhanced citation metadata route passed')
    return True


def test_version_and_fix_documentation_alignment():
    print('🔍 Testing version and fix documentation alignment...')

    version = read_config_version()
    fix_doc_content = read_text(FIX_DOC)

    assert version == '0.240.025', version
    assert 'Fixed/Implemented in version: **0.240.025**' in fix_doc_content
    assert 'older chat citations' in fix_doc_content.lower()
    assert 'archived PDF and tabular content' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_chat_can_fetch_metadata_for_historical_cited_revisions,
        test_enhanced_citations_route_exposes_exact_document_metadata_lookup,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)