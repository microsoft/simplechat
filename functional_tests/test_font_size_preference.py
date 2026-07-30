#!/usr/bin/env python3
"""
Functional test for the global font size preference.
Version: 0.250.073
Implemented in: 0.250.073

This test ensures that supported font size values are normalized, persisted
through the user settings contract, and mapped to controlled global CSS.
"""

import ast
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_repo_file(*parts):
    file_path = os.path.join(REPO_ROOT, *parts)
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _load_font_size_contract():
    settings_source = _read_repo_file(
        "application",
        "single_app",
        "functions_settings.py",
    )
    settings_tree = ast.parse(settings_source)
    selected_nodes = []
    target_names = {
        "FONT_SIZE_PREFERENCES",
        "DEFAULT_FONT_SIZE_PREFERENCE",
    }

    for node in settings_tree.body:
        if isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assigned_names & target_names:
                selected_nodes.append(node)
        elif (
            isinstance(node, ast.FunctionDef)
            and node.name == "normalize_font_size_preference"
        ):
            selected_nodes.append(node)

    namespace = {}
    contract_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(contract_module, "functions_settings.py", "exec"), namespace)
    return namespace


def test_font_size_normalization_contract():
    """Validate supported values and safe fallback behavior."""
    contract = _load_font_size_contract()
    normalize = contract["normalize_font_size_preference"]

    assert contract["FONT_SIZE_PREFERENCES"] == ("xs", "s", "m", "l", "xl")
    assert contract["DEFAULT_FONT_SIZE_PREFERENCE"] == "m"
    assert normalize(" XL ") == "xl"
    assert normalize("unsupported") == "m"
    assert normalize(None) == "m"


def test_font_size_api_and_render_contract():
    """Validate API allowlisting, strict validation, and controlled CSS mappings."""
    route_source = _read_repo_file(
        "application",
        "single_app",
        "route_backend_users.py",
    )
    base_template = _read_repo_file(
        "application",
        "single_app",
        "templates",
        "base.html",
    )
    profile_template = _read_repo_file(
        "application",
        "single_app",
        "templates",
        "profile.html",
    )
    styles_source = _read_repo_file(
        "application",
        "single_app",
        "static",
        "css",
        "styles.css",
    )

    assert "'fontSizePreference'" in route_source
    assert "font_size_preference not in FONT_SIZE_PREFERENCES" in route_source
    assert "Invalid font size preference" in route_source
    assert 'data-font-size="{{ saved_font_size_preference' in base_template
    assert 'name="font-size-preference"' in profile_template
    assert "saveFontSizePreference" in profile_template

    expected_mappings = {
        "xs": "75%",
        "s": "87.5%",
        "m": "100%",
        "l": "150%",
        "xl": "200%",
    }
    for preference, percentage in expected_mappings.items():
        selector = f'html[data-font-size="{preference}"]'
        assert selector in styles_source
        selector_block = styles_source.split(selector, 1)[1].split("}", 1)[0]
        assert f"font-size: {percentage};" in selector_block


if __name__ == "__main__":
    tests = [
        test_font_size_normalization_contract,
        test_font_size_api_and_render_contract,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            results.append(True)
            print("PASS")
        except Exception as exc:
            results.append(False)
            print(f"FAIL: {exc}")

    sys.exit(0 if all(results) else 1)
