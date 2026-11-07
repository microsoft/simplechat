# test_v2_orchestration_workflow_run_floor.py
"""
Real-component browser tests for plans that start a saved workflow.
Version: 0.261.212
Implemented in: 0.261.212
Refs: microsoft/simplechat#1551

The production OrchestrationPlanCard, OrchestrationRunView and orchestration controller run in
Chromium with the production CSS. Only HTTP boundaries are stubbed. SERVER_PLAN is the `/plan`
route's real answer to "Please run my WEEKLY DIGEST now." asked in Timed mode, captured from
`functional_tests/test_orchestration_workflow_run_approval_floor.py`'s real-HTTP harness: the
server saved it as manual approval with an approval floor, and names the workflow it starts.

The server's side of the floor (normalize_plan on every planning path, and the claim_plan_run
backstop that refuses a changed record) is covered by that functional test. These tests cover
the browser's own guard: a plan that starts a saved workflow never counts down and never runs
itself, even when a stale or altered plan reaches the card marked Timed or Auto, and a user's
own click still runs it exactly once.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_workflow_run_floor.py -q
"""

import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


pytestmark = pytest.mark.ui
IMPLEMENTED_IN = "0.261.212"
CONVERSATION = "conversation-1"
TURN = "floor-turn"
RUN = "/api/v2/orchestration/run"
RUNS = "/api/v2/orchestration/runs"
PLAN = "/api/v2/orchestration/plan"
HANDLE = "workflow-weekly-digest-702b6c"
REQUEST = "Please run my WEEKLY DIGEST now."
NOTICE = "This plan starts a saved workflow, so it always waits for you to run it."
PAUSED_NOTE = "A paused workflow still runs once when you start it here. Starting it doesn't turn it back on."
HOSTILE_NAME = '<img src=x onerror="window.__hostile = 1"> Weekly <b>digest</b>'
FLOOR = {"mode": "manual", "reason": "workflow_run"}

# The `/plan` route's answer for the weekly digest request asked in Timed mode (see the docstring).
SERVER_PLAN = {
    "kind": "plan",
    "steps": [
        {
            "step_id": "prepare", "capability_id": "compose", "title": "Prepare content", "rationale": "",
            "arguments": {"instruction": "Prepare the complete requested content."},
            "depends_on": [], "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
            "optional": False, "enabled": True, "estimated_cost": "low", "role": "reason", "status": "pending",
        },
        {
            "step_id": "run_digest", "capability_id": "workflow_run", "title": "Run workflow", "rationale": "",
            "arguments": {"workflow": HANDLE},
            "depends_on": [], "inputs": {}, "outputs": [{"name": "run", "kind": "structured-v1"}],
            "optional": False, "enabled": True, "estimated_cost": "low", "role": "gather", "status": "pending",
        },
    ],
    "final_response": {
        "version": "orchestration-input-binding-v1", "step_id": "prepare", "output_name": "answer",
        "existing_result": None,
    },
    "plan_id": "plan_2fa6aa0ee3ed4641a1441493bffc8470",
    "run_id": "run_f8fe1023fb514e748088a02978cf7d35",
    "turn_id": TURN,
    "revision": 0,
    "conversation_id": CONVERSATION,
    "user_id": "owner",
    "planner_contract_version": 2,
    "intent": {"summary": "", "complexity": "simple", "confidence": None},
    "assumptions": [],
    "approval": {
        "mode": "manual", "timeout_seconds": 10, "state": "pending", "approved_at": None,
        "approved_by": None, "edited": False, "floor": dict(FLOOR),
    },
    "deliverables": [{
        "id": "answer", "kind": "answer", "requested": "explicit", "status": "planned",
        "description": "An answer to your request.", "implicit": True,
    }],
    "validation": {"ok": True, "errors": [], "repairs": []},
    "inputs": {
        "documents": [], "image_reference_documents": [], "image_reference_messages": [], "web": False,
        "required_capabilities": [], "actions": [], "agent": None,
        "model": {"model_deployment": "gpt-4o", "model_provider": "aoai"}, "prompt": None,
        "workflows": [{
            "handle": HANDLE, "name": "Weekly digest", "trigger_summary": "Mondays 08:00 America/New_York",
            "paused": True,
        }],
    },
    "outputs": [
        {"kind": "message"},
        {"kind": "markdown-v1", "source_step_id": "prepare", "name": "answer"},
        {"kind": "structured-v1", "source_step_id": "run_digest", "name": "run"},
    ],
    "status": "awaiting_approval",
    "planner_model": "gpt-4o",
    "planner": {"label": "gpt-4o", "source": "default"},
    "reasoning_adjustments": [],
}


def server_plan(*, name=None):
    plan = copy.deepcopy(SERVER_PLAN)
    if name is not None:
        plan["inputs"]["workflows"][0]["name"] = name
    return plan


