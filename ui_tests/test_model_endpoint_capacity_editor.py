# test_model_endpoint_capacity_editor.py
"""
Azure Playwright-ready endpoint/model capacity editor workflows.

Version: 0.261.035
Implemented in: 0.261.035

Exercises the real shared modal, local Bootstrap/assets, and admin/personal/group
editors with same-origin API fixtures. Uses the existing AZURE_PLAYWRIGHT_*
workspace configuration and DefaultAzureCredential when configured, otherwise
the same workflows run in local Chromium. These fixtures do not qualify tenant
authentication or make requests to a live model deployment.
"""

import copy
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from azure.identity import DefaultAzureCredential
from azure.mgmt.playwright import PlaywrightMgmtClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

from application.single_app.functions_model_endpoint_providers import (
    get_model_endpoint_provider_ui_options,
)


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ORIGIN = "http://simplechat.test"
BUDGET_KEYS = (
    "contextWindow", "inputTokenLimit", "outputTokenLimit", "catalogModelId",
    "modelVersion", "tokenLimitProvider", "outputTokenAccounting",
)
pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def capacity_browser(playwright):
    """Reuse the established Azure workspace configuration, with local fallback."""
    endpoint = os.getenv("AZURE_PLAYWRIGHT_WS_ENDPOINT")
    if not endpoint:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()
        return
    with DefaultAzureCredential() as credential:
        with PlaywrightMgmtClient(credential, os.environ["AZURE_SUBSCRIPTION_ID"]) as client:
            workspace = client.playwright_workspaces.get(
                os.environ["AZURE_PLAYWRIGHT_RESOURCE_GROUP"],
                os.environ["AZURE_PLAYWRIGHT_WORKSPACE"],
            )
            if not workspace.id:
                raise RuntimeError("The Azure Playwright workspace could not be verified.")
            token = credential.get_token(os.environ["AZURE_PLAYWRIGHT_TOKEN_SCOPE"])
            browser = playwright.chromium.connect(
                endpoint,
                headers={"Authorization": f"Bearer {token.token}"},
                expose_network="<loopback>",
            )
            try:
                yield browser
            finally:
                browser.close()


def _saved_endpoint():
    return {
        "id": "endpoint-one",
        "name": "Verified endpoint",
        "provider": "custom",
        "api_type": "openai",
        "enabled": True,
        "connection": {"endpoint": "https://gateway.example"},
        "auth": {"type": "api_key"},
        "has_api_key": True,
        "capabilities": {"toolCalling": True},
        "operatorMetadata": {"source": "verified deployment documentation"},
        "models": [{
            "id": "model-one",
            "modelName": "private-deployment",
            "displayName": "Verified model",
            "description": "Keep this model metadata",
            "enabled": True,
            "icon": {},
            "responseLength": 512,
            "capabilities": {"reasoning": False, "structuredOutput": True},
            "reasoning_effort": "none",
            "metadata": {"tags": ["verified"]},
        }],
    }


class EndpointApiFixture:
    def __init__(self, scope):
        self.scope = scope
        self.endpoints = [_saved_endpoint()]
        self.saved_payloads = []
        self.discovered_models = []
        self.fetch_payloads = []
        self.page_errors = []
        self.console_errors = []
        self.nonlocal_requests = []
        self.fail_save = False
        self.expected_save_error = False

    def handle_api(self, route, path):
        prefix = "/api" if self.scope == "admin" else f"/api/{self.scope}"
        body = route.request.post_data_json or {}
        if path == f"{prefix}/model-endpoints":
            if route.request.method == "POST":
                self.saved_payloads.append(copy.deepcopy(body))
                if self.fail_save:
                    self.expected_save_error = True
                    route.fulfill(
                        status=400, content_type="application/json",
                        body=json.dumps({
                            "error": "contextWindow must be a positive whole number of tokens.",
                            "error_code": "model_context_invalid",
                        }),
                    )
                    return
                self.endpoints = copy.deepcopy(body["endpoints"])
                for endpoint in self.endpoints:
                    endpoint["auth"].pop("api_key", None)
                    endpoint["auth"].pop("client_secret", None)
            payload = {"success": True, "endpoints": self.endpoints}
        elif path == f"{prefix}/models/fetch":
            self.fetch_payloads.append(copy.deepcopy(body))
            payload = {"models": self.discovered_models}
        else:
            route.fulfill(status=404, content_type="application/json", body="{}")
            return
        route.fulfill(content_type="application/json", body=json.dumps(payload))


