#!/usr/bin/env python3
"""
Functional test for Admin Settings group-shared control regions.
Version: 0.260.016
Implemented in: 0.260.016

Some groups share one set of controls across all of their tabs. Backup &
Recovery is the case that forced this: five tabs share a single save button,
one status line and one operational warning, all driven by one JavaScript
module.

Those controls cannot be copied into each pane, because that repeats element
ids and the module would bind to the wrong one. They cannot live in a single
pane either, because an inactive tab pane is hidden, so the other four tabs
would lose the save button. So they sit outside the panes and are revealed
only while their group is active.

This test ensures that arrangement holds.
"""

import os
import re
import sys
import collections

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.templates import read_admin_settings_template  # noqa: E402
from test_support.nav import iter_tabs  # noqa: E402

APP_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
)
SIDEBAR_JS = os.path.join(APP_ROOT, "static", "js", "admin", "admin_sidebar_nav.js")

SHARED_REGION_PATTERN = re.compile(r'data-admin-group-shared="([a-z0-9-]+)"')


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_shared_regions_name_a_real_group():
    """A shared region must belong to a group that exists in the nav map."""
    print("Testing group-shared regions reference real groups...")

    markup = read_admin_settings_template()
    owners = SHARED_REGION_PATTERN.findall(markup)
    assert owners, "Expected at least one group-shared region"

    known_groups = {group["id"] for group, _ in iter_tabs()}
    unknown = sorted(set(owners) - known_groups)
    assert not unknown, f"Shared regions reference groups that do not exist: {unknown}"

    print(f"All {len(owners)} shared region(s) reference a real group.")
    return True


def test_shared_regions_sit_outside_every_pane():
    """A shared region inside a pane would be hidden with that pane."""
    print("Testing group-shared regions sit outside the tab panes...")

    markup = read_admin_settings_template()
    for match in SHARED_REGION_PATTERN.finditer(markup):
        before = markup[: match.start()]
        # Every pane opens with a tab-pane div and the tab content container
        # comes after all shared regions, so a shared region declared after the
        # container has been opened would be inside it.
        assert 'id="adminSettingsTabContent"' not in before, (
            f"Shared region '{match.group(1)}' is declared inside the tab content "
            "container, where it would be hidden along with the active pane"
        )

    print("Shared regions are declared before the tab content container.")
    return True


def test_shared_controls_are_not_duplicated():
    """The whole point is one control serving many tabs, not one per tab."""
    print("Testing shared controls appear exactly once...")

    markup = read_admin_settings_template()
    ids = collections.Counter(re.findall(r'\sid="([A-Za-z0-9_-]+)"', markup))
    duplicates = sorted(element_id for element_id, count in ids.items() if count > 1)
    assert not duplicates, (
        "Element ids declared more than once in the composed Admin Settings "
        f"template: {duplicates}"
    )

    print(f"All {len(ids)} element ids in Admin Settings are unique.")
    return True


def test_shared_regions_are_synced_on_tab_change():
    """A region that is never toggled would stay hidden forever."""
    print("Testing shared regions are synced when the tab changes...")

    source = _read(SIDEBAR_JS)
    assert "function syncAdminGroupSharedRegions(" in source, (
        "Expected a helper that reveals the shared region for the active group"
    )
    # Called from the programmatic path, the initial-load path, and Bootstrap's
    # own tab event, so no route into a tab leaves the region stale.
    call_count = source.count("syncAdminGroupSharedRegions(")
    assert call_count >= 4, (
        f"Expected the sync helper to be defined and called from every path "
        f"that activates a tab, found {call_count} references"
    )
    assert "shown.bs.tab" in source, (
        "Clicking a tab button directly does not go through showAdminTab, so "
        "Bootstrap's shown.bs.tab event must also sync the shared regions"
    )

    print("Shared regions are synced from every path that activates a tab.")
    return True


def test_shared_region_lookup_handles_both_navigations():
    """Only one navigation renders at a time, so both must resolve the group."""
    print("Testing group lookup works in the tab and sidebar layouts...")

    source = _read(SIDEBAR_JS)
    match = re.search(r"function syncAdminGroupSharedRegions\(tabId\) \{.*?\n\}", source, re.S)
    assert match, "Expected the shared region sync helper"
    body = match.group(0)

    # The top tab strip is skipped entirely in the sidebar layout, so a lookup
    # that only reads `.admin-tab-item` would leave the region hidden for good
    # and Backup & Recovery would lose its only save button.
    assert ".admin-tab-item[data-admin-group]" in body, (
        "Expected the tab layout lookup"
    )
    assert ".admin-nav-tab[data-tab=" in body, (
        "Expected a sidebar layout fallback so the region resolves when the top "
        "tab strip is not rendered"
    )

    print("Both navigation layouts can resolve the owning group.")
    return True


if __name__ == "__main__":
    tests = [
        test_shared_regions_name_a_real_group,
        test_shared_regions_sit_outside_every_pane,
        test_shared_controls_are_not_duplicated,
        test_shared_regions_are_synced_on_tab_change,
        test_shared_region_lookup_handles_both_navigations,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
