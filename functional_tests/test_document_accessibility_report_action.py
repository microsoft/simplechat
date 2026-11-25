#!/usr/bin/env python3
# test_document_accessibility_report_action.py
"""
Functional test for the get_document_accessibility_report Semantic Kernel function.
Version: 0.261.483
Implemented in: 0.261.392
Explicit native slide request contract covered in: 0.261.444
Typed refusal of Word comment requests with paging or filter arguments covered in: 0.261.483

This test ensures that:
1. get_document_accessibility_payload returns the full stored accessibility, style, and issue
   metadata for one document, honors the requested sections, and attaches page chunk text on request.
2. It refuses chat-scope documents and documents that have no stored metadata, with guidance.
3. The Document Search plugin exposes the function, and the agent citation layer treats it as a
   document-level citation.
4. Word comments asked together with a paging or filter argument are refused with a typed request
   error before any source is read, naming the arguments that were refused.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from functions_native_document_inspection import has_retained_native_source, inspect_native_document  # noqa: E402
from functions_native_audit import build_native_audit  # noqa: E402
from native_document_evidence import (  # noqa: E402
    NativeInspectionRequestError, validate_native_report_request,
)


def _load_payload_namespace(document, scope="personal", chunks=None):
    """Exec the payload helper from source with stubbed service dependencies."""
    source = (APP_ROOT / "functions_search_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted_functions = {"_normalize_accessibility_sections", "get_document_accessibility_payload"}
    wanted_assignments = {
        "ACCESSIBILITY_REPORT_SECTIONS",
        "ACCESSIBILITY_REPORT_STYLE_KEY",
        "ACCESSIBILITY_REPORT_ISSUES_KEY",
    }

    calls = {"chunks": []}

    def resolve_document_context(**kwargs):
        if document is None:
            return None
        return {"document": dict(document), "scope": scope, "group_id": None, "public_workspace_id": None}

    def get_ordered_document_chunks(**kwargs):
        calls["chunks"].append(kwargs)
        return chunks or []

    namespace = {
        "PROVENANCE_FIELD": "provenance",
        "resolve_document_context": resolve_document_context,
        "assert_document_available": lambda doc, **kwargs: doc,
        "document_provenance": lambda doc: {"id": doc.get("id")},
        "assert_evidence_available": lambda evidence, user_id: None,
        "get_ordered_document_chunks": get_ordered_document_chunks,
        "_coerce_positive_int": lambda value, default_value=1: max(int(value), 1) if str(value).isdigit() else default_value,
        "_serialize_document": lambda doc, scope_name: {"id": doc.get("id"), "scope": scope_name},
        "has_retained_native_source": has_retained_native_source,
        "inspect_native_document": inspect_native_document,
        "build_native_audit": build_native_audit,
        "validate_native_report_request": validate_native_report_request,
    }
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "functions_search_service.py", "exec"), namespace)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in wanted_assignments for target in node.targets
        ):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "functions_search_service.py", "exec"), namespace)
    namespace["_calls"] = calls
    return namespace


STORED_DOCUMENT = {
    "id": "doc-1",
    "accessibility_metadata": {
        "format": "pdf",
        "schema_version": "1.0",
        "language": "en-US",
        "is_tagged": True,
        "style_inventory": {"body_font": "Arial", "body_size_pt": 11},
        "issues": [{"code": "PDF_MISSING_LANGUAGE", "severity": "high"}],
    },
}


def test_payload_returns_full_metadata_and_sections():
    print("Testing accessibility payload sections...")
    namespace = _load_payload_namespace(STORED_DOCUMENT)
    payload = namespace["get_document_accessibility_payload"]("doc-1", "user-1")
    assert payload["sections"] == ["accessibility", "style", "issues"]
    assert payload["format"] == "pdf"
    assert payload["accessibility_metadata"] == {
        "format": "pdf", "schema_version": "1.0", "language": "en-US", "is_tagged": True,
    }
    assert payload["style_inventory"]["body_font"] == "Arial"
    assert payload["issues"][0]["code"] == "PDF_MISSING_LANGUAGE"
    assert payload["document"]["id"] == "doc-1"
    assert "page_chunks" not in payload

    style_only = namespace["get_document_accessibility_payload"]("doc-1", "user-1", sections="style")
    assert style_only["sections"] == ["style"]
    assert "issues" not in style_only and "accessibility_metadata" not in style_only

    ignored = namespace["get_document_accessibility_payload"]("doc-1", "user-1", sections="bogus, ISSUES")
    assert ignored["sections"] == ["issues"]
    fallback = namespace["get_document_accessibility_payload"]("doc-1", "user-1", sections="bogus")
    assert fallback["sections"] == ["accessibility", "style", "issues"]
    print("Payload sections test passed!")
    return True


def test_payload_page_chunks():
    print("Testing accessibility payload page chunks...")
    chunks = [
        {"page_number": 1, "chunk_text": "page one"},
        {"page_number": 2, "chunk_text": "page two\n- Page 2 Formatting"},
    ]
    namespace = _load_payload_namespace(STORED_DOCUMENT, chunks=chunks)
    payload = namespace["get_document_accessibility_payload"]("doc-1", "user-1", page_number="2")
    assert payload["page_number"] == 2
    assert [chunk["chunk_text"] for chunk in payload["page_chunks"]] == ["page two\n- Page 2 Formatting"]
    assert namespace["_calls"]["chunks"], "Expected the ordered chunks to be requested"
    print("Payload page chunks test passed!")
    return True


def test_payload_errors():
    print("Testing accessibility payload errors...")
    cases = [
        (None, "personal", "not found"),
        ({"id": "doc-2"}, "personal", "re-upload"),
        ({"id": "doc-3", "accessibility_metadata": {}}, "group", "re-upload"),
        (STORED_DOCUMENT, "chat", "chat uploads"),
    ]
    for document, scope, expected in cases:
        namespace = _load_payload_namespace(document, scope=scope)
        try:
            namespace["get_document_accessibility_payload"]("doc", "user-1")
        except LookupError as error:
            assert expected in str(error), str(error)
        else:
            raise AssertionError(f"Expected LookupError for scope={scope}, document={document}")
    print("Payload errors test passed!")
    return True


def test_word_comment_request_conflict_is_a_typed_refusal():
    """0.261.483: this was a plain ValueError, which ended an action step instead of correcting it."""
    print("Testing the Word comment request refusal...")
    document = {"id": "doc-w", "file_name": "review.docx", "accessibility_metadata": {"format": "docx"}}
    namespace = _load_payload_namespace(document)
    for arguments in (
        {"native_section": "all"}, {"native_cursor": "opaque-cursor"},
        {"sheet_name": "Summary"}, {"cell_range": "A1:B2"},
        {"native_cursor": "opaque-cursor", "cell_range": "A1:B2"},
    ):
        try:
            namespace["get_document_accessibility_payload"]("doc-w", "user-1", sections="comments", **arguments)
        except NativeInspectionRequestError as error:
            assert error.code == "native_word_comments_arguments_unsupported", error.code
            assert error.validation_rule == "native_word_comments_arguments_unsupported"
            assert set(error.refused_arguments) == set(arguments), error.refused_arguments
            assert error.argument_field == error.refused_arguments[0]
        else:
            raise AssertionError(f"Expected a typed refusal for {arguments}")
    assert not namespace["_calls"]["chunks"], "A refused request must not read the source"

    # The same request is valid for a workbook, for a Word request that keeps the defaults, and
    # for any request that does not ask for comments.
    validate_native_report_request("xlsx", "comments", native_section="all", sheet_name="Summary")
    validate_native_report_request("docx", "comments")
    validate_native_report_request("docx", "comments", native_section="comments", native_cursor="")
    validate_native_report_request("docx", "accessibility,style", native_section="all")
    print("Word comment request refusal test passed!")
    return True


def test_plugin_and_citation_contract():
    print("Testing plugin and citation contract...")
    plugin_source = (APP_ROOT / "semantic_kernel_plugins" / "document_search_plugin.py").read_text(encoding="utf-8")
    tree = ast.parse(plugin_source)
    plugin_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DocumentSearchPlugin"
    )
    method = next(
        node for node in plugin_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_document_accessibility_report"
    )
    decorators = {ast.unparse(decorator).split("(")[0] for decorator in method.decorator_list}
    assert "kernel_function" in decorators, decorators
    assert "get_document_accessibility_payload" in plugin_source
    assert plugin_source.count("get_document_accessibility_report") >= 2, "Expected a metadata entry"

    citation_source = (APP_ROOT / "functions_agent_document_citations.py").read_text(encoding="utf-8")
    assert "get_document_accessibility_report" in citation_source
    print("Plugin and citation contract test passed!")
    return True


def test_version():
    assert_app_version_at_least("0.261.392")
    return True


if __name__ == "__main__":
    tests = [
        test_payload_returns_full_metadata_and_sections,
        test_payload_page_chunks,
        test_payload_errors,
        test_word_comment_request_conflict_is_a_typed_refusal,
        test_plugin_and_citation_contract,
        test_version,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception:
            import traceback

            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
