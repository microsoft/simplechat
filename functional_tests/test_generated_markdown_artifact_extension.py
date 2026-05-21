#!/usr/bin/env python3
# test_generated_markdown_artifact_extension.py
"""
Functional test for generated Markdown artifact extension handling.
Version: 0.241.081
Implemented in: 0.241.081

This test ensures generated Markdown artifacts keep their .md extension when
saved as chat artifacts and when legacy .json-named artifacts are promoted into
a workspace.
"""

import ast
import os
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIMPLECHAT_OPERATIONS_FILE = ROOT / "application" / "single_app" / "functions_simplechat_operations.py"
ENHANCED_CITATIONS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_enhanced_citations.py"


def load_isolated_functions(path, function_names):
    """Load selected pure helper functions without importing Azure-backed modules."""
    source = path.read_text(encoding="utf-8")
    module_ast = ast.parse(source, filename=str(path))
    requested_names = set(function_names)
    selected_nodes = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in requested_names
    ]
    loaded_names = {node.name for node in selected_nodes}
    missing_names = requested_names - loaded_names
    if missing_names:
        raise AssertionError(f"Missing helper(s) in {path}: {sorted(missing_names)}")

    isolated_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(isolated_module)
    namespace = {"os": os}
    exec(compile(isolated_module, str(path), "exec"), namespace)
    return {name: namespace[name] for name in function_names}


def test_generated_document_file_name_preserves_markdown_extension():
    """Validate generated artifact filename normalization does not relabel Markdown as JSON."""
    helpers = load_isolated_functions(
        SIMPLECHAT_OPERATIONS_FILE,
        ["_normalize_generated_document_file_name"],
    )
    normalize_file_name = helpers["_normalize_generated_document_file_name"]

    assert normalize_file_name("deep_research_ledger_20260521_194546.md") == "deep_research_ledger_20260521_194546.md"
    assert normalize_file_name("analysis-result.csv") == "analysis-result.csv"
    assert normalize_file_name("analysis-result") == "analysis-result.json"
    assert normalize_file_name("unsupported.exe") == "unsupported.exe"
    return True


def test_promotion_file_name_repairs_legacy_markdown_artifact_extension():
    """Validate promotion names use output format metadata for existing misnamed artifacts."""
    helpers = load_isolated_functions(
        ENHANCED_CITATIONS_ROUTE_FILE,
        ["_resolve_generated_artifact_file_name"],
    )
    resolve_file_name = helpers["_resolve_generated_artifact_file_name"]

    legacy_markdown_message = {
        "filename": "deep_research_ledger_20260521_194546.json",
        "metadata": {
            "generated_artifact_output_format": "md",
        },
    }
    assert resolve_file_name(legacy_markdown_message) == "deep_research_ledger_20260521_194546.md"

    current_markdown_message = {
        "filename": "deep_research_ledger_20260521_194546.md",
        "metadata": {
            "generated_artifact_output_format": "md",
        },
    }
    assert resolve_file_name(current_markdown_message) == "deep_research_ledger_20260521_194546.md"

    json_message = {
        "filename": "analysis-output.json",
        "metadata": {
            "generated_artifact_output_format": "json",
        },
    }
    assert resolve_file_name(json_message) == "analysis-output.json"
    return True


def test_download_and_promotion_routes_use_resolved_artifact_name():
    """Validate download and workspace promotion both use corrected artifact filenames."""
    route_content = ENHANCED_CITATIONS_ROUTE_FILE.read_text(encoding="utf-8")
    assert "'file_name': _resolve_generated_artifact_file_name(message_item)" in route_content
    assert "file_name = _resolve_generated_artifact_file_name(message_item)" in route_content
    return True


def run_tests():
    tests = [
        test_generated_document_file_name_preserves_markdown_extension,
        test_promotion_file_name_repairs_legacy_markdown_artifact_extension,
        test_download_and_promotion_routes_use_resolved_artifact_name,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
            print("PASS")
        except Exception as exc:
            print(f"FAIL: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)