# test_v2_group_file_sources.py
"""
Production-SPA coverage for the native scope-aware V2 group file sources section.
Version: 0.261.171
Implemented in: 0.261.147
Credential identifiers kept on edit: 0.261.156
Selected paths, fixed tags, folder tags, remote delete policy and root-relative browse: 0.261.171

Exercises the real file sources section and its editor dialog against closed synthetic
HTTP. The fixture serves only the immutable `/api/groups/<id>/file-sources` family and
the `/api/groups/<id>/file-source-options` route, and never a personal
`/api/file-sync/personal/*` or personal identity read, so a group scope that leaked
into personal file sync would fail the run rather than be answered. A manager creates
through the group route, edits with a conditional write over `config_revision` that
keeps the stored secret masked, and keeps the draft open on a stale `config_revision`
409; an inline `source_actions` gate hides edit, sync and delete per source beside an
editable positive control; a delete is deliberate about the documents the source
produced, showing the counts, and a refusal that already removed the documents says
so rather than claiming nothing changed; the reviewed Sync now refusal renders
verbatim; a bound group identity names itself on the row and in the editor picker; and
a member's manager-only section is unavailable with no group read at all. One node
check pins the personal adapter's transport byte-identical and the group seam never
reaching a personal URL.

The editor also sets the four classic File Sync fields: the folders and files to sync,
chosen by browsing from the source root or typed and normalized as the server stores
them; the fixed tags, with the group's existing tags offered from the explicit-group
tag read; the folder tag mode; and the remote delete policy. An edit saves all four back
untouched, a conflict reload adopts another manager's change to them, a path leaving
the root is refused before it is sent, and a typed path or tag left unadded blocks the
save instead of vanishing. Browse paths are relative to the root, never the root itself.
"""

import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401
from ui_tests.fixtures.group_workspace import (  # noqa: F401
    FILE_SOURCE_BUSY_ERROR, FILE_SOURCE_SYNC_BUSY_ERROR, FILE_SOURCE_SYNC_LIMIT_ERROR,
    FILE_SOURCE_CONFLICT_ERROR, GROUP_CONNECTIONS_ROLE_REASON, group_file_source,
)
from ui_tests.fixtures.group_file_sources import (  # noqa: F401
    GroupFileSourcesFixture, group_file_sources_ui,
    EDITABLE_SOURCE_ID, WITHHELD_SOURCE_ID, IDENTITY_SOURCE_ID, FILE_SYNC_IDENTITY_ID,
)


pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
SEAM_LOGIC_TS = Path(__file__).parent / "test_v2_group_file_sources.ts"

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

BUSY_MESSAGE = FILE_SOURCE_BUSY_ERROR
SYNC_BUSY_MESSAGE = FILE_SOURCE_SYNC_BUSY_ERROR
SYNC_LIMIT_MESSAGE = FILE_SOURCE_SYNC_LIMIT_ERROR
CONFLICT_MESSAGE = FILE_SOURCE_CONFLICT_ERROR
REBASE_NOTICE = (
    "Someone else changed this while you were editing. Their changes are loaded; "
    "your edits are kept. Review, then save."
)
REBASE_DELETED_NOTICE = "This item was deleted. Copy anything you need, then close."


def open_sources(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/sync", **options)


def open_manager(ui, group="group-a", **options):
    open_sources(ui, group, **options)
    expect(ui.page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New file source", exact=True)).to_be_visible()


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def sources_get(ui, group="group-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/groups/{group}/file-sources" and entry.method == "GET"
    ]


def last_write(ui, path, method):
    matches = [entry for entry in ui.writes if entry.path == path and entry.method == method]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w.method, w.path) for w in ui.writes]}"
    return matches[-1]


def assert_no_personal_reads(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/file-sync/personal/")], (
        "A group file source surface must not read personal file sync sources."
    )
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/workspace-identities/")], (
        "A group file source surface must not read personal reusable identities."
    )
    assert not [entry for entry in ui.requests if entry.query.get("agent_scope") == ["personal"]], (
        "A group file source surface must never request a personal scope."
    )


def open_editor_for(ui, name):
    """Open the editor for a saved source and wait for its options to finish loading."""
    row(ui, name).get_by_role("button", name=f"Edit {name}", exact=True).click()
    expect(ui.page.get_by_role("button", name="Save changes", exact=True)).to_be_enabled()


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_group_file_source_layout(group_file_sources_ui, theme, width, height):
    """The manager section matches the shell in both themes and both breakpoints."""
    ui = group_file_sources_ui
    open_sources(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="New file source", exact=True)).to_be_enabled()
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    # The native section renders, not the classic hand-off panel.
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


