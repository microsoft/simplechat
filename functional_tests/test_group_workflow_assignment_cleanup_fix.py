#!/usr/bin/env python3
# test_group_workflow_assignment_cleanup_fix.py
"""
Functional test for group workflow assignment cleanup.
Version: 0.261.059
Implemented in: 0.241.201

This test ensures malformed nested JSON strings cannot be persisted as group
workflow assignment IDs and that valid group UUIDs are preserved.

The normalizers are extracted from source and executed in isolation rather than
imported, because importing ``functions_settings`` reaches ``config.py`` and a
live Cosmos client. As of 0.261.059 the pure ones live in
``functions_group_assignment_ids.py`` and are re-exported, so the extraction spans
both modules and the re-export itself is asserted.
"""

import ast
import json
import re
import sys
import traceback
import uuid
from pathlib import Path
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
FUNCTIONS_SETTINGS_PATH = APP_DIR / "functions_settings.py"
# The pure id normalizers were moved out of functions_settings.py so that
# admin_settings_fields.py could reuse them: that module renders the V2 admin
# surface and cannot import functions_settings, which builds a Cosmos client at
# import time. functions_settings re-exports them, so callers are unchanged, but
# the AST extraction below has to look in both files to find their definitions.
GROUP_ASSIGNMENT_IDS_PATH = APP_DIR / "functions_group_assignment_ids.py"
ADMIN_SETTINGS_JS_PATH = APP_DIR / "static" / "js" / "admin" / "admin_settings.js"
CONFIG_PATH = APP_DIR / "config.py"

# Where each symbol is defined. Pinning this rather than searching every module
# keeps the test meaningful: a symbol that quietly moves again fails here with the
# file it was expected in, instead of passing because some other copy was found.
NORMALIZER_SYMBOL_SOURCES = {
    GROUP_ASSIGNMENT_IDS_PATH: {
        "GROUP_WORKFLOW_ALLOWED_GROUP_ID_PARSE_DEPTH_LIMIT",
        "_iter_group_workflow_allowed_group_id_candidates",
        "normalize_group_workflow_allowed_group_id",
        "normalize_group_workflow_allowed_group_ids",
    },
    FUNCTIONS_SETTINGS_PATH: {
        "normalize_group_workflow_assignment_settings",
    },
}


def read_text(path):
    """Read a repository file."""
    return path.read_text(encoding="utf-8")


