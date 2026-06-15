#!/usr/bin/env python3
# test_group_workflow_assignment_cleanup_fix.py
"""
Functional test for group workflow assignment cleanup.
Version: 0.241.201
Implemented in: 0.241.201

This test ensures malformed nested JSON strings cannot be persisted as group
workflow assignment IDs and that valid group UUIDs are preserved.
"""

import ast
import json
import sys
import traceback
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_SETTINGS_PATH = REPO_ROOT / "application" / "single_app" / "functions_settings.py"
ADMIN_SETTINGS_JS_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"


def read_text(path):
    """Read a repository file."""
    return path.read_text(encoding="utf-8")


def load_settings_normalizer_symbols():
    """Load the pure group workflow assignment normalizer symbols from functions_settings.py."""
    source = read_text(FUNCTIONS_SETTINGS_PATH)
    module_tree = ast.parse(source)
    required_names = {
        "GROUP_WORKFLOW_ALLOWED_GROUP_ID_PARSE_DEPTH_LIMIT",
        "_iter_group_workflow_allowed_group_id_candidates",
        "normalize_group_workflow_allowed_group_id",
        "normalize_group_workflow_allowed_group_ids",
        "normalize_group_workflow_assignment_settings",
    }
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

    missing_names = [
        name for name in required_names
        if name not in {
            getattr(node, "name", None)
            for node in selected_nodes
        } and name not in {
            target.id
            for node in selected_nodes
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
    ]
    assert not missing_names, f"Missing expected normalizer symbols: {missing_names}"

    normalizer_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(normalizer_module)

    namespace = {
        "json": json,
        "uuid": uuid,
    }
    exec(compile(normalizer_module, str(FUNCTIONS_SETTINGS_PATH), "exec"), namespace)
    return namespace, source


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
        "if merge_changed or migration_updated or assignment_settings_updated:",
        "normalize_group_workflow_assignment_settings(settings_item)",
    ]
    for marker in required_settings_markers:
        assert marker in settings_source, f"Missing settings cleanup marker: {marker}"

    required_admin_js_markers = [
        "const GROUP_WORKFLOW_ASSIGNMENT_PARSE_DEPTH_LIMIT = 5;",
        "function collectGroupWorkflowAssignmentIds(value, depth = 0)",
        "return isGuidLike(groupId) ? groupId.toLowerCase() : '';",
        "return Array.from(new Set(collectGroupWorkflowAssignmentIds(value)));",
    ]
    for marker in required_admin_js_markers:
        assert marker in admin_js_source, f"Missing admin UI cleanup marker: {marker}"

    assert 'VERSION = "0.241.201"' in config_source, "Expected config.py version 0.241.201"

    print("Group workflow assignment cleanup wiring verified.")


def run_tests():
    """Run all group workflow assignment cleanup tests."""
    tests = [
        test_normalizer_removes_junk_and_preserves_valid_group_ids,
        test_assignment_settings_cleanup_is_idempotent,
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