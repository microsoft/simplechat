#!/usr/bin/env python3
"""
Functional test for Backup & Recovery pane binding in Admin Settings.
Version: 0.261.001
Implemented in: 0.261.001

Backup & Recovery was a single "Data Management" tab until the Admin Settings
information architecture was split into five sibling panes: Backup, Migrate,
Restore, Cosmos Editor and Jobs. The pane element that carried
``id="data-management"`` disappeared in that split, but admin_data_management.js
still resolved its root from that id and returned early when it was missing.

Every listener in the module, including the change tracking that enables the
Backup & Recovery save button, was attached inside that guard. The result was a
save button that never left its disabled "Saved" state, so an admin could toggle
scheduled backups and had no way to persist it.

These tests ensure the module and the global save button resolve the panes from
a contract that is declared in the markup, so splitting or adding a Backup &
Recovery tab cannot silently strand the module again.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.nav import iter_tabs  # noqa: E402
from test_support.templates import read_admin_settings_template  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

APP_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
)
DATA_MANAGEMENT_JS = os.path.join(APP_ROOT, "static", "js", "admin", "admin_data_management.js")
ADMIN_SETTINGS_JS = os.path.join(APP_ROOT, "static", "js", "admin", "admin_settings.js")

GROUP_ID = "backup-recovery"
GROUP_ATTRIBUTE = f'data-admin-group-pane="{GROUP_ID}"'

BOUND_IDS_PATTERN = re.compile(r"function bindElements\(\) \{\s*const ids = \[(.*?)\];", re.S)
ELEMENT_ID_PATTERN = re.compile(r'\sid="([A-Za-z0-9_:.-]+)"')
TAB_PANE_PATTERN = re.compile(r'<div class="tab-pane fade[^>]*?\sid="([A-Za-z0-9_:.-]+)"[^>]*>')

# Representative settings controls that saveDataManagementSettings() sends. One
# lives on the Backup tab and one on the Migrate tab, so a regression that binds
# change tracking to only the first pane is caught.
SETTINGS_CONTROL_IDS = (
    "data_management_enabled",
    "data_management_retention_value",
    "data_management_encryption_enabled",
    "data_management_migration_retry_count",
)


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _group_tab_ids():
    return [tab["id"] for group, tab in iter_tabs() if group["id"] == GROUP_ID]


def _pane_regions(markup):
    """Return {pane_id: markup} for every tab pane in the composed template."""
    matches = list(TAB_PANE_PATTERN.finditer(markup))
    regions = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markup)
        regions[match.group(1)] = markup[match.start():end]
    return regions


def test_every_bound_element_id_exists():
    """A bound id with no element is a silently dead binding."""
    print("Testing every bound Data Management element id exists...")

    source = _read(DATA_MANAGEMENT_JS)
    block = BOUND_IDS_PATTERN.search(source)
    assert block, "Expected a bindElements() id list in admin_data_management.js"

    bound_ids = re.findall(r'"([^"]+)"', block.group(1))
    assert bound_ids, "Expected bindElements() to bind at least one element id"

    present = set(ELEMENT_ID_PATTERN.findall(read_admin_settings_template()))
    missing = sorted(set(bound_ids) - present)
    assert not missing, (
        "admin_data_management.js binds element ids that do not exist in the "
        f"composed Admin Settings template: {missing}"
    )

    print(f"All {len(bound_ids)} bound element ids resolve to real elements.")
    return True


def test_every_group_tab_declares_its_pane():
    """The module finds its panes by group, so every tab must declare it."""
    print("Testing every Backup & Recovery tab declares its pane group...")

    markup = read_admin_settings_template()
    regions = _pane_regions(markup)

    tab_ids = _group_tab_ids()
    assert tab_ids, f"Expected the '{GROUP_ID}' group to define tabs"

    undeclared = []
    for tab_id in tab_ids:
        region = regions.get(tab_id)
        assert region is not None, f"No tab pane found for '{tab_id}'"
        if GROUP_ATTRIBUTE not in region.split(">", 1)[0]:
            undeclared.append(tab_id)

    assert not undeclared, (
        f"Backup & Recovery panes missing {GROUP_ATTRIBUTE}: {undeclared}. "
        "admin_data_management.js binds its listeners inside these panes, so an "
        "undeclared pane loses every control it holds."
    )

    print(f"All {len(tab_ids)} Backup & Recovery tabs declare their pane group.")
    return True


def test_no_unrelated_pane_claims_the_group():
    """Claiming the group elsewhere would bind unrelated controls."""
    print("Testing only Backup & Recovery panes claim the group...")

    markup = read_admin_settings_template()
    tab_ids = set(_group_tab_ids())

    claimed = [
        pane_id
        for pane_id, region in _pane_regions(markup).items()
        if GROUP_ATTRIBUTE in region.split(">", 1)[0]
    ]
    unexpected = sorted(set(claimed) - tab_ids)
    assert not unexpected, (
        f"Panes outside the '{GROUP_ID}' group declare {GROUP_ATTRIBUTE}: {unexpected}"
    )
    assert len(claimed) == len(tab_ids), (
        f"Expected {len(tab_ids)} panes to declare the group, found {len(claimed)}"
    )

    print(f"Exactly the {len(claimed)} Backup & Recovery panes claim the group.")
    return True


def test_module_resolves_panes_from_the_group():
    """Resolving one removed root id is what broke the module."""
    print("Testing the module resolves its panes from the group attribute...")

    source = _read(DATA_MANAGEMENT_JS)

    assert 'getElementById("data-management")' not in source, (
        "admin_data_management.js still resolves the removed 'data-management' "
        "pane id"
    )
    assert '"data-management",' not in source, (
        "The removed 'data-management' id is still in the bindElements() list"
    )
    assert f"data-admin-group-pane='{GROUP_ID}'" in source, (
        "Expected the module to select its panes by the declared group attribute"
    )
    assert "elements.tabPanes = Array.from(document.querySelectorAll(" in source, (
        "Expected the module to resolve every declared pane, not just the first"
    )
    assert "if (!elements.tabPanes.length) {" in source, (
        "Expected the startup guard to bail only when no pane is present"
    )

    print("The module resolves and guards on the full set of panes.")
    return True


def test_change_tracking_covers_every_pane():
    """Backup and Migrate settings both have to arm the save button."""
    print("Testing change tracking is bound across every pane...")

    source = _read(DATA_MANAGEMENT_JS)
    match = re.search(
        r"function bindDataManagementChangeTracking\(\) \{.*?\n\}", source, re.S
    )
    assert match, "Expected the Data Management change tracking helper"
    body = match.group(0)

    assert "elements.tabPanes.forEach(" in body, (
        "Change tracking must iterate every pane. Binding to a single pane "
        "leaves the other tabs unable to enable the save button."
    )
    assert "markDataManagementModified" in body, (
        "Expected change tracking to mark the settings as modified"
    )
    # The Cosmos Editor is a direct database editor, not a settings surface, so
    # its controls must stay out of the settings modified state.
    assert "data-ignore-data-management-change" in body, (
        "Expected the opt-out that keeps the Cosmos Editor out of settings changes"
    )

    print("Change tracking is bound across every Backup & Recovery pane.")
    return True


def test_settings_controls_live_in_a_tracked_pane():
    """A settings control outside a tracked pane can never be saved."""
    print("Testing saved settings controls sit inside tracked panes...")

    markup = read_admin_settings_template()
    tracked = {
        pane_id: region
        for pane_id, region in _pane_regions(markup).items()
        if GROUP_ATTRIBUTE in region.split(">", 1)[0]
    }

    untracked = []
    for control_id in SETTINGS_CONTROL_IDS:
        needle = f'id="{control_id}"'
        assert needle in markup, f"Expected the '{control_id}' control to exist"
        if not any(needle in region for region in tracked.values()):
            untracked.append(control_id)

    assert not untracked, (
        "Settings controls that saveDataManagementSettings() sends are outside "
        f"every tracked pane, so changing them cannot enable the save button: {untracked}"
    )

    print(f"All {len(SETTINGS_CONTROL_IDS)} sampled settings controls are tracked.")
    return True


def test_global_save_button_defers_to_the_group():
    """Two save buttons appeared once the removed id stopped resolving."""
    print("Testing the global save button hides for Backup & Recovery...")

    source = _read(ADMIN_SETTINGS_JS)
    match = re.search(r"function updateSaveButtonState\(\) \{.*?\n\}", source, re.S)
    assert match, "Expected the global save button state helper"
    body = match.group(0)

    assert "getElementById('data-management')" not in body, (
        "The global save button still tests the removed 'data-management' pane "
        "id, so it stays visible alongside the dedicated Backup & Recovery button"
    )
    assert f'[data-admin-group-pane="{GROUP_ID}"].active' in body, (
        "Expected the global save button to hide while a Backup & Recovery pane "
        "is active, detected through the declared group attribute"
    )

    print("The global save button defers to the Backup & Recovery group.")
    return True


def test_version_supports_the_fix():
    """The fix ships from this version onward."""
    print("Testing the application version carries the fix...")

    version = assert_app_version_at_least(
        "0.261.001",
        reason="Backup & Recovery pane binding fix.",
    )

    print(f"config.py VERSION is {version}.")
    return True


if __name__ == "__main__":
    tests = [
        test_every_bound_element_id_exists,
        test_every_group_tab_declares_its_pane,
        test_no_unrelated_pane_claims_the_group,
        test_module_resolves_panes_from_the_group,
        test_change_tracking_covers_every_pane,
        test_settings_controls_live_in_a_tracked_pane,
        test_global_save_button_defers_to_the_group,
        test_version_supports_the_fix,
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
