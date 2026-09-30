# test_v2_orchestration_streaming_bubble.py
"""
Browser regression for the V2 orchestration streaming bubble.
Version: 0.261.204
Implemented in: 0.261.204

While an orchestrated turn is planned or run, the streaming bubble shows only the
"N reasoning steps" toggle and the "Thinking" indicator. It used to also draw an
Orchestration progress card (heading, "Current step: Building a plan", a percentage,
a step count and a progress bar) that repeated what the toggle and the plan card
already say, so that card is no longer drawn, live or in a finished answer's
expanded reasoning. Tabular analysis keeps its progress card.

The production controller, stores, SSE reader, MessageList and plan card run in
Chromium with production CSS. Only HTTP is deterministic: the plan and run streams
are held open and fed one server-shaped frame at a time, so each intermediate state
of the bubble can be inspected. No live model, deployment or workspace content is used.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_streaming_bubble.py -q
"""

import re
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
CONVERSATION = "streaming-bubble-chat"
PLAN = "/api/v2/orchestration/plan"
RUN = editor_tests.RUN
QUESTION = "Compare the quarterly reports and summarise how revenue changed."
DECIDING = "Deciding what this question needs."
MEMORY_NOTICE = "Saved facts could not be searched. Any available instruction memories are still included."
ANSWER = "Revenue rose 12% between the two quarters."

# Plan and run responses stay open until the test ends them, so every frame can be
# checked on screen before the next one lands. Other requests go to the page router.
INSTALL_STREAMS = r"""
(paths) => {
    const encoder = new TextEncoder();
    const passThrough = window.fetch.bind(window);
    window.__streams = {};
    window.emitFrame = (path, event) => {
        window.__streams[path].enqueue(encoder.encode('data: ' + JSON.stringify(event) + '\n\n'));
    };
    window.endStream = (path) => {
        try {
            window.__streams[path].close();
        } catch (error) {
            // The reader already stopped at the terminal frame.
        }
    };
    window.fetch = (input, init = {}) => {
        const url = new URL(input instanceof Request ? input.url : String(input), location.href);
        if (!paths.includes(url.pathname)) {
            return passThrough(input, init);
        }
        const body = new ReadableStream({
            start(controller) {
                window.__streams[url.pathname] = controller;
            },
        });
        return Promise.resolve(new Response(body, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        }));
    };
}
"""


def planning_thought(content, status="running"):
    """A planner reasoning step, shaped exactly as build_planning_thought serializes it."""
    return {
        "type": "thought",
        "message_id": None,
        "step_index": 1,
        "step_type": "orchestration_planning",
        "content": content,
        "activity": {
            "lane_key": "orchestration",
            "kind": "orchestration_planning",
            "title": "Building a plan",
            "status": status,
        },
    }


def run_done(plan, turn):
    """The run's terminal frame, shaped as build_run_done_event serializes a completed run."""
    return {
        "done": True,
        "type": "orchestration_done",
        "conversation_id": CONVERSATION,
        "message_id": "orchestrated-answer",
        "run_id": plan["run_id"],
        "full_content": ANSWER,
        "hybrid_citations": [],
        "web_search_citations": [],
        "agent_citations": [],
        "augmented": False,
        "generated_artifacts": [],
        "orchestration": {},
        "status": "completed",
        "outcome": "completed",
        "turn_id": turn,
        "attempt_index": 1,
        "retry_of_run_id": None,
        "failure": None,
        "failures": [],
        "recovery": None,
        "message_saved": True,
        "reasoning_adjustments": [],
    }


class BubbleApi:
    """Serves the harness and its production CSS; any other request fails the test."""

    def __init__(self, assets):
        self.assets = assets
        self.errors = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.errors.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test request."})


@pytest.fixture
def bubble_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    api = BubbleApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", lambda message: api.errors.append(message.text) if message.type == "error" else None)
    try:
        mount(page, api)
        yield page, api
    finally:
        context.close()
        assert not api.errors, api.errors


def mount(page, api):
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(
        """(conversation) => {
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
                messages: [], messagesLoading: false, messagesError: null, streaming: false,
                streamError: null, streamingContent: '', thoughts: [],
                conversations: [{id: conversation, title: 'Quarterly comparison'}],
            });
            H.mount('mount-a', 'MessageList');
        }""",
        CONVERSATION,
    )
    page.evaluate(INSTALL_STREAMS, [PLAN, RUN])


def emit(page, path, event):
    page.evaluate("([path, event]) => window.emitFrame(path, event)", [path, event])


def wait_for_stream(page, path):
    page.wait_for_function("(path) => Boolean(window.__streams[path])", arg=path)


def toggle(page, count):
    label = f"{count} reasoning step{'' if count == 1 else 's'}"
    return page.get_by_role("button", name=label, exact=True)


def expect_no_progress_card(page):
    """Nothing that the orchestration progress card drew may be on screen."""
    expect(page.get_by_role("progressbar")).to_have_count(0)
    expect(page.get_by_text("Orchestration", exact=True)).to_have_count(0)
    expect(page.get_by_text("Orchestration complete", exact=True)).to_have_count(0)
    expect(page.get_by_text(re.compile(r"^Current step: "))).to_have_count(0)
    expect(page.get_by_text(re.compile(r"^\d{1,3}%$"))).to_have_count(0)
    expect(page.get_by_text(re.compile(r"^\d+/\d+ steps?\b"))).to_have_count(0)
    expect(page.get_by_text("Orchestration captured for this response", exact=True)).to_have_count(0)


