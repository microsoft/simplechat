# test_v2_responses_api_selection.py
"""Rendered Responses toggle, pasted URL normalization and saved-choice regressions.

Version: 0.261.389
Implemented in: 0.261.389
"""

from pathlib import Path
import re
import sys

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from custom_connections_admin import CustomConnectionsFixture
from playwright_connection import connect_options


__all__ = ["connect_options"]


@pytest.mark.ui
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("dark", [False, True])
def test_pasted_responses_url_checks_switch_saves_base_and_can_be_changed_independently(page, width, dark):
    fixture = CustomConnectionsFixture(page)
    fixture.open(width)
    page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", dark)
    page.get_by_role("button", name="Edit Saved Gateway", exact=True).click()
    dialog = page.get_by_role("dialog")
    toggle = dialog.get_by_role("checkbox", name=re.compile(r"^Use Responses API"))
    endpoint = dialog.get_by_label("Endpoint URL", exact=True)
    expect(toggle).not_to_be_checked()
    endpoint.fill("https://gateway.example.test/tenant/models/proxy/responses")
    expect(toggle).to_be_checked()
    expect(endpoint).to_have_value("https://gateway.example.test/tenant/models/proxy")
    toggle.focus()
    page.keyboard.press("Space")
    expect(toggle).not_to_be_checked()
    expect(endpoint).to_have_value("https://gateway.example.test/tenant/models/proxy")
    toggle.focus()
    page.keyboard.press("Space")
    expect(toggle).to_be_checked()
    if (width, dark) in ((1440, False), (390, True)):
        artifacts = Path(__file__).resolve().parent / "artifacts"
        artifacts.mkdir(exist_ok=True)
        toggle.evaluate("input => input.closest('label').scrollIntoView({block: 'center'})")
        page.screenshot(path=str(artifacts / f"responses-api-toggle-{width}.png"), full_page=True, animations="disabled")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    saved = fixture.connection_writes[-1]
    assert saved["connection"]["endpoint"] == "https://gateway.example.test/tenant/models/proxy"
    assert saved["connection"]["use_responses_api"] is True
    assert "bearer_token" not in saved["auth"]
    page.get_by_role("button", name="Edit Saved Gateway", exact=True).click()
    dialog = page.get_by_role("dialog")
    toggle = dialog.get_by_role("checkbox", name=re.compile(r"^Use Responses API"))
    expect(toggle).to_be_checked()
    toggle.focus()
    page.keyboard.press("Space")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    assert fixture.connection_writes[-1]["connection"]["use_responses_api"] is False
    assert fixture.connection_writes[-1]["connection"]["endpoint"] == saved["connection"]["endpoint"]
    fixture.assert_clean()


@pytest.mark.ui
@pytest.mark.parametrize("width", [390, 1440])
def test_resource_base_can_select_responses_without_an_operation_url(page, width):
    fixture = CustomConnectionsFixture(page)
    record = fixture.endpoints[0]
    record["provider"] = "aoai"
    record.pop("api_type")
    record["connection"] = {"endpoint": "https://resource.openai.azure.com", "openai_api_version": "2024-10-01-preview"}
    record["auth"] = {"type": "api_key"}
    record["has_api_key"] = True
    record["models"][0]["deploymentName"] = "private-chat-model"
    fixture.open(width)
    page.get_by_role("button", name="Edit Saved Gateway", exact=True).click()
    dialog = page.get_by_role("dialog")
    toggle = dialog.get_by_role("checkbox", name=re.compile(r"^Use Responses API"))
    dialog.get_by_label("Endpoint URL", exact=True).fill("https://resource.openai.azure.com/openai")
    toggle.focus()
    page.keyboard.press("Space")
    expect(toggle).to_be_checked()
    expect(dialog.get_by_label("OpenAI API version", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    assert fixture.connection_writes[-1]["connection"]["use_responses_api"] is True
    assert fixture.connection_writes[-1]["connection"]["endpoint"] == "https://resource.openai.azure.com/openai"
    assert fixture.connection_writes[-1]["connection"]["openai_api_version"] == "2024-10-01-preview"
    fixture.assert_clean()
