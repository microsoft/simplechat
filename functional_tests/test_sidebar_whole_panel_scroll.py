# test_sidebar_whole_panel_scroll.py
"""
Functional test for whole-panel chat sidebar scrolling.
Version: 0.250.002
Implemented in: 0.250.002

This test ensures both sidebar templates use the shared outer scroll container
and the Conversations list cannot regain its former nested scrollbar.
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SIDEBAR_CSS = REPO_ROOT / "application" / "single_app" / "static" / "css" / "sidebar.css"
SIDEBAR_TEMPLATES = (
    REPO_ROOT / "application" / "single_app" / "templates" / "_sidebar_nav.html",
    REPO_ROOT / "application" / "single_app" / "templates" / "_sidebar_short_nav.html",
)


def _css_rule(css_content, selector):
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css_content, re.DOTALL)
    assert match is not None, f"Expected CSS rule for {selector}."
    return match.group("body")


def test_sidebar_templates_use_outer_scroll_container():
    """Check both chat sidebar shells opt into the shared scroll container."""
    for template_path in SIDEBAR_TEMPLATES:
        content = template_path.read_text(encoding="utf-8")
        assert 'id="sidebar-content" class="sidebar-scroll-content ' in content
        assert '<div id="conversations-section">' in content
        assert 'id="conversations-section" class="flex-grow-1 overflow-auto"' not in content
        assert 'id="conversations-toggle" class="sidebar-section-toggle mt-2 ' not in content


def test_sidebar_css_has_one_scroll_region_and_sticky_heading():
    """Check overflow and sticky rules preserve the intended scroll boundaries."""
    css_content = SIDEBAR_CSS.read_text(encoding="utf-8")
    outer_scroll_rule = _css_rule(css_content, ".sidebar-scroll-content")
    conversations_section_rule = _css_rule(css_content, "#conversations-section")
    conversations_list_rule = _css_rule(css_content, "#sidebar-conversations-list")
    conversations_toggle_rule = _css_rule(css_content, "#conversations-toggle")

    assert "overflow-y: auto;" in outer_scroll_rule
    assert "overflow-x: hidden;" in outer_scroll_rule
    assert "flex: 0 0 auto;" in conversations_section_rule
    assert "max-height: none;" in conversations_section_rule
    assert "overflow: visible;" in conversations_list_rule
    assert "overflow-y: auto;" not in conversations_list_rule
    assert "position: sticky;" in conversations_toggle_rule
    assert "top: 0;" in conversations_toggle_rule
    assert "padding-top: 0.5rem;" in conversations_toggle_rule
    assert "max-height: calc(100vh - 350px)" not in css_content


if __name__ == "__main__":
    tests = [
        test_sidebar_templates_use_outer_scroll_container,
        test_sidebar_css_has_one_scroll_region_and_sticky_heading,
    ]

    try:
        for test in tests:
            test()
            print(f"PASS: {test.__name__}")
    except Exception as ex:
        print(f"FAIL: {ex}")
        sys.exit(1)

    print(f"PASS: {len(tests)} sidebar scroll regression tests")
