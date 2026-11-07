# test_v2_admin_speech_resource_id_save.py
"""
Browser regression for the V2 Speech Resource ID Build-to-save workflow.
Version: 0.261.397
Implemented in: 0.261.397

Use the existing closed local/Azure Playwright harness with the production SPA,
Speech field schema, and real normalizer. No live application settings are used.
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

SUBSCRIPTION_ID = "12345678-1234-1234-1234-123456789abc"
RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-speech-test"
    "/providers/Microsoft.CognitiveServices/accounts/speech-test"
)


@pytest.fixture
def speech_ui(page):
    fixture = AdminSettingsFixture(
        page,
        sections={"knowledge": ("ai-voice-chat-section",)},
        validate_updates=True,
    )
    fixture.settings.update({
        "enable_text_to_speech": True,
        "speech_service_authentication_type": "managed_identity",
        "speech_service_resource_id": "",
    })
    yield fixture
    fixture.assert_clean()


def _edit_speech_resource(fixture, *, pasted=False):
    fixture.open(ready_region="AI Voice Conversations")
    page = fixture.page
    page.get_by_label("Speech Endpoint", exact=True).fill(
        "https://speech-test.cognitiveservices.azure.com/"
    )
    page.get_by_label("Location", exact=True).fill("eastus")
    page.get_by_label("Subscription ID", exact=True).fill(SUBSCRIPTION_ID)
    page.get_by_label("Resource Group", exact=True).fill("rg-speech-test")
    page.get_by_label("Resource Name", exact=True).fill("speech-test")
    resource_id = page.get_by_label("Speech Resource ID", exact=True)
    if pasted:
        resource_id.fill(f"  {RESOURCE_ID}  ")
    else:
        page.get_by_role("button", name="Build", exact=True).click()
        expect(resource_id).to_have_value(RESOURCE_ID)
    return resource_id


@pytest.mark.parametrize("pasted", [False, True], ids=["built", "pasted"])
def test_speech_resource_id_saves_with_companions_and_reloads(speech_ui, pasted):
    _edit_speech_resource(speech_ui, pasted=pasted)
    page = speech_ui.page
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)

    assert len(speech_ui.patches) == 1
    assert speech_ui.settings["speech_service_resource_id"] == RESOURCE_ID
    assert speech_ui.settings["speech_service_location"] == "eastus"
    assert speech_ui.settings["speech_service_resource_name"] == "speech-test"
    assert speech_ui.settings["speech_service_subscription_id"] == SUBSCRIPTION_ID
    assert speech_ui.settings["speech_service_resource_group"] == "rg-speech-test"

    page.reload(wait_until="networkidle")
    region = page.get_by_role("region", name="AI Voice Conversations", exact=True)
    region.get_by_role("button", name="Speech resource", exact=False).click()
    expect(page.get_by_label("Speech Resource ID", exact=True)).to_have_value(RESOURCE_ID)
    expect(page.get_by_label("Speech Endpoint", exact=True)).to_have_value(
        "https://speech-test.cognitiveservices.azure.com/"
    )


def test_rejected_speech_save_keeps_full_draft_for_retry(speech_ui):
    resource_id = _edit_speech_resource(speech_ui)
    page = speech_ui.page
    speech_ui.reject_next_save = True
    page.get_by_role("button", name="Save changes", exact=True).click()

    expect(page.get_by_text("Fixture validation error.").first).to_be_visible()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_visible()
    expect(resource_id).to_have_value(RESOURCE_ID)
    expect(page.get_by_label("Subscription ID", exact=True)).to_have_value(SUBSCRIPTION_ID)
    expect(page.get_by_label("Resource Name", exact=True)).to_have_value("speech-test")
    assert speech_ui.settings["speech_service_resource_id"] == ""
    assert speech_ui.settings["speech_service_location"] == ""

    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert len(speech_ui.patches) == 2
    assert speech_ui.patches[0] == speech_ui.patches[1]
    assert speech_ui.settings["speech_service_resource_id"] == RESOURCE_ID
    assert speech_ui.errors and all("400" in error for error in speech_ui.errors)
    speech_ui.errors.clear()