def test_overview_offers_file_sources_as_native(group_file_sources_ui):
    """The overview card links to the native section and no longer carries the Classic label."""
    ui = group_file_sources_ui
    ui.open("/groups/group-a")
    expect(ui.page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    card = ui.page.get_by_role("link").filter(has_text="Bring approved files into this group from other systems.")
    expect(card).to_have_count(1)
    expect(card).to_have_attribute("href", re.compile(r"/groups/group-a/sync$"))
    expect(card).not_to_contain_text("Classic")
    card.click()
    expect(ui.page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_have_count(0)
    assert_no_personal_reads(ui)


def test_group_file_sources_read_from_the_group_route_only(group_file_sources_ui):
    """Every list is a group read with no query; no personal file sync request is ever made."""
    ui = group_file_sources_ui
    open_manager(ui)
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    assert sources_get(ui), "The section must load from the group file sources route."
    assert all(not entry.query for entry in sources_get(ui)), (
        "The file sources list route takes no query parameters."
    )
    assert_no_personal_reads(ui)


def test_source_actions_gate_row_controls(group_file_sources_ui):
    """The editable source shows Sync, Edit and Delete; the withheld source shows none."""
    ui = group_file_sources_ui
    open_manager(ui)
    editable = row(ui, EDITABLE_NAME)
    expect(editable.get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Sync {EDITABLE_NAME} now", exact=True)).to_be_visible()

    withheld = row(ui, WITHHELD_NAME)
    expect(withheld.get_by_role("button", name=f"Edit {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Delete {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Sync {WITHHELD_NAME} now", exact=True)).to_have_count(0)


def test_bound_identity_names_itself_on_the_row(group_file_sources_ui):
    """A source bound to a group identity shows the identity name on its row."""
    ui = group_file_sources_ui
    open_manager(ui)
    expect(row(ui, IDENTITY_NAME).get_by_text(IDENTITY_LABEL, exact=True)).to_be_visible()


def test_group_manager_creates_a_file_source(group_file_sources_ui):
    """A manager authors a new source through the group route with its documents choice absent."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New file source", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Design assets share")
    # Enter credentials directly so the create does not depend on an eligible identity.
    page.get_by_role("radio", name="Enter credentials directly").check()
    create = page.get_by_role("button", name="Create source", exact=True)
    expect(create).to_be_enabled()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/groups/group-a/file-sources"
    ) as response:
        create.click()
    assert response.value.status == 201
    write = last_write(ui, "/api/groups/group-a/file-sources", "POST")
    assert write.body["name"] == "Design assets share"
    assert write.body["source_type"] == "smb"
    assert "expected_config_revision" not in write.body
    created = next(r for r in ui.native_file_sources["group-a"] if r["name"] == "Design assets share")
    assert created["id"].startswith("group-source-created-")
    expect(row(ui, "Design assets share")).to_be_visible()


def test_group_manager_edits_with_a_conditional_write(group_file_sources_ui):
    """Editing a source sends expected_config_revision and the changed field, and updates the row."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    revision = ui._file_source_config_revision("group-a", EDITABLE_SOURCE_ID)
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    name = page.get_by_label("Name", exact=True)
    expect(name).to_have_value(EDITABLE_NAME)
    name.fill("Quarterly reports share (rotated)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}", "PATCH")
    assert write.body["expected_config_revision"] == revision
    assert write.body["name"] == "Quarterly reports share (rotated)"
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID)["name"] == "Quarterly reports share (rotated)"


def test_edit_preserves_the_stored_secret(group_file_sources_ui):
    """Editing a source without touching its secret keeps the stored credential masked."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    page.get_by_label("Name", exact=True).fill("Quarterly reports share (kept)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}", "PATCH")
    # A blank secret means "keep the stored value"; it rides as an empty string, never a placeholder.
    assert write.body["credentials"]["password"] == ""
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID)["_secret"] is True


BLOB_CONNECTION = {"account_url": "https://contoso.blob.core.windows.net", "container_name": "finance", "blob_prefix": ""}
SP_SOURCE_ID, SP_NAME = "group-a-service-principal-source", "Finance blob container"
SP_CLIENT, SP_TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "11111111-2222-3333-4444-555555555555"
MI_SOURCE_ID, MI_NAME = "group-a-managed-identity-source", "Archive blob container"
MI_CLIENT = "99999999-8888-7777-6666-555555555555"


def rename_and_save(ui, source_id, name, *, opened=False):
    page = ui.page
    if not opened:
        open_manager(ui)
        open_editor_for(ui, name)
    page.get_by_label("Name", exact=True).fill(f"{name} (2024)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{source_id}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    return last_write(ui, f"/api/groups/group-a/file-sources/{source_id}", "PATCH")


def test_editing_a_service_principal_source_keeps_its_tenant(group_file_sources_ui):
    """The editor shows the stored tenant and sends it back, so a rename keeps it."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui._seed_file_sources("group-a", [*ui.native_file_sources["group-a"], group_file_source(
        "group-a", SP_SOURCE_ID, SP_NAME, source_type="azure_blob", auth_type="client_secret",
        client_identity=SP_CLIENT, tenant_id=SP_TENANT, secret_stored=True, connection=BLOB_CONNECTION,
    )])
    open_manager(ui)
    open_editor_for(ui, SP_NAME)
    expect(page.get_by_label("Tenant ID (optional)", exact=True)).to_have_value(SP_TENANT)
    write = rename_and_save(ui, SP_SOURCE_ID, SP_NAME, opened=True)
    assert write.body["credentials"]["tenant_id"] == SP_TENANT
    assert write.body["credentials"]["client_id"] == SP_CLIENT
    assert write.body["credentials"]["secret"] == ""
    stored = ui.record_file_source("group-a", SP_SOURCE_ID)
    assert (stored["_tenant_id"], stored["_client_identity"], stored["_secret"]) == (SP_TENANT, SP_CLIENT, True)


