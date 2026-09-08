# test_admin_shared_ai_connections_classic.py
"""
Classic shared connection manager, image selection, recovery and saved-test workflows.
Version: 0.261.102
Implemented in: 0.261.102
"""

import copy
import json
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from ai_connections_admin import image_import_error_notice, reference
from classic_ai_connections_admin import ClassicAIConnectionsFixture
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.fixture
def classic_ui(page):
    fixture = ClassicAIConnectionsFixture(page)
    yield fixture
    fixture.assert_clean()


def test_classic_registry_and_image_default_work_with_chat_mode_off(classic_ui):
    classic_ui.settings["enable_multi_model_endpoints"] = False
    classic_ui.open()
    page = classic_ui.page
    expect(page.locator("#model-endpoints-tbody tr")).to_have_count(3)
    expect(page.locator("#default-model-selection-wrapper")).not_to_be_visible()
    expect(page.locator("#legacy-image-recovery")).not_to_be_visible()
    expect(page.locator("#legacy-image-settings")).to_have_js_property("disabled", True)
    expect(page.locator("#image-generation-default-model optgroup")).to_have_count(3)
    page.get_by_label("Default image model", exact=True).select_option("0")
    expect(page.get_by_label("Default image model", exact=True)).to_be_enabled()
    assert classic_ui.selections["image_generation"] == reference("team", "same:model", "aoai")
    assert classic_ui.patches == []


def test_classic_failed_default_save_rolls_back_and_image_test_uses_saved_reference(classic_ui):
    classic_ui.open()
    page = classic_ui.page
    picker = page.get_by_label("Default image model", exact=True)
    classic_ui.reject_selection = True
    picker.select_option("2")
    expect(page.locator("#image-generation-model-error")).to_have_text("The image default could not be saved.")
    expect(picker).to_have_value("1")
    page.get_by_role("button", name="Test image generation", exact=True).click()
    expect(page.locator("#test_image_result")).to_have_text("The saved image model generated an image successfully.")
    assert classic_ui.image_tests == [{"test_type": "image", "selection": reference("studio", "same:model", "aoai")}]
    picker.select_option("")
    expect(picker).to_be_enabled()
    assert classic_ui.selections["image_generation"] == reference()
    expect(page.get_by_role("button", name="Test image generation", exact=True)).to_be_disabled()


def test_classic_model_policy_remains_a_form_draft_and_unsaved_images_cannot_test(classic_ui):
    classic_ui.open()
    page = classic_ui.page
    expect(page.locator("#default-model-selection option")).to_have_count(2)
    row = page.locator("#model-endpoints-tbody tr").filter(has_text="Imported Studio")
    row.get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Use for chat", exact=True)).not_to_be_checked()
    dialog.get_by_label("Use for chat", exact=True).check()
    dialog.get_by_role("button", name="Test image generation", exact=True).click()
    expect(page.locator("#fixture-toasts")).to_contain_text("Save the connection first.")
    assert classic_ui.image_tests == []
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    stored = json.loads(page.locator("#model_endpoints_json").input_value())
    imported = next(item for item in stored if item["id"] == "studio")
    assert set(imported["models"][0]["enabled_capabilities"]) == {"chat", "image_generation"}
    assert imported["connection"]["operation_settings"] == classic_ui.endpoints[1]["connection"]["operation_settings"]
    expect(page.locator("#default-model-selection option")).to_have_count(3)
    expect(page.locator("#image-generation-model-notice")).to_contain_text("Save the connection first")
    assert classic_ui.connection_writes == []


def test_classic_failed_import_shows_recovery_without_executing_notice_markup(classic_ui):
    classic_ui.migration = image_import_error_notice()
    classic_ui.migration["message"] += ' <img src=x onerror="window.untrustedExecuted=true">'
    classic_ui.open()
    page = classic_ui.page
    expect(page.locator("#legacy-image-recovery")).to_be_visible()
    expect(page.locator("#legacy-image-settings")).to_have_js_property("disabled", False)
    expect(page.locator("#image-generation-migration-notice")).to_contain_text("Existing image settings remain active.")
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert page.evaluate("window.untrustedExecuted") is None
    assert classic_ui.selection_writes == []
    page.reload(wait_until="networkidle")
    expect(page.locator("#legacy-image-recovery")).to_be_visible()
    expect(page.locator("#legacy-image-settings")).to_have_js_property("disabled", False)
    expect(page.locator("#azure_openai_image_gen_endpoint")).to_be_enabled()


def test_classic_late_metadata_lookup_does_not_replace_publication_edits(classic_ui):
    pending = []
    classic_ui.page.route("**/api/models/vision-capability", lambda route: pending.append(route))
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Imported Studio").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    dialog.get_by_label("Use for chat", exact=True).check()
    assert pending
    pending[0].fulfill(json={"models": {"same-deployment": {"supports_vision": True, "source": "catalog"}}})
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_checked()
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    stored = json.loads(page.locator("#model_endpoints_json").input_value())
    assert "chat" in stored[1]["models"][0]["enabled_capabilities"]