def altered_plan(mode, *, marker, workflow=True):
    """A stale or altered plan that reached the browser marked Timed or Auto.

    The server never sends one: it saves every plan that starts a saved workflow as manual. The
    browser must hold such a plan anyway, from the floor marker or from the run step alone.
    """
    plan = server_plan()
    if mode == "auto":
        plan["approval"] = {"mode": "auto", "timeout_seconds": 0, "state": "approved"}
        plan["status"] = "approved"
    else:
        plan["approval"] = {"mode": mode, "timeout_seconds": 1, "state": "pending"}
    if marker:
        plan["approval"]["floor"] = dict(FLOOR)
    if not workflow:
        # The control: the same plan without its workflow step, which must count down or run.
        plan["steps"] = [step for step in plan["steps"] if step["capability_id"] != "workflow_run"]
        plan["outputs"] = [output for output in plan["outputs"] if output.get("source_step_id") != "run_digest"]
        del plan["inputs"]["workflows"]
    return plan


def stream(route, event):
    route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")


class FloorApi:
    """The orchestration routes the card and controller call, recording every `/run` request."""

    def __init__(self, assets):
        self.assets = assets
        self.plan = server_plan()
        self.requests = []
        self.unexpected = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        body = request.post_data_json if request.method == "POST" else None
        self.requests.append({"method": request.method, "path": path, "body": body})
        if path == PLAN and request.method == "POST":
            plan = copy.deepcopy(self.plan)
            # Like the server, echo the client's own conversation and turn.
            plan.update(conversation_id=body["conversation_id"], turn_id=body["turn_id"])
            stream(route, {"type": "orchestration_plan", "plan": plan, "done": True})
            return
        if path == RUN and request.method == "POST":
            stream(route, {"done": True, "message_id": "saved-answer", "content": "Started Weekly digest."})
            return
        if path == RUNS and request.method == "GET":
            route.fulfill(json={"runs": []})
            return
        if re.fullmatch(re.escape(RUNS) + r"/[^/]+/steps", path) and request.method == "GET":
            route.fulfill(json={"steps": []})
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})

    def runs(self):
        return [call["body"] for call in self.requests if call["path"] == RUN]


@pytest.fixture
def floor_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = FloorApi(editor_assets)
    errors = []
    dialogs = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)
    try:
        yield page, api
        hostile = page.evaluate("() => window.__hostile ?? null")
        assert hostile is None, hostile
    finally:
        context.close()
    assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
    assert not errors, f"Unexpected browser errors: {errors}"
    assert not dialogs, f"Unexpected browser dialogs: {dialogs}"


def open_harness(page, api, *, theme="light"):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            document.documentElement.classList.toggle('dark', spec.theme === 'dark');
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.212', settings: {}, branding: { app_title: 'SimpleChat' },
                features: { enable_chat_orchestration: true },
                user: { id: 'owner', display_name: 'Workflow Owner' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, allow_user_approval_override: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Weekly digest' }],
                messages: [{ id: 'user-1', conversation_id: spec.conversation, role: 'user',
                    content: spec.request, metadata: { orchestration_turn_id: spec.turn } }],
            });
        }""",
        {"conversation": CONVERSATION, "turn": TURN, "theme": theme, "request": REQUEST},
    )


def mount_card(page, api, plan, *, theme="light"):
    open_harness(page, api, theme=theme)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            const store = H.stores.orchestration.useOrchestrationStore.getState();
            store.setPlan(spec.conversation, spec.turn, spec.plan);
            store.setActiveTurn(spec.conversation, spec.turn);
            const props = { conversationId: spec.conversation, turnId: spec.turn };
            H.mount('mount-a', 'OrchestrationPlanCard', props, { strictMode: true });
            H.mount('mount-b', 'OrchestrationRunView', props, { strictMode: true });
        }""",
        {"conversation": CONVERSATION, "turn": TURN, "plan": plan},
    )
    card = page.locator("#mount-a")
    expect(card.get_by_role("button", name="Approve and run the plan")).to_be_visible()
    return card


def wait_for(page, predicate, message):
    for _ in range(200):
        if predicate():
            return
        page.wait_for_timeout(25)
    raise AssertionError(message)


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_the_card_names_the_workflow_and_only_a_click_runs_it_once(floor_ui, theme, width):
    page, api = floor_ui
    page.set_viewport_size({"width": width, "height": 900})
    card = mount_card(page, api, server_plan(name=HOSTILE_NAME), theme=theme)

    notice = card.get_by_role("note", name="Saved workflows in this plan")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text(NOTICE)
    expect(notice).to_contain_text(PAUSED_NOTE)
    items = notice.get_by_role("list", name="Workflows this plan starts").get_by_role("listitem")
    expect(items).to_have_count(1)
    # The workflow's own name and trigger are shown exactly as written and never become markup.
    expect(items.first.get_by_text(HOSTILE_NAME, exact=True)).to_be_visible()
    expect(items.first).to_contain_text("· Mondays 08:00 America/New_York")
    expect(items.first.get_by_text("Paused", exact=True)).to_be_visible()
    for tag in ("img", "b", "script"):
        expect(notice.locator(tag)).to_have_count(0)
    box = notice.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= width

    # The Review view names the workflow too, and neither view shows the internal handle.
    step = page.locator("#mount-b").get_by_test_id("orchestration-workflow-run-input")
    expect(step).to_contain_text("Workflow")
    expect(step.get_by_text(HOSTILE_NAME, exact=True)).to_be_visible()
    expect(step).to_contain_text("(paused)")
    assert HANDLE not in page.locator("body").inner_text()

    # A plan that starts a saved workflow never counts down: nothing runs until the user does.
    expect(page.get_by_role("timer")).to_have_count(0)
    page.wait_for_timeout(300)
    assert api.runs() == []

    approve = card.get_by_role("button", name="Approve and run the plan")
    approve.focus()
    expect(approve).to_be_focused()
    page.keyboard.press("Enter")
    wait_for(page, lambda: len(api.runs()) == 1, "The user's own approval must run the plan.")
    if approve.count() and approve.is_enabled():
        page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    runs = api.runs()
    assert len(runs) == 1, runs
    assert runs[0]["run_id"] == SERVER_PLAN["run_id"] and runs[0]["conversation_id"] == CONVERSATION


