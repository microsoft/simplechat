#!/usr/bin/env python3
# test_admin_settings_nav_map.py
"""
Functional test for the Admin Settings navigation map.
Version: 0.260.010
Implemented in: 0.260.010

The top tab strip and the sidebar used to declare the same navigation twice, by
hand, and had already drifted: tab order differed between them, and three tabs
carried different labels in each. Both now render from
``admin_settings_nav.ADMIN_NAV``, which adds a group level above tabs.

This test pins the map itself, since it is now the contract both renderings
depend on:

  1. Structure is well formed and free of duplicates.
  2. Every tab has a matching pane, and every section a matching card.
  3. Both navigations render from the map rather than listing tabs by hand.
  4. Latest Features stays last so it never opens by default.
"""

import re
import sys
from pathlib import Path

from test_support.nav import ADMIN_NAV, get_section_ids, get_tab_ids, iter_tabs
from test_support.templates import (
    ADMIN_SETTINGS_TEMPLATE,
    read_admin_settings_template,
)
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
SIDEBAR_TEMPLATE = (
    REPO_ROOT / "application" / "single_app" / "templates" / "_sidebar_nav.html"
)


def test_nav_map_is_well_formed():
    """A malformed map would break both navigations at once."""
    print("Testing Admin Settings nav map structure...")

    assert_app_version_at_least("0.260.010")
    assert ADMIN_NAV, "Navigation map is empty"

    group_ids = [group["id"] for group in ADMIN_NAV]
    assert len(group_ids) == len(set(group_ids)), (
        f"Duplicate group ids: {sorted({g for g in group_ids if group_ids.count(g) > 1})}"
    )

    for group in ADMIN_NAV:
        for key in ("id", "label", "icon", "tabs"):
            assert key in group, f"Group {group.get('id')} is missing '{key}'"
        assert group["tabs"], f"Group {group['id']} has no tabs"

    tab_ids = get_tab_ids()
    duplicate_tabs = sorted({t for t in tab_ids if tab_ids.count(t) > 1})
    assert not duplicate_tabs, f"Tabs listed in more than one group: {duplicate_tabs}"

    section_ids = get_section_ids()
    duplicate_sections = sorted({s for s in section_ids if section_ids.count(s) > 1})
    assert not duplicate_sections, (
        f"Sections listed under more than one tab: {duplicate_sections}"
    )

    for _, tab in iter_tabs():
        for key in ("id", "label", "icon", "sections"):
            assert key in tab, f"Tab {tab.get('id')} is missing '{key}'"

    print(
        f"Map is well formed: {len(ADMIN_NAV)} groups, "
        f"{len(tab_ids)} tabs, {len(section_ids)} sections."
    )


def test_every_nav_destination_exists():
    """A destination with nothing behind it is a dead end for the admin."""
    print("Testing Admin Settings nav destinations...")

    composed = read_admin_settings_template()
    panes = set(re.findall(r'<div class="tab-pane[^"]*" id="([^"]+)"', composed))
    element_ids = set(re.findall(r'\sid="([^"]+)"', composed))

    missing_panes = sorted(set(get_tab_ids()) - panes)
    assert not missing_panes, f"Tabs with no matching pane: {missing_panes}"

    # Sections may use an alias resolved by the sidebar script, so accept
    # either the declared id or its resolved target.
    script = (
        REPO_ROOT
        / "application"
        / "single_app"
        / "static"
        / "js"
        / "admin"
        / "admin_sidebar_nav.js"
    ).read_text(encoding="utf-8")
    alias_body = re.search(
        r"const sectionMap = \{(.*?)^\s*\};", script, re.MULTILINE | re.DOTALL
    )
    aliases = dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)'", alias_body.group(1)))

    missing_sections = sorted(
        section_id
        for section_id in get_section_ids()
        if aliases.get(section_id, section_id) not in element_ids
    )
    assert not missing_sections, (
        f"Sections pointing at elements that do not exist: {missing_sections}"
    )

    print("Every tab and section destination resolves.")


def test_both_navigations_render_from_the_map():
    """Two hand-maintained copies of one structure will drift, and did."""
    print("Testing Admin Settings navigation rendering...")

    parent = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    sidebar = SIDEBAR_TEMPLATE.read_text(encoding="utf-8")

    for name, source in (("top tab strip", parent), ("sidebar", sidebar)):
        assert "admin_nav" in source, (
            f"The {name} does not render from the navigation map"
        )

    # Hardcoded tab buttons would reintroduce the drift this replaced.
    hardcoded = re.findall(r'id="([a-z-]+)-tab"\s+data-bs-toggle="tab"', parent)
    assert not hardcoded, (
        "These tabs are hardcoded in the top strip instead of coming from the "
        f"navigation map: {sorted(set(hardcoded))}"
    )

    print("Both navigations render from the map.")


def test_latest_features_stays_last():
    """Latest Features opened on every visit; it is pinned last deliberately."""
    print("Testing Latest Features placement in the nav map...")

    tab_ids = get_tab_ids()
    assert tab_ids[-1] == "latest-features", (
        f"Latest Features must be the last tab, got '{tab_ids[-1]}'"
    )
    assert tab_ids[0] == "general", (
        f"General must be the first tab, got '{tab_ids[0]}'"
    )
    assert ADMIN_NAV[-1]["id"] == "help", (
        "Latest Features should sit in the last group"
    )

    print("Latest Features is last; General leads.")


if __name__ == "__main__":
    tests = [
        test_nav_map_is_well_formed,
        test_every_nav_destination_exists,
        test_both_navigations_render_from_the_map,
        test_latest_features_stays_last,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
