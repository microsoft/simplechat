# test_admin_orchestration_planner_model.py
"""
UI coverage for the orchestration planner model dropdown in both Admin Settings pages.
Version: 0.261.137
Implemented in: 0.261.137

The planner used to be named with four typed values: deployment, model id, endpoint id and
provider. Both admin pages now offer one dropdown built from the configured models and write the
four values for the administrator. The classic pane is rendered from its real template with the
real ES module; the V2 control is the real React component in the orchestration harness. Only the
capability-model list is supplied, over an intercepted request. No server or credential is used.
"""

import json
import re
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "orchestration"))

import harness_build as hb  # noqa: E402

pytestmark = pytest.mark.ui
APP_ROOT = HERE.parent / "application" / "single_app"
MODULE = "/application/single_app/static/js/admin/admin_orchestration_planner_model.js"
KEYS = {
    "deployment": "chat_orchestration_planner_deployment",
    "model_id": "chat_orchestration_planner_model_id",
    "endpoint_id": "chat_orchestration_planner_model_endpoint_id",
    "provider": "chat_orchestration_planner_model_provider",
}
ANSWER = "Use the answer model (default)"
# The classic page hides elements with Bootstrap's d-none class; the pane is rendered here without
# the stylesheet, so the class is the contract checked.
HIDDEN = re.compile(r"\bd-none\b")

ENDPOINTS = [
    {"id": "east", "name": "East connection", "provider": "aoai", "enabled": True, "models": [
        {"id": "mini", "deploymentName": "gpt-5-mini", "displayName": "GPT-5 mini", "enabled": True},
        {"id": "nano", "deploymentName": "gpt-5-nano", "displayName": "GPT-5 nano", "enabled": False},
        {"id": "embed", "deploymentName": "embed", "displayName": "Embeddings", "enabled": True, "chat": False},
    ]},
    {"id": "west", "name": "West connection", "provider": "new_foundry", "enabled": True, "models": [
        {"id": "terra", "deploymentName": "terra", "displayName": "Terra", "enabled": True},
    ]},
    {"id": "off", "name": "Disabled connection", "provider": "aoai", "enabled": False, "models": [
        {"id": "hidden", "deploymentName": "hidden", "displayName": "Hidden", "enabled": True},
    ]},
]
CLASSIC_MODELS = [
    {"deploymentName": "gpt-4o", "modelName": "gpt-4o"},
    {"deploymentName": "small-planner", "modelName": "gpt-4o-mini"},
]


def planner(**values):
    return {KEYS[name]: value for name, value in values.items()}


def render_pane(settings):
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"), autoescape=select_autoescape(["html"]),
    )
    return environment.get_template("admin/_panes/chat-orchestration.html").render(
        settings=settings, admin_landing_tab="chat-orchestration",
        orchestration_capabilities=(), orchestration_selected_capabilities=(),
    )


@pytest.fixture(scope="module")
def static_origin():
    with hb.start_static_server() as url:
        yield url


def mount_classic(page, origin, settings, *, multi=True, classic=None):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{origin}/ui_tests/fixtures/orchestration/harness.html", wait_until="domcontentloaded")
    page.set_content(f'<form id="orchestration-settings">{render_pane(settings)}</form>')
    page.evaluate(
        """async ({ module, multi, endpoints, classic }) => {
            const planner = await import(module);
            window.changes = [];
            planner.mountPlannerModelPicker({
                getChoices: () => multi
                    ? planner.connectionChoices(endpoints, (model) => model.enabled !== false && model.chat !== false)
                    : planner.classicChoices(classic),
                onChange: (selection) => window.changes.push(selection),
            });
        }""",
        {"module": MODULE, "multi": multi, "endpoints": ENDPOINTS, "classic": classic or {}},
    )
    return errors


def submitted(page):
    return page.evaluate(
        """(keys) => {
            const form = new FormData(document.getElementById('orchestration-settings'));
            return Object.fromEntries(keys.map((key) => [key, form.get(key)]));
        }""",
        list(KEYS.values()),
    )


