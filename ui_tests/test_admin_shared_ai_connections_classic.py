# test_admin_shared_ai_connections_classic.py
"""
Classic shared connection manager, independent defaults, recovery and operation tests.
Version: 0.261.108
Implemented in: 0.261.105; embeddings added in 0.261.106
"""

import copy
import json
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from ai_connections_admin import connection, embedding_import_error_notice, embedding_model, image_import_error_notice, reference
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
    expect(page.locator("#model-endpoints-tbody tr")).to_have_count(4)
    vector_row = page.locator("#model-endpoints-tbody tr").filter(has=page.get_by_text("Vector Resource", exact=True))
    expect(vector_row.get_by_text("1 embeddings", exact=True)).to_be_visible()
    expect(vector_row.get_by_text("0 chat", exact=True)).to_be_visible()
    expect(page.locator("#default-model-selection-wrapper")).not_to_be_visible()
    expect(page.locator("#legacy-image-recovery")).not_to_be_visible()
    expect(page.locator("#legacy-image-settings")).to_have_js_property("disabled", True)
    expect(page.locator("#image-generation-default-model optgroup")).to_have_count(3)
    page.get_by_label("Default image model", exact=True).select_option("0")
    expect(page.get_by_label("Default image model", exact=True)).to_be_enabled()
    assert classic_ui.selections["image_generation"] == reference("team", "same:model", "custom")
    expect(page.get_by_label("Default embedding model", exact=True)).to_be_enabled()
    expect(page.locator("#legacy-embedding-settings")).to_have_js_property("disabled", True)
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
    assert classic_ui.image_tests == [{"test_type": "image", "selection": reference("studio", "same:model", "custom")}]
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


def test_classic_manual_alias_keeps_the_underlying_model_without_an_api_override(classic_ui):
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


def test_classic_custom_image_metadata_preserves_separate_edit_and_mask_flags(classic_ui):
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Imported Studio").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    dialog.get_by_label("Model Name", exact=True).fill("private-image-orchestrator")
    dialog.get_by_text("Capability metadata", exact=True).click()
    dialog.get_by_label("Image generation support", exact=True).select_option("true")
    dialog.get_by_label("Source-image editing support", exact=True).select_option("true")
    dialog.get_by_label("Uploaded-mask support", exact=True).select_option("false")
    dialog.get_by_label("Image API for explicit metadata", exact=True).select_option("responses")
    expect(dialog.get_by_label("Source-image editing support", exact=True)).to_be_visible()
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    stored = json.loads(page.locator("#model_endpoints_json").input_value())
    model = next(item for item in stored if item["id"] == "studio")["models"][0]
    assert model["supportsImageGeneration"] is True
    assert model["supportsImageEditing"] is True
    assert model["supportsImageMasking"] is False
    assert model["image_generation_api"] == "responses"
    assert classic_ui.image_tests == [] and classic_ui.connection_writes == []

def test_classic_edit_preserves_an_omitted_raw_gateway_key_prefix(classic_ui):
    source = classic_ui.endpoints[1]
    source["auth"]["api_key_header"] = "X-Gateway-Key"
    source["auth"].pop("api_key_prefix", None)
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Imported Studio").get_by_role("button", name="Edit", exact=True).click()
    expect(page.locator("#model-endpoint-api-key-prefix")).to_have_value("")
    page.locator("#model-endpoint-save-btn").click()
    expect(page.locator("#fixture-toasts")).to_contain_text("Please save your settings to persist changes.")
    expect(page.locator("#modelEndpointModal")).not_to_be_visible()
    stored = json.loads(page.locator("#model_endpoints_json").input_value())
    auth = next(item for item in stored if item["id"] == "studio")["auth"]
    assert auth["api_key_header"] == "X-Gateway-Key"
    assert auth.get("api_key_prefix", "") == ""


