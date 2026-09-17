# test_v2_orchestration_planning_retry.py
"""
Browser regressions for failed, unpersisted orchestration planning turns.
Version: 0.261.113
Implemented in: 0.261.113

The production controller, stores, SSE reader, message actions, and composer run
with production CSS. Only HTTP responses are deterministic. No live model,
deployment, source permission, or workspace content is changed.
"""

import copy
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
CONVERSATION = "planning-retry-chat"
PLAN = "/api/v2/orchestration/plan"
PROMPT = (
    "Use Analyze on the three selected documents. Explain the main risks in these "
    "documents. Include source references and a concise table. Do not invent scores. "
    "Also provide Markdown and CSV outputs."
)
FAILURE = "The request could not be planned. Please retry."
SEEDS = {
    "selected_document_ids": ["supplier", "terms", "governance"],
    "context_documents": [
        {"document_id": name, "file_name": f"{name}.txt"}
        for name in ("supplier", "terms", "governance")
    ],
    "doc_scope": "group",
    "active_group_id": "isolated-analysis-group",
    "model_deployment": "gpt-4o",
    "model_endpoint_id": "original-model-endpoint",
    "required_capabilities": [],
    "prompt_info": {"id": "risk-prompt", "name": "Risk review", "content": PROMPT},
}


class PlanningApi:
    def __init__(self, assets):
        self.assets = assets
        self.mode = "failure"
        self.requests = []
        self.pending = []
        self.errors = []
        self.messages = []
        self.conversations = []

    def answer(self, route, body, mode):
        if mode == "http":
            route.fulfill(status=503, json={"error": "Planning is temporarily unavailable."})
            return
        plan = editor_tests.make_plan(body["conversation_id"], body["turn_id"])
        events = {
            "failure": {"error": FAILURE, "done": True},
            "missing": {"type": "orchestration_plan", "done": True},
            "malformed": {"type": "orchestration_plan", "plan": "not a plan", "done": True},
            "plan": {"type": "orchestration_plan", "plan": plan, "done": True},
        }
        event = events.get(mode, {"type": "thought", "content": "Planning the review."})
        route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        body = request.post_data_json if request.post_data else None
        self.requests.append({"path": path, "method": request.method, "body": copy.deepcopy(body)})
        if path == PLAN:
            if self.mode == "held":
                self.pending.append((route, body))
            else:
                self.answer(route, body, self.mode)
            return
        if path.startswith("/api/message/") and path.endswith("/retry"):
            if "pending-user-" in path:
                route.fulfill(status=404, json={"error": "Message not found."})
            else:
                route.fulfill(json={"chat_request": {
                    "conversation_id": CONVERSATION, "message": "Ordinary persisted message",
                }})
            return
        if path == "/api/chat/stream":
            self.messages.append({
                "id": "ordinary-answer", "conversation_id": CONVERSATION,
                "role": "assistant", "content": "Ordinary retry answer.",
            })
            event = {
                "done": True, "conversation_id": CONVERSATION,
                "message_id": "ordinary-answer", "full_content": "Ordinary retry answer.",
            }
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")
            return
        if path == "/api/get_messages":
            route.fulfill(json={"messages": self.messages})
            return
        if path in ("/api/get_conversations", "/api/conversations/feed"):
            route.fulfill(json={"conversations": self.conversations, "has_more": False})
            return
        if path == "/api/user/settings":
            route.fulfill(json={"settings": {}})
            return
        if path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
            return
        if path == "/api/collaboration/file-approvals":
            route.fulfill(json={"approvals": []})
            return
        if path == "/api/user/collaboration-suggestions":
            route.fulfill(json={"results": []})
            return
        if path == f"/api/conversations/{CONVERSATION}/metadata":
            route.fulfill(json={
                "conversation_id": CONVERSATION, "title": "Three document review",
                "used_documents": [
                    {"document_id": name, "file_name": name * 80 + ".txt"}
                    for name in ("Supplier", "Terms", "Governance")
                ],
            })
            return
        if request.method == "DELETE" and CONVERSATION in path:
            route.fulfill(json={"success": True})
            return
        self.errors.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test request."})

    def calls(self, path):
        return [request for request in self.requests if request["path"] == path]

    def release(self, mode="plan"):
        pending, self.pending = self.pending, []
        for route, body in pending:
            self.answer(route, body, mode)


