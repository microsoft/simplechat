# test_v2_personal_identities.py
"""
Native personal identity authoring and concurrency in the production V2 SPA.
Version: 0.261.315
Implemented in: 0.261.315
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.personal_identities import (
    LIST_PATH, SAVED_ID, SAVED_NAME, personal_identities_ui,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import ACTION_ID, connect_options  # noqa: F401
from ui_tests.test_v2_workspace_authoring import editor_section, save_resource
from ui_tests.fixtures.personal_file_sources import BASE as SOURCE_BASE, SOURCE_ID
from ui_tests.test_v2_personal_file_sources import edit_source, open_sources


pytestmark = pytest.mark.ui


def open_identities(ui, **options):
    ui.open("/workspace/identities", **options)
    expect(ui.page.get_by_role("heading", name="Identities", exact=True)).to_be_visible()


def row(ui, name=SAVED_NAME):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def open_new(ui):
    ui.page.get_by_role("button", name="New identity", exact=True).click()
    return ui.page.get_by_role("dialog", name="New identity", exact=True)


def open_edit(ui):
    row(ui).get_by_role("button", name=f"Edit {SAVED_NAME}", exact=True).click()
    return ui.page.get_by_role("dialog", name="Edit identity", exact=True)


def write(ui, method):
    matches = [entry for entry in ui.writes if entry.path.startswith(LIST_PATH) and entry.method == method]
    assert matches
    return matches[-1]


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900),
    ("light", 390, 844), ("dark", 390, 844),
])
def test_native_identity_layout_and_keyboard_focus(personal_identities_ui, theme, width, height):
    ui = personal_identities_ui
    open_identities(ui, theme=theme, width=width, height=height)
    expect(row(ui)).to_be_visible()
    dialog = open_new(ui)
    expect(dialog).to_contain_text("your workspace")
    expect(dialog.get_by_label("Name", exact=True)).to_be_focused()
    ui.assert_no_overflow()
    ui.page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="New identity", exact=True)).to_be_focused()
    assert not any("legacy" in entry.path or entry.path in ("/workspace", "/group_workspaces", "/public_workspaces") for entry in ui.requests)


@pytest.mark.parametrize("auth_type,uses_secret", [
    ("api_key", True), ("bearer_token", True), ("client_secret", True),
    ("connection_string", True), ("username_password", True),
    ("managed_identity", False), ("anonymous", False),
])
def test_creating_every_supported_auth_method(personal_identities_ui, auth_type, uses_secret):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_new(ui)
    dialog.get_by_label("Name", exact=True).fill("Native credential")
    if auth_type == "anonymous":
        dialog.get_by_role("checkbox", name=re.compile("^File Sync")).check()
        dialog.get_by_role("checkbox", name=re.compile("^Actions")).uncheck()
    dialog.get_by_label("Authentication method").select_option(auth_type)
    if auth_type == "username_password":
        dialog.get_by_label("Username", exact=True).fill("svc-personal")
    if auth_type == "client_secret":
        dialog.get_by_label("Client ID", exact=True).fill("app-client")
    if uses_secret:
        dialog.locator('input[type="password"]').fill("fixture-new-secret")
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(row(ui, "Native credential")).to_be_visible()
    body = write(ui, "POST").body
    assert body["credentials"]["auth_type"] == auth_type
    assert "expected_etag" not in body and "user_id" not in body
    ui.assert_no_secret_storage("fixture-new-secret")
    assert urlsplit(ui.page.url).path == "/v2/workspace/identities"
    ui.open("/workspace/identities")
    expect(row(ui, "Native credential")).to_be_visible()


def test_edit_preserves_secret_and_sends_opening_etag(personal_identities_ui):
    ui = personal_identities_ui
    etag = ui.identities[SAVED_ID]["etag"]
    open_identities(ui)
    dialog = open_edit(ui)
    expect(dialog.locator('input[type="password"]')).to_have_value("")
    dialog.get_by_label("Name", exact=True).fill("Renamed credential")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(row(ui, "Renamed credential")).to_be_visible()
    body = write(ui, "PATCH").body
    assert body["expected_etag"] == etag and body["credentials"]["secret"] == ""
    assert ui.identity_secrets[SAVED_ID] == "fixture-existing-personal-secret"


def test_stale_edit_keeps_draft_and_explicitly_rebases(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_edit(ui)
    dialog.get_by_label("Name", exact=True).fill("My edit")
    dialog.locator('input[type="password"]').fill("fixture-rotated-secret")
    ui.identities[SAVED_ID].update(description="Other tab's description", etag='"concurrent-etag"')
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("modified")
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("My edit")
    dialog.get_by_role("button", name="Refresh", exact=True).click()
    expect(dialog.get_by_label("Description (optional)", exact=True)).to_have_value("Other tab's description")
    expect(dialog.locator('input[type="password"]')).to_have_value("fixture-rotated-secret")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    assert write(ui, "PATCH").body["expected_etag"] == '"concurrent-etag"'
    assert ui.identities[SAVED_ID]["description"] == "Other tab's description"


def test_deleted_identity_keeps_draft_without_recreating(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_edit(ui)
    dialog.get_by_label("Name", exact=True).fill("Draft to copy")
    ui.identities.pop(SAVED_ID)
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("deleted")
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Draft to copy")
    expect(dialog.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
    assert ui.created_identity_count == 0


def test_validation_and_network_errors_keep_the_secret_draft(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_new(ui)
    dialog.get_by_label("Name", exact=True).fill("Incomplete credential")
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("requires a secret")
    dialog.locator('input[type="password"]').fill("fixture-retry-secret")
    ui.reject_next("POST", LIST_PATH, status=500, error="Unable to save the identity.")
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Unable to save")
    expect(dialog.locator('input[type="password"]')).to_have_value("fixture-retry-secret")
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog).to_have_count(0)
    assert ui.created_identity_count == 1


def test_dirty_discard_clears_credentials(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_new(ui)
    dialog.get_by_label("Name", exact=True).fill("Discard me")
    dialog.locator('input[type="password"]').fill("fixture-discard-secret")
    ui.page.keyboard.press("Escape")
    expect(dialog.get_by_text("Discard your unsaved changes?", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Keep editing", exact=True).click()
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Discard me")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    dialog.get_by_role("button", name="Discard", exact=True).click()
    dialog = open_new(ui)
    expect(dialog.locator('input[type="password"]')).to_have_value("")
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("")
    ui.assert_no_secret_storage("fixture-discard-secret")


def test_saving_blocks_close_and_duplicate_submission(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_new(ui)
    dialog.get_by_label("Name", exact=True).fill("Slow credential")
    dialog.locator('input[type="password"]').fill("fixture-slow-secret")
    ui.defer_next("POST", LIST_PATH)
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog.get_by_role("button", name="Saving", exact=True)).to_be_disabled()
    dialog.get_by_role("button", name="Close", exact=True).click()
    ui.page.keyboard.press("Escape")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Name", exact=True)).to_be_disabled()
    ui.release_responses()
    expect(dialog).to_have_count(0)
    assert ui.created_identity_count == 1


def test_failed_read_is_not_an_empty_list_and_can_retry(personal_identities_ui):
    ui = personal_identities_ui
    ui.reject_next("GET", LIST_PATH, status=500, error="Unable to load identities.")
    open_identities(ui)
    expect(ui.page.get_by_role("alert")).to_contain_text("Unable to load")
    expect(ui.page.get_by_text("No identities yet", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Retry identities", exact=True).click()
    expect(row(ui)).to_be_visible()


@pytest.mark.parametrize("malformed", ["envelope", "owner", "etag"])
def test_invalid_native_reads_never_render_or_fall_back(personal_identities_ui, malformed):
    ui = personal_identities_ui
    if malformed == "envelope":
        ui.malformed_identity_list = True
    elif malformed == "owner":
        ui.identities[SAVED_ID]["user_id"] = "someone-else"
    else:
        ui.identities[SAVED_ID]["etag"] = ""
    open_identities(ui)
    expect(ui.page.get_by_role("alert")).to_be_visible()
    expect(row(ui)).to_have_count(0)
    assert not any(entry.path.startswith("/api/workspace-identities") for entry in ui.requests)


def test_names_render_as_text_not_markup(personal_identities_ui):
    ui = personal_identities_ui
    name = '<img src=x onerror="window.identityXss=true">'
    ui.identities[SAVED_ID]["name"] = name
    open_identities(ui)
    expect(ui.page.get_by_text(name, exact=True)).to_be_visible()
    assert ui.page.evaluate("window.identityXss === undefined")


def test_in_use_delete_restores_row_and_names_references(personal_identities_ui):
    ui = personal_identities_ui
    ui.identity_references[SAVED_ID] = [{"kind": "action", "id": "connector", "name": "Personal connector"}]
    open_identities(ui)
    resource = row(ui)
    resource.get_by_role("button", name=f"Delete {SAVED_NAME}", exact=True).click()
    resource.get_by_role("button", name="Delete", exact=True).click()
    expect(resource).to_be_visible()
    expect(ui.page.get_by_role("alert")).to_contain_text("Personal connector")
    assert write(ui, "DELETE").body == {"expected_etag": '"etag-1"'}


def test_created_identity_can_bind_to_an_action_without_copying_secrets(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_new(ui)
    dialog.get_by_label("Name", exact=True).fill("New action identity")
    dialog.locator('input[type="password"]').fill("fixture-connector-secret")
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog).to_have_count(0)
    created_id = next(identifier for identifier, record in ui.identities.items() if record["name"] == "New action identity")
    ui.open(f"/workspace/actions/{ACTION_ID}")
    editor_section(ui.page, "Authentication")
    picker = ui.page.get_by_label("Reusable identity", exact=True)
    expect(picker.locator(f'option[value="{created_id}"]')).to_contain_text("New action identity")
    picker.select_option(created_id)
    response = save_resource(ui, "action", identifier=ACTION_ID)
    assert response.status == 200
    assert ui.actions[ACTION_ID]["identity_id"] == created_id
    action_write = [entry for entry in ui.writes if entry.path == f"/api/user/plugins/{ACTION_ID}"][-1]
    assert "fixture-connector-secret" not in str(action_write.body)
    ui.assert_no_secret_storage("fixture-connector-secret")


def test_read_failure_after_committed_create_does_not_restore_draft(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    expect(row(ui)).to_be_visible()
    dialog = open_new(ui)
    dialog.get_by_label("Name", exact=True).fill("Committed identity")
    dialog.locator('input[type="password"]').fill("fixture-committed-secret")
    ui.reject_next("GET", LIST_PATH, status=503, error="Refresh temporarily unavailable.")
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("alert").filter(has_text="Refresh temporarily unavailable.")).to_be_visible()
    assert ui.created_identity_count == 1
    ui.page.get_by_role("button", name="Retry identities", exact=True).click()
    expect(row(ui, "Committed identity")).to_be_visible()


def test_created_identity_can_bind_to_a_file_source_without_copying_secrets(personal_identities_ui):
    ui = personal_identities_ui
    open_identities(ui)
    dialog = open_new(ui)
    dialog.get_by_label("Name", exact=True).fill("New source identity")
    dialog.get_by_role("checkbox", name=re.compile("^File Sync")).check()
    dialog.get_by_role("checkbox", name=re.compile("^Actions")).uncheck()
    dialog.get_by_label("Authentication method").select_option("username_password")
    dialog.get_by_label("Username", exact=True).fill("svc-source")
    dialog.locator('input[type="password"]').fill("fixture-source-identity-secret")
    dialog.get_by_role("button", name="Create identity", exact=True).click()
    expect(dialog).to_have_count(0)
    created_id = next(identifier for identifier, record in ui.identities.items() if record["name"] == "New source identity")
    open_sources(ui)
    dialog = edit_source(ui)
    dialog.get_by_label("Use a saved workspace identity", exact=True).check()
    picker = dialog.get_by_label("Identity", exact=True)
    expect(picker.locator(f'option[value="{created_id}"]')).to_have_text("New source identity")
    picker.select_option(created_id)
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    source_write = [entry for entry in ui.writes if entry.path == f"{SOURCE_BASE}/{SOURCE_ID}"][-1]
    assert source_write.body["identity_id"] == created_id and "credentials" not in source_write.body
    assert "fixture-source-identity-secret" not in str(source_write.body)
    ui.assert_no_secret_storage("fixture-source-identity-secret")
