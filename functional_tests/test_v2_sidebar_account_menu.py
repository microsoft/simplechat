#!/usr/bin/env python3
"""
Functional test for the V2 rail's account menu and remembered navigation groups.
Version: 0.261.054
Implemented in: 0.261.054

Four things about the V2 navigation rail are asserted here, all of which fail silently:

  - Admin Settings has moved out of the primary navigation list and into the account menu,
    where the classic interface has always kept it. A stray entry left behind in NAV_ITEMS
    would simply reappear in the rail for administrators.
  - The account menu renders when the rail is collapsed. It previously did not: the popover
    was gated on `!collapsed`, so clicking the avatar in the icon strip flipped state and
    painted nothing, putting settings, the classic interface and sign out out of reach.
  - The menu names its two destinations User Settings and Admin Settings, so the pair is
    tellable apart.
  - `sidebarMenuState` is writable through /api/user/settings. The route drops keys outside
    its whitelist *without failing the request*, so a missing entry there would leave the
    collapse state looking saved while it was being discarded on every write.

These are source-level assertions rather than a browser test, which is what makes them
runnable without a deployment. ui_tests/test_v2_appearance_branding_and_nav.py exercises the
rendered rail against a live tenant.
"""

import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
APP_ROOT = REPO_ROOT / "application" / "single_app"


def _read(path):
    return path.read_text(encoding="utf-8")


def _nav_items_block(sidebar_source):
    """Return the NAV_ITEMS literal, so the assertions cannot match the account menu."""
    match = re.search(r"const NAV_ITEMS: NavItem\[\] = \[(.*?)\n\];", sidebar_source, re.DOTALL)
    assert match, "NAV_ITEMS could not be located in Sidebar.tsx"
    return match.group(1)


def _user_menu_block(sidebar_source):
    """Return the UserMenu component body, ending at the next top-level declaration."""
    match = re.search(
        r"function UserMenu\(\{ collapsed \}: \{ collapsed: boolean \}\) \{(.*?)\nexport function ",
        sidebar_source,
        re.DOTALL,
    )
    assert match, "UserMenu could not be located in Sidebar.tsx"
    return match.group(1)


def test_admin_settings_left_the_primary_navigation():
    """Administration is an account concern, not one of the places you work."""
    print("Testing Admin Settings placement...")

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    nav_items = _nav_items_block(sidebar)

    assert "'/admin'" not in nav_items and '"/admin"' not in nav_items, (
        "Admin Settings must not be a primary navigation entry; it belongs in the account "
        "menu, matching where the classic interface keeps App Settings"
    )
    assert "adminOnly" not in sidebar, (
        "The adminOnly flag has no remaining user now that /admin is not a nav item; "
        "leaving it invites the entry being added back"
    )

    # The rest of the primary list is untouched, so a bad edit to NAV_ITEMS is caught rather
    # than passing because the whole list went missing. Home is deliberately absent: the
    # brand mark above the list carries that destination (test_v2_brand_mark_home_link.py).
    for route in ("'/chat'", "'/agents'", "'/workspace'", "'/groups'", "'/public'"):
        assert route in nav_items, f"The primary navigation lost {route}"

    print("Admin Settings placement test passed!")
    return True


def test_account_menu_offers_both_settings_destinations():
    """User Settings for everyone, Admin Settings for administrators only."""
    print("Testing account menu entries...")

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    user_menu = _user_menu_block(sidebar)

    assert 'to="/settings"' in user_menu, "The account menu must reach personal settings"
    assert "User Settings" in user_menu, (
        "Personal settings must be labelled User Settings; 'Settings' one line above "
        "'Admin Settings' does not say which one you are choosing"
    )
    assert 'to="/admin"' in user_menu, "The account menu must reach Admin Settings"
    assert "Admin Settings" in user_menu, "The Admin Settings entry must be labelled"
    assert 'href="/logout"' in user_menu, "The account menu must still offer sign out"
    assert "classicChatHref" in user_menu, (
        "The way back to the classic interface must still carry the open conversation"
    )

    print("Account menu entries test passed!")
    return True


def test_admin_entry_is_gated_on_the_admin_flag():
    """Only an administrator is offered the administration destination."""
    print("Testing Admin Settings gating...")

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    user_menu = _user_menu_block(sidebar)

    assert "isAdmin && (" in user_menu, (
        "Admin Settings must be rendered behind the is_admin check. The page refuses "
        "non-administrators anyway, but offering a destination that then refuses you is a "
        "worse experience than not offering it"
    )
    admin_link_index = user_menu.index('to="/admin"')
    gate_index = user_menu.rindex("isAdmin && (", 0, admin_link_index)
    assert admin_link_index - gate_index < 400, (
        "The is_admin check no longer appears to wrap the Admin Settings entry"
    )

    print("Admin Settings gating test passed!")
    return True


def test_account_menu_opens_when_the_rail_is_collapsed():
    """The collapsed rail is an icon strip, and the avatar in it must still open its menu."""
    print("Testing collapsed account menu...")

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    user_menu = _user_menu_block(sidebar)

    assert "open && !collapsed" not in user_menu, (
        "The account menu must not be gated on the rail being expanded: clicking the avatar "
        "in the collapsed strip would flip state and paint nothing, leaving settings, the "
        "classic interface and sign out unreachable"
    )
    assert "left-full" in user_menu, (
        "The collapsed menu must open beside the rail; there is no room for a 68px-wide "
        "panel above the avatar"
    )
    assert "Escape" in user_menu and "mousedown" in user_menu, (
        "The account menu must close on Escape and on a click outside, like every other "
        "menu in the interface"
    )

    print("Collapsed account menu test passed!")
    return True


