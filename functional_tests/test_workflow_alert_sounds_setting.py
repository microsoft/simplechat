#!/usr/bin/env python3
# test_workflow_alert_sounds_setting.py
"""
Functional test for the workflow alert sounds admin setting.
Version: 0.261.234
Implemented in: 0.261.234

This test ensures that the app-wide workflow alert sound gate defaults on,
appears in both admin setting surfaces, reaches the V2 bootstrap contract, and
is safe to expose through sanitized settings.
"""

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui" / "src"

SETTINGS_KEY = "enable_workflow_alert_sounds"
WORKFLOW_SECTION = "workflow-settings-section"

FUNCTIONS_SETTINGS = APP_DIR / "functions_settings.py"
ADMIN_WORKFLOW_PANE = APP_DIR / "templates" / "admin" / "_panes" / "workflow.html"
ADMIN_ROUTE = APP_DIR / "route_frontend_admin_settings.py"
V2_ROUTE = APP_DIR / "route_backend_v2.py"
V2_TYPES = V2_DIR / "lib" / "types.ts"


def read_text(path):
    """Read a repository source file as UTF-8."""
    return path.read_text(encoding="utf-8")


def default_settings_value(key):
    """Return a literal value from the ``get_settings`` default settings dict."""
    tree = ast.parse(read_text(FUNCTIONS_SETTINGS))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "get_settings":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "default_settings"
                for target in child.targets
            ):
                continue
            for key_node, value_node in zip(child.value.keys, child.value.values):
                if isinstance(key_node, ast.Constant) and key_node.value == key:
                    return ast.literal_eval(value_node)
    raise AssertionError(f"{key} was not found in get_settings defaults.")


def load_sanitize_settings_for_user():
    """Load just ``sanitize_settings_for_user`` without importing Azure setup."""
    tree = ast.parse(read_text(FUNCTIONS_SETTINGS))
    function_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "sanitize_settings_for_user"
    )
    namespace = {
        "TABULAR_GENERATION_BACKEND_SETTING_KEYS": set(),
        "sanitize_model_endpoints_for_frontend": lambda endpoints, include_connection_details=False: endpoints,
        "normalize_support_latest_features_visibility": lambda value: value or {},
        "has_visible_support_latest_features": lambda settings: False,
        "get_public_workspace_label_context": lambda settings: {},
    }
    module = ast.Module(body=[function_node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(FUNCTIONS_SETTINGS), "exec"), namespace)
    return namespace["sanitize_settings_for_user"]


def test_default_setting_is_true():
    """The settings document default keeps workflow alert sounds enabled."""
    assert default_settings_value(SETTINGS_KEY) is True
    source = read_text(FUNCTIONS_SETTINGS)
    assert f"'{SETTINGS_KEY}': True" in source
    assert f"'{SETTINGS_KEY}': new_settings['{SETTINGS_KEY}'] is not False" in source
    return True


def test_admin_field_registry_has_workflow_switch():
    """The V2 admin registry exposes the switch in the Workflow section."""
    fields = import_app_module("admin_settings_fields")
    workflow_fields = fields.get_admin_settings_fields()[WORKFLOW_SECTION]
    field = next((entry for entry in workflow_fields if entry.get("key") == SETTINGS_KEY), None)

    assert field is not None
    assert field["type"] == "switch"
    assert field["label"] == "Enable Workflow Alert Sounds"
    assert field["default"] is True
    assert "repeat it until someone acknowledges the alert" in field["help"]

    normalized, errors, _warnings = fields.normalize_admin_settings_updates(
        {SETTINGS_KEY: False},
        {SETTINGS_KEY: True},
    )
    assert errors == {}
    assert normalized[SETTINGS_KEY] is False
    return True


def test_classic_admin_pane_contains_toggle():
    """The classic Workflow pane submits the same setting."""
    source = read_text(ADMIN_WORKFLOW_PANE)
    assert f'id="{SETTINGS_KEY}"' in source
    assert f'name="{SETTINGS_KEY}"' in source
    assert f"settings.{SETTINGS_KEY}" in source
    assert "Enable Workflow Alert Sounds" in source
    assert "silences every workflow alert sound for everyone" in source
    return True


def test_admin_route_defaults_and_parses_form_value():
    """The classic admin route fills missing settings and parses posted forms."""
    source = read_text(ADMIN_ROUTE)
    assert f"if '{SETTINGS_KEY}' not in settings:" in source
    assert f"settings['{SETTINGS_KEY}'] = True" in source
    assert f"'{SETTINGS_KEY}': form_data.get('{SETTINGS_KEY}') == 'on'" in source
    return True


def test_v2_bootstrap_exposes_feature_flag_and_type():
    """The V2 bootstrap payload carries the feature and TypeScript type."""
    route_source = read_text(V2_ROUTE)
    type_source = read_text(V2_TYPES)

    assert f'"{SETTINGS_KEY}": (' in route_source
    assert f'settings.get("{SETTINGS_KEY}", True) is not False' in route_source
    assert "interface BootstrapFeatures extends Record<string, boolean | undefined>" in type_source
    assert f"{SETTINGS_KEY}?: boolean;" in type_source
    return True


def test_sanitized_settings_keep_non_secret_flag():
    """Sanitization strips secret-looking keys but keeps the workflow sound flag."""
    sanitize_settings_for_user = load_sanitize_settings_for_user()

    sanitized = sanitize_settings_for_user(
        {
            SETTINGS_KEY: False,
            "azure_openai_key": "secret-value",
            "nested": {SETTINGS_KEY: True, "client_secret": "hidden"},
        }
    )

    assert sanitized[SETTINGS_KEY] is False
    assert "azure_openai_key" not in sanitized
    assert sanitized["nested"][SETTINGS_KEY] is True
    assert "client_secret" not in sanitized["nested"]
    return True


def main():
    """Run all workflow alert sound setting checks."""
    tests = [
        test_default_setting_is_true,
        test_admin_field_registry_has_workflow_switch,
        test_classic_admin_pane_contains_toggle,
        test_admin_route_defaults_and_parses_form_value,
        test_v2_bootstrap_exposes_feature_flag_and_type,
        test_sanitized_settings_keep_non_secret_flag,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"Passed: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
