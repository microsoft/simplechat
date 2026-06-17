# test_public_workspace_manage_script_parse.py
"""
UI test for public workspace manage script parsing.
Version: 0.242.058
Implemented in: 0.241.009

This test ensures Chromium can parse the public workspace management script
without the syntax error that prevented public workspace pages from loading.
Updated in 0.242.058 to verify the manage page uses the app version in the
script URL so browsers fetch a fresh asset after deployments.
"""

from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
MANAGE_PUBLIC_WORKSPACE_JS = (
    ROOT_DIR
    / "application"
    / "single_app"
    / "static"
    / "js"
    / "public"
    / "manage_public_workspace.js"
)
MANAGE_PUBLIC_WORKSPACE_TEMPLATE = (
    ROOT_DIR
    / "application"
    / "single_app"
    / "templates"
    / "manage_public_workspace.html"
)


@pytest.mark.ui
def test_public_workspace_manage_script_parses_in_chromium(page):
    """Validate the public workspace manage script parses in Chromium."""
    source = MANAGE_PUBLIC_WORKSPACE_JS.read_text(encoding="utf-8")

    parse_result = page.evaluate(
        """
        (scriptSource) => {
            try {
                new Function(scriptSource);
                return { ok: true };
            } catch (error) {
                return {
                    ok: false,
                    name: error.name,
                    message: error.message,
                    stack: error.stack,
                };
            }
        }
        """,
        source,
    )

    assert parse_result["ok"], (
        "Expected manage_public_workspace.js to parse in Chromium. "
        f"Observed: {parse_result}"
    )


@pytest.mark.ui
def test_manage_public_workspace_script_reference_uses_app_version():
    """Validate the manage page cache-busts the public workspace script."""
    source = MANAGE_PUBLIC_WORKSPACE_TEMPLATE.read_text(encoding="utf-8")
    expected_reference = (
        "<script src=\"{{ url_for('static', filename='js/public/manage_public_workspace.js') }}"
        "?v={{ config['VERSION'] }}\"></script>"
    )
    unversioned_reference = (
        "<script src=\"{{ url_for('static', filename='js/public/manage_public_workspace.js') }}\"></script>"
    )

    assert expected_reference in source
    assert unversioned_reference not in source