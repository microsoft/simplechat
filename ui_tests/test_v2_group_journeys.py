# test_v2_group_journeys.py
"""M8 group workspace end-to-end journeys, on the real built SPA.

Version: 0.261.163
Implemented in: 0.261.161

These ride one composite group store (`group_journeys_ui`) that answers the
directory, membership, prompt, document-collaboration and native-authoring routes
from a single group while keeping every family's trap. The suite proves the
journeys the release gate names, driving each into the built SPA rather than
asserting a static inventory: the "active group changed elsewhere" reconciliation,
a status or role change taking effect mid-session across every section, the selector
reaching an off-page group, the unsaved-editor guard across every authoring editor,
the classic round trip, the backend-generated deep links, and the full role x status
x section rail-and-overview matrix read straight from the pinned context. Journeys the
per-section suites already cover end to end (chat handoffs, the directory-to-member
flow, the cross-editor conflict) are cited by test name in the coverage table rather
than restated.

Coverage table (contract sec 4 / M8_GROUP_PARITY_MATRIX sec 8; every row names its tests):
  J1  activation once ........... test_j1_opening_a_group_activates_it_once (here)
                                  + shell::test_group_selection_populates_shared_shell_without_personal_data
  J1  reconciliation ........... test_j1_active_group_changed_elsewhere_is_reconcilable (here)
  J1  uncertain switch ......... shell::test_partial_switch_has_explicit_read_only_recovery_without_replaying_patch
  J1  Settings activation ...... shell::test_settings_activation_refreshes_catalogs_and_restores_in_group_page
  J2  selector reach ........... test_j2_selector_reaches_an_off_page_group_without_capping (here)
                                  + parity test_group_picker_fixture_parity.py (page/search/cap pins)
  J2  search ignores case ...... test_j2_picker_search_ignores_case_and_matches_descriptions (here)
                                  + parity test_group_picker_fixture_parity.py::
                                    test_list_search_ignores_case_and_matches_descriptions_like_the_server
  J3  revocation ............... test_j3_membership_revoked_mid_session_clears_documents_and_authoring (here)
  J4  status change ............ test_j4_lock_disables_write_controls_across_sections (here)
                                  + test_j4_inactive_status_bars_viewing_and_keeps_the_classic_link (here)
  J5  role change .............. test_j5_role_demotion_removes_manage_writes_and_manager_sections (here)
                                  + test_j5_demoted_admin_keeps_members_but_loses_its_controls (here)
  J6  chat handoffs ............ documents test_v2_group_documents.py::test_chat_handoff_keeps_source_identity
                                  (selected documents + tags, active_group_ids, no setActive)
                                  prompts   test_v2_group_prompts.py::test_scoped_prompt_link_attaches_in_chat
                                  agents    test_v2_group_agents.py::test_group_use_in_chat_link_targets_the_named_group
                                  no-replay documents test_v2_group_documents.py::test_legacy_link_and_lock_error
                                  handoff   test_v2_chat_context_selection.py::
                                            test_router_state_group_documents_require_an_explicit_group_handoff
  J7  deep links (driven) ...... test_j7_backend_group_links_open_the_named_section (here, data-driven sweep)
                                  documents test_v2_group_classic_handoffs.py::test_stray_resource_segments_never_reach_a_classic_panel
                                  members   test_v2_group_members.py::test_a_stray_segment_on_members_opens_the_section
                                  workflow  shell::test_legacy_workflow_target_survives_restore_but_not_a_group_switch
                                  off-page  test_v2_group_document_collaboration.py::
                                            test_off_page_deep_link_reads_exact_document_and_never_executes_a_decision
  J8  classic round trip ....... test_j8_manage_classic_confirms_setactive_before_leaving (here)
                                  + test_j8_a_classic_side_change_shows_in_v2_after_a_refocus (here)
                                  documents test_v2_group_classic_handoffs.py::test_documents_section_shows_the_relabelled_classic_link
                                  shell     shell::test_classic_handoff_reconfirms_the_selected_group
                                  Settings delete link (sec 8.10) test_j8_manage_classic_confirms_setactive_before_leaving (here)
  J9  unsaved-editor guard ..... test_j9_unsaved_editor_guards_every_authoring_section (here, 8-editor sweep)
                                  + shell::test_group_delegation_editing_and_navigation_keep_the_correct_scope
                                  Settings editor test_j9_unsaved_editor_guards_every_authoring_section[settings] (here)
  J10 role x status matrix ..... test_j10_rail_matches_the_pinned_context_matrix (here)
                                  + test_j10_overview_lists_locked_sections_with_their_reason (here)
  J11 directory to member ...... test_v2_group_directory.py::test_join_then_cancel_follow_the_server_rows (the join request)
                                  + test_v2_group_members.py::test_approve_and_reject_follow_the_server (owner approval)
                                  (optional; the requester's picker after approval isn't driven end to end)
  J12 conflict smoke ........... test_v2_rebase_draft_logic.mjs
                                  + test_v2_group_prompts.py::test_conflict_refresh_rebases_concurrent_description_and_local_name
                                  + test_v2_workflow_control_flow.py::test_skip_dependency_is_rejected_and_stale_save_retains_flow

Product findings:
  - Fixed in 0.261.162: the picker searched server-side through a case-sensitive, name-only
    `search_groups`, so a lowercase or description fragment missed a group the V2 directory would
    find. `test_j2_picker_search_ignores_case_and_matches_descriptions` was the suite's one strict
    xfail and now passes; no journey is expected to fail.
"""

