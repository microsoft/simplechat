# test_v2_public_file_sources.py
"""
Production-SPA coverage for the native V2 public workspace file sources section (M10B).
Version: 0.261.179
Implemented in: 0.261.179

Exercises the real file sources section and its editor dialog against closed synthetic HTTP. The
fixture serves only the immutable `/api/public-workspaces/<id>/file-sources` family, the
`/api/public-workspaces/<id>/file-source-options` route, and the editor's manager-gated
`/identities` and `/documents/tags` reads, and never a personal `/api/file-sync/personal/*` read,
a personal `/api/workspace-identities/*` read, or a group `/api/groups/*` read, so a public scope
that leaked into personal or group file sync would fail the run rather than be answered. A manager
reads from the public route with no query, creates through it with no `expected_config_revision`,
edits with a conditional write over `config_revision` that keeps the stored secret masked, keeps the
draft open on a stale-revision 409 and adopts a concurrent change on reload, and deletes with a
deliberate documents choice; an inline `source_actions` gate hides edit, sync and delete per source
beside an editable positive control; a delete refused because a sync is running says so; a returned
source scoped to another workspace is refused rather than rendered; a bound public workspace identity
names itself on the row and the editor's picker lists the eligible one; a locked workspace is a
read-only section; and a reader's and a File-Sync-off manager's manager-only section is unavailable
with the server's own reason.

The live File Sync engine, run history, connection tests, browse and ignore are exercised
byte-for-byte by the group M5B suite because the public routes drive the same scope-generic engine,
so this suite does not repeat them; the public envelope, projection, credentials, conflict codes and
management gating are what differ, and those are what it covers.
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401
from ui_tests.fixtures.public_workspace import (
    PUBLIC_CONNECTIONS_MANAGER_REASON, PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON,
)
from ui_tests.fixtures.public_file_sources import (  # noqa: F401
    PublicFileSourcesFixture, public_file_sources_ui,
    EDITABLE_SOURCE_ID, WITHHELD_SOURCE_ID, IDENTITY_SOURCE_ID, FILE_SYNC_IDENTITY_ID,
    FILE_SOURCE_CONFLICT_BODY, FILE_SOURCE_BUSY_BODY,
)


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

EDITABLE_NAME = "Quarterly reports share"
WITHHELD_NAME = "Locked archive share"
IDENTITY_NAME = "Shared drive via identity"
IDENTITY_LABEL = "Archive file share account"

CONFLICT_MESSAGE = FILE_SOURCE_CONFLICT_BODY["error"]
BUSY_MESSAGE = FILE_SOURCE_BUSY_BODY["error"]
REBASE_NOTICE = (
    "Someone else changed this while you were editing. Their changes are loaded; "
    "your edits are kept. Review, then save."
)


def open_sources(ui, workspace="pub-a", **options):
    ui.open(f"/public/{workspace}/sync", **options)


def open_manager(ui, workspace="pub-a", **options):
    open_sources(ui, workspace, **options)
    expect(ui.page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New file source", exact=True)).to_be_visible()


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def sources_get(ui, workspace="pub-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/public-workspaces/{workspace}/file-sources" and entry.method == "GET"
    ]


def last_write(ui, path, method):
    matches = [entry for entry in ui.writes if entry.path == path and entry.method == method]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w.method, w.path) for w in ui.writes]}"
    return matches[-1]


def assert_no_personal_or_group_reads(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/file-sync/personal/")], (
        "A public file source surface must not read personal file sync sources."
    )
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/workspace-identities/")], (
        "A public file source surface must not read personal reusable identities."
    )
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/groups/")], (
        "A public file source surface must not read a group route."
    )
    assert not [entry for entry in ui.requests if entry.query.get("agent_scope") == ["personal"]], (
        "A public file source surface must never request a personal scope."
    )


def open_editor_for(ui, name):
    """Open the editor for a saved source and wait for its options to finish loading."""
    row(ui, name).get_by_role("button", name=f"Edit {name}", exact=True).click()
    expect(ui.page.get_by_role("button", name="Save changes", exact=True)).to_be_enabled()


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_public_file_source_layout(public_file_sources_ui, theme, width, height):
    """The manager section matches the shell in both themes and both breakpoints."""
    ui = public_file_sources_ui
    open_sources(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New file source", exact=True)).to_be_enabled()
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    # The native section renders, not the classic hand-off panel.
    expect(ui.page.get_by_text("available in the classic", exact=False)).to_have_count(0)
    ui.assert_no_overflow()


def test_public_file_sources_read_from_the_public_route_only(public_file_sources_ui):
    """Every list is a public read with no query; no personal or group file source request is made."""
    ui = public_file_sources_ui
    open_manager(ui)
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    assert sources_get(ui), "The section must load from the public file sources route."
    assert all(not entry.query for entry in sources_get(ui)), (
        "The file sources list route takes no query parameters."
    )
    assert_no_personal_or_group_reads(ui)


def test_public_file_source_response_scope_is_validated(public_file_sources_ui):
    """A returned source scoped to another workspace is refused rather than rendered."""
    ui = public_file_sources_ui
    ui.file_sources["pub-a"].append({
        **ui.record("pub-a", EDITABLE_SOURCE_ID),
        "id": "foreign-source",
        "public_workspace_id": "pub-z", "name": "Foreign source",
    })
    open_sources(ui)
    expect(ui.page.get_by_text(re.compile("does not match this workspace"))).to_be_visible()
    expect(ui.page.get_by_text("Foreign source", exact=True)).to_have_count(0)


def test_inline_source_actions_gate_row_controls(public_file_sources_ui):
    """The editable source shows Sync, Edit and Delete; the withheld source shows none."""
    ui = public_file_sources_ui
    open_manager(ui)
    editable = row(ui, EDITABLE_NAME)
    expect(editable.get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Sync {EDITABLE_NAME} now", exact=True)).to_be_visible()

    withheld = row(ui, WITHHELD_NAME)
    expect(withheld.get_by_role("button", name=f"Edit {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Delete {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Sync {WITHHELD_NAME} now", exact=True)).to_have_count(0)


def test_bound_identity_names_itself_on_the_row(public_file_sources_ui):
    """A source bound to a public workspace identity shows the identity name on its row."""
    ui = public_file_sources_ui
    open_manager(ui)
    expect(row(ui, IDENTITY_NAME).get_by_text(IDENTITY_LABEL, exact=True)).to_be_visible()


def test_public_manager_creates_a_file_source(public_file_sources_ui):
    """A manager authors a new source through the public route with its documents choice absent."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New file source", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Design assets share")
    # Enter credentials directly so the create does not depend on an eligible identity.
    page.get_by_role("radio", name="Enter credentials directly").check()
    create = page.get_by_role("button", name="Create source", exact=True)
    expect(create).to_be_enabled()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/public-workspaces/pub-a/file-sources"
    ) as response:
        create.click()
    assert response.value.status == 201
    write = last_write(ui, "/api/public-workspaces/pub-a/file-sources", "POST")
    assert write.body["name"] == "Design assets share"
    assert write.body["source_type"] == "smb"
    assert "expected_config_revision" not in write.body
    created = next(r for r in ui.file_sources["pub-a"] if r["name"] == "Design assets share")
    assert created["public_workspace_id"] == "pub-a"
    assert created["id"].startswith("public-created-")
    expect(row(ui, "Design assets share")).to_be_visible()


