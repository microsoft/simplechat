# test_v2_group_file_sources.py
"""
Production-SPA coverage for the native scope-aware V2 group file sources section.
Version: 0.261.147
Implemented in: 0.261.147

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
    FILE_SOURCE_CONFLICT_ERROR,
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
        page.get_by_role("dialog").get_by_role("button").filter(has_text="Browse").click()
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
    """Clicking a browsed folder browses into it; the entry is a folder by `type`, not `is_dir`."""
    ui, page = group_file_sources_ui, group_file_sources_ui.page
    open_manager(ui)
    open_editor_for(ui, EDITABLE_NAME)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/browse"
    ) as first:
        page.get_by_role("dialog").get_by_role("button").filter(has_text="Browse").click()
    first_path = (first.value.request.post_data_json or {}).get("browse_path")
    # The folder is labelled as a folder and the file as a file, from the real `type` field.
    expect(page.get_by_role("button", name=re.compile(r"^Folder: reports"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^File: budget.xlsx"))).to_be_visible()
    # Opening the folder browses into its path, which the engine returns as a child of the current path.
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == f"/api/groups/group-a/file-sources/{EDITABLE_SOURCE_ID}/browse"
        and (response.request.post_data_json or {}).get("browse_path") == f"{first_path}/reports"
    ):
        page.get_by_role("button", name=re.compile(r"^Folder: reports")).click()
    expect(page.get_by_text(re.compile(r"Browsing .*reports/reports"))).to_be_visible()
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
        page.get_by_role("dialog").get_by_role("button").filter(has_text="Browse").click()
    file_entry = page.get_by_role("listitem").filter(
        has=page.get_by_role("button", name=re.compile(r"^File: budget.xlsx")))
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
    expect(page.get_by_text("Your role does not permit managing group connections.", exact=True)).to_be_visible()
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