def test_classic_saving_during_the_open_transition_still_closes_the_editor(classic_ui):
    classic_ui.open()
    page = classic_ui.page
    edit = page.locator("#model-endpoints-tbody tr").filter(has_text="Imported Studio").get_by_role("button", name="Edit", exact=True)
    edit.evaluate("""(button) => {
        const modal = document.getElementById('modelEndpointModal');
        modal.addEventListener('shown.bs.modal', () => { modal.dataset.fixtureOpened = 'true'; }, { once: true });
        button.click();
        document.getElementById('model-endpoint-save-btn').click();
    }""")
    expect(page.locator("#fixture-toasts")).to_contain_text("Please save your settings to persist changes.")
    expect(page.locator("#modelEndpointModal")).to_have_attribute("data-fixture-opened", "true")
    expect(page.locator("#modelEndpointModal")).not_to_be_visible()
    stored = json.loads(page.locator("#model_endpoints_json").input_value())
    assert next(item for item in stored if item["id"] == "studio")["models"][0]["id"] == "same:model"
    assert classic_ui.connection_writes == []


@pytest.mark.parametrize("auth_type", ["api_key", "service_principal"])
def test_classic_duplicate_editor_preserves_image_profiles_and_secret_copy_policy(classic_ui, auth_type):
    source = classic_ui.endpoints[1]
    source["provider"] = "aoai"
    source.pop("api_type", None)
    source["models"][0]["modelName"] = "gpt-image-1"
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
    classic_ui.refresh_capabilities()
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
    assert len(json.loads(page.locator("#model_endpoints_json").input_value())) == 4

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


@pytest.mark.parametrize("width", [1440, 390])
def test_classic_embedding_defaults_work_independently_and_show_policy(classic_ui, width):
    classic_ui.settings.update({"enable_multi_model_endpoints": False, "enable_image_generation": False})
    classic_ui.endpoints.append(connection("backup", "Backup Vector Resource", [embedding_model()]))
    previous = copy.deepcopy(classic_ui.selections)
    classic_ui.open(width=width)
    page = classic_ui.page
    picker = page.get_by_label("Default embedding model", exact=True)
    expect(picker.locator("optgroup")).to_have_count(2)
    expect(page.locator("#embedding-model-policy")).to_contain_text("1,536 dimensions · 8,192 input tokens")
    expect(page.locator("#embeddings-configuration")).to_contain_text("Matching dimensions do not make two embedding models compatible.")
    picker.select_option("1")
    expect(picker).to_be_enabled()
    assert classic_ui.selections["embeddings"] == reference("backup", "embedding-model", "aoai")
    assert classic_ui.selections["chat"] == previous["chat"]
    assert classic_ui.selections["image_generation"] == previous["image_generation"]
    assert classic_ui.patches == []
    page.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.locator("#test_embedding_result")).to_contain_text("returned 1,536 dimensions. No vectors were stored")
    assert classic_ui.embedding_tests == [{"test_type": "embedding", "selection": classic_ui.selections["embeddings"]}]


@pytest.mark.parametrize("message,dimensions,status", [
    ("A different model cannot use existing vectors even at the same dimensions. A controlled rebuild is required.", 1536, 409),
    ("The embedding profile requires 3072 dimensions, but the index has 1536. Recreate the empty index before switching.", 3072, 409),
    ("Settings changed while compatibility was being checked. Refresh and retry.", 1536, 409),
    ("Vector-store compatibility could not be checked. Retry after the stores are available.", 1536, 503),
    ("The embedding endpoint or model policy is invalid. Review the connection configuration.", 1536, 400),
])
def test_classic_rejected_embedding_selection_restores_previous_default(classic_ui, message, dimensions, status):
    classic_ui.endpoints.append(connection("other", "Other Vector Resource", [embedding_model("other", "text-embedding-3-large", dimensions)]))
    classic_ui.open()
    previous = copy.deepcopy(classic_ui.selections)
    classic_ui.reject_selection = True
    classic_ui.selection_error = message
    classic_ui.selection_error_status = status
    page = classic_ui.page
    picker = page.get_by_label("Default embedding model", exact=True)
    picker.select_option("1")
    expect(page.locator("#embedding-model-error")).to_have_text(message)
    expect(picker).to_have_value("0")
    assert classic_ui.selections == previous
    expect(page.locator("#embedding-compatibility-notice")).to_contain_text("Existing vectors use the current embedding profile.")