@pytest.mark.parametrize("marker", [True, False], ids=["floor-marker", "run-step-only"])
def test_a_timed_plan_that_starts_a_workflow_never_counts_down(floor_ui, marker):
    page, api = floor_ui
    page.clock.install()
    card = mount_card(page, api, altered_plan("timed", marker=marker))
    expect(card.get_by_role("note", name="Saved workflows in this plan")).to_contain_text(NOTICE)
    expect(page.get_by_role("timer")).to_have_count(0)
    page.clock.run_for(5000)
    page.wait_for_timeout(200)
    expect(page.get_by_role("timer")).to_have_count(0)
    assert api.runs() == []
    expect(card.get_by_role("button", name="Approve and run the plan")).to_be_enabled()


def test_the_same_timed_plan_without_its_workflow_step_counts_down_and_runs(floor_ui):
    """The control for the test above: this harness's countdown really does run a timed plan."""
    page, api = floor_ui
    page.clock.install()
    card = mount_card(page, api, altered_plan("timed", marker=False, workflow=False))
    expect(card.get_by_role("note", name="Saved workflows in this plan")).to_have_count(0)
    expect(page.get_by_role("timer")).to_be_visible()
    page.clock.run_for(5000)
    wait_for(page, lambda: len(api.runs()) == 1, "An expired countdown must run a plan with no workflow step.")


START_AND_SETTLE = """
async (spec) => {
    const H = window.OrchHarness;
    await H.controller.startOrchestrationPlan({
        conversationId: spec.conversation, message: spec.request, approvalMode: 'auto', seeds: {},
    });
    const orchestration = H.stores.orchestration.useOrchestrationStore.getState();
    const chat = H.stores.chat.useChatStore.getState();
    const keys = Object.keys(orchestration.plans);
    const turnId = keys.length === 1 ? keys[0].split('\\u0000')[1] : null;
    return { keys, turnId, streaming: chat.streaming, streamError: chat.streamError };
}
"""


@pytest.mark.parametrize("marker", [True, False], ids=["floor-marker", "run-step-only"])
def test_an_auto_plan_that_starts_a_workflow_settles_and_never_runs_itself(floor_ui, marker):
    page, api = floor_ui
    open_harness(page, api)
    api.plan = altered_plan("auto", marker=marker)
    result = page.evaluate(START_AND_SETTLE, {"conversation": CONVERSATION, "request": REQUEST})
    assert result["turnId"], result
    # The turn settles as planned, waiting for the card, instead of starting the run.
    assert result["streaming"] is False and result["streamError"] is None, result
    page.wait_for_timeout(300)
    assert api.runs() == []

    # Nothing automatic can start it either, even when asked to directly.
    page.evaluate(
        """(spec) => window.OrchHarness.controller.approveAndRunPlan({
            conversationId: spec.conversation, turnId: spec.turn, automatic: true })""",
        {"conversation": CONVERSATION, "turn": result["turnId"]},
    )
    page.wait_for_timeout(300)
    assert api.runs() == []

    # The user's own approval still runs it, once.
    page.evaluate(
        """(spec) => window.OrchHarness.controller.approveAndRunPlan({
            conversationId: spec.conversation, turnId: spec.turn })""",
        {"conversation": CONVERSATION, "turn": result["turnId"]},
    )
    wait_for(page, lambda: len(api.runs()) == 1, "The user's own approval must run the plan.")


def test_the_same_auto_plan_without_its_workflow_step_runs_itself(floor_ui):
    """The control for the test above: this harness's auto mode really does run an approved plan."""
    page, api = floor_ui
    open_harness(page, api)
    api.plan = altered_plan("auto", marker=False, workflow=False)
    result = page.evaluate(START_AND_SETTLE, {"conversation": CONVERSATION, "request": REQUEST})
    assert result["turnId"], result
    wait_for(page, lambda: len(api.runs()) == 1, "An approved auto plan with no workflow step must run.")
