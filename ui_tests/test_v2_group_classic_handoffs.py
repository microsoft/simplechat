# test_v2_group_classic_handoffs.py
"""
M8A classic handoff cleanup for the native V2 group workspace.
Version: 0.261.154
Implemented in: 0.261.154

Every group workspace section is native now, so the V2 group pages must stop sending people to
classic where classic offers nothing more. This suite pins that the "Classic" availability labels
and the overview's Classic promise are gone, that a stray resource segment redirects to its own
section (or the workflow query) instead of a classic panel, that the actions-off surface keeps only
the Call agent view, that Tags drops its classic button, and that Documents keeps a relabelled
classic-tools link (classic still owns the legacy-document upgrade).
"""

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_workspace import (
    connect_options, group_context, group_ui,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui

OLD_OVERVIEW_COPY = "Shared documents, prompts and automation for this group. Sections marked Classic open in the existing interface while their V2 experience is being built."
NEW_OVERVIEW_COPY = "Shared documents, prompts and automation for this group. A locked section shows why it's unavailable to you."
REMOVED_PANEL_COPY = "This section is available in the classic group workspace."
CLASSIC_BUTTON = "Open classic group workspace"


def section(page, label):
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role("link", name=label, exact=True).click()


def set_active_writes(ui):
    return [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]


def test_manager_overview_carries_no_classic_labels(group_ui):
    ui = group_ui
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("About this group", exact=True)).to_be_visible()
    main = ui.page.get_by_role("main")
    expect(main.get_by_text(NEW_OVERVIEW_COPY, exact=True)).to_be_visible()
    expect(main.get_by_text(OLD_OVERVIEW_COPY, exact=True)).to_have_count(0)
    expect(main.get_by_text("Classic", exact=True)).to_have_count(0)
    ui.assert_clean()


def test_member_overview_shows_the_reason_not_a_classic_label(group_ui):
    ui = group_ui
    ui.open("/groups/group-b")
    expect(ui.page.get_by_text("About this group", exact=True)).to_be_visible()
    main = ui.page.get_by_role("main")
    # A read-only member cannot manage the group's connections, so Identities and Sync are locked
    # with the server's reason rather than pointed at a classic tab.
    expect(main.get_by_text("Your role does not permit managing group connections.", exact=True).first).to_be_visible()
    expect(main.get_by_text("Classic", exact=True)).to_have_count(0)
    expect(main.get_by_role("button", name=CLASSIC_BUTTON, exact=True)).to_have_count(0)
    ui.assert_clean()


def test_actions_off_with_call_agent_on_drops_the_classic_button(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    # A delegation-only workspace: the group action capability is off (the backend empties the
    # management hint to match), but the Call agent tools (native_delegation) stay on, so the nav
    # slot advertises Call agent and the section renders the delegation manager with no classic
    # handoff. This mirrors the group-c shape the group_actions fixture models.
    actions = ui.groups["group-a"]["sections"]["actions"]
    actions["enabled"] = False
    actions["can_manage"] = False
    actions["reason"] = "Group actions are turned off for this workspace."
    ui.groups["group-a"]["action_management"] = {"schema_version": 1, "operations": []}
    ui.open("/groups/group-a")
    overview = ui.page.get_by_role("main")
    expect(overview.get_by_text("Call agent", exact=True).first).to_be_visible()
    expect(overview.get_by_text("Classic", exact=True)).to_have_count(0)

    ui.open("/groups/group-a/actions")
    expect(ui.page.get_by_text(
        "Group actions are turned off for this group. You can still choose which agents this group "
        "can call and which local actions may trigger them.",
        exact=True,
    )).to_be_visible()
    expect(ui.page.get_by_role("button", name=CLASSIC_BUTTON, exact=True)).to_have_count(0)
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/groups/group-a/actions")], (
        "The group action route must not be read when the capability is off."
    )
    ui.assert_clean()


def test_stray_resource_segments_never_reach_a_classic_panel(group_ui):
    ui = group_ui
    # The group is already active, so any /api/groups/setActive that follows is proof the redirect
    # re-activated the group rather than merely dropping the stray segment.
    ui.active_group = "group-a"

    ui.open("/groups/group-a/documents/stray-document")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/documents")
    expect(ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(REMOVED_PANEL_COPY, exact=True)).to_have_count(0)

    ui.open("/groups/group-a/tags/stray-tag")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/tags")
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(REMOVED_PANEL_COPY, exact=True)).to_have_count(0)

    # A resource segment on Workflows becomes the ?workflow_id= query the section already understands.
    ui.open("/groups/group-a/workflows/workflow-1")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/workflows?workflow_id=workflow-1")
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(REMOVED_PANEL_COPY, exact=True)).to_have_count(0)

    # An unknown section keeps its own not-found state, and still never a classic panel.
    ui.open("/groups/group-a/not-a-section/xyz")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/not-a-section/xyz")
    expect(ui.page.get_by_text("Section not found", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(REMOVED_PANEL_COPY, exact=True)).to_have_count(0)

    assert not set_active_writes(ui), "A stray-segment redirect must never re-activate the group."
    assert not ui.classic_visits, "A stray-segment redirect must never fall through to a classic page."
    ui.assert_clean()


def test_tags_section_has_no_classic_button(group_ui):
    ui = group_ui
    ui.open("/groups/group-a/tags")
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name=CLASSIC_BUTTON, exact=True)).to_have_count(0)
    ui.assert_clean()


def test_documents_section_shows_the_relabelled_classic_link(group_ui):
    ui = group_ui
    ui.open("/groups/group-a/documents")
    link = ui.page.get_by_role("button", name="Open classic tools for group documents", exact=True)
    expect(link).to_be_visible()
    expect(link).to_contain_text("Classic tools")
    # The generic classic-group-workspace button is gone; only the documents-scoped tools link remains.
    expect(ui.page.get_by_role("button", name=CLASSIC_BUTTON, exact=True)).to_have_count(0)
    ui.assert_clean()


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844),
])
def test_classic_cleanup_layout(group_ui, theme, width, height):
    ui = group_ui
    ui.open("/groups/group-a/documents", theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("button", name="Open classic tools for group documents", exact=True)).to_be_visible()
    ui.assert_no_overflow()

    ui.open("/groups/group-a", theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("main").get_by_text(NEW_OVERVIEW_COPY, exact=True)).to_be_visible()
    ui.assert_no_overflow()
    ui.assert_clean()
