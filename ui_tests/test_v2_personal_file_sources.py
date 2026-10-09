# test_v2_personal_file_sources.py
"""
Production-SPA tests for personal native source creation and configuration.
Version: 0.261.310
Implemented in: 0.261.310
"""

import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.personal_file_sources import (
    BASE, SOURCE_ID, SOURCE_NAME, STORED_PASSWORD, personal_file_sources_ui,
)


pytestmark = pytest.mark.ui


def source_row(ui, name=SOURCE_NAME):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def open_sources(ui, **layout):
    ui.open("/workspace/sync", **layout)
    expect(ui.page.get_by_role("heading", name="File sources", exact=True)).to_be_visible()
    expect(source_row(ui)).to_be_visible()


def edit_source(ui, name=SOURCE_NAME):
    source_row(ui, name).get_by_role("button", name=f"Edit {name}", exact=True).click()
    expect(ui.page.get_by_role("button", name="Save changes", exact=True)).to_be_enabled()
    return ui.page.get_by_role("dialog")


def last_write(ui, method, path):
    writes = [entry for entry in ui.writes if entry.method == method and entry.path == path]
    assert writes, f"No {method} to {path}."
    return writes[-1]


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844),
])
def test_native_personal_layout_and_focus(personal_file_sources_ui, theme, width, height):
    ui = personal_file_sources_ui
    open_sources(ui, theme=theme, width=width, height=height)
    dialog = edit_source(ui)
    expect(dialog.get_by_label("Name", exact=True)).to_be_focused()
    expect(ui.page.get_by_role("link", name=re.compile("classic", re.I))).to_have_count(0)
    ui.assert_no_overflow()
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(source_row(ui).get_by_role("button", name=f"Edit {SOURCE_NAME}", exact=True)).to_be_focused()


