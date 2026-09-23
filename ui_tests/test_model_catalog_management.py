# test_model_catalog_management.py
"""
Classic and real React V2 catalog workflows on Azure Playwright or local Chromium.
Version: 0.261.126
Implemented in: 0.261.126

API fixtures use the real pure profile validator/transform. They do not establish
tenant authentication, Cosmos availability, or live provider readiness.
"""

from pathlib import Path
import sys
from urllib.parse import unquote

import pytest
from playwright.sync_api import expect

from test_model_endpoint_capacity_editor import capacity_browser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "orchestration"))

import harness_build as hb
from functions_model_catalog import ModelCatalogError, TASKS, change_catalog, get_effective_model_profiles

pytestmark = pytest.mark.ui


@pytest.fixture
def catalog_page(capacity_browser):
    hb.ensure_bundle()
    settings = {}
    revision = 1
    errors = []
    context = capacity_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))

    def api(route):
        nonlocal settings, revision
        request = route.request
        if request.method != "GET":
            payload = request.post_data_json
            if payload.get("etag") != str(revision):
                route.fulfill(status=409, json={"error": "The catalog changed. Reload and review before saving."})
                return
            profile_id = unquote(request.url.rsplit("/", 1)[-1]) if request.method == "PATCH" else None
            try:
                settings = change_catalog(settings, profile_id=profile_id, profile=payload.get("profile"), preferences=payload.get("preferences"))
            except ModelCatalogError as error:
                route.fulfill(status=400, json={"error": error.public_message})
                return
            revision += 1
        profiles = [profile for profile in get_effective_model_profiles(settings)
                    if profile["origin"] == "custom" or profile["id"] == "gpt-5-nano"]
        route.fulfill(json={"profiles": profiles, "tasks": TASKS, "etag": str(revision)})

    page.route("**/api/admin/model-catalog**", api)
    page.route("**/api/v2/bootstrap", lambda route: route.fulfill(json={"catalogs": {"models": []}}))
    with hb.start_static_server() as base:
        page.goto(f"{base}/{hb.HARNESS_HTML_REL}")
        page.wait_for_function("Boolean(window.OrchHarness)")
        page.add_style_tag(path=str(ROOT / "application/single_app/static/css/model-catalog.css"))
        try:
            yield page, settings
            assert errors == []
        finally:
            context.close()


def mount_catalog(page, flavor):
    if flavor == "v2":
        page.evaluate("window.OrchHarness.mount('mount-a', 'ModelCatalogManager', {})")
    else:
        page.add_script_tag(type="module", content="""
            import { mountModelCatalog } from '/application/single_app/static/js/admin/model_catalog_ui.js';
            mountModelCatalog(document.getElementById('mount-a'));
        """)
    expect(page.locator("#mount-a").get_by_label("Search profiles")).to_be_visible()


@pytest.mark.parametrize("flavor", ["classic", "v2"])
def test_catalog_custom_profile_preferences_and_archive(catalog_page, flavor):
    page, _settings = catalog_page
    mount_catalog(page, flavor)
    root = page.locator("#mount-a")
    root.get_by_role("button", name="Add custom profile", exact=True).click()
    root.get_by_label("Name", exact=True).fill("Internal summary model")
    root.get_by_label("What this model is good at", exact=True).fill("Summarizes internal text.")
    root.get_by_label("Summarization", exact=True).select_option("strong")
    root.get_by_label("processes Text", exact=True).select_option("true")
    root.get_by_label("generates Text", exact=True).select_option("true")
    root.get_by_role("button", name="Save profile", exact=True).click()
    expect(root.get_by_text("Catalog saved.", exact=True)).to_be_visible()
    root.get_by_role("button", name="Internal summary model", exact=True).click()
    root.get_by_role("button", name="Favorite", exact=True).click()
    expect(root.get_by_role("button", name="Remove favorite", exact=True)).to_be_visible()
    root.get_by_label("Priority", exact=True).select_option("preferred")
    expect(root.get_by_text("Catalog saved.", exact=True)).to_be_visible()
    root.get_by_role("button", name="Reload catalog", exact=True).click()
    root.get_by_role("button", name="Favorite - Internal summary model", exact=True).click()
    expect(root.get_by_label("Priority", exact=True)).to_have_value("preferred")
    root.get_by_role("button", name="Archive profile", exact=True).click()
    root.get_by_label("Status", exact=True).select_option("archived")
    expect(root.get_by_role("button", name="Favorite - Internal summary model", exact=True)).to_be_visible()
    root.get_by_role("button", name="Unarchive profile", exact=True).click()
    expect(root.get_by_text("No matching profiles.", exact=False)).to_be_visible()


@pytest.mark.parametrize("flavor", ["classic", "v2"])
def test_invalid_profile_preserves_form_and_mobile_layout(catalog_page, flavor):
    page, _settings = catalog_page
    page.set_viewport_size({"width": 390, "height": 844})
    mount_catalog(page, flavor)
    root = page.locator("#mount-a")
    root.get_by_role("button", name="Add custom profile", exact=True).click()
    root.get_by_role("button", name="Save profile", exact=True).click()
    expect(root.get_by_role("alert")).to_contain_text("displayName")
    expect(root.get_by_label("Name", exact=True)).to_be_visible()
    root.get_by_label("Name", exact=True).fill("<img src=x onerror=alert(1)>")
    root.get_by_role("button", name="Save profile", exact=True).click()
    expect(root.get_by_role("button", name="<img src=x onerror=alert(1)>", exact=True)).to_be_visible()
    assert root.locator("img").count() == 0
    width = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert width


