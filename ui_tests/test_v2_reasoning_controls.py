# test_v2_reasoning_controls.py
"""
Real-Composer reasoning, capability selections, and saved-plan notice regressions.
Version: 0.261.105
Implemented in: 0.261.104

Reuse the local/Azure Playwright fixtures without live model, Azure or retrieval calls.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_model_capabilities import resolve_model_reasoning_policy  # noqa: E402
from test_v2_orchestration_approval_persistence import (  # noqa: E402, F401
    approval_assets, approval_browser, approval_ui, connect_options,
    CHAT_PATH, PLAN_PATH, mount, message_box, send_button, settings_response,
)

pytestmark = pytest.mark.ui


def configure(api, *, orchestrating=True):
    models = [
        {
            "selection_key": "global::east:luna-uuid", "model_id": "luna-uuid",
            "deployment_name": "production", "endpoint_id": "east", "provider": "aoai",
            "model_name": "gpt-5.6-luna", "display_name": "Luna",
            "reasoning_capabilities": resolve_model_reasoning_policy("gpt-5.6-luna"),
        },
        {
            "selection_key": "global::west:other-uuid", "model_id": "other-uuid",
            "deployment_name": "production", "endpoint_id": "west", "provider": "aoai",
            "model_name": "gpt-5", "display_name": "Other model",
            "reasoning_capabilities": resolve_model_reasoning_policy("gpt-5"),
        },
    ]
    api.bootstrap["catalogs"].update(models=models, initial_model_selection=models[0])
    api.bootstrap["features"].update({
        "enable_chat_orchestration": orchestrating, "enable_source_review": True,
        "enable_deep_source_review": True, "enable_web_search": True,
        "enable_url_access": True, "enable_image_generation": True,
    })
    api.settings["reasoningEffortSettings"] = {"luna-uuid": "minimal", "other-uuid": "high"}


def open_manual(page):
    page.get_by_title("Manual controls", exact=True).click()


def choose_effort(page, current, desired):
    page.get_by_role("button", name=current, exact=True).click()
    page.get_by_role("listbox", name="Reasoning options").get_by_role("option", name=desired, exact=True).click()


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_stale_minimal_is_corrected_once_even_with_manual_controls_collapsed(approval_ui, width, mode):
    open_page, api = approval_ui
    configure(api)
    api.settings["orchestrationApprovalMode"] = mode
    page = open_page(width)
    mount(page, api)
    notice = page.get_by_role("status").filter(has_text="Minimal could not be used")
    expect(notice).to_have_count(1)
    expect(notice).to_contain_text("using Low")
    expect(page.get_by_role("button", name="Low", exact=True)).to_have_count(0)
    page.wait_for_function("() => window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().settings.reasoningEffortSettings['luna-uuid'] === 'low'")
    open_manual(page)
    expect(page.get_by_role("button", name="Low", exact=True)).to_be_visible()
    message_box(page).fill("A short request")
    expect(notice).to_have_count(1)
    # Autosave may already have finished while the controls were exercised.
    page.evaluate("async () => await window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().flush()")
    assert api.settings["reasoningEffortSettings"] == {"luna-uuid": "low", "other-uuid": "high"}
    assert api.settings["darkModeEnabled"] is True
    mount(page, api)
    expect(page.get_by_role("status").filter(has_text="Minimal could not be used")).to_have_count(0)
    open_manual(page)
    expect(page.get_by_role("button", name="Low", exact=True)).to_be_visible()


def test_none_and_xhigh_are_real_choices_and_none_is_sent_explicitly(approval_ui):
    open_page, api = approval_ui
    configure(api)
    api.settings["reasoningEffortSettings"]["luna-uuid"] = "high"
    page = open_page()
    mount(page, api)
    open_manual(page)
    page.get_by_role("button", name="High", exact=True).click()
    options = page.get_by_role("listbox", name="Reasoning options").get_by_role("option")
    expect(options).to_have_text(["None", "Low", "Medium", "High", "XHigh"])
    options.filter(has_text="XHigh").click()
    choose_effort(page, "XHigh", "None")
    message_box(page).fill("Hello")
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        send_button(page).click()
    assert api.plans[-1]["reasoning_effort"] == "none"
    assert api.plans[-1]["model_id"] == "luna-uuid"
    assert api.plans[-1]["model_endpoint_id"] == "east"
    assert api.plans[-1]["required_capabilities"] == []
    assert api.plans[-1]["web_search_enabled"] is False


def test_late_settings_merge_preserves_choices_for_two_models(approval_ui):
    open_page, api = approval_ui
    configure(api)
    api.hold_reads = True
    page = open_page()
    mount(page, api)
    open_manual(page)
    choose_effort(page, "Low", "XHigh")
    page.get_by_role("button", name="Luna", exact=True).click()
    page.get_by_role("option", name="Other model", exact=True).click()
    choose_effort(page, "Low", "Medium")
    assert not any("reasoningEffortSettings" in write["settings"] for write in api.writes)
    api.release_reads()
    expect(page.get_by_role("button", name="Medium", exact=True)).to_be_visible()
    with page.expect_response(settings_response):
        page.evaluate("() => window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().flush()")
    assert api.settings["reasoningEffortSettings"] == {"luna-uuid": "xhigh", "other-uuid": "medium"}
    assert api.settings["darkModeEnabled"] is True
    page.get_by_role("button", name="Other model", exact=True).click()
    page.get_by_role("option", name="Luna", exact=True).click()
    expect(page.get_by_role("button", name="XHigh", exact=True)).to_be_visible()


@pytest.mark.parametrize("policy_name", ["gpt-4o", "unknown-private-model"])
def test_unsupported_or_unknown_policy_omits_reasoning_without_erasing_preferences(approval_ui, policy_name):
    open_page, api = approval_ui
    configure(api, orchestrating=False)
    api.bootstrap["catalogs"]["models"][0]["reasoning_capabilities"] = resolve_model_reasoning_policy(policy_name)
    page = open_page()
    mount(page, api)
    expect(page.get_by_role("status").filter(has_text="using Model default")).to_be_visible()
    expect(page.get_by_role("button", name="Low", exact=True)).to_have_count(0)
    message_box(page).fill("Hello")
    with page.expect_response(lambda response: urlsplit(response.url).path == CHAT_PATH):
        send_button(page).click()
    assert "reasoning_effort" not in api.chats[-1]
    assert api.settings["reasoningEffortSettings"]["luna-uuid"] == "minimal"


def test_selected_supported_controls_are_positive_requirements_without_web_opt_in(approval_ui):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    open_manual(page)
    expect(page.get_by_title("Deep research", exact=True)).to_be_enabled()
    page.get_by_title("Deep research", exact=True).click()
    expect(page.get_by_title("Web", exact=True)).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_title("Image unavailable in Orchestrate", exact=True)).to_be_disabled()
    message_box(page).fill("Read https://example.test/report")
    page.get_by_title("Read URLs", exact=True).click()
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        send_button(page).click()
    assert api.plans[-1]["required_capabilities"] == ["deep_research", "url_fetch"]
    assert api.plans[-1]["web_search_enabled"] is False
    assert not any("image" in key for key in api.plans[-1])


@pytest.mark.parametrize("width,manual_controls", [(1440, True), (390, False)])
@pytest.mark.parametrize("choice", ["regular_chat", "orchestrate_without_image"])
def test_preselected_image_requires_an_explicit_compatible_choice_before_click_or_enter(
    approval_ui, width, manual_controls, choice,
):
    open_page, api = approval_ui
    configure(api)
    api.bootstrap["orchestration"]["show_manual_controls"] = manual_controls
    page = open_page(width)
    mount(page, api)
    page.get_by_title("Orchestrate", exact=True).click()
    page.get_by_title("Image", exact=True).click()
    message_box(page).fill("Draw an illustration.")
    page.get_by_title("Orchestrate", exact=True).click()
    notice = page.get_by_role("alert").filter(has_text="Orchestrate cannot generate images")
    expect(notice).to_be_visible()
    expect(send_button(page)).to_be_disabled()
    send_button(page).dispatch_event("click")
    message_box(page).press("Enter")
    expect(notice).to_be_focused()
    expect(message_box(page)).to_have_value("Draw an illustration.")
    assert api.plans == [] and api.chats == []

    if choice == "regular_chat":
        page.get_by_role("button", name="Use regular Chat with Image", exact=True).click()
        expect(page.get_by_title("Image", exact=True)).to_have_attribute("aria-pressed", "true")
        with page.expect_response(lambda response: urlsplit(response.url).path == CHAT_PATH):
            message_box(page).press("Enter")
        assert api.chats[-1]["image_generation"] is True
        assert api.plans == []
        return

    page.get_by_role("button", name="Use Orchestrate without Image for this message", exact=True).click()
    expect(message_box(page)).to_be_focused()
    expect(page.get_by_role("status").filter(has_text="This orchestration message will not generate images")).to_be_visible()
    expect(send_button(page)).to_be_enabled()
    assert api.plans == [] and api.chats == []
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        message_box(page).press("Enter")
    assert api.plans[-1]["required_capabilities"] == []
    assert not any("image" in key for key in api.plans[-1])
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    message_box(page).fill("A second illustration.")
    expect(send_button(page)).to_be_disabled()
    message_box(page).press("Enter")
    expect(notice).to_be_focused()
    assert len(api.plans) == 1
    page.get_by_role("button", name="Use regular Chat with Image", exact=True).click()
    expect(page.get_by_title("Image", exact=True)).to_have_attribute("aria-pressed", "true")


@pytest.mark.parametrize("previous_selection", ["edited_out", "previous_message", "capability_disabled"])
def test_no_url_means_no_hidden_url_requirement_on_later_submission(approval_ui, previous_selection):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    open_manual(page)
    page.get_by_title("Deep research", exact=True).click()
    message_box(page).fill("Read https://example.test/report")
    page.get_by_title("Read URLs", exact=True).click()
    if previous_selection == "previous_message":
        with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
            send_button(page).click()
        assert api.plans[-1]["required_capabilities"] == ["deep_research", "url_fetch"]
        page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    elif previous_selection == "capability_disabled":
        api.bootstrap["features"]["enable_url_access"] = False
        page.evaluate("() => window.OrchHarness.stores.bootstrap.useBootstrapStore.getState().refresh()")
        expect(page.get_by_role("status").filter(has_text="still be sent for server validation")).to_be_visible()
    message_box(page).fill("Research another topic without an explicit link.")
    expect(page.get_by_title("Read URLs", exact=True)).to_have_count(0)
    expect(page.get_by_role("status").filter(has_text="selected retrieval requirement is no longer available")).to_have_count(0)
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        message_box(page).press("Enter")
    assert api.plans[-1]["required_capabilities"] == ["deep_research"]
    assert api.plans[-1]["web_search_enabled"] is False


def test_url_selection_uses_the_resolved_attached_prompt_not_only_typed_text(approval_ui):
    open_page, api = approval_ui
    configure(api)
    api.bootstrap["catalogs"]["prompts"] = [{
        "id": "url-prompt", "name": "URL prompt", "content": "Read https://example.test/prompt",
        "scope_type": "personal",
    }]
    page = open_page()
    mount(page, api)
    open_manual(page)
    page.get_by_role("button", name="Prompt", exact=True).click()
    page.get_by_role("option", name="URL prompt", exact=True).click()
    page.get_by_title("Read URLs", exact=True).click()
    message_box(page).fill("Summarize that source.")
    expect(page.get_by_title("Read URLs", exact=True)).to_have_attribute("aria-pressed", "true")
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        send_button(page).click()
    assert api.plans[-1]["required_capabilities"] == ["url_fetch"]
    assert "https://example.test/prompt" in api.plans[-1]["message"]


def test_deep_research_respects_availability_and_role_projection(approval_ui):
    open_page, api = approval_ui
    configure(api)
    api.bootstrap["features"]["enable_source_review"] = False
    page = open_page()
    mount(page, api)
    open_manual(page)
    expect(page.get_by_title("Deep research", exact=True)).to_have_count(0)


def test_crawl_depth_setting_does_not_disable_the_authorized_research_operation(approval_ui):
    open_page, api = approval_ui
    configure(api)
    api.bootstrap["features"]["enable_deep_source_review"] = False
    page = open_page()
    mount(page, api)
    open_manual(page)
    expect(page.get_by_title("Deep research", exact=True)).to_be_enabled()


def test_availability_refresh_does_not_silently_drop_a_selected_requirement(approval_ui):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    open_manual(page)
    page.get_by_title("Deep research", exact=True).click()
    api.bootstrap["features"]["enable_source_review"] = False
    page.evaluate("() => window.OrchHarness.stores.bootstrap.useBootstrapStore.getState().refresh()")
    expect(page.get_by_role("status").filter(has_text="still be sent for server validation")).to_be_visible()
    message_box(page).fill("Research this.")
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        send_button(page).click()
    assert api.plans[-1]["required_capabilities"] == ["deep_research"]


def test_saved_plan_and_backend_default_notices_are_safe_and_do_not_make_revisions(approval_ui):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        const store = H.stores.orchestration.useOrchestrationStore.getState();
        store.setPlan('approval-chat', 'saved-turn', {
            plan_id: 'saved-plan', run_id: 'saved-run', turn_id: 'saved-turn', revision: 4,
            conversation_id: 'approval-chat',
            intent: { summary: 'Saved plan', complexity: 'simple' },
            approval: { mode: 'manual', state: 'pending', timeout_seconds: 0 },
            status: 'awaiting_approval', steps: [{step_id: 'answer', capability_id: 'respond'}],
            reasoning_adjustments: [{
                requested_effort: 'minimal', effective_effort: null, mode: 'model_default',
                adjustment_reason: '<img src=x onerror=alert(1)>', stage: 'planner',
                model_name: '<b>Luna</b>',
            }],
        });
        H.mount('mount-b', 'OrchestrationPlanCard', {conversationId: 'approval-chat', turnId: 'saved-turn'});
    }""")
    notice = page.locator("#mount-b").get_by_role("status")
    expect(notice).to_contain_text("Planner: Minimal could not be used for <b>Luna</b>; using Model default.")
    expect(notice.locator("b, img, script")).to_have_count(0)
    assert page.evaluate("() => window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().plans['approval-chat\\u0000saved-turn'].revision") == 4
    assert api.plans == []