def test_classic_dropdown_lists_enabled_connection_chat_models_and_writes_the_set(page, static_origin):
    errors = mount_classic(page, static_origin, {"enable_chat_orchestration": True})
    select = page.get_by_label("Planner model", exact=True)
    expect(select).to_have_value("")
    expect(select.locator("option")).to_have_text([ANSWER, "GPT-5 mini", "Terra"])
    expect(select.locator("optgroup")).to_have_count(2)
    assert select.locator("optgroup").first.get_attribute("label") == "East connection"
    expect(page.locator("#chat-orchestration-planner-model-saved-note")).to_have_class(HIDDEN)
    assert submitted(page) == planner(deployment="", model_id="", endpoint_id="", provider="")

    select.select_option(label="Terra")
    assert submitted(page) == planner(deployment="", model_id="terra", endpoint_id="west", provider="new_foundry")
    select.select_option(label=ANSWER)
    expect(select).to_have_value("")
    assert submitted(page) == planner(deployment="", model_id="", endpoint_id="", provider="")
    assert len(page.evaluate("() => window.changes")) == 2
    assert errors == []


def test_classic_dropdown_offers_classic_deployments_and_preselects_the_saved_one(page, static_origin):
    mount_classic(
        page, static_origin, planner(deployment="small-planner"), multi=False,
        classic={"apimEnabled": False, "legacyModels": CLASSIC_MODELS},
    )
    select = page.get_by_label("Planner model", exact=True)
    expect(select.locator("option")).to_have_text([ANSWER, "gpt-4o", "small-planner (gpt-4o-mini)"])
    expect(select.locator("option:checked")).to_have_text("small-planner (gpt-4o-mini)")
    select.select_option(label="gpt-4o")
    assert submitted(page) == planner(deployment="gpt-4o", model_id="", endpoint_id="", provider="")


def test_classic_dropdown_offers_apim_deployments(page, static_origin):
    mount_classic(
        page, static_origin, {}, multi=False,
        classic={"apimEnabled": True, "apimDeployments": " planner-a, planner-b ,, planner-a"},
    )
    select = page.get_by_label("Planner model", exact=True)
    expect(select.locator("option")).to_have_text([ANSWER, "planner-a", "planner-b"])


@pytest.mark.parametrize("width", [1280, 390])
def test_classic_saved_value_outside_the_list_is_kept_and_named(page, static_origin, width):
    page.set_viewport_size({"width": width, "height": 900})
    saved = planner(deployment="", model_id="retired", endpoint_id="gone", provider="aoai")
    mount_classic(page, static_origin, saved)
    select = page.get_by_label("Planner model", exact=True)
    expect(select.locator("option:checked")).to_have_text("retired on gone — not in the current model list")
    note = page.locator("#chat-orchestration-planner-model-saved-note")
    expect(note).not_to_have_class(HIDDEN)
    assert submitted(page) == saved
    select.select_option(label="GPT-5 mini")
    expect(note).to_have_class(HIDDEN)
    expect(select.locator("option", has_text="not in the current model list")).to_have_count(0)
    assert submitted(page) == planner(deployment="", model_id="mini", endpoint_id="east", provider="aoai")


def mount_v2(page, origin, settings, *, connections_enabled=True, response=None, status=200):
    requests = []

    def capability_models(route):
        requests.append(route.request.url)
        if status != 200:
            route.fulfill(status=status, json={"error": "Models are unavailable."})
            return
        route.fulfill(json=response or {
            "capability": "chat", "selection": {}, "reason": None, "enabled": True, "migration": None,
            "choices": [
                {"endpoint_id": "east", "model_id": "mini", "provider": "aoai",
                 "connection_name": "East connection", "label": "GPT-5 mini",
                 "deployment_name": "gpt-5-mini", "capability": {"supported": True, "available": True, "source": "catalog"}},
                {"endpoint_id": "west", "model_id": "terra", "provider": "new_foundry",
                 "connection_name": "West connection", "label": "Terra",
                 "deployment_name": "terra", "capability": {"supported": True, "available": True, "source": "catalog"}},
            ],
        })

    page.route("**/api/v2/admin/capability-models/chat", capability_models)
    page.goto(f"{origin}/ui_tests/fixtures/orchestration/harness.html", wait_until="domcontentloaded")
    page.wait_for_function("() => typeof window.OrchHarness === 'object'")
    page.evaluate(
        """({ settings, connectionsEnabled }) => {
            window.OrchHarness.reset();
            window.OrchHarness.mount('mount-a', 'PlannerModelWorkflow', { settings, connectionsEnabled });
        }""",
        {"settings": settings, "connectionsEnabled": connections_enabled},
    )
    return requests


