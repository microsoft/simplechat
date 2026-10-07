# test_action_catalogue_dedupe_hidden_types.py
#!/usr/bin/env python3
"""
Functional test for action catalogue dedupe and hidden legacy types.
Version: 0.261.276
Implemented in: 0.261.276

This test statically validates that get_plugin_types deduplicates by action type,
hides legacy/internal-only types from new-action creation, and exposes the
catalogue metadata used by the V2 action picker.
"""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_BACKEND_PLUGINS_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_plugins.py"
WORKSPACE_AUTHORING_FILE = REPO_ROOT / "application" / "single_app" / "functions_workspace_authoring.py"


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    function_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    return ast.get_source_segment(source, function_node) or ""


def test_hidden_new_action_types_are_declared():
    source = ROUTE_BACKEND_PLUGINS_FILE.read_text(encoding="utf-8")
    assert "DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE" in source
    for plugin_type in ("embedding_model", "queue_storage", "ui_test", "sql_schema"):
        assert plugin_type in source, f"{plugin_type} must be marked hidden/legacy for new action creation"
    assert "entry['hidden'] = True" in source
    assert "entry['legacy'] = True" in source


def test_get_plugin_types_dedupes_by_module_class_and_type_key():
    function_source = _function_source(ROUTE_BACKEND_PLUGINS_FILE, "get_plugin_types")
    assert "obj.__module__ == module.__name__" in function_source
    assert "type_entries = {}" in function_source
    assert "if module_type in type_entries" in function_source
    assert "list(type_entries.values())" in function_source


def test_catalogue_metadata_for_sql_databricks_and_m365():
    function_source = _function_source(ROUTE_BACKEND_PLUGINS_FILE, "get_plugin_types")
    assert "display_name = 'SQL Database'" in function_source
    assert "Schema discovery is included automatically" in function_source
    assert "Run governed read-only SQL Warehouse queries against Azure Databricks" in function_source
    assert "graph_endpoint=_catalog_graph_endpoint()" in function_source


def test_editor_types_preserve_catalogue_flags_and_capabilities():
    function_source = _function_source(WORKSPACE_AUTHORING_FILE, "build_action_editor_types")
    for field in ("hidden", "legacy", "capabilities", "defaults", "graph_endpoint"):
        assert field in function_source, f"build_action_editor_types must pass through {field}"


if __name__ == "__main__":
    test_hidden_new_action_types_are_declared()
    test_get_plugin_types_dedupes_by_module_class_and_type_key()
    test_catalogue_metadata_for_sql_databricks_and_m365()
    test_editor_types_preserve_catalogue_flags_and_capabilities()
    print("Action catalogue cleanup checks passed.")