def _select_symbol_nodes(source, path, required_names):
    """Return the AST nodes defining ``required_names``, asserting none are missing."""
    module_tree = ast.parse(source)
    selected_nodes = []

    for node in module_tree.body:
        if isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assigned_names.intersection(required_names):
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in required_names:
            selected_nodes.append(node)

    defined_names = {
        getattr(node, "name", None) for node in selected_nodes
    } | {
        target.id
        for node in selected_nodes
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    missing_names = sorted(required_names - defined_names)
    assert not missing_names, (
        f"Missing expected normalizer symbols in {path.name}: {missing_names}. "
        "An import does not count: this test executes the definitions in isolation "
        "so the normalizers are exercised without standing up Azure clients."
    )
    return selected_nodes


def load_settings_normalizer_symbols():
    """Load the pure group workflow assignment normalizer symbols.

    Returns ``(namespace, functions_settings_source)``. The namespace holds the
    normalizers executed in isolation, which is how this test exercises them
    without importing ``functions_settings`` and, through it, a live Cosmos client.
    """
    selected_nodes = []
    settings_source = None

    for path, required_names in NORMALIZER_SYMBOL_SOURCES.items():
        source = read_text(path)
        if path == FUNCTIONS_SETTINGS_PATH:
            settings_source = source
        selected_nodes.extend(_select_symbol_nodes(source, path, required_names))

    normalizer_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(normalizer_module)

    namespace = {
        "json": json,
        "uuid": uuid,
    }
    exec(compile(normalizer_module, str(FUNCTIONS_SETTINGS_PATH), "exec"), namespace)
    return namespace, settings_source


def test_normalizers_are_re_exported_by_functions_settings():
    """Callers import these from functions_settings; the move must be invisible."""
    print("Testing that functions_settings re-exports the moved normalizers...")

    settings_source = read_text(FUNCTIONS_SETTINGS_PATH)
    module_tree = ast.parse(settings_source)

    imported_names = {
        alias.asname or alias.name
        for node in module_tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == GROUP_ASSIGNMENT_IDS_PATH.stem
        for alias in node.names
    }

    expected = NORMALIZER_SYMBOL_SOURCES[GROUP_ASSIGNMENT_IDS_PATH]
    missing = sorted(expected - imported_names)

    assert not missing, (
        "functions_settings.py no longer re-exports these normalizers from "
        f"{GROUP_ASSIGNMENT_IDS_PATH.name}, so every existing caller that imports "
        f"them from functions_settings breaks:\n  {missing}"
    )

    print(f"  All {len(expected)} moved normalizer(s) are re-exported.")


def build_nested_json_list(value, depth):
    """Build a legacy nested JSON-list string around a value."""
    nested_value = value
    remaining_depth = depth
    while remaining_depth > 0:
        nested_value = json.dumps([nested_value])
        remaining_depth -= 1
    return nested_value


def test_normalizer_removes_junk_and_preserves_valid_group_ids():
    """Validate malformed escaped payloads cannot survive as assignment IDs."""
    print("Testing group workflow assignment normalizer behavior...")

    namespace, _ = load_settings_normalizer_symbols()
    normalize_group_ids = namespace["normalize_group_workflow_allowed_group_ids"]

    first_group_id = "11111111-1111-4111-8111-111111111111"
    second_group_id = "22222222-2222-4222-8222-222222222222"
    nested_first_group_id = build_nested_json_list(first_group_id, 3)
    double_encoded_second_group_id = json.dumps(json.dumps([second_group_id.upper()]))
    malformed_escaped_blob = json.dumps([
        "not-a-group-id",
        "[" + ("\\" * 512),
        build_nested_json_list("still-not-a-guid", 2),
    ])

    normalized_ids = normalize_group_ids([
        nested_first_group_id,
        first_group_id.upper(),
        double_encoded_second_group_id,
        malformed_escaped_blob,
        "not-a-guid",
        "[" + ("\\" * 512),
    ])

    assert normalized_ids == [first_group_id, second_group_id], (
        f"Expected only canonical UUID group IDs, got {normalized_ids}"
    )
    assert all("\\" not in group_id and "[" not in group_id for group_id in normalized_ids), (
        "Escaped JSON fragments should not survive normalization"
    )

    delimited_ids = normalize_group_ids(
        f"{first_group_id}\nnot-a-group,{second_group_id};{first_group_id.upper()}"
    )
    assert delimited_ids == [first_group_id, second_group_id], (
        f"Expected delimiter parsing to preserve valid UUIDs only, got {delimited_ids}"
    )

    print("Group workflow assignment normalizer behavior verified.")


def test_assignment_settings_cleanup_is_idempotent():
    """Validate settings cleanup mutates malformed stored values once."""
    print("Testing persisted group workflow assignment cleanup...")

    namespace, _ = load_settings_normalizer_symbols()
    cleanup_settings = namespace["normalize_group_workflow_assignment_settings"]

    first_group_id = "11111111-1111-4111-8111-111111111111"
    second_group_id = "22222222-2222-4222-8222-222222222222"
    settings = {
        "group_workflow_allowed_group_ids": [
            build_nested_json_list(first_group_id, 2),
            "not-a-group-id",
            json.dumps([second_group_id]),
        ]
    }

    assert cleanup_settings(settings) is True, "Expected malformed persisted settings to be cleaned"
    assert settings["group_workflow_allowed_group_ids"] == [first_group_id, second_group_id]
    assert cleanup_settings(settings) is False, "Expected already-clean settings to be idempotent"

    print("Persisted group workflow assignment cleanup verified.")


def test_settings_and_admin_ui_wiring():
    """Validate cleanup is wired into settings persistence and admin UI parsing."""
    print("Testing group workflow assignment cleanup wiring...")

    _, settings_source = load_settings_normalizer_symbols()
    admin_js_source = read_text(ADMIN_SETTINGS_JS_PATH)
    config_source = read_text(CONFIG_PATH)

    required_settings_markers = [
        "assignment_settings_updated = normalize_group_workflow_assignment_settings(merged)",
        "normalize_group_workflow_assignment_settings(settings_item)",
    ]
    for marker in required_settings_markers:
        assert marker in settings_source, f"Missing settings cleanup marker: {marker}"

    # The cleanup only reaches Cosmos if its result is one of the reasons
    # get_settings decides to write the merged document back. Matched as a clause
    # rather than as a whole line: the condition has grown to a dozen terms across
    # as many lines, and pinning its exact text made this assertion fail for
    # formatting reasons rather than behavioural ones.
    persistence_condition = re.search(
        r"# If merging added anything new.*?\n\s*if \((?P<clauses>.*?)\n\s*\):",
        settings_source,
        re.DOTALL,
    )
    assert persistence_condition, (
        "Could not find the condition in get_settings that upserts the merged "
        "settings document; the cleanup wiring can no longer be verified."
    )
    assert "assignment_settings_updated" in persistence_condition.group("clauses"), (
        "normalize_group_workflow_assignment_settings runs, but its result is no "
        "longer one of the reasons the merged settings document is written back, so "
        "a malformed stored assignment would be cleaned in memory and never saved."
    )

    required_admin_js_markers = [
        "const GROUP_WORKFLOW_ASSIGNMENT_PARSE_DEPTH_LIMIT = 5;",
        "function collectGroupWorkflowAssignmentIds(value, depth = 0)",
        "return isGuidLike(groupId) ? groupId.toLowerCase() : '';",
        "return Array.from(new Set(collectGroupWorkflowAssignmentIds(value)));",
    ]
    for marker in required_admin_js_markers:
        assert marker in admin_js_source, f"Missing admin UI cleanup marker: {marker}"

    assert_app_version_at_least("0.241.201")

    print("Group workflow assignment cleanup wiring verified.")


def run_tests():
    """Run all group workflow assignment cleanup tests."""
    tests = [
        test_normalizer_removes_junk_and_preserves_valid_group_ids,
        test_assignment_settings_cleanup_is_idempotent,
        test_normalizers_are_re_exported_by_functions_settings,
        test_settings_and_admin_ui_wiring,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)