@pytest.fixture(params=("admin", "user", "group"))
def capacity_ui(request, capacity_browser):
    scope = request.param
    api = EndpointApiFixture(scope)
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    modal = environment.get_template("_multiendpoint_modal.html").render(
        model_endpoint_api_types=get_model_endpoint_provider_ui_options(),
    )
    module = "admin/admin_model_endpoints.js" if scope == "admin" else "workspace/workspace_model_endpoints.js"
    container_id = "group-multi-endpoint-configuration" if scope == "group" else "workspace-multi-endpoint-configuration"
    html = (
        '<!doctype html><html lang="en"><head>'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />'
        '<link rel="stylesheet" href="/static/css/bootstrap.min.css" />'
        '<link rel="stylesheet" href="/static/css/bootstrap-icons.css" />'
        '</head><body>'
        '<div id="toast-container" class="toast-container position-fixed top-0 end-0 p-3"></div>'
        f'<main id="{container_id}">'
        '<input type="checkbox" id="enable_multi_model_endpoints" checked />'
        '<input type="hidden" id="model_endpoints_json" />'
        '<div id="model-endpoints-wrapper">'
        '<button type="button" id="add-model-endpoint-btn">Add Endpoint</button>'
        '<div class="table-responsive"><table class="table">'
        '<tbody id="model-endpoints-tbody"></tbody></table></div></div></main>'
        f'{modal}'
        '<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>'
        '<script src="/static/js/toast.js"></script>'
        f'<script type="module" src="/static/js/{module}"></script>'
        '</body></html>'
    )
    context = capacity_browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.on("pageerror", lambda error: api.page_errors.append(str(error)))
    page.on("console", lambda message: api.console_errors.append(message.text) if message.type == "error" else None)

    def route_request(route):
        parsed = urlsplit(route.request.url)
        path = parsed.path
        if parsed.netloc != "simplechat.test":
            api.nonlocal_requests.append(route.request.url)
            route.abort()
            return
        if path.startswith("/api/"):
            api.handle_api(route, path)
            return
        if path.startswith("/static/"):
            static_root = (APP_ROOT / "static").resolve()
            asset = (static_root / unquote(path[len("/static/"):])).resolve()
            if not asset.is_relative_to(static_root) or not asset.is_file():
                route.fulfill(status=404, body="")
                return
            route.fulfill(
                body=asset.read_bytes(),
                content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream",
            )
            return
        if path == "/capacity-editor":
            route.fulfill(content_type="text/html", body=html)
            return
        route.fulfill(status=204, body="")

    context.route("**/*", route_request)
    try:
        yield page, api
    finally:
        context.close()
        assert not api.page_errors
        assert not api.nonlocal_requests
        unexpected_errors = [
            error for error in api.console_errors
            if not (
                api.expected_save_error
                and ("Error saving endpoint" in error or "status of 400" in error)
            )
        ]
        assert not unexpected_errors


def _open_editor(page, api):
    page.add_init_script(
        f"window.modelEndpoints = {json.dumps(api.endpoints)};"
        f"window.modelEndpointScope = {json.dumps(api.scope)};"
        "window.enableMultiModelEndpoints = true;"
    )
    page.goto(f"{ORIGIN}/capacity-editor", wait_until="networkidle")
    _edit_saved_endpoint(page)


def _edit_saved_endpoint(page):
    modal = page.locator("#modelEndpointModal")
    modal.evaluate("""element => {
        element.dataset.capacityEditorReady = "false";
        element.addEventListener("shown.bs.modal", () => {
            element.dataset.capacityEditorReady = "true";
        }, {once: true});
    }""")
    page.get_by_role("button", name="Edit", exact=True).first.click()
    expect(modal).to_be_visible()
    expect(modal).to_have_attribute("data-capacity-editor-ready", "true")


