# test_v2_group_journeys.py
"""M8 group workspace end-to-end journeys, on the real built SPA.

Version: 0.261.157
Implemented in: 0.261.157

These ride one composite group store (`group_journeys_ui`) that answers the
directory, membership, prompt, document-collaboration and native-authoring routes
from a single group while keeping every family's trap. The suite proves the
journeys the release gate names that the per-section suites cannot: the
"active group changed elsewhere" reconciliation, a status or role change taking
effect mid-session, and the full role x status x section rail matrix read straight
from the pinned context. The remaining journeys (chat handoffs, deep links, the
classic round trip, the directory-to-member flow, the cross-editor conflict) are
covered by the existing suites cited in the coverage table below, so this file adds
the cross-section journeys rather than restating them.

Coverage table (contract sec 4; existing suites cited by test name):
  J1 activation once ....... test_j1_opening_a_group_activates_it_once (here)
                             + shell test_group_selection_populates_shared_shell_without_personal_data
  J1 reconciliation ........ test_j1_active_group_changed_elsewhere_is_reconcilable (here, new)
  J1 uncertain switch ...... shell test_partial_switch_has_explicit_read_only_recovery_without_replaying_patch
  J1 Settings activation ... shell test_settings_activation_refreshes_catalogs_and_restores_in_group_page
  J2 selector reach ........ test_j2_selector_reaches_an_off_page_group_without_capping (here)
                             + shell test_saved_selection_and_off_page_group_resolve_without_an_arbitrary_default
  J3 revocation ............ test_j3_membership_revoked_mid_session_clears_the_store (here)
  J4 status change ......... test_j4_status_change_mid_session_locks_write_controls (here)
  J5 role change ........... test_j5_role_demotion_mid_session_removes_manage_and_writes (here)
  J6 chat handoffs ......... test_v2_group_documents.py / test_v2_group_prompts.py / test_v2_group_agents.py
                             (Use in chat / selected-document handoffs)
  J7 deep links ............ test_public_workspace_notification_links_fix.py (the /v2 link inventory)
                             + shell test_legacy_workflow_target_survives_restore_but_not_a_group_switch
  J8 classic round trip .... shell test_classic_handoff_reconfirms_the_selected_group
                             (PENDING M7C-FE: the Settings delete link)
  J9 unsaved-editor guard .. test_j9_unsaved_editor_blocks_switch_and_navigation (here)
                             + shell test_group_delegation_editing_and_navigation_keep_the_correct_scope
                             (PENDING M7C-FE: the Settings editor)
  J10 role x status matrix . test_j10_rail_matches_the_pinned_context_matrix (here, new)
  J11 directory to member .. test_v2_group_directory.py (join request + owner approval)
  J12 conflict smoke ....... test_v2_rebase_draft_logic.mjs + workflow editor refuse-and-keep suites

xfail product findings: none. Every drift found while pinning the picker was in the
fixture and is fixed in group_journeys.py / group_directory_harness.py; no product
code reads a field the server never sends.
"""

