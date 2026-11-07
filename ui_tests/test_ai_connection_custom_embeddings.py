# test_ai_connection_custom_embeddings.py
"""
Custom embedding controls in the real Classic AI Connections editor.
Version: 0.261.122
Implemented in: 0.261.122

Uses the existing Azure Playwright/local Chromium harness with the actual local
scripts and modal/templates. Inference is a closed, same-origin API fixture.
"""

import re

import pytest
from playwright.sync_api import expect

from ui_tests.test_model_endpoint_capacity_editor import (
    _open_editor, _save, capacity_browser, capacity_ui,
)


pytestmark = [
    pytest.mark.ui,
    pytest.mark.parametrize(
        "capacity_ui", [{"scope": "admin", "connection_templates": True}], indirect=True,
    ),
]


def configure_embedding(api, *, provider="custom", api_type="openai", auth_type="api_key"):
    endpoint = api.endpoints[0]
    endpoint.update(provider=provider, api_type=api_type, has_bearer_token=True)
    endpoint["auth"] = {"type": auth_type}
    endpoint["connection"].update(api_version="2025-03-01-preview", url_mode="auto")
    endpoint["models"][0].update(
        modelName="text-embedding-3-small", deploymentName="embedding-prod",
        enabled_capabilities=["embeddings"], supportsEmbeddings=True,
        embedding_config={"dimensions": 1536, "max_input_tokens": 8192},
        capability_status={
            "embeddings": {"supported": True, "available": True, "source": "catalog", "api": "openai"},
        },
    )
    return endpoint


@pytest.mark.parametrize("provider,api_type,auth_type", [
    ("custom", "openai", "api_key"),
    ("custom", "openai", "bearer"),
    ("custom", "azure_openai", "api_key"),
    ("openai_compatible", "", "api_key"),
])
def test_supported_custom_embeddings_use_the_matching_api_and_saved_selection(
    capacity_ui, provider, api_type, auth_type,
):
    page, api = capacity_ui
    configure_embedding(api, provider=provider, api_type=api_type, auth_type=auth_type)
    _open_editor(page, api)
    expect(page.locator("#model-endpoint-embedding-settings")).to_be_visible()
    expect(page.locator("#model-endpoint-embedding-unavailable")).to_be_hidden()
    expect(page.locator('input[data-capability="embeddings"]')).to_be_enabled()
    expect(page.locator('input[data-capability="embeddings"]')).to_be_checked()
    azure = api_type == "azure_openai"
    azure_option = page.locator('#model-endpoint-embedding-api option[value="azure_openai"]')
    openai_option = page.locator('#model-endpoint-embedding-api option[value="openai"]')
    version_group = page.locator("#model-endpoint-embedding-version-group")
    if azure:
        expect(azure_option).to_be_enabled()
        expect(openai_option).to_be_disabled()
        expect(version_group).to_be_visible()
    else:
        expect(azure_option).to_be_disabled()
        expect(openai_option).to_be_enabled()
        expect(version_group).to_be_hidden()
    page.get_by_role("button", name="Test embeddings", exact=True).click()
    expect(page.locator("#toast-container")).to_contain_text("1,536 dimensions")
    assert api.operation_tests == [{
        "test_type": "embedding",
        "selection": {"endpoint_id": "endpoint-one", "model_id": "model-one", "provider": provider},
    }]
    saved = _save(page, api)
    assert saved["models"][0]["enabled_capabilities"] == ["embeddings"]
    assert "embeddings" not in saved["connection"].get("operation_settings", {})
    if azure:
        assert saved["connection"]["api_version"] == "2025-03-01-preview"


@pytest.mark.parametrize("api_type,auth_type", [
    ("anthropic", "api_key"), ("gemini", "api_key"), ("openai", "oauth2_client_credentials"),
])
def test_unsupported_custom_embedding_protocols_are_not_advertised(capacity_ui, api_type, auth_type):
    page, api = capacity_ui
    configure_embedding(api, api_type=api_type, auth_type=auth_type)
    _open_editor(page, api)
    expect(page.locator("#model-endpoint-embedding-unavailable")).to_contain_text(
        "Other Custom API types and OAuth2 embeddings are not supported.",
    )
    expect(page.locator("#model-endpoint-embedding-settings")).to_be_hidden()
    expect(page.locator('input[data-capability="embeddings"]')).to_be_disabled()
    expect(page.locator('input[data-capability="embeddings"]')).not_to_be_checked()
    expect(page.get_by_role("button", name="Test embeddings", exact=True)).to_be_hidden()
    expect(page.locator('select[data-metadata-key="supportsEmbeddings"]')).to_be_disabled()
    expect(page.locator("#model-endpoints-tbody")).to_contain_text(re.compile(r"0 embeddings", re.I))
    assert api.operation_tests == []


def test_authentication_changes_preserve_drafts_and_reject_invalid_metadata(capacity_ui):
    page, api = capacity_ui
    configure_embedding(api)
    _open_editor(page, api)
    page.locator("[data-description-for]").fill("Keep this draft while changing authentication")
    page.locator("details[data-model-capability-details-for] summary").click()
    dimensions = page.locator('input[data-config-key="dimensions"]')
    dimensions.fill("1.5")
    auth = page.locator("#model-endpoint-auth-type")
    auth.select_option("oauth2_client_credentials")
    expect(auth).to_have_value("api_key")
    expect(dimensions).to_have_value("1.5")
    dimensions.fill("512")
    auth.select_option("oauth2_client_credentials")
    expect(page.locator("#model-endpoint-embedding-unavailable")).to_be_visible()
    expect(page.locator('input[data-capability="embeddings"]')).to_be_disabled()
    expect(dimensions).to_have_value("512")
    expect(page.locator("[data-description-for]")).to_have_value("Keep this draft while changing authentication")
    auth.select_option("api_key")
    expect(page.locator("#model-endpoint-embedding-unavailable")).to_be_hidden()
    expect(page.locator('input[data-capability="embeddings"]')).to_be_enabled()
    expect(dimensions).to_have_value("512")
    expect(page.locator("[data-description-for]")).to_have_value("Keep this draft while changing authentication")


def test_custom_api_mismatch_has_an_explicit_error_instead_of_saving(capacity_ui):
    page, api = capacity_ui
    endpoint = configure_embedding(api, api_type="azure_openai")
    endpoint["connection"]["operation_settings"] = {"embeddings": {"api": "openai"}}
    _open_editor(page, api)
    before = page.locator("#model_endpoints_json").input_value()
    page.locator("#model-endpoint-save-btn").click()
    expect(page.locator("#toast-container")).to_contain_text(
        "The embedding operation must match the Custom connection API type.",
    )
    expect(page.locator("#modelEndpointModal")).to_be_visible()
    assert page.locator("#model_endpoints_json").input_value() == before