def _expand(editor):
    if editor.get_attribute("open") is None:
        editor.locator("summary").click()


def _save(page, api):
    if api.scope == "admin":
        page.locator("#model-endpoint-save-btn").click()
    else:
        expected_url = f"{ORIGIN}/api/{api.scope}/model-endpoints"
        with page.expect_response(
            lambda response: response.url == expected_url and response.request.method == "POST"
        ) as saved_response:
            page.locator("#model-endpoint-save-btn").click()
        status = saved_response.value.status
        assert status == 200
    expect(page.locator("#modelEndpointModal")).to_be_hidden()
    if api.scope == "admin":
        return json.loads(page.locator("#model_endpoints_json").input_value())[0]
    assert api.saved_payloads
    return api.saved_payloads[-1]["endpoints"][0]


def test_capacity_save_clear_inheritance_and_metadata(capacity_ui):
    page, api = capacity_ui
    original = copy.deepcopy(api.endpoints[0])
    _open_editor(page, api)
    endpoint_editor = page.get_by_test_id("endpoint-budget-editor")
    model_editor = page.get_by_test_id("model-budget-editor").first
    _expand(endpoint_editor)
    _expand(model_editor)
    expect(endpoint_editor.get_by_text("Response Length is a per-request generation allowance", exact=False)).to_be_visible()
    for label, value in (
        ("Context Window (tokens)", "64000"),
        ("Input Token Limit (tokens)", "60000"),
        ("Output Token Limit (tokens)", "16000"),
    ):
        endpoint_editor.get_by_label(label, exact=True).fill(value)
    endpoint_editor.get_by_label("Token Limit Provider", exact=True).select_option("custom")
    endpoint_editor.get_by_label("Output Token Accounting", exact=True).select_option("unknown")
    for label, value in (
        ("Catalog Model ID", " gpt-5.6-terra "),
        ("Model Version", " snapshot-1 "),
        ("Context Window (tokens)", "16384"),
        ("Input Token Limit (tokens)", "12000"),
        ("Output Token Limit (tokens)", "8192"),
    ):
        model_editor.get_by_label(label, exact=True).fill(value)
    model_editor.get_by_label("Token Limit Provider", exact=True).select_option("azure")
    model_editor.get_by_label("Output Token Accounting", exact=True).select_option("total_generation")
    page.locator("input[data-response-length-for]").first.fill("1024")
    saved = _save(page, api)
    model = saved["models"][0]
    assert [saved[key] for key in BUDGET_KEYS[:3]] == [64000, 60000, 16000]
    assert [model[key] for key in BUDGET_KEYS[:3]] == [16384, 12000, 8192]
    assert saved["tokenLimitProvider"] == "custom"
    assert saved["outputTokenAccounting"] == "unknown"
    assert model["tokenLimitProvider"] == "azure"
    assert model["outputTokenAccounting"] == "total_generation"
    assert model["catalogModelId"] == "gpt-5.6-terra"
    assert model["modelVersion"] == "snapshot-1"
    assert model["responseLength"] == 1024
    assert saved["capabilities"] == original["capabilities"]
    assert saved["operatorMetadata"] == original["operatorMetadata"]
    assert model["capabilities"] == original["models"][0]["capabilities"]
    assert model["metadata"] == original["models"][0]["metadata"]
    assert model["reasoning_effort"] == "none"
    assert not saved["auth"].get("api_key")

    _edit_saved_endpoint(page)
    _expand(endpoint_editor)
    _expand(model_editor)
    expect(model_editor.get_by_label("Model Version", exact=True)).to_have_value("snapshot-1")
    for editor in (endpoint_editor, model_editor):
        for control in editor.locator("input[data-budget-field]").all():
            control.fill("")
        for control in editor.locator("select[data-budget-field]").all():
            control.select_option("")
    cleared = _save(page, api)
    for key in (*BUDGET_KEYS[:3], "tokenLimitProvider", "outputTokenAccounting"):
        assert cleared[key] is None
    for key in BUDGET_KEYS:
        assert cleared["models"][0][key] is None
    assert cleared["models"][0]["responseLength"] == 1024

    _edit_saved_endpoint(page)
    _expand(model_editor)
    expect(model_editor.get_by_label("Context Window (tokens)", exact=True)).to_have_value("")
    expect(model_editor.get_by_label("Catalog Model ID", exact=True)).to_have_attribute("placeholder", "Inherit")


