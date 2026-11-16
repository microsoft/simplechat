# test_v2_personal_endpoints.py
"""
Native personal endpoint production-SPA workflows and real-route persistence.
Version: 0.261.315
Implemented in: 0.261.315

Exercise the shared connection editor with personal APIs, not an admin session.
The closed fixture uses Azure Playwright when configured, or the established
local browser fallback. No live Azure inference or deployment is claimed.
"""

import base64
import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.personal_endpoints import (
    BASE, ENDPOINT_ID, ENDPOINT_NAME, FOUNDRY_ID,
    connect_options, personal_endpoints_ui,  # noqa: F401
)
from test_support.group_endpoint_harness import foundry_endpoint


pytestmark = pytest.mark.ui
LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]


def open_endpoints(ui, **options):
    ui.open("/workspace/endpoints", **options)
    expect(ui.page.get_by_role("heading", name="Endpoints", exact=True)).to_be_visible()


def row(ui, name=ENDPOINT_NAME):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def edit(ui, name=ENDPOINT_NAME):
    row(ui, name).get_by_role("button", name=f"Edit {name}", exact=True).click()
    dialog = ui.page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    return dialog


def save(ui, dialog, name=ENDPOINT_NAME):
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(row(ui, name)).to_be_visible()


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_personal_editor_layout_and_keyboard(personal_endpoints_ui, theme, width, height):
    ui = personal_endpoints_ui
    open_endpoints(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("link", name=re.compile("classic", re.I))).to_have_count(0)
    expect(ui.page.get_by_text("Images and embeddings remain available when chat uses its classic endpoint.", exact=False)).to_have_count(0)
    button = row(ui).get_by_role("button", name=f"Edit {ENDPOINT_NAME}", exact=True)
    button.focus()
    button.press("Enter")
    dialog = ui.page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("button", name="Test connection", exact=True)).to_have_count(0)
    dialog.locator("summary").filter(has_text="Advanced endpoint capacity").click()
    dialog.locator("summary").filter(has_text="Advanced model capacity").click()
    dialog.locator("summary").filter(has_text="Model icon").click()
    ui.assert_no_overflow()
    assert dialog.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(button).to_be_focused()


@pytest.mark.parametrize("provider,auth_type,api_type", [
    ("aoai", "managed_identity", None),
    ("aoai", "service_principal", None),
    ("aoai", "api_key", None),
    ("aifoundry", "service_principal", None),
    ("new_foundry", "api_key", None),
    ("openai_compatible", "api_key", None),
    ("custom", "api_key", "openai"),
    ("custom", "bearer", "anthropic"),
    ("custom", "oauth2_client_credentials", "gemini"),
    ("custom", "api_key", "azure_openai"),
])
def test_create_and_reopen_provider_authentication(personal_endpoints_ui, provider, auth_type, api_type):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    ui.page.get_by_role("button", name="Add connection", exact=True).click()
    dialog = ui.page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Native endpoint")
    dialog.get_by_label("Provider", exact=True).select_option(provider)
    if api_type:
        dialog.get_by_label("Custom API type", exact=True).select_option(api_type)
    url = "https://personal.openai.azure.com"
    if provider in {"aifoundry", "new_foundry"}:
        url = "https://personal.services.ai.azure.com/api/projects/research"
    elif provider in {"custom", "openai_compatible"}:
        url = "https://gateway.example.com/v1"
    dialog.locator("#connection-endpoint").fill(url)
    dialog.get_by_label("Method", exact=True).select_option(auth_type)
    if auth_type == "api_key":
        dialog.get_by_label("API key", exact=True).fill("new-only-test-key")
    elif auth_type == "service_principal":
        dialog.get_by_label("Tenant id", exact=True).fill("tenant-test")
        dialog.get_by_label("Client id", exact=True).fill("client-test")
        dialog.get_by_label("Client secret", exact=True).fill("new-only-test-secret")
    elif auth_type == "bearer":
        dialog.locator("#custom-auth-bearer_token").fill("new-only-test-bearer")
    elif auth_type == "oauth2_client_credentials":
        dialog.get_by_label("OAuth2 token URL", exact=True).fill("https://gateway.example.com/oauth/token")
        dialog.get_by_label("OAuth2 client ID", exact=True).fill("client-test")
        dialog.get_by_label("OAuth2 client secret", exact=True).fill("new-only-test-secret")
    if api_type == "azure_openai":
        dialog.get_by_label("API version", exact=True).fill("2024-10-21")
    dialog.get_by_role("button", name="Add manually", exact=True).click()
    uses_model_name = provider == "custom" and api_type != "azure_openai"
    dialog.get_by_label("Model name" if uses_model_name else "Deployment name", exact=True).fill("native-model")
    dialog.get_by_role("button", name="Create connection", exact=True).click()
    expect(dialog).to_have_count(0)
    created = next(entry for entry in ui.writes if entry.path == BASE and entry.method == "POST")
    assert created.body["provider"] == provider and created.body["auth"]["type"] == auth_type
    assert "endpoints" not in created.body and "expected_revision" not in created.body
    dialog = edit(ui, "Native endpoint")
    expect(dialog.get_by_label("Provider", exact=True)).to_have_value(provider)
    expect(dialog.get_by_label("Method", exact=True)).to_have_value(auth_type)
    for field in dialog.locator('input[type="password"]').all():
        expect(field).to_have_value("")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    ui.assert_no_secret_storage("new-only-test-key", "new-only-test-secret", "new-only-test-bearer")


