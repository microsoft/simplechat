#!/usr/bin/env python3
"""
Functional test for configurable Public Workspace end-user display names.
Version: 0.250.110
Implemented in: 0.250.110

This test ensures that Public Workspace display-name settings are normalized,
derived labels are safe for frontend use, and only the raw setting is persisted.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SETTINGS_HELPER = os.path.join(REPO_ROOT, "application", "single_app", "functions_settings.py")
ADMIN_ROUTE = os.path.join(REPO_ROOT, "application", "single_app", "route_frontend_admin_settings.py")
ADMIN_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "admin_settings.html")
BASE_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "base.html")


def read_source(path):
    with open(path, "r", encoding="utf-8") as source_file:
        return source_file.read()


def assert_contains(source, needle, description):
    if needle not in source:
        raise AssertionError(f"Missing {description}: {needle}")


def load_display_name_helpers():
    """Load only the display-name helper definitions from functions_settings.py."""
    source = read_source(SETTINGS_HELPER)
    tree = ast.parse(source, filename=SETTINGS_HELPER)
    names_to_load = {
        "PUBLIC_WORKSPACE_DISPLAY_NAME_DEFAULT",
        "PUBLIC_WORKSPACE_DISPLAY_NAME_PLURAL_DEFAULT",
        "PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH",
        "normalize_public_workspace_display_name",
        "get_public_workspace_label_context",
        "normalize_public_workspace_display_settings",
        "attach_public_workspace_label_context",
    }
    selected_nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names_to_load for target in node.targets)
        )
        or (
            isinstance(node, ast.FunctionDef)
            and node.name in names_to_load
        )
    ]
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, SETTINGS_HELPER, "exec"), namespace)
    return namespace


def test_display_name_normalization():
    """Validate display-name normalization and default/custom label derivation."""
    print("Testing Public Workspace display-name normalization...")
    helpers = load_display_name_helpers()
    normalize = helpers["normalize_public_workspace_display_name"]
    get_context = helpers["get_public_workspace_label_context"]

    assert normalize("  Domain\n Knowledge   ") == "Domain Knowledge"
    long_value = "A" * 40
    assert normalize(long_value) == "A" * 32

    default_context = get_context({})
    assert default_context["singular"] == "Public Workspace"
    assert default_context["plural"] == "Public Workspaces"
    assert default_context["lower_singular"] == "public workspace"
    assert default_context["lower_plural"] == "public workspaces"
    assert default_context["short"] == "Public"
    assert default_context["is_custom"] is False
    assert default_context["max_length"] == 32

    custom_context = get_context({"public_workspace_display_name": "Domain Knowledge"})
    assert custom_context["singular"] == "Domain Knowledge"
    assert custom_context["plural"] == "Domain Knowledge"
    assert custom_context["lower_singular"] == "Domain Knowledge"
    assert custom_context["lower_plural"] == "Domain Knowledge"
    assert custom_context["short"] == "Domain Knowledge"
    assert custom_context["is_custom"] is True
    print("Display-name normalization passed.")
    return True


def test_display_name_persistence_shape():
    """Validate derived labels are attached for reads but removed before persistence."""
    print("Testing Public Workspace display-name persistence shape...")
    helpers = load_display_name_helpers()
    normalize_settings = helpers["normalize_public_workspace_display_settings"]
    attach_labels = helpers["attach_public_workspace_label_context"]

    settings = {
        "public_workspace_display_name": "  Domain\n Knowledge  ",
        "public_workspace_labels": {"singular": "stale"},
    }
    changed = normalize_settings(settings)
    assert changed is True
    assert settings["public_workspace_display_name"] == "Domain Knowledge"
    assert "public_workspace_labels" not in settings

    attach_labels(settings)
    assert settings["public_workspace_labels"]["singular"] == "Domain Knowledge"
    assert settings["public_workspace_labels"]["max_length"] == 32

    changed_again = normalize_settings(settings)
    assert changed_again is True
    assert "public_workspace_labels" not in settings
    assert normalize_settings(settings) is False
    print("Display-name persistence shape passed.")
    return True


def test_admin_and_frontend_wiring():
    """Validate Admin Settings and frontend sanitized-label wiring."""
    print("Testing Public Workspace display-name wiring...")
    settings_source = read_source(SETTINGS_HELPER)
    admin_route_source = read_source(ADMIN_ROUTE)
    admin_template_source = read_source(ADMIN_TEMPLATE)
    base_template_source = read_source(BASE_TEMPLATE)

    assert_contains(
        settings_source,
        "'public_workspace_display_name': ''",
        "default display-name setting",
    )
    assert_contains(
        settings_source,
        "sanitized['public_workspace_labels'] = get_public_workspace_label_context(full_settings)",
        "sanitized frontend labels",
    )
    assert_contains(
        admin_route_source,
        "public_workspace_display_name = normalize_public_workspace_display_name(",
        "admin route normalization",
    )
    assert_contains(
        admin_route_source,
        "'public_workspace_display_name': public_workspace_display_name",
        "admin route persistence",
    )
    assert_contains(
        admin_template_source,
        'id="public_workspace_display_name"',
        "admin display-name field",
    )
    assert_contains(
        admin_template_source,
        'maxlength="{{ settings.public_workspace_labels.max_length }}"',
        "admin 32-character maxlength binding",
    )
    assert_contains(
        base_template_source,
        "window.publicWorkspaceLabels = {{ app_settings.public_workspace_labels | default({}) | tojson }};",
        "global label JSON",
    )
    assert_contains(
        base_template_source,
        "window.getPublicWorkspaceLabel = function(key)",
        "global label accessor",
    )
    print("Display-name wiring passed.")
    return True


def main():
    """Run all Public Workspace display-name settings checks."""
    tests = [
        test_display_name_normalization,
        test_display_name_persistence_shape,
        test_admin_and_frontend_wiring,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    test_success = main()
    sys.exit(0 if test_success else 1)