def test_legacy_save_leaves_capacity_unset(capacity_ui):
    page, api = capacity_ui
    _open_editor(page, api)
    saved = _save(page, api)
    assert not set(BUDGET_KEYS).intersection(saved)
    assert not set(BUDGET_KEYS).intersection(saved["models"][0])
    assert saved["models"][0]["responseLength"] == 512


@pytest.mark.parametrize("editor_scope", ("endpoint", "model"))
def test_invalid_capacity_is_visible_and_cannot_save(capacity_ui, editor_scope):
    page, api = capacity_ui
    _open_editor(page, api)
    editor = page.get_by_test_id(f"{editor_scope}-budget-editor").first
    _expand(editor)
    original_admin_payload = page.locator("#model_endpoints_json").input_value()
    for key, invalid in (
        ("contextWindow", "0"),
        ("contextWindow", "-1"),
        ("contextWindow", "1e3"),
        ("contextWindow", "+1"),
        ("contextWindow", "NaN"),
        ("contextWindow", "true"),
        ("contextWindow", "1,000"),
        ("contextWindow", "\uff11\uff12"),
        ("inputTokenLimit", "1.5"),
        ("inputTokenLimit", "1.0"),
        ("outputTokenLimit", "9007199254740992"),
        ("outputTokenLimit", "<img src=x onerror=alert(1)>"),
    ):
        control = editor.locator(f'[data-budget-field="{key}"]')
        control.fill(invalid)
        page.locator("#model-endpoint-save-btn").click()
        expect(page.locator("#modelEndpointModal")).to_be_visible()
        expect(editor.locator(f'[data-budget-error-for="{key}"]')).to_contain_text("positive whole number")
        expect(control).to_have_attribute("aria-invalid", "true")
        expect(control).to_be_focused()
        assert not api.saved_payloads
        assert page.locator("#model_endpoints_json").input_value() == original_admin_payload
        control.fill("")
        expect(control).not_to_have_attribute("aria-invalid", "true")
    editor.get_by_label("Context Window (tokens)", exact=True).fill("9007199254740991")
    saved = _save(page, api)
    record = saved if editor_scope == "endpoint" else saved["models"][0]
    assert record["contextWindow"] == 9007199254740991


def test_discovery_preserves_selected_identity_version_and_overrides(capacity_ui):
    page, api = capacity_ui
    endpoint = api.endpoints[0]
    endpoint.update({
        "provider": "aoai",
        "auth": {"type": "managed_identity", "management_cloud": "public"},
        "management": {"subscription_id": "subscription", "resource_group": "resource-group"},
    })
    endpoint.pop("api_type")
    endpoint["models"][0].update({
        "deploymentName": "private-deployment",
        "modelName": "gpt-5.6-terra",
        "catalogModelId": "gpt-5.6-terra",
        "modelVersion": "snapshot-original",
    })
    api.discovered_models = [
        {"deploymentName": "private-deployment", "modelName": "gpt-5.6-terra", "modelVersion": "remote-version"},
        {"deploymentName": "second-deployment", "modelName": "gpt-5.6-luna", "modelVersion": "new-snapshot"},
    ]
    _open_editor(page, api)
    editor = page.get_by_test_id("model-budget-editor").first
    _expand(editor)
    editor.get_by_label("Model Version", exact=True).fill("exact-local-version")
    editor.get_by_label("Input Token Limit (tokens)", exact=True).fill("7777")
    page.locator("#model-endpoint-fetch-btn").click()
    expect(page.get_by_test_id("model-budget-editor")).to_have_count(2)
    _expand(editor)
    expect(editor.get_by_label("Model Version", exact=True)).to_have_value("exact-local-version")
    expect(editor.get_by_label("Input Token Limit (tokens)", exact=True)).to_have_value("7777")
    new_editor = page.get_by_test_id("model-budget-editor").nth(1)
    _expand(new_editor)
    expect(new_editor.get_by_label("Model Version", exact=True)).to_have_value("new-snapshot")
    saved = _save(page, api)
    assert saved["models"][0]["modelVersion"] == "exact-local-version"
    assert saved["models"][0]["catalogModelId"] == "gpt-5.6-terra"
    assert saved["models"][0]["inputTokenLimit"] == 7777
    assert saved["models"][1]["modelVersion"] == "new-snapshot"
    assert len(api.fetch_payloads) == 1


