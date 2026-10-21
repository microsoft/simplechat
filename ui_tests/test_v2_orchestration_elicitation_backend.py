# test_v2_orchestration_elicitation_backend.py
"""
Browser-to-Flask regression for self-contained clarification continuation.
Version: 0.261.365
Implemented in: 0.261.365

The real card, controller, resolver, planner, routes and persistence run unchanged.
Only external model, storage and source-discovery I/O is deterministic. The browser
must reach a saved manual-review plan after answering, while a genuinely necessary
second question remains answerable. No live application or model is contacted.
The existing browser fixture supports local Chromium and configured Azure Playwright.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_orchestration_elicitation_routes import (  # noqa: F401
    empty_history_runtime, input_question, modules as offline_modules, plan_doc, real_http_harness,
)
from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS, ORIGIN, connect_options, editor_assets, editor_browser,
)
from v2_pending_action_stubs import is_pending_actions_list, pending_actions_payload


pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def modules():
    # The backend owns an asyncio loop; do not close it inside Playwright's running loop.
    with ThreadPoolExecutor(max_workers=1) as worker:
        fixture = offline_modules.__wrapped__()
        backend = worker.submit(next, fixture).result()
        try:
            yield backend
        finally:
            worker.submit(next, fixture, None).result()


@pytest.fixture
def clarification_ui(empty_history_runtime, editor_browser, editor_assets):
    runtime = empty_history_runtime
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors, requests = [], []

    def forward(route):
        request = route.request
        url = urlsplit(request.url)
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            errors.append(f"Unexpected browser origin: {request.url}")
            route.abort()
            return
        if request.method == "GET" and url.path in editor_assets:
            route.fulfill(path=str(editor_assets[url.path]))
            return
        if url.path == "/favicon.ico":
            route.fulfill(status=204)
            return
        if is_pending_actions_list(request.method, url.path):
            route.fulfill(json=pending_actions_payload())
            return
        if request.method == "GET" and url.path == "/api/action-credentials/pending":
            route.fulfill(json={"requests": []})
            return
        if not url.path.startswith("/api/v2/orchestration/"):
            errors.append(f"Unexpected browser request: {request.method} {url.path}")
            route.abort()
            return
        response = runtime.client.open(
            url.path + (f"?{url.query}" if url.query else ""),
            method=request.method, data=request.post_data,
            content_type=request.headers.get("content-type"), buffered=True,
        )
        requests.append({"path": url.path, "body": request.post_data_json if request.post_data else None})
        if response.status_code >= 400:
            errors.append(f"Flask rejected {url.path}: {response.get_data(as_text=True)}")
        route.fulfill(
            status=response.status_code, content_type=response.content_type,
            body=response.get_data(),
        )

    page.route("**/*", forward)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    try:
        page.goto(ORIGIN + HARNESS)
        page.wait_for_function("() => Boolean(window.OrchHarness)")
        for url in editor_assets:
            if url.endswith(".css"):
                page.add_style_tag(url=ORIGIN + url)
        page.evaluate("""() => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                settings: {}, branding: { app_title: 'SimpleChat' },
                features: { enable_chat_orchestration: true },
                user: { id: 'owner', display_name: 'Test user' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, allow_user_approval_override: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: 'conversation-1', activeConversationKind: 'personal',
                conversations: [{ id: 'conversation-1', title: 'Delivery note' }],
                messages: [], messagesLoading: false, messagesError: null,
            });
            H.mount('mount-a', 'PlanEditorExperience', {}, { strictMode: true });
        }""")
        yield page, runtime, requests
    finally:
        context.close()
        assert not errors, errors


@pytest.mark.parametrize("second_question", [False, True])
def test_answer_reaches_real_saved_review_plan(clarification_ui, second_question):
    page, runtime, requests = clarification_ui
    harness = runtime.harness
    request = "Prepare an order note with Order ID ORDER-12 and Note reference NOTE-93 as separate fields."
    request += " Ask me for its delivery date" + (" and destination first." if second_question else " first.")
    harness.replies.append(json.dumps(input_question("date", "What is the delivery date?")))
    page.evaluate("""(message) => window.OrchHarness.controller.startOrchestrationPlan({
        conversationId: 'conversation-1', message, approvalMode: 'manual',
    })""", request)
    question = page.get_by_role("region", name="Follow-up questions", exact=True)
    expect(question).to_be_visible()
    expect(question.get_by_role("button", name="Finish", exact=True)).to_be_disabled()
    assert len(harness.model_calls) == 1

    harness.replies.append(json.dumps(
        input_question("destination", "Where should it be delivered?") if second_question else plan_doc(),
    ))
    question.get_by_role("textbox", name="What is the delivery date?", exact=True).fill("2027-02-12")
    question.get_by_role("button", name="Finish", exact=True).click()
    if second_question:
        expect(question.get_by_role("textbox", name="Where should it be delivered?", exact=True)).to_be_visible()
        expect(question.get_by_role("button", name="Finish", exact=True)).to_be_disabled()
        assert len(harness.model_calls) == 2
        harness.replies.append(json.dumps(plan_doc()))
        question.get_by_role("textbox", name="Where should it be delivered?", exact=True).fill("North office")
        question.get_by_role("button", name="Finish", exact=True).click()

    expect(page.get_by_role("button", name="Edit the plan", exact=True).first).to_be_visible()
    expect(question).to_have_count(0)
    assert len(harness.model_calls) == (3 if second_question else 2)
    payload = json.loads(harness.model_calls[-1]["messages"][1]["content"])
    assert payload["original_message"] == payload["message"] == request
    assert payload["clarifications"][0]["answer"] == {"date": "2027-02-12"}
    if second_question:
        assert payload["clarifications"][1]["answer"] == {"destination": "North office"}
    state = page.evaluate("""() => {
        const H = window.OrchHarness;
        const state = H.stores.orchestration.useOrchestrationStore.getState();
        return H.stores.orchestration.selectPlan(state, 'conversation-1', state.activeTurns['conversation-1']);
    }""")
    record = harness.runs.read_item(state["run_id"], "conversation-1")
    assert record["approval"]["mode"] == "manual"
    assert record["status"] == "awaiting_approval"
    assert record["started_at"] is None
    assert harness.blobs.file_uploads == 0
    assert not any(item["path"] == "/api/v2/orchestration/run" for item in requests)
    assert not harness.replies
