# test_settings_deep_merge_persistence_fix.py
"""
Settings default merging and safe persistence regression checks.
Version: 0.261.025
Implemented in: 0.240.002
Updated for conditional shared-settings writes in: 0.261.025
"""

import ast
import copy
from pathlib import Path
import sys

from test_support.versioning import assert_app_version_at_least


SOURCE_PATH = Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_settings.py"


def _load_functions_settings_ast():
    source = SOURCE_PATH.read_text(encoding="utf-8-sig")
    return source, ast.parse(source)


def _find_top_level_function(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def test_get_settings_merge_detection_ast_wiring():
    """Read normalization must not blindly upsert its earlier snapshot."""
    _, tree = _load_functions_settings_ast()
    getter = _find_top_level_function(tree, "get_settings")
    calls = [node for node in ast.walk(getter) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "write"
        and call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "normalize_loaded_settings"
        for call in calls
    )
    assert not any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "upsert_item"
        for call in calls
    )
    assert any(
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "merged"
        and isinstance(node.ops[0], ast.NotEq)
        for node in ast.walk(getter)
    )


def test_deep_merge_dicts_ast_behavior_wiring():
    """Defaults are added recursively without overwriting explicit saved values."""
    _, tree = _load_functions_settings_ast()
    definition = _find_top_level_function(tree, "deep_merge_dicts")
    namespace = {"copy": copy}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(SOURCE_PATH), "exec"), namespace)
    merge = namespace["deep_merge_dicts"]
    settings = {"enabled": False, "nested": {"user_choice": "saved"}}
    defaults = {"enabled": True, "nested": {"user_choice": "default", "new_key": 1}}
    assert merge(defaults, settings) is True
    assert settings == {"enabled": False, "nested": {"user_choice": "saved", "new_key": 1}}
    assert merge(defaults, settings) is False


def test_version_alignment_for_fix_release():
    assert_app_version_at_least("0.261.025")


if __name__ == "__main__":
    test_get_settings_merge_detection_ast_wiring()
    test_deep_merge_dicts_ast_behavior_wiring()
    test_version_alignment_for_fix_release()
    sys.exit(0)