def test_classic_embedding_test_failure_and_unsaved_model_are_not_success(classic_ui):
    classic_ui.open()
    page = classic_ui.page
    classic_ui.reject_embedding_test = True
    page.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.locator("#test_embedding_result")).to_have_text("Embedding inference returned incompatible dimensions.")
    assert classic_ui.selection_writes == []
    page.locator("#model-endpoints-tbody tr").filter(has_text="Vector Resource").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_checked()
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("button", name="Test chat", exact=True)).not_to_be_visible()
    dialog.get_by_label("Endpoint Name", exact=True).fill("Pending vector connection")
    dialog.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.locator("#fixture-toasts")).to_contain_text("Save the connection first.")
    assert len(classic_ui.embedding_tests) == 1


@pytest.mark.parametrize("width", [1440, 390])
def test_classic_custom_embedding_provider_is_api_key_only_and_manual(classic_ui, width):
    classic_ui.open(width=width)
    page = classic_ui.page
    page.get_by_role("button", name="Add Connection", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    dialog.get_by_label("Endpoint Name", exact=True).fill("Custom Vector Gateway")
    page.locator("#model-endpoint-provider").select_option("openai_compatible")
    expect(page.locator("#model-endpoint-auth-type")).to_have_value("api_key")
    assert page.locator("#model-endpoint-auth-type option:not([disabled])").evaluate_all("(options) => options.map(option => option.value)") == ["api_key"]
    for identifier in ("model-endpoint-project-group", "model-endpoint-project-api-version-group", "model-endpoint-openai-api-version-group", "model-endpoint-subscription-group", "model-endpoint-resource-group-group", "model-endpoint-mi-type-group", "model-endpoint-tenant-group", "model-endpoint-client-group", "model-endpoint-fetch-btn"):
        expect(page.locator(f"#{identifier}")).not_to_be_visible()
    dialog.get_by_label("Embedding API base URL", exact=True).fill("https://gateway.example.test/prefix/api/v1")
    page.locator("#model-endpoint-api-key").fill("fixture-only-not-a-service-key")
    page.locator("#model-endpoint-add-model-btn").click()
    dialog.locator("input[data-deployment-name-for]").fill("private-embed")
    dialog.get_by_label("Text embedding support", exact=True).select_option("true")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).to_be_visible()
    expect(page.locator("#fixture-toasts")).to_contain_text("explicit dimensions and an input token limit")
    dialog.get_by_label("Embedding dimensions", exact=True).fill("768")
    dialog.get_by_label("Embedding input token limit", exact=True).fill("2048")
    dialog.get_by_label("Embedding model revision", exact=True).fill("release-1")
    dialog.get_by_label("Embedding authentication header", exact=True).select_option("authorization")
    expect(dialog.get_by_role("button", name="Test chat", exact=True)).not_to_be_visible()
    dialog.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.locator("#fixture-toasts")).to_contain_text("Save the connection first.")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    payload = json.loads(page.locator("#model_endpoints_json").input_value())[-1]
    assert payload["provider"] == "openai_compatible"
    assert payload["connection"]["endpoint"] == "https://gateway.example.test/prefix/api/v1"
    assert payload["connection"]["operation_settings"]["embeddings"] == {"auth_header": "authorization"}
    assert set(payload["auth"]) == {"type", "api_key"}
    assert payload["management"] == {}
    assert not {"project_name", "project_api_version", "openai_api_version"} & payload["connection"].keys()
    assert payload["models"][0]["embedding_config"] == {"dimensions": 768, "max_input_tokens": 2048, "model_revision": "release-1"}
    assert payload["models"][0]["supportsEmbeddings"] is True
    expect(page.locator("#embedding-model-notice")).to_contain_text("Save the connection first")
    expect(page.locator("#embedding-default-model optgroup")).to_have_count(1)
    assert classic_ui.embedding_tests == [] and classic_ui.connection_tests == []


