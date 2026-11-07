# test_v2_admin_extraction_model_settings.py
"""
Browser coverage for V2 Admin Settings metadata extraction and vision model pickers.
Version: 0.261.393
Implemented in: 0.261.393

Exercise the built V2 Admin Settings SPA with the real field schema, real model
catalog builder, and production settings normalizer. Verify that:
  - enabling Metadata Extraction and Multi-Modal Vision Analysis and selecting
    gpt-5.6-terra from an AI Connection saves both deployment names and their
    structured connection references without 400 errors,
  - reloading the page preserves the selected models and Configured section status,
  - non-vision chat models are offered for Metadata Extraction but excluded from
    Vision Model,
  - duplicate deployment names across distinct AI Connections stay distinguishable,
    save the chosen connection reference, and pass that connection to the vision
    connection test,
  - server validation errors keep unsaved edits on screen and Discard reverts them.
"""

import ast
import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
for _path in (str(REPO_ROOT / "functional_tests"), str(APP_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import functions_ai_connections as connections  # noqa: E402
from functions_model_capabilities import resolve_model_vision_support  # noqa: E402


pytestmark = pytest.mark.ui

EXTRACTION_SECTIONS = {
    "knowledge": (
        "metadata-extraction-section",
        "multimodal-vision-section",
    ),
}
METADATA_SWITCH_LABEL = "Enable metadata extraction"
VISION_SWITCH_LABEL = "Enable Multi-Modal Vision Analysis"
ARTIFACTS = "v2_admin_extraction_models"


def _load_model_catalog_builder():
    route_source = APP_ROOT / "route_backend_v2.py"
    route_tree = ast.parse(route_source.read_text(encoding="utf-8"))
    builder = next(
        copy.deepcopy(node)
        for node in ast.walk(route_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build_model_catalog"
    )
    namespace = {
        "supports_model_capability": connections.supports_model_capability,
        "resolve_model_vision_support": resolve_model_vision_support,
    }
    exec(compile(ast.Module(body=[builder], type_ignores=[]), str(route_source), "exec"), namespace)
    return namespace["_build_model_catalog"]


BUILD_MODEL_CATALOG = _load_model_catalog_builder()


def _endpoint(endpoint_id, name, provider="aoai", models=None):
    if models is None:
        models = [
            {
                "id": "terra-model",
                "deploymentName": "gpt-5.6-terra",
                "modelName": "gpt-5.6-terra",
                "displayName": "gpt-5.6-terra",
                "enabled": True,
            },
            {
                "id": "text-only-model",
                "deploymentName": "gpt-5.3-chat",
                "modelName": "gpt-5.3-chat",
                "displayName": "gpt-5.3-chat",
                "enabled": True,
                "supportsVision": False,
            },
        ]
    return {
        "id": endpoint_id,
        "name": name,
        "provider": provider,
        "enabled": True,
        "connection": {
            "endpoint": f"https://{endpoint_id}.openai.azure.com",
            "openai_api_version": "2025-04-01-preview",
        },
        "auth": {"type": "managed_identity"},
        "models": copy.deepcopy(models),
    }


@pytest.fixture
def extraction_ui(page):
    fixture = AdminSettingsFixture(page, sections=EXTRACTION_SECTIONS, validate_updates=True)
    fixture.settings.update({
        "enable_multi_model_endpoints": True,
        "model_endpoints": [_endpoint("migrated-aoai", "Migrated Azure OpenAI Endpoint")],
        "enable_extract_meta_data": False,
        "metadata_extraction_model": "",
        "metadata_extraction_model_selection": {
            "endpoint_id": "",
            "model_id": "",
            "provider": "",
        },
        "enable_multimodal_vision": False,
        "multimodal_vision_model": "",
        "multimodal_vision_model_selection": {
            "endpoint_id": "",
            "model_id": "",
            "provider": "",
        },
    })
    fixture.payload["model_catalog"] = BUILD_MODEL_CATALOG(fixture.settings)
    yield fixture
    fixture.assert_clean()


def _switch(scope, label):
    return scope.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))


def _set_switch(page, label, checked):
    checkbox = _switch(page, label)
    if checkbox.is_checked() != checked:
        page.get_by_text(label, exact=True).click()
    expect(checkbox).to_be_checked(checked=checked)


def _save(page):
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)


