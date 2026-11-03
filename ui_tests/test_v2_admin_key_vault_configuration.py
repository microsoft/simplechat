# test_v2_admin_key_vault_configuration.py
"""
Browser regression coverage for configuring Key Vault in V2 Admin Settings.
Version: 0.261.396
Implemented in: 0.261.396

Use the built SPA, production field schema and settings normalizer with the
shared local/Azure Playwright fixture. Connection tests are intercepted: no
Azure resource, secret, signed-in browser or live setting is changed.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

STORAGE_KEY = "enable_key_vault_secret_storage"
STORAGE_LABEL = "Store agent and action secrets in Key Vault"
VAULT_NAME = "v2-test-vault"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def vault_ui(page):
    fixture = AdminSettingsFixture(
        page, sections={"security": ("keyvault-section",)}, validate_updates=True,
    )
    yield fixture
    fixture.assert_clean()


def _region(page):
    return page.get_by_role("region", name="Key Vault", exact=True)


def _storage_switch(page):
    return _region(page).get_by_role("checkbox", name=re.compile(f"^{STORAGE_LABEL}"))


def _set_enabled(page, enabled):
    checkbox = _storage_switch(page)
    if checkbox.is_checked() != enabled:
        _region(page).get_by_text(STORAGE_LABEL, exact=True).click()
    expect(checkbox).to_be_checked(checked=enabled)


def _expand_connection(page):
    button = _region(page).get_by_role("button", name=re.compile("^Vault connection"))
    if button.get_attribute("aria-expanded") != "true":
        button.click()
    expect(button).to_have_attribute("aria-expanded", "true")


def _save(page):
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)


def _serve_connection_test(fixture, response, status=200):
    requests = []

    def respond(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=status, json=response)

    fixture.extra_routes[("POST", "/api/v2/admin/settings/test-connection")] = respond
    return requests


@pytest.mark.parametrize("stored", [False, True], ids=["baseline", "saved-disabled"])
def test_disabled_key_vault_keeps_its_switch_and_warning_reachable(vault_ui, stored):
    if not stored:
        for key in (STORAGE_KEY, "key_vault_name", "key_vault_identity"):
            vault_ui.settings.pop(key)
    vault_ui.open(ready_region="Key Vault")
    page = vault_ui.page

    expect(_storage_switch(page)).to_be_visible()
    expect(_storage_switch(page)).not_to_be_checked()
    expect(_region(page).get_by_text("effectively one-way", exact=False)).to_be_visible()
    expect(page.get_by_label("Key Vault Name", exact=True)).to_have_count(0)
    expect(page.get_by_label("Managed Identity Client ID", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Test Key Vault connection", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert vault_ui.patches == []


def test_enabled_unconfigured_key_vault_opens_its_inputs(vault_ui):
    vault_ui.settings[STORAGE_KEY] = True
    vault_ui.open(ready_region="Key Vault")
    page = vault_ui.page

    expect(_storage_switch(page)).to_be_visible()
    expect(_region(page).get_by_text("Needs configuration", exact=True)).to_be_visible()
    expect(page.get_by_label("Key Vault Name", exact=True)).to_be_visible()
    expect(page.get_by_label("Managed Identity Client ID", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Test Key Vault connection", exact=True)).to_be_visible()


@pytest.mark.parametrize("width,theme", [(1440, "light"), (390, "dark")])
@pytest.mark.parametrize("client_id", ["", CLIENT_ID], ids=["system-identity", "user-identity"])
def test_enabling_key_vault_reveals_tests_and_saves_the_draft(vault_ui, width, theme, client_id):
    requests = _serve_connection_test(
        vault_ui, {"success": True, "message": "Key Vault connection succeeded."},
    )
    vault_ui.open(width=width, theme=theme, ready_region="Key Vault")
    page = vault_ui.page

    _set_enabled(page, True)
    name = page.get_by_label("Key Vault Name", exact=True)
    identity = page.get_by_label("Managed Identity Client ID", exact=True)
    expect(name).to_be_visible()
    expect(identity).to_be_visible()
    expect(identity).to_have_value("")
    expect(_region(page).get_by_text("Leave blank", exact=False)).to_be_visible()

    name.fill(VAULT_NAME)
    if client_id:
        identity.fill(client_id)
    page.get_by_role("button", name="Test Key Vault connection", exact=True).click()
    expect(_region(page).get_by_role("status")).to_contain_text("Key Vault connection succeeded.")
    assert requests == [{"test_type": "key_vault", "vault_name": VAULT_NAME, "client_id": client_id}]
    assert vault_ui.settings[STORAGE_KEY] is False
    assert vault_ui.settings["key_vault_name"] == ""
    assert vault_ui.patches == []

    expected = {STORAGE_KEY: True, "key_vault_name": VAULT_NAME}
    if client_id:
        expected["key_vault_identity"] = client_id
    _save(page)
    assert vault_ui.patches == [expected]
    assert vault_ui.settings["key_vault_identity"] == client_id

    page.reload(wait_until="networkidle")
    expect(_storage_switch(page)).to_be_checked()
    _expand_connection(page)
    expect(name).to_have_value(VAULT_NAME)
    expect(identity).to_have_value(client_id)
    overflow_free = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert overflow_free
    if not client_id:
        vault_ui.capture(f"configured-{width}-{theme}", "v2_admin_key_vault")


def test_vault_name_search_finds_the_input_after_enabling(vault_ui):
    vault_ui.open(ready_region="Key Vault")
    page = vault_ui.page
    _set_enabled(page, True)

    page.get_by_role("searchbox", name="Search settings", exact=True).fill("Key Vault Name")
    expect(page.get_by_label("Key Vault Name", exact=True)).to_be_visible()
    expect(page.get_by_text("No settings match", exact=False)).to_have_count(0)
    page.get_by_role("searchbox", name="Search settings", exact=True).fill("")
    expect(_storage_switch(page)).to_be_checked()
    assert vault_ui.patches == []


def test_clearing_the_identity_selects_system_assigned_identity(vault_ui):
    vault_ui.settings.update({
        STORAGE_KEY: True, "key_vault_name": VAULT_NAME, "key_vault_identity": CLIENT_ID,
    })
    requests = _serve_connection_test(vault_ui, {"success": True})
    vault_ui.open(ready_region="Key Vault")
    page = vault_ui.page
    _expand_connection(page)

    page.get_by_label("Managed Identity Client ID", exact=True).fill("")
    page.get_by_role("button", name="Test Key Vault connection", exact=True).click()
    expect(_region(page).get_by_role("status")).to_contain_text("Connection succeeded.")
    assert requests == [{"test_type": "key_vault", "vault_name": VAULT_NAME, "client_id": ""}]
    _save(page)
    assert vault_ui.patches == [{"key_vault_identity": ""}]
    assert vault_ui.settings["key_vault_name"] == VAULT_NAME
    assert vault_ui.settings["key_vault_identity"] == ""


def test_failed_connection_and_save_keep_the_configuration_draft(vault_ui):
    requests = _serve_connection_test(vault_ui, {
        "success": False,
        "error": "Key Vault write permission is missing.",
        "guidance": ["Assign Key Vault Secrets Officer to the selected identity."],
    }, status=400)
    vault_ui.open(ready_region="Key Vault")
    page = vault_ui.page
    _set_enabled(page, True)
    page.get_by_label("Key Vault Name", exact=True).fill(VAULT_NAME)
    page.get_by_label("Managed Identity Client ID", exact=True).fill(CLIENT_ID)

    page.get_by_role("button", name="Test Key Vault connection", exact=True).click()
    result = _region(page).get_by_role("status")
    expect(result).to_contain_text("Key Vault write permission is missing.")
    expect(result).to_contain_text("Assign Key Vault Secrets Officer")
    assert requests[0]["vault_name"] == VAULT_NAME
    assert vault_ui.patches == []

    vault_ui.reject_next_save = True
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(_region(page).get_by_role("alert").first).to_contain_text("Fixture validation error.")
    expect(page.get_by_label("Key Vault Name", exact=True)).to_have_value(VAULT_NAME)
    expect(page.get_by_label("Managed Identity Client ID", exact=True)).to_have_value(CLIENT_ID)
    assert vault_ui.settings[STORAGE_KEY] is False
    _save(page)
    assert vault_ui.settings[STORAGE_KEY] is True
    assert vault_ui.settings["key_vault_name"] == VAULT_NAME
    # Chromium reports each deliberately rejected request as a resource error.
    resource_error = "Failed to load resource: the server responded with a status of 400 (Bad Request)"
    for _ in range(2):
        vault_ui.errors.remove(resource_error)


def test_disabling_hides_controls_without_clearing_the_saved_connection(vault_ui):
    vault_ui.settings.update({
        STORAGE_KEY: True, "key_vault_name": VAULT_NAME, "key_vault_identity": CLIENT_ID,
    })
    vault_ui.open(ready_region="Key Vault")
    page = vault_ui.page
    _set_enabled(page, False)

    expect(page.get_by_label("Key Vault Name", exact=True)).to_have_count(0)
    expect(page.get_by_label("Managed Identity Client ID", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Test Key Vault connection", exact=True)).to_have_count(0)
    expect(_region(page).get_by_text("effectively one-way", exact=False)).to_be_visible()
    _save(page)
    assert vault_ui.patches == [{STORAGE_KEY: False}]
    assert vault_ui.settings["key_vault_name"] == VAULT_NAME
    assert vault_ui.settings["key_vault_identity"] == CLIENT_ID

    page.reload(wait_until="networkidle")
    expect(_storage_switch(page)).to_be_visible()
    expect(_storage_switch(page)).not_to_be_checked()
    expect(page.get_by_label("Key Vault Name", exact=True)).to_have_count(0)
