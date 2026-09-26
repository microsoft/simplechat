# test_v2_public_identities.py
"""
Production-SPA coverage for the native V2 public workspace identities section (M10B).
Version: 0.261.182
Implemented in: 0.261.182

Exercises the real identities section and its editor dialog against closed synthetic HTTP. The
fixture serves only the immutable `/api/public-workspaces/<id>/identities` family and never a
personal `/api/user/*` (bar settings), a personal `/api/workspace-identities/*` read, or a group
`/api/groups/*` read, so a public scope that leaked into personal or group identities would fail the
run rather than be answered. A manager reads from the public route with no query, creates through it
with no `expected_etag`, edits with a conditional write that keeps the stored secret masked, deletes
with an `expected_etag`-only body, and keeps the draft open on a stale-etag 409 with a refresh that
rebases; an inline `identity_actions` gate hides edit and delete per identity beside an editable
positive control; a delete refused because the identity still feeds a File Sync source names what
uses it; the server's reviewed validation message renders verbatim; a returned identity scoped to
another workspace is refused rather than rendered; and a reader's and a File-Sync-off manager's
manager-only section is unavailable with the server's own reason. A public workspace has no actions
surface, so the editor's "Used for" picker offers only File Sync and a new draft never proposes an
action-only capability the workspace cannot feed.
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401
from ui_tests.fixtures.public_workspace import (
    PUBLIC_CONNECTIONS_MANAGER_REASON, PUBLIC_IDENTITIES_UNAVAILABLE_REASON,
)
from ui_tests.fixtures.public_identities import (  # noqa: F401
    PublicIdentitiesFixture, public_identities_ui,
    EDITABLE_IDENTITY_ID, WITHHELD_IDENTITY_ID, IN_USE_IDENTITY_ID,
)


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

EDITABLE_NAME = "Reporting service account"
WITHHELD_NAME = "Locked platform credential"
IN_USE_NAME = "Bound archive credential"
REBASE_NOTICE = (
    "Someone else changed this while you were editing. Their changes are loaded; "
    "your edits are kept. Review, then save."
)
REBASE_DELETED_NOTICE = "This item was deleted. Copy anything you need, then close."


def open_identities(ui, workspace="pub-a", **options):
    ui.open(f"/public/{workspace}/identities", **options)


def open_manager(ui, workspace="pub-a", **options):
    open_identities(ui, workspace, **options)
    expect(ui.page.get_by_role("heading", name="Identities", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New identity", exact=True)).to_be_visible()


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def identities_get(ui, workspace="pub-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/public-workspaces/{workspace}/identities" and entry.method == "GET"
    ]


def last_write(ui, path, method):
    matches = [entry for entry in ui.writes if entry.path == path and entry.method == method]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w.method, w.path) for w in ui.writes]}"
    return matches[-1]


def assert_no_personal_or_group_reads(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/workspace-identities/")], (
        "A public identity surface must not read personal reusable identities."
    )
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/groups/")], (
        "A public identity surface must not read a group identity route."
    )
    assert not [
        entry for entry in ui.requests
        if entry.path.startswith("/api/user/") and entry.path != "/api/user/settings"
    ], "A public identity surface must not read any personal /api/user resource."
    assert not [entry for entry in ui.requests if entry.query.get("agent_scope") == ["personal"]], (
        "A public identity surface must never request a personal scope."
    )


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_public_identity_layout(public_identities_ui, theme, width, height):
    """The manager section matches the shell in both themes and both breakpoints."""
    ui = public_identities_ui
    open_identities(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Identities", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New identity", exact=True)).to_be_enabled()
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    # The native section renders, not the classic hand-off panel.
    expect(ui.page.get_by_text("available in the classic", exact=False)).to_have_count(0)
    ui.assert_no_overflow()


def test_public_identities_read_from_the_public_route_only(public_identities_ui):
    """Every list is a public read with no query; no personal or group identity request is made."""
    ui = public_identities_ui
    open_manager(ui)
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    assert identities_get(ui), "The section must load from the public identities route."
    assert all(not entry.query for entry in identities_get(ui)), (
        "The identities list route takes no query parameters."
    )
    assert_no_personal_or_group_reads(ui)


def test_public_identity_response_identity_is_validated(public_identities_ui):
    """A returned identity scoped to another workspace is refused rather than rendered."""
    ui = public_identities_ui
    ui.identities["pub-a"].append({
        **ui.record("pub-a", EDITABLE_IDENTITY_ID),
        "id": "foreign-identity",
        "public_workspace_id": "pub-z", "name": "Foreign identity",
    })
    open_identities(ui)
    expect(ui.page.get_by_text(re.compile("does not match this workspace"))).to_be_visible()
    expect(ui.page.get_by_text("Foreign identity", exact=True)).to_have_count(0)


def test_inline_identity_actions_gate_edit_and_delete(public_identities_ui):
    """The editable identity shows Edit and Delete; the withheld identity shows neither."""
    ui = public_identities_ui
    open_manager(ui)
    editable = row(ui, EDITABLE_NAME)
    expect(editable.get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True)).to_be_visible()

    withheld = row(ui, WITHHELD_NAME)
    expect(withheld.get_by_role("button", name=f"Edit {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Delete {WITHHELD_NAME}", exact=True)).to_have_count(0)


def test_search_narrows_identities_by_name_and_sign_in(public_identities_ui):
    """The search matches an identity's name or the sign-in its row shows (`CORP\\svc-report`),
    ignoring case; a term matching nothing says so, and clearing it restores every identity. It
    filters the loaded list, so it never re-reads the public route."""
    ui = public_identities_ui
    open_manager(ui)
    names = (EDITABLE_NAME, WITHHELD_NAME, IN_USE_NAME)
    for name in names:
        expect(row(ui, name)).to_be_visible()
    reads = len(identities_get(ui))
    search = ui.page.get_by_role("searchbox", name="Search identities", exact=True)
    for term, match in (("REPORTING", EDITABLE_NAME), ("corp\\svc", EDITABLE_NAME)):
        search.fill(term)
        expect(row(ui, match)).to_be_visible()
        for name in names:
            if name != match:
                expect(row(ui, name)).to_have_count(0)
    search.fill("no such credential")
    expect(ui.page.get_by_text("No identities match your search", exact=True)).to_be_visible()
    for name in names:
        expect(row(ui, name)).to_have_count(0)
    search.fill("")
    for name in names:
        expect(row(ui, name)).to_be_visible()
    assert len(identities_get(ui)) == reads


def test_public_editor_offers_only_the_file_sync_capability(public_identities_ui):
    """A public workspace feeds file sources only, so the editor's "Used for" picker offers File Sync
    and never Actions, and a new draft defaults to the file-sync auth methods rather than an API key."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New identity", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("checkbox", name=re.compile("File Sync"))).to_be_visible()
    expect(dialog.get_by_role("checkbox", name=re.compile("^Actions"))).to_have_count(0)
    # A file-sync default carries a Username/password method, so its credential field is a password,
    # not the action-only API key the group default would show.
    expect(page.get_by_label("Password", exact=True)).to_be_visible()


