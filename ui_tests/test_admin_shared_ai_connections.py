# test_admin_shared_ai_connections.py
"""
Browser coverage for independent chat/image defaults and shared connection availability.
Version: 0.261.102
Implemented in: 0.261.102

Exercise the real built SPA, production schema and protected API shapes without live services.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from ai_connections_admin import AIConnectionsFixture, image_import_error_notice, reference
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
    for name in ("Team Azure", "Imported Studio", "Image Resource"):
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
    expect(manager.get_by_text(re.compile("embeddings|transcription|speech|computer use", re.I))).to_have_count(0)


@pytest.mark.parametrize("chat_enabled,image_enabled", [(False, True), (True, False)])
def test_image_defaults_do_not_depend_on_chat_mode(ai_ui, chat_enabled, image_enabled):
    ai_ui.settings.update({"enable_multi_model_endpoints": chat_enabled, "enable_image_generation": image_enabled})
    ai_ui.open()
    expect(ai_ui.page.get_by_label("Default chat model", exact=True)).to_be_enabled(enabled=chat_enabled)
    expect(ai_ui.page.get_by_label("Default image model", exact=True)).to_be_enabled()
    expect(ai_ui.page.get_by_role("button", name="Test image generation", exact=True)).to_be_enabled(enabled=image_enabled)
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