import copy

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_journeys import group_journeys_ui  # noqa: F401
from ui_tests.fixtures.group_workspace import (
    GROUP_INACTIVE_REASON, GROUP_STATUS_UNKNOWN_REASON, group_context,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui


# The rail label for each section id, mirrored from pages/workspace/sections.tsx and
# groupManageSections.ts so the matrix can name the link the SPA renders. The shell suite
# hardcodes the same visible strings ("Documents", "Overview"); the picker and context
# parity pins guard the underlying ids from drifting.
SECTION_LABELS = {
    "documents": "Documents", "tags": "Tags", "sync": "File sources",
    "prompts": "Prompts", "agents": "Agents", "actions": "Actions",
    "workflows": "Workflows", "identities": "Identities", "endpoints": "Endpoints",
    "members": "Members",
}

# The header's friendly role and status strings, mirrored from lib/groupWorkspaceNavigation.ts
# (GROUP_ROLE_LABELS / GROUP_STATUS_LABELS). A raw "DocumentManager" or "locked" would leak
# if these drifted, which the shell header assertions also pin.
ROLE_LABELS = {
    "Owner": "Owner", "Admin": "Admin",
    "DocumentManager": "Document manager", "User": "Member",
}
STATUS_LABELS = {
    "active": "Active", "locked": "Locked - read only",
    "upload_disabled": "Uploads disabled", "inactive": "Inactive",
    "unknown": "Status unavailable",
}


def section(page, label):
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role(
        "link", name=label, exact=True).click()


def refocus(ui):
    # The App refreshes the bootstrap on focus, and the group page revalidates its context;
    # this is how a change another actor made server-side reaches an open page.
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")


def setactive_writes(ui):
    return [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]


def rail_enabled(context, section_id):
    """Whether the rail shows a section, exactly as groupWorkspaceNavigationAvailability decides.

    Every id reads its own `enabled`, except `actions`: the navigation availability swaps in
    `native_delegation` whenever that is enabled, so the Call agent tools stay reachable even
    when the full actions tab is off.
    """
    if section_id == "actions":
        return bool(context["native_delegation"]["enabled"]) or bool(context["sections"]["actions"]["enabled"])
    return bool(context["sections"][section_id]["enabled"])


# --- J1: activation and reconciliation -----------------------------------------------------------

def test_j1_opening_a_group_activates_it_once(group_journeys_ui):
    ui = group_journeys_ui
    # No group is active yet, so opening group A is a real activation.
    ui.active_group = None
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Role: Owner", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    assert [entry.body.get("groupId") for entry in setactive_writes(ui)] == ["group-a"]
    # A refocus refreshes the bootstrap and revalidates the context, but the group is already
    # active, so it must not activate a second time.
    refocus(ui)
    expect(ui.page.get_by_text("About this group", exact=True)).to_be_visible()
    assert len(setactive_writes(ui)) == 1


def test_j1_active_group_changed_elsewhere_is_reconcilable(group_journeys_ui):
    ui = group_journeys_ui
    # Group A is the active group, so opening it reads without activating.
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Role: Owner", exact=True)).to_be_visible()
    assert not setactive_writes(ui)
    # Another tab activates group B: a server-side active-group change, surfaced by a refocus.
    ui.active_group = "group-b"
    refocus(ui)
    banner = ui.page.get_by_text("Your active group changed elsewhere", exact=False)
    expect(banner).to_be_visible()
    make_active = ui.page.get_by_role("button", name="Make this group active", exact=True)
    expect(make_active).to_be_enabled()
    # The page stayed on A while B was active elsewhere: no silent switch, no stale write.
    assert not setactive_writes(ui)
    make_active.click()
    expect(ui.page.get_by_text("Your active group changed elsewhere", exact=False)).to_have_count(0)
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a")
    # Reconciling re-activates A, and nothing ever activated B from this page.
    assert [entry.body.get("groupId") for entry in setactive_writes(ui)] == ["group-a"]


# --- J2: selector reach --------------------------------------------------------------------------

def test_j2_selector_reaches_an_off_page_group_without_capping(group_journeys_ui):
    ui = group_journeys_ui
    # Pad the store past a thousand groups without disturbing the two seeded ones, so group A is
    # only reachable off the first page.
    ui.groups.update({
        f"group-pad-{index:04d}": group_context(f"group-pad-{index:04d}", f"Workspace {index:04d}")
        for index in range(1, 1001)
    })
    ui.active_group = None
    ui.open("/groups")
    expect(ui.page.get_by_text("Choose a group workspace", exact=True)).to_be_visible()
    listings = [entry for entry in ui.requests if entry.path == "/api/groups"]
    # More than a thousand groups, and the list is still paged at 25: the picker never asks the
    # server for the whole set.
    assert len(ui.groups) > 1000
    assert listings and all(entry.query.get("page_size") == ["25"] for entry in listings)
    # A specific group resolves by its own id, off whatever page it lands on, without an
    # arbitrary default.
    ui.open("/groups/group-a")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a")
    expect(ui.page.get_by_text("About this group", exact=True)).to_be_visible()
    assert [entry.body.get("groupId") for entry in setactive_writes(ui)] == ["group-a"]


# --- J3: membership revoked mid-session ----------------------------------------------------------

def test_j3_membership_revoked_mid_session_clears_the_store(group_journeys_ui):
    ui = group_journeys_ui
    ui.open("/groups/group-a/actions")
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_be_visible()
    expect(ui.page.locator('[data-testid="workspace-action"]')).not_to_have_count(0)
    # The server removed this user from the group after the page loaded.
    ui.denied_groups.add("group-a")
    refocus(ui)
    expect(ui.page.get_by_role("alert")).to_contain_text("permission")
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    expect(ui.page.locator('[data-testid="workspace-action"]')).to_have_count(0)


# --- J4: status change mid-session ---------------------------------------------------------------

def test_j4_status_change_mid_session_locks_write_controls(group_journeys_ui):
    ui = group_journeys_ui
    ui.open("/groups/group-a/actions")
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_be_visible()
    # The group is locked to read-only while the page is open.
    ui.set_status("group-a", "locked")
    refocus(ui)
    expect(ui.page.get_by_text("Status: Locked - read only", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Read-only access.", exact=False)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    # A read-only status writes nothing.
    assert not [entry for entry in ui.writes if entry.path.startswith("/api/group/plugins")]


# --- J5: role change mid-session -----------------------------------------------------------------

def test_j5_role_demotion_mid_session_removes_manage_and_writes(group_journeys_ui):
    ui = group_journeys_ui
    ui.set_viewer_role("group-a", "Admin")
    ui.open("/groups/group-a/actions")
    expect(ui.page.get_by_text("Role: Admin", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_be_visible()
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    # Admin is a content manager, so the connections sections are in the rail.
    expect(nav.get_by_role("link", name="Identities", exact=True)).to_have_count(1)
    expect(nav.get_by_role("link", name="File sources", exact=True)).to_have_count(1)
    # The user demoted themselves to an ordinary member in Members.
    ui.set_viewer_role("group-a", "User")
    refocus(ui)
    expect(ui.page.get_by_text("Role: Member", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Read-only access.", exact=False)).to_be_visible()
    # No stale control is left: the write button and the manager-only sections are gone.
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    expect(nav.get_by_role("link", name="Identities", exact=True)).to_have_count(0)
    expect(nav.get_by_role("link", name="File sources", exact=True)).to_have_count(0)


# --- J9: the unsaved-editor guard ----------------------------------------------------------------

def test_j9_unsaved_editor_blocks_switch_and_navigation(group_journeys_ui):
    ui = group_journeys_ui
    ui.open("/groups/group-a/actions")
    ui.page.get_by_role("button", name="New Call agent action", exact=True).click()
    ui.page.get_by_label("Action name", exact=True).fill("Draft delegate")
    # A dirty draft freezes the group switcher and guards navigation away.
    expect(ui.page.get_by_role("combobox", name="Group workspace")).to_be_disabled()
    section(ui.page, "Overview")
    expect(ui.page.get_by_role("dialog", name="Discard unsaved changes?")).to_be_visible()
    ui.page.get_by_role("button", name="Keep editing", exact=True).click()
    expect(ui.page.get_by_label("Action name", exact=True)).to_have_value("Draft delegate")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/actions")
    # The guarded draft never reached the server.
    assert not [entry for entry in ui.writes if entry.path.startswith("/api/group/plugins")]


# --- J10: the role x status x section matrix -----------------------------------------------------

# raw status sent to the fixture, and the status the server coerces it to. An unrecognized status
# (here "frozen") becomes "unknown", exactly as group_context does.
_STATUSES = [("active", "active"), ("locked", "locked"),
             ("upload_disabled", "upload_disabled"), ("inactive", "inactive"), ("frozen", "unknown")]
_ROLES = ["Owner", "Admin", "DocumentManager", "User"]

_MATRIX = [
    pytest.param(role, raw, coerced, 1440, 900, id=f"{role}-{coerced}-desktop")
    for role in _ROLES for raw, coerced in _STATUSES
] + [
    # Contract sec 2: run one role at 390x844, across a viewable and a non-viewable status.
    pytest.param("Owner", raw, coerced, 390, 844, id=f"Owner-{coerced}-mobile")
    for raw, coerced in (("active", "active"), ("frozen", "unknown"))
]


@pytest.mark.parametrize("role,raw_status,status,width,height", _MATRIX)
def test_j10_rail_matches_the_pinned_context_matrix(group_journeys_ui, role, raw_status, status, width, height):
    ui = group_journeys_ui
    ui.set_viewer_role("group-a", role, status=raw_status)
    context = copy.deepcopy(ui.groups["group-a"])
    assert context["role"] == role and context["status"] == status
    ui.open("/groups/group-a", width=width, height=height)
    # The header names the role and the status exactly as the pinned context does.
    expect(ui.page.get_by_text(f"Role: {ROLE_LABELS[role]}", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(f"Status: {STATUS_LABELS[status]}", exact=True)).to_be_visible()
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    # Every rail section is present or absent exactly as the context says; a disabled section is
    # never a live link, so nothing offers a control the context withholds.
    for section_id, label in SECTION_LABELS.items():
        expected = 1 if rail_enabled(context, section_id) else 0
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_count(expected)
    if status in ("inactive", "unknown"):
        # A status that bars viewing leaves nothing in the rail; the overview carries the reason.
        reason = GROUP_INACTIVE_REASON if status == "inactive" else GROUP_STATUS_UNKNOWN_REASON
        expect(ui.page.get_by_text(reason, exact=False).first).to_be_visible()