def test_classic_operation_edits_preserve_mixed_gateway_settings_and_catalog_defaults(classic_ui):
    endpoint = classic_ui.endpoints[0]
    endpoint["provider"] = "aoai"
    endpoint.pop("api_type", None)
    endpoint["connection"]["endpoint"] = "https://gateway.example.test/team/model-routing"
    endpoint["models"].append(embedding_model())
    endpoint["models"][1]["embedding_config"] = {
        "model_revision": "declared-revision", "document_prefix": "passage: ", "query_prefix": "query: ", "max_batch_size": 2,
    }
    endpoint["connection"]["operation_settings"]["embeddings"] = {
        "api": "azure_openai", "endpoint": "https://gateway.example.test/team/vectors",
        "api_version": "2024-10-21", "is_apim": True, "auth_header": "Ocp-Apim-Subscription-Key",
    }
    original = copy.deepcopy(endpoint)
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Team OpenAI").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog.get_by_label("Embedding inference base URL", exact=True)).to_have_value("https://gateway.example.test/team/vectors")
    dialog.get_by_label("Endpoint Name", exact=True).fill("Reviewed mixed connection")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    payload = json.loads(page.locator("#model_endpoints_json").input_value())[0]
    assert payload["connection"]["operation_settings"] == original["connection"]["operation_settings"]
    assert payload["models"][1]["embedding_config"] == original["models"][1]["embedding_config"]
    assert "dimensions" not in payload["models"][1]["embedding_config"]
    assert "max_input_tokens" not in payload["models"][1]["embedding_config"]
    assert "api_key" not in payload["auth"]
    assert "client_secret" not in payload["auth"]


@pytest.mark.parametrize("selection", ["0", ""])
def test_classic_embedding_recovery_is_independent_and_retires_on_shared_save(classic_ui, selection):
    classic_ui.embedding_migration = embedding_import_error_notice()
    classic_ui.embedding_migration["message"] += ' <img src=x onerror="window.untrustedExecuted=true">'
    classic_ui.settings.update({
        "ai_connections_embedding_migration_notice": copy.deepcopy(classic_ui.embedding_migration),
        "azure_openai_embedding_endpoint": "https://legacy-embedding.example.test",
        "azure_openai_embedding_key": "legacy-fixture-key",
        "embedding_model": {"selected": [{"deploymentName": "legacy-embed", "modelName": "text-embedding-ada-002"}], "all": []},
    })
    classic_ui.open()
    page = classic_ui.page
    expect(page.locator("#legacy-embedding-recovery")).to_be_visible()
    expect(page.locator("#legacy-embedding-settings")).to_have_js_property("disabled", False)
    expect(page.locator("#legacy-image-recovery")).not_to_be_visible()
    expect(page.locator("#ai-connections-migration-notice")).to_contain_text("Embedding connection import could not finish.")
    expect(page.locator("#azure_openai_embedding_endpoint")).to_have_value("https://legacy-embedding.example.test")
    assert page.evaluate("window.untrustedExecuted") is None
    expect(page.locator('img[src="x"]')).to_have_count(0)
    previous = page.locator("#embedding_model_json").input_value()
    picker = page.get_by_label("Default embedding model", exact=True)
    picker.select_option(selection)
    expect(picker).to_be_enabled()
    expect(page.locator("#legacy-embedding-settings")).to_have_js_property("disabled", True)
    expect(page.locator("#embedding-migration-notice")).to_contain_text("Embedding configuration now uses AI Connections")
    submitted = page.locator("#admin-settings-form").evaluate("(form) => [...new FormData(form).keys()]")
    assert "embedding_model_json" not in submitted and "azure_openai_embedding_key" not in submitted
    assert page.locator("#embedding_model_json").input_value() == previous
    page.reload(wait_until="networkidle")
    expect(page.locator("#legacy-embedding-recovery")).not_to_be_visible()
    page.evaluate("window.selectEmbeddingModel('retired', 'text-embedding-3-large')")
    expect(page.locator("#embedding-model-error")).to_contain_text("Legacy embedding configuration is not editable.")
    assert page.locator("#embedding_model_json").input_value() == previous
    assert classic_ui.patches == []


def test_classic_foundry_embedding_endpoint_is_explicit_and_not_a_project_rewrite(classic_ui):
    endpoint = classic_ui.endpoints[3]
    endpoint["provider"] = "new_foundry"
    endpoint["connection"].update({"endpoint": "https://foundry.example.test/api/projects/project", "openai_api_version": "v1", "project_api_version": "v1"})
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Vector Resource").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog).to_contain_text("Foundry project endpoints do not route embeddings")
    page.locator("#model-endpoint-save-btn").click()
    expect(page.locator("#fixture-toasts")).to_contain_text("explicit embedding inference base URL ending /openai/v1/")
    expect(dialog).to_be_visible()
    dialog.get_by_label("Embedding inference base URL", exact=True).fill("https://foundry.example.test/openai/v1/")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    payload = json.loads(page.locator("#model_endpoints_json").input_value())[3]
    assert payload["connection"]["endpoint"].endswith("/api/projects/project")
    assert payload["connection"]["operation_settings"]["embeddings"] == {"endpoint": "https://foundry.example.test/openai/v1/"}