def expect_toggle_first(button):
    """The reasoning toggle opens its panel: no card is drawn above it."""
    assert button.evaluate("(node) => node.parentElement.firstElementChild === node")


def start_plan(page):
    page.evaluate(
        """(spec) => { void window.OrchHarness.controller.startOrchestrationPlan(spec); }""",
        {"conversationId": CONVERSATION, "message": QUESTION, "approvalMode": "manual", "seeds": {}},
    )
    wait_for_stream(page, PLAN)
    return page.evaluate(
        "(conversation) => window.OrchHarness.stores.orchestration.useOrchestrationStore"
        ".getState().activeTurns[conversation]",
        CONVERSATION,
    )


def finish_plan(page, turn):
    plan = editor_tests.make_plan(CONVERSATION, turn)
    emit(page, PLAN, planning_thought("Plan ready.", status="completed"))
    emit(page, PLAN, {"type": "orchestration_plan", "plan": plan, "done": True})
    page.evaluate("(path) => window.endStream(path)", PLAN)
    expect(page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
    return plan


def test_planning_bubble_shows_reasoning_toggle_and_thinking_without_a_progress_card(bubble_ui):
    page, api = bubble_ui
    turn = start_plan(page)
    thinking = page.get_by_text("Thinking", exact=True)
    expect(thinking).to_be_visible()
    expect(page.get_by_text(QUESTION, exact=True)).to_be_visible()

    emit(page, PLAN, planning_thought(DECIDING))
    steps = toggle(page, 1)
    expect(steps).to_be_visible()
    expect(steps).to_have_attribute("aria-expanded", "false")
    expect(thinking).to_be_visible()
    expect_no_progress_card(page)
    # The card repeated the latest planner sentence under its bar; collapsed, it stays hidden.
    expect(page.get_by_text(DECIDING, exact=True)).to_have_count(0)
    expect_toggle_first(steps)
    toggle_box = steps.bounding_box()
    thinking_box = thinking.bounding_box()
    assert toggle_box and thinking_box and toggle_box["y"] < thinking_box["y"]

    steps.click()
    expect(steps).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_text("orchestration_planning", exact=True)).to_be_visible()
    expect(page.get_by_text(DECIDING, exact=True)).to_be_visible()
    expect_no_progress_card(page)

    finish_plan(page, turn)
    expect(thinking).to_have_count(0)
    expect(page.get_by_text(DECIDING, exact=True)).to_have_count(0)
    expect_no_progress_card(page)


def test_run_and_finished_answer_show_no_orchestration_progress_card(bubble_ui):
    page, api = bubble_ui
    turn = start_plan(page)
    emit(page, PLAN, planning_thought(DECIDING))
    expect(toggle(page, 1)).to_be_visible()
    plan = finish_plan(page, turn)

    page.get_by_role("button", name="Approve and run the plan").first.click()
    wait_for_stream(page, RUN)
    thinking = page.get_by_text("Thinking", exact=True)
    expect(thinking).to_be_visible()
    # Run progress stays on the plan card, which keeps its own compact line.
    expect(page.get_by_role("button", name="Review the running plan")).to_be_visible()

    emit(page, RUN, planning_thought(MEMORY_NOTICE))
    steps = toggle(page, 1)
    expect(steps).to_be_visible()
    expect(thinking).to_be_visible()
    expect(page.get_by_text(MEMORY_NOTICE, exact=True)).to_have_count(0)
    expect_toggle_first(steps)
    expect_no_progress_card(page)

    emit(page, RUN, {"content": ANSWER})
    emit(page, RUN, run_done(plan, turn))
    page.evaluate("(path) => window.endStream(path)", RUN)
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    expect(thinking).to_have_count(0)

    saved = toggle(page, 1)
    expect(saved).to_be_visible()
    saved.click()
    expect(saved).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_text(MEMORY_NOTICE, exact=True)).to_be_visible()
    expect_no_progress_card(page)


def test_tabular_streaming_bubble_keeps_its_progress_card(bubble_ui):
    page, api = bubble_ui
    page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.setState({
        streaming: true,
        thoughts: [{
            id: '0',
            title: 'tabular_analysis',
            content: 'Reading the quarterly workbook.',
            stepType: 'tabular_analysis',
            activity: {
                activity_key: 'call-1', kind: 'tabular_tool_invocation',
                title: 'describe_tabular_file', status: 'running', state: 'running',
                lane_key: 'tabular', lane_label: 'Tabular',
                plugin_name: 'TabularProcessingPlugin', function_name: 'describe_tabular_file',
            },
        }],
    })""")
    expect(page.get_by_role("progressbar", name="Tabular analysis progress")).to_be_visible()
    expect(page.get_by_text("Tabular analysis", exact=True)).to_be_visible()
    expect(page.get_by_text("Current tabular step: describe_tabular_file", exact=True)).to_be_visible()
    expect(toggle(page, 1)).to_be_visible()
    expect(page.get_by_text("Thinking", exact=True)).to_be_visible()
