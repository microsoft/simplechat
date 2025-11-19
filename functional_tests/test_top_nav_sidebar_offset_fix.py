#!/usr/bin/env python3
# test_top_nav_sidebar_offset_fix.py
"""
Functional test for top navigation sidebar offset alignment.
Version: 0.233.163
Implemented in: 0.233.163

This test ensures that the short sidebar sits below the fixed top navigation
bar and that inline template styles no longer hard-code the offset. It
validates both the template markup and the supporting navigation CSS rules.
"""

import os
import re


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))


def _read_file(*rel_path: str) -> str:
    with open(os.path.join(REPO_ROOT, *rel_path), "r", encoding="utf-8") as fh:
        return fh.read()


def test_sidebar_offset_alignment() -> bool:
    """Validate template styles and CSS positioning for the short sidebar."""
    template_content = _read_file("application", "single_app", "templates", "_sidebar_short_nav.html")
    navigation_css = _read_file("application", "single_app", "static", "css", "navigation.css")

    style_match = re.search(r'<div id="sidebar-nav"[^>]*style="([^"]+)"', template_content)
    if not style_match:
        raise AssertionError("Unable to locate sidebar nav style attribute in template.")

    inline_style = style_match.group(1)
    if "top:" in inline_style or "height:" in inline_style:
        raise AssertionError("Inline sidebar style should not include top/height after fix.")

    required_rules = {
        "nav.navbar.fixed-top + #sidebar-nav": "66px",
        "body.has-classification-banner nav.navbar.fixed-top + #sidebar-nav": "106px",
    }

    for selector, expected_offset in required_rules.items():
        if selector not in navigation_css:
            raise AssertionError(f"Missing CSS selector '{selector}' in navigation.css")
        selector_block_pattern = rf"{re.escape(selector)}\s*{{[^}}]*top:\s*{expected_offset}"  # noqa: W605
        if not re.search(selector_block_pattern, navigation_css):
            raise AssertionError(
                f"CSS selector '{selector}' does not define top: {expected_offset}"
            )

    print("✅ Top nav sidebar offset fix validated.")
    return True


if __name__ == "__main__":
    success = test_sidebar_offset_alignment()
    raise SystemExit(0 if success else 1)
