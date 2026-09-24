# test_v2_group_identities.py
"""
Production-SPA coverage for the native scope-aware V2 group identities section.
Version: 0.261.138
Implemented in: 0.261.138

Exercises the real identities section and its editor dialog against closed synthetic
HTTP. The fixture serves only the immutable `/api/groups/<id>/identities` family and
never a personal `/api/user/*` or `/api/workspace-identities/personal/*` read, so a
group scope that leaked into personal identities would fail the run rather than be
answered. A manager creates through the group route with no `expected_etag`, edits
with a conditional write that keeps the stored secret masked, deletes with an
`expected_etag`-only body, and keeps the draft open on a stale-etag 409; an inline
`identity_actions` gate hides edit and delete per identity beside an editable
positive control; a delete refused because the identity is still referenced names
what uses it; the server's reviewed validation message renders verbatim; and a
member's manager-only section is unavailable. Two action-editor checks close the M4
gap: a manager's editor lists the group's action-usage identities (excluding the
File Sync one) from the group route with no personal read, and a member's editor
turns the 403 into a silent unresolved list rather than a personal identity read.
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401
from ui_tests.fixtures.group_identities import (  # noqa: F401
    GroupIdentitiesFixture, group_identities_ui,
    EDITABLE_IDENTITY_ID, WITHHELD_IDENTITY_ID, FILE_SYNC_IDENTITY_ID,
    IN_USE_IDENTITY_ID, CONNECTOR_ACTION_ID,
)
from ui_tests.test_v2_workspace_authoring import editor_section


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

EDITABLE_NAME = "Reporting service account"
WITHHELD_NAME = "Locked platform credential"
FILE_SYNC_NAME = "Archive file share"
IN_USE_NAME = "Bound integration credential"


def open_identities(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/identities", **options)


def open_manager(ui, group="group-a", **options):
    open_identities(ui, group, **options)
    expect(ui.page.get_by_role("heading", name="Identities", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New identity", exact=True)).to_be_visible()


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def identities_get(ui, group="group-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/groups/{group}/identities" and entry.method == "GET"
    ]


def last_write(ui, path, method):
    matches = [entry for entry in ui.writes if entry.path == path and entry.method == method]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w.method, w.path) for w in ui.writes]}"
    return matches[-1]


def assert_no_personal_reads(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/workspace-identities/")], (
        "A group identity surface must not read personal reusable identities."
    )
    assert not [
        entry for entry in ui.requests
        if entry.path.startswith("/api/user/") and entry.path != "/api/user/settings"
    ], "A group identity surface must not read any personal /api/user resource."
    assert not [entry for entry in ui.requests if entry.query.get("agent_scope") == ["personal"]], (
        "A group identity surface must never request a personal scope."
    )


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_group_identity_layout(group_identities_ui, theme, width, height):
    """The manager section matches the shell in both themes and both breakpoints."""
    ui = group_identities_ui
    open_identities(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Identities", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New identity", exact=True)).to_be_enabled()
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    # The native section renders, not the classic hand-off panel.
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


def test_group_identities_read_from_the_group_route_only(group_identities_ui):
    """Every list is a group read with no query; no personal identity request is ever made."""
    ui = group_identities_ui
    open_manager(ui)
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    assert identities_get(ui), "The section must load from the group identities route."
    assert all(not entry.query for entry in identities_get(ui)), (
        "The identities list route takes no query parameters."
    )
    assert_no_personal_reads(ui)


def test_group_identity_response_identity_is_validated(group_identities_ui):
    """A returned identity scoped to another group is refused rather than rendered."""
    ui = group_identities_ui
    ui.native_identities["group-a"].append({
        **ui.record_identity("group-a", EDITABLE_IDENTITY_ID),
        "id": "foreign-identity", "identity_id": "foreign-identity",
        "group_id": "group-z", "name": "Foreign identity",
    })
    ui.native_identity_revisions[("group-a", "foreign-identity")] = 1
    open_identities(ui)
    expect(ui.page.get_by_text(re.compile("does not match this group"))).to_be_visible()
    expect(ui.page.get_by_text("Foreign identity", exact=True)).to_have_count(0)


def test_inline_identity_actions_gate_edit_and_delete(group_identities_ui):
    """The editable identity shows Edit and Delete; the withheld identity shows neither."""
    ui = group_identities_ui
    open_manager(ui)
    editable = row(ui, EDITABLE_NAME)
    expect(editable.get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True)).to_be_visible()

    withheld = row(ui, WITHHELD_NAME)
    expect(withheld.get_by_role("button", name=f"Edit {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Delete {WITHHELD_NAME}", exact=True)).to_have_count(0)


def test_group_manager_creates_an_identity(group_identities_ui):
    """A manager authors a new identity through the group route with no expected_etag."""
    ui, page = group_identities_ui, group_identities_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New identity", exact=True).click()
    expect(page.get_by_role("button", name="Create identity", exact=True)).to_be_visible()
    page.get_by_label("Name", exact=True).fill("Data warehouse key")
    page.get_by_label("Secret", exact=True).fill("warehouse-secret-value")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/groups/group-a/identities"
    ) as response:
        page.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 201
    write = last_write(ui, "/api/groups/group-a/identities", "POST")
    assert write.body["name"] == "Data warehouse key"
    assert write.body["usage_contexts"] == ["action"]
    assert write.body["credentials"]["auth_type"] == "api_key"
    assert write.body["credentials"]["secret"] == "warehouse-secret-value"
    assert "expected_etag" not in write.body
    created = next(r for r in ui.native_identities["group-a"] if r["name"] == "Data warehouse key")
    assert created["group_id"] == "group-a"
    expect(row(ui, "Data warehouse key")).to_be_visible()


def test_group_manager_edits_with_a_conditional_write(group_identities_ui):
    """Editing an identity sends expected_etag and the changed field, and updates the stored row."""
    ui, page = group_identities_ui, group_identities_ui.page
    etag = ui._identity_etag("group-a", EDITABLE_IDENTITY_ID)
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    name = page.get_by_label("Name", exact=True)
    expect(name).to_have_value(EDITABLE_NAME)
    name.fill("Reporting service account (rotated)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/identities/{EDITABLE_IDENTITY_ID}", "PATCH")
    assert write.body["expected_etag"] == etag
    assert write.body["name"] == "Reporting service account (rotated)"
    assert ui.record_identity("group-a", EDITABLE_IDENTITY_ID)["name"] == "Reporting service account (rotated)"


def test_edit_preserves_the_stored_secret(group_identities_ui):
    """Editing an identity without touching its secret keeps the stored credential masked."""
    ui, page = group_identities_ui, group_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    # The stored-secret field carries a help note, so its accessible name is more than the bare
    # label; match the label as a substring rather than exactly.
    secret = page.get_by_label("Secret (stored)")
    expect(secret).to_have_value("")
    page.get_by_label("Description (optional)", exact=True).fill("Rotated description")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/identities/{EDITABLE_IDENTITY_ID}", "PATCH")
    # A blank secret means "keep the stored value"; it rides as an empty string, never a placeholder.
    assert write.body["credentials"]["secret"] == ""
    assert ui.record_identity("group-a", EDITABLE_IDENTITY_ID)["_secret"] is True


def test_group_manager_deletes_an_identity(group_identities_ui):
    """Deleting an identity confirms, calls DELETE with only the version marker, and removes the row."""
    ui, page = group_identities_ui, group_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        row(ui, EDITABLE_NAME).get_by_role("button", name="Delete", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/identities/{EDITABLE_IDENTITY_ID}", "DELETE")
    assert set(write.body) == {"expected_etag"}
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)
    assert ui.record_identity("group-a", EDITABLE_IDENTITY_ID) is None


def test_conflict_keeps_the_draft_and_offers_a_refresh(group_identities_ui):
    """A stale etag keeps the editor and its draft and offers to reload the saved identity."""
    ui, page = group_identities_ui, group_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Draft in flight")
    ui.touch_identity("group-a", EDITABLE_IDENTITY_ID)
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409
    expect(page.get_by_label("Name", exact=True)).to_have_value("Draft in flight")
    expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile("modified"))).to_be_visible()


def test_delete_in_use_names_the_references(group_identities_ui):
    """A delete refused because the identity is still referenced names what uses it; nothing is removed."""
    ui, page = group_identities_ui, group_identities_ui.page
    open_manager(ui)
    row(ui, IN_USE_NAME).get_by_role("button", name=f"Delete {IN_USE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/identities/{IN_USE_IDENTITY_ID}"
    ) as response:
        row(ui, IN_USE_NAME).get_by_role("button", name="Delete", exact=True).click()
    assert response.value.status == 409
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("still in use")
    expect(alert).to_contain_text("Shared connector")
    expect(row(ui, IN_USE_NAME)).to_be_visible()
    assert ui.record_identity("group-a", IN_USE_IDENTITY_ID) is not None


def test_reviewed_validation_message_renders_verbatim(group_identities_ui):
    """The server's reviewed validation message renders verbatim, and the draft is kept."""
    ui, page = group_identities_ui, group_identities_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New identity", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Warehouse account")
    # The auth-method select uses an implicit wrapping label whose text folds in the option
    # names, so target it as the dialog's only combobox rather than by that polluted label.
    page.get_by_role("dialog").get_by_role("combobox").select_option(label="Username and password")
    page.get_by_label("Username", exact=True).fill("svc-user")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/groups/group-a/identities"
    ) as response:
        page.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 400
    expect(page.get_by_text("Username/password identities require a password", exact=True)).to_be_visible()
    expect(page.get_by_label("Name", exact=True)).to_have_value("Warehouse account")


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_member_has_no_native_identities_section(group_identities_ui, theme, width, height):
    """A member's identities section is manager-only, so it is locked with the server's reason."""
    ui, page = group_identities_ui, group_identities_ui.page
    open_identities(ui, group="group-b", theme=theme, width=width, height=height)
    # The manager-only section is unavailable to a member: a locked notice with the governance
    # reason, no native create control, and no group identity read at all.
    expect(page.get_by_text("Identities is not available", exact=True)).to_be_visible()
    expect(page.get_by_text("Your role does not permit managing group connections.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New identity", exact=True)).to_have_count(0)
    assert not identities_get(ui, group="group-b"), (
        "A member's unavailable section must not read the group identity route."
    )
    assert_no_personal_reads(ui)
    ui.assert_no_overflow()


