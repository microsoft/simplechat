# test_file_upload_document_ingestion_security_audit.py
"""
Functional test for file upload and document ingestion security audit fixes.
Version: 0.242.054
Implemented in: 0.242.054

This test ensures external public document operations revalidate public workspace
roles, citation-derived browser HTML is escaped, and download response filenames
use safe Content-Disposition encoding.
"""

import ast
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "application" / "single_app" / "config.py"
EXTERNAL_PUBLIC_DOCUMENTS_ROUTE = ROOT_DIR / "application" / "single_app" / "route_external_public_documents.py"
ENHANCED_CITATIONS_ROUTE = ROOT_DIR / "application" / "single_app" / "route_enhanced_citations.py"
CHAT_CITATIONS_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-citations.js"
FIX_DOC_PATH = ROOT_DIR / "docs" / "explanation" / "fixes" / "FILE_UPLOAD_DOCUMENT_INGESTION_SECURITY_AUDIT_FIX.md"
EXPECTED_VERSION = "0.242.054"


def _read_text(path):
    return path.read_text(encoding="utf-8")


def _route_functions(path):
    tree = ast.parse(_read_text(path), filename=str(path))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _call_names(function_node):
    names = []
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def _assert_contains(source, snippets, label):
    missing = [snippet for snippet in snippets if snippet not in source]
    assert not missing, f"Missing {label} snippets: {missing}"


def _assert_not_contains(source, snippets, label):
    present = [snippet for snippet in snippets if snippet in source]
    assert not present, f"Unexpected {label} snippets: {present}"


def test_external_public_document_routes_revalidate_workspace_context():
    """External public document routes must authorize scope before data operations."""
    print("Testing external public document route authorization guardrails...")

    source = _read_text(EXTERNAL_PUBLIC_DOCUMENTS_ROUTE)
    functions = _route_functions(EXTERNAL_PUBLIC_DOCUMENTS_ROUTE)
    route_names = [
        "external_upload_public_document",
        "external_get_public_documents",
        "external_get_public_document",
        "external_patch_public_document",
        "external_delete_public_document",
        "external_extract_public_metadata",
        "external_upgrade_legacy_public_documents",
    ]

    for route_name in route_names:
        assert route_name in functions, f"Missing route function: {route_name}"
        calls = _call_names(functions[route_name])
        assert "_require_external_public_workspace_context" in calls, (
            f"{route_name} must revalidate public workspace context"
        )

    manager_routes = [
        "external_upload_public_document",
        "external_patch_public_document",
        "external_delete_public_document",
        "external_extract_public_metadata",
        "external_upgrade_legacy_public_documents",
    ]
    for route_name in manager_routes:
        route_source = ast.get_source_segment(source, functions[route_name]) or ""
        assert "PUBLIC_WORKSPACE_EXTERNAL_MANAGER_ROLES" in route_source, (
            f"{route_name} must require public workspace manager roles"
        )

    _assert_not_contains(
        source,
        [
            "request.form.get('user_id')",
            "request.args.get('user_id')",
            "request.form.get('active_workspace_id')",
            "request.args.get('active_workspace_id')",
        ],
        "caller-supplied identity reads outside the shared validator",
    )


def test_chat_citation_html_escapes_document_derived_values():
    """Citation parser must escape filenames, labels, and generated attributes."""
    print("Testing chat citation HTML escaping guardrails...")

    source = _read_text(CHAT_CITATIONS_JS)
    _assert_contains(
        source,
        [
            "sanitizeHttpUrl",
            "function serializeSafeElement(element)",
            "function buildSafeExternalLinkHtml(url, label)",
            "const safeFilenameText = escapeHtml(trimmedFilename);",
            "filenameHtml = buildSafeExternalLinkHtml(safeFilenameUrl, trimmedFilename);",
            "return escapeHtml(token);",
            "${escapeHtml(locationLabel)}",
            "const safePageText = escapeHtml(pageStr);",
            "link.dataset.citationId = cleanCitationId;",
            "link.dataset.sheetName = String(sheetName);",
            "link.textContent = String(pageStr ?? '');",
            "return serializeSafeElement(link);",
        ],
        "citation XSS hardening",
    )
    _assert_not_contains(
        source,
        [
            'href="${filename.trim()}"',
            'data-citation-id="${cleanCitationId}"',
            "${pageStr}</a>",
            "escapeAttribute(safeFilenameUrl)",
        ],
        "unsafe citation interpolation",
    )


def test_enhanced_citation_download_headers_encode_filenames():
    """Download responses must not interpolate raw document filenames into headers."""
    print("Testing enhanced citation Content-Disposition filename encoding...")

    source = _read_text(ENHANCED_CITATIONS_ROUTE)
    _assert_contains(
        source,
        [
            "def _build_content_disposition(",
            "secure_filename(normalized_file_name)",
            "quote(normalized_file_name, safe='')",
            "filename*=UTF-8",
            "'Content-Disposition': _build_content_disposition('attachment', filename)",
            "'Content-Disposition': _build_content_disposition(disposition, raw_doc.get('file_name'))",
            "'Content-Disposition': _build_content_disposition('inline', raw_doc.get('file_name'))",
        ],
        "safe Content-Disposition helper usage",
    )
    _assert_not_contains(
        source,
        [
            "filename=\"{filename}\"",
            "filename=\"{raw_doc[\"file_name\"]}\"",
            "filename=\"{raw_doc['file_name']}\"",
        ],
        "raw Content-Disposition filename interpolation",
    )


def test_fix_version_and_documentation_exist():
    """Version and fix documentation must track this security change."""
    print("Testing version bump and fix documentation...")

    config_source = _read_text(CONFIG_PATH)
    assert f'VERSION = "{EXPECTED_VERSION}"' in config_source
    assert FIX_DOC_PATH.exists(), f"Expected fix documentation at {FIX_DOC_PATH}"


def main():
    tests = [
        test_external_public_document_routes_revalidate_workspace_context,
        test_chat_citation_html_escapes_document_derived_values,
        test_enhanced_citation_download_headers_encode_filenames,
        test_fix_version_and_documentation_exist,
    ]

    failures = []
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"FAIL: {test.__name__}: {exc}")

    if failures:
        return 1

    print(f"Results: {len(tests)}/{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())