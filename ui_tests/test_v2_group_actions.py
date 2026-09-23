# test_v2_group_actions.py
"""
Production-SPA coverage for the native scope-aware V2 group actions workbench.
Version: 0.261.137
Implemented in: 0.261.137

Exercises the real action collection, editor and connection-test path against closed
synthetic HTTP. The fixture only serves the immutable `/api/groups/<id>/actions`
family, never personal `/api/user/plugins` writes, so a group scope that leaked into
personal authoring would fail. A manager creates, edits with a conditional
`expected_revision`, deletes, and tests a connection carrying `action_scope: group`;
an inline `action_actions` gate hides edit and delete per action beside an editable
positive control; an ordinary member gets a read-only workbench; and a stale revision
keeps the draft with a reload offer. A companion runtime check proves a group A draft
never restores into group B or personal scope.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN
from ui_tests.fixtures.group_actions import (  # noqa: F401
    GroupActionsFixture, connect_options, group_actions_ui,
    EDITABLE_ACTION_ID, WITHHELD_ACTION_ID, MEMBER_ACTION_ID,
    IDENTITY_ACTION_ID, PROVIDED_ACTION_ID, BOUND_IDENTITY_ID,
)
from ui_tests.test_v2_workspace_authoring import (
    action_field, begin_action, editor_section, name_field,
)


pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
DRAFT_LOGIC_TS = Path(__file__).parent / "test_v2_group_action_drafts.ts"
SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "group-actions"),
))

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

EDITABLE_NAME = "Weekly report API"
WITHHELD_NAME = "Withheld API"
MEMBER_NAME = "Team charter API"
IDENTITY_NAME = "Bound report API"
PROVIDED_NAME = "Shared platform API"


def open_actions(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/actions", **options)
    expect(ui.page.get_by_role("heading", name="Actions", exact=True)).to_be_visible()


def open_editor(ui, identifier, group="group-a", **options):
    ui.open(f"/groups/{group}/actions/{identifier}", **options)


def row(ui, identifier):
    return ui.page.locator(f'[data-testid="workspace-action"][data-action-id="{identifier}"]')


def collection_get(ui, group="group-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/groups/{group}/actions" and entry.method == "GET"
    ]


def last_write(ui, path, method):
    matches = [
        entry for entry in ui.writes
        if entry.path == path and entry.method == method
    ]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w.method, w.path) for w in ui.writes]}"
    return matches[-1]


def save_action(ui, group_id, *, identifier=None):
    method = "PATCH" if identifier else "POST"
    base = f"/api/groups/{group_id}/actions"
    path = f"{base}/{identifier}" if identifier else base
    with ui.page.expect_response(
        lambda response: response.request.method == method and urlsplit(response.url).path == path
    ) as response:
        ui.page.get_by_role("button", name="Save action", exact=True).click()
    result = response.value
    if result.ok:
        expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/{group_id}/actions")
    return result


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_group_action_layout(group_actions_ui, theme, width, height):
    """The manager collection matches the shell in both themes and both breakpoints."""
    ui = group_actions_ui
    open_actions(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("button", name="New action", exact=True)).to_be_enabled()
    expect(row(ui, EDITABLE_ACTION_ID)).to_be_visible()
    # The native collection carries the Call agent manager below it, not the classic fallback.
    expect(ui.page.get_by_role("heading", name="Call agent", exact=True).first).to_be_visible()
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


def test_group_actions_read_from_the_group_route_only(group_actions_ui):
    """Every list is a group read; no personal /api/user/plugins request is ever made."""
    ui = group_actions_ui
    open_actions(ui)
    expect(row(ui, EDITABLE_ACTION_ID)).to_be_visible()
    assert collection_get(ui), "The collection must load from the group actions route."
    assert not [entry for entry in ui.requests if entry.path == "/api/user/plugins"], (
        "A group workbench must never read personal actions."
    )


def test_group_action_response_identity_is_validated(group_actions_ui):
    """A returned action scoped to another group is refused rather than rendered."""
    ui = group_actions_ui
    # Build the foreign record without the stored credential: its id has no registered secret
    # path, so the projector would echo a real key and trip the credential-boundary guard.
    ui.native_actions["group-a"].append(
        {**ui.record("group-a", EDITABLE_ACTION_ID), "id": "foreign", "group_id": "group-z",
         "displayName": "Foreign API", "action_actions": [], "auth": {"type": "none"}}
    )
    open_actions(ui)
    expect(ui.page.get_by_text(re.compile("does not match this group"))).to_be_visible()
    expect(ui.page.get_by_text("Foreign API", exact=True)).to_have_count(0)


def test_inline_action_actions_gate_edit_and_delete(group_actions_ui):
    """The editable action shows Edit and Delete; the withheld action shows neither."""
    ui = group_actions_ui
    open_actions(ui)
    editable = row(ui, EDITABLE_ACTION_ID)
    expect(editable.get_by_role("link", name=f"Edit {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True)).to_be_visible()

    withheld = row(ui, WITHHELD_ACTION_ID)
    expect(withheld.get_by_role("link", name=f"View {WITHHELD_NAME}", exact=True)).to_be_visible()
    expect(withheld.get_by_role("link", name=f"Edit {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Delete {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_text("Read only", exact=True)).to_be_visible()


def test_group_manager_creates_an_action(group_actions_ui):
    """A manager authors a new action through the group route with no expected_revision."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_actions(ui)
    page.get_by_role("button", name="New action", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/groups/group-a/actions/new")
    begin_action(page, "fixture_custom", "Ledger export")
    result = save_action(ui, "group-a")
    assert result.status == 201
    write = last_write(ui, "/api/groups/group-a/actions", "POST")
    assert set(write.body) == {"updates", "clear_secret_paths", "removed_paths"}
    assert "expected_revision" not in write.body
    assert write.body["updates"]["displayName"] == "Ledger export"
    assert not {"user_id", "is_global", "is_group", "group_id"} & set(write.body["updates"])
    created = next(action for action in ui.native_actions["group-a"] if action["displayName"] == "Ledger export")
    assert created["group_id"] == "group-a" and created["is_group"] is True


def test_group_manager_edits_with_a_conditional_write(group_actions_ui):
    """Editing an action sends expected_revision and only the changed field."""
    ui, page = group_actions_ui, group_actions_ui.page
    revision = ui._action_revision("group-a", EDITABLE_ACTION_ID)
    open_editor(ui, EDITABLE_ACTION_ID)
    name = name_field(page, "action")
    expect(name).to_have_value(EDITABLE_NAME)
    name.fill("Weekly report connector")
    result = save_action(ui, "group-a", identifier=EDITABLE_ACTION_ID)
    assert result.ok
    write = last_write(ui, f"/api/groups/group-a/actions/{EDITABLE_ACTION_ID}", "PATCH")
    assert write.body["expected_revision"] == revision
    assert write.body["updates"] == {"displayName": "Weekly report connector"}
    assert ui.record("group-a", EDITABLE_ACTION_ID)["displayName"] == "Weekly report connector"


def test_edit_preserves_the_stored_secret(group_actions_ui):
    """Renaming an action without touching its key keeps the stored credential masked."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_editor(ui, EDITABLE_ACTION_ID)
    name_field(page, "action").fill("Weekly report renamed")
    result = save_action(ui, "group-a", identifier=EDITABLE_ACTION_ID)
    assert result.ok
    assert ui.record("group-a", EDITABLE_ACTION_ID)["auth"]["key"] == "fixture-only-existing-credential"
    ui.assert_no_secret_storage("Weekly report renamed")


def test_group_manager_deletes_an_action(group_actions_ui):
    """Deleting an action confirms, calls DELETE with no body, and removes the row."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_actions(ui)
    page.get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    expect(page.get_by_role("button", name="Delete action", exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/actions/{EDITABLE_ACTION_ID}"
    ):
        page.get_by_role("button", name="Delete action", exact=True).click()
    expect(row(ui, EDITABLE_ACTION_ID)).to_have_count(0)
    write = last_write(ui, f"/api/groups/group-a/actions/{EDITABLE_ACTION_ID}", "DELETE")
    assert write.body is None
    assert ui.record("group-a", EDITABLE_ACTION_ID) is None


def test_connection_test_carries_the_group_scope(group_actions_ui):
    """A group connection test posts action_scope 'group' with the group ID, not personal."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_editor(ui, EDITABLE_ACTION_ID)
    editor_section(page, "Configuration")
    button = page.get_by_role("button", name="Test OpenAPI connection", exact=True)
    expect(button).to_be_enabled()
    with page.expect_response(
        lambda response: urlsplit(response.url).path == "/api/plugins/test-openapi-connection"
    ):
        button.click()
    write = last_write(ui, "/api/plugins/test-openapi-connection", "POST")
    assert write.body["action_scope"] == "group"
    assert write.body["group_id"] == "group-a"
    # The connection context also identifies the group, so the server tests it in group scope.
    assert write.body["plugin_context"]["scope"] == "group"


def test_conflict_keeps_the_draft_and_offers_a_reload(group_actions_ui):
    """A stale revision keeps the editor and its draft and offers to load the saved action."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_editor(ui, EDITABLE_ACTION_ID)
    name_field(page, "action").fill("Draft in flight")
    ui.touch_action("group-a", EDITABLE_ACTION_ID)
    result = save_action(ui, "group-a", identifier=EDITABLE_ACTION_ID)
    assert result.status == 409
    expect(page.get_by_text(re.compile("changed in another session"))).to_be_visible()
    expect(name_field(page, "action")).to_have_value("Draft in flight")
    page.get_by_role("button", name="Load saved version", exact=True).click()
    dialog = page.get_by_role("dialog", name="Load the saved action?", exact=True)
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Load saved version", exact=True).click()
    expect(name_field(page, "action")).to_have_value(EDITABLE_NAME)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_member_gets_a_read_only_workbench(group_actions_ui, theme, width, height):
    """An ordinary member can read a group action but cannot create, edit or delete."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_actions(ui, group="group-b", theme=theme, width=width, height=height)
    expect(page.get_by_role("button", name="New action", exact=True)).to_be_disabled()
    member = row(ui, MEMBER_ACTION_ID)
    expect(member.get_by_role("link", name=f"View {MEMBER_NAME}", exact=True)).to_be_visible()
    expect(member.get_by_role("button", name=f"Delete {MEMBER_NAME}", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


def test_member_editor_is_read_only(group_actions_ui):
    """A member who deep-links the editor sees details with no name field or Save."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_editor(ui, MEMBER_ACTION_ID, group="group-b")
    expect(page.get_by_role("heading", name="Action details", exact=True)).to_be_visible()
    expect(name_field(page, "action")).to_be_disabled()
    expect(page.get_by_role("button", name="Save action", exact=True)).to_have_count(0)
    assert not [entry for entry in ui.writes if "/actions" in entry.path]


def test_member_editor_loads_the_type_catalogue_without_error(group_actions_ui):
    """A member's editor loads the enriched type catalogue from the group route, read-only."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_editor(ui, MEMBER_ACTION_ID, group="group-b")
    expect(page.get_by_role("heading", name="Action details", exact=True)).to_be_visible()
    # The {"types": [...]} envelope resolves, so there is no catalogue error and the type-specific
    # configuration renders (read-only) rather than falling back to a bare form.
    expect(page.get_by_text(re.compile("Could not load the governed action catalogue"))).to_have_count(0)
    editor_section(page, "Configuration")
    expect(page.locator('[data-testid="openapi-configuration"]')).to_be_visible()
    types_reads = [
        entry for entry in ui.requests
        if entry.path == "/api/groups/group-b/actions/types" and entry.method == "GET"
    ]
    assert types_reads, "The enriched type catalogue must load from the group route for a member."
    assert all(not entry.query for entry in types_reads), "The types route takes no query parameters."


def test_identity_bound_action_keeps_its_binding_without_a_personal_read(group_actions_ui):
    """An identity-bound action edits without listing or requesting personal identities."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_editor(ui, IDENTITY_ACTION_ID)
    name = name_field(page, "action")
    expect(name).to_have_value(IDENTITY_NAME)
    # No reusable group identity route exists yet, so the editor lists none and never falls back to
    # reading the member's personal identities.
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/workspace-identities/")], (
        "A group action editor must not read personal reusable identities."
    )
    name.fill("Bound report connector")
    result = save_action(ui, "group-a", identifier=IDENTITY_ACTION_ID)
    assert result.ok
    write = last_write(ui, f"/api/groups/group-a/actions/{IDENTITY_ACTION_ID}", "PATCH")
    # The binding is unchanged, so it is never echoed back into the write.
    assert "identity_id" not in write.body["updates"]
    assert write.body["updates"] == {"displayName": "Bound report connector"}
    assert ui.record("group-a", IDENTITY_ACTION_ID)["identity_id"] == BOUND_IDENTITY_ID


def test_group_without_the_actions_capability_shows_call_agent(group_actions_ui):
    """Agents on but actions off: the Call agent view renders and the actions route is never read."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_actions(ui, group="group-c")
    # The native workbench never mounts, so there is no create control and no group actions read.
    expect(page.get_by_role("button", name="New action", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Open classic group workspace", exact=True)).to_be_visible()
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/groups/group-c/actions")], (
        "The actions route must not be read when the group action capability is off."
    )


def test_provided_global_action_opens_read_only_from_the_group_route(group_actions_ui):
    """A provided (global) action lists and opens read-only: no edit, delete or connection test."""
    ui, page = group_actions_ui, group_actions_ui.page
    open_actions(ui)
    provided = row(ui, PROVIDED_ACTION_ID)
    expect(provided.get_by_role("link", name=f"View {PROVIDED_NAME}", exact=True)).to_be_visible()
    expect(provided.get_by_role("link", name=f"Edit {PROVIDED_NAME}", exact=True)).to_have_count(0)
    expect(provided.get_by_role("button", name=f"Delete {PROVIDED_NAME}", exact=True)).to_have_count(0)
    expect(provided.get_by_text(re.compile("Provided"))).to_be_visible()

    open_editor(ui, PROVIDED_ACTION_ID)
    expect(page.get_by_role("heading", name="Action details", exact=True)).to_be_visible()
    expect(name_field(page, "action")).to_be_disabled()
    expect(page.get_by_role("button", name="Save action", exact=True)).to_have_count(0)
    editor_section(page, "Configuration")
    expect(page.get_by_text(re.compile("Provided actions are read-only"))).to_be_visible()
    expect(page.get_by_role("button", name="Test OpenAPI connection", exact=True)).to_be_disabled()


def test_group_action_draft_scope_isolation_holds():
    """The draft cache and created-action handoff never cross a scope boundary (runtime)."""
    assert (V2_DIR / "node_modules").is_dir(), (
        "application/v2_ui/node_modules is missing; restore the frontend dependencies first"
    )
    assert DRAFT_LOGIC_TS.exists(), "The draft-scope runtime check is missing."
    bundle = V2_DIR / "node_modules" / ".cache-group-action-drafts.mjs"
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(DRAFT_LOGIC_TS), "--bundle", "--platform=node",
                "--format=esm", "--packages=external", "--define:import.meta.env={}",
                f"--outfile={bundle}", "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)], cwd=str(V2_DIR), capture_output=True, text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the draft-scope runtime checks failed")
    assert "draft scope isolation checks passed" in result.stdout
