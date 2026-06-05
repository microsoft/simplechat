# test_document_intelligence_auto_reprocess_contract.py
"""
Functional test for Document Intelligence Auto mode and PDF reprocessing.
Version: 0.241.163
Implemented in: 0.241.163

This test ensures Auto mode, stored source-file requirements, Read/Layout
reprocess APIs, and workspace UI controls are wired without requiring live
Azure Document Intelligence or Blob Storage calls.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content, expected_text, description):
    """Raise a clear assertion error when expected text is missing."""
    if expected_text not in content:
        raise AssertionError(f"Missing {description}: {expected_text}")


def test_document_intelligence_auto_reprocess_contract():
    """Validate Auto mode and PDF reprocess contracts across backend and UI."""
    print("Testing Document Intelligence Auto/reprocess contract...")

    config = read_repo_file("application/single_app/config.py")
    settings = read_repo_file("application/single_app/functions_settings.py")
    content = read_repo_file("application/single_app/functions_content.py")
    documents = read_repo_file("application/single_app/functions_documents.py")
    personal_route = read_repo_file("application/single_app/route_backend_documents.py")
    group_route = read_repo_file("application/single_app/route_backend_group_documents.py")
    public_route = read_repo_file("application/single_app/route_backend_public_documents.py")
    workspace_html = read_repo_file("application/single_app/templates/workspace.html")
    workspace_js = read_repo_file("application/single_app/static/js/workspace/workspace-documents.js")
    workspace_tags_js = read_repo_file("application/single_app/static/js/workspace/workspace-tags.js")
    group_html = read_repo_file("application/single_app/templates/group_workspaces.html")
    public_html = read_repo_file("application/single_app/templates/public_workspaces.html")
    public_js = read_repo_file("application/single_app/static/js/public/public_workspace.js")

    assert_contains(config, 'VERSION = "0.241.163"', "current version")

    assert_contains(settings, '"auto"', "Auto allowed mode")
    assert_contains(settings, "DOCUMENT_INTELLIGENCE_MANUAL_EXTRACTION_MODES", "manual reprocess modes")
    assert_contains(settings, "DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_MAX = 20", "Auto sample page cap")

    assert_contains(content, 'analyze_options["pages"] = str(pages)', "DI page sampling support")

    assert_contains(documents, "def _resolve_document_intelligence_auto_mode", "Auto resolver")
    assert_contains(documents, "Selection marks detected:", "selection mark Auto signal")
    assert_contains(documents, "DI_MARKDOWN_TABLE_SEPARATOR_PATTERN", "table Auto signal")
    assert_contains(documents, "source_file_available", "source blob metadata")
    assert_contains(documents, '"mark_enhanced_citations": False', "source-only blob upload")
    assert_contains(documents, "def validate_document_reprocess_source", "reprocess source validation")
    assert_contains(documents, "Only PDF documents can be reprocessed", "PDF-only validation message")
    assert_contains(documents, "def process_document_reprocess_extraction_background", "reprocess worker")
    assert_contains(documents, "delete_document_chunks(document_id", "chunk replacement before reindex")
    assert_contains(documents, "extraction_mode_override=target_mode", "forced reprocess mode")

    for route_content, route_name in (
        (personal_route, "personal"),
        (group_route, "group"),
        (public_route, "public"),
    ):
        assert_contains(route_content, "reprocess_extraction", f"{route_name} reprocess route")
        assert_contains(route_content, "@swagger_route(security=get_auth_security())", f"{route_name} swagger decorator")
        assert_contains(route_content, "DOCUMENT_INTELLIGENCE_MANUAL_EXTRACTION_MODES", f"{route_name} manual mode validation")
        assert_contains(route_content, "validate_document_reprocess_source", f"{route_name} source validation")
        assert_contains(route_content, "process_document_reprocess_extraction_background", f"{route_name} background worker")

    assert_contains(group_route, "require_active_group(", "group active-scope authorization")
    assert_contains(public_route, "require_active_public_workspace(", "public active-scope authorization")

    assert_contains(workspace_html, "reprocess-selected-dropdown", "personal bulk reprocess dropdown")
    assert_contains(workspace_js, "getDocumentExtractionModeBadge", "personal extraction badge")
    assert_contains(workspace_js, "window.reprocessDocumentExtraction", "personal single reprocess handler")
    assert_contains(workspace_js, "window.reprocessSelectedDocumentExtraction", "personal bulk reprocess handler")
    assert_contains(workspace_tags_js, "getWorkspaceDocumentExtractionModeBadge", "personal folder extraction badge")

    assert_contains(group_html, "group-reprocess-selected-dropdown", "group bulk reprocess dropdown")
    assert_contains(group_html, "getGroupDocumentExtractionModeBadge", "group extraction badge")
    assert_contains(group_html, "reprocessGroupDocumentExtraction", "group single reprocess handler")
    assert_contains(group_html, "reprocessGroupSelectedDocumentExtraction", "group bulk reprocess handler")

    assert_contains(public_html, "public-reprocess-selected-dropdown", "public bulk reprocess dropdown")
    assert_contains(public_js, "getPublicDocumentExtractionModeBadgeHtml", "public extraction badge")
    assert_contains(public_js, "reprocessPublicDocumentExtraction", "public single reprocess handler")
    assert_contains(public_js, "reprocessPublicSelectedDocumentExtraction", "public bulk reprocess handler")

    print("Document Intelligence Auto/reprocess contract passed.")
    return True


if __name__ == "__main__":
    try:
        success = test_document_intelligence_auto_reprocess_contract()
    except Exception as exc:
        print(f"Test failed: {exc}")
        sys.exit(1)
    sys.exit(0 if success else 1)