def test_classic_unsupported_embedding_model_is_not_published_as_chat_or_images(classic_ui):
    model = classic_ui.endpoints[3]["models"][0]
    model["modelName"] = "embed-v-4-0"
    model["capability_status"]["embeddings"].update({
        "supported": False, "available": False,
        "reason": "This model requires a verified compatible gateway. Native and deprecated embedding APIs are not supported.",
    })
    model["embedding_policy"].update({"api": "unsupported", "requires_input_type": True})
    classic_ui.open()
    page = classic_ui.page
    expect(page.locator("#embedding-default-model option")).to_have_count(1)
    expect(page.locator("#embedding-default-model")).to_have_value("")
    expect(page.locator("#embedding-model-notice")).to_contain_text("The saved default is no longer available. Choose a replacement.")
    assert classic_ui.selections["embeddings"] == reference("vectors", "embedding-model", "aoai")
    assert classic_ui.selection_writes == []
    page.locator("#model-endpoints-tbody tr").filter(has_text="Vector Resource").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Use for images", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("button", name="Test embeddings", exact=True)).not_to_be_visible()
    expect(dialog).to_contain_text("Native and deprecated embedding APIs are not supported.")


@pytest.mark.parametrize("model_name,dimensions", [("embed-v-4-0", 1536), ("Cohere-embed-v3-english", 1024)])
def test_classic_foundry_cohere_gateway_declaration_needs_no_picker_policy_on_model(classic_ui, model_name, dimensions):
    endpoint = connection("cohere", "Cohere Gateway", [embedding_model("cohere-model", model_name, dimensions)])
    endpoint["provider"] = "new_foundry"
    endpoint["connection"].update({
        "endpoint": "https://foundry.example.test/api/projects/project",
        "openai_api_version": "v1", "project_api_version": "v1",
    })
    endpoint["connection"]["operation_settings"]["embeddings"] = {
        "api": "openai", "endpoint": "https://foundry.example.test/openai/v1/",
    }
    classic_ui.endpoints.append(endpoint)
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Cohere Gateway").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_disabled()
    dialog.get_by_text("Capability metadata", exact=True).click()
    expect(dialog.get_by_label("Embedding dimensions", exact=True)).to_have_value("")
    expect(dialog.get_by_label("Embedding dimensions", exact=True)).to_have_attribute("placeholder", "Use catalog default")
    expect(dialog.get_by_label("Embedding input token limit", exact=True)).to_have_value("")
    dialog.get_by_label("Verified OpenAI-compatible gateway", exact=True).select_option("true")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_checked()
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Use for images", exact=True)).to_be_disabled()
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    model = json.loads(page.locator("#model_endpoints_json").input_value())[-1]["models"][0]
    assert model["embedding_config"] == {"openai_compatible": True}
    assert "embedding_policy" not in model
    assert classic_ui.connection_writes == [] and classic_ui.selection_writes == []


