# test_tabular_execution_settings_sanitization.py
#!/usr/bin/env python3
"""
Functional test for admin-only tabular execution settings sanitization.
Version: 0.250.168
Implemented in: 0.250.168

This test ensures normal frontend settings responses omit admin-only tabular
execution controls while retaining the confirmation fields required by chat.
"""

import ast
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT_DIR / "application" / "single_app" / "functions_settings.py"
IMPLEMENTED_VERSION = "0.250.168"

ADMIN_ONLY_TABULAR_SETTINGS = {
    "enable_tabular_hierarchical_analysis": True,
    "tabular_hierarchical_analysis_reduce_fan_in": 10,
    "tabular_generated_output_chunk_model_mode": "configured",
    "tabular_generated_output_chunk_model_deployment": "internal-chunk-deployment",
    "tabular_generated_output_model_validation_auto_retries": 7,
}

CHAT_CONFIRMATION_SETTINGS = {
    "enable_tabular_durable_run_confirmation": True,
    "tabular_durable_run_confirmation_threshold_rows": 750,
    "tabular_durable_run_confirmation_threshold_batches": 100,
}


def load_sanitize_settings_for_user():
    """Load the sanitizer without importing the full Flask application."""
    source = SETTINGS_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SETTINGS_FILE))
    selected_nodes = []

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TABULAR_GENERATION_BACKEND_SETTING_KEYS":
                    selected_nodes.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "sanitize_settings_for_user":
            selected_nodes.append(node)

    namespace = {
        "sanitize_model_endpoints_for_frontend": lambda endpoints: list(endpoints or []),
        "normalize_support_latest_features_visibility": lambda visibility: {},
        "has_visible_support_latest_features": lambda settings: False,
        "get_public_workspace_label_context": lambda settings: {},
    }
    exec(
        compile(ast.Module(body=selected_nodes, type_ignores=[]), str(SETTINGS_FILE), "exec"),
        namespace,
    )
    return namespace["sanitize_settings_for_user"]


def test_admin_only_tabular_execution_settings_are_sanitized():
    """Backend execution controls must not reach normal frontend settings."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    sanitize_settings_for_user = load_sanitize_settings_for_user()
    raw_settings = {
        "app_title": "SimpleChat",
        **ADMIN_ONLY_TABULAR_SETTINGS,
        **CHAT_CONFIRMATION_SETTINGS,
    }

    sanitized = sanitize_settings_for_user(raw_settings)

    assert sanitized["app_title"] == "SimpleChat"
    for setting_key in ADMIN_ONLY_TABULAR_SETTINGS:
        assert setting_key not in sanitized, f"{setting_key} must remain backend-only"
    for setting_key, expected_value in CHAT_CONFIRMATION_SETTINGS.items():
        assert sanitized[setting_key] == expected_value, f"{setting_key} is required by chat"


if __name__ == "__main__":
    test_admin_only_tabular_execution_settings_are_sanitized()
    print("Tabular execution settings sanitization test passed.")
