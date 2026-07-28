# test_admin_multimodal_vision_model_options.py
"""
UI test for Admin Settings multi-modal Vision Model options.

Version: 0.250.066
Implemented in: 0.250.066

This test ensures enabled GPT 5.6 and later models are recognized across
model, display, and deployment names from multi-model endpoints.
"""

import json
from pathlib import Path

import pytest
from jinja2 import Environment

from application.single_app.functions_model_capabilities import is_vision_capable_model

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
EXPECTED_OPTION_VALUES = [
    "",
    "luna-deployment",
    "gpt-5.6-sol",
    "gpt-4o",
    "N-gpt-5.6-terra",
    "gpt_5.7_preview",
]


def _build_model_endpoints():
    return [
        {
            "id": "aoai-global",
            "provider": "aoai",
            "enabled": True,
            "models": [
                {"id": "luna", "enabled": True, "displayName": "GPT 5.6 Luna", "deploymentName": "luna-deployment", "modelName": ""},
                {"id": "sol", "enabled": True, "displayName": "Sol", "deploymentName": "gpt-5.6-sol", "modelName": ""},
                {"id": "legacy", "enabled": True, "displayName": "GPT-4o", "deploymentName": "gpt-4o", "modelName": "gpt-4o"},
                {"id": "disabled", "enabled": False, "displayName": "GPT 5.6 Disabled", "deploymentName": "gpt-5.6-disabled", "modelName": ""},
            ],
        },
        {
            "id": "new-foundry",
            "provider": "new_foundry",
            "enabled": True,
            "models": [
                {"id": "terra", "enabled": True, "displayName": "Terra", "deploymentName": "N-gpt-5.6-terra", "modelName": ""},
                {"id": "future", "enabled": True, "displayName": "Future model", "deploymentName": "gpt_5.7_preview", "modelName": ""},
                {"id": "text-only", "enabled": True, "displayName": "Claude", "deploymentName": "claude-opus", "modelName": "claude-opus"},
            ],
        },
        {
            "id": "disabled-endpoint",
            "provider": "aifoundry",
            "enabled": False,
            "models": [
                {"id": "hidden", "enabled": True, "displayName": "GPT 6", "deploymentName": "gpt-6", "modelName": "gpt-6"},
            ],
        },
    ]


def _extract_javascript_function(source, function_name):
    """Extract a named function declaration and its balanced body."""
    start = source.index(f"function {function_name}(")
    body_start = source.index("{", start)
    depth = 0

    for index in range(body_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]

    raise AssertionError(f"Could not extract JavaScript function: {function_name}")


def _extract_vision_select_template(source):
    start = source.index('<select class="form-select" id="multimodal_vision_model"')
    end = source.index("</select>", start) + len("</select>")
    return source[start:end]


def _assert_expected_options(page):
    options = page.locator("#multimodal_vision_model option")
    expect(options).to_have_count(len(EXPECTED_OPTION_VALUES))
    assert options.evaluate_all("options => options.map(option => option.value)") == EXPECTED_OPTION_VALUES
    assert all("()" not in label for label in options.all_text_contents())


@pytest.mark.ui
def test_multimodal_vision_options_include_gpt_5_6_and_later_aliases():
    """Populate the Vision Model selector from all supported model name fields."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    source = ADMIN_JS.read_text(encoding="utf-8")
    template_source = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    vision_matcher = _extract_javascript_function(source, "isVisionCapableModelName")
    vision_populator = _extract_javascript_function(source, "populateVisionModels")
    model_endpoints = _build_model_endpoints()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        try:
            vision_select_template = Environment(autoescape=True).from_string(
                _extract_vision_select_template(template_source)
            )
            page.set_content(vision_select_template.render(
                settings={
                    "enable_multi_model_endpoints": True,
                    "model_endpoints": model_endpoints,
                    "multimodal_vision_model": "N-gpt-5.6-terra",
                    "enable_gpt_apim": False,
                    "azure_apim_gpt_deployment": "",
                    "gpt_model": {"selected": []},
                },
                is_vision_capable_model=is_vision_capable_model,
            ))
            _assert_expected_options(page)
            expect(page.locator("#multimodal_vision_model")).to_have_value("N-gpt-5.6-terra")

            page.set_content(
                '<label for="multimodal_vision_model">Vision Model</label>'
                '<select id="multimodal_vision_model"></select>'
            )
            page.add_script_tag(content=f"""
                const visionSelect = document.getElementById('multimodal_vision_model');
                {vision_matcher}
                {vision_populator}

                window.enableMultiModelEndpoints = true;
                window.modelEndpoints = {json.dumps(model_endpoints)};

                populateVisionModels();
            """)

            _assert_expected_options(page)
        finally:
            browser.close()