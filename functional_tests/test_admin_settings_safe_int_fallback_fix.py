#!/usr/bin/env python3
"""
Functional test for admin safe_int fallback hardening.
Version: 0.239.006
Implemented in: 0.239.006

This test ensures admin settings integer parsing always returns ints,
including when persisted fallback values are malformed.
"""

import ast
import os
import sys
import traceback

ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")

if APP_DIR not in sys.path:
    sys.path.append(APP_DIR)

from admin_settings_int_utils import safe_int, safe_int_with_source


def _read_file(*path_parts):
    file_path = os.path.join(
        ROOT_DIR,
        *path_parts
    )
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _parse_python_file(*path_parts):
    """Read and parse a Python source file into AST."""
    source = _read_file(*path_parts)
    return source, ast.parse(source)


def _find_top_level_function(module_tree, function_name):
    """Find a top-level function definition by name."""
    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    return None


def _find_nested_function(parent_function, function_name):
    """Find a nested function definition by name in a parent function body."""
    for node in parent_function.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    return None


def test_safe_int_behavior_with_malformed_values():
    """Validate helper behavior for raw, fallback, and hard-default parsing paths."""
    print("🔍 Testing admin safe_int helper behavior...")

    behavior_cases = [
        ("42", "30", 0, 42),
        ("abc", "30", 0, 30),
        (None, "28", 0, 28),
        ("bad", "still_bad", 17, 17),
        ("-5", "10", 3, -5)
    ]

    for raw_value, fallback_value, hard_default, expected in behavior_cases:
        parsed_value = safe_int(raw_value, fallback_value, hard_default)
        assert isinstance(parsed_value, int), (
            f"safe_int should always return int; got {type(parsed_value).__name__} "
            f"for raw={raw_value}, fallback={fallback_value}, hard_default={hard_default}"
        )
        assert parsed_value == expected, (
            f"Unexpected safe_int result for raw={raw_value}, fallback={fallback_value}, hard_default={hard_default}. "
            f"Expected {expected}, got {parsed_value}"
        )

    parsed_value, parse_source = safe_int_with_source("9", "30", 0)
    assert parsed_value == 9 and parse_source == "raw", "Expected raw parse source for valid raw input"

    parsed_value, parse_source = safe_int_with_source("bad", "30", 0)
    assert parsed_value == 30 and parse_source == "fallback", "Expected fallback parse source when raw input is invalid"

    parsed_value, parse_source = safe_int_with_source("bad", "still_bad", 11)
    assert parsed_value == 11 and parse_source == "hard_default", "Expected hard_default parse source when raw and fallback are invalid"

    print("✅ Admin safe_int helper behavior is valid")


def test_route_wiring_uses_module_safe_int_helper():
    """Validate admin settings route uses extracted module helper for integer parsing."""
    print("🔍 Testing admin route wiring for extracted safe_int helper...")

    _, route_tree = _parse_python_file("application", "single_app", "route_frontend_admin_settings.py")

    has_helper_import = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "admin_settings_int_utils"
        and any(alias.name == "safe_int_with_source" for alias in node.names)
        for node in route_tree.body
    )
    assert has_helper_import, "Missing 'from admin_settings_int_utils import safe_int_with_source' import"

    register_route_def = _find_top_level_function(route_tree, "register_route_frontend_admin_settings")
    assert register_route_def is not None, "Missing register_route_frontend_admin_settings function"

    admin_settings_def = _find_nested_function(register_route_def, "admin_settings")
    assert admin_settings_def is not None, "Missing nested admin_settings route function"

    has_legacy_nested_safe_int = any(
        isinstance(node, ast.FunctionDef) and node.name == "safe_int"
        for node in ast.walk(admin_settings_def)
    )
    assert not has_legacy_nested_safe_int, "Legacy nested safe_int function should be removed after extraction"

    has_parse_admin_int = any(
        isinstance(node, ast.FunctionDef) and node.name == "parse_admin_int"
        for node in ast.walk(admin_settings_def)
    )
    assert has_parse_admin_int, "Missing parse_admin_int wrapper for route logging and helper usage"

    has_safe_int_with_source_call = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "safe_int_with_source"
        for node in ast.walk(admin_settings_def)
    )
    assert has_safe_int_with_source_call, "Missing safe_int_with_source helper call in admin settings route"

    parse_admin_int_calls = [
        node for node in ast.walk(admin_settings_def)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "parse_admin_int"
    ]
    assert len(parse_admin_int_calls) >= 2, "Expected parse_admin_int usage for idle timeout and warning fields"

    print("✅ Admin route wiring for extracted safe_int helper is present")


def test_version_alignment_for_safe_int_fix():
    """Validate config version aligns with safe_int fix release."""
    print("🔍 Testing version alignment for safe_int fallback fix...")

    config_content = _read_file("application", "single_app", "config.py")

    required_markers = [
        "VERSION = \"0.239.006\""
    ]

    missing_markers = [marker for marker in required_markers if marker not in config_content]
    assert not missing_markers, f"Missing config markers: {missing_markers}"

    print("✅ Safe_int fix release version markers are aligned")


def main():
    """Run all safe_int fallback hardening functional checks."""
    print("🧪 Running Admin Safe Int Fallback Functional Tests...\n")

    tests = [
        test_safe_int_behavior_with_malformed_values,
        test_route_wiring_uses_module_safe_int_helper,
        test_version_alignment_for_safe_int_fix
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
        print("✅ All admin safe_int fallback functional tests passed!")
    else:
        print("❌ Some admin safe_int fallback functional tests failed.")

    return success


if __name__ == "__main__":
    test_success = main()
    sys.exit(0 if test_success else 1)
