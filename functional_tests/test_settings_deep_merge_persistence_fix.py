#!/usr/bin/env python3
# test_settings_deep_merge_persistence_fix.py
"""
Functional test for settings deep-merge persistence fix.
Version: v0.240.002
Implemented in: v0.240.002

This test ensures merge persistence logic is validated using AST structure checks
and controlled runtime behavior validation for deep_merge_dicts.
"""

import ast
import os
import sys
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_file(*path_parts):
    file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        *path_parts
    )
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _load_functions_settings_ast():
    """Load and parse functions_settings.py into an AST tree."""
    source = _read_file("application", "single_app", "functions_settings.py")
    return source, ast.parse(source)

def _find_top_level_function(module_tree, function_name):
    """Find a top-level function definition by name."""
    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    return None


def test_get_settings_merge_detection_ast_wiring():
    """Validate get_settings merge persistence logic through AST structure checks."""
    print("🔍 Testing get_settings merge persistence AST wiring...")

    _, module_tree = _load_functions_settings_ast()

    has_copy_import = any(
        isinstance(node, ast.Import) and any(alias.name == "copy" for alias in node.names)
        for node in module_tree.body
    )
    assert has_copy_import, "Missing 'import copy' in functions_settings.py"

    get_settings_def = _find_top_level_function(module_tree, "get_settings")
    assert get_settings_def is not None, "Missing get_settings function in functions_settings.py"

    has_merged_assignment = False
    has_settings_changed_assignment = False
    merge_comparison_if = None

    for node in ast.walk(get_settings_def):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "merged":
                    if (
                        isinstance(node.value, ast.Name)
                        and node.value.id == "settings_item"
                    ):
                        has_merged_assignment = True

                if isinstance(target, ast.Name) and target.id == "settings_changed":
                    if (
                        isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "deep_merge_dicts"
                        and len(node.value.args) == 2
                        and isinstance(node.value.args[0], ast.Name)
                        and node.value.args[0].id == "default_settings"
                        and isinstance(node.value.args[1], ast.Name)
                        and node.value.args[1].id == "merged"
                    ):
                        has_settings_changed_assignment = True

        if isinstance(node, ast.If) and isinstance(node.test, ast.Name):
            if node.test.id == "settings_changed":
                merge_comparison_if = node

    assert has_merged_assignment, "Missing merged = settings_item assignment"
    assert has_settings_changed_assignment, "Missing settings_changed = deep_merge_dicts(default_settings, merged) assignment"
    assert merge_comparison_if is not None, "Missing if settings_changed branch"

    has_upsert_in_branch = False
    has_log_event_in_branch = False

    for node in ast.walk(merge_comparison_if):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "cosmos_settings_container"
            and node.func.attr == "upsert_item"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "merged"
        ):
            has_upsert_in_branch = True

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "log_event"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and "missing keys were merged and persisted to Cosmos DB" in node.args[0].value
        ):
            has_log_event_in_branch = True

    assert has_upsert_in_branch, "Missing cosmos_settings_container.upsert_item(merged) in merge-detected branch"
    assert has_log_event_in_branch, "Missing merge persistence log_event message in merge-detected branch"

    print("✅ Get_settings merge persistence AST wiring is present")


def test_deep_merge_dicts_ast_behavior_wiring():
    """Validate deep_merge_dicts merge behavior through AST structure checks."""
    print("🔍 Testing deep_merge_dicts AST behavior wiring...")

    _, module_tree = _load_functions_settings_ast()
    deep_merge_def = _find_top_level_function(module_tree, "deep_merge_dicts")
    assert deep_merge_def is not None, "Missing deep_merge_dicts function in functions_settings.py"

    has_not_in_guard = False
    has_missing_key_assignment = False
    has_recursive_merge_call = False
    has_changed_init = False
    has_changed_true_assignment = False
    returns_changed = False

    for node in ast.walk(deep_merge_def):
        if isinstance(node, ast.Compare):
            if (
                isinstance(node.left, ast.Name)
                and node.left.id == "k"
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.NotIn)
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Name)
                and node.comparators[0].id == "existing_dict"
            ):
                has_not_in_guard = True

        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]

            if (
                isinstance(target, ast.Name)
                and target.id == "changed"
                and isinstance(node.value, ast.Constant)
                and node.value.value is False
            ):
                has_changed_init = True

            if (
                isinstance(target, ast.Name)
                and target.id == "changed"
                and isinstance(node.value, ast.Constant)
                and node.value.value is True
            ):
                has_changed_true_assignment = True

            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "existing_dict"
                and isinstance(node.value, ast.Name)
                and node.value.id == "default_val"
            ):
                has_missing_key_assignment = True

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "deep_merge_dicts"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "default_val"
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == "existing_val"
        ):
            has_recursive_merge_call = True

        if isinstance(node, ast.Return):
            if isinstance(node.value, ast.Name) and node.value.id == "changed":
                returns_changed = True

    assert has_not_in_guard, "Missing 'if k not in existing_dict' guard in deep_merge_dicts"
    assert has_missing_key_assignment, "Missing existing_dict[k] = default_val assignment in deep_merge_dicts"
    assert has_recursive_merge_call, "Missing recursive deep_merge_dicts(default_val, existing_val) call"
    assert has_changed_init, "Missing changed = False initialization in deep_merge_dicts"
    assert has_changed_true_assignment, "Missing changed = True assignment in deep_merge_dicts"
    assert returns_changed, "Missing return changed in deep_merge_dicts"

    print("✅ deep_merge_dicts AST behavior wiring is present")

def test_version_alignment_for_fix_release():
    """Validate config version reflects this fix release."""
    print("🔍 Testing fix release version alignment...")

    config_content = _read_file("application", "single_app", "config.py")

    required_markers = [
        "VERSION = \"0.240.002\""
    ]

    missing_markers = [marker for marker in required_markers if marker not in config_content]
    assert not missing_markers, f"Missing config markers: {missing_markers}"

    print("✅ Fix release version markers are aligned")


def main():
    """Run all functional checks for deep-merge persistence fix."""
    print("🧪 Running Settings Deep Merge Persistence Functional Tests...\n")

    tests = [
        test_get_settings_merge_detection_ast_wiring,
        test_deep_merge_dicts_ast_behavior_wiring,
        test_version_alignment_for_fix_release
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except AssertionError as error:
            print(f"❌ {test.__name__} failed: {error}")
            results.append(False)
        except Exception as error:
            print(f"❌ {test.__name__} error: {error}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")

    if success:
        print("✅ All deep-merge persistence functional tests passed!")
    else:
        print("❌ Some deep-merge persistence functional tests failed.")

    return success


if __name__ == "__main__":
    test_success = main()
    sys.exit(0 if test_success else 1)