@pytest.fixture
def planning_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    api = PlanningApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        mount(page, api)
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def mount(page, api, messages=None):
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(
        """({conversation, messages}) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                features: {enable_chat_orchestration: true},
                settings: {}, user: {id: 'tester', display_name: 'Tester'},
                catalogs: {models: [], agents: [], prompts: []},
                scope: {groups: [], public_workspaces: []},
                orchestration: {enabled: true, capabilities: [], default_approval_mode: 'manual'},
            }});
            H.stores.chat.useChatStore.setState({
                activeConversationId: conversation, activeConversationKind: 'personal',
                messages, messagesLoading: false, streaming: false, streamError: null,
                streamingContent: '', thoughts: [],
                conversations: [{id: conversation, title: 'Three document review'}],
            });
            H.mount('mount-a', 'PromptExperience');
        }""",
        {"conversation": CONVERSATION, "messages": messages or []},
    )


def start_failed_plan(page, api, seeds=None):
    page.evaluate(
        """(spec) => {
            window.originalPlanningSeeds = spec.seeds;
            void window.OrchHarness.controller.startOrchestrationPlan(spec);
        }""",
        {"conversationId": CONVERSATION, "message": PROMPT, "approvalMode": "manual",
         "seeds": seeds if seeds is not None else SEEDS},
    )
    page.wait_for_function("() => Boolean(window.OrchHarness.stores.chat.useChatStore.getState().streamError)")
    assert len(api.calls(PLAN)) == 1
    return page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().messages[0]")


@pytest.mark.parametrize("failure", ["failure", "http", "missing", "malformed", "truncated"])
def test_failed_planning_retry_reuses_exact_context_without_a_second_bubble(planning_ui, failure):
    page, api = planning_ui
    api.mode = failure
    original = start_failed_plan(page, api)
    page.evaluate("""() => {
        window.originalPlanningSeeds.selected_document_ids.push('unrelated-document');
        window.originalPlanningSeeds.context_documents[0].file_name = 'changed.txt';
        window.originalPlanningSeeds.model_deployment = 'different-model';
    }""")
    api.mode = "plan"
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
    assert len(api.calls(PLAN)) == 2
    assert api.calls(PLAN)[0]["body"] == api.calls(PLAN)[1]["body"]
    state = page.evaluate("""() => {
        const S = window.OrchHarness.stores.chat.useChatStore.getState();
        return {messages: S.messages, error: S.streamError, streaming: S.streaming};
    }""")
    assert state["messages"] == [original]
    assert state["error"] is None and not state["streaming"]
    assert not any(request["path"].endswith("/retry") for request in api.requests)
    assert not api.calls(editor_tests.RUN)


def test_repeated_retry_clicks_share_one_request_and_stop_discards_late_plan(planning_ui):
    page, api = planning_ui
    original = start_failed_plan(page, api)
    api.mode = "held"
    with page.expect_request(lambda request: urlsplit(request.url).path == PLAN):
        page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Retry", exact=True)).to_be_disabled()
    page.evaluate(
        "(id) => window.OrchHarness.stores.chat.useChatStore.getState().retryMessage(id)", original["id"],
    )
    assert len(api.calls(PLAN)) == 2
    page.evaluate("(id) => window.OrchHarness.controller.cancelOrchestration(id)", CONVERSATION)
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    api.release()
    assert page.evaluate("Object.keys(window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().plans)") == []
    assert page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().messages") == [original]
    assert not api.calls(editor_tests.RUN)