def test_editing_a_managed_identity_source_keeps_its_client_id(group_file_sources_ui):
    """A managed identity's client ID isn't shown, but a rename sends the stored one back."""
    ui = group_file_sources_ui
    ui._seed_file_sources("group-a", [*ui.native_file_sources["group-a"], group_file_source(
        "group-a", MI_SOURCE_ID, MI_NAME, source_type="azure_blob", auth_type="managed_identity",
        managed_identity_client_id=MI_CLIENT, secret_stored=False, connection=BLOB_CONNECTION,
    )])
    write = rename_and_save(ui, MI_SOURCE_ID, MI_NAME)
    assert write.body["credentials"] == {"auth_type": "managed_identity", "managed_identity_client_id": MI_CLIENT}
    assert ui.record_file_source("group-a", MI_SOURCE_ID)["_mi_client_id"] == MI_CLIENT


def test_config_conflict_keeps_the_draft_and_offers_a_reload(group_file_sources_ui):
    """A stale config_revision keeps the editor and its draft and offers to reload the source."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    page.get_by_label("Name", exact=True).fill("Draft in flight")
    ui.touch_file_source("group-a", EDITABLE_SOURCE_ID)
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409
    expect(page.get_by_label("Name", exact=True)).to_have_value("Draft in flight")
    expect(page.get_by_role("button", name="Reload", exact=True)).to_be_visible()
    expect(page.get_by_text(CONFLICT_MESSAGE, exact=True)).to_be_visible()


def test_write_conflict_on_save_allows_a_plain_retry(group_file_sources_ui):
    """A bare etag race (write_conflict, unchanged revision) keeps the draft but offers no reload:
    the same Save can simply be retried and then succeeds."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    page.get_by_label("Name", exact=True).fill("Retriable draft")
    ui.file_source_forced_write_conflict = "write_conflict"
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409
    # The draft survives, but a write_conflict is a plain retry, so no Reload is offered.
    expect(page.get_by_label("Name", exact=True)).to_have_value("Retriable draft")
    expect(page.get_by_role("button", name="Reload", exact=True)).to_have_count(0)
    # Retrying the same Save now succeeds because the one-shot conflict has cleared.
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as retry:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert retry.value.ok
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID)["name"] == "Retriable draft"


def test_config_conflict_reload_rebases_concurrent_subfolder_scope_and_local_name(group_file_sources_ui):
    """Reloading a config conflict adopts untouched source fields and keeps the local name."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    record = ui.record_file_source("group-a", EDITABLE_SOURCE_ID)
    record["recursive"] = False
    ui.touch_file_source("group-a", EDITABLE_SOURCE_ID)
    page.get_by_label("Name", exact=True).fill("Quarterly reports share local")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as conflict:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == "/api/groups/group-a/file-sources"
    ):
        page.get_by_role("button", name="Reload", exact=True).click()
    expect(page.get_by_label("Include subfolders", exact=True)).not_to_be_checked()
    expect(page.get_by_label("Name", exact=True)).to_have_value("Quarterly reports share local")
    expect(page.get_by_text(REBASE_NOTICE, exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as saved:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert saved.value.ok
    saved_record = ui.record_file_source("group-a", EDITABLE_SOURCE_ID)
    assert saved_record["recursive"] is False
    assert saved_record["name"] == "Quarterly reports share local"


def test_config_conflict_reload_reports_name_conflict_and_keeps_local_name(group_file_sources_ui):
    """Reloading reports a same-field source conflict and keeps the user's name."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    ui.record_file_source("group-a", EDITABLE_SOURCE_ID)["name"] = "Quarterly reports share concurrent"
    ui.touch_file_source("group-a", EDITABLE_SOURCE_ID)
    page.get_by_label("Name", exact=True).fill("Quarterly reports share local conflict")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as conflict:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == "/api/groups/group-a/file-sources"
    ):
        page.get_by_role("button", name="Reload", exact=True).click()
    expect(page.get_by_text(f"{REBASE_NOTICE} You and someone else both changed: Name. Your values are shown.", exact=True)).to_be_visible()
    expect(page.get_by_label("Name", exact=True)).to_have_value("Quarterly reports share local conflict")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as saved:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert saved.value.ok
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID)["name"] == "Quarterly reports share local conflict"


def test_config_conflict_reload_reports_deleted_source_without_resaving(group_file_sources_ui):
    """Reloading after a stale save shows that the source was deleted and does not save again."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    ui.drop_file_source_for_conflict("group-a", EDITABLE_SOURCE_ID)
    page.get_by_label("Name", exact=True).fill("Quarterly reports share deleted local")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as conflict:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == "/api/groups/group-a/file-sources"
    ):
        page.get_by_role("button", name="Reload", exact=True).click()
    expect(page.get_by_text(REBASE_DELETED_NOTICE, exact=True)).to_be_visible()
    writes = [
        entry for entry in ui.writes
        if entry.method == "PATCH" and entry.path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ]
    assert len(writes) == 1
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID) is None


@pytest.mark.parametrize("defect", ["config_revision", "source_actions"])
def test_list_item_missing_a_required_field_is_a_hard_load_error(group_file_sources_ui, defect):
    """Every list item must carry a string config_revision and an array source_actions; a row missing
    either is a hard load error, never a silently usable source."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.file_source_list_item_defect = defect
    open_sources(ui)
    expect(page.get_by_text(re.compile("file sources response was malformed"))).to_be_visible()
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)


