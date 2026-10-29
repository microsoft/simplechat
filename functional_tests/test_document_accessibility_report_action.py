#!/usr/bin/env python3
# test_document_accessibility_report_action.py
"""
Functional test for the get_document_accessibility_report Semantic Kernel function.
Version: 0.261.392
Implemented in: 0.261.392

This test ensures that:
1. get_document_accessibility_payload returns the full stored accessibility, style, and issue
   metadata for one document, honors the requested sections, and attaches page chunk text on request.
2. It refuses chat-scope documents and documents that have no stored metadata, with guidance.
3. The Document Search plugin exposes the function, and the agent citation layer treats it as a
   document-level citation.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


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