def test_enabling_and_selecting_gpt_5_6_terra_for_metadata_and_vision_saves_and_reloads(extraction_ui):
    extraction_ui.open(ready_region="Metadata Extraction")
    page = extraction_ui.page

    _set_switch(page, METADATA_SWITCH_LABEL, True)
    _set_switch(page, VISION_SWITCH_LABEL, True)

    extraction_select = page.get_by_label("Extraction Model", exact=True)
    vision_select = page.get_by_label("Vision Model", exact=True)
    expect(extraction_select).to_be_visible()
    expect(vision_select).to_be_visible()

    # Metadata extraction lists both chat models; vision excludes the non-vision chat model.
    extraction_options = extraction_select.locator("option").all_text_contents()
    vision_options = vision_select.locator("option").all_text_contents()
    assert "gpt-5.6-terra · Migrated Azure OpenAI Endpoint" in extraction_options
    assert "gpt-5.3-chat · Migrated Azure OpenAI Endpoint" in extraction_options
    assert "gpt-5.6-terra · Migrated Azure OpenAI Endpoint" in vision_options
    assert "gpt-5.3-chat · Migrated Azure OpenAI Endpoint" not in vision_options

    extraction_select.select_option(label="gpt-5.6-terra · Migrated Azure OpenAI Endpoint")
    vision_select.select_option(label="gpt-5.6-terra · Migrated Azure OpenAI Endpoint")

    _save(page)

    assert len(extraction_ui.patches) == 1
    assert extraction_ui.settings["metadata_extraction_model"] == "gpt-5.6-terra"
    assert extraction_ui.settings["metadata_extraction_model_selection"] == {
        "endpoint_id": "migrated-aoai",
        "model_id": "terra-model",
        "provider": "aoai",
    }
    assert extraction_ui.settings["multimodal_vision_model"] == "gpt-5.6-terra"
    assert extraction_ui.settings["multimodal_vision_model_selection"] == {
        "endpoint_id": "migrated-aoai",
        "model_id": "terra-model",
        "provider": "aoai",
    }

    page.reload(wait_until="networkidle")
    metadata_region = page.get_by_role("region", name="Metadata Extraction", exact=True)
    vision_region = page.get_by_role("region", name="Multi-Modal Vision Analysis", exact=True)
    expect(metadata_region).to_contain_text("Configured")
    expect(vision_region).to_contain_text("Configured")

    metadata_region.get_by_role("button", name=re.compile(r"^Model")).click()
    vision_region.get_by_role("button", name=re.compile(r"^Model")).click()
    expect(page.get_by_label("Extraction Model", exact=True)).to_have_value("gpt-5.6-terra")
    expect(page.get_by_label("Vision Model", exact=True)).to_have_value("gpt-5.6-terra")
    extraction_ui.capture("saved-terra-models", ARTIFACTS)