def test_public_manager_creates_an_identity(public_identities_ui):
    """A manager authors a new identity through the public route with no expected_etag, and the
    file-sync capability rides as `usage_contexts: ["file_sync"]`."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New identity", exact=True).click()
    expect(page.get_by_role("button", name="Create identity", exact=True)).to_be_visible()
    page.get_by_label("Name", exact=True).fill("Archive share account")
    page.get_by_label("Username", exact=True).fill("svc-new")
    page.get_by_label("Password", exact=True).fill("archive-secret-value")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/public-workspaces/pub-a/identities"
    ) as response:
        page.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 201
    write = last_write(ui, "/api/public-workspaces/pub-a/identities", "POST")
    assert write.body["name"] == "Archive share account"
    assert write.body["usage_contexts"] == ["file_sync"]
    assert write.body["credentials"]["auth_type"] == "username_password"
    assert write.body["credentials"]["username"] == "svc-new"
    assert write.body["credentials"]["password"] == "archive-secret-value"
    assert "expected_etag" not in write.body
    created = next(r for r in ui.identities["pub-a"] if r["name"] == "Archive share account")
    assert created["public_workspace_id"] == "pub-a"
    expect(row(ui, "Archive share account")).to_be_visible()


def test_public_manager_edits_with_a_conditional_write(public_identities_ui):
    """Editing an identity sends expected_etag and the changed field, and updates the stored row."""
    ui, page = public_identities_ui, public_identities_ui.page
    etag = ui._identity_etag("pub-a", EDITABLE_IDENTITY_ID)
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    name = page.get_by_label("Name", exact=True)
    expect(name).to_have_value(EDITABLE_NAME)
    name.fill("Reporting service account (rotated)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}", "PATCH")
    assert write.body["expected_etag"] == etag
    assert write.body["name"] == "Reporting service account (rotated)"
    assert ui.record("pub-a", EDITABLE_IDENTITY_ID)["name"] == "Reporting service account (rotated)"


def test_edit_preserves_the_stored_secret(public_identities_ui):
    """Editing an identity without touching its password keeps the stored credential masked."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    # The stored-secret field carries a help note, so its accessible name is more than the bare
    # label; match the label as a substring rather than exactly.
    secret = page.get_by_label("Password (stored)")
    expect(secret).to_have_value("")
    page.get_by_label("Description (optional)", exact=True).fill("Rotated description")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}", "PATCH")
    # A blank password means "keep the stored value"; it rides as an empty string, never a placeholder.
    assert write.body["credentials"]["password"] == ""
    assert ui.record("pub-a", EDITABLE_IDENTITY_ID)["credentials"]["password_stored"] is True


def test_public_manager_deletes_an_identity(public_identities_ui):
    """Deleting an identity confirms, calls DELETE with only the version marker, and removes the row."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        row(ui, EDITABLE_NAME).get_by_role("button", name="Delete", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}", "DELETE")
    assert set(write.body) == {"expected_etag"}
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)
    assert not any(r["id"] == EDITABLE_IDENTITY_ID for r in ui.identities["pub-a"])


def test_conflict_keeps_the_draft_and_offers_a_refresh(public_identities_ui):
    """A stale etag keeps the editor and its draft and offers to reload the saved identity."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Draft in flight")
    ui.touch_identity("pub-a", EDITABLE_IDENTITY_ID)
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409
    expect(page.get_by_label("Name", exact=True)).to_have_value("Draft in flight")
    expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile("modified"))).to_be_visible()