def test_action_editor_lists_group_identities_filtered_to_action_usage(group_identities_ui):
    """A manager's action editor offers the group's action-usage identities and no File Sync one."""
    ui, page = group_identities_ui, group_identities_ui.page
    ui.open(f"/groups/group-a/actions/{CONNECTOR_ACTION_ID}")
    editor_section(page, "Authentication")
    select = page.get_by_label("Reusable identity", exact=True)
    expect(select).to_be_visible()
    expect(select.get_by_role("option", name=re.compile(re.escape(EDITABLE_NAME)))).to_have_count(1)
    expect(select.get_by_role("option", name=re.compile(re.escape(FILE_SYNC_NAME)))).to_have_count(0)
    assert identities_get(ui, group="group-a"), "The editor must list identities from the group route."
    assert_no_personal_reads(ui)


def test_action_editor_member_gets_a_silent_unresolved_list(group_identities_ui):
    """A member's action editor turns the 403 into a silent empty list, never a personal read."""
    ui, page = group_identities_ui, group_identities_ui.page
    ui.open("/groups/group-b/actions/group-b-connector")
    editor_section(page, "Authentication")
    select = page.get_by_label("Reusable identity", exact=True)
    expect(select).to_be_visible()
    # The list is silently empty: the connector still offers action-specific credentials, and no
    # identity error banner surfaces.
    expect(page.get_by_text(re.compile("No compatible reusable identities"))).to_be_visible()
    reads = [
        entry for entry in ui.requests
        if entry.path == "/api/groups/group-b/identities" and entry.method == "GET"
    ]
    assert reads, "The editor must attempt the group identity route, which answers 403."
    assert_no_personal_reads(ui)