@pytest.mark.parametrize("source_type,auth_type,fields", [
    ("smb", "username_password", {"Network path": "\\\\files\\new", "Username": "svc-new", "Password": "fixture-draft-password"}),
    ("azure_files", "client_secret", {"File service URL": "https://storage.file.core.windows.net", "Share name": "reports", "Directory": "2026",
                                   "Client ID": "client-new", "Tenant ID": "tenant-new", "Client secret": "fixture-draft-client-secret"}),
    ("azure_blob", "connection_string", {"Blob service URL": "https://storage.blob.core.windows.net", "Container": "reports", "Prefix": "2026",
                                        "Connection string": "fixture-draft-connection-string"}),
])
def test_create_reopen_and_edit_each_connector(personal_file_sources_ui, source_type, auth_type, fields):
    ui, page = personal_file_sources_ui, personal_file_sources_ui.page
    open_sources(ui)
    page.get_by_role("button", name="New file source", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Name", exact=True)).to_be_visible()
    dialog.get_by_label("Name", exact=True).fill(f"New {source_type}")
    dialog.get_by_label("Source type", exact=True).select_option(source_type)
    dialog.get_by_label("Enter credentials directly", exact=True).check()
    dialog.get_by_label("Authentication method", exact=True).select_option(auth_type)
    for label, value in fields.items():
        dialog.get_by_label(re.compile(rf"^{re.escape(label)}")).fill(value)
    dialog.get_by_role("button", name="Test connection", exact=True).click()
    expect(dialog.get_by_text("Connected. Checked 1 entry: 0 folders, 1 file.", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Create source", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    write = last_write(ui, "POST", BASE)
    assert write.body["source_type"] == source_type and write.body["credentials"]["auth_type"] == auth_type
    assert not [entry for entry in ui.writes if entry.path.endswith("/sync")]
    dialog = edit_source(ui, f"New {source_type}")
    secret_label = {"username_password": "Password", "client_secret": "Client secret", "connection_string": "Connection string"}[auth_type]
    expect(dialog.get_by_label(re.compile(rf"^{re.escape(secret_label)}(?: \(stored\))?$"))).to_have_value("")
    dialog.get_by_label("Name", exact=True).fill(f"Saved {source_type}")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(source_row(ui, f"Saved {source_type}")).to_be_visible()
    assert last_write(ui, "PATCH", f"{BASE}/created-source-1").body["expected_config_revision"]
    ui.assert_no_secret_storage(*[value for label, value in fields.items() if label == secret_label])


def test_all_fields_browse_selection_tags_and_ignore(personal_file_sources_ui):
    ui, page = personal_file_sources_ui, personal_file_sources_ui.page
    open_sources(ui)
    dialog = edit_source(ui)
    dialog.get_by_role("button", name="Browse the source", exact=True).click()
    expect(dialog.get_by_role("button", name="Ignore report.pdf", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Ignore report.pdf", exact=True).click()
    expect(dialog.get_by_role("button", name="Restore report.pdf", exact=True)).to_be_visible()
    ignored = last_write(ui, "POST", f"{BASE}/{SOURCE_ID}/ignore-path")
    assert ignored.body == {"remote_path": "\\\\files\\reports\\report.pdf", "ignored": True}
    dialog.get_by_role("button", name="Restore report.pdf", exact=True).click()
    expect(dialog.get_by_role("button", name="Ignore report.pdf", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Select report.pdf", exact=True).click()
    dialog.get_by_label("Include patterns", exact=True).fill("*.pdf, *.docx")
    dialog.get_by_label("Exclude patterns", exact=True).fill("drafts/*")
    dialog.get_by_label("Allowed file types", exact=True).fill("pdf, docx")
    dialog.get_by_label("Folder tags", exact=True).select_option("full_path")
    dialog.get_by_label("When a source file is deleted", exact=True).select_option("hard_delete")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    write = last_write(ui, "PATCH", f"{BASE}/{SOURCE_ID}").body
    assert write["connection"]["selected_paths"] == ["Reports", "report.pdf"]
    assert write["filters"] == {
        "include_patterns": ["*.pdf", "*.docx"], "exclude_patterns": ["drafts/*"],
        "allowed_extensions": ["pdf", "docx"], "fixed_tags": ["finance"], "folder_tag_mode": "full_path",
    }
    assert write["remote_delete_policy"] == "hard_delete"
    assert write["credentials"]["password"] == "" and ui.source_secrets[SOURCE_ID] == STORED_PASSWORD
    dialog = edit_source(ui)
    expect(dialog.get_by_label("Folder tags", exact=True)).to_have_value("full_path")


def test_saved_identity_is_selected_without_inline_credentials(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    dialog = edit_source(ui)
    dialog.get_by_label("Use a saved workspace identity", exact=True).check()
    dialog.get_by_label("Identity", exact=True).select_option("personal-smb-identity")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    write = last_write(ui, "PATCH", f"{BASE}/{SOURCE_ID}").body
    assert write["identity_id"] == "personal-smb-identity" and "credentials" not in write
    dialog = edit_source(ui)
    expect(dialog.get_by_label("Identity", exact=True)).to_have_value("personal-smb-identity")


def test_conflict_reload_preserves_local_edits_and_adopts_remote_fields(personal_file_sources_ui):
    ui, page = personal_file_sources_ui, personal_file_sources_ui.page
    open_sources(ui)
    dialog = edit_source(ui)
    dialog.get_by_label("Name", exact=True).fill("Local reports")
    ui.change_source(SOURCE_ID, recursive=False, remote_delete_policy="hard_delete")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_text("This file source changed while you were editing.", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Reload", exact=True).click()
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Local reports")
    expect(dialog.get_by_label("Include subfolders", exact=True)).not_to_be_checked()
    expect(dialog.get_by_label("When a source file is deleted", exact=True)).to_have_value("hard_delete")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(source_row(ui, "Local reports")).to_be_visible()
    assert last_write(ui, "PATCH", f"{BASE}/{SOURCE_ID}").body["expected_config_revision"] == "revision-2"


def test_options_failure_is_explicit_and_retry_does_not_guess(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    ui.reject_next("GET", "/api/file-sync/personal/source-options", error="Options unavailable.")
    ui.page.get_by_role("button", name="New file source", exact=True).click()
    dialog = ui.page.get_by_role("dialog")
    expect(dialog.get_by_role("alert")).to_contain_text("Options unavailable.")
    expect(dialog.get_by_role("button", name="Create source", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Retry editor", exact=True).click()
    expect(dialog.get_by_role("button", name="Create source", exact=True)).to_be_visible()


def test_late_test_response_is_not_applied_to_changed_connection(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    dialog = edit_source(ui)
    ui.defer_next("POST", f"{BASE}/{SOURCE_ID}/test-connection")
    with ui.page.expect_request(f"**{BASE}/{SOURCE_ID}/test-connection"):
        dialog.get_by_role("button", name="Test connection", exact=True).click()
    expect(dialog.get_by_role("button", name="Test connection", exact=True)).to_be_disabled()
    assert ui.pending_responses
    dialog.get_by_label("Network path", exact=True).fill("\\\\files\\changed")
    ui.release_responses()
    expect(dialog.get_by_text("Connected. Checked 1 entry: 0 folders, 1 file.", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog.get_by_text("Discard your unsaved changes?", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Keep editing", exact=True).click()
    expect(dialog.get_by_label("Network path", exact=True)).to_have_value("\\\\files\\changed")


def test_server_defaults_and_schedule_limits(personal_file_sources_ui):
    ui = personal_file_sources_ui
    ui.source_options["recursive_allowed"] = False
    ui.source_options["default_remote_delete_policy"] = "hard_delete"
    open_sources(ui)
    ui.page.get_by_role("button", name="New file source", exact=True).click()
    dialog = ui.page.get_by_role("dialog")
    expect(dialog.get_by_label("Name", exact=True)).to_be_visible()
    expect(dialog.get_by_label("Include subfolders", exact=True)).to_have_count(0)
    expect(dialog.get_by_label("When a source file is deleted", exact=True)).to_have_value("hard_delete")
    dialog.get_by_label("Name", exact=True).fill("Scheduled identity source")
    dialog.get_by_label("Identity", exact=True).select_option("personal-smb-identity")
    dialog.get_by_label("Network path", exact=True).fill("\\\\files\\scheduled")
    dialog.get_by_label("Sync on a schedule", exact=True).check()
    interval = dialog.get_by_role("spinbutton")
    interval.fill("4")
    expect(dialog.get_by_role("button", name="Create source", exact=True)).to_be_disabled()
    interval.fill("12.5")
    expect(dialog.get_by_role("button", name="Create source", exact=True)).to_be_disabled()
    interval.fill("30")
    dialog.get_by_role("button", name="Create source", exact=True).click()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    write = last_write(ui, "POST", BASE).body
    assert write["schedule"] == {"enabled": True, "interval_minutes": 30}
    assert write["recursive"] is False and write["remote_delete_policy"] == "hard_delete"


def test_deleted_source_conflict_blocks_all_dependent_actions(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    dialog = edit_source(ui)
    dialog.get_by_label("Name", exact=True).fill("Kept draft")
    ui.reject_next("PATCH", f"{BASE}/{SOURCE_ID}", status=409, error="Source changed.", error_code="config_conflict")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_text("Source changed.", exact=True)).to_be_visible()
    del ui.sources[SOURCE_ID]
    dialog.get_by_role("button", name="Reload", exact=True).click()
    expect(dialog.get_by_text("This item was deleted. Copy anything you need, then close.", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("button", name="Test connection", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("button", name="Browse the source", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Kept draft")


def test_failed_save_retains_typed_secret_and_retry_commits_it(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    dialog = edit_source(ui)
    secret = "fixture-personal-replacement-password"
    dialog.get_by_label("Password (stored)", exact=True).fill(secret)
    ui.reject_next("PATCH", f"{BASE}/{SOURCE_ID}", error="Save unavailable.")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Save unavailable.")
    expect(dialog.get_by_label("Password (stored)", exact=True)).to_have_value(secret)
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    assert ui.source_secrets[SOURCE_ID] == secret
    ui.assert_no_secret_storage(secret)


def test_sync_history_and_conditional_delete_remain_native(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    source_row(ui).get_by_role("button", name="Show sync history", exact=True).click()
    expect(source_row(ui).get_by_text("completed", exact=True)).to_be_visible()
    source_row(ui).get_by_role("button", name=f"Sync {SOURCE_NAME} now", exact=True).click()
    expect(ui.page.get_by_text(f"Sync started for {SOURCE_NAME}", exact=True)).to_be_visible()
    source_row(ui).get_by_role("button", name=f"Delete {SOURCE_NAME}", exact=True).click()
    ui.page.get_by_role("button", name="Delete documents too", exact=True).click()
    expect(source_row(ui)).to_have_count(0)
    write = last_write(ui, "DELETE", f"{BASE}/{SOURCE_ID}").body
    assert write == {"expected_config_revision": "revision-1", "delete_associated_files": True}
    expect(ui.page.get_by_text("File source deleted (3 deleted)", exact=True)).to_be_visible()


def test_disabled_personal_sources_do_not_make_source_requests(personal_file_sources_ui):
    ui = personal_file_sources_ui
    ui.disabled_sections["sync"] = "File Sync is unavailable."
    ui.open("/workspace/sync")
    expect(ui.page.get_by_text("File Sync is unavailable.", exact=True)).to_be_visible()
    assert not [entry for entry in ui.requests if entry.path.startswith(BASE)]


def test_cancelled_options_cannot_overwrite_a_reopened_source(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    ui.defer_next("GET", "/api/file-sync/personal/source-options")
    ui.page.get_by_role("button", name="New file source", exact=True).click()
    dialog = ui.page.get_by_role("dialog")
    expect(dialog.get_by_role("status")).to_contain_text("Loading file source configuration")
    assert ui.pending_responses
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    dialog = edit_source(ui)
    ui.release_responses()
    expect(dialog.get_by_label("Name", exact=True)).to_have_value(SOURCE_NAME)
    expect(dialog.get_by_role("button", name="Save changes", exact=True)).to_be_enabled()


def test_late_browse_does_not_offer_paths_for_a_changed_connection(personal_file_sources_ui):
    ui = personal_file_sources_ui
    open_sources(ui)
    dialog = edit_source(ui)
    ui.defer_next("POST", f"{BASE}/{SOURCE_ID}/browse")
    with ui.page.expect_request(f"**{BASE}/{SOURCE_ID}/browse"):
        dialog.get_by_role("button", name="Browse the source", exact=True).click()
    expect(dialog.get_by_role("button", name="Browse the source", exact=True)).to_be_disabled()
    assert ui.pending_responses
    dialog.get_by_label("Network path", exact=True).fill("\\\\files\\changed")
    ui.release_responses()
    expect(dialog.get_by_role("button", name="Browse the source", exact=True)).to_be_enabled()
    expect(dialog.get_by_role("button", name="Select report.pdf", exact=True)).to_have_count(0)