@pytest.mark.parametrize("terminal_kind,terminal_adjustment,clear_source", [
    ("done", False, None), ("done", True, None), ("cancelled", False, None),
    ("done", False, "thought"), ("done", False, "top_level"),
    ("done", False, "metadata"), ("cancelled", False, "metadata"),
])
def test_ordinary_thought_corrections_are_live_latest_and_preserved_at_completion(
    approval_ui, terminal_kind, terminal_adjustment, clear_source,
):
    open_page, api = approval_ui
    configure(api, orchestrating=False)
    page = open_page()
    mount(page, api)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.mount('mount-b', 'MessageList');
        const originalFetch = window.fetch;
        window.fetch = (url, options) => {
            if (!String(url).endsWith('/api/chat/stream')) return originalFetch(url, options);
            const stream = new ReadableStream({
                start(controller) {
                    window.emitOrdinaryReasoningEvent = (event) => {
                        controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\\n\\n`));
                        if (event.done) controller.close();
                    };
                },
            });
            return Promise.resolve(new Response(stream, {headers: {'Content-Type': 'text/event-stream'}}));
        };
    }""")
    message_box(page).fill("Answer this request.")
    send_button(page).click()
    page.wait_for_function("() => Boolean(window.emitOrdinaryReasoningEvent)")
    first = {
        "requested_effort": "minimal", "effective_effort": "low", "mode": "explicit",
        "adjustment_reason": "reasoning_effort_unsupported",
        "model_name": "gpt-5.6-luna", "stage": "answer",
    }
    thought = {
        "type": "thought", "step_type": "generation", "content": "Adjusting reasoning.",
        "reasoning_adjustments": [first],
    }
    page.evaluate("(event) => window.emitOrdinaryReasoningEvent(event)", thought)
    notice = page.locator("#mount-b").get_by_role("status").filter(has_text="Minimal could not be used")
    expect(notice).to_have_count(1)
    expect(notice).to_contain_text("using Low")
    assert page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().streamingContent") == ""
    page.evaluate("(event) => window.emitOrdinaryReasoningEvent(event)", thought)
    latest = {
        **first, "effective_effort": None, "mode": "model_default",
        "adjustment_reason": "<img src=x onerror=alert(1)>",
    }
    page.evaluate("(event) => window.emitOrdinaryReasoningEvent(event)", {
        "type": "thought", "step_type": "generation", "reasoning_adjustments": [latest],
    })
    expect(notice).to_have_count(1)
    expect(notice).to_contain_text("using Model default")
    expect(notice.locator("img, script")).to_have_count(0)
    assert page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().thoughts.length") == 2
    cleared = {
        **first, "requested_effort": "low", "adjustment_reason": None,
    }
    if clear_source == "thought":
        page.evaluate("(event) => window.emitOrdinaryReasoningEvent(event)", {
            "type": "thought", "step_type": "generation", "reasoning_adjustments": [cleared],
        })
        expect(notice).to_have_count(0)
        assert page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().thoughts.length") == 2
    page.evaluate("(event) => window.emitOrdinaryReasoningEvent(event)", {"content": "A useful answer."})
    expect(page.locator("#mount-b").get_by_text("A useful answer.", exact=True)).to_be_visible()
    terminal = {
        "done": True, "cancelled": terminal_kind == "cancelled", "message_id": "ordinary-answer",
        "reasoning_effort": None, "requested_reasoning_effort": "minimal", "reasoning_mode": "model_default",
        "metadata": {"fixture_marker": "preserved"},
    }
    if terminal_adjustment:
        terminal["reasoning_adjustments"] = [latest]
    if clear_source:
        terminal.update(reasoning_effort="low", requested_reasoning_effort="low", reasoning_mode="explicit")
        if clear_source == "top_level":
            terminal["reasoning_adjustments"] = [cleared]
        elif clear_source == "metadata":
            terminal["metadata"]["reasoning_adjustments"] = [cleared]
    page.evaluate("(event) => window.emitOrdinaryReasoningEvent(event)", terminal)
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    expect(notice).to_have_count(0 if clear_source else 1)
    if not clear_source:
        expect(notice).to_contain_text("using Model default")
    result = page.evaluate("""() => {
        const state = window.OrchHarness.stores.chat.useChatStore.getState();
        return {metadata: state.messages.find((message) => message.role === 'assistant').metadata,
            live: state.streamingReasoningAdjustments};
    }""")
    assert result["metadata"].get("reasoning_adjustments", []) == ([] if clear_source else [latest])
    assert result["metadata"]["reasoning_effort"] == ("low" if clear_source else None)
    assert result["metadata"]["requested_reasoning_effort"] == ("low" if clear_source else "minimal")
    assert result["metadata"]["reasoning_mode"] == ("explicit" if clear_source else "model_default")
    assert result["metadata"]["fixture_marker"] == "preserved"
    assert result["live"] == []


def test_documents_prompt_and_agent_survive_positive_seeds_without_model_override(approval_ui):
    open_page, api = approval_ui
    configure(api)
    api.bootstrap["catalogs"]["agents"] = [{
        "id": "selected-agent", "name": "Helper", "display_name": "Helper",
        "scope_type": "global",
    }]
    api.bootstrap["catalogs"]["prompts"] = [{
        "id": "selected-prompt", "name": "Brief answer", "content": "Keep the answer brief.",
        "scope_type": "personal",
    }]
    page = open_page()
    mount(page, api)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.unmount('mount-a');
        H.mount('mount-a', 'Composer', {}, {initialEntries: [{
            pathname: '/chat',
            search: '?document_ids=selected-doc&doc_scope=personal',
            state: {contextDocuments: [{
                document: {id: 'selected-doc', file_name: 'Report.pdf'},
                scope: {kind: 'personal', id: null, name: 'My workspace'},
            }]},
        }]});
    }""")
    open_manual(page)
    page.get_by_role("button", name="Agent", exact=True).click()
    page.get_by_role("option", name="Helper", exact=True).click()
    page.get_by_role("button", name="Prompt", exact=True).click()
    page.get_by_role("option", name="Brief answer", exact=True).click()
    page.get_by_title("Web", exact=True).click()
    message_box(page).fill("Read this document.")
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        send_button(page).click()
    request = api.plans[-1]
    assert request["required_capabilities"] == ["document_search", "web_search"]
    assert request["selected_document_ids"] == ["selected-doc"]
    assert request["agent_info"]["id"] == "selected-agent"
    assert request["prompt_info"]["id"] == "selected-prompt"
    assert not any(key in request for key in ("model_id", "model_endpoint_id", "reasoning_effort"))


def test_real_chat_completion_displays_backend_omission_instead_of_claiming_low(approval_ui):
    open_page, api = approval_ui
    configure(api, orchestrating=False)
    api.settings["reasoningEffortSettings"]["luna-uuid"] = "low"
    page = open_page()

    def complete(route):
        api.chats.append(route.request.post_data_json)
        events = [
            {"content": "Completed answer."},
            {
                "done": True, "message_id": "answer-with-adjustment",
                "reasoning_adjustments": [{
                    "requested_effort": "low", "effective_effort": None,
                    "mode": "model_default", "adjustment_reason": "provider_rejected",
                    "stage": "answer", "model_name": "gpt-5.6-luna",
                }],
                "metadata": {"reasoning_effort": None, "reasoning_mode": "model_default"},
            },
        ]
        route.fulfill(content_type="text/event-stream", body="".join(f"data: {json.dumps(event)}\n\n" for event in events))

    page.route("**/api/chat/stream", complete)
    mount(page, api)
    message_box(page).fill("Hello")
    with page.expect_response(lambda response: urlsplit(response.url).path == CHAT_PATH):
        send_button(page).click()
    page.evaluate("() => window.OrchHarness.mount('mount-b', 'MessageList', {})")
    expect(page.locator("#mount-b").get_by_role("status").filter(has_text="using Model default")).to_be_visible()
    assert api.chats[-1]["reasoning_effort"] == "low"


def test_run_thought_corrections_appear_before_completion_and_latest_stage_wins(approval_ui):
    open_page, api = approval_ui
    configure(api)
    api.settings["reasoningEffortSettings"]["luna-uuid"] = "low"
    page = open_page()
    mount(page, api)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.stores.orchestration.useOrchestrationStore.getState().setPlan('approval-chat', 'live-turn', {
            plan_id: 'live-plan', run_id: 'live-run', turn_id: 'live-turn',
            conversation_id: 'approval-chat', revision: 4, edit_version: 'unchanged-v4',
            intent: { summary: 'Saved plan', complexity: 'simple' },
            approval: { mode: 'manual', state: 'pending', timeout_seconds: 0 },
            status: 'awaiting_approval',
            steps: [{step_id: 'answer', capability_id: 'respond', title: 'Answer'}],
            reasoning_adjustments: [{
                requested_effort: 'minimal', effective_effort: 'low', mode: 'explicit',
                adjustment_reason: 'unsupported_effort', stage: 'planner', model_name: 'gpt-5.6-luna',
            }],
        });
        const store = H.stores.orchestration.useOrchestrationStore.getState();
        store.adoptPlanEditor('approval-chat', 'live-turn', {
            plan: store.plans['approval-chat\\u0000live-turn'], version: 'unchanged-v4',
            edits: {disabled_step_ids: [], removed_document_ids: {}},
            chat: [], history: [], next_before_revision: null, pending: null, busy: false,
        });
        H.mount('mount-b', 'OrchestrationPlanCard', {conversationId: 'approval-chat', turnId: 'live-turn'});
        const originalFetch = window.fetch;
        window.fetch = (url, options) => {
            if (!String(url).endsWith('/api/v2/orchestration/run')) return originalFetch(url, options);
            const stream = new ReadableStream({
                start(controller) {
                    window.emitReasoningRunEvent = (event) => {
                        controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\\n\\n`));
                        if (event.done) controller.close();
                    };
                },
            });
            return Promise.resolve(new Response(stream, {headers: {'Content-Type': 'text/event-stream'}}));
        };
        void H.controller.approveAndRunPlan({conversationId: 'approval-chat', turnId: 'live-turn'});
    }""")
    page.wait_for_function("() => Boolean(window.emitReasoningRunEvent)")
    correction = {
        "type": "thought", "step_type": "orchestration_planning", "status": "info",
        "reasoning_adjustments": [{
            "requested_effort": "minimal", "effective_effort": None, "mode": "model_default",
            "adjustment_reason": "provider_rejected", "stage": "planner", "model_name": "gpt-5.6-luna",
        }],
    }
    page.evaluate("(event) => window.emitReasoningRunEvent(event)", correction)
    notice = page.locator("#mount-b").get_by_role("status")
    expect(notice).to_contain_text("Planner: Minimal could not be used for gpt-5.6-luna; using Model default.")
    expect(notice).not_to_contain_text("using Low")
    assert page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    correction["reasoning_adjustments"][0].update(stage="answer", effective_effort="low", mode="explicit")
    page.evaluate("(event) => window.emitReasoningRunEvent(event)", correction)
    page.evaluate("(event) => window.emitReasoningRunEvent(event)", correction)
    expect(notice.locator("p")).to_have_count(2)
    expect(notice).to_contain_text("Answer: Minimal could not be used for gpt-5.6-luna; using Low.")
    plan = page.evaluate("() => window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().plans['approval-chat\\u0000live-turn']")
    assert plan["revision"] == 4 and plan["edit_version"] == "unchanged-v4"
    assert len(plan["reasoning_adjustments"]) == 2
    page.evaluate("""() => window.emitReasoningRunEvent({
        done: true, message_id: 'completed-answer',
        reasoning_effort: null, requested_reasoning_effort: 'minimal',
        reasoning_mode: 'model_default',
    })""")
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    metadata = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().messages.find((message) => message.id === 'completed-answer').metadata")
    assert metadata["reasoning_effort"] is None and metadata["reasoning_mode"] == "model_default"
    assert metadata["requested_reasoning_effort"] == "minimal"
    assert api.plans == []


@pytest.mark.parametrize("original_requirements", [[], ["deep_research"], ["agent_invoke"]])
def test_hydration_does_not_promote_model_selected_retrieval_to_manual_requirements(
    approval_ui, original_requirements,
):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    summary = {
        "run_id": "hydrated-run", "conversation_id": "approval-chat", "turn_id": "hydrated-turn",
        "status": "awaiting_approval", "user_message_id": "saved-question",
        "created_at": "2026-09-07T12:00:00Z",
        "plan_summary": {
            "plan_id": "hydrated-plan", "run_id": "hydrated-run", "turn_id": "hydrated-turn",
            "status": "awaiting_approval", "intent_summary": "Research chosen by the model", "step_count": 3,
        },
    }
    original_seeds = {"required_capabilities": original_requirements, "web_search_enabled": False}
    plan = {
        "plan_id": "hydrated-plan", "run_id": "hydrated-run", "turn_id": "hydrated-turn",
        "conversation_id": "approval-chat", "revision": 2,
        "intent": {"summary": "Research chosen by the model", "complexity": "complex"},
        "inputs": {"web": True, "documents": [], "required_capabilities": original_requirements},
        "steps": [
            {"step_id": "web", "capability_id": "web_search", "title": "Search"},
            {"step_id": "deep", "capability_id": "deep_research", "title": "Read sources"},
            {"step_id": "answer", "capability_id": "respond", "title": "Answer"},
        ],
        "approval": {"mode": "manual", "state": "pending", "timeout_seconds": 0},
        "status": "awaiting_approval",
    }
    run_requests = []
    page.route("**/api/v2/orchestration/runs?*", lambda route: route.fulfill(json={"runs": [summary]}))
    page.route("**/api/v2/orchestration/runs/hydrated-run?*", lambda route: route.fulfill(
        json={"run": {**summary, "plan": plan, "seeds": original_seeds}},
    ))
    page.route("**/api/v2/orchestration/runs/hydrated-run/steps?*", lambda route: route.fulfill(json={"steps": []}))

    def complete(route):
        run_requests.append(route.request.post_data_json)
        route.fulfill(content_type="text/event-stream", body='data: {"done":true,"message_id":"hydrated-answer"}\n\n')

    page.route("**/api/v2/orchestration/run", complete)
    page.evaluate("""async () => {
        const H = window.OrchHarness;
        H.stores.chat.useChatStore.setState({
            messages: [{id: 'saved-question', role: 'user', content: 'Find suitable information.'}],
        });
        await H.resume.resumeOrchestrationForConversation('approval-chat');
        H.mount('mount-b', 'OrchestrationPlanCard', {conversationId: 'approval-chat', turnId: 'hydrated-turn'});
    }""")
    expect(page.locator("#mount-b")).to_contain_text("Research chosen by the model")
    restored_requirements = page.evaluate("""() => {
        const H = window.OrchHarness;
        const plan = H.stores.orchestration.useOrchestrationStore.getState().plans['approval-chat\\u0000hydrated-turn'];
        const narrowed = H.plan.applyPlanEdits(plan, {disabled_step_ids: ['web'], removed_document_ids: {}});
        return {restored: plan.inputs.required_capabilities, narrowed: narrowed.inputs.required_capabilities};
    }""")
    assert restored_requirements == {"restored": original_requirements, "narrowed": original_requirements}
    open_manual(page)
    expect(page.get_by_title("Web", exact=True)).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_title("Deep research", exact=True)).to_have_attribute("aria-pressed", "false")
    assert api.plans == [] and run_requests == []
    with page.expect_response(lambda response: urlsplit(response.url).path == "/api/v2/orchestration/run"):
        page.evaluate("() => { void window.OrchHarness.controller.approveAndRunPlan({conversationId: 'approval-chat', turnId: 'hydrated-turn'}); }")
    request = run_requests[-1]
    assert request["run_id"] == "hydrated-run" and request["plan_id"] == "hydrated-plan"
    # The server uses the saved original selections under this run identity. The client must
    # not replace them with flags inferred from inputs.web or model-authored retrieval steps.
    assert not any(key in request for key in ("seeds", "required_capabilities", "web_search_enabled", "selected_document_ids"))
    assert original_seeds == {"required_capabilities": original_requirements, "web_search_enabled": False}
    assert api.plans == []


def test_implicit_selected_documents_keep_user_provenance_without_widening_step_arguments(approval_ui):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        const plan = H.plan.normalizePlan({
            plan_id: 'implicit-plan', run_id: 'implicit-run', turn_id: 'implicit-turn',
            intent: {summary: 'Selected documents', complexity: 'simple'},
            inputs: {
                required_capabilities: ['document_search'], web: false,
                documents: [
                    {document_id: 'selected-doc', display_name: 'Original report.pdf', selected_by_user: true},
                    {document_id: 'other-selected-doc', display_name: 'Second report.pdf', selected_by_user: true},
                    {document_id: 'model-doc', display_name: 'Model choice.pdf', selected_by_user: false},
                ],
            },
            steps: [{step_id: 'docs', capability_id: 'document_search', arguments: {query: 'Summarize'}},
                {step_id: 'answer', capability_id: 'respond'}],
            approval: {mode: 'manual', state: 'pending'}, status: 'awaiting_approval',
        });
        window.implicitDocumentPlan = plan;
        H.mount('mount-b', 'OrchestrationRunView', {conversationId: 'approval-chat', turnId: 'implicit-turn', previewPlan: plan});
    }""")
    view = page.locator("#mount-b")
    expect(view.get_by_text("Original report.pdf", exact=True)).to_be_visible()
    expect(view.get_by_text("Second report.pdf", exact=True)).to_be_visible()
    expect(view.get_by_text("Model choice.pdf", exact=True)).to_have_count(0)
    expect(view.get_by_text("yours", exact=True)).to_have_count(2)
    assert page.evaluate("() => window.implicitDocumentPlan.steps[0].arguments") == {"query": "Summarize"}
    page.evaluate("""() => {
        const H = window.OrchHarness;
        const plan = window.implicitDocumentPlan;
        H.mount('mount-b', 'OrchestrationRunView', {
            conversationId: 'approval-chat', turnId: 'implicit-turn',
            previewPlan: {...plan, steps: [{...plan.steps[0], arguments: {document_ids: ['selected-doc']}}, plan.steps[1]]},
        });
    }""")
    expect(view.get_by_text("Original report.pdf", exact=True)).to_be_visible()
    expect(view.get_by_text("Second report.pdf", exact=True)).to_have_count(0)
