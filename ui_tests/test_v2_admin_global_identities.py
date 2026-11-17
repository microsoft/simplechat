#!/usr/bin/env python3
# test_v2_admin_global_identities.py
"""
Browser coverage for creating, editing and deleting Global Identities in V2 Admin Settings.
Version: 0.261.445
Implemented in: 0.261.445

Global Identities used to be a read-only list that sent an administrator to the classic admin page
to change one. The section is now the identities workbench the workspaces use, bound to the admin
routes that name the global scope. Exercise the built application with the real schema, and with only
HTTP stubbed (``ui_tests/fixtures/v2_admin_global_identities.py``, held to the real routes by
``functional_tests/test_global_identity_admin_routes.py``), at 1440px and at 390px with no sideways
scrolling:

- the list shows each identity's sign-in, authentication method and uses, beside the card's own help
  text and a New identity control, and leaves nothing to the classic page;
- a new identity is created with the write the classic editor sends, offering the methods the classic
  pane offers (never anonymous) and the capabilities File Sync and Actions;
- the server's own validation sentence is shown as written and the draft is kept;
- an edit keeps the stored secret (a blank secret rides as an empty string, never a placeholder) and
  sends no version marker, because these records carry none;
- a conflict a versioned server would report keeps the editor and the draft, and Refresh rebases onto
  the other writer's version; an identity deleted elsewhere cannot be saved again;
- a delete removes the row with no request body, and a delete refused because global actions still use
  the identity names them and removes nothing;
- a 403 is shown and changes nothing, on the first read and on a write;
- the keyboard opens the editor with focus in the Name field and Escape closes it, asking first when
  there is unsaved work.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

# Fixtures stay under ui_tests; the import also registers Azure connect_options.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_global_identities import (  # noqa: E402,F401
    API_KEY_ID,
    ETAG_CONFLICT_BODY,
    FILE_SHARE_ID,
    FORBIDDEN_BODY,
    GLOBAL_IDENTITIES_PATH,
    GRAPH_APP_ID,
    STORED_SECRET,
    TICKET_TOKEN_ID,
    GlobalIdentitiesFixture,
    connect_options,
    global_identities_ui,
)


pytestmark = pytest.mark.ui

WIDTHS = [pytest.param(1440, id="desktop"), pytest.param(390, id="mobile")]
REBASE_NOTICE = (
    "Someone else changed this while you were editing. Their changes are loaded; "
    "your edits are kept. Review, then save."
)
REBASE_DELETED_NOTICE = "This item was deleted. Copy anything you need, then close."


def card(ui):
    return ui.page.get_by_role("region", name="Global Identities", exact=True)


def row(ui, name):
    return card(ui).get_by_role("listitem").filter(has_text=name)


def dialog(ui):
    return ui.page.get_by_role("dialog")


def fits_the_screen(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "The page scrolls sideways"
    )


def item_path(identifier):
    return f"{GLOBAL_IDENTITIES_PATH}/{identifier}"


def last_write(ui, method, path):
    matches = [write for write in ui.identity_writes if write[0] == method and write[1] == path]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w[0], w[1]) for w in ui.identity_writes]}"
    return matches[-1][2]


def method_responses(page, method, path):
    return page.expect_response(
        lambda response: response.request.method == method and urlsplit(response.url).path == path
    )


def auth_method(ui):
    """The Authentication method select, the only combobox in the editor."""
    return dialog(ui).get_by_role("combobox")


def auth_options(ui):
    return auth_method(ui).locator("option").all_text_contents()


def open_editor(ui, name=None):
    """Open the New identity editor, or an existing identity's Edit."""
    if name is None:
        card(ui).get_by_role("button", name="New identity", exact=True).click()
        expect(dialog(ui).get_by_role("heading", name="New identity")).to_be_visible()
    else:
        row(ui, name).get_by_role("button", name=f"Edit {name}", exact=True).click()
        expect(dialog(ui).get_by_role("heading", name="Edit identity")).to_be_visible()


