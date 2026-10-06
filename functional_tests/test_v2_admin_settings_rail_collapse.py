#!/usr/bin/env python3
# test_v2_admin_settings_rail_collapse.py
"""
Functional test for the collapsible V2 Admin Settings categories rail.
Version: 0.261.267
Implemented in: 0.261.267

The workspace section rail collapses to icons and remembers that per user. The Admin
Settings categories rail now does the same, under its own preference, so making room for
the settings cards does not rearrange the workspace pages or the application shell. This
file pins the contracts: the page reads and writes its own key ahead of its non-admin
return, the settings route accepts the key (an unlisted key is dropped silently), and a
collapsed entry keeps its label for screen readers. The browser behaviour is exercised by
ui_tests/test_v2_admin_settings_rail_collapse.py.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
PAGE_TSX = V2_SRC / "pages" / "AdminSettingsPage.tsx"
USER_SETTINGS_TS = V2_SRC / "lib" / "userSettings.ts"
USERS_ROUTE = REPO_ROOT / "application" / "single_app" / "route_backend_users.py"
PREFERENCE_KEY = "v2AdminRailCollapsed"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _categories_rail(page):
    """The categories rail markup, from its landmark to its closing tag."""
    match = re.search(r'<aside\s+aria-label="Settings categories".*?</aside>', page, re.DOTALL)
    assert match, "The Settings categories rail is missing from AdminSettingsPage.tsx"
    return match.group(0)


def test_version_is_at_least_the_implementing_release():
    print("Testing the application version...")
    assert_app_version_at_least("0.261.267")
    print("  ok  the version includes the collapsible admin rail")
    return True


def test_the_rail_uses_its_own_preference():
    print("Testing the admin rail preference...")
    page = _read(PAGE_TSX)

    assert f"state.settings.{PREFERENCE_KEY} === true" in page, (
        "The rail should read its own preference and treat anything but true as expanded"
    )
    assert f"updateUserSettings({{ {PREFERENCE_KEY}: !railCollapsed }})" in page, (
        "The collapse control should write the admin rail's own preference"
    )
    for other in ("v2WorkspaceRailCollapsed", "v2RailCollapsed"):
        assert other not in page, (
            f"The admin rail must not reuse {other}; collapsing it should not change the "
            "workspace pages or the application shell"
        )

    # A hook after the early return would change the hook count once the bootstrap says
    # the user is an admin, which React reports as an error.
    hook = page.find(f"state.settings.{PREFERENCE_KEY}")
    early_return = re.search(r"\n    if \(!isAdmin\) \{\s*return \(", page)
    assert early_return, "Could not find the page's non-admin return"
    assert hook < early_return.start(), (
        "The preference must be read before the page returns early for non-admins"
    )
    print("  ok  the rail reads and writes v2AdminRailCollapsed, ahead of the early return")
    return True


def test_the_rail_collapses_to_labelled_icons():
    print("Testing the collapse control and the collapsed entries...")
    rail = _categories_rail(_read(PAGE_TSX))

    assert "PanelLeftClose" in rail and "PanelLeftOpen" in rail, (
        "The rail should use the same collapse and expand icons as the workspace rail"
    )
    assert "aria-expanded={!railCollapsed}" in rail
    assert 'aria-controls="admin-settings-category-list"' in rail
    assert 'id="admin-settings-category-list"' in rail
    assert "'Collapse settings categories'" in rail and "'Expand settings categories'" in rail
    assert "railCollapsed ? 'sr-only'" in rail, (
        "A collapsed entry still needs its label available to a screen reader"
    )
    assert "title={railCollapsed ? category.label : undefined}" in rail, (
        "A collapsed entry should name its category in a tooltip"
    )
    assert "railCollapsed ? 'w-16" in rail and "'w-56" in rail
    assert "motion-reduce:transition-none" in rail, "The width change must respect reduced motion"
    assert "lg:block" in rail, "Below lg the category select should still replace the rail"

    # Unsaved Call agent changes lock the categories, collapsed or not, but the collapse
    # control changes no category and must stay usable.
    toggle = rail.split("<button", 2)[1].split("</button>", 1)[0]
    assert "aria-expanded" in toggle, "The collapse control should be the rail's first button"
    assert "disabled" not in toggle, "The collapse control must not be locked by unsaved changes"
    assert "disabled={delegationDirty}" in rail
    print("  ok  the rail collapses to icons that keep their names")
    return True


def test_the_preference_is_accepted_by_the_settings_route():
    print("Testing that the preference is whitelisted...")
    users = _read(USERS_ROUTE)
    allowed = re.search(r"allowed_keys = \{(.*?)\}", users, re.DOTALL)
    assert allowed, "Could not find allowed_keys in route_backend_users.py"
    assert f"'{PREFERENCE_KEY}'" in allowed.group(1), (
        "The settings route drops unlisted keys silently, so the rail would forget its state"
    )

    settings = _read(USER_SETTINGS_TS)
    writable = re.search(
        r"export const WRITABLE_USER_SETTING_KEYS = \[(.*?)\] as const;", settings, re.DOTALL
    )
    assert writable, "Could not find WRITABLE_USER_SETTING_KEYS in userSettings.ts"
    assert f"'{PREFERENCE_KEY}'" in writable.group(1), (
        "The client must declare the key it writes so the whitelist check covers it"
    )
    assert f"{PREFERENCE_KEY}?: boolean;" in settings
    print("  ok  the route accepts the key the client writes")
    return True


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_rail_uses_its_own_preference,
    test_the_rail_collapses_to_labelled_icons,
    test_the_preference_is_accepted_by_the_settings_route,
]


if __name__ == "__main__":
    results = []
    for test in TESTS:
        try:
            results.append(test() is True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
