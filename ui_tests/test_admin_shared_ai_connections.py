# test_admin_shared_ai_connections.py
"""
Browser coverage for independent chat/image/embedding defaults and connection availability.
Version: 0.261.106
Implemented in: 0.261.105; embeddings added in 0.261.106

Exercise the real built SPA, production schema and protected API shapes without live services.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from ai_connections_admin import (
    AIConnectionsFixture, connection, embedding_import_error_notice, embedding_model,
    image_import_error_notice, reference,
)
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.fixture
def ai_ui(page):
    fixture = AIConnectionsFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize("width", [1440, 390])
def test_shared_list_and_grouped_defaults_preserve_connection_identity(ai_ui, width):
    ai_ui.open(width=width)
    page = ai_ui.page
    manager = page.get_by_role("region", name="AI Connections", exact=True)
    for name in ("Team Azure", "Imported Studio", "Image Resource", "Vector Resource"):
        expect(manager.get_by_text(name, exact=True)).to_be_visible()
    chat = page.get_by_label("Default chat model", exact=True)
    expect(chat.locator("option")).to_have_text(["No default chat model", "Dual model (same-deployment)"])
    image = page.get_by_label("Default image model", exact=True)
    expect(image.locator("optgroup")).to_have_count(3)
    expect(image).to_have_value("1")
    image.select_option("0")
    expect(image).to_be_enabled()
    assert ai_ui.selections["image_generation"] == reference("team", "same:model", "aoai")
    image.select_option("1")
    expect(image).to_be_enabled()
    assert ai_ui.selections["image_generation"] == reference("studio", "same:model", "aoai")
    assert ai_ui.selections["chat"] == reference("team", "same:model", "aoai")
    for legacy in ("Azure OpenAI Image Generation Endpoint", "Azure APIM Subscription Key", "Use APIM instead of direct to Azure OpenAI endpoint"):
        expect(page.get_by_label(legacy, exact=True)).to_have_count(0)
    expect(manager.get_by_text(re.compile(r"1 embeddings"))).to_be_visible()
    expect(manager.get_by_text(re.compile("transcription|speech|computer use", re.I))).to_have_count(0)
    expect(page.get_by_label("Default embedding model", exact=True)).to_have_value("0")


@pytest.mark.parametrize("chat_enabled,image_enabled", [(False, True), (True, False), (False, False)])
def test_image_defaults_do_not_depend_on_chat_mode(ai_ui, chat_enabled, image_enabled):
    ai_ui.settings.update({"enable_multi_model_endpoints": chat_enabled, "enable_image_generation": image_enabled})
    ai_ui.open()
    expect(ai_ui.page.get_by_label("Default chat model", exact=True)).to_be_enabled(enabled=chat_enabled)
    expect(ai_ui.page.get_by_label("Default image model", exact=True)).to_be_enabled()
    expect(ai_ui.page.get_by_role("button", name="Test image generation", exact=True)).to_be_enabled(enabled=image_enabled)
    expect(ai_ui.page.get_by_label("Default embedding model", exact=True)).to_be_enabled()
    expect(ai_ui.page.get_by_role("button", name="Test embeddings", exact=True)).to_be_enabled()
    assert ai_ui.patches == []


def test_default_failure_rolls_back_and_clear_never_restores_legacy(ai_ui):
    ai_ui.open()
    image = ai_ui.page.get_by_label("Default image model", exact=True)
    ai_ui.reject_selection = True
    image.select_option("0")
    expect(ai_ui.page.get_by_role("alert").filter(has_text="The image default could not be saved.")).to_be_visible()
    expect(image).to_have_value("1")
    assert ai_ui.selections["image_generation"]["endpoint_id"] == "studio"
    image.select_option("")
    expect(image).to_be_enabled()
    assert ai_ui.selections["image_generation"] == reference()
    expect(ai_ui.page.get_by_text("Select a default image model before generating images.", exact=False)).to_be_visible()


def test_connection_failure_preserves_draft_and_saved_model(ai_ui):
    ai_ui.open()
    ai_ui.page.get_by_role("button", name="Edit Team Azure", exact=True).click()
    dialog = ai_ui.page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Renamed")
    ai_ui.reject_connection = True
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_role("alert")).to_have_text("The connection could not be saved.")
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Renamed")
    assert ai_ui.endpoints[0]["name"] == "Team Azure"
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(ai_ui.page.get_by_label("Default image model", exact=True)).to_have_value("1")


def test_usage_policy_and_connection_notifications_refresh_choices(ai_ui):
    ai_ui.open()
    page = ai_ui.page
    page.get_by_role("button", name="Edit Imported Studio", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Use for chat", exact=True)).not_to_be_checked()
    expect(dialog.get_by_label("Use for images", exact=True)).to_be_checked()
    expect(dialog.get_by_text("Text output · catalog", exact=True)).to_be_visible()
    dialog.get_by_label("Use for chat", exact=True).check()
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(page.get_by_label("Default chat model", exact=True).locator("optgroup")).to_have_count(2)
    assert set(ai_ui.endpoints[1]["models"][0]["enabled_capabilities"]) == {"chat", "image_generation"}
    reads_before = len(ai_ui.capability_reads)
    page.get_by_role("button", name="Disable Imported Studio", exact=True).click()
    expect(page.get_by_label("Default image model", exact=True)).to_have_value("unavailable")
    expect(page.get_by_test_id("capability-picker-image_generation").get_by_text("The saved default is no longer available.", exact=False)).to_be_visible()
    assert len(ai_ui.capability_reads) > reads_before


def test_image_tests_require_saved_bindings_and_actual_image_success(ai_ui):
    ai_ui.open()
    page = ai_ui.page
    page.get_by_role("button", name="Edit Team Azure", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Display name", exact=True).fill("Pending name")
    dialog.get_by_role("button", name="Test image generation", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Save the connection first.")
    assert ai_ui.image_tests == []
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    ai_ui.reject_image_test = True
    page.get_by_role("button", name="Test image generation", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="The saved model did not return an image.")).to_be_visible()
    assert ai_ui.image_tests == [{"test_type": "image", "selection": reference("studio", "same:model", "aoai")}]
    ai_ui.reject_image_test = False
    page.get_by_role("button", name="Test image generation", exact=True).click()
    expect(page.get_by_text("The saved image model generated an image successfully.", exact=True)).to_be_visible()


def test_migration_notice_and_unknown_default_are_safe_and_actionable(ai_ui):
    injected = '<img src=x onerror="window.untrustedExecuted=true">'
    ai_ui.migration = image_import_error_notice()
    ai_ui.migration["message"] += f" {injected}"
    ai_ui.selections["image_generation"] = reference("missing", "old", "aoai")
    ai_ui.open()
    page = ai_ui.page
    expect(page.get_by_label("Default image model", exact=True)).to_have_value("unavailable")
    expect(page.get_by_test_id("capability-picker-image_generation")).to_contain_text("Classic Image Generation recovery settings")
    assert page.evaluate("window.untrustedExecuted") is None
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert ai_ui.selection_writes == []


@pytest.mark.parametrize("declare_support", [True, False])
def test_manual_image_model_metadata_is_saved_before_default_selection(ai_ui, declare_support):
    ai_ui.open()
    page = ai_ui.page
    page.get_by_role("button", name="Add connection", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Manual Image Resource")
    dialog.get_by_label("Endpoint URL", exact=True).fill("https://manual.example.test")
    dialog.get_by_label("Method", exact=True).select_option("api_key")
    dialog.get_by_label("API key", exact=True).fill("fixture-only-not-a-service-key")
    dialog.get_by_role("button", name="Add manually", exact=True).click()
    dialog.get_by_label("Deployment name", exact=True).fill("manual-image")
    dialog.get_by_label("Display name", exact=True).fill("Manual image")
    dialog.get_by_label("Underlying model name (optional)", exact=True).fill("gpt-image-1")
    dialog.get_by_label("Enable manual-image", exact=True).check()
    if declare_support:
        dialog.get_by_text("Capability metadata", exact=True).click()
        dialog.get_by_label("Text output support", exact=True).select_option("false")
        dialog.get_by_label("Image generation support", exact=True).select_option("true")
        expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
        expect(dialog.get_by_label("Use for images", exact=True)).to_be_checked()
        dialog.get_by_role("button", name="Test image generation", exact=True).click()
        expect(dialog.get_by_role("alert")).to_contain_text("Save the connection first.")
    assert ai_ui.image_tests == []
    dialog.get_by_role("button", name="Create connection", exact=True).click()
    expect(dialog).to_have_count(0)
    image = page.get_by_label("Default image model", exact=True)
    expect(image.locator("optgroup")).to_have_count(4)
    image.select_option("3")
    expect(image).to_be_enabled()
    saved = ai_ui.connection_writes[0]["models"][0]
    assert saved["deploymentName"] == "manual-image" and saved["modelName"] == "gpt-image-1"
    assert "image_generation_api" not in saved
    if declare_support:
        assert saved["supportsChat"] is False and saved["supportsImageGeneration"] is True
    else:
        assert "supportsChat" not in saved and "supportsImageGeneration" not in saved
    assert ai_ui.selections["image_generation"]["endpoint_id"] == "manual-connection"
    expect(page.get_by_label("Default chat model", exact=True).locator("option")).to_have_count(2)


def test_connection_check_does_not_claim_to_test_image_inference(ai_ui):
    ai_ui.open()
    page = ai_ui.page
    page.get_by_role("button", name="Edit Team Azure", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Test connection", exact=True).click()
    expect(page.get_by_text("Connected. 2 deployments visible. Image inference was not tested.", exact=True)).to_be_visible()
    assert ai_ui.image_tests == [] and len(ai_ui.connection_tests) == 1


def test_embedding_defaults_are_global_grouped_and_independent_with_chat_off(ai_ui):
    ai_ui.settings.update({"enable_multi_model_endpoints": False, "enable_image_generation": False})
    ai_ui.endpoints.append(connection("backup", "Backup Vector Resource", [embedding_model()]))
    previous = copy.deepcopy(ai_ui.selections)
    ai_ui.open()
    picker = ai_ui.page.get_by_label("Default embedding model", exact=True)
    expect(picker.locator("optgroup")).to_have_count(2)
    picker.select_option("1")
    expect(picker).to_be_enabled()
    assert ai_ui.selections["embeddings"] == reference("backup", "embedding-model", "aoai")
    assert ai_ui.selections["chat"] == previous["chat"]
    assert ai_ui.selections["image_generation"] == previous["image_generation"]
    assert ai_ui.patches == []
    pane = ai_ui.page.get_by_test_id("capability-picker-embeddings")
    expect(pane.get_by_text(re.compile("1,536 dimensions.*8,192 input tokens"))).to_be_visible()
    expect(pane.get_by_text("Matching dimensions do not make two models compatible.", exact=False)).to_be_visible()
    expect(pane).to_contain_text("personal, group and public")


@pytest.mark.parametrize("message,dimensions,status", [
    ("Existing vectors use another embedding model, even though both models have 1536 dimensions. A controlled rebuild is required.", 1536, 409),
    ("The search index has 1536 dimensions, but the selected embedding profile requires 3072. Recreate the empty index before switching.", 3072, 409),
    ("Settings changed while compatibility was being checked. Refresh and retry.", 1536, 409),
    ("Vector-store compatibility could not be checked. Retry after the stores are available.", 1536, 503),
    ("The embedding endpoint or model policy is invalid. Review the connection configuration.", 1536, 400),
])
def test_rejected_embedding_default_restores_previous_selection_and_policy(ai_ui, message, dimensions, status):
    alternative = embedding_model("other-model", "text-embedding-3-large", dimensions)
    ai_ui.endpoints.append(connection("other", "Other Vector Resource", [alternative]))
    ai_ui.open()
    ai_ui.reject_selection = True
    ai_ui.selection_error = message
    ai_ui.selection_error_status = status
    picker = ai_ui.page.get_by_label("Default embedding model", exact=True)
    picker.select_option("1")
    expect(ai_ui.page.get_by_test_id("capability-picker-embeddings").get_by_role("alert")).to_have_text(message)
    expect(picker).to_have_value("0")
    assert ai_ui.selections["embeddings"] == reference("vectors", "embedding-model", "aoai")
    expect(ai_ui.page.get_by_test_id("capability-picker-embeddings")).to_contain_text("1,536 dimensions")


def test_embedding_operation_tests_use_saved_references_without_default_writes(ai_ui):
    ai_ui.open()
    page = ai_ui.page
    before = copy.deepcopy(ai_ui.selections)
    ai_ui.reject_embedding_test = True
    page.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.get_by_test_id("capability-picker-embeddings").get_by_role("alert")).to_have_text("Embedding inference returned incompatible dimensions.")
    ai_ui.reject_embedding_test = False
    page.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.get_by_test_id("capability-picker-embeddings")).to_contain_text("returned 1,536 dimensions. No vectors were stored")
    assert ai_ui.embedding_tests == [{"test_type": "embedding", "selection": before["embeddings"]}] * 2
    assert ai_ui.selections == before and ai_ui.selection_writes == []
    page.get_by_role("button", name="Edit Vector Resource", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_checked()
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("button", name="Test chat", exact=True)).to_have_count(0)
    dialog.get_by_label("Display name", exact=True).fill("Pending display name")
    dialog.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Save the connection first.")
    assert len(ai_ui.embedding_tests) == 2


@pytest.mark.parametrize("width", [1440, 390])
def test_custom_embedding_provider_requires_api_key_and_explicit_unknown_metadata(ai_ui, width):
    ai_ui.open(width=width)
    page = ai_ui.page
    page.get_by_role("button", name="Add connection", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Custom Vector Gateway")
    dialog.get_by_label("Provider", exact=True).select_option("openai_compatible")
    expect(dialog.get_by_label("Method", exact=True).locator("option")).to_have_text(["API key"])
    for label in ("Project endpoint", "Project name", "Project API version", "OpenAI API version", "Subscription id", "Tenant id", "Client id", "Management cloud"):
        expect(dialog.get_by_label(label, exact=True)).to_have_count(0)
    for button in ("Discover models", "Test connection", "Test chat"):
        expect(dialog.get_by_role("button", name=button, exact=True)).to_have_count(0)
    dialog.get_by_label("Embedding API base URL", exact=True).fill("https://gateway.example.test/prefix/api/v1")
    dialog.get_by_label("API key", exact=True).fill("fixture-only-not-a-service-key")
    dialog.get_by_role("button", name="Add manually", exact=True).click()
    dialog.get_by_label("Deployment name", exact=True).fill("private-embed-v1")
    dialog.get_by_label("Display name", exact=True).fill("Private embeddings")
    dialog.get_by_label("Enable private-embed-v1", exact=True).check()
    dialog.get_by_label("Text embedding support", exact=True).select_option("true")
    dialog.get_by_role("button", name="Create connection", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="Unknown embedding models require explicit dimensions")).to_be_visible()
    assert ai_ui.connection_writes == []
    dialog.get_by_label("Embedding dimensions", exact=True).fill("768")
    dialog.get_by_label("Embedding input token limit", exact=True).fill("2048")
    dialog.get_by_label("Embedding model revision", exact=True).fill("release-1")
    dialog.get_by_label("Verified OpenAI-compatible gateway", exact=True).select_option("true")
    dialog.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="Save the connection first.")).to_be_visible()
    dialog.get_by_role("button", name="Create connection", exact=True).click()
    expect(dialog).to_have_count(0)
    payload = ai_ui.connection_writes[0]
    assert payload["provider"] == "openai_compatible"
    assert payload["connection"]["endpoint"] == "https://gateway.example.test/prefix/api/v1"
    assert payload["management"] == {}
    assert set(payload["auth"]) == {"type", "api_key"}
    assert not {"project_name", "project_api_version", "openai_api_version"} & payload["connection"].keys()
    assert payload["models"][0]["embedding_config"] == {
        "dimensions": 768, "max_input_tokens": 2048, "model_revision": "release-1", "openai_compatible": True,
    }
    picker = page.get_by_label("Default embedding model", exact=True)
    expect(picker.locator("optgroup")).to_have_count(2)
    picker.select_option("1")
    expect(picker).to_be_enabled()
    assert ai_ui.selections["embeddings"]["provider"] == "openai_compatible"
    expect(page.get_by_label("Default chat model", exact=True).locator("option")).to_have_count(2)
    expect(page.get_by_label("Default image model", exact=True).locator("optgroup")).to_have_count(3)
    assert ai_ui.embedding_tests == [] and ai_ui.connection_tests == []


def test_foundry_mixed_connection_preserves_operation_overrides_and_blank_secret(ai_ui):
    endpoint = ai_ui.endpoints[0]
    endpoint["provider"] = "new_foundry"
    endpoint["connection"].update({
        "endpoint": "https://foundry.example.test/api/projects/project",
        "openai_api_version": "v1", "project_api_version": "v1",
    })
    endpoint["connection"]["operation_settings"]["embeddings"] = {
        "api": "openai", "endpoint": "https://foundry.example.test/openai/v1/",
        "is_apim": False, "auth_header": "api-key",
    }
    endpoint["models"].append(embedding_model())
    operations = copy.deepcopy(endpoint["connection"]["operation_settings"])
    ai_ui.open()
    ai_ui.page.get_by_role("button", name="Edit Team Azure", exact=True).click()
    dialog = ai_ui.page.get_by_role("dialog")
    expect(dialog.get_by_label("Embedding inference base URL", exact=True)).to_have_value("https://foundry.example.test/openai/v1/")
    expect(dialog).to_contain_text("Foundry project endpoints do not route embeddings")
    dialog.get_by_label("Name", exact=True).fill("Reviewed Foundry")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    payload = ai_ui.connection_writes[0]
    assert payload["connection"]["operation_settings"] == operations
    assert payload["connection"]["endpoint"].endswith("/api/projects/project")
    assert "api_key" not in payload["auth"]
    assert "embedding_config" not in payload["models"][1]


def test_embedding_import_notice_is_independent_and_does_not_execute_markup(ai_ui):
    ai_ui.embedding_migration = embedding_import_error_notice()
    ai_ui.embedding_migration["message"] += ' <img src=x onerror="window.untrustedExecuted=true">'
    ai_ui.selections["embeddings"] = reference("missing", "missing", "aoai")
    ai_ui.open()
    page = ai_ui.page
    pane = page.get_by_test_id("capability-picker-embeddings")
    expect(pane).to_contain_text("Classic Embeddings recovery settings")
    expect(page.get_by_label("Default embedding model", exact=True)).to_have_value("")
    expect(pane).to_contain_text("The saved default is no longer available. Choose a replacement.")
    expect(page.get_by_role("region", name="AI Connections", exact=True)).to_contain_text("Embedding connection import could not finish.")
    expect(page.get_by_test_id("capability-picker-image_generation")).not_to_contain_text("Embedding connection import could not finish")
    assert page.evaluate("window.untrustedExecuted") is None
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert ai_ui.selection_writes == []
    assert ai_ui.selections["embeddings"] == reference("missing", "missing", "aoai")


def test_unsupported_foundry_embedding_routes_are_explained_not_published(ai_ui):
    model = embedding_model("cohere", "embed-v-4-0")
    model["displayName"] = "Unsupported native model"
    model["capability_status"]["embeddings"].update({
        "supported": False, "available": False,
        "reason": "This model requires a verified compatible gateway. Native and deprecated embedding APIs are not supported.",
    })
    model["embedding_policy"].update({"api": "unsupported", "requires_input_type": True})
    endpoint = connection("foundry", "Unsupported Foundry", [model])
    endpoint["provider"] = "new_foundry"
    endpoint["connection"].update({"endpoint": "https://foundry.example.test/api/projects/project", "openai_api_version": "v1", "project_api_version": "v1"})
    ai_ui.endpoints.append(endpoint)
    ai_ui.open()
    page = ai_ui.page
    expect(page.get_by_label("Default embedding model", exact=True).locator("option")).to_have_count(2)
    page.get_by_role("button", name="Edit Unsupported Foundry", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Use for images", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("button", name="Test embeddings", exact=True)).to_have_count(0)
    expect(dialog).to_contain_text("Native and deprecated embedding APIs are not supported.")
    expect(dialog).to_contain_text("Foundry project endpoints do not route embeddings.")
    expect(dialog.get_by_label("Embedding API", exact=True).locator("option")).to_have_count(2)


def test_embedding_profile_edit_rejection_keeps_draft_and_previous_default(ai_ui):
    ai_ui.open()
    page = ai_ui.page
    page.get_by_role("button", name="Edit Vector Resource", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_text("Capability metadata", exact=True).click()
    expect(dialog.get_by_label("Embedding dimensions", exact=True)).to_have_value("")
    dialog.get_by_label("Embedding dimensions", exact=True).fill("768")
    ai_ui.reject_connection = True
    ai_ui.connection_error = "The active embedding profile cannot change while stored vectors remain. A controlled rebuild is required."
    ai_ui.connection_error_status = 409
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog.get_by_role("alert")).to_have_text(ai_ui.connection_error)
    expect(dialog.get_by_label("Embedding dimensions", exact=True)).to_have_value("768")
    assert "embedding_config" not in ai_ui.endpoints[3]["models"][0]
    assert ai_ui.selections["embeddings"] == reference("vectors", "embedding-model", "aoai")
    assert ai_ui.connection_writes[0]["models"][0]["embedding_config"] == {"dimensions": 768}


def test_saved_nondefault_embedding_test_does_not_activate_that_model(ai_ui):
    ai_ui.endpoints.append(connection("other", "Other Vector Resource", [embedding_model()]))
    ai_ui.open()
    before = copy.deepcopy(ai_ui.selections)
    page = ai_ui.page
    page.get_by_role("button", name="Edit Other Vector Resource", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.get_by_text("docs-embedding returned 1,536 dimensions. No vectors were stored and the default was not changed.", exact=True)).to_be_visible()
    assert ai_ui.embedding_tests == [{"test_type": "embedding", "selection": reference("other", "embedding-model", "aoai")}]
    assert ai_ui.selections == before and ai_ui.selection_writes == []


@pytest.mark.parametrize("model_name,dimensions", [("embed-v-4-0", 1536), ("Cohere-embed-v3-english", 1024)])
def test_foundry_cohere_gateway_declaration_uses_catalog_limits_without_policy_on_editor_records(ai_ui, model_name, dimensions):
    endpoint = connection("cohere", "Cohere Gateway", [embedding_model("cohere-model", model_name, dimensions)])
    endpoint["provider"] = "new_foundry"
    endpoint["connection"].update({
        "endpoint": "https://foundry.example.test/api/projects/project",
        "openai_api_version": "v1", "project_api_version": "v1",
    })
    endpoint["connection"]["operation_settings"]["embeddings"] = {
        "api": "openai", "endpoint": "https://foundry.example.test/openai/v1/",
    }
    ai_ui.endpoints.append(endpoint)
    ai_ui.open()
    page = ai_ui.page
    page.get_by_role("button", name="Edit Cohere Gateway", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_disabled()
    dialog.get_by_text("Capability metadata", exact=True).click()
    expect(dialog.get_by_label("Embedding dimensions", exact=True)).to_have_value("")
    expect(dialog.get_by_label("Embedding dimensions", exact=True)).to_have_attribute("placeholder", "Use catalog default")
    expect(dialog.get_by_label("Embedding input token limit", exact=True)).to_have_value("")
    dialog.get_by_label("Verified OpenAI-compatible gateway", exact=True).select_option("true")
    expect(dialog.get_by_label("Use for embeddings", exact=True)).to_be_checked()
    expect(dialog.get_by_label("Use for chat", exact=True)).to_be_disabled()
    expect(dialog.get_by_label("Use for images", exact=True)).to_be_disabled()
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    model = ai_ui.connection_writes[0]["models"][0]
    assert model["embedding_config"] == {"openai_compatible": True}
    assert "embedding_policy" not in model
    assert ai_ui.selection_writes == []
    picker = page.get_by_label("Default embedding model", exact=True)
    expect(picker.locator("optgroup")).to_have_count(2)
    picker.select_option("1")
    expect(picker).to_be_enabled()
    expect(page.get_by_test_id("capability-picker-embeddings")).to_contain_text("512 input tokens per text")
