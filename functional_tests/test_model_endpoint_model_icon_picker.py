#!/usr/bin/env python3
"""
Functional test for model endpoint model icon picker support.
Version: 0.242.060
Implemented in: 0.242.060

This test ensures model endpoint available-model rows use the shared Bootstrap
icon search and image upload workflow instead of a raw icon class text field.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(text, expected, label):
    if expected not in text:
        raise AssertionError(f"Missing expected {label}: {expected}")


def test_shared_icon_helper_supports_scoped_controls():
    helper = read_repo_file("application/single_app/static/js/agents_common.js")

    assert_contains(helper, "export function initializeIconControls", "scoped icon control initializer")
    assert_contains(helper, "export function setIconPayload", "scoped icon payload hydration")
    assert_contains(helper, "export function getIconPayload", "scoped icon payload extraction")
    assert_contains(helper, "DEFAULT_ICON_CONTROL_SELECTORS", "default agent icon selectors")
    assert_contains(helper, "getAgentIconPayload(root)", "agent helper compatibility wrapper")


def test_model_endpoint_scripts_use_icon_picker_controls():
    admin_script = read_repo_file("application/single_app/static/js/admin/admin_model_endpoints.js")
    workspace_script = read_repo_file("application/single_app/static/js/workspace/workspace_model_endpoints.js")

    for label, script in {
        "admin model endpoints": admin_script,
        "workspace model endpoints": workspace_script,
    }.items():
        assert_contains(script, "import { getIconPayload, setIconPayload }", f"{label} shared helper import")
        assert_contains(script, "MODEL_ICON_CONTROL_CONFIG", f"{label} selector map")
        assert_contains(script, "createModelIconEditor", f"{label} model icon editor")
        assert_contains(script, "model-icon-picker-search", f"{label} Bootstrap icon search")
        assert_contains(script, "model-icon-image-file", f"{label} image upload")
        assert_contains(script, "model-icon-image-clear", f"{label} image clear")
        assert_contains(script, "data-icon-class-for", f"{label} backward-compatible icon class marker")
        assert_contains(script, "getIconPayload(iconEditor, MODEL_ICON_CONTROL_CONFIG)", f"{label} full icon payload collection")
        assert_contains(script, "setIconPayload(", f"{label} icon payload hydration")


def test_model_endpoint_icon_picker_styles_are_global():
    styles = read_repo_file("application/single_app/static/css/styles.css")

    assert_contains(styles, ".agent-icon-preview", "shared icon preview styles")
    assert_contains(styles, ".agent-icon-picker-menu", "shared icon picker menu styles")
    assert_contains(styles, ".agent-icon-picker-list", "shared icon picker list styles")
    assert_contains(styles, ".model-icon-editor .btn-group", "model icon editor layout styles")


if __name__ == "__main__":
    test_shared_icon_helper_supports_scoped_controls()
    test_model_endpoint_scripts_use_icon_picker_controls()
    test_model_endpoint_icon_picker_styles_are_global()
    print("Model endpoint model icon picker contract tests passed.")