def test_failed_planning_retry_keeps_the_original_group_agent(planning_ui):
    page, api = planning_ui
    seeds = copy.deepcopy(SEEDS)
    seeds.pop("model_deployment")
    seeds.pop("model_endpoint_id")
    seeds["agent_info"] = {"id": "group-agent", "name": "risk-reviewer", "is_group": True, "group_id": "original-group"}
    start_failed_plan(page, api, seeds)
    page.evaluate("window.originalPlanningSeeds.agent_info.group_id = 'different-group'")
    api.mode = "plan"
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
    assert api.calls(PLAN)[0]["body"] == api.calls(PLAN)[1]["body"]
    assert api.calls(PLAN)[1]["body"]["agent_info"] == seeds["agent_info"]
    assert "model_deployment" not in api.calls(PLAN)[1]["body"]


def test_retry_does_not_replace_an_existing_plan_or_execute_it(planning_ui):
    page, api = planning_ui
    start_failed_plan(page, api)
    api.mode = "plan"
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_text("This request already has a plan.", exact=False)).to_be_visible()
    assert len(api.calls(PLAN)) == 2
    assert not api.calls(editor_tests.RUN)
    assert not any(request["path"].endswith("/retry") for request in api.requests)


@pytest.mark.parametrize("action", ["navigate", "delete"])
def test_late_retry_does_not_write_into_a_new_or_deleted_conversation(planning_ui, action):
    page, api = planning_ui
    start_failed_plan(page, api)
    api.mode = "held"
    with page.expect_request(lambda request: urlsplit(request.url).path == PLAN):
        page.get_by_role("button", name="Retry", exact=True).click()
    page.evaluate(
        """({action, conversation}) => {
            const S = window.OrchHarness.stores.chat.useChatStore.getState();
            return action === 'delete' ? S.removeConversation(conversation) : S.startNewConversation();
        }""",
        {"action": action, "conversation": CONVERSATION},
    )
    api.release()
    page.wait_for_function("() => !window.OrchHarness.controller.hasActiveOrchestration('planning-retry-chat')")
    state = page.evaluate("""() => {
        const H = window.OrchHarness;
        const S = H.stores.chat.useChatStore.getState();
        return {id: S.activeConversationId, messages: S.messages, error: S.streamError,
            plans: H.stores.orchestration.useOrchestrationStore.getState().plans};
    }""")
    assert state["id"] is None and state["messages"] == [] and state["error"] is None
    if action == "delete":
        assert state["plans"] == {}
    assert not api.calls(editor_tests.RUN)


def test_lost_planning_context_requires_deliberate_recovery_not_message_retry(planning_ui):
    page, api = planning_ui
    original = start_failed_plan(page, api)
    mount(page, api, [original])
    api.requests.clear()
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_text("Copy the original message to the composer", exact=False)).to_be_visible()
    assert not api.calls(PLAN)
    assert not any(request["path"].endswith("/retry") for request in api.requests)


def test_ordinary_persisted_message_retry_still_uses_message_api(planning_ui):
    page, api = planning_ui
    api.messages = [{
        "id": "persisted-user", "conversation_id": CONVERSATION,
        "role": "user", "content": "Ordinary persisted message",
    }]
    mount(page, api, api.messages)
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_text("Ordinary retry answer.", exact=True)).to_be_visible()
    assert len(api.calls("/api/message/persisted-user/retry")) == 1
    assert not api.calls(PLAN)