@pytest.mark.parametrize("api_type", ["openai", "azure_openai"])
@pytest.mark.parametrize("auth_type", ["api_key", "bearer"])
def test_classic_custom_embeddings_keep_image_metadata_and_saved_request_identity(classic_ui, api_type, auth_type):
    endpoint = classic_ui.add_custom_embedding_connection(api_type, auth_type)
    original = copy.deepcopy(endpoint)
    previous = copy.deepcopy(classic_ui.selections)
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Custom Mixed Gateway").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog.get_by_label("Custom API Type", exact=True)).to_have_value(api_type)
    expect(page.locator("#model-endpoint-auth-type")).to_have_value(auth_type)
    expect(dialog.get_by_label("Use for embeddings", exact=True).nth(1)).to_be_checked()
    expect(dialog.get_by_label("Use for chat", exact=True).nth(1)).to_be_disabled()
    expect(dialog.get_by_label("Use for images", exact=True).nth(1)).to_be_disabled()
    expect(page.locator("#model-endpoint-fetch-btn")).not_to_be_visible()
    wire_name = "embedding-wire-alias" if api_type == "azure_openai" else "text-embedding-3-small"
    expect(dialog.get_by_label("Deployment Name" if api_type == "azure_openai" else "Model Name", exact=True).nth(1)).to_have_value(wire_name)
    dialog.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.locator("#fixture-toasts")).to_contain_text("returned 1,536 dimensions. No vectors were stored")
    assert classic_ui.embedding_tests == [{"test_type": "embedding", "selection": reference("custom-vectors", "custom-embedding", "custom")}]
    dialog.get_by_role("button", name="Test chat", exact=True).click()
    expect(page.locator("#fixture-toasts")).to_contain_text("Chat request succeeded.")
    assert classic_ui.chat_tests[-1]["model"]["modelName"] == "gpt-5.6-sol"
    assert classic_ui.chat_tests[-1]["api_type"] == api_type
    dialog.get_by_label("Embedding inference base URL", exact=True).fill("https://gateway.example.test/other/embedding-base")
    dialog.get_by_label("Embedding authentication header", exact=True).select_option("authorization")
    dialog.get_by_label("Endpoint Name", exact=True).fill("Reviewed Custom Mixed Gateway")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    saved = next(item for item in json.loads(page.locator("#model_endpoints_json").input_value()) if item["id"] == "custom-vectors")
    assert saved["provider"] == "custom" and saved["api_type"] == api_type
    assert saved["connection"]["endpoint"] == original["connection"]["endpoint"]
    assert saved["connection"]["url_mode"] == "exact"
    expected_operations = copy.deepcopy(original["connection"]["operation_settings"])
    expected_operations["embeddings"] = {
        "endpoint": "https://gateway.example.test/other/embedding-base", "auth_header": "authorization",
    }
    assert saved["connection"]["operation_settings"] == expected_operations
    if api_type == "azure_openai":
        assert saved["connection"]["api_version"] == original["connection"]["api_version"]
    assert saved["models"][1]["id"] == "custom-embedding"
    assert saved["models"][1]["deploymentName"] == "embedding-wire-alias"
    assert saved["models"][1]["modelName"] == "text-embedding-3-small"
    assert saved["models"][1]["embedding_config"] == original["models"][1]["embedding_config"]
    assert saved["models"][1]["vendorOptions"] == original["models"][1]["vendorOptions"]
    for key in ("supportsImageEditing", "supportsImageMasking", "image_generation_api"):
        assert saved["models"][0][key] == original["models"][0][key]
    assert not {"api_key", "bearer_token", "client_secret"} & saved["auth"].keys()
    assert saved[f"has_{'api_key' if auth_type == 'api_key' else 'bearer_token'}"] is True
    assert classic_ui.selections == previous and classic_ui.selection_writes == []
    assert classic_ui.connection_writes == []
    expect(page.locator("#embedding-model-notice")).to_contain_text("Save the connection first")


@pytest.mark.parametrize("api_type,auth_type", [
    ("anthropic", "api_key"), ("gemini", "api_key"),
    ("openai", "oauth2_client_credentials"), ("azure_openai", "oauth2_client_credentials"),
])
def test_classic_custom_unsupported_embeddings_leave_chat_controls_available(classic_ui, api_type, auth_type):
    classic_ui.add_custom_embedding_connection(api_type, auth_type)
    classic_ui.open()
    page = classic_ui.page
    expect(page.locator("#embedding-default-model optgroup")).to_have_count(1)
    page.locator("#model-endpoints-tbody tr").filter(has_text="Custom Mixed Gateway").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(page.locator("#model-endpoint-embedding-settings")).not_to_be_visible()
    expect(dialog.get_by_label("Use for embeddings", exact=True).nth(1)).to_be_disabled()
    expect(dialog.get_by_role("button", name="Test embeddings", exact=True)).not_to_be_visible()
    expect(dialog.get_by_label("Use for chat", exact=True).first).to_be_checked()
    expect(dialog.get_by_role("button", name="Test chat", exact=True).first).to_be_visible()
    expect(page.locator("#model-endpoint-embedding-unavailable")).to_contain_text("Other Custom API types and OAuth2 embeddings are not supported.")
    dialog.get_by_text("Capability metadata", exact=True).nth(1).click()
    expect(dialog.get_by_label("Text embedding support", exact=True).nth(1)).to_be_disabled()
    assert classic_ui.embedding_tests == [] and classic_ui.selection_writes == []