def test_manual_row_refresh_preserves_identity_as_inert_text(capacity_ui):
    page, api = capacity_ui
    api.endpoints[0]["models"][0]["id"] = 'model"][data-untrusted="row'
    version = 'snapshot"><img src=x onerror="window.budgetInjection=true">'
    _open_editor(page, api)
    editor = page.get_by_test_id("model-budget-editor").first
    _expand(editor)
    editor.get_by_label("Catalog Model ID", exact=True).fill("gpt-5.6-terra")
    editor.get_by_label("Model Version", exact=True).fill(version)
    page.locator("#model-endpoint-add-model-btn").click()
    expect(page.get_by_test_id("model-budget-editor")).to_have_count(2)
    _expand(editor)
    expect(editor.get_by_label("Model Version", exact=True)).to_have_value(version)
    page.locator('[data-action="remove-model"]').nth(1).click()
    expect(page.get_by_test_id("model-budget-editor")).to_have_count(1)
    saved = _save(page, api)
    assert saved["models"][0]["modelVersion"] == version
    assert saved["models"][0]["catalogModelId"] == "gpt-5.6-terra"
    assert page.locator('img[src="x"]').count() == 0
    injected = page.evaluate("Boolean(window.budgetInjection)")
    assert injected is False


def test_capacity_editor_mobile_keyboard_and_labels(capacity_ui):
    page, api = capacity_ui
    page.set_viewport_size({"width": 390, "height": 844})
    _open_editor(page, api)
    for scope in ("endpoint", "model"):
        editor = page.get_by_test_id(f"{scope}-budget-editor").first
        summary = editor.locator("summary")
        summary.focus()
        summary.press("Enter")
        control = editor.get_by_label("Context Window (tokens)", exact=True)
        expect(control).to_be_visible()
        expect(control).to_have_attribute("inputmode", "numeric")
        control.scroll_into_view_if_needed()
        bounds = control.bounding_box()
        assert bounds is not None
        assert bounds["x"] >= 0
        assert bounds["x"] + bounds["width"] <= 390
    dimensions = page.locator("#modelEndpointModal .modal-body").evaluate(
        "(element) => ({client: element.clientWidth, scroll: element.scrollWidth})"
    )
    assert dimensions["scroll"] <= dimensions["client"]


@pytest.mark.parametrize("capacity_ui", ("user", "group"), indirect=True)
def test_rejected_server_configuration_keeps_editor_open(capacity_ui):
    page, api = capacity_ui
    api.fail_save = True
    _open_editor(page, api)
    editor = page.get_by_test_id("model-budget-editor").first
    _expand(editor)
    editor.get_by_label("Context Window (tokens)", exact=True).fill("4096")
    page.locator("#model-endpoint-save-btn").click()
    expect(page.locator("#modelEndpointModal")).to_be_visible()
    expect(page.locator(".toast-body").filter(
        has_text="contextWindow must be a positive whole number of tokens."
    )).to_be_visible()
    assert "contextWindow" not in api.endpoints[0]["models"][0]
    expect(editor.get_by_label("Context Window (tokens)", exact=True)).to_have_value("4096")
    api.fail_save = False
    saved = _save(page, api)
    assert saved["models"][0]["contextWindow"] == 4096