@pytest.mark.parametrize("width", [390, 1280])
def test_analysis_shell_responsive_navigation_does_not_widen_the_page(planning_ui, width):
    page, api = planning_ui
    page.set_viewport_size({"width": width, "height": 844})
    page.evaluate(
        """(conversation) => {
            const H = window.OrchHarness;
            H.stores.chat.useChatStore.setState({messages: [{
                id: 'analysis-layout', conversation_id: conversation, role: 'assistant',
                content: 'Northstar is the sole supplier. Maya Chen owns quarterly reviews.\\n\\n'
                    + '| Source | Finding |\\n| --- | --- |\\n'
                    + '| Supplier | No qualified alternative |\\n'
                    + '| Terms | USD 10,000 convenience termination fee; dates unstated |',
                metadata: {generated_analysis_artifacts: [{
                    artifact_message_id: 'artifact-layout', conversation_id: conversation,
                    capability: 'analyze', storage_scope: 'chat', output_format: 'csv',
                    file_name: 'Supplier_very_long_name_'.repeat(18) + '.csv',
                    preview_rows: [{source: 'Supplier', finding: 'No qualified alternative'}],
                }]},
            }]});
            H.unmount('mount-a');
            H.mount('mount-a', 'ChatExperience', {}, {initialEntries: ['/chat']});
        }""",
        CONVERSATION,
    )
    expect(page.get_by_role("navigation", name="Primary")).to_be_visible()
    expand = page.get_by_role("button", name="Expand navigation", exact=True)
    if expand.is_visible():
        expand.click()
    expect(page.get_by_role("button", name="Collapse navigation", exact=True)).to_be_visible()
    dimensions = page.evaluate("({viewport: innerWidth, document: document.documentElement.scrollWidth})")
    assert dimensions["document"] <= width + 1, dimensions
    page.get_by_role("button", name="Collapse navigation", exact=True).click()
    button = page.get_by_role("button", name="Download CSV", exact=True)
    button.scroll_into_view_if_needed()
    box = button.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    page.get_by_role("button", name="Open used documents", exact=True).click()
    expect(page.get_by_role("complementary", name="Conversation details")).to_be_visible()
    expect(page.get_by_role("button", name="Close panel", exact=True)).to_be_in_viewport()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    page.get_by_role("button", name="Close panel", exact=True).click()
    if width == 390:
        expand = page.get_by_role("button", name="Expand navigation", exact=True)
        expand.focus()
        expand.press("Enter")
        expect(page.get_by_role("button", name="Collapse navigation", exact=True)).to_be_focused()
        assert page.evaluate("document.querySelector('nav[aria-label=\"Primary\"]').parentElement.querySelector('main').inert")
        page.keyboard.press("Escape")
        expect(expand).to_be_focused()
        assert not page.evaluate("document.querySelector('nav[aria-label=\"Primary\"]').parentElement.querySelector('main').inert")
        expand.click()
        page.get_by_role("button", name="Close navigation", exact=True).click(position={"x": width - 10, "y": 100})
        expect(expand).to_be_visible()
        assert not [
            call for call in api.calls("/api/user/settings")
            if call["method"] != "GET" and "v2RailCollapsed" in json.dumps(call["body"])
        ]
        page.set_viewport_size({"width": 1280, "height": 844})
        expect(page.get_by_role("button", name="Collapse navigation", exact=True)).to_be_visible()


def test_mobile_share_dialog_does_not_remain_inside_inert_chat(planning_ui):
    page, api = planning_ui
    page.set_viewport_size({"width": 390, "height": 844})
    api.conversations = [{"id": CONVERSATION, "title": "Shared review", "user_id": "tester", "chat_type": "personal_single_user"}]
    page.evaluate("""(conversations) => {
        const H = window.OrchHarness;
        H.stores.bootstrap.useBootstrapStore.setState(state => ({data: {
            ...state.data, features: {...state.data.features, enable_collaborative_conversations: true},
        }}));
        H.stores.chat.useChatStore.setState({conversations});
        H.unmount('mount-a');
        H.mount('mount-a', 'ChatExperience', {}, {initialEntries: ['/chat']});
    }""", api.conversations)
    page.get_by_role("button", name="Expand navigation", exact=True).click()
    page.get_by_role("button", name="Actions for Shared review", exact=True).click()
    page.get_by_role("button", name="Share", exact=True).click()
    panel = page.get_by_role("dialog", name="Conversation participants")
    expect(panel).to_be_visible()
    expect(page.get_by_role("button", name="Expand navigation", exact=True)).to_be_visible()
    search = panel.get_by_role("searchbox", name="Search for people to add")
    search.focus()
    expect(search).to_be_focused()
    panel.get_by_role("button", name="Close participants", exact=True).click()
    expect(panel).not_to_be_visible()