def test_navigation_groups_are_always_collapsible_and_remembered():
    """Every group is a menu, and the choice is stored per user."""
    print("Testing navigation group collapse...")

    nav_extras = _read(V2_SRC / "components" / "layout" / "NavExtras.tsx")
    navigation_groups = _read(V2_SRC / "lib" / "navigationGroups.ts")

    assert "shouldRenderAsMenu" not in nav_extras, (
        "Groups collapse at any entry count now, so the classic three-item threshold must "
        "not decide whether the heading is a control"
    )
    assert "shouldRenderAsMenu" not in navigation_groups, (
        "shouldRenderAsMenu is unused and must not be left behind for a future caller"
    )
    assert 'stateKey="externalLinks"' in nav_extras, "External Links must persist its state"
    assert 'stateKey="customPages"' in nav_extras, "Custom Pages must persist its state"
    assert "withSidebarMenuExpanded" in nav_extras and "readSidebarMenuExpanded" in nav_extras, (
        "The group must read and write its expanded state through the shared helpers, which "
        "are what keep the whole setting object intact on write"
    )
    assert "aria-expanded={expanded}" in nav_extras, (
        "The heading is a disclosure control and must report its state to assistive tech"
    )

    print("Navigation group collapse test passed!")
    return True


def test_sidebar_menu_state_is_writable_end_to_end():
    """The client may write the key, and the route accepts it."""
    print("Testing sidebarMenuState write path...")

    user_settings = _read(V2_SRC / "lib" / "userSettings.ts")
    assert "'sidebarMenuState'," in user_settings, (
        "sidebarMenuState must be in WRITABLE_USER_SETTING_KEYS"
    )

    route = _read(APP_ROOT / "route_backend_users.py")
    allowed = re.search(r"allowed_keys = \{(.*?)\n\s*\}", route, re.DOTALL)
    assert allowed, "allowed_keys could not be located in route_backend_users.py"
    assert "'sidebarMenuState'" in allowed.group(1), (
        "The route drops keys outside allowed_keys without failing the request, so the "
        "collapse state would look saved while being discarded on every write"
    )

    # The key names have to match the classic interface exactly, or a toggle made in one
    # interface is dropped by the other's normaliser on its next write.
    classic_sidebar = _read(APP_ROOT / "static" / "js" / "sidebar.js")
    classic_keys = re.search(r"sidebarMenuStateKeys = new Set\(\[(.*?)\]\)", classic_sidebar, re.DOTALL)
    assert classic_keys, "sidebarMenuStateKeys could not be located in sidebar.js"

    shared_state = _read(V2_SRC / "lib" / "sidebarMenuState.ts")
    v2_keys = re.search(
        r"SIDEBAR_MENU_STATE_KEYS = \[(.*?)\] as const", shared_state, re.DOTALL
    )
    assert v2_keys, "SIDEBAR_MENU_STATE_KEYS could not be located in sidebarMenuState.ts"

    def _keys(block):
        return sorted(set(re.findall(r"'([A-Za-z]+)'", block)))

    assert _keys(v2_keys.group(1)) == _keys(classic_keys.group(1)), (
        "The two interfaces must recognise the same menu keys, or each will discard the "
        "other's entries the next time it writes"
    )

    print("sidebarMenuState write path test passed!")
    return True


def test_profile_photo_is_shown_where_the_account_is():
    """The stored Graph photo reaches the rail and the settings page."""
    print("Testing profile photo...")

    avatar = _read(V2_SRC / "components" / "layout" / "UserAvatar.tsx")
    assert "settings.profileImage" in avatar, (
        "The avatar must read the photo the server already caches on the user's settings "
        "document; nothing else holds it"
    )
    assert "onError" in avatar, (
        "The cached data URI is never re-validated, so a broken one must fall back to "
        "initials rather than leaving an empty circle"
    )

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    assert "<UserAvatar" in sidebar, "The account control must show the user's picture"

    settings_page = _read(V2_SRC / "pages" / "SettingsPage.tsx")
    assert "<UserAvatar" in settings_page, (
        "The settings page header must show the user's picture beside its title"
    )
    assert 'title="User Settings"' in settings_page, (
        "The page title must match the account menu entry that reaches it"
    )

    print("Profile photo test passed!")
    return True


def test_version_is_at_least_the_implementation_version():
    """The application carries at least the version this behaviour arrived in."""
    print("Testing version...")
    assert_app_version_at_least(
        "0.261.054",
        reason="The V2 account menu and remembered navigation groups landed in 0.261.054.",
    )
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_admin_settings_left_the_primary_navigation,
        test_account_menu_offers_both_settings_destinations,
        test_admin_entry_is_gated_on_the_admin_flag,
        test_account_menu_opens_when_the_rail_is_collapsed,
        test_navigation_groups_are_always_collapsible_and_remembered,
        test_sidebar_menu_state_is_writable_end_to_end,
        test_profile_photo_is_shown_where_the_account_is,
        test_version_is_at_least_the_implementation_version,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