def v2_values(page):
    return json.loads(page.get_by_label("Planner settings", exact=True).inner_text())


@pytest.fixture(scope="module", autouse=True)
def harness_bundle():
    hb.ensure_bundle()


def test_v2_picker_uses_the_default_chat_model_list_and_writes_the_set(page, static_origin):
    requests = mount_v2(page, static_origin, {})
    select = page.get_by_label("Planner Model", exact=True)
    expect(select.locator("option")).to_have_text([ANSWER, "GPT-5 mini (gpt-5-mini)", "Terra (terra)"])
    expect(select).to_be_enabled()
    assert len(requests) == 1
    select.select_option(label="GPT-5 mini (gpt-5-mini)")
    assert v2_values(page) == planner(deployment="", model_id="mini", endpoint_id="east", provider="aoai")
    select.select_option(label=ANSWER)
    assert v2_values(page) == planner(deployment="", model_id="", endpoint_id="", provider="")


def test_v2_picker_lists_classic_deployments_without_connections(page, static_origin):
    requests = mount_v2(page, static_origin, {
        "gpt_model": {"selected": CLASSIC_MODELS}, **planner(deployment="small-planner"),
    }, connections_enabled=False)
    select = page.get_by_label("Planner Model", exact=True)
    expect(select.locator("option:checked")).to_have_text("small-planner (gpt-4o-mini)")
    select.select_option(label="gpt-4o")
    assert v2_values(page) == planner(deployment="gpt-4o", model_id="", endpoint_id="", provider="")
    assert requests == []


def test_v2_saved_value_outside_the_list_is_kept_until_replaced(page, static_origin):
    saved = planner(deployment="", model_id="retired", endpoint_id="gone", provider="aoai")
    mount_v2(page, static_origin, saved)
    select = page.get_by_label("Planner Model", exact=True)
    expect(select.locator("option:checked")).to_have_text("retired on gone — not in the current model list")
    expect(page.get_by_text("The saved planner model is not one of the models listed here.", exact=False)).to_be_visible()
    assert v2_values(page) == saved
    select.select_option(label="Terra (terra)")
    assert v2_values(page) == planner(deployment="", model_id="terra", endpoint_id="west", provider="new_foundry")


def test_v2_load_failure_offers_a_retry_without_calling_the_saved_model_missing(page, static_origin):
    saved = planner(deployment="", model_id="mini", endpoint_id="east", provider="aoai")
    mount_v2(page, static_origin, saved, status=503)
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("Models are unavailable.")
    select = page.get_by_label("Planner Model", exact=True)
    expect(select.locator("option:checked")).to_have_text("mini on east")
    page.unroute("**/api/v2/admin/capability-models/chat")
    mount_v2_route = []
    page.route("**/api/v2/admin/capability-models/chat", lambda route: (mount_v2_route.append(1), route.fulfill(json={
        "capability": "chat", "selection": {}, "reason": None, "enabled": True, "migration": None,
        "choices": [{"endpoint_id": "east", "model_id": "mini", "provider": "aoai",
                     "connection_name": "East connection", "label": "GPT-5 mini",
                     "deployment_name": "gpt-5-mini", "capability": {"supported": True, "available": True}}],
    })))
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(select.locator("option:checked")).to_have_text("GPT-5 mini (gpt-5-mini)")
    expect(alert).to_have_count(0)
    assert mount_v2_route == [1]
