# test_admin_custom_pages_open_action.py
"""
UI contract test for the Admin Settings Custom Pages Open action.
Version: 0.250.106
Implemented in: 0.250.106

This test ensures the Custom Pages table exposes a safe Open action that links
through the existing `/custom/<slug>` route and keeps unavailable pages disabled.
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_CUSTOM_PAGES_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_custom_pages.js"


@pytest.mark.ui
def test_admin_custom_pages_table_open_action_contract():
    """Validate the admin Custom Pages table exposes the expected Open action behavior."""
    script = ADMIN_CUSTOM_PAGES_JS.read_text(encoding="utf-8")

    required_markers = [
        "createCustomPageOpenAction(page)",
        "openLink.href = getCustomPageUrl(page)",
        "openLink.target = \"_blank\"",
        "openLink.rel = \"noopener noreferrer\"",
        "`/custom/${encodeURIComponent(slug)}`",
        "window.customPagesInitiallyEnabled !== true",
        "disabledButton.disabled = true",
        "Disabled custom pages are not available to open.",
        "Route authorization still applies.",
    ]

    for marker in required_markers:
        assert marker in script, f"Missing Custom Pages Open action marker: {marker}"