def test_public_manager_edits_with_a_conditional_write(public_file_sources_ui):
    """Editing a source sends expected_config_revision and the changed field, and updates the row."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    revision = ui._file_source_config_revision("pub-a", EDITABLE_SOURCE_ID)
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    name = page.get_by_label("Name", exact=True)
    expect(name).to_have_value(EDITABLE_NAME)
    name.fill("Quarterly reports share (rotated)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}", "PATCH")
    assert write.body["expected_config_revision"] == revision
    assert write.body["name"] == "Quarterly reports share (rotated)"
    assert ui.record("pub-a", EDITABLE_SOURCE_ID)["name"] == "Quarterly reports share (rotated)"


def test_edit_preserves_the_stored_secret(public_file_sources_ui):
    """Editing a source without touching its secret keeps the stored credential masked."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    page.get_by_label("Name", exact=True).fill("Quarterly reports share (kept)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}", "PATCH")
    # A blank secret means "keep the stored value"; it rides as an empty string, never a placeholder.
    assert write.body["credentials"]["password"] == ""
    assert ui.record("pub-a", EDITABLE_SOURCE_ID)["credentials"]["password_stored"] is True


def test_config_conflict_keeps_the_draft_and_offers_a_reload(public_file_sources_ui):
    """A stale config_revision keeps the editor and its draft and offers to reload the source."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    page.get_by_label("Name", exact=True).fill("Draft in flight")
    ui.touch_file_source("pub-a", EDITABLE_SOURCE_ID)
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409
    expect(page.get_by_label("Name", exact=True)).to_have_value("Draft in flight")
    expect(page.get_by_role("button", name="Reload", exact=True)).to_be_visible()
    expect(page.get_by_text(CONFLICT_MESSAGE, exact=True)).to_be_visible()


def test_config_conflict_reload_rebases_concurrent_scope_and_keeps_local_name(public_file_sources_ui):
    """Reloading a config conflict adopts an untouched concurrent change and keeps the local name."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    record = ui.record("pub-a", EDITABLE_SOURCE_ID)
    record["recursive"] = False
    ui.touch_file_source("pub-a", EDITABLE_SOURCE_ID)
    page.get_by_label("Name", exact=True).fill("Quarterly reports share local")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as conflict:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == "/api/public-workspaces/pub-a/file-sources"
    ):
        page.get_by_role("button", name="Reload", exact=True).click()
    expect(page.get_by_label("Include subfolders", exact=True)).not_to_be_checked()
    expect(page.get_by_label("Name", exact=True)).to_have_value("Quarterly reports share local")
    expect(page.get_by_text(REBASE_NOTICE, exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as saved:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert saved.value.ok
    saved_record = ui.record("pub-a", EDITABLE_SOURCE_ID)
    assert saved_record["recursive"] is False
    assert saved_record["name"] == "Quarterly reports share local"


def test_delete_keep_documents_removes_only_the_source(public_file_sources_ui):
    """Deleting and keeping documents sends the version marker and the false choice, and removes the row."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Keep documents", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}", "DELETE")
    assert set(write.body) == {"expected_config_revision", "delete_associated_files"}
    assert write.body["delete_associated_files"] is False
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)
    assert not any(r["id"] == EDITABLE_SOURCE_ID for r in ui.file_sources["pub-a"])


def test_delete_documents_too_sends_the_true_choice(public_file_sources_ui):
    """Deleting with the documents removed too sends the true choice and removes the row."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Delete documents too", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}", "DELETE")
    assert write.body["delete_associated_files"] is True
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)


