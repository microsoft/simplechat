# test_custom_page_shell_hero.py
"""
UI test for Custom Pages shell hero styling.
Version: 0.250.025
Implemented in: 0.250.025

This test ensures custom pages, including the Request Access page, use the
rounded workspace-style hero header instead of a square banner.
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CUSTOM_PAGE_SHELL = REPO_ROOT / "application" / "single_app" / "templates" / "custom_page_shell.html"


@pytest.mark.ui
def test_custom_page_shell_uses_workspace_style_hero():
    """Validate the custom page shell includes the rounded gradient hero contract."""
    shell = CUSTOM_PAGE_SHELL.read_text(encoding="utf-8")

    required_markers = [
        "custom-page-hero",
        "border-radius: 1rem",
        "box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12)",
        "linear-gradient(135deg, var(--custom-page-hero-color) 0%, var(--custom-page-hero-color-dark) 100%)",
        "aria-labelledby=\"custom-page-title\"",
        "id=\"custom-page-title\"",
        "custom-page-hero__description",
    ]

    for marker in required_markers:
        assert marker in shell, f"Missing custom page hero marker: {marker}"

    assert "<header class=\"mb-4\">" not in shell
    assert "<p class=\"text-muted\">{{ custom_page.description }}</p>" not in shell