# ---------------------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("width", WIDTHS)
def test_the_section_lists_global_identities_beside_its_own_help_and_leaves_nothing_to_classic(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page
    help_text = ui.schema["workspace-identities-section"][0]["help"]

    expect(card(ui).get_by_text(help_text, exact=True)).to_be_visible()
    expect(card(ui).get_by_role("button", name="New identity", exact=True)).to_be_enabled()
    for name in ("Reporting API key", "File share account", "Ticket API token", "Graph app registration"):
        expect(row(ui, name)).to_be_visible()
        # The name is never squeezed out by the pills and actions beside it, at any width.
        title = row(ui, name).get_by_text(name, exact=True)
        expect(title).to_be_visible()
        assert title.evaluate("element => element.scrollWidth <= element.clientWidth"), f"{name} is truncated"

    # What a row says about an identity: who it signs in as, how, and what may use it.
    share = row(ui, "File share account")
    expect(share).to_contain_text("CORP\\svc-files")
    expect(share).to_contain_text("Username and password")
    expect(share).to_contain_text("File Sync")
    expect(share).not_to_contain_text("Actions")
    graph = row(ui, "Graph app registration")
    expect(graph).to_contain_text("11111111-2222-4333-8444-555555555555")
    expect(graph).to_contain_text("Client secret")
    expect(graph).to_contain_text("File Sync")
    expect(graph).to_contain_text("Actions")
    key = row(ui, "Reporting API key")
    expect(key).to_contain_text("Stored secret")
    expect(key).to_contain_text("API key")
    for secret in (STORED_SECRET, "Stored_In_KeyVault"):
        expect(card(ui).get_by_text(secret)).to_have_count(0)

    # The card is already titled, so the section adds no heading, no workspace wording, no hand-off.
    expect(card(ui).get_by_role("heading", name="Identities", exact=True)).to_have_count(0)
    expect(card(ui).get_by_text(re.compile("Used by |A workspace manager"))).to_have_count(0)
    expect(card(ui).get_by_role("link")).to_have_count(0)
    expect(card(ui).get_by_text(re.compile("classic", re.IGNORECASE))).to_have_count(0)

    assert [request for request in ui.identity_requests] == [("GET", GLOBAL_IDENTITIES_PATH)]
    assert not [url for url in ui.unexpected_requests if "identit" in url]
    fits_the_screen(page)


@pytest.mark.parametrize("width", WIDTHS)
def test_an_empty_list_invites_the_first_identity(global_identities_ui, width):
    ui = global_identities_ui
    ui.identities.clear()
    ui.open(width=width)

    expect(card(ui).get_by_text("No identities yet", exact=True)).to_be_visible()
    expect(card(ui).get_by_text(re.compile("reuse it across the deployment’s File Sync sources and actions"))).to_be_visible()
    expect(card(ui).get_by_role("button", name="New identity", exact=True)).to_be_visible()
    fits_the_screen(ui.page)


# ---------------------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("width", WIDTHS)
def test_a_new_identity_is_created_with_the_write_the_classic_editor_sends(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page
    open_editor(ui)
    editor = dialog(ui)

    expect(editor).to_contain_text("A reusable credential for the systems this deployment connects to.")
    expect(editor.get_by_role("checkbox", name=re.compile("^Actions"))).to_be_checked()
    expect(editor.get_by_role("checkbox", name=re.compile("^File Sync"))).not_to_be_checked()
    expect(editor.get_by_label("Name", exact=True)).to_be_focused()
    assert auth_options(ui) == [
        "API key", "Bearer token", "Client secret", "Connection string", "Username and password", "Managed identity",
    ]
    fits_the_screen(page)

    # A File Sync identity is offered the file-sync methods, and never anonymous.
    editor.get_by_role("checkbox", name=re.compile("^File Sync")).check()
    editor.get_by_role("checkbox", name=re.compile("^Actions")).uncheck()
    assert auth_options(ui) == ["Username and password", "Managed identity", "Client secret", "Connection string"]
    editor.get_by_role("checkbox", name=re.compile("^Actions")).check()
    assert "Anonymous" not in auth_options(ui)
    editor.get_by_role("checkbox", name=re.compile("^File Sync")).uncheck()
    # Leaving File Sync made Username and password the selected method; an API key is what this one is.
    auth_method(ui).select_option("api_key")

    editor.get_by_label("Name", exact=True).fill("CRM API key")
    editor.get_by_label("Description (optional)", exact=True).fill("Used by the CRM action.")
    editor.get_by_label("Secret", exact=True).fill("crm-secret-value")
    with method_responses(page, "POST", GLOBAL_IDENTITIES_PATH) as response:
        editor.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 201

    assert last_write(ui, "POST", GLOBAL_IDENTITIES_PATH) == {
        "name": "CRM API key",
        "description": "Used by the CRM action.",
        "provider": "action",
        "source_type": "action",
        "usage_contexts": ["action"],
        "supported_source_types": ["action"],
        "credentials": {
            "auth_type": "api_key", "username": "", "domain": "", "identity": "", "client_id": "",
            "secret": "crm-secret-value",
        },
    }
    expect(dialog(ui)).to_have_count(0)
    expect(page.get_by_text("Identity created", exact=True)).to_be_visible()
    expect(row(ui, "CRM API key")).to_be_visible()
    expect(row(ui, "CRM API key")).to_contain_text("Stored secret")
    assert len(ui.reads()) == 2, "The list is read again after a committed save."
    fits_the_screen(page)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_client_secret_identity_for_both_uses_carries_the_client_id(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    open_editor(ui)
    editor = dialog(ui)

    editor.get_by_role("checkbox", name=re.compile("^File Sync")).check()
    auth_method(ui).select_option("client_secret")
    editor.get_by_label("Name", exact=True).fill("OneDrive connector")
    editor.get_by_label("Client ID", exact=True).fill("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    editor.get_by_label("Client secret", exact=True).fill("connector-secret-value")
    with method_responses(ui.page, "POST", GLOBAL_IDENTITIES_PATH) as response:
        editor.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 201

    write = last_write(ui, "POST", GLOBAL_IDENTITIES_PATH)
    assert write["usage_contexts"] == ["action", "file_sync"]
    assert write["provider"] == "action"
    assert write["supported_source_types"][0] == "action" and "onedrive" in write["supported_source_types"]
    assert write["credentials"] == {
        "auth_type": "client_secret", "username": "", "domain": "",
        "identity": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "client_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "secret": "connector-secret-value",
    }
    row_text = row(ui, "OneDrive connector")
    expect(row_text).to_contain_text("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    expect(row_text).to_contain_text("Client secret")
    expect(row_text).to_contain_text("File Sync")
    expect(row_text).to_contain_text("Actions")


@pytest.mark.parametrize("width", WIDTHS)
def test_a_validation_message_is_shown_as_the_server_wrote_it_and_the_draft_is_kept(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page
    open_editor(ui)
    editor = dialog(ui)

    editor.get_by_role("checkbox", name=re.compile("^File Sync")).check()
    editor.get_by_role("checkbox", name=re.compile("^Actions")).uncheck()
    expect(auth_method(ui)).to_have_value("username_password")
    editor.get_by_label("Name", exact=True).fill("Share without a password")
    editor.get_by_label("Username", exact=True).fill("svc-share")
    with method_responses(page, "POST", GLOBAL_IDENTITIES_PATH) as response:
        editor.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 400

    expect(editor.get_by_role("alert")).to_have_text("Username/password identities require a password")
    expect(editor.get_by_label("Name", exact=True)).to_have_value("Share without a password")
    expect(editor.get_by_label("Username", exact=True)).to_have_value("svc-share")
    expect(row(ui, "Share without a password")).to_have_count(0)
    fits_the_screen(page)

    editor.get_by_label("Password", exact=True).fill("share-password-value")
    with method_responses(page, "POST", GLOBAL_IDENTITIES_PATH) as response:
        editor.get_by_role("button", name="Create identity", exact=True).click()
    assert response.value.status == 201
    expect(dialog(ui)).to_have_count(0)
    expect(row(ui, "Share without a password")).to_contain_text("svc-share")


# ---------------------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("width", WIDTHS)
def test_an_edit_keeps_the_stored_secret_and_sends_no_version_marker(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page
    open_editor(ui, "Reporting API key")
    editor = dialog(ui)

    expect(editor.get_by_label("Name", exact=True)).to_have_value("Reporting API key")
    secret = editor.get_by_label("Secret (stored)")
    expect(secret).to_have_value("")
    expect(secret).to_have_attribute("placeholder", "Stored value unchanged")
    expect(editor.get_by_text(re.compile("A secret is already stored. Leave this blank to keep it"))).to_be_visible()
    fits_the_screen(page)

    editor.get_by_label("Name", exact=True).fill("Reporting API key (rotated)")
    with method_responses(page, "PATCH", item_path(API_KEY_ID)) as response:
        editor.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok

    write = last_write(ui, "PATCH", item_path(API_KEY_ID))
    assert write["name"] == "Reporting API key (rotated)"
    assert write["credentials"]["auth_type"] == "api_key"
    assert write["credentials"]["secret"] == "", "A blank secret keeps the stored value; it never rides as a placeholder."
    assert "expected_etag" not in write
    assert ui.stored_secrets[API_KEY_ID] == STORED_SECRET
    assert ui.record(API_KEY_ID)["credentials"]["secret_stored"] is True
    expect(dialog(ui)).to_have_count(0)
    expect(page.get_by_text("Identity saved", exact=True)).to_be_visible()
    expect(row(ui, "Reporting API key (rotated)")).to_be_visible()


def test_an_edit_can_replace_a_secret_and_change_who_may_use_the_identity(global_identities_ui):
    ui = global_identities_ui
    ui.open()
    open_editor(ui, "File share account")
    editor = dialog(ui)

    expect(editor.get_by_label("Username", exact=True)).to_have_value("svc-files")
    expect(editor.get_by_label("Domain (optional)", exact=True)).to_have_value("CORP")
    expect(editor.get_by_label("Password (stored)")).to_have_value("")
    editor.get_by_label("Password (stored)").fill("rotated-share-password")
    editor.get_by_role("checkbox", name=re.compile("^Actions")).check()
    with method_responses(ui.page, "PATCH", item_path(FILE_SHARE_ID)) as response:
        editor.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok

    write = last_write(ui, "PATCH", item_path(FILE_SHARE_ID))
    assert write["usage_contexts"] == ["file_sync", "action"]
    assert write["credentials"]["username"] == "svc-files" and write["credentials"]["domain"] == "CORP"
    assert write["credentials"]["password"] == "rotated-share-password"
    assert ui.stored_secrets[FILE_SHARE_ID] == "rotated-share-password"
    expect(row(ui, "File share account")).to_contain_text("Actions")
    expect(ui.page.get_by_text("rotated-share-password")).to_have_count(0)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_conflict_keeps_the_editor_and_the_draft_and_refresh_rebases_onto_the_other_save(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page
    open_editor(ui, "Reporting API key")
    editor = dialog(ui)
    editor.get_by_label("Name", exact=True).fill("Draft in flight")

    # Another administrator saves first. The real routes do not version these records, so the
    # answer is the 409 a versioned server would give; the section reads it the same way.
    ui.touch(API_KEY_ID, description="Concurrent description.")
    ui.fail_next("PATCH", 409, ETAG_CONFLICT_BODY, path=item_path(API_KEY_ID))
    with method_responses(page, "PATCH", item_path(API_KEY_ID)) as response:
        editor.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409

    expect(editor.get_by_role("alert")).to_have_text("This workspace identity was modified. Reload and try again.")
    expect(editor.get_by_label("Name", exact=True)).to_have_value("Draft in flight")
    refresh = editor.get_by_role("button", name="Refresh", exact=True)
    expect(refresh).to_be_visible()
    fits_the_screen(page)

    with method_responses(page, "GET", GLOBAL_IDENTITIES_PATH):
        refresh.click()
    expect(editor.get_by_label("Description (optional)", exact=True)).to_have_value("Concurrent description.")
    expect(editor.get_by_label("Name", exact=True)).to_have_value("Draft in flight")
    expect(editor.get_by_text(REBASE_NOTICE, exact=True)).to_be_visible()

    with method_responses(page, "PATCH", item_path(API_KEY_ID)) as saved:
        editor.get_by_role("button", name="Save changes", exact=True).click()
    assert saved.value.ok
    stored = ui.record(API_KEY_ID)
    assert stored["name"] == "Draft in flight" and stored["description"] == "Concurrent description."
    expect(dialog(ui)).to_have_count(0)


def test_an_identity_deleted_elsewhere_cannot_be_saved_again(global_identities_ui):
    ui = global_identities_ui
    ui.open()
    page = ui.page
    open_editor(ui, "Reporting API key")
    editor = dialog(ui)
    editor.get_by_label("Name", exact=True).fill("Edited after it was deleted")

    ui.drop(API_KEY_ID)
    with method_responses(page, "PATCH", item_path(API_KEY_ID)) as response:
        editor.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 404

    expect(editor.get_by_role("alert")).to_have_text(REBASE_DELETED_NOTICE)
    expect(editor.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
    expect(editor.get_by_label("Name", exact=True)).to_have_value("Edited after it was deleted")
    assert len(ui.writes("PATCH")) == 1, "A deleted identity is never recreated by a second save."


# ---------------------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("width", WIDTHS)
def test_a_delete_asks_first_and_removes_the_row_with_no_request_body(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page

    row(ui, "Reporting API key").get_by_role("button", name="Delete Reporting API key", exact=True).click()
    assert not ui.writes("DELETE"), "Nothing is sent until the delete is confirmed."
    with method_responses(page, "DELETE", item_path(API_KEY_ID)) as response:
        row(ui, "Reporting API key").get_by_role("button", name="Delete", exact=True).click()
    assert response.value.ok

    assert last_write(ui, "DELETE", item_path(API_KEY_ID)) is None
    expect(row(ui, "Reporting API key")).to_have_count(0)
    expect(page.get_by_text("Identity deleted", exact=True)).to_be_visible()
    expect(row(ui, "File share account")).to_be_visible()
    assert not any(record["id"] == API_KEY_ID for record in ui.identities)
    fits_the_screen(page)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_delete_refused_because_actions_still_use_the_identity_names_them_and_removes_nothing(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page

    row(ui, "Ticket API token").get_by_role("button", name="Delete Ticket API token", exact=True).click()
    with method_responses(page, "DELETE", item_path(TICKET_TOKEN_ID)) as response:
        row(ui, "Ticket API token").get_by_role("button", name="Delete", exact=True).click()
    assert response.value.status == 409

    alert = card(ui).get_by_role("alert")
    expect(alert).to_contain_text("“Ticket API token” is still in use, so it was not deleted.")
    expect(alert.get_by_role("listitem")).to_have_text(["Ticket search (action)", "Roadmap lookup (action)"])
    expect(row(ui, "Ticket API token")).to_be_visible()
    expect(page.get_by_text("Identity deleted", exact=True)).to_have_count(0)
    assert any(record["id"] == TICKET_TOKEN_ID for record in ui.identities)
    fits_the_screen(page)

    # Once nothing uses it, the same delete goes through and the warning goes with it.
    ui.references.pop(TICKET_TOKEN_ID)
    row(ui, "Ticket API token").get_by_role("button", name="Delete Ticket API token", exact=True).click()
    with method_responses(page, "DELETE", item_path(TICKET_TOKEN_ID)) as response:
        row(ui, "Ticket API token").get_by_role("button", name="Delete", exact=True).click()
    assert response.value.ok
    expect(row(ui, "Ticket API token")).to_have_count(0)
    expect(card(ui).get_by_text("is still in use")).to_have_count(0)


# ---------------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("width", WIDTHS)
def test_a_403_on_the_first_read_is_shown_with_a_retry_and_never_the_empty_state(global_identities_ui, width):
    ui = global_identities_ui
    ui.reject_all(403, FORBIDDEN_BODY)
    ui.open(width=width)

    alert = card(ui).get_by_role("alert")
    expect(alert).to_contain_text("Forbidden")
    expect(card(ui).get_by_text("No identities yet", exact=True)).to_have_count(0)
    expect(card(ui).get_by_role("listitem")).to_have_count(0)
    fits_the_screen(ui.page)

    ui.allow_all()
    alert.get_by_role("button", name="Retry identities", exact=True).click()
    expect(row(ui, "Reporting API key")).to_be_visible()
    expect(alert).to_have_count(0)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_403_on_a_write_is_shown_in_the_editor_and_changes_nothing(global_identities_ui, width):
    ui = global_identities_ui
    ui.open(width=width)
    page = ui.page
    open_editor(ui, "Reporting API key")
    editor = dialog(ui)
    editor.get_by_label("Name", exact=True).fill("Not allowed")

    ui.reject_all(403, FORBIDDEN_BODY)
    with method_responses(page, "PATCH", item_path(API_KEY_ID)) as response:
        editor.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 403

    expect(editor.get_by_role("alert")).to_have_text("Forbidden")
    expect(editor.get_by_label("Name", exact=True)).to_have_value("Not allowed")
    assert ui.record(API_KEY_ID)["name"] == "Reporting API key"
    fits_the_screen(page)

    # The refusal is not a conflict: there is nothing to refresh, and the draft saves once it is allowed.
    expect(editor.get_by_role("button", name="Refresh", exact=True)).to_have_count(0)
    ui.allow_all()
    with method_responses(page, "PATCH", item_path(API_KEY_ID)) as response:
        editor.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    assert ui.record(API_KEY_ID)["name"] == "Not allowed"


def test_a_403_on_a_delete_is_shown_and_the_row_stays(global_identities_ui):
    ui = global_identities_ui
    ui.open()
    page = ui.page

    ui.reject_all(403, FORBIDDEN_BODY)
    row(ui, "File share account").get_by_role("button", name="Delete File share account", exact=True).click()
    with method_responses(page, "DELETE", item_path(FILE_SHARE_ID)) as response:
        row(ui, "File share account").get_by_role("button", name="Delete", exact=True).click()
    assert response.value.status == 403

    expect(card(ui).get_by_role("alert")).to_have_text("Forbidden")
    expect(row(ui, "File share account")).to_be_visible()
    assert any(record["id"] == FILE_SHARE_ID for record in ui.identities)
    expect(card(ui).get_by_text("is still in use")).to_have_count(0)


# ---------------------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------------------

def test_the_keyboard_opens_the_editor_with_focus_in_the_name_field_and_escape_asks_before_discarding(global_identities_ui):
    ui = global_identities_ui
    ui.open()
    page = ui.page

    new_identity = card(ui).get_by_role("button", name="New identity", exact=True)
    new_identity.focus()
    page.keyboard.press("Enter")
    editor = dialog(ui)
    expect(editor.get_by_label("Name", exact=True)).to_be_focused()

    # Nothing typed: Escape closes it and focus returns to the control that opened it.
    page.keyboard.press("Escape")
    expect(dialog(ui)).to_have_count(0)
    expect(new_identity).to_be_focused()

    page.keyboard.press("Enter")
    editor.get_by_label("Name", exact=True).fill("Half-written identity")
    page.keyboard.press("Escape")
    expect(editor.get_by_text("Discard your unsaved changes?")).to_be_visible()
    editor.get_by_role("button", name="Keep editing", exact=True).click()
    expect(editor.get_by_label("Name", exact=True)).to_have_value("Half-written identity")
    page.keyboard.press("Escape")
    editor.get_by_role("button", name="Discard", exact=True).click()
    expect(dialog(ui)).to_have_count(0)
    expect(row(ui, "Half-written identity")).to_have_count(0)
    assert not ui.writes(), "Nothing was sent for an identity that was discarded."
