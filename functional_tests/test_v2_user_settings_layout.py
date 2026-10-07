#!/usr/bin/env python3
# test_v2_user_settings_layout.py
"""
Functional test for the V2 User Settings layout redesign.
Version: 0.261.277
Implemented in: 0.261.277

User Settings now follows the Admin Settings design language: a collapsible section rail
remembered per user, full-width content, settings cards, and an "On this page" index on
the right that is built from the cards each tab renders. Preferences are grouped, and the
Violations tab is always listed. This file pins those contracts.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
SETTINGS_DIR = V2_SRC / "components" / "settings"
PAGE_TSX = V2_SRC / "pages" / "SettingsPage.tsx"
CARD_TSX = SETTINGS_DIR / "SettingsCard.tsx"
USER_SETTINGS_TS = V2_SRC / "lib" / "userSettings.ts"
USERS_ROUTE = REPO_ROOT / "application" / "single_app" / "route_backend_users.py"
PREFERENCE_KEY = "v2UserSettingsRailCollapsed"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_version_is_at_least_the_implementing_release():
    print("Testing the application version...")
    assert_app_version_at_least("0.261.277")
    return True


def test_rail_collapse_is_remembered_per_user():
    print("Testing the user settings rail preference...")
    page = _read(PAGE_TSX)
    assert f"state.settings.{PREFERENCE_KEY} === true" in page
    assert f"updateUserSettings({{ {PREFERENCE_KEY}: !railCollapsed }})" in page
    assert 'aria-label="User settings sections"' in page
    assert "Collapse user settings sections" in page and "Expand user settings sections" in page

    allowed = re.search(r"allowed_keys = \{(.*?)\}", _read(USERS_ROUTE), re.DOTALL)
    assert allowed and f"'{PREFERENCE_KEY}'" in allowed.group(1), (
        "The settings route drops unlisted keys silently, so the rail key must be allowed"
    )
    user_settings = _read(USER_SETTINGS_TS)
    writable = re.search(r"export const WRITABLE_USER_SETTING_KEYS = \[(.*?)\] as const;", user_settings, re.DOTALL)
    assert writable and f"'{PREFERENCE_KEY}'" in writable.group(1)
    assert f"{PREFERENCE_KEY}?: boolean;" in user_settings
    return True


def test_page_index_is_built_from_registered_cards():
    print("Testing the On this page index...")
    page = _read(PAGE_TSX)
    card = _read(CARD_TSX)
    assert "SettingsSectionRegistryContext.Provider" in page
    assert "<SettingsIndex" in page
    assert "@min-[76rem]:grid-cols-[minmax(0,1fr)_15rem]" in page, "Content should fill the width beside the index"
    assert "register(" in card and "unregister(" in card, "Cards must register with the page index"
    assert "admin-settings-distinct" in card, "Cards should share the Admin Settings card styling"
    return True


def test_every_tab_renders_settings_cards():
    print("Testing tab card usage...")
    for name in ("PreferencesTab", "StatsTab", "FeedbackTab", "ViolationsTab", "WorkspaceListTab"):
        source = _read(SETTINGS_DIR / f"{name}.tsx")
        assert "<SettingsCard" in source, f"{name} should render SettingsCard so it appears in the index"
    return True


def test_preferences_are_grouped():
    print("Testing preference groups...")
    prefs = _read(SETTINGS_DIR / "PreferencesTab.tsx")
    for label in ("Appearance", "Chat", "Notifications and alerts", "Diagrams and charts"):
        assert f'label="{label}"' in prefs, f"Preferences should include the {label} group"
    return True


def test_violations_tab_is_always_listed():
    print("Testing Violations visibility...")
    tabs = _read(SETTINGS_DIR / "tabs.tsx")
    entry = re.search(r"id: 'violations'.*?\}", tabs, re.DOTALL)
    assert entry and "feature:" not in entry.group(0), "Violations should not be gated by a feature flag"
    violations = _read(SETTINGS_DIR / "ViolationsTab.tsx")
    assert "if (available)" in violations, "The tab should not call the endpoints when content safety is off"
    return True


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_rail_collapse_is_remembered_per_user,
        test_page_index_is_built_from_registered_cards,
        test_every_tab_renders_settings_cards,
        test_preferences_are_grouped,
        test_violations_tab_is_always_listed,
    ]
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)
    print(f"Results: {sum(bool(r) for r in results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
