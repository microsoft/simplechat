#!/usr/bin/env python3
"""
Functional test for Admin Settings sidebar and agent catalog guard.
Version: 0.242.072
Implemented in: 0.242.072

This test ensures Blueprint route migration does not hide Admin Settings
left-navigation sections and that Admin Settings does not call the agent
catalog endpoint while Semantic Kernel is disabled.
"""

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    """Read a repository text file."""
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_sidebar_uses_blueprint_endpoint_names():
    """Verify sidebar template endpoint checks use Blueprint-qualified names."""
    template_paths = [
        "application/single_app/templates/base.html",
        "application/single_app/templates/_top_nav.html",
        "application/single_app/templates/_sidebar_nav.html",
        "application/single_app/templates/_sidebar_short_nav.html",
    ]
    combined_source = "\n".join(read_text(path) for path in template_paths)

    assert "request.endpoint == 'chats'" not in combined_source
    assert 'request.endpoint == "chats"' not in combined_source
    assert "request.endpoint == 'admin_settings'" not in combined_source
    assert 'request.endpoint == "admin_settings"' not in combined_source
    assert "request.endpoint == 'frontend_chats.chats'" in combined_source
    assert "request.endpoint == 'frontend_admin_settings.admin_settings'" in combined_source


def test_admin_settings_skips_agent_catalog_when_semantic_kernel_disabled():
    """Verify Admin Settings exposes and respects the Semantic Kernel guard."""
    template_source = read_text("application/single_app/templates/admin_settings.html")
    script_source = read_text("application/single_app/static/js/admin/admin_settings.js")

    assert "window.enableSemanticKernel" in template_source
    assert "let enableSemanticKernel = Boolean(window.enableSemanticKernel);" in script_source
    assert "if (!enableSemanticKernel)" in script_source
    assert "Enable Agents to load available agents" in script_source
    assert "fetch('/api/agents/catalog?include_usage=true')" in script_source


if __name__ == "__main__":
    tests = [
        test_sidebar_uses_blueprint_endpoint_names,
        test_admin_settings_skips_agent_catalog_when_semantic_kernel_disabled,
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