def test_conflict_keeps_unsaved_profile(catalog_page):
    page, _settings = catalog_page
    mount_catalog(page, "classic")
    root = page.locator("#mount-a")
    root.get_by_role("button", name="Add custom profile", exact=True).click()
    root.get_by_label("Name", exact=True).fill("Keep my draft")

    def conflict(route):
        route.fulfill(status=409, json={"error": "The catalog changed. Reload and review before saving."})

    page.route("**/api/admin/model-catalog", conflict)
    root.get_by_role("button", name="Save profile", exact=True).click()
    expect(root.get_by_role("alert")).to_contain_text("Reload and review")
    expect(root.get_by_label("Name", exact=True)).to_have_value("Keep my draft")
    root.get_by_role("button", name="Cancel editing", exact=True).click()
    expect(root.get_by_role("button", name="Discard changes", exact=True)).to_be_visible()


@pytest.mark.parametrize("refresh_fails", [False, True])
def test_v2_catalog_save_refreshes_model_availability(catalog_page, refresh_fails):
    page, _settings = catalog_page
    page.route("**/api/v2/bootstrap", lambda route: route.fulfill(
        status=503 if refresh_fails else 200,
        json={"error": "Unavailable"} if refresh_fails else {
            "catalogs": {"models": [{"selection_key": "refreshed-model"}]},
        },
    ))
    page.evaluate("window.OrchHarness.mount('mount-b', 'Toaster', {})")
    mount_catalog(page, "v2")
    root = page.locator("#mount-a")
    root.get_by_role("button", name="Add custom profile", exact=True).click()
    root.get_by_label("Name", exact=True).fill("Refresh availability")
    root.get_by_role("button", name="Save profile", exact=True).click()
    expect(root.get_by_text("Catalog saved.", exact=True)).to_be_visible()
    if refresh_fails:
        expect(page.get_by_text(
            "Catalog saved, but model availability could not refresh. Reload before selecting a model.",
            exact=True,
        )).to_be_visible()
    else:
        page.wait_for_function("""window.OrchHarness.stores.bootstrap.useBootstrapStore
            .getState().data?.catalogs?.models?.[0]?.selection_key === 'refreshed-model'""")


def test_auto_is_orchestration_only_and_sends_no_model_identity(catalog_page):
    page, _settings = catalog_page
    plans = []
    page.route("**/api/user/settings", lambda route: route.fulfill(json={"settings": {}}))

    def plan(route):
        plans.append(route.request.post_data_json)
        route.fulfill(content_type="text/event-stream", body='data: {"type":"error","error":"Fixture planning stopped"}\n\n')

    page.route("**/api/v2/orchestration/plan", plan)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.reset();
        H.stores.bootstrap.useBootstrapStore.setState({ data: {
            features: { enable_chat_orchestration: true },
            orchestration: { enabled: true, show_manual_controls: true, default_approval_mode: 'manual', allow_user_approval_override: false },
            settings: {}, user: { id: 'catalog-user', display_name: 'Tester' },
            catalogs: { prompts: [], agents: [], models: [
                { selection_key: 'global::one:a', display_name: 'Model A', deployment_name: 'deployed-a', model_id: 'a', endpoint_id: 'one', provider: 'aoai' },
                { selection_key: 'global::two:b', display_name: 'Model B', deployment_name: 'deployed-b', model_id: 'b', endpoint_id: 'two', provider: 'aoai' }
            ] }
        } });
        H.stores.chat.useChatStore.setState({
            activeConversationId: 'catalog-chat', activeConversationKind: 'personal',
            conversations: [{ id: 'catalog-chat', title: 'Model routing' }],
            streaming: false, messagesLoading: false
        });
        H.mount('mount-a', 'Composer', {});
    }""")
    picker = page.locator('[title="Auto chooses by task, then admin priority and favorites. A specific model stays pinned."]')
    expect(picker).to_be_visible()
    picker.click()
    page.get_by_role("option", name="Auto - choose per step", exact=True).click()
    page.get_by_role("textbox", name="Message", exact=True).fill("Summarize then write code.")
    with page.expect_response("**/api/v2/orchestration/plan"):
        page.get_by_role("button", name="Send message", exact=True).click()
    assert len(plans) == 1
    assert plans[0]["model_routing"] == "auto"
    assert not set(plans[0]) & {"model_deployment", "model_id", "model_endpoint_id", "model_provider", "reasoning_effort"}
    page.locator('[title="Orchestrate"]').click()
    expect(picker).to_have_count(0)
    expect(page.get_by_text("Auto - choose per step", exact=True)).to_have_count(0)


def test_execution_model_attribution_survives_runtime_events(catalog_page):
    page, _settings = catalog_page
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.reset();
        const store = H.stores.orchestration.useOrchestrationStore.getState();
        store.setPlan('catalog-conversation', 'catalog-turn', {
            plan_id: 'plan', conversation_id: 'catalog-conversation', turn_id: 'catalog-turn',
            intent: { summary: 'Model attribution', complexity: 'simple' },
            steps: [{ step_id: 'answer', capability_id: 'respond', title: 'Answer',
                model_binding: { label: 'Summary deployment', reason: 'Summarization; standard priority', profile_id: 'gpt-5-nano' } }],
            approval: { mode: 'manual', state: 'pending' }
        });
        H.mount('mount-a', 'OrchestrationRunView', { conversationId: 'catalog-conversation', turnId: 'catalog-turn' });
    }""")
    attribution = page.get_by_test_id("orchestration-step-model")
    expect(attribution).to_contain_text("Planned model: Summary deployment")
    page.evaluate("""() => {
        window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().applyStepEvent(
            'catalog-conversation', 'catalog-turn', {
                step_id: 'answer', status: 'completed', summary: 'Done',
                model_binding: { label: 'Executed deployment', reason: 'Captured execution', profile_id: 'gpt-5-nano' }
            });
    }""")
    expect(attribution).to_contain_text("Execution model: Executed deployment")
