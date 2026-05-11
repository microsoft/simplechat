# test_enhanced_citations_pdf_error_logging_fix.py
"""
Functional test for enhanced citations PDF dependency and logging fixes.
Version: 0.241.010
Implemented in: 0.241.009

This test ensures the enhanced citations PDF route resolves stored blob
metadata correctly, emits structured backend diagnostics, and the browser-side
PDF modal surfaces backend error messages instead of hiding them behind a
failed iframe request.
"""

import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_FILE = os.path.join(REPO_ROOT, 'application', 'single_app', 'config.py')
ENHANCED_CITATIONS_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_enhanced_citations.py')
ENHANCED_CITATIONS_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'chat', 'chat-enhanced-citations.js')
FIX_DOC = os.path.join(
    REPO_ROOT,
    'docs',
    'explanation',
    'fixes',
    'v0.241.009',
    'ENHANCED_CITATIONS_PDF_ERROR_LOGGING_FIX.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_route_imports_blob_helper_and_structured_logging():
    """Ensure the PDF route imports the blob helper and uses structured logging."""
    print('🔍 Validating enhanced citations PDF backend wiring...')

    route_content = read_file_text(ENHANCED_CITATIONS_ROUTE)

    assert 'from functions_appinsights import log_event' in route_content, (
        'Enhanced citations route should import log_event for structured diagnostics.'
    )
    assert 'from functions_documents import get_document_metadata, get_document_blob_storage_info' in route_content, (
        'Enhanced citations route should import get_document_blob_storage_info explicitly.'
    )
    assert 'def _log_enhanced_citations_debug(message, **details):' in route_content, (
        'Enhanced citations route should centralize tagged debug logging.'
    )
    assert '"PDF request received"' in route_content, (
        'PDF requests should emit a dedicated debug trace message.'
    )
    assert 'def _log_enhanced_citations_error(message, error, **details):' in route_content, (
        'Enhanced citations route should centralize structured error logging.'
    )
    assert '"Failed to serve citation content"' in route_content, (
        'Shared citation content failures should emit structured error logs.'
    )
    assert '"Failed to serve PDF citation content"' in route_content, (
        'PDF citation failures should emit structured error logs.'
    )
    assert 'print(f"Error serving enhanced citation content: {e}")' not in route_content, (
        'Shared citation content failures should no longer use print-based logging.'
    )
    assert 'print(f"Error serving PDF citation content: {e}")' not in route_content, (
        'PDF citation failures should no longer use print-based logging.'
    )

    print('✅ Enhanced citations PDF backend wiring is present')


def test_pdf_modal_prefetches_and_surfaces_backend_errors():
    """Ensure the PDF modal fetches first so backend JSON errors reach the browser."""
    print('🔍 Validating enhanced citations PDF modal error handling...')

    js_content = read_file_text(ENHANCED_CITATIONS_JS)

    assert 'await showPdfModal(docId, pageNumberOrTimestamp, citationId);' in js_content, (
        'Enhanced citation modal should await the async PDF loader.'
    )
    assert 'export async function showPdfModal(docId, pageNumber, citationId)' in js_content, (
        'PDF modal loader should be async so it can inspect backend responses.'
    )
    assert "const response = await fetch(pdfUrl" in js_content, (
        'PDF modal should prefetch the PDF endpoint before attempting to render it.'
    )
    assert "const pdfBlob = await response.blob();" in js_content, (
        'Successful PDF responses should be converted to a blob-backed viewer URL.'
    )
    assert "response.headers.get('X-Sub-PDF-Page') || '1'" in js_content, (
        'PDF modal should preserve the server-selected viewer page.'
    )
    assert "showToast(error.message || 'Failed to load PDF document.', 'danger');" in js_content, (
        'Backend PDF error messages should be shown to the user through a toast.'
    )
    assert 'fallBackToTextCitation(citationId);' in js_content, (
        'Failed PDF loads should still fall back to text citations.'
    )
    assert 'pdfFrame.src = `${pdfObjectUrl}#page=${encodeURIComponent(viewerPage)}`;' in js_content, (
        'PDF iframe should render the fetched blob URL at the correct viewer page.'
    )

    print('✅ Enhanced citations PDF modal error handling is present')


def test_fix_documentation_and_version_alignment():
    """Ensure config and fix documentation reflect the PDF dependency/logging fix."""
    print('🔍 Validating version bump and fix documentation...')

    config_content = read_file_text(CONFIG_FILE)
    fix_doc_content = read_file_text(FIX_DOC)

    assert 'VERSION = "0.241.010"' in config_content, 'Expected config.py version 0.241.010.'
    assert 'Fixed/Implemented in version: **0.241.009**' in fix_doc_content, (
        'Fix documentation should reference version 0.241.009.'
    )
    assert 'get_document_blob_storage_info' in fix_doc_content, (
        'Fix documentation should mention the missing blob helper import root cause.'
    )
    assert 'log_event' in fix_doc_content, (
        'Fix documentation should mention the structured backend logging update.'
    )
    assert 'showPdfModal' in fix_doc_content, (
        'Fix documentation should mention the PDF modal fetch-first behavior.'
    )
    assert 'ui_tests/test_enhanced_citations_pdf_error_toast.py' in fix_doc_content, (
        'Fix documentation should reference the UI regression coverage.'
    )

    print('✅ Version bump and fix documentation are aligned')


if __name__ == '__main__':
    tests = [
        test_route_imports_blob_helper_and_structured_logging,
        test_pdf_modal_prefetches_and_surfaces_backend_errors,
        test_fix_documentation_and_version_alignment,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except AssertionError as error:
            results.append(False)
            print(f'❌ {test.__name__} failed: {error}')
        print()

    passed = sum(results)
    total = len(results)
    print(f'📊 Test Results: {passed}/{total} tests passed')
    sys.exit(0 if passed == total else 1)