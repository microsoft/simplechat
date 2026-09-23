# test_v2_group_workspace_shell.py
"""
Real-SPA group selection, navigation, scope, and draft safety.
Version: 0.261.128
Implemented in: 0.261.127
"""

import copy

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_workspace import (
    connect_options, group_context, group_ui,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui


def section(page, label):
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role("link", name=label, exact=True).click()


def activate(ui, group_id="group-a"):
    ui.page.get_by_role("combobox", name="Group workspace", exact=True).select_option(group_id)
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/{group_id}")
    expect(ui.page.get_by_text("About this group", exact=True)).to_be_visible()


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844),
])
def test_group_selection_populates_shared_shell_without_personal_data(group_ui, theme, width, height):
    ui = group_ui
    ui.open("/groups", theme=theme, width=width, height=height)
    expect(ui.page.get_by_text("Choose a group workspace", exact=True)).to_be_visible()
    assert not [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]
    activate(ui)
    expect(ui.page.get_by_text("Research group owner · owner@example.test", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Role: Owner", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    section(ui.page, "Documents")
    expect(ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Upload", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_be_visible()
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/documents") or entry.path in ("/api/user/plugins", "/api/user/agents")]
    section(ui.page, "Overview")
    ui.assert_no_overflow()


def test_saved_selection_and_off_page_group_resolve_without_an_arbitrary_default(group_ui):
    ui = group_ui
    ui.groups = {
        f"group-{index}": group_context(f"group-{index}", f"Workspace {index:04d}")
        for index in range(1, 1002)
    }
    ui.active_group = "group-1001"
    ui.open("/groups")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-1001")
    expect(ui.page.get_by_role("combobox", name="Group workspace")).to_have_value("group-1001")
    expect(ui.page.get_by_text("Workspace 1001 owner · owner@example.test", exact=True)).to_be_visible()
    assert not [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]
    list_reads = [entry for entry in ui.requests if entry.path == "/api/groups"]
    assert list_reads and all(entry.query["page_size"] == ["25"] for entry in list_reads)
    ui.page.get_by_role("searchbox", name="Search your groups", exact=True).fill("Workspace 0999")
    expect(ui.page.get_by_role("option", name="Workspace 0999", exact=True)).to_have_count(1)
    expect(ui.page.get_by_role("combobox", name="Group workspace")).to_have_value("group-1001")
    assert any(entry.query.get("search") == ["Workspace 0999"] for entry in ui.requests if entry.path == "/api/groups")


def test_failed_activation_keeps_previous_page_and_does_not_load_target_resources(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/groups/group-a/actions")
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_be_visible()
    ui.reject_next("PATCH", "/api/groups/setActive", status=403, error="Denied selection.")
    ui.page.get_by_role("combobox", name="Group workspace").select_option("group-b")
    expect(ui.page.get_by_role("alert")).to_contain_text("permission")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/actions")
    expect(ui.page.get_by_role("combobox", name="Group workspace")).to_have_value("group-a")
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/group/") and entry.query.get("group_id") == ["group-b"]]
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/groups/group-b/actions")], (
        "A failed activation must not load the target group's native actions."
    )


def test_partial_switch_has_explicit_read_only_recovery_without_replaying_patch(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/groups/group-a")
    ui.reject_next("GET", "/api/v2/bootstrap")
    ui.page.get_by_role("combobox", name="Group workspace").select_option("group-b")
    expect(ui.page.get_by_role("button", name="Refresh workspace selection", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("combobox", name="Group workspace")).to_be_disabled()
    patches = [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]
    assert len(patches) == 1
    ui.page.get_by_role("button", name="Refresh workspace selection", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-b")
    expect(ui.page.get_by_text("Role: Member", exact=True)).to_be_visible()
    assert len([entry for entry in ui.writes if entry.path == "/api/groups/setActive"]) == 1


def test_group_delegation_editing_and_navigation_keep_the_correct_scope(group_ui):
    ui = group_ui
    ui.open("/groups/group-a/actions")
    ui.page.get_by_role("button", name="New Call agent action", exact=True).click()
    ui.page.get_by_label("Action name", exact=True).fill("Team delegate")
    expect(ui.page.get_by_role("combobox", name="Group workspace")).to_be_disabled()
    section(ui.page, "Overview")
    expect(ui.page.get_by_role("dialog", name="Discard unsaved changes?")).to_be_visible()
    ui.page.get_by_role("button", name="Keep editing", exact=True).click()
    expect(ui.page.get_by_label("Action name", exact=True)).to_have_value("Team delegate")
    ui.page.get_by_label("Target agent", exact=True).select_option(label="Group reviewer · group · local")
    ui.page.get_by_role("button", name="Save Call agent action", exact=True).click()
    expect(ui.page.get_by_text("Call agent action saved.", exact=True)).to_be_visible()
    writes = [entry for entry in ui.writes if entry.path == "/api/group/plugins"]
    assert writes[-1].query == {"group_id": ["group-a"]}
    assert ui.group_actions["group-a"][-1]["displayName"] == "Team delegate"
    ui.page.get_by_role("button", name="Edit Call agent action Team delegate", exact=True).click()
    ui.page.get_by_label("Action name", exact=True).fill("Team renamed")
    ui.page.get_by_role("button", name="Save Call agent action", exact=True).click()
    expect(ui.page.get_by_text("Team renamed", exact=True)).to_be_visible()
    assert ui.writes[-1].method == "PATCH"
    assert ui.writes[-1].query == {"group_id": ["group-a"]}
    ui.page.get_by_role("button", name="Attach Call agent actions to Local caller", exact=True).click()
    ui.page.get_by_role("checkbox", name="Team renamed").check()
    ui.page.get_by_role("button", name="Save bindings", exact=True).click()
    expect(ui.page.get_by_text("Call agent bindings saved.", exact=True)).to_be_visible()
    assert ui.writes[-1].path == "/api/group/agents/caller/agent-actions"
    assert ui.writes[-1].query == {"group_id": ["group-a"]}
    ui.page.get_by_role("combobox", name="Group workspace").select_option("group-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-b/actions")
    expect(ui.page.get_by_text("Read-only access.", exact=False)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)


def test_owner_only_catalog_can_deny_group_management(group_ui):
    ui = group_ui
    ui.delegation_manage = False
    ui.open("/groups/group-a/actions")
    expect(ui.page.get_by_text("Read-only access.", exact=False)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    assert not [entry for entry in ui.writes if entry.path.startswith("/api/group/")]


def test_group_action_delete_preserves_callers(group_ui):
    ui = group_ui
    before = copy.deepcopy(ui.group_agents)
    ui.open("/groups/group-a/actions")
    ui.page.get_by_role("button", name="Delete Call agent action Call group reviewer", exact=True).click()
    assert not [entry for entry in ui.writes if entry.method == "DELETE"]
    ui.page.get_by_role("button", name="Confirm delete", exact=True).click()
    expect(ui.page.get_by_text("Call agent action deleted.", exact=False)).to_be_visible()
    assert ui.group_agents == before
    assert ui.writes[-1].path == "/api/group/plugins/group-call"
    assert ui.writes[-1].query == {"group_id": ["group-a"]}


def test_native_workflows_and_read_only_roles(group_ui):
    ui = group_ui
    ui.open("/groups/group-a/workflows")
    expect(ui.page.get_by_text("Review group files", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Run Review group files", exact=True).click()
    expect(ui.page.get_by_role("button", name="Cancel Review group files", exact=True)).to_be_visible()
    assert ui.writes[-1].query == {"group_id": ["group-a"]}
    ui.page.get_by_role("button", name="Cancel Review group files", exact=True).click()
    expect(ui.page.get_by_role("button", name="Run Review group files", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(ui.page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    ui.page.get_by_label("Workflow name", exact=True).fill("Unsaved group workflow")
    expect(ui.page.get_by_role("combobox", name="Group workspace")).to_be_disabled()
    ui.page.get_by_role("button", name="Cancel", exact=True).click()
    ui.page.get_by_role("button", name="Discard changes", exact=True).click()
    ui.page.get_by_role("combobox", name="Group workspace").select_option("group-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-b/workflows")
    expect(ui.page.get_by_role("button", name="Create workflow", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Run Review group files", exact=True)).to_have_count(0)


def test_refocus_retains_dirty_draft_and_blocks_saving_until_access_is_confirmed(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/groups/group-a/actions")
    ui.page.get_by_role("button", name="New Call agent action", exact=True).click()
    ui.page.get_by_label("Action name", exact=True).fill("Retained draft")
    ui.page.get_by_label("Target agent", exact=True).select_option(label="Group reviewer · group · local")
    ui.reject_next("GET", "/api/v2/workspaces/group/group-a")
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(ui.page.get_by_role("alert")).to_contain_text("Your changes are kept")
    expect(ui.page.get_by_label("Action name", exact=True)).to_have_value("Retained draft")
    expect(ui.page.get_by_role("button", name="Save Call agent action", exact=True)).to_be_disabled()
    ui.page.get_by_role("button", name="Retry workspace details", exact=True).click()
    expect(ui.page.get_by_role("button", name="Save Call agent action", exact=True)).to_be_enabled()
    expect(ui.page.get_by_label("Action name", exact=True)).to_have_value("Retained draft")


def test_classic_handoff_reconfirms_the_selected_group(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/groups/group-a/documents")
    ui.active_group = "group-b"
    ui.page.get_by_role("button", name="Open classic group workspace", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/group_workspaces")
    assert ui.classic_visits == [("/group_workspaces", "group-a")]


def test_disabled_and_revoked_workspaces_do_not_fetch_resources(group_ui):
    ui = group_ui
    ui.group_enabled = False
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Group workspaces are not enabled", exact=True)).to_be_visible()
    assert not [entry for entry in ui.requests if entry.path == "/api/groups" or entry.path.startswith("/api/v2/workspaces/")]


def test_missing_group_is_an_error_not_a_fallback_to_the_active_group(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/groups/missing")
    expect(ui.page.get_by_role("alert")).to_contain_text("no longer exists")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/missing")
    assert not [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]


def test_membership_revocation_clears_the_selected_resources(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/groups/group-a/actions")
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_be_visible()
    expect(ui.page.locator('[data-testid="workspace-action"]')).not_to_have_count(0)
    ui.denied_groups.add("group-a")
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(ui.page.get_by_role("alert")).to_contain_text("permission")
    expect(ui.page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    expect(ui.page.get_by_text("Call group reviewer", exact=True)).to_have_count(0)
    expect(ui.page.locator('[data-testid="workspace-action"]')).to_have_count(0)


def test_group_labels_render_as_text_not_markup(group_ui):
    ui = group_ui
    text = '<img src=x onerror="window.groupLabelExecuted=true">'
    ui.groups["group-a"]["workspace"].update({"name": text, "description": text})
    ui.open("/groups/group-a")
    description = ui.page.locator("dd").filter(has_text=text)
    expect(description).to_be_visible()
    expect(description).to_have_text(text)
    executed = ui.page.evaluate("window.groupLabelExecuted === true")
    assert executed is False
    assert not ui.unexpected_requests


def test_settings_activation_refreshes_catalogs_and_restores_in_group_page(group_ui):
    ui = group_ui
    ui.open("/settings?tab=groups")
    item = ui.page.get_by_role("listitem").filter(has_text="Research group")
    item.get_by_role("button", name="Set active", exact=True).click()
    expect(item.get_by_text("Active", exact=True)).to_be_visible()
    assert any(entry.path == "/api/v2/bootstrap" for entry in ui.requests)
    ui.page.get_by_role("link", name="Group Workspaces", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a")
    expect(ui.page.get_by_text("Research group owner · owner@example.test", exact=True)).to_be_visible()


def test_back_navigation_can_keep_or_discard_a_group_draft(group_ui):
    ui = group_ui
    ui.open("/groups")
    activate(ui)
    section(ui.page, "Actions")
    ui.page.get_by_role("button", name="New Call agent action", exact=True).click()
    ui.page.get_by_label("Action name", exact=True).fill("Back navigation draft")
    ui.page.go_back()
    expect(ui.page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Keep editing", exact=True).click()
    expect(ui.page.get_by_label("Action name", exact=True)).to_have_value("Back navigation draft")
    section(ui.page, "Overview")
    ui.page.get_by_role("button", name="Discard changes", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a")
    assert not [entry for entry in ui.writes if entry.path.startswith("/api/group/")]


def test_legacy_workflow_target_survives_restore_but_not_a_group_switch(group_ui):
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/groups?workflow_id=workflow-1")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/workflows?workflow_id=workflow-1")
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Cancel", exact=True).click()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    ui.page.get_by_role("combobox", name="Group workspace").select_option("group-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-b/workflows")
    expect(ui.page.get_by_role("dialog")).to_have_count(0)


def test_group_selection_does_not_block_its_own_restore_navigation(group_ui):
    ui = group_ui
    ui.open("/groups")
    ui.page.evaluate("""() => {
        window.unexpectedGroupDialog = false;
        window.groupDialogObserver = new MutationObserver(() => {
            if (document.querySelector('dialog[open]')) window.unexpectedGroupDialog = true;
        });
        window.groupDialogObserver.observe(document.body, {
            childList: true, subtree: true, attributes: true, attributeFilter: ['open'],
        });
    }""")
    try:
        activate(ui)
        expect(ui.page.get_by_role("dialog")).to_have_count(0)
        unexpected = ui.page.evaluate("window.unexpectedGroupDialog")
        assert unexpected is False
    finally:
        ui.page.evaluate("window.groupDialogObserver.disconnect()")