def test_delete_keep_documents_removes_only_the_source(group_file_sources_ui):
    """Deleting and keeping documents sends the version marker and the false choice, and removes the row."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Keep documents", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}", "DELETE")
    assert set(write.body) == {"expected_config_revision", "delete_associated_files"}
    assert write.body["delete_associated_files"] is False
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID) is None


def test_delete_documents_too_shows_the_counts(group_file_sources_ui):
    """Deleting with the documents removed too sends the true choice and reports the counts."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Delete documents too", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}", "DELETE")
    assert write.body["delete_associated_files"] is True
    # The success toast carries the counts the server returned (3 deleted, 1 skipped).
    expect(page.get_by_text(re.compile(r"File source deleted.*3 deleted.*1 skipped"))).to_be_visible()
    expect(row(ui, EDITABLE_NAME)).to_have_count(0)


def test_delete_incomplete_keeps_the_source_and_shows_counts(group_file_sources_ui):
    """A delete refused after removing documents keeps the source listed and reports the counts."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.file_source_delete_plan[("group-a", EDITABLE_SOURCE_ID)] = {
        "status": 409,
        "payload": {
            "error": "The documents were removed, but the file source could not be deleted.",
            "error_code": "delete_incomplete",
            "partial": True,
            "delete_result": {
                "associated_files_requested": True,
                "documents_deleted": 2, "documents_skipped": 1, "documents_failed": 0,
            },
        },
    }
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Delete documents too", exact=True).click()
    assert response.value.status == 409
    # The modal stays open with the counts, and the source is still listed.
    expect(page.get_by_text(re.compile(r"documents were removed.*2 deleted.*1 skipped"))).to_be_visible()
    expect(page.get_by_role("button", name="Delete documents too", exact=True)).to_be_visible()
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID) is not None


def test_partial_delete_says_the_documents_were_deleted(group_file_sources_ui):
    """A partial refusal that already removed documents says so, never that nothing changed."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.file_source_delete_plan[("group-a", EDITABLE_SOURCE_ID)] = {
        "status": 409,
        "payload": {
            "error": "Removing the file source did not finish.",
            "partial": True,
            "delete_result": {
                "associated_files_requested": True,
                "documents_deleted": 4, "documents_skipped": 0, "documents_failed": 0,
            },
        },
    }
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ):
        page.get_by_role("button", name="Delete documents too", exact=True).click()
    expect(page.get_by_text(re.compile(r"documents were deleted.*4 deleted"))).to_be_visible()


def test_delete_refused_while_a_sync_runs_is_explained(group_file_sources_ui):
    """A delete refused because a sync is running explains it rather than claiming a conflict."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.mark_file_source_running("group-a", EDITABLE_SOURCE_ID)
    open_manager(ui)
    row(ui, EDITABLE_NAME).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as response:
        page.get_by_role("button", name="Delete documents too", exact=True).click()
    assert response.value.status == 409
    expect(page.get_by_text(BUSY_MESSAGE, exact=True)).to_be_visible()
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID) is not None


def test_sync_now_starts_a_run(group_file_sources_ui):
    """Sync now queues a run through the group route and confirms it started."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/sync"
    ) as response:
        row(ui, EDITABLE_NAME).get_by_role("button", name=f"Sync {EDITABLE_NAME} now", exact=True).click()
    assert response.value.status == 202
    expect(page.get_by_text(re.compile(rf"Sync started for {re.escape(EDITABLE_NAME)}"))).to_be_visible()


def test_sync_now_refusal_is_shown_verbatim(group_file_sources_ui):
    """A Sync now refused because one is already running shows the reviewed message verbatim."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.mark_file_source_running("group-a", EDITABLE_SOURCE_ID)
    open_manager(ui)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/sync"
    ) as response:
        row(ui, EDITABLE_NAME).get_by_role("button", name=f"Sync {EDITABLE_NAME} now", exact=True).click()
    assert response.value.status == 400
    expect(page.get_by_text(SYNC_BUSY_MESSAGE, exact=True)).to_be_visible()


def test_sync_now_concurrent_limit_is_shown_verbatim(group_file_sources_ui):
    """A Sync now refused by the concurrent-run limit shows the reviewed limit message verbatim."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.file_source_sync_limit_reached.add(("group-a", EDITABLE_SOURCE_ID))
    open_manager(ui)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/sync"
    ) as response:
        row(ui, EDITABLE_NAME).get_by_role("button", name=f"Sync {EDITABLE_NAME} now", exact=True).click()
    assert response.value.status == 400
    expect(page.get_by_text(SYNC_LIMIT_MESSAGE, exact=True)).to_be_visible()