def test_duplicate_deployment_names_and_vision_test_use_selected_connection(extraction_ui):
    extraction_ui.settings["model_endpoints"].append(
        _endpoint(
            "secondary-foundry",
            "Secondary Foundry Endpoint",
            provider="new_foundry",
            models=[
                {
                    "id": "terra-foundry-model",
                    "deploymentName": "gpt-5.6-terra",
                    "modelName": "gpt-5.6-terra",
                    "displayName": "gpt-5.6-terra",
                    "enabled": True,
                },
            ],
        )
    )
    extraction_ui.payload["model_catalog"] = BUILD_MODEL_CATALOG(extraction_ui.settings)

    vision_tests = []

    def handle_test_connection(route):
        body = route.request.post_data_json
        vision_tests.append(copy.deepcopy(body))
        route.fulfill(json={"success": True, "message": "Vision model responded."})

    extraction_ui.extra_routes[("POST", "/api/v2/admin/settings/test-connection")] = handle_test_connection

    extraction_ui.open(ready_region="Metadata Extraction")
    page = extraction_ui.page

    _set_switch(page, METADATA_SWITCH_LABEL, True)
    _set_switch(page, VISION_SWITCH_LABEL, True)

    extraction_select = page.get_by_label("Extraction Model", exact=True)
    vision_select = page.get_by_label("Vision Model", exact=True)
    extraction_select.select_option(label="gpt-5.6-terra · Secondary Foundry Endpoint")
    vision_select.select_option(label="gpt-5.6-terra · Secondary Foundry Endpoint")

    page.get_by_role("button", name="Test vision analysis", exact=True).click()
    expect(page.get_by_text("Vision model responded.", exact=True)).to_be_visible()
    assert vision_tests == [
        {
            "test_type": "multimodal_vision",
            "vision_model": "gpt-5.6-terra",
            "multi_endpoint": {
                "endpoint_id": "secondary-foundry",
                "model_id": "terra-foundry-model",
                "provider": "new_foundry",
                "deployment_name": "gpt-5.6-terra",
            },
        }
    ]

    _save(page)
    assert extraction_ui.settings["metadata_extraction_model_selection"] == {
        "endpoint_id": "secondary-foundry",
        "model_id": "terra-foundry-model",
        "provider": "new_foundry",
    }
    assert extraction_ui.settings["multimodal_vision_model_selection"] == {
        "endpoint_id": "secondary-foundry",
        "model_id": "terra-foundry-model",
        "provider": "new_foundry",
    }

    page.reload(wait_until="networkidle")
    metadata_region = page.get_by_role("region", name="Metadata Extraction", exact=True)
    vision_region = page.get_by_role("region", name="Multi-Modal Vision Analysis", exact=True)
    metadata_region.get_by_role("button", name=re.compile(r"^Model")).click()
    vision_region.get_by_role("button", name=re.compile(r"^Model")).click()
    expect(
        page.get_by_label("Extraction Model", exact=True).locator("option:checked")
    ).to_have_text("gpt-5.6-terra · Secondary Foundry Endpoint")
    expect(
        page.get_by_label("Vision Model", exact=True).locator("option:checked")
    ).to_have_text("gpt-5.6-terra · Secondary Foundry Endpoint")


def test_server_rejection_preserves_unsaved_edits_and_discard_reverts_references(extraction_ui):
    extraction_ui.open(ready_region="Metadata Extraction")
    page = extraction_ui.page

    _set_switch(page, METADATA_SWITCH_LABEL, True)
    _set_switch(page, VISION_SWITCH_LABEL, True)
    page.get_by_label("Extraction Model", exact=True).select_option(
        label="gpt-5.6-terra · Migrated Azure OpenAI Endpoint"
    )
    page.get_by_label("Vision Model", exact=True).select_option(
        label="gpt-5.6-terra · Migrated Azure OpenAI Endpoint"
    )

    extraction_ui.reject_next_save = True
    page.get_by_role("button", name="Save changes", exact=True).click()

    expect(page.get_by_text("Fixture validation error.").first).to_be_visible()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_visible()
    assert extraction_ui.settings["metadata_extraction_model"] == ""
    assert extraction_ui.settings["multimodal_vision_model"] == ""

    page.get_by_role("button", name="Discard", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    expect(_switch(page, METADATA_SWITCH_LABEL)).not_to_be_checked()
    expect(_switch(page, VISION_SWITCH_LABEL)).not_to_be_checked()
    assert len(extraction_ui.patches) == 1
    assert extraction_ui.errors and all("400" in error for error in extraction_ui.errors)
    extraction_ui.errors.clear()
