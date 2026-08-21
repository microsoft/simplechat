# test_codeql_import_cycle_lazy_imports.py
#!/usr/bin/env python3
"""
Functional test for CodeQL import-cycle lazy-import remediation.
Version: 0.250.120
Implemented in: 0.250.120

This test ensures the mixed-source and document-analysis modules do not reintroduce
the module-level imports that triggered PR 1145 CodeQL cyclic-import alerts.
"""

import ast
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(REPO_ROOT, "application", "single_app")


def _read_module_tree(module_filename):
    module_path = os.path.join(SINGLE_APP_DIR, module_filename)
    with open(module_path, "r", encoding="utf-8") as module_file:
        return ast.parse(module_file.read(), filename=module_path)


def _top_level_imports_from(tree, module_name):
    imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            imports.append(node)
    return imports


def _has_function(tree, function_name):
    return any(
        isinstance(node, ast.FunctionDef) and node.name == function_name
        for node in tree.body
    )


def test_mixed_source_log_event_import_is_lazy():
    """Validate mixed-source orchestration no longer imports App Insights at module load."""
    print("Testing mixed-source orchestration lazy telemetry import...")

    tree = _read_module_tree("functions_mixed_source_orchestration.py")
    top_level_imports = _top_level_imports_from(tree, "functions_appinsights")

    assert top_level_imports == [], "functions_appinsights must not be imported at module scope."
    assert _has_function(tree, "log_event"), "Expected lazy log_event wrapper to remain available."


def test_document_analysis_mixed_source_import_is_lazy():
    """Validate document analysis no longer imports mixed-source contracts at module load."""
    print("Testing document-analysis lazy mixed-source helper import...")

    tree = _read_module_tree("functions_document_analysis.py")
    top_level_imports = _top_level_imports_from(tree, "functions_mixed_source_orchestration")

    assert top_level_imports == [], "functions_mixed_source_orchestration must not be imported at module scope."
    assert _has_function(tree, "_get_mixed_source_orchestration_helpers"), (
        "Expected lazy mixed-source helper resolver to remain available."
    )


def main():
    tests = [
        test_mixed_source_log_event_import_is_lazy,
        test_document_analysis_mixed_source_import_is_lazy,
    ]
    results = []

    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as ex:
            print(f"FAIL: {test.__name__}: {ex}")
            results.append(False)

    success = all(results)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())