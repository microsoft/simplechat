# test_action_editor_configuration_cleanup_static.py
#!/usr/bin/env python3
"""
Functional test for V2 action editor configuration cleanup.
Version: 0.261.276
Implemented in: 0.261.276

This test statically validates that unknown schema fields are preserved for
Advanced JSON instead of rendered as removable custom fields, connection checks
live in Authentication, and internal Yamcs/Log Analytics settings are covered.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_SCHEMA_FIELDS = REPO_ROOT / "application" / "v2_ui" / "src" / "components" / "workspaceActions" / "ActionSchemaFields.tsx"
ACTION_CONFIGURATION_FIELDS = REPO_ROOT / "application" / "v2_ui" / "src" / "components" / "workspaceActions" / "ActionConfigurationFields.tsx"
ACTION_AUTHENTICATION = REPO_ROOT / "application" / "v2_ui" / "src" / "components" / "workspaceActions" / "ActionAuthentication.tsx"
ACTION_CONNECTION_CHECK = REPO_ROOT / "application" / "v2_ui" / "src" / "components" / "workspaceActions" / "ActionConnectionCheck.tsx"
ACTION_EDITOR_PAGE = REPO_ROOT / "application" / "v2_ui" / "src" / "pages" / "workspace" / "ActionEditorPage.tsx"


def test_custom_schema_fields_are_not_rendered_or_removed():
    source = ACTION_SCHEMA_FIELDS.read_text(encoding="utf-8")
    assert "function ActionAddCustomField" not in source
    assert "Remove field" not in source
    assert "known.startsWith(`${pointer}/`)" in source


def test_connection_check_moved_to_authentication():
    configuration_source = ACTION_CONFIGURATION_FIELDS.read_text(encoding="utf-8")
    authentication_source = ACTION_AUTHENTICATION.read_text(encoding="utf-8")
    connection_source = ACTION_CONNECTION_CHECK.read_text(encoding="utf-8")
    assert "Connection check" not in configuration_source
    assert "<ActionConnectionCheck props={props} definition={definition}" in authentication_source
    assert "title=\"Connection check\"" in connection_source
    assert "title=\"Validate and test\"" in connection_source


def test_internal_configuration_fields_are_covered():
    configuration_source = ACTION_CONFIGURATION_FIELDS.read_text(encoding="utf-8")
    for hidden_path in (
        "/additionalFields/query_history",
        "/additionalFields/enable_basic_auth",
        "/additionalFields/basic_auth_username",
        "/additionalFields/basic_auth_password",
        "/additionalFields/basic_auth_identity_id",
    ):
        assert hidden_path in configuration_source


def test_empty_configuration_and_hidden_picker_paths():
    editor_source = ACTION_EDITOR_PAGE.read_text(encoding="utf-8")
    assert "hasActionConfigurationFields" in editor_source
    assert "!type.hidden && !type.legacy" in editor_source
    assert "current settings for this action type will be cleared" in editor_source


if __name__ == "__main__":
    test_custom_schema_fields_are_not_rendered_or_removed()
    test_connection_check_moved_to_authentication()
    test_internal_configuration_fields_are_covered()
    test_empty_configuration_and_hidden_picker_paths()
    print("Action editor cleanup checks passed.")
