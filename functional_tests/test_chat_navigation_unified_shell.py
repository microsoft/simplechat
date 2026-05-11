# test_chat_navigation_unified_shell.py
#!/usr/bin/env python3
"""
Functional test for the unified chat navigation shell.
Version: 0.241.023
Implemented in: 0.241.023

This test ensures that chats in top-nav mode now use a single adaptive rail,
route the mobile hamburger into that rail, and keep the new inline desktop
toggle instead of the old floating reopen control while avoiding duplicate
Bootstrap offcanvas ownership for the chat rail while keeping the mobile
drawer offset below the fixed header.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def read_text(relative_path: str) -> str:
    """Read a repository file as UTF-8 text."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_base_template_marks_chat_top_nav_shell() -> bool:
    """Validate the base template exposes chat shell body classes and desktop-only sidebar padding."""
    print("Testing base template chat shell markers...")
    base_template = read_text("application/single_app/templates/base.html")

    required_snippets = [
        "chat-shell-page",
        "chat-top-nav-shell",
        "body:not(.sidebar-nav-enabled) .sidebar-padding",
        "{% set is_sidebar_layout = nav_layout == 'sidebar' or (not nav_layout and app_settings.enable_left_nav_default) %}",
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in base_template]
    if missing_snippets:
        print(f"Missing base template chat shell snippets: {missing_snippets}")
        return False

    print("Base template chat shell markers found.")
    return True


def test_top_nav_routes_chat_hamburger_to_chat_rail() -> bool:
    """Validate the top nav routes mobile chat into the rail and keeps desktop chat links visible."""
    top_nav_template = read_text("application/single_app/templates/_top_nav.html")

    required_snippets = [
        "{% set is_chat_page = request.endpoint == 'chats' %}",
        "top-nav-chat-nav",
        'data-bs-target="#sidebar-nav"',
        'aria-label="Open chat navigation"',
        'data-navigation-drawer="top-nav"',
        '{% if not is_chat_page %}',
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in top_nav_template]
    if missing_snippets:
        print(f"Missing top nav chat routing snippets: {missing_snippets}")
        return False

    print("Top nav chat drawer routing found.")
    return True


def test_chat_sidebar_is_adaptive_and_inline_toggle_exists() -> bool:
    """Validate the chat sidebar and scripts implement the adaptive rail pattern."""
    sidebar_template = read_text("application/single_app/templates/_sidebar_short_nav.html")
    chats_template = read_text("application/single_app/templates/chats.html")
    sidebar_css = read_text("application/single_app/static/css/sidebar.css")
    navigation_css = read_text("application/single_app/static/css/navigation.css")
    navigation_js = read_text("application/single_app/static/js/navigation.js")
    sidebar_js = read_text("application/single_app/static/js/sidebar.js")

    required_sidebar_snippets = [
        "chat-sidebar-nav offcanvas-lg offcanvas-start",
        'data-navigation-drawer="chat-rail"',
        "chat-sidebar-mobile-header",
        "chat-sidebar-user-account",
        "chat-sidebar-mobile-sections",
        'top-nav-mobile-section-label">Workspace</div>',
        "url_for('workspace')",
        "url_for('group_workspaces')",
        "url_for('public_directory')",
    ]
    required_chat_snippets = [
        'id="chat-sidebar-inline-toggle"',
        'data-sidebar-toggle="toggle"',
    ]
    required_css_snippets = [
        "body.chat-top-nav-shell #sidebar-nav.chat-sidebar-nav",
        "body.chat-top-nav-shell #sidebar-nav.chat-sidebar-nav.show",
        "body.chat-top-nav-shell #sidebar-nav.chat-sidebar-nav .chat-sidebar-mobile-header",
        "height: calc(100vh - var(--chat-sidebar-top));",
        "top: var(--chat-sidebar-top);",
    ]
    required_navigation_js_snippets = [
        "initializeNavigationOverlayCoordination()",
        "getNavigationOffcanvasElements()",
        "closeOpenDropdowns()",
        "isChatRailNavigationDrawer(offcanvasElement)",
    ]
    required_navigation_css_snippets = [
        "--top-nav-height: 66px;",
        ".top-nav-mobile-drawer.offcanvas-start {",
        "height: calc(100vh - var(--top-nav-height));",
        "top: var(--top-nav-height);",
        "z-index: 1046;",
    ]
    required_sidebar_js_snippets = [
        "initializeChatSidebarDrawer()",
        "#sidebar-nav[data-navigation-drawer=\"chat-rail\"]",
        "bootstrap.Offcanvas.getInstance(sidebar)",
    ]

    missing_snippets = [snippet for snippet in required_sidebar_snippets if snippet not in sidebar_template]
    missing_snippets.extend(snippet for snippet in required_chat_snippets if snippet not in chats_template)
    missing_snippets.extend(snippet for snippet in required_css_snippets if snippet not in sidebar_css)
    missing_snippets.extend(snippet for snippet in required_navigation_css_snippets if snippet not in navigation_css)
    missing_snippets.extend(snippet for snippet in required_navigation_js_snippets if snippet not in navigation_js)
    missing_snippets.extend(snippet for snippet in required_sidebar_js_snippets if snippet not in sidebar_js)

    if missing_snippets:
        print(f"Missing adaptive chat rail snippets: {missing_snippets}")
        return False

    if 'id="floating-expand-btn"' in sidebar_template:
        print("Short chat sidebar still contains the floating expand button markup")
        return False

    if 'bootstrap.Offcanvas.getOrCreateInstance(sidebar)' in sidebar_js:
        print("Chat sidebar drawer still creates a duplicate Bootstrap offcanvas instance")
        return False

    if "if (isChatRailNavigationDrawer(offcanvasElement))" not in navigation_js:
        print("Generic navigation drawer initialization still attempts to own the chat rail")
        return False

    print("Adaptive chat rail snippets found.")
    return True


def test_config_version_bumped_for_chat_navigation_shell() -> bool:
    """Validate the repository version bump for the chat navigation shell work."""
    print("Testing config version bump for chat navigation shell...")
    config_content = read_text("application/single_app/config.py")

    if 'VERSION = "0.241.023"' not in config_content:
        print("Config version was not bumped to 0.241.023")
        return False

    print("Config version bump found.")
    return True


if __name__ == "__main__":
    checks = [
        test_base_template_marks_chat_top_nav_shell,
        test_top_nav_routes_chat_hamburger_to_chat_rail,
        test_chat_sidebar_is_adaptive_and_inline_toggle_exists,
        test_config_version_bumped_for_chat_navigation_shell,
    ]

    results = []
    for check in checks:
        print(f"\nRunning {check.__name__}...")
        results.append(check())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} checks passed")
    raise SystemExit(0 if success else 1)