def test_metadata_round_trip_and_explicit_clears(personal_endpoints_ui):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    dialog = edit(ui)
    expect(dialog.get_by_label("API key", exact=True)).to_have_value("")
    dialog.locator("summary").filter(has_text="Advanced endpoint capacity").click()
    dialog.get_by_label("Context window (tokens)", exact=True).first.fill("256000")
    dialog.locator("summary").filter(has_text="Advanced model capacity").click()
    dialog.get_by_label("Context window (tokens)", exact=True).last.fill("")
    dialog.get_by_label("Catalog model ID", exact=True).fill("")
    dialog.get_by_label("Model description", exact=True).fill("<img src=x onerror=bad()> Plain description")
    dialog.get_by_label("Response length", exact=True).fill("1024")
    save(ui, dialog)
    stored = ui.stored()
    assert stored["contextWindow"] == 256000
    assert stored["models"][0]["contextWindow"] is None and stored["models"][0]["catalogModelId"] is None
    assert stored["models"][0]["responseLength"] == 1024 and stored["models"][0]["metadata"] == {"keep": False}
    assert stored["models"][0]["icon"] == {"kind": "bootstrap", "value": "bi-stars"}
    assert ui.environment.vault.writes == []
    dialog = edit(ui)
    expect(dialog.get_by_label("Model description", exact=True)).to_have_value("<img src=x onerror=bad()> Plain description")
    expect(dialog.locator('img[src="x"]')).to_have_count(0)
    dialog.get_by_label("Response length", exact=True).fill("")
    dialog.get_by_label("API key", exact=True).fill("replacement-only-test-key")
    save(ui, dialog)
    assert "responseLength" not in ui.stored()["models"][0]
    secret_name = ui.stored()["auth"]["api_key"]
    assert ui.environment.vault.secrets[secret_name] == "replacement-only-test-key"
    ui.assert_no_secret_storage("replacement-only-test-key")


def test_invalid_capacity_is_visible_and_never_written(personal_endpoints_ui):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    dialog = edit(ui)
    dialog.locator("summary").filter(has_text="Advanced endpoint capacity").click()
    field = dialog.get_by_label("Context window (tokens)", exact=True).first
    field.fill("1e3")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(field).to_have_value("1e3")
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(dialog.get_by_role("alert").filter(has_text="positive whole number")).to_be_visible()
    assert not ui.writes
    field.fill("9007199254740991")
    save(ui, dialog)
    assert ui.stored()["contextWindow"] == 9007199254740991