def test_delete_refused_while_a_sync_runs_is_explained(public_file_sources_ui):
    """A delete refused because a sync is running explains it rather than claiming a conflict."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    ui.mark_source_busy("pub-a", EDITABLE_SOURCE_ID)
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/public-workspaces/pub-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Delete documents too", exact=True).click()
    assert response.value.status == 409
    expect(page.get_by_text(BUSY_MESSAGE, exact=True)).to_be_visible()
    assert any(r["id"] == EDITABLE_SOURCE_ID for r in ui.file_sources["pub-a"])


def test_search_filters_sources_by_name_and_path(public_file_sources_ui):
    """The search narrows the loaded list by name or remote path without another read, says when
    nothing matches, and restores the list when cleared."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    for name in (EDITABLE_NAME, WITHHELD_NAME, IDENTITY_NAME):
        expect(row(ui, name)).to_be_visible()
    reads_before = len(sources_get(ui))
    search = page.get_by_placeholder("Search file sources")
    search.fill("archive")
    expect(row(ui, WITHHELD_NAME)).to_be_visible()
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)
    expect(row(ui, IDENTITY_NAME)).to_have_count(0)
    # A path matches too: the identity source's share is \\files.example.test\shared.
    search.fill("\\shared")
    expect(row(ui, IDENTITY_NAME)).to_be_visible()
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)
    search.fill("no such source")
    expect(page.get_by_text("No sources match your search", exact=True)).to_be_visible()
    search.fill("")
    for name in (EDITABLE_NAME, WITHHELD_NAME, IDENTITY_NAME):
        expect(row(ui, name)).to_be_visible()
    assert len(sources_get(ui)) == reads_before, "Searching filters the loaded list; it never re-reads."


