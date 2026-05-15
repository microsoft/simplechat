# test_public_workspace_manage_script_parse.py
"""
UI test for public workspace manage script parsing.
Version: 0.241.009
Implemented in: 0.241.009

This test ensures Chromium can parse the public workspace management script
without the syntax error that prevented public workspace pages from loading.
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