def test_saved_binding_gates_edits_discovery_and_disabled_models(personal_endpoints_ui):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    dialog = edit(ui)
    test = dialog.get_by_role("button", name="Test chat", exact=True)
    expect(test).to_be_enabled()
    with ui.page.expect_response(lambda response: response.url.endswith("/api/user/models/test-model")) as tested:
        test.click()
    assert tested.value.status == 200, tested.value.json()
    expect(ui.page.get_by_text("existing-chat answered a chat request. Image inference was not tested.", exact=True)).to_be_visible()
    assert len(ui.environment.chat_clients) == 1
    dialog.get_by_label("Endpoint URL", exact=True).fill("https://changed.openai.azure.com")
    expect(test).to_be_disabled()
    expect(dialog.get_by_role("status").filter(has_text="Save changes before")).to_be_visible()
    save(ui, dialog)
    dialog = edit(ui)
    dialog.get_by_label("Enable existing-chat", exact=True).uncheck()
    expect(dialog.get_by_role("button", name="Test chat", exact=True)).to_have_count(0)
    save(ui, dialog)
    dialog = edit(ui)
    expect(dialog.get_by_role("button", name="Test chat", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    foundry_name = ui.stored(FOUNDRY_ID)["name"]
    dialog = edit(ui, foundry_name)
    discover = dialog.get_by_role("button", name="Discover models", exact=True)
    expect(discover).to_be_enabled()
    dialog.get_by_label("Client secret", exact=True).fill("rotation-only-test-secret")
    expect(discover).to_be_disabled()
    dialog.get_by_label("Client secret", exact=True).fill("")
    # A saved model list change, even a display name, must not test the old binding.
    dialog.get_by_label("Display name", exact=True).fill("Updated model")
    expect(discover).to_be_disabled()
    dialog.get_by_role("button", name="Cancel", exact=True).click()


def test_discovery_merges_without_erasing_advanced_models(personal_endpoints_ui):
    ui = personal_endpoints_ui
    endpoint = ui.stored()
    foundry = foundry_endpoint(ENDPOINT_ID)
    endpoint.update({key: foundry[key] for key in ("provider", "connection", "auth", "management")})
    ui.environment.seed_personal_endpoints("workspace-editor-user", [endpoint])
    open_endpoints(ui)
    dialog = edit(ui)
    with ui.page.expect_response(lambda response: response.url.endswith("/api/user/models/fetch")) as discovered:
        dialog.get_by_role("button", name="Discover models", exact=True).click()
    assert discovered.value.status == 200, discovered.value.json()
    expect(dialog.get_by_label("Deployment name", exact=True)).to_have_count(2)
    expect(dialog.get_by_role("button", name="Test chat", exact=True)).to_be_disabled()
    save(ui, dialog)
    assert ui.stored()["models"][0]["responseLength"] == 512
    assert ui.stored()["models"][1]["deploymentName"] == "gpt-4o"
    assert ui.stored()["models"][1]["enabled"] is False


def test_model_icons_local_catalog_upload_errors_and_reset(personal_endpoints_ui):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    dialog = edit(ui)
    dialog.locator("summary").filter(has_text="Model icon").click()
    dialog.get_by_role("button", name="Load all local icons", exact=True).click()
    expect(dialog.get_by_role("button", name="Load all local icons", exact=True)).to_be_enabled()
    dialog.get_by_label("Search Bootstrap icons", exact=True).fill("robot")
    dialog.get_by_label("Bootstrap icon", exact=True).select_option("bi-robot")
    upload = dialog.get_by_label("Upload model icon", exact=True)
    upload.set_input_files({"name": "invalid.svg", "mimeType": "image/svg+xml", "buffer": b"<svg/>"})
    expect(dialog.get_by_role("alert").filter(has_text="Choose a PNG or JPEG")).to_be_visible()
    upload.set_input_files({"name": "corrupt.png", "mimeType": "image/png", "buffer": b"corrupt"})
    expect(dialog.get_by_role("alert")).to_be_visible()
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7ioAAAAASUVORK5CYII=")
    upload.set_input_files({"name": "icon.png", "mimeType": "image/png", "buffer": png})
    expect(dialog.get_by_role("img", name="Model icon preview", exact=True)).to_be_visible()
    assert dialog.get_by_role("img", name="Model icon preview", exact=True).evaluate(
        "image => image.naturalWidth <= 128 && image.naturalHeight <= 128")
    save(ui, dialog)
    assert ui.stored()["models"][0]["icon"]["value"].startswith("data:image/png;base64,")
    dialog = edit(ui)
    dialog.locator("summary").filter(has_text="Model icon").click()
    dialog.get_by_role("button", name="Use default icon", exact=True).click()
    save(ui, dialog)
    assert not ui.stored()["models"][0]["icon"]


def test_toggle_delete_and_cancel_preserve_other_endpoints(personal_endpoints_ui):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    dialog = edit(ui)
    dialog.get_by_label("Name", exact=True).fill("Cancelled draft")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert not ui.writes
    row(ui).get_by_role("button", name=f"Disable {ENDPOINT_NAME}", exact=True).click()
    expect(row(ui).get_by_role("button", name=f"Enable {ENDPOINT_NAME}", exact=True)).to_be_visible()
    assert ui.writes[-1].body == {"enabled": False}
    assert ui.stored()["models"][0]["responseLength"] == 512
    row(ui).get_by_role("button", name=f"Delete {ENDPOINT_NAME}", exact=True).click()
    dialog = ui.page.get_by_role("dialog")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert ui.stored() is not None
    row(ui).get_by_role("button", name=f"Delete {ENDPOINT_NAME}", exact=True).click()
    ui.page.get_by_role("dialog").get_by_role("button", name="Delete", exact=True).click()
    expect(row(ui)).to_have_count(0)
    assert ui.stored() is None and ui.stored(FOUNDRY_ID) is not None
    assert ui.writes[-1].method == "DELETE" and ui.writes[-1].body is None


@pytest.mark.parametrize("malformed", [False, True])
def test_failed_list_is_not_an_empty_state(personal_endpoints_ui, malformed):
    ui = personal_endpoints_ui
    if malformed:
        ui.malformed_list = True
    else:
        ui.reject_next("GET", BASE, error="Endpoints temporarily unavailable.")
    ui.open("/workspace/endpoints")
    expect(ui.page.get_by_role("alert")).to_be_visible()
    expect(ui.page.get_by_text(re.compile("^No connections yet"))).to_have_count(0)
    ui.malformed_list = False
    ui.page.get_by_role("button", name="Retry connections", exact=True).click()
    expect(row(ui)).to_be_visible()


def test_failed_save_and_chat_keep_the_draft(personal_endpoints_ui):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    dialog = edit(ui)
    ui.reject_next("POST", "/api/user/models/test-model", error="Provider did not respond.")
    dialog.get_by_role("button", name="Test chat", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="Provider did not respond.")).to_be_visible()
    dialog.get_by_label("Name", exact=True).fill("Retry personal endpoint")
    ui.reject_next("PATCH", f"{BASE}/{ENDPOINT_ID}", error="Endpoint could not be saved.")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="Endpoint could not be saved.")).to_be_visible()
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Retry personal endpoint")
    save(ui, dialog, "Retry personal endpoint")