def test_editor_offers_only_eligible_public_identities(public_file_sources_ui):
    """The editor's identity picker lists the workspace's File Sync identity, read from the public route."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New file source", exact=True).click()
    # The default credential mode is a saved identity, so the picker is shown at once. Locate it by
    # the eligible option it carries, not by copy, since the reused dialog labels it "group identity".
    picker = page.get_by_role("dialog").locator("select").filter(
        has=page.get_by_role("option", name=IDENTITY_LABEL, exact=True))
    expect(picker).to_be_visible()
    expect(picker.get_by_role("option", name=IDENTITY_LABEL, exact=True)).to_have_count(1)
    # Only the eligible File Sync identity is offered, beside the placeholder -- no ineligible ones.
    expect(picker.get_by_role("option")).to_have_count(2)
    identity_reads = [
        entry for entry in ui.requests
        if entry.path == "/api/public-workspaces/pub-a/identities" and entry.method == "GET"
    ]
    assert identity_reads, "The editor must list identities from the public route."
    assert_no_personal_or_group_reads(ui)


def test_create_editor_fits_mobile(public_file_sources_ui):
    """The create editor and its credential fields fit the narrow breakpoint without sideways scroll."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_sources(ui, theme="dark", width=390, height=844)
    expect(page.get_by_role("button", name="New file source", exact=True)).to_be_visible()
    page.get_by_role("button", name="New file source", exact=True).click()
    page.get_by_role("radio", name="Enter credentials directly").check()
    expect(page.get_by_role("button", name="Create source", exact=True)).to_be_visible()
    ui.assert_no_overflow()


def test_locked_manager_gets_a_read_only_section(public_file_sources_ui):
    """A locked workspace is readable but advertises no operations, so a manager sees no write tools."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    ui.set_file_source_policy("pub-a", role="Owner", status="locked")
    open_sources(ui)
    expect(page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    # The list still loads, but every write control is gone: no create, edit, sync or delete.
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    expect(page.get_by_role("button", name="New file source", exact=True)).to_have_count(0)
    expect(row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True)).to_have_count(0)
    expect(row(ui, EDITABLE_NAME).get_by_role("button", name=f"Sync {EDITABLE_NAME} now", exact=True)).to_have_count(0)
    expect(row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True)).to_have_count(0)
    assert not ui.unexpected_requests, ui.unexpected_requests
    assert_no_personal_or_group_reads(ui)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_reader_has_no_native_file_sources_section(public_file_sources_ui, theme, width, height):
    """A reader's file sources section is manager-only, so it is locked with the server's role reason."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    open_sources(ui, workspace="pub-b", theme=theme, width=width, height=height)
    expect(page.get_by_text("File sources is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(PUBLIC_CONNECTIONS_MANAGER_REASON, exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New file source", exact=True)).to_have_count(0)
    assert not sources_get(ui, workspace="pub-b"), (
        "A reader's unavailable section must not read the public file sources route."
    )
    assert_no_personal_or_group_reads(ui)
    ui.assert_no_overflow()


def test_file_sync_off_manager_section_is_unavailable(public_file_sources_ui):
    """File sources require File Sync: with it off, even a manager's section is locked with the File
    Sync reason and never reads the file source route."""
    ui, page = public_file_sources_ui, public_file_sources_ui.page
    ui.set_file_source_policy("pub-a", role="Owner", status="active", available=False)
    open_sources(ui)
    expect(page.get_by_text("File sources is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON, exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New file source", exact=True)).to_have_count(0)
    assert not sources_get(ui, workspace="pub-a"), (
        "A File-Sync-off section must not read the public file source route."
    )
    assert_no_personal_or_group_reads(ui)