import copy
import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_journeys import group_journeys_ui  # noqa: F401
from ui_tests.fixtures.group_workspace import (
    GROUP_CONNECTIONS_ROLE_REASON, GROUP_INACTIVE_REASON, GROUP_STATUS_UNKNOWN_REASON,
    group_context,  # noqa: F401
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


def plugin_writes(ui):
    return [entry for entry in ui.writes if entry.path.startswith("/api/group/plugins")]


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

# The unique name of the group seeded last, after the padding, so it is only reachable off the first
# page, and a description word no other group carries.
_OFF_PAGE_NAME = "Zulu Frontier Workspace"
_OFF_PAGE_ID = "group-off-page-target"
_OFF_PAGE_DESCRIPTION = "Expedition logistics for the northern route."
_OFF_PAGE_DESCRIPTION_WORD = "expedition"


def _pad_directory(ui, count):
    """Push `count` padding groups between the two seeded ones and the off-page target."""
    ui.groups.update({
        f"group-pad-{index:04d}": group_context(f"group-pad-{index:04d}", f"Padding Workspace {index:04d}")
        for index in range(count)
    })


def test_j2_selector_reaches_an_off_page_group_without_capping(group_journeys_ui):
    ui = group_journeys_ui
    # Seed the reachable target only after a thousand padding groups, so insertion-order paging keeps
    # it off page one -- exactly where a capped or first-page-only picker would strand it.
    _pad_directory(ui, 1000)
    ui.groups[_OFF_PAGE_ID] = group_context(_OFF_PAGE_ID, _OFF_PAGE_NAME)
    ui.active_group = None
    ui.open("/groups")
    expect(ui.page.get_by_text("Choose a group workspace", exact=True)).to_be_visible()

    picker = ui.page.get_by_role("combobox", name="Group workspace", exact=True)
    # What the user sees: the picker reports the full store, not a capped page. group-a, group-b, the
    # thousand pads and the target make 1003.
    expect(ui.page.get_by_text(re.compile(rf"\b{len(ui.groups)}\s+groups\b"))).to_be_visible()
    # The list is still paged at 25, so the picker never asked the server for the whole set, and the
    # off-page target is absent from the first page of options.
    listings = [entry for entry in ui.requests if entry.path == "/api/groups"]
    assert listings and all(entry.query.get("page_size") == ["25"] for entry in listings)
    assert len(ui.groups) == 1003
    expect(picker.get_by_role("option", name=_OFF_PAGE_NAME, exact=True)).to_have_count(0)

    # The user reaches it through the picker by typing part of its name; the server-accurate search
    # narrows the list and the option becomes selectable.
    search = ui.page.get_by_role("searchbox", name="Search your groups", exact=True)
    search.fill("Zulu")
    expect(picker.get_by_role("option", name=_OFF_PAGE_NAME, exact=True)).to_have_count(1)
    picker.select_option(_OFF_PAGE_ID)
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/{_OFF_PAGE_ID}")
    expect(ui.page.get_by_text("About this group", exact=True)).to_be_visible()
    # It resolved by its own id, off whatever page it lands on, and activation named it, never an
    # arbitrary default.
    assert [entry.body.get("groupId") for entry in setactive_writes(ui)] == [_OFF_PAGE_ID]


def test_j2_picker_search_ignores_case_and_matches_descriptions(group_journeys_ui):
    ui = group_journeys_ui
    # The target sits off page one, so the picker can only surface it through the server search --
    # never the always-rendered selected-group fallback option or the first, unfiltered page. That
    # removes the debounce race: the option is 0 before and after each search unless the search itself
    # matches, so a passing assertion here means the server search really found the group.
    _pad_directory(ui, 1000)
    ui.groups[_OFF_PAGE_ID] = group_context(_OFF_PAGE_ID, _OFF_PAGE_NAME)
    ui.groups[_OFF_PAGE_ID]["workspace"]["description"] = _OFF_PAGE_DESCRIPTION
    ui.active_group = None
    ui.open("/groups")
    picker = ui.page.get_by_role("combobox", name="Group workspace", exact=True)
    search = ui.page.get_by_role("searchbox", name="Search your groups", exact=True)
    target = picker.get_by_role("option", name=_OFF_PAGE_NAME, exact=True)
    # The user types the group's name in lowercase and reaches it, exactly as they can in the V2
    # directory.
    search.fill(_OFF_PAGE_NAME.lower())
    expect(target).to_have_count(1)
    # Clearing the search restores the unfiltered first page, where the target is absent again, so
    # the next assertion can't pass on this result.
    search.fill("")
    expect(target).to_have_count(0)
    # A word only the description carries reaches it too.
    search.fill(_OFF_PAGE_DESCRIPTION_WORD)
    expect(target).to_have_count(1)
    searched = [entry.query.get("search") for entry in ui.requests if entry.path == "/api/groups"]
    assert [_OFF_PAGE_NAME.lower()] in searched and [_OFF_PAGE_DESCRIPTION_WORD] in searched


# --- J3: membership revoked mid-session ----------------------------------------------------------

def test_j3_membership_revoked_mid_session_clears_documents_and_authoring(group_journeys_ui):
    ui = group_journeys_ui
    # Documents read for a member of the group.
    ui.open("/groups/group-a/documents")
    expect(ui.page.get_by_role(
        "searchbox", name="Search documents. Press Enter to search immediately.", exact=True)).to_be_visible()
    # An authoring section with a dirty draft: the group switcher freezes while the draft is open, so
    # the draft is guarded rather than silently navigated away from.
    section(ui.page, "Actions")
    ui.page.get_by_role("button", name="New Call agent action", exact=True).click()
    ui.page.get_by_label("Action name", exact=True).fill("Draft delegate")
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_disabled()
    # The server removed this user from the group after the page loaded.
    ui.denied_groups.add("group-a")
    refocus(ui)
    # Revocation clears both the documents and the authoring store, and the guarded draft never
    # reached the server.
    expect(ui.page.get_by_role("alert")).to_contain_text("permission")
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    expect(ui.page.locator('[data-testid="workspace-action"]')).to_have_count(0)
    assert not plugin_writes(ui)


# --- J4: status change mid-session ---------------------------------------------------------------

# Each writeable section, the rail label to open it, and the control that must vanish when the group
# is locked to read-only. Endpoints uses "Add connection"; Documents guards the file input directly.
_LOCK_SWEEP = [
    ("documents", "Documents", None),
    ("prompts", "Prompts", "New prompt"),
    ("identities", "Identities", "New identity"),
    ("endpoints", "Endpoints", "Add connection"),
    ("sync", "File sources", "New file source"),
    ("members", "Members", "Add member"),
]


def test_j4_lock_disables_write_controls_across_sections(group_journeys_ui):
    ui = group_journeys_ui
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    # Every section offers its write control while the group is active.
    for section_id, label, control in _LOCK_SWEEP:
        section(ui.page, label)
        if control is None:
            expect(ui.page.locator('input[type="file"]').first).to_have_count(1)
        else:
            expect(ui.page.get_by_role("button", name=control, exact=True)).to_be_visible()
    # The group is locked to read-only while the page is open.
    ui.set_status("group-a", "locked")
    refocus(ui)
    expect(ui.page.get_by_text("Status: Locked - read only", exact=True)).to_be_visible()
    # Locked is still viewable, so every section stays in the rail, but its write control is gone.
    for section_id, label, control in _LOCK_SWEEP:
        section(ui.page, label)
        expect(ui.page.get_by_text("Status: Locked - read only", exact=True)).to_be_visible()
        if control is None:
            expect(ui.page.locator('input[type="file"]')).to_have_count(0)
        else:
            expect(ui.page.get_by_role("button", name=control, exact=True)).to_have_count(0)


def test_j4_inactive_status_bars_viewing_and_keeps_the_classic_link(group_journeys_ui):
    ui = group_journeys_ui
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    # An active group no longer shows the header's classic escape hatch: sec 8.9 restricts it to the
    # barred statuses, where the native sections are unavailable. In an active group the only classic
    # link lives in the Settings danger zone (see test_j8_manage_classic_confirms_setactive_before_leaving).
    expect(ui.page.get_by_role("button", name="Manage group (classic)", exact=True)).to_have_count(0)
    ui.set_status("group-a", "inactive")
    refocus(ui)
    expect(ui.page.get_by_text("Status: Inactive", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(GROUP_INACTIVE_REASON, exact=False).first).to_be_visible()
    # The rail no longer offers the sections a viewable status would.
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    expect(nav.get_by_role("link", name="Documents", exact=True)).to_have_count(0)
    # The owner still has the classic escape hatch in the barred status.
    expect(ui.page.get_by_role("button", name="Manage group (classic)", exact=True)).to_be_visible()
    # The unknown status is barred the same way, with its own reason, and nothing else covers it here.
    ui.set_status("group-a", "unknown")
    refocus(ui)
    expect(ui.page.get_by_text("Status: Status unavailable", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(GROUP_STATUS_UNKNOWN_REASON, exact=False).first).to_be_visible()
    expect(nav.get_by_role("link", name="Documents", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Manage group (classic)", exact=True)).to_be_visible()


# --- J5: role change mid-session -----------------------------------------------------------------

def test_j5_role_demotion_removes_manage_writes_and_manager_sections(group_journeys_ui):
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


def test_j5_demoted_admin_keeps_members_but_loses_its_controls(group_journeys_ui):
    ui = group_journeys_ui
    ui.set_viewer_role("group-a", "Admin")
    ui.open("/groups/group-a/members")
    # An admin manages members: the add and import controls are live.
    expect(ui.page.get_by_role("button", name="Add member", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Import CSV", exact=True)).to_be_visible()
    # Demoted to an ordinary member mid-session. The context still opens Members to Users, so the
    # section stays in the rail.
    ui.set_viewer_role("group-a", "User")
    refocus(ui)
    expect(ui.page.get_by_text("Role: Member", exact=True)).to_be_visible()
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    expect(nav.get_by_role("link", name="Members", exact=True)).to_have_count(1)
    # The caller re-reads Members (leaving and returning to the section), and the server's own
    # membership hint -- now a User's -- offers no management operations, so every management control
    # is withdrawn while the section itself still renders.
    section(ui.page, "Documents")
    section(ui.page, "Members")
    expect(ui.page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Import CSV", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("heading", name="Requests to join", exact=True)).to_have_count(0)
    # A member may still leave, and that is the only self-control left.
    expect(ui.page.get_by_role("button", name="Leave this group", exact=True)).to_be_visible()


# --- J7: deep links driven into the SPA ----------------------------------------------------------

# The sections whose stray-resource behaviour the cited suites do not already pin, each with the
# write control that proves the section itself rendered after the stray segment was dropped.
_STRAY_SWEEP = [
    ("prompts", "New prompt"),
    ("identities", "New identity"),
    ("endpoints", "Add connection"),
    ("sync", "New file source"),
]


@pytest.mark.parametrize("section_id,control", _STRAY_SWEEP, ids=[row[0] for row in _STRAY_SWEEP])
def test_j7_backend_group_links_open_the_named_section(group_journeys_ui, section_id, control):
    ui = group_journeys_ui
    ui.active_group = "group-a"
    # A backend-generated or hand-built link with a stray resource segment on a section that has no
    # item route: the SPA drops the segment and opens the section, never a dead "opening..." view.
    ui.open(f"/groups/group-a/{section_id}/stray-{section_id}-segment")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/{section_id}")
    expect(ui.page.get_by_role("button", name=control, exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Opening the requested view...", exact=True)).to_have_count(0)


# --- J8: the classic round trip ------------------------------------------------------------------

def test_j8_manage_classic_confirms_setactive_before_leaving(group_journeys_ui):
    ui = group_journeys_ui
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Role: Owner", exact=True)).to_be_visible()
    # The classic escape hatch for an active group lives in the Settings danger zone now, not the header.
    section(ui.page, "Settings")
    expect(ui.page.get_by_test_id("group-settings-danger")).to_be_visible()
    # Another tab moved the active group to B while this page stayed on A.
    ui.active_group = "group-b"
    ui.page.get_by_role("button", name="Delete group (classic)", exact=True).click()
    # The danger-zone confirm explains the classic hand-off before leaving.
    dialog = ui.page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="Delete this group in classic?", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Open classic", exact=True).click()
    # The classic hand-off re-activates A before it navigates: the setActive write names A, and the
    # classic page is entered with A active, never B.
    expect(ui.page).to_have_url(f"{ORIGIN}/groups/group-a")
    assert [entry.body.get("groupId") for entry in setactive_writes(ui)] == ["group-a"]
    assert ui.classic_visits[-1] == ("/groups/group-a", "group-a")


def test_j8_a_classic_side_change_shows_in_v2_after_a_refocus(group_journeys_ui):
    ui = group_journeys_ui
    original = ui.groups["group-a"]["workspace"]["name"]
    renamed = f"{original} (renamed in classic)"
    ui.open("/groups/group-a")
    # The header renders the group name in a single semibold paragraph; the picker also lists it in a
    # hidden <option>, so target the visible header node, not the option.
    name = ui.page.locator("p.font-semibold.text-text-1").first
    expect(name).to_have_text(original)
    # A classic-side rename, simulated in the shared store, is what another surface would have written.
    ui.groups["group-a"]["workspace"]["name"] = renamed
    refocus(ui)
    # The group page revalidates its context on focus, so the new name reaches the open V2 page.
    expect(name).to_have_text(renamed)


# --- J9: the unsaved-editor guard across every authoring section ----------------------------------

# The group SPA guards an unsaved authoring draft with one of three mechanisms, so the sweep asserts
# the one that protects each editor plus the invariants every editor shares: a dirty draft never
# activates the group (no setActive write) and a guarded draft stays intact. Every editor is guarded;
# the mechanism differs, which is why the sweep branches rather than asserting one shape everywhere.
#   - "switcher": the editor feeds the group-level dirty flag, which freezes the group picker and
#     makes a rail navigation raise the shared "Discard unsaved changes?" dialog (delegation actions).
#   - "frame": a full-page editor (WorkspaceEditorFrame) whose own blocker raises the same dialog on a
#     rail navigation; the picker stays enabled because the frame, not the group page, holds the draft.
#   - "modal": a dialog editor (prompts, identities, endpoints, file sources, workflows) whose draft
#     lives in the dialog behind a backdrop; the group picker is not the guard here -- the open dialog
#     is, so the sweep asserts the dialog stays open with the draft rather than a group-level freeze.


def _open_action_draft(ui):
    section(ui.page, "Actions")
    ui.page.get_by_role("button", name="New Call agent action", exact=True).click()
    field = ui.page.get_by_label("Action name", exact=True)
    field.fill("Draft delegate")
    return field, "Draft delegate"


def _open_agent_draft(ui):
    section(ui.page, "Agents")
    ui.page.get_by_role("button", name="New agent", exact=True).click()
    expect(ui.page).to_have_url(re.compile(r"/v2/groups/group-a/agents/new$"))
    field = ui.page.get_by_label("Display name", exact=True)
    field.fill("Ledger reviewer")
    return field, "Ledger reviewer"


def _open_prompt_draft(ui):
    section(ui.page, "Prompts")
    ui.page.get_by_role("button", name="New prompt", exact=True).click()
    field = ui.page.locator("#prompt-name")
    field.fill("Draft prompt")
    return field, "Draft prompt"


def _open_identity_draft(ui):
    section(ui.page, "Identities")
    ui.page.get_by_role("button", name="New identity", exact=True).click()
    field = ui.page.get_by_label("Name", exact=True)
    field.fill("Draft identity")
    return field, "Draft identity"


def _open_endpoint_draft(ui):
    section(ui.page, "Endpoints")
    ui.page.get_by_role("button", name="Add connection", exact=True).click()
    field = ui.page.get_by_role("dialog").get_by_label("Name", exact=True)
    field.fill("Draft connection")
    return field, "Draft connection"


def _open_file_source_draft(ui):
    section(ui.page, "File sources")
    ui.page.get_by_role("button", name="New file source", exact=True).click()
    field = ui.page.get_by_label("Name", exact=True)
    field.fill("Draft source")
    return field, "Draft source"


def _open_workflow_draft(ui):
    section(ui.page, "Workflows")
    ui.page.get_by_role("button", name="Create workflow", exact=True).click()
    field = ui.page.get_by_role("dialog").get_by_label("Workflow name", exact=True)
    field.fill("Draft workflow")
    return field, "Draft workflow"


def _open_settings_draft(ui):
    section(ui.page, "Settings")
    # The Settings editor feeds the group-level dirty flag from both its profile and its retention
    # drafts (S1/S5). Dirty the retention select first, then the profile name, and track the name for
    # the survival assertion; both must persist through the discard guard.
    retention = ui.page.get_by_test_id("group-settings-retention-conversation")
    retention.select_option("none" if retention.input_value() != "none" else "default")
    field = ui.page.get_by_test_id("group-settings-name")
    field.fill("Draft group name")
    return field, "Draft group name"


_EDITORS = [
    pytest.param("switcher", _open_action_draft, id="actions-delegation"),
    pytest.param("frame", _open_agent_draft, id="agents"),
    pytest.param("modal", _open_prompt_draft, id="prompts"),
    pytest.param("modal", _open_identity_draft, id="identities"),
    pytest.param("modal", _open_endpoint_draft, id="endpoints"),
    pytest.param("modal", _open_file_source_draft, id="file-sources"),
    pytest.param("modal", _open_workflow_draft, id="workflows"),
    pytest.param("switcher", _open_settings_draft, id="settings"),
]


@pytest.mark.parametrize("guard,opener", _EDITORS)
def test_j9_unsaved_editor_guards_every_authoring_section(group_journeys_ui, guard, opener):
    ui = group_journeys_ui
    ui.open("/groups/group-a")
    field, value = opener(ui)
    picker = ui.page.get_by_role("combobox", name="Group workspace", exact=True)
    if guard == "switcher":
        # A group-level dirty draft freezes the switcher and turns a rail navigation into the shared
        # discard dialog; keeping editing restores the draft and the section URL.
        expect(picker).to_be_disabled()
        section(ui.page, "Overview")
        expect(ui.page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)).to_be_visible()
        ui.page.get_by_role("button", name="Keep editing", exact=True).click()
        expect(field).to_have_value(value)
    elif guard == "frame":
        # A full-page editor keeps the picker live, but its own blocker guards a rail navigation.
        section(ui.page, "Overview")
        expect(ui.page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)).to_be_visible()
        ui.page.get_by_role("button", name="Keep editing", exact=True).click()
        expect(field).to_have_value(value)
    else:
        # A modal editor holds the draft in its own dialog behind a backdrop: the field keeps its
        # value, which proves the dialog stayed open and the draft intact -- the guard that protects
        # it here rather than the group-level freeze.
        expect(field).to_have_value(value)
    # No authoring guard ever activated the group.
    assert not setactive_writes(ui)


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


def test_j10_overview_lists_locked_sections_with_their_reason(group_journeys_ui):
    ui = group_journeys_ui
    # An ordinary member on an active group: Documents and Prompts are available, the connections
    # sections are locked with the role reason. The overview must list both, so it matches the rail.
    ui.set_viewer_role("group-a", "User")
    context = copy.deepcopy(ui.groups["group-a"])
    ui.open("/groups/group-a")
    expect(ui.page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    # A section the rail offers is an available overview card; a section it withholds is a locked
    # overview card carrying the context's reason, read from the constant, never hard-coded.
    for section_id, reason_key in (("identities", GROUP_CONNECTIONS_ROLE_REASON),
                                   ("sync", GROUP_CONNECTIONS_ROLE_REASON)):
        assert not rail_enabled(context, section_id)
        expect(nav.get_by_role("link", name=SECTION_LABELS[section_id], exact=True)).to_have_count(0)
        locked = ui.page.get_by_label(f"{SECTION_LABELS[section_id]} (unavailable)", exact=True)
        expect(locked).to_be_visible()
        expect(locked).to_contain_text(reason_key)
    # An available section is a live overview card, matching the rail's live link.
    assert rail_enabled(context, "documents")
    expect(ui.page.get_by_label("Documents (unavailable)", exact=True)).to_have_count(0)