def test_conflict_refresh_rebases_concurrent_description_and_local_name(public_identities_ui):
    """Refreshing a stale identity edit adopts untouched fields and keeps the local name."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    record = ui.record("pub-a", EDITABLE_IDENTITY_ID)
    record["description"] = "Concurrent identity description."
    ui.touch_identity("pub-a", EDITABLE_IDENTITY_ID)
    page.get_by_label("Name", exact=True).fill("Reporting service account local")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as conflict:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == "/api/public-workspaces/pub-a/identities"
    ):
        page.get_by_role("button", name="Refresh", exact=True).click()
    expect(page.get_by_label("Description (optional)", exact=True)).to_have_value("Concurrent identity description.")
    expect(page.get_by_label("Name", exact=True)).to_have_value("Reporting service account local")
    expect(page.get_by_text(REBASE_NOTICE, exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as saved:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert saved.value.ok
    saved_record = ui.record("pub-a", EDITABLE_IDENTITY_ID)
    assert saved_record["description"] == "Concurrent identity description."
    assert saved_record["name"] == "Reporting service account local"


def test_conflict_refresh_reports_deleted_identity_without_resaving(public_identities_ui):
    """Refreshing after a stale save shows that the identity was deleted and does not save again."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True).click()
    ui.drop_identity_for_conflict("pub-a", EDITABLE_IDENTITY_ID)
    page.get_by_label("Name", exact=True).fill("Reporting service account deleted local")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ) as conflict:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == "/api/public-workspaces/pub-a/identities"
    ):
        page.get_by_role("button", name="Refresh", exact=True).click()
    expect(page.get_by_text(REBASE_DELETED_NOTICE, exact=True)).to_be_visible()
    writes = [
        entry for entry in ui.writes
        if entry.method == "PATCH" and entry.path == f"/api/public-workspaces/pub-a/identities/{EDITABLE_IDENTITY_ID}"
    ]
    assert len(writes) == 1
    assert not any(r["id"] == EDITABLE_IDENTITY_ID for r in ui.identities["pub-a"])


def test_delete_in_use_names_the_references(public_identities_ui):
    """A delete refused because the identity still feeds a File Sync source names it; nothing goes."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    row(ui, IN_USE_NAME).get_by_role("button", name=f"Delete {IN_USE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/identities/{IN_USE_IDENTITY_ID}"
    ) as response:
        row(ui, IN_USE_NAME).get_by_role("button", name="Delete", exact=True).click()
    assert response.value.status == 409
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("still in use")
    expect(alert).to_contain_text("Archive share")
    expect(row(ui, IN_USE_NAME)).to_be_visible()
    assert any(r["id"] == IN_USE_IDENTITY_ID for r in ui.identities["pub-a"])


def test_reviewed_validation_message_renders_verbatim(public_identities_ui):
    """The server's reviewed validation message renders verbatim, and the draft is kept."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New identity", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Password-less account")
    # Leave the file-sync username/password default in place but supply no password, the one reviewed
    # refusal a strict client can still reach.
    page.get_by_label("Username", exact=True).fill("svc-user")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/public-workspaces/pub-a/identities"
    ) as response:
        page.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 400
    expect(page.get_by_text("Username/password identities require a password", exact=True)).to_be_visible()
    expect(page.get_by_label("Name", exact=True)).to_have_value("Password-less account")


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_reader_has_no_native_identities_section(public_identities_ui, theme, width, height):
    """A reader's identities section is manager-only, so it is locked with the server's role reason."""
    ui, page = public_identities_ui, public_identities_ui.page
    open_identities(ui, workspace="pub-b", theme=theme, width=width, height=height)
    expect(page.get_by_text("Identities is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(PUBLIC_CONNECTIONS_MANAGER_REASON, exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New identity", exact=True)).to_have_count(0)
    assert not identities_get(ui, workspace="pub-b"), (
        "A reader's unavailable section must not read the public identity route."
    )
    assert_no_personal_or_group_reads(ui)
    ui.assert_no_overflow()


def test_file_sync_off_manager_section_is_unavailable(public_identities_ui):
    """Identities require File Sync: with it off, even a manager's section is locked with the File
    Sync reason and never reads the identity route."""
    ui, page = public_identities_ui, public_identities_ui.page
    ui.set_identity_policy("pub-a", role="Owner", status="active", available=False)
    open_identities(ui)
    expect(page.get_by_text("Identities is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(PUBLIC_IDENTITIES_UNAVAILABLE_REASON, exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New identity", exact=True)).to_have_count(0)
    assert not identities_get(ui, workspace="pub-a"), (
        "A File-Sync-off section must not read the public identity route."
    )
    assert_no_personal_or_group_reads(ui)