@pytest.mark.parametrize("selection", ["0", ""])
def test_classic_shared_save_retires_failed_import_recovery_even_after_reload(classic_ui, selection):
    classic_ui.migration = image_import_error_notice()
    classic_ui.open()
    page = classic_ui.page
    expect(page.locator("#legacy-image-recovery")).to_be_visible()
    picker = page.get_by_label("Default image model", exact=True)
    picker.select_option(selection)
    expect(picker).to_be_enabled()
    expect(page.locator("#legacy-image-recovery")).not_to_be_visible()
    expect(page.locator("#legacy-image-settings")).to_have_js_property("disabled", True)
    expect(page.locator("#image-generation-migration-notice")).to_contain_text("Image configuration now uses AI Connections")
    assert classic_ui.settings["image_generation_model_selection"] == classic_ui.selections["image_generation"]
    assert classic_ui.patches == []

    page.reload(wait_until="networkidle")
    expect(page.locator("#legacy-image-recovery")).not_to_be_visible()
    previous = page.locator("#image_gen_model_json").input_value()
    page.evaluate("window.selectImageModel('retired-deployment', 'gpt-image-1')")
    expect(page.locator("#image-generation-model-error")).to_contain_text("Legacy image configuration is not editable.")
    assert page.locator("#image_gen_model_json").input_value() == previous


@pytest.mark.parametrize("status", ["pending", "not_started"])
def test_classic_recovery_editing_is_limited_to_failed_imports(classic_ui, status):
    classic_ui.migration = {"status": status, "message": "Image import is not ready yet."}
    classic_ui.open()
    expect(classic_ui.page.locator("#legacy-image-recovery")).not_to_be_visible()
    expect(classic_ui.page.locator("#legacy-image-settings")).to_have_js_property("disabled", True)


def test_classic_recovery_accepts_the_legacy_failed_status(classic_ui):
    classic_ui.migration = {**image_import_error_notice(), "status": "failed"}
    classic_ui.open()
    expect(classic_ui.page.locator("#legacy-image-recovery")).to_be_visible()
    expect(classic_ui.page.locator("#legacy-image-settings")).to_have_js_property("disabled", False)


def test_classic_manual_alias_keeps_the_underlying_model_without_an_api_picker(classic_ui):
    classic_ui.open()
    page = classic_ui.page
    page.get_by_role("button", name="Add Connection", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    dialog.get_by_label("Endpoint Name", exact=True).fill("Manual Image Alias")
    page.locator("#model-endpoint-endpoint").fill("https://manual.example.test")
    page.locator("#model-endpoint-auth-type").select_option("api_key")
    page.locator("#model-endpoint-api-key").fill("fixture-only-not-a-service-key")
    page.locator("#model-endpoint-add-model-btn").click()
    dialog.locator("input[data-deployment-name-for]").fill("opaque-image-alias")
    dialog.get_by_label("Underlying Model Name (optional)", exact=True).fill("gpt-image-1")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    stored = json.loads(page.locator("#model_endpoints_json").input_value())
    model = stored[-1]["models"][0]
    assert model["deploymentName"] == "opaque-image-alias"
    assert model["modelName"] == "gpt-image-1"
    assert "image_generation_api" not in model
    assert "supportsChat" not in model and "supportsImageGeneration" not in model
    assert classic_ui.image_tests == [] and classic_ui.connection_writes == []


@pytest.mark.parametrize("auth_type", ["api_key", "service_principal"])
def test_classic_duplicate_editor_preserves_image_profiles_and_secret_copy_policy(classic_ui, auth_type):
    source = classic_ui.endpoints[1]
    source["connection"] = {
        "endpoint": "https://gateway.example.test/team/image-routing",
        "openai_api_version": "2024-05-01-preview",
        "operation_settings": {
            "image_generation": {
                "api_version": "2025-04-01-preview",
                "is_apim": True,
                "auth_header": "api-key",
            },
        },
    }
    source["has_api_key"] = auth_type == "api_key"
    source["has_client_secret"] = auth_type == "service_principal"
    source["auth"] = (
        {"type": "api_key", "api_key": "source-fixture-key"}
        if auth_type == "api_key"
        else {"type": "service_principal", "tenant_id": "test-tenant", "client_id": "test-client"}
    )
    original = copy.deepcopy(source)
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Imported Studio").get_by_role("button", name="Duplicate", exact=True).click()
    if auth_type == "api_key":
        expect(page.locator("#endpoint-duplicate-key-confirm-modal")).to_contain_text("will not include the API key")
        page.locator("#endpoint-duplicate-key-confirm-btn").click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog).to_be_visible()
    secret = page.locator("#model-endpoint-api-key" if auth_type == "api_key" else "#model-endpoint-client-secret")
    expect(secret).to_have_value("")
    if auth_type == "api_key":
        expect(secret).to_have_attribute("placeholder", "")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).to_be_visible()
    expect(page.locator("#fixture-toasts")).to_contain_text(
        "API key is required" if auth_type == "api_key" else "Client Secret are required"
    )
    assert len(json.loads(page.locator("#model_endpoints_json").input_value())) == 3

    secret.fill("replacement-fixture-credential")
    dialog.get_by_label("Endpoint Name", exact=True).fill("Reviewed gateway copy")
    page.locator("#model-endpoint-openai-api-version").select_option("2024-10-01-preview")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    stored = json.loads(page.locator("#model_endpoints_json").input_value())
    duplicate = next(item for item in stored if item["name"] == "Reviewed gateway copy")
    assert duplicate["id"] != original["id"] and duplicate["enabled"] is False
    assert duplicate["models"][0]["id"] != original["models"][0]["id"]
    assert duplicate["connection"].get("operation_settings") == original["connection"]["operation_settings"]
    assert duplicate["connection"]["endpoint"] == original["connection"]["endpoint"]
    assert duplicate["connection"]["openai_api_version"] == "2024-10-01-preview"
    assert duplicate["auth"]["api_key" if auth_type == "api_key" else "client_secret"] == "replacement-fixture-credential"
    assert next(item for item in stored if item["id"] == original["id"]) == original
    assert classic_ui.connection_writes == [] and classic_ui.image_tests == []