def test_denied_section_never_loads_endpoints(personal_endpoints_ui):
    ui = personal_endpoints_ui
    ui.disabled_sections["endpoints"] = "Personal endpoints are unavailable under this policy."
    ui.open("/workspace/endpoints")
    expect(ui.page.get_by_text("Personal endpoints are unavailable under this policy.", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Add connection", exact=True)).to_have_count(0)
    assert not [entry for entry in ui.requests if entry.path == BASE]


def test_new_draft_discovery_failure_retry_and_test(personal_endpoints_ui):
    ui = personal_endpoints_ui
    open_endpoints(ui)
    ui.page.get_by_role("button", name="Add connection", exact=True).click()
    dialog = ui.page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Unsaved Foundry")
    dialog.get_by_label("Provider", exact=True).select_option("aifoundry")
    dialog.get_by_label("Project endpoint", exact=True).fill("https://personal.services.ai.azure.com/api/projects/research")
    dialog.get_by_label("Method", exact=True).select_option("service_principal")
    dialog.get_by_label("Tenant id", exact=True).fill("tenant-test")
    dialog.get_by_label("Client id", exact=True).fill("client-test")
    dialog.get_by_label("Client secret", exact=True).fill("transient-only-test-secret")
    ui.reject_next("POST", "/api/user/models/fetch", error="Discovery is temporarily unavailable.")
    dialog.get_by_role("button", name="Discover models", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="Discovery is temporarily unavailable.")).to_be_visible()
    dialog.get_by_role("button", name="Discover models", exact=True).click()
    expect(dialog.get_by_label("Deployment name", exact=True)).to_have_value("gpt-4o")
    dialog.get_by_label("Enable gpt-4o", exact=True).check()
    with ui.page.expect_response(lambda response: response.url.endswith("/api/user/models/test-model")) as tested:
        dialog.get_by_role("button", name="Test chat", exact=True).click()
    assert tested.value.status == 200, tested.value.json()
    for entry in ui.writes:
        assert "id" not in entry.body and "endpoint_id" not in entry.body
    assert len(ui.environment.user_settings["workspace-editor-user"]["settings"]["personal_model_endpoints"]) == 2
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    ui.assert_no_secret_storage("transient-only-test-secret")