def test_classic_saved_embedding_alias_retains_provider_wire_name_and_path(classic_ui):
    endpoint = classic_ui.add_embedding_alias()
    original = copy.deepcopy(endpoint)
    classic_ui.open()
    page = classic_ui.page
    page.locator("#model-endpoints-tbody tr").filter(has_text="Saved Embedding Alias").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(page.locator("#model-endpoint-provider")).to_have_value("openai_compatible")
    expect(dialog.get_by_label("Deployment Name", exact=True)).to_have_value("saved-wire-alias")
    expect(dialog.get_by_label("Underlying Model Name (optional)", exact=True)).to_have_value("text-embedding-3-small")
    expect(page.locator("#custom-model-endpoint-fields")).not_to_be_visible()
    dialog.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.locator("#fixture-toasts")).to_contain_text("returned 1,536 dimensions")
    dialog.get_by_label("Endpoint Name", exact=True).fill("Reviewed Embedding Alias")
    page.locator("#model-endpoint-save-btn").click()
    expect(dialog).not_to_be_visible()
    saved = next(item for item in json.loads(page.locator("#model_endpoints_json").input_value()) if item["id"] == "alias-vectors")
    assert saved["provider"] == "openai_compatible" and "api_type" not in saved
    assert saved["connection"] == original["connection"]
    assert saved["models"][0]["id"] == "alias-embedding"
    assert saved["models"][0]["deploymentName"] == "saved-wire-alias"
    assert saved["models"][0]["modelName"] == "text-embedding-3-small"
    assert saved["auth"] == {"type": "api_key"} and saved["has_api_key"] is True
    assert classic_ui.embedding_tests == [{"test_type": "embedding", "selection": reference("alias-vectors", "alias-embedding", "openai_compatible")}]
    assert classic_ui.selection_writes == [] and classic_ui.connection_writes == []


@pytest.mark.parametrize("model_name,api,description", [
    ("MAI-Image-2.6", "mai", "MAI image output"),
    ("FLUX.2-pro", "flux", "FLUX image output"),
])
def test_classic_provider_image_controls_keep_non_chat_edit_capabilities(classic_ui, model_name, api, description):
    endpoint = classic_ui.add_provider_image_connection(model_name)
    classic_ui.open()
    page = classic_ui.page
    before = copy.deepcopy(classic_ui.selections)
    picker = page.get_by_label("Default image model", exact=True)
    picker.select_option("3")
    expect(picker).to_be_enabled()
    page.locator("#model-endpoints-tbody tr").filter(has_text="Provider Images").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Use for images", exact=True)).to_be_checked()
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_disabled()
    expect(dialog).to_contain_text(description)
    expect(dialog).to_contain_text("Reference-image edits; no uploaded masks")
    dialog.get_by_text("Capability metadata", exact=True).click()
    assert dialog.get_by_label("Image API for explicit metadata", exact=True).locator("option").evaluate_all("(options) => options.map(option => option.value)") == ["", "images", "responses", "mai", "flux"]
    status = endpoint["models"][0]["capability_status"]["image_generation"]
    assert status["api"] == api and status["editing"] is True and status["masking"] is False
    assert status["qualities"] == [] and status["backgrounds"] == []
    assert classic_ui.selections["embeddings"] == before["embeddings"]
    assert classic_ui.selections["chat"] == before["chat"]
    assert classic_ui.image_tests == [] and classic_ui.connection_writes == []


def test_classic_three_default_notices_remain_independent_inert_text(classic_ui):
    classic_ui.default_notices = {
        "chat": "The saved chat model needs review.",
        "image_generation": "The saved image model needs review.",
        "embeddings": 'The saved embedding model needs review. <img src=x onerror="window.noticeExecuted=true">',
    }
    classic_ui.open()
    page = classic_ui.page
    for message in classic_ui.default_notices.values():
        expect(page.locator("#ai-connections-default-notices")).to_contain_text(message)
    assert page.evaluate("window.noticeExecuted") is None
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert classic_ui.selection_writes == [] and classic_ui.connection_writes == []
