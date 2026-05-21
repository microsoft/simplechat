#!/usr/bin/env python3
# test_visio_extensions_config.py
"""
Functional test for Visio extension configuration export.
Version: 0.241.079
Implemented in: 0.241.079

This test ensures that config.py exports VISIO_EXTENSIONS and includes VSDX
in allowed uploads so Visio ingestion and enhanced citation routes can start.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CONFIG_PATH = APP_ROOT / "config.py"
ENHANCED_CITATIONS_ROUTE_PATH = APP_ROOT / "route_enhanced_citations.py"


def _parse_python_file(path):
    """Parse a Python file without executing import-time Azure client setup."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _get_set_assignment(tree, assignment_name):
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == assignment_name for target in node.targets):
            continue
        if not isinstance(node.value, ast.Set):
            raise AssertionError(f"{assignment_name} must be declared as a set literal")
        return {
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
    raise AssertionError(f"{assignment_name} was not declared in config.py")


def test_visio_extensions_constant_declared():
    """Validate the shared Visio extension constant exists for imports."""
    config_tree = _parse_python_file(CONFIG_PATH)

    assert _get_set_assignment(config_tree, "VISIO_EXTENSIONS") == {"vsdx"}


def test_allowed_extensions_include_visio_extensions():
    """Validate VSDX files are accepted by the shared upload allow-list."""
    config_tree = _parse_python_file(CONFIG_PATH)
    get_allowed_extensions = next(
        (
            node
            for node in config_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "get_allowed_extensions"
        ),
        None,
    )

    assert get_allowed_extensions is not None
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "extensions"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "VISIO_EXTENSIONS"
        for node in ast.walk(get_allowed_extensions)
    )


def test_enhanced_citations_imports_visio_extensions():
    """Validate enhanced citation startup imports the shared Visio constant."""
    route_tree = _parse_python_file(ENHANCED_CITATIONS_ROUTE_PATH)

    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "config"
        and any(alias.name == "VISIO_EXTENSIONS" for alias in node.names)
        for node in route_tree.body
    )


def run_standalone():
    """Run tests without pytest for local functional validation."""
    tests = [
        test_visio_extensions_constant_declared,
        test_allowed_extensions_include_visio_extensions,
        test_enhanced_citations_imports_visio_extensions,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"{test.__name__} passed")
            results.append(True)
        except Exception as error:
            print(f"{test.__name__} failed: {error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    success = run_standalone()
    sys.exit(0 if success else 1)