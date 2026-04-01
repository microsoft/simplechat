#!/usr/bin/env python3
"""
Functional test for public prompt visibility and prompt editor dark mode.
Version: 0.239.199
Implemented in: 0.239.196

This test ensures that public workspace prompts are loaded from the correct
public scope with legacy fallback support, and that the SimpleMDE prompt editor
uses the shared dark-mode overrides and visible toolbar icon mappings.
"""

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]


def assert_contains(text, snippets, label):
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        raise AssertionError(f"Missing {label}: {missing}")


def test_public_prompt_backend_uses_public_workspace_scope():
    route_text = (ROOT_DIR / "application/single_app/route_backend_public_prompts.py").read_text(encoding="utf-8")
    assert_contains(
        route_text,
        [
            "public_workspace_id=active_ws",
            "prompt_type='public_prompt'",
        ],
        "public prompt route scope wiring",
    )
    if "group_id=active_ws" in route_text:
        raise AssertionError("Public prompt routes still reference group_id=active_ws")


def test_public_prompt_helper_has_legacy_fallback_support():
    prompts_text = (ROOT_DIR / "application/single_app/functions_prompts.py").read_text(encoding="utf-8")
    assert_contains(
        prompts_text,
        [
            "def _get_public_prompt_items(prompt_type, public_workspace_id):",
            "cosmos_public_prompts_container",
            "cosmos_group_prompts_container",
            "c.public_id = @id_value",
            "c.group_id = @id_value",
            "count_public_prompts_for_workspace",
        ],
        "public prompt fallback helpers",
    )


def test_public_prompt_count_route_uses_shared_counter():
    route_text = (ROOT_DIR / "application/single_app/route_backend_public_workspaces.py").read_text(encoding="utf-8")
    assert_contains(
        route_text,
        [
            "from functions_prompts import count_public_prompts_for_workspace",
            "prompt_count = count_public_prompts_for_workspace(ws_id)",
        ],
        "public prompt count wiring",
    )


def test_simplemde_overrides_are_loaded_from_base_template():
    base_text = (ROOT_DIR / "application/single_app/templates/base.html").read_text(encoding="utf-8")
    assert_contains(
        base_text,
        [
            "css/simplemde-overrides.css",
        ],
        "SimpleMDE override stylesheet include",
    )


def test_simplemde_override_styles_cover_icons_and_dark_mode():
    css_text = (ROOT_DIR / "application/single_app/static/css/simplemde-overrides.css").read_text(encoding="utf-8")
    assert_contains(
        css_text,
        [
            '.editor-toolbar a.fa::before',
            '.editor-toolbar a.fa-bold::before',
            '.editor-toolbar a.fa-picture-o::before',
            '[data-bs-theme="dark"] .CodeMirror',
            '[data-bs-theme="dark"] .editor-toolbar',
        ],
        "SimpleMDE override rules",
    )


def test_config_version_is_bumped_for_follow_up_fix():
    config_text = (ROOT_DIR / "application/single_app/config.py").read_text(encoding="utf-8")
    assert_contains(config_text, ['VERSION = "0.239.199"'], "config version")


if __name__ == "__main__":
    tests = [
        test_public_prompt_backend_uses_public_workspace_scope,
        test_public_prompt_helper_has_legacy_fallback_support,
        test_public_prompt_count_route_uses_shared_counter,
        test_simplemde_overrides_are_loaded_from_base_template,
        test_simplemde_override_styles_cover_icons_and_dark_mode,
        test_config_version_is_bumped_for_follow_up_fix,
    ]

    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)