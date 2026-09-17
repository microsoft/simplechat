# test_admin_custom_connections.py
"""
Custom global connection editor browser regressions.
Version: 0.261.107
Implemented in: 0.261.107

Cover real classic/React forms, credential staging, explicit API types, metadata,
and request identifiers using the existing local/Azure Playwright harness.
"""

import json
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

# Existing fixtures provide all local/Azure browser wiring without provisioning.
from custom_connections_admin import CustomConnectionsFixture
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width", [1440, 390])
def test_react_custom_bearer_edit_preserves_ids_and_tests_model_name(page, width):
    fixture = CustomConnectionsFixture(page)
    fixture.open(width)
    page.get_by_role("button", name="Edit Saved Gateway", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Custom API type", exact=True)).to_have_value("openai")
    expect(dialog.get_by_label("Model name", exact=True)).to_have_value("private-chat-model")
    expect(dialog.get_by_label("OpenAI API version", exact=True)).to_have_count(0)
    expect(dialog.get_by_label("Bearer token", exact=True)).to_have_value("")
    dialog.get_by_role("button", name="Test chat", exact=True).click()
    expect(page.get_by_text("private-chat-model answered a chat request. Image inference was not tested.", exact=True)).to_be_visible()
    assert fixture.model_tests[0]["model"]["modelName"] == "private-chat-model"
    dialog.get_by_label("Name", exact=True).fill("Renamed Gateway")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    saved = fixture.connection_writes[-1]
    assert saved["api_type"] == "openai" and saved["models"][0]["id"] == "stable-model"
    assert saved["models"][0]["vendorOptions"] == {"future": [1, 2]}
    assert "bearer_token" not in saved["auth"]
    fixture.assert_clean()


def test_react_custom_oauth_and_mtls_configuration(page):
    fixture = CustomConnectionsFixture(page)
    fixture.open()
    page.get_by_role("button", name="Add connection", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Gemini gateway")
    dialog.get_by_label("Provider", exact=True).select_option("custom")
    dialog.get_by_label("Custom API type", exact=True).select_option("gemini")
    dialog.get_by_label("Endpoint URL", exact=True).fill("https://gateway.example.test/v1beta/openai")
    dialog.get_by_label("Method", exact=True).select_option("oauth2_client_credentials")
    expect(dialog.get_by_label("Management cloud", exact=True)).to_have_count(0)
    dialog.get_by_label("OAuth2 token URL", exact=True).fill("https://identity.example.test/token")
    dialog.get_by_label("OAuth2 client ID", exact=True).fill("fixture-client")
    dialog.get_by_label("OAuth2 client secret", exact=True).fill("fixture-secret")
    dialog.get_by_label("OAuth2 scope (optional)", exact=True).fill("inference")
    dialog.get_by_text("Client certificate (mTLS)", exact=True).click()
    dialog.get_by_label("Client certificate path", exact=True).fill("mounted-cert.pem")
    dialog.get_by_label("Client private key path", exact=True).fill("mounted-key.pem")
    dialog.get_by_role("button", name="Add manually", exact=True).click()
    dialog.get_by_label("Model name", exact=True).fill("gemini-model")
    dialog.get_by_role("button", name="Create connection", exact=True).click()
    expect(dialog).to_have_count(0)
    saved = fixture.connection_writes[-1]
    assert saved["api_type"] == "gemini"
    assert "api_version" not in saved["connection"] and "openai_api_version" not in saved["connection"]
    assert saved["auth"]["client_secret"] == "fixture-secret"
    assert saved["connection"]["client_key_path"] == "mounted-key.pem"
    assert saved["models"][0]["modelName"] == "gemini-model"
    fixture.assert_clean()


@pytest.mark.parametrize("width", [1440, 390])
def test_classic_custom_edit_is_staged_and_keeps_canonical_model_name(page, width):
    fixture = CustomConnectionsFixture(page, classic=True)
    fixture.open(width)
    page.locator("#model-endpoints-tbody tr").filter(has_text="Saved Gateway").get_by_role("button", name="Edit", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Custom API Type", exact=True)).to_have_value("openai")
    expect(dialog.get_by_label("Model Name", exact=True)).to_have_value("private-chat-model")
    expect(dialog.get_by_label("Bearer Token", exact=True)).to_have_value("")
    dialog.get_by_label("Endpoint Name", exact=True).fill("Staged Gateway")
    dialog.get_by_role("button", name="Save Endpoint", exact=True).click()
    expect(dialog).not_to_be_visible()
    staged = json.loads(page.locator("#model_endpoints_json").input_value())[0]
    assert staged["id"] == "stable-endpoint" and staged["api_type"] == "openai"
    assert staged["models"][0]["id"] == "stable-model"
    assert staged["models"][0]["vendorOptions"] == {"future": [1, 2]}
    assert staged["has_bearer_token"] is True
    assert "openai_api_version" not in staged["connection"]
    assert fixture.connection_writes == []
    fixture.assert_clean()


def test_react_custom_network_policy_is_an_explicit_separate_save(page):
    fixture = CustomConnectionsFixture(page)
    fixture.open()
    page.get_by_text("Custom endpoint network policy", exact=True).click()
    page.get_by_label("Allow private Custom endpoint hosts", exact=True).check()
    page.get_by_label("Custom CA bundle path", exact=True).fill("mounted-ca.pem")
    page.get_by_role("button", name="Save Custom network policy", exact=True).click()
    expect(page.get_by_text("Saved Custom network policy.", exact=True)).to_be_visible()
    assert fixture.patches[-1] == {
        "allow_private_custom_model_endpoints": True,
        "allow_insecure_custom_model_endpoints": False,
        "custom_model_endpoint_ca_bundle_path": "mounted-ca.pem",
    }
    assert fixture.connection_writes == []
    fixture.assert_clean()


@pytest.mark.parametrize("classic", [False, True])
def test_custom_connection_labels_remain_inert_text(page, classic):
    fixture = CustomConnectionsFixture(page, classic=classic)
    injected = '<img src=x onerror="window.customInjected=true">'
    fixture.endpoints[0]["name"] = injected
    fixture.open()
    expect(page.get_by_text(injected, exact=True).first).to_be_visible()
    assert page.evaluate("window.customInjected") is None
    expect(page.locator('img[src="x"]')).to_have_count(0)
    fixture.assert_clean()


def test_classic_custom_duplicate_requires_new_credentials_and_starts_disabled(page):
    fixture = CustomConnectionsFixture(page, classic=True)
    fixture.open()
    page.locator("#model-endpoints-tbody tr").filter(has_text="Saved Gateway").get_by_role("button", name="Duplicate", exact=True).click()
    dialog = page.locator("#modelEndpointModal")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Bearer Token", exact=True)).to_have_value("")
    dialog.get_by_label("Bearer Token", exact=True).fill("fresh-fixture-token")
    dialog.get_by_role("button", name="Save Endpoint", exact=True).click()
    expect(dialog).not_to_be_visible()
    staged = json.loads(page.locator("#model_endpoints_json").input_value())
    duplicate = next(item for item in staged if item["id"] != "stable-endpoint")
    assert duplicate["enabled"] is False
    assert duplicate["auth"]["bearer_token"] == "fresh-fixture-token"
    assert duplicate["models"][0]["id"] != "stable-model"
    assert fixture.connection_writes == []
    fixture.assert_clean()