def test_run_history_expands_from_the_group_route(group_file_sources_ui):
    """Showing a source's history loads its runs from the group route."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    with page.expect_response(
        lambda response: response.request.method == "GET"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/runs"
    ):
        row(ui, EDITABLE_NAME).get_by_role("button", name="Show sync history", exact=True).click()
    expect(row(ui, EDITABLE_NAME).get_by_text("completed", exact=True)).to_be_visible()
    assert_no_personal_reads(ui)


def test_test_connection_and_browse_run_against_the_draft(group_file_sources_ui):
    """The editor tests the connection and browses the remote path through the saved-source routes."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/test-connection"
    ):
        page.get_by_role("button", name="Test connection", exact=True).click()
    # The success shape reports the counts the server saw, never a bare "succeeded".
    expect(page.get_by_text(re.compile(r"Connected\. Checked 12 entries: 3 folders, 9 files\."))).to_be_visible()

    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/browse"
    ):
        page.get_by_role("button", name="Browse the source", exact=True).click()
    expect(page.get_by_text(re.compile("budget.xlsx"))).to_be_visible()
    assert_no_personal_reads(ui)


def test_failed_test_connection_shows_the_server_message_verbatim(group_file_sources_ui):
    """A failed connection test is an HTTP 400 whose message is shown verbatim, not a success shape."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.file_source_test_failure = "The network share refused the connection: access denied."
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/test-connection"
    ) as response:
        page.get_by_role("button", name="Test connection", exact=True).click()
    assert response.value.status == 400
    expect(page.get_by_text(
        "The network share refused the connection: access denied.", exact=True)).to_be_visible()
    # A failed test never renders as a connected summary.
    expect(page.get_by_text(re.compile("Connected. Checked"))).to_have_count(0)


def test_browse_opens_a_folder_by_type(group_file_sources_ui):
    """Browse starts at the source root and opens a folder by sending back its path, which the engine
    returns relative to the root; an entry is a folder by `type`, not `is_dir`. Browsing never
    changes the root itself."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/browse"
    ) as first:
        page.get_by_role("button", name="Browse the source", exact=True).click()
    # The first browse lists the root itself: the browse path is relative to it, so it is empty,
    # never the root's own network path (which the server would resolve under the root and fail).
    assert (first.value.request.post_data_json or {}).get("browse_path") == ""
    assert first.value.ok
    expect(page.get_by_text("Browsing the source root", exact=True)).to_be_visible()
    # The folder is labelled as a folder and opens; the file is labelled as a file, from the real
    # `type` field.
    expect(page.get_by_role("button", name=re.compile(r"^Folder: reports"))).to_be_visible()
    expect(page.get_by_text("File: budget.xlsx", exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/browse"
        and (response.request.post_data_json or {}).get("browse_path") == "reports"
    ) as opened:
        page.get_by_role("button", name=re.compile(r"^Folder: reports")).click()
    assert opened.value.ok
    expect(page.get_by_text("Browsing reports", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^Folder: 2024"))).to_be_visible()
    expect(page.get_by_text("File: summary.pdf", exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/browse"
        and (response.request.post_data_json or {}).get("browse_path") == ""
    ):
        page.get_by_role("button", name="Up one folder", exact=True).click()
    expect(page.get_by_text("Browsing the source root", exact=True)).to_be_visible()
    expect(page.get_by_label("Network path", exact=True)).to_have_value("\\\\files.example.test\\reports")
    assert_no_personal_reads(ui)


def test_ignore_then_restore_tracks_the_returned_item(group_file_sources_ui):
    """Ignoring a browsed path flips its control from the item's `ignored` flag, and restore flips back."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/browse"
    ):
        page.get_by_role("button", name="Browse the source", exact=True).click()
    file_entry = page.get_by_role("listitem").filter(has_text="File: budget.xlsx")
    # Browse cannot report ignore state, so every entry defaults to "Ignore".
    ignore_button = file_entry.get_by_role("button", name="Ignore", exact=True)
    expect(ignore_button).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/ignore-path"
        and (response.request.post_data_json or {}).get("ignored") is True
    ):
        ignore_button.click()
    # The returned item's `ignored: true` flips the control to Restore without a re-browse.
    restore_button = file_entry.get_by_role("button", name="Restore", exact=True)
    expect(restore_button).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/ignore-path"
        and (response.request.post_data_json or {}).get("ignored") is False
    ):
        restore_button.click()
    expect(file_entry.get_by_role("button", name="Ignore", exact=True)).to_be_visible()
    assert_no_personal_reads(ui)


SELECTION_SOURCE_ID, SELECTION_NAME = "group-a-selection-source", "Contracts share with a selection"
PATH_INVALID_MESSAGE = (
    "A path can\u2019t have an empty, \u201c.\u201d or \u201c..\u201d folder name. "
    "Enter a folder or file under the source root."
)


def seed_selection_source(ui):
    """A source whose four sync fields are all set away from their defaults."""
    ui._seed_file_sources("group-a", [*ui.native_file_sources["group-a"], group_file_source(
        "group-a", SELECTION_SOURCE_ID, SELECTION_NAME, source_type="smb", secret_stored=True,
        username="svc-contracts", connection={
            "unc_path": "\\\\files.example.test\\contracts",
            "selected_paths": ["reports/2024", "budget.xlsx"],
        },
        filters={"fixed_tags": ["finance", "quarterly"], "folder_tag_mode": "none"},
        remote_delete_policy="hard_delete",
    )])


def sync_field_values(record_or_body):
    connection = record_or_body.get("connection") or {}
    filters = record_or_body.get("filters") or {}
    return {
        "selected_paths": connection.get("selected_paths"),
        "fixed_tags": filters.get("fixed_tags"),
        "folder_tag_mode": filters.get("folder_tag_mode"),
        "remote_delete_policy": record_or_body.get("remote_delete_policy"),
    }


def save_changes(ui, source_id):
    page = ui.page
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{source_id}"
    ) as response:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok, response.value.text()
    return last_write(ui, f"/api/groups/group-a/file-sources/{source_id}", "PATCH")


def test_an_edit_saves_the_stored_selection_tags_and_choices_untouched(group_file_sources_ui):
    """The editor shows the stored selection, fixed tags, folder tags and delete policy, and a save
    that only renames the source sends every one of them back unchanged."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    seed_selection_source(ui)
    stored = sync_field_values(ui.record_file_source("group-a", SELECTION_SOURCE_ID))
    open_manager(ui)
    open_editor_for(ui, SELECTION_NAME)
    selection = page.get_by_role("list", name="Selected folders and files")
    expect(selection.get_by_role("listitem")).to_have_text(["reports/2024", "budget.xlsx"])
    expect(page.get_by_role("list", name="Fixed tags").get_by_role("listitem")).to_have_text(["finance", "quarterly"])
    expect(page.get_by_label("Folder tags", exact=True)).to_have_value("none")
    expect(page.get_by_label("When a source file is deleted", exact=True)).to_have_value("hard_delete")
    expect(page.get_by_text(
        "The next sync deletes the document from this group when its source file is deleted.", exact=True,
    )).to_be_visible()
    write = rename_and_save(ui, SELECTION_SOURCE_ID, SELECTION_NAME, opened=True)
    assert sync_field_values(write.body) == stored
    assert write.body["connection"]["unc_path"] == "\\\\files.example.test\\contracts"
    assert sync_field_values(ui.record_file_source("group-a", SELECTION_SOURCE_ID)) == stored


def test_browsing_selects_folders_and_files_to_sync(group_file_sources_ui):
    """Browse selects folders and files under the root; the selection is saved relative to the root
    and the root itself is never changed."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    expect(page.get_by_text("Syncing everything under the source root.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Browse the source", exact=True).click()
    select_budget = page.get_by_role("button", name="Select budget.xlsx", exact=True)
    expect(select_budget).to_have_attribute("aria-pressed", "false")
    select_budget.click()
    expect(select_budget).to_have_attribute("aria-pressed", "true")
    expect(select_budget).to_have_text("Selected")
    page.get_by_role("button", name=re.compile(r"^Folder: reports")).click()
    page.get_by_role("button", name="Select reports/2024", exact=True).click()
    selection = page.get_by_role("list", name="Selected folders and files")
    expect(selection.get_by_role("listitem")).to_have_text(["budget.xlsx", "reports/2024"])
    # Deselecting from the list is the same as deselecting from the browse, which it updates.
    page.get_by_role("button", name="Stop syncing budget.xlsx", exact=True).click()
    expect(selection.get_by_role("listitem")).to_have_text(["reports/2024"])
    page.get_by_role("button", name="Up one folder", exact=True).click()
    expect(page.get_by_role("button", name="Select budget.xlsx", exact=True)).to_have_attribute("aria-pressed", "false")
    write = save_changes(ui, EDITABLE_SOURCE_ID)
    assert write.body["connection"] == {
        "unc_path": "\\\\files.example.test\\reports", "selected_paths": ["reports/2024"],
    }
    stored = ui.record_file_source("group-a", EDITABLE_SOURCE_ID)
    assert stored["connection"]["selected_paths"] == ["reports/2024"]
    assert stored["connection"]["unc_path"] == "\\\\files.example.test\\reports"
    assert_no_personal_reads(ui)


def test_a_typed_path_is_normalized_and_one_leaving_the_root_is_refused(group_file_sources_ui):
    """A typed path is added as the server stores it and once, ignoring case; a path leaving the root
    is refused with a reason before anything is sent; and a typed path left unadded blocks the save
    rather than being silently dropped."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    path_input = page.get_by_label("Add a folder or file", exact=True)
    path_input.fill("Reports\\2024\\")
    path_input.press("Enter")
    selection = page.get_by_role("list", name="Selected folders and files")
    expect(selection.get_by_role("listitem")).to_have_text(["Reports/2024"])
    path_input.fill(" reports/2024 ")
    page.get_by_role("button", name="Add path", exact=True).click()
    expect(selection.get_by_role("listitem")).to_have_text(["Reports/2024"])
    path_input.fill("reports/../secrets")
    page.get_by_role("button", name="Add path", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=PATH_INVALID_MESSAGE)).to_be_visible()
    expect(path_input).to_have_value("reports/../secrets")
    expect(selection.get_by_role("listitem")).to_have_text(["Reports/2024"])
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_text("Add the path you typed, or clear it, before saving.", exact=True)).to_be_visible()
    assert not [entry for entry in ui.writes if entry.method == "PATCH"], "An unadded path must block the save."
    path_input.fill("")
    write = save_changes(ui, EDITABLE_SOURCE_ID)
    assert write.body["connection"]["selected_paths"] == ["Reports/2024"]
    assert ui.record_file_source("group-a", EDITABLE_SOURCE_ID)["connection"]["selected_paths"] == ["Reports/2024"]


def test_fixed_tags_folder_tags_and_delete_policy_are_saved_as_shown(group_file_sources_ui):
    """Fixed tags show as the server stores them, the group's existing tags are offered most used
    first, and the folder tag and delete choices are saved exactly as chosen."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    expect(page.get_by_text("No fixed tags.", exact=True)).to_be_visible()
    offered = page.get_by_role("button", name=re.compile(r"^Add the existing tag "))
    expect(offered).to_have_text(["+ quarterly", "+ finance", "+ legal"])
    tag_input = page.get_by_label("Add a fixed tag", exact=True)
    tag_input.fill("Q1 Reports")
    expect(page.get_by_text("Saved as \u201cq1-reports\u201d.", exact=True)).to_be_visible()
    tag_input.press("Enter")
    page.get_by_role("button", name="Add the existing tag legal", exact=True).click()
    tags = page.get_by_role("list", name="Fixed tags").get_by_role("listitem")
    expect(tags).to_have_text(["q1-reports", "legal"])
    expect(offered).to_have_text(["+ quarterly", "+ finance"])
    tag_input.fill("fin")
    expect(offered).to_have_text(["+ finance"])
    tag_input.fill("!!")
    page.get_by_role("button", name="Add tag", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="A tag needs at least one letter or number.")).to_be_visible()
    tag_input.fill("")
    page.get_by_role("button", name="Remove the fixed tag q1-reports", exact=True).click()
    expect(tags).to_have_text(["legal"])
    page.get_by_label("Folder tags", exact=True).select_option("full_path")
    expect(page.get_by_text(
        "A file in Reports/2024 also gets the tags \u201creports\u201d and \u201c2024\u201d.", exact=True,
    )).to_be_visible()
    page.get_by_label("When a source file is deleted", exact=True).select_option("hard_delete")
    write = save_changes(ui, EDITABLE_SOURCE_ID)
    assert sync_field_values(write.body) == {
        "selected_paths": [], "fixed_tags": ["legal"], "folder_tag_mode": "full_path",
        "remote_delete_policy": "hard_delete",
    }
    assert sync_field_values(ui.record_file_source("group-a", EDITABLE_SOURCE_ID)) == sync_field_values(write.body)
    tag_reads = [entry for entry in ui.requests if entry.path == "/api/group_documents/tags"]
    assert tag_reads and all(entry.query == {"group_id": ["group-a"]} for entry in tag_reads), (
        "The existing tags must come from the explicit-group tag read, never the active group."
    )
    assert_no_personal_reads(ui)


def test_existing_tag_suggestions_are_optional(group_file_sources_ui):
    """A failed read of the group's tags costs only the suggestions: the editor opens, says so, and a
    typed tag is still saved."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.group_document_tag_read_failures.add("group-a")
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    expect(page.get_by_text(
        "This group\u2019s existing tags couldn\u2019t be loaded. You can still type a tag.", exact=True,
    )).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^Add the existing tag "))).to_have_count(0)
    page.get_by_label("Add a fixed tag", exact=True).fill("legal")
    page.get_by_role("button", name="Add tag", exact=True).click()
    write = save_changes(ui, EDITABLE_SOURCE_ID)
    assert write.body["filters"]["fixed_tags"] == ["legal"]


def test_config_conflict_reload_adopts_a_concurrent_fixed_tag_change(group_file_sources_ui):
    """A conflict reload adopts another manager's change to the fixed tags and folder tags the user
    left alone, and keeps the user's own edit."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    record = ui.record_file_source("group-a", EDITABLE_SOURCE_ID)
    record["filters"]["fixed_tags"] = ["legal"]
    record["filters"]["folder_tag_mode"] = "parent"
    ui.touch_file_source("group-a", EDITABLE_SOURCE_ID)
    page.get_by_label("Name", exact=True).fill("Quarterly reports share, tags reloaded")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}"
    ) as conflict:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    page.get_by_role("button", name="Reload", exact=True).click()
    expect(page.get_by_text(REBASE_NOTICE, exact=True)).to_be_visible()
    expect(page.get_by_role("list", name="Fixed tags").get_by_role("listitem")).to_have_text(["legal"])
    expect(page.get_by_label("Folder tags", exact=True)).to_have_value("parent")
    write = save_changes(ui, EDITABLE_SOURCE_ID)
    assert write.body["filters"]["fixed_tags"] == ["legal"]
    assert write.body["name"] == "Quarterly reports share, tags reloaded"


def test_search_filters_sources_by_name_and_path(group_file_sources_ui):
    """The search narrows the loaded list by name or remote path without another read, says when
    nothing matches, and restores the list when cleared."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
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


def assert_dialog_fits(page):
    """Nothing in the open dialog scrolls sideways or reaches past the viewport."""
    assert page.get_by_role("dialog").evaluate("""dialog => {
        const viewport = window.innerWidth;
        return [...dialog.querySelectorAll('*')].every((node) => {
            const box = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            const scrollsSideways = ['auto', 'scroll'].includes(style.overflowX) && node.scrollWidth > node.clientWidth + 1;
            return !scrollsSideways && (box.width === 0 || (box.left >= -1 && box.right <= viewport + 1));
        });
    }"""), "The file source editor overflows horizontally."


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_editor_sync_fields_fit_desktop_and_mobile(group_file_sources_ui, theme, width, height):
    """The selection, the browse listing, the fixed tags and both choices fit both breakpoints."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    seed_selection_source(ui)
    open_sources(ui, theme=theme, width=width, height=height)
    open_editor_for(ui, SELECTION_NAME)
    page.get_by_role("button", name="Browse the source", exact=True).click()
    expect(page.get_by_text("Browsing the source root", exact=True)).to_be_visible()
    page.get_by_label("Add a fixed tag", exact=True).fill("A very long tag name that the server shortens")
    page.get_by_role("dialog").get_by_text("Tags and deletions", exact=True).scroll_into_view_if_needed()
    assert_dialog_fits(page)
    ui.assert_no_overflow()


def test_locked_group_manager_gets_a_read_only_section(group_file_sources_ui):
    """A locked group is readable but advertises no operations, so a manager sees no write tools and
    never issues a test, browse or ignore request."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.set_file_source_policy("group-a", role="Owner", status="locked")
    open_sources(ui)
    expect(page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    # The list still loads, but every write control is gone: no create, edit, sync or delete.
    expect(row(ui, EDITABLE_NAME)).to_be_visible()
    expect(page.get_by_role("button", name="New file source", exact=True)).to_have_count(0)
    expect(row(ui, EDITABLE_NAME).get_by_role("button", name=f"Edit {EDITABLE_NAME}", exact=True)).to_have_count(0)
    expect(row(ui, EDITABLE_NAME).get_by_role("button", name=f"Sync {EDITABLE_NAME} now", exact=True)).to_have_count(0)
    # No draft-tool request is ever made from a read-only section.
    assert not [
        entry for entry in ui.requests
        if "/test-connection" in entry.path or "/browse" in entry.path or "/ignore-path" in entry.path
    ], "A locked read-only section must not test, browse or ignore."
    assert not ui.unexpected_requests, ui.unexpected_requests
    assert_no_personal_reads(ui)


def test_editor_offers_only_eligible_group_identities(group_file_sources_ui):
    """The editor's identity picker lists the group's File Sync identity, read from the group route."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    page.get_by_role("button", name="New file source", exact=True).click()
    # The default credential mode is a saved group identity, so the picker is shown at once. The
    # picker is the connection dialog's identity <select>, located by the eligible option it carries.
    page.get_by_text("Use a saved group identity", exact=True).wait_for()
    picker = page.get_by_role("dialog").locator("select").filter(
        has=page.get_by_role("option", name=IDENTITY_LABEL, exact=True))
    expect(picker).to_be_visible()
    expect(picker.get_by_role("option", name=IDENTITY_LABEL, exact=True)).to_have_count(1)
    # Only the eligible File Sync identity is offered, beside the placeholder -- no ineligible ones.
    expect(picker.get_by_role("option")).to_have_count(2)
    identity_reads = [
        entry for entry in ui.requests
        if entry.path == "/api/groups/group-a/identities" and entry.method == "GET"
    ]
    assert identity_reads, "The editor must list identities from the group route."
    assert_no_personal_reads(ui)


def test_malformed_list_is_a_hard_load_error(group_file_sources_ui):
    """A malformed list envelope is a hard load error, never an empty successful load."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    ui.malformed_file_source_list = True
    open_sources(ui)
    expect(page.get_by_text(re.compile("file sources response was malformed"))).to_be_visible()
    assert_no_personal_reads(ui)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_member_has_no_native_file_sources_section(group_file_sources_ui, theme, width, height):
    """A member's file sources section is manager-only, so it is locked with the server's reason."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_sources(ui, group="group-b", theme=theme, width=width, height=height)
    expect(page.get_by_text("File sources is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(GROUP_CONNECTIONS_ROLE_REASON, exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New file source", exact=True)).to_have_count(0)
    assert not sources_get(ui, group="group-b"), (
        "A member's unavailable section must not read the group file sources route."
    )
    assert_no_personal_reads(ui)
    ui.assert_no_overflow()


def test_file_source_scope_seam_holds():
    """The personal adapter's transport is unchanged and the group seam never reaches personal (runtime)."""
    assert (V2_DIR / "node_modules").is_dir(), (
        "application/v2_ui/node_modules is missing; restore the frontend dependencies first"
    )
    assert SEAM_LOGIC_TS.exists(), "The scope-seam runtime check is missing."
    # Call the local esbuild binary directly. A bare `npx` can download a package, and `node_modules`
    # is a shared junction here, so the bundle carries a unique name and is removed afterwards.
    esbuild = V2_DIR / "node_modules" / "esbuild" / "bin" / "esbuild"
    assert esbuild.exists(), (
        "application/v2_ui/node_modules/esbuild is missing; restore the frontend dependencies first"
    )
    bundle = V2_DIR / "node_modules" / f".cache-group-file-source-seam-{uuid.uuid4().hex}.mjs"
    try:
        subprocess.run(
            [
                "node", str(esbuild), str(SEAM_LOGIC_TS), "--bundle", "--platform=node",
                "--format=esm", "--packages=external", "--define:import.meta.env={}",
                f"--outfile={bundle}", "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            ["node", str(bundle)], cwd=str(V2_DIR), capture_output=True, text=True,
        )
    finally:
        if bundle.exists():
            bundle.unlink()
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the scope-seam runtime checks failed")
