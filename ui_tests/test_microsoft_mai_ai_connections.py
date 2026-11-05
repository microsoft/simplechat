# test_microsoft_mai_ai_connections.py
"""
UI regression coverage for native Microsoft MAI connection configuration.
Version: 0.261.410
Implemented in: 0.261.410

The existing Azure Playwright-ready fixture serves the built V2 application and
intercepts every API. These workflows never contact the beta app, acquire model
credentials, change cloud resources, or perform inference.
"""

from copy import deepcopy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

# Reuse the repository's Azure Playwright connection and closed API fixture.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui


@pytest.fixture
def mai_connections_ui(page):
    fixture = AdminSettingsFixture(
        page, sections={"ai-models": ("model-catalog-section", "multi-endpoint-configuration")},
    )
    fixture.settings["enable_multi_model_endpoints"] = True
    fixture.endpoints = [{
        "id": "mai-connection", "name": "Microsoft MAI", "provider": "new_foundry", "enabled": True,
        "connection": {
            "endpoint": "https://resource.services.ai.azure.com/api/projects/team",
            "use_responses_api": False, "openai_api_version": "",
            "project_api_version": "", "project_name": "",
        },
        "auth": {"type": "managed_identity", "managed_identity_type": "system_assigned"},
        "models": [{
            "id": "mai-model", "deploymentName": "production-mai", "modelName": "MAI-Thinking-1",
            "responseLength": 2048, "enabled": True,
        }],
    }]
    fixture.connection_saves = []

    def save_connection(route):
        body = deepcopy(route.request.post_data_json)
        fixture.connection_saves.append(body)
        fixture.endpoints = [{**body, "id": "mai-connection"}]
        route.fulfill(json={"endpoint": fixture.endpoints[0]})

    fixture.extra_routes[("PATCH", "/api/v2/admin/model-endpoints/mai-connection")] = save_connection
    page.emulate_media(reduced_motion="reduce")
    yield fixture
    fixture.assert_clean()


def _edit(mai_connections_ui, width):
    mai_connections_ui.open(width=width, height=1000, ready_region="Model Catalog")
    page = mai_connections_ui.page
    page.get_by_role("button", name="Edit Microsoft MAI", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit Microsoft MAI", exact=True)
    expect(dialog).to_be_visible()
    return dialog


@pytest.mark.parametrize("width", [390, 1440])
def test_native_mai_can_be_saved_without_discovery_or_default_changes(mai_connections_ui, width):
    dialog = _edit(mai_connections_ui, width)
    expect(dialog.get_by_label("Foundry endpoint", exact=True)).to_have_value(
        "https://resource.services.ai.azure.com/api/projects/team",
    )
    preset = dialog.get_by_label("Catalog profile", exact=True)
    expect(preset).to_have_value("")
    expect(preset.get_by_role("option", name="Automatic exact match: MAI-Thinking-1")).to_have_count(1)
    preset.select_option("mai-thinking-1")
    expect(dialog.get_by_label("Catalog model ID", exact=True)).to_have_value("mai-thinking-1")
    responses = dialog.get_by_role("checkbox", name=re.compile("^Use Responses API"))
    expect(responses).not_to_be_checked()
    expect(responses).to_be_enabled()
    expect(dialog.get_by_text(re.compile("^Native model routing is automatic"))).to_be_visible()
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    saved = mai_connections_ui.connection_saves
    assert len(saved) == 1
    assert saved[0]["connection"]["endpoint"] == "https://resource.services.ai.azure.com/api/projects/team"
    assert saved[0]["connection"]["use_responses_api"] is False
    assert saved[0]["models"][0]["deploymentName"] == "production-mai"
    assert saved[0]["models"][0]["modelName"] == "mai-thinking-1"
    assert saved[0]["models"][0]["catalogModelId"] == "mai-thinking-1"
    assert saved[0]["auth"]["type"] == "managed_identity"
    assert mai_connections_ui.patches == [], "Saving a MAI connection must not change global defaults."


def test_native_models_keep_the_shared_openai_preference_without_forcing_mai_to_responses(mai_connections_ui):
    mai_connections_ui.endpoints[0]["connection"]["use_responses_api"] = True
    dialog = _edit(mai_connections_ui, 1440)
    responses = dialog.get_by_role("checkbox", name=re.compile("^Use Responses API"))
    expect(responses).to_be_checked()
    expect(responses).to_be_enabled()
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    assert mai_connections_ui.connection_saves[0]["connection"]["use_responses_api"] is True


def test_custom_gateway_model_preset_preserves_the_route_and_request_alias(mai_connections_ui):
    endpoint = mai_connections_ui.endpoints[0]
    endpoint.update(provider="custom", api_type="openai", has_api_key=True)
    endpoint["connection"] = {"endpoint": "https://gateway.example/team/proxy", "url_mode": "exact"}
    endpoint["auth"] = {"type": "api_key", "api_key_header": "Ocp-Apim-Subscription-Key", "api_key_prefix": ""}
    endpoint["models"][0]["modelName"] = "gateway-mai"
    dialog = _edit(mai_connections_ui, 1440)
    dialog.get_by_label("Catalog profile", exact=True).select_option("mai-thinking-1")
    dialog.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    saved = mai_connections_ui.connection_saves[0]
    assert saved["connection"]["endpoint"] == "https://gateway.example/team/proxy"
    assert saved["connection"]["url_mode"] == "exact"
    assert saved["models"][0]["modelName"] == "gateway-mai"
    assert saved["models"][0]["catalogModelId"] == "mai-thinking-1"
    assert saved["auth"]["api_key_header"] == "Ocp-Apim-Subscription-Key"
