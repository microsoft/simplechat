# test_v2_orchestration_workflow_handoff_plan.py
"""
Real-component browser tests for plans that hand work off to a one-time workflow.
Version: 0.261.253
Implemented in: 0.261.287
Refs: microsoft/simplechat#1549, microsoft/simplechat#1543

The production OrchestrationPlanCard, OrchestrationRunView and orchestration controller run in
Chromium with the production CSS. Only HTTP boundaries are stubbed. SERVER_PLAN is the `/plan`
route's normalized plan for a contract review asked in Timed mode, captured through the
`_normalize` helpers of `functional_tests/test_orchestration_workflow_handoff_capability.py`: the
server saved it as manual approval with the hand-off approval floor, and its hand-off step keeps
the blueprint exactly as the planner wrote it, handles, instructions and filters included. The
documents-only and best-match plans are the same capture's other loop shapes, which have no
compose step and no final response.

The server's side of the floor (normalize_plan, and the claim_plan_run backstop) and the adapter's
step result are covered by 7a's functional tests. These tests cover the browser: the plan card
says why the plan waits and what approving it does, the Review view puts the blueprint in words
without its instructions, handles or filters, a plan that hands work off never counts down or
runs itself, and a finished hand-off step shows only its summary, from the stream or from the
stored records, whatever else the step carries.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_workflow_handoff_plan.py -q
"""

import ast
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

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def server_literal(module, name):
    """A literal assigned at the top of a server module that can't be imported without Azure clients."""
    tree = ast.parse((APP_ROOT / f"{module}.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{module}.{name} not found")


pytestmark = pytest.mark.ui
IMPLEMENTED_IN = "0.261.253"
HANDOFFS = "functions_orchestration_workflow_handoffs"
CONVERSATION = "conversation-1"
TURN = "handoff-turn"
RUN = "/api/v2/orchestration/run"
RUNS = "/api/v2/orchestration/runs"
PLAN = "/api/v2/orchestration/plan"
REQUEST = "Review every contract and say what to do first."
FLOOR = {"mode": "manual", "reason": "workflow_handoff"}
DOCUMENT_HANDLE = "doc-weekly-priorities-docx-56b92f"
SCOPE_HANDLE = "scope-your-personal-workspace-96a2a4"
DOCUMENT_ID = "5c1e7b1f-2d3e-4f60-9bac-00000000d001"
HANDOFF_ID = "wfh_sentinel_7b_0001"
STEP_LABEL = "Hand off large work"
NOTICE_NAME = "Workflow hand-off in this plan"
NOTICE = "This plan hands work off to a one-time workflow, so it always waits for your approval."
NOTICE_DETAIL = (
    "Approving this plan prepares a one-time workflow. Nothing runs until you accept it on the "
    "hand-off card that appears under the answer."
)
HOSTILE_NAME = '<img src=x onerror="window.__hostile = 1"> Review <b>contracts</b>'
HOSTILE_DESCRIPTION = "<script>window.__hostile = 2</script>Sentinel description of the review"
HOSTILE_TITLE = "<script>window.__hostile = 3</script>Review one"

# The adapter's own step summaries (adapter_workflow_handoff). They are inline literals there, so
# test_the_step_summaries_are_the_adapters_own checks they are still the server's words.
READY_SUMMARY = "Prepared a one-time workflow hand-off for your approval."
NOT_READY_SUMMARY = "Prepared a one-time workflow hand-off that cannot be handed off as planned."
WORKFLOW_HANDOFF_NOTE = server_literal(HANDOFFS, "WORKFLOW_HANDOFF_NOTE")

# Nothing in a hand-off step is for the reader except its name, what it covers and its task
# titles. None of these may reach the page, as text or in the markup.
BLUEPRINT_SENTINELS = (
    "Review this contract.",
    "Write the report.",
    DOCUMENT_HANDLE,
    SCOPE_HANDLE,
    "indemnity",
    "renewal-tag",
    "blueprint",
    "workspace_query",
    '"loop"',
    "all_matches",
    "best_n",
    "Sentinel description",
)
# The step's retained result and server-only sidecar, which ride on the step record.
RESULT_SENTINELS = BLUEPRINT_SENTINELS + (
    HANDOFF_ID,
    DOCUMENT_ID,
    "digest-sentinel-7b",
    "Sidecar sentinel",
    "sentinel_error_code",
    "result_outputs",
    "requester_user_id",
)

# The `/plan` route's answer for the contract review asked in Timed mode (see the docstring).
SERVER_PLAN = {
    "kind": "plan",
    "steps": [
        {
            "step_id": "answer", "capability_id": "compose", "title": "Prepare content", "rationale": "",
            "arguments": {"instruction": "List what to focus on this week.", "knowledge_basis": "general_knowledge"},
            "depends_on": [], "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
            "optional": False, "enabled": True, "estimated_cost": "low", "role": "reason", "status": "pending",
        },
        {
            "step_id": "handoff", "capability_id": "workflow_handoff", "title": STEP_LABEL, "rationale": "",
            "arguments": {"blueprint": {
                "name": "Review contracts",
                "loop": {
                    "source": "workspace_query", "scopes": [SCOPE_HANDLE], "selection": "all_matches",
                    "content": "indemnity",
                },
                "tasks": [
                    {"title": "Review one", "instructions": "Review this contract."},
                    {"title": "Report", "instructions": "Write the report."},
                ],
            }},
            "depends_on": [], "inputs": {}, "outputs": [{"name": "handoff", "kind": "structured-v1"}],
            "optional": False, "enabled": True, "estimated_cost": "low", "role": "reason", "status": "pending",
        },
    ],
    "final_response": {
        "version": "orchestration-input-binding-v1", "step_id": "answer", "output_name": "answer",
        "existing_result": None,
    },
    "plan_id": "plan_748799c912754d31aa47c96a653a432a",
    "run_id": "run_dd1c458fc76e4eca91984a9307c0233e",
    "turn_id": TURN,
    "revision": 0,
    "conversation_id": CONVERSATION,
    "user_id": "owner",
    "planner_contract_version": 2,
    "intent": {"summary": REQUEST, "complexity": "simple", "confidence": None},
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
        "required_capabilities": [], "actions": [], "agent": None, "model": None, "prompt": None,
    },
    "outputs": [
        {"kind": "message"},
        {"kind": "markdown-v1", "source_step_id": "answer", "name": "answer"},
        {"kind": "structured-v1", "source_step_id": "handoff", "name": "handoff"},
    ],
    "status": "awaiting_approval",
}


def handoff_step(plan):
    return next(step for step in plan["steps"] if step["capability_id"] == "workflow_handoff")


def server_plan(*, hostile=False):
    plan = copy.deepcopy(SERVER_PLAN)
    if hostile:
        # The server keeps a planner's name, description and task titles as written.
        blueprint = handoff_step(plan)["arguments"]["blueprint"]
        blueprint["name"] = HOSTILE_NAME
        blueprint["description"] = HOSTILE_DESCRIPTION
        blueprint["tasks"][0]["title"] = HOSTILE_TITLE
    return plan


def handoff_only_plan(loop, *, plan_id, run_id):
    """The capture's plans that only hand work off: no compose step and no final response."""
    plan = server_plan()
    plan.update(plan_id=plan_id, run_id=run_id)
    plan["intent"]["summary"] = "Review every contract."
    plan["steps"] = [handoff_step(plan)]
    del plan["final_response"]
    plan["outputs"] = [output for output in plan["outputs"] if output.get("source_step_id") != "answer"]
    handoff_step(plan)["arguments"]["blueprint"]["loop"] = loop
    return plan


def documents_plan():
    return handoff_only_plan(
        {"source": "documents", "documents": [DOCUMENT_HANDLE]},
        plan_id="plan_874b2f1b9e9044bb8c586fe8f63eb03f", run_id="run_99735d08b90242b789b099ef6fff1f67",
    )


def best_matches_plan():
    return handoff_only_plan(
        {
            "source": "workspace_query", "scopes": [SCOPE_HANDLE], "selection": "best_n", "count": 7,
            "content": "indemnity", "tags": ["renewal-tag"],
        },
        plan_id="plan_0be536681c78478e8868f8d4c6592265", run_id="run_e17620d9d16049789a90f66efaa31655",
    )


def altered_plan(mode, *, marker, handoff=True, enabled=True):
    """A stale or altered plan that reached the browser marked Timed or Auto.

    The server never sends one: it saves every plan with an enabled hand-off step as manual. The
    browser must hold such a plan anyway, from the floor marker or from the hand-off step alone.
    """
    plan = server_plan()
    if mode == "auto":
        plan["approval"] = {"mode": "auto", "timeout_seconds": 0, "state": "approved"}
        plan["status"] = "approved"
    else:
        plan["approval"] = {"mode": mode, "timeout_seconds": 1, "state": "pending"}
    if marker:
        plan["approval"]["floor"] = dict(FLOOR)
    if not handoff:
        # The control: the same plan without its hand-off step, which must count down or run.
        plan["steps"] = [step for step in plan["steps"] if step["capability_id"] != "workflow_handoff"]
        plan["outputs"] = [output for output in plan["outputs"] if output.get("source_step_id") != "handoff"]
    elif not enabled:
        handoff_step(plan)["enabled"] = False
    return plan


def handoff_result(plan, *, status="ready"):
    """The step's server-only sidecar and its retained `handoff` result, as the adapter builds them.

    Neither is sent to the browser: the step frame and public step record whitelist their fields.
    Each is sent here anyway, full of sentinels, to prove the browser would never show them.
    """
    blueprint = copy.deepcopy(handoff_step(plan)["arguments"]["blueprint"])
    summary = {
        "name": "Sidecar sentinel name", "description": "Sidecar sentinel description",
        "tasks": [{"title": "Sidecar sentinel task", "runner": "model", "agent_name": None}],
        "alerts": {"mode": "every_run", "severity": "info"}, "durable": True, "one_time": True,
    }
    disclosure = {
        "kind": "workspace_query", "limit": 500, "limit_behavior": "pause",
        "text": "Sidecar sentinel disclosure", "scope_count": 1, "scope_names": ["Sidecar sentinel scope"],
    }
    created_at = "2026-09-29T12:19:00Z"
    sidecar = {
        "version": 1, "handoff_id": HANDOFF_ID, "origin_run_id": plan["run_id"], "step_id": "handoff",
        "conversation_id": CONVERSATION, "requester_user_id": "owner", "created_at": created_at,
        "expires_at": "2026-10-13T12:19:00Z", "status": status, "reason": None,
        "error_codes": ["sentinel_error_code"], "blueprint": blueprint, "blueprint_digest": "digest-sentinel-7b",
        "handles": {
            "documents": {DOCUMENT_HANDLE: {"document_id": DOCUMENT_ID, "scope_id": "owner", "scope_type": "personal"}},
            "scopes": {SCOPE_HANDLE: {"name": "Sidecar sentinel scope", "scope_id": "owner", "scope_type": "personal"}},
            "agents": {},
        },
        "dry_run": {"ok": True, "error_codes": []}, "disclosure": disclosure, "loop_limit": 500,
        "model_selection": None, "time_zone": "America/New_York", "summary": summary,
    }
    card = {
        "version": 1, "handoff_id": HANDOFF_ID, "name": summary["name"], "summary": copy.deepcopy(summary),
        "disclosure": copy.deepcopy(disclosure), "status": status, "reason": None, "created_at": created_at,
    }
    return sidecar, {"handoff": card}


def stream(route, events):
    route.fulfill(
        content_type="text/event-stream",
        body="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )


DONE = {"done": True, "message_id": "saved-answer", "content": WORKFLOW_HANDOFF_NOTE}


class HandoffPlanApi:
    """The orchestration routes the card and controller call, recording every `/run` request."""

    def __init__(self, assets):
        self.assets = assets
        self.plan = server_plan()
        self.run_events = [dict(DONE)]
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
            stream(route, [{"type": "orchestration_plan", "plan": plan, "done": True}])
            return
        if path == RUN and request.method == "POST":
            stream(route, self.run_events)
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
def handoff_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = HandoffPlanApi(editor_assets)
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
                version: '0.261.253', settings: {}, branding: { app_title: 'SimpleChat' },
                features: { enable_chat_orchestration: true, enable_chat_orchestration_workflow_handoff: true },
                user: { id: 'owner', display_name: 'Contract Owner' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, allow_user_approval_override: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Contract review' }],
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


def handoff_row(page):
    return page.locator("#mount-b li[data-step-id='handoff']")


def wait_for(page, predicate, message):
    for _ in range(200):
        if predicate():
            return
        page.wait_for_timeout(25)
    raise AssertionError(message)


def assert_no_sentinels(page, sentinels=BLUEPRINT_SENTINELS):
    text = page.locator("body").inner_text()
    markup = page.content()
    leaked = [sentinel for sentinel in sentinels if sentinel in text or sentinel in markup]
    assert not leaked, f"Shown or rendered into the page: {leaked}"


def approve_once(page, card):
    approve = card.get_by_role("button", name="Approve and run the plan")
    approve.focus()
    expect(approve).to_be_focused()
    page.keyboard.press("Enter")
    return approve


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


def test_the_step_summaries_are_the_adapters_own():
    source = (APP_ROOT / f"{HANDOFFS}.py").read_text(encoding="utf-8")
    assert f"'{READY_SUMMARY}'" in source
    assert f"'{NOT_READY_SUMMARY}'" in source
    assert WORKFLOW_HANDOFF_NOTE.startswith("Prepared a one-time workflow for this request.")


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_the_card_explains_the_hand_off_and_only_a_click_runs_it_once(handoff_ui, theme, width):
    page, api = handoff_ui
    page.set_viewport_size({"width": width, "height": 900})
    card = mount_card(page, api, server_plan(hostile=True), theme=theme)

    notice = card.get_by_role("note", name=NOTICE_NAME)
    expect(notice).to_be_visible()
    expect(notice).to_contain_text(NOTICE)
    expect(notice).to_contain_text(NOTICE_DETAIL)
    for tag in ("img", "b", "script"):
        expect(notice.locator(tag)).to_have_count(0)
    box = notice.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= width

    # The Review view names the step, not its capability id, and puts the blueprint in words.
    step = handoff_row(page)
    expect(step).to_have_attribute("aria-label", f"Step 2: {STEP_LABEL}")
    expect(step.get_by_text(STEP_LABEL, exact=True)).to_have_count(2)
    assert "workflow_handoff" not in step.inner_text()
    args = step.get_by_test_id("orchestration-step-arguments")
    values = [HOSTILE_NAME, "a search of 1 workspace, all matches", f"{HOSTILE_TITLE}, Report"]
    expect(args.locator("dt")).to_have_text(["workflow", "documents", "tasks"])
    # The planner's name and titles are shown exactly as written and never become markup.
    expect(args.locator("dd")).to_have_text(values)
    for index, value in enumerate(values):
        expect(args.locator("dd").nth(index)).to_have_attribute("title", value)
    for tag in ("img", "b", "script"):
        expect(step.locator(tag)).to_have_count(0)
    box = args.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= width

    # The step's named output is its declaration: a name and a kind, never a value.
    bindings = step.get_by_role("region", name=f"Result bindings for {STEP_LABEL}")
    expect(bindings).to_contain_text("Named outputs")
    expect(bindings.locator("dt")).to_have_text(["handoff"])
    expect(bindings).to_contain_text("Kind: structured-v1")
    assert_no_sentinels(page)

    # A plan that hands work off never counts down: nothing runs until the user approves it.
    expect(page.get_by_role("timer")).to_have_count(0)
    page.wait_for_timeout(300)
    assert api.runs() == []

    approve = approve_once(page, card)
    wait_for(page, lambda: len(api.runs()) == 1, "The user's own approval must run the plan.")
    if approve.count() and approve.is_enabled():
        page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    runs = api.runs()
    assert len(runs) == 1, runs
    assert runs[0]["run_id"] == SERVER_PLAN["run_id"] and runs[0]["conversation_id"] == CONVERSATION


@pytest.mark.parametrize(
    "make_plan,documents",
    [(documents_plan, "1 named document"), (best_matches_plan, "a search of 1 workspace, the 7 best matches")],
    ids=["named-documents", "best-matches"],
)
def test_the_review_view_puts_each_loop_in_words(handoff_ui, make_plan, documents):
    page, api = handoff_ui
    card = mount_card(page, api, make_plan())
    expect(card.get_by_role("note", name=NOTICE_NAME)).to_contain_text(NOTICE)
    step = handoff_row(page)
    expect(step).to_have_attribute("aria-label", f"Step 1: {STEP_LABEL}")
    args = step.get_by_test_id("orchestration-step-arguments")
    expect(args.locator("dt")).to_have_text(["workflow", "documents", "tasks"])
    expect(args.locator("dd")).to_have_text(["Review contracts", documents, "Review one, Report"])
    assert_no_sentinels(page)
    expect(page.get_by_role("timer")).to_have_count(0)


@pytest.mark.parametrize("marker", [True, False], ids=["floor-marker", "hand-off-step-only"])
def test_a_timed_plan_that_hands_work_off_never_counts_down(handoff_ui, marker):
    page, api = handoff_ui
    page.clock.install()
    card = mount_card(page, api, altered_plan("timed", marker=marker))
    expect(card.get_by_role("note", name=NOTICE_NAME)).to_contain_text(NOTICE)
    expect(page.get_by_role("timer")).to_have_count(0)
    page.clock.run_for(5000)
    page.wait_for_timeout(200)
    expect(page.get_by_role("timer")).to_have_count(0)
    assert api.runs() == []
    expect(card.get_by_role("button", name="Approve and run the plan")).to_be_enabled()


def test_the_same_timed_plan_without_its_hand_off_step_counts_down_and_runs(handoff_ui):
    """The control for the test above: this harness's countdown really does run a timed plan."""
    page, api = handoff_ui
    page.clock.install()
    card = mount_card(page, api, altered_plan("timed", marker=False, handoff=False))
    expect(card.get_by_role("note", name=NOTICE_NAME)).to_have_count(0)
    expect(page.get_by_role("timer")).to_be_visible()
    page.clock.run_for(5000)
    wait_for(page, lambda: len(api.runs()) == 1, "An expired countdown must run a plan with no hand-off step.")


def test_a_timed_plan_whose_hand_off_step_is_off_counts_down_and_runs(handoff_ui):
    """As on the server, only an enabled hand-off step holds a plan without a floor marker."""
    page, api = handoff_ui
    page.clock.install()
    card = mount_card(page, api, altered_plan("timed", marker=False, enabled=False))
    expect(card.get_by_role("note", name=NOTICE_NAME)).to_have_count(0)
    expect(page.get_by_role("timer")).to_be_visible()
    page.clock.run_for(5000)
    wait_for(page, lambda: len(api.runs()) == 1, "A plan whose hand-off step is off must count down and run.")


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


@pytest.mark.parametrize("marker", [True, False], ids=["floor-marker", "hand-off-step-only"])
def test_an_auto_plan_that_hands_work_off_settles_and_never_runs_itself(handoff_ui, marker):
    page, api = handoff_ui
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


def test_the_same_auto_plan_without_its_hand_off_step_runs_itself(handoff_ui):
    """The control for the test above: this harness's auto mode really does run an approved plan."""
    page, api = handoff_ui
    open_harness(page, api)
    api.plan = altered_plan("auto", marker=False, handoff=False)
    result = page.evaluate(START_AND_SETTLE, {"conversation": CONVERSATION, "request": REQUEST})
    assert result["turnId"], result
    wait_for(page, lambda: len(api.runs()) == 1, "An approved auto plan with no hand-off step must run.")


def test_a_streamed_hand_off_step_shows_only_its_summary(handoff_ui):
    page, api = handoff_ui
    plan = server_plan()
    sidecar, outputs = handoff_result(plan)
    step_frame = {
        "type": "orchestration_step", "step_id": "handoff", "step_index": 1,
        "capability_id": "workflow_handoff", "role": "reason",
    }
    api.run_events = [
        {"type": "orchestration_step", "step_id": "answer", "step_index": 0, "capability_id": "compose",
         "role": "reason", "status": "completed", "summary": ""},
        {**step_frame, "status": "running", "summary": ""},
        # The server never sends these keys on a step frame; the browser must ignore them if it did.
        {**step_frame, "status": "completed", "summary": READY_SUMMARY,
         "workflow_handoff": sidecar, "result_outputs": outputs},
        dict(DONE),
    ]
    card = mount_card(page, api, plan)
    approve_once(page, card)
    wait_for(page, lambda: len(api.runs()) == 1, "The user's own approval must run the plan.")

    step = handoff_row(page)
    expect(step.get_by_text(READY_SUMMARY, exact=True)).to_be_visible()
    expect(step.get_by_text("Completed", exact=True).first).to_be_visible()
    page.wait_for_timeout(300)
    assert_no_sentinels(page, RESULT_SENTINELS)
    assert len(api.runs()) == 1


def test_a_stored_hand_off_step_shows_only_its_summary(handoff_ui):
    page, api = handoff_ui
    open_harness(page, api)
    plan = server_plan()
    plan["status"] = "completed"
    plan["approval"].update(state="approved", approved_at="2026-09-29T12:18:00Z", approved_by="owner")
    sidecar, outputs = handoff_result(plan, status="invalid")
    base = {"run_id": plan["run_id"], "started_at": "2026-09-29T12:18:01Z", "completed_at": "2026-09-29T12:18:04Z",
            "reused": False, "reused_from_run_id": None, "checkpoint_available": True, "model_binding": None}
    records = [
        {**base, "step_id": "answer", "step_index": 0, "capability_id": "compose", "title": "Prepare content",
         "status": "completed", "duration_ms": 2100, "summary": ""},
        # A public step record never carries these keys; the browser must ignore them if one did.
        {**base, "step_id": "handoff", "step_index": 1, "capability_id": "workflow_handoff", "title": STEP_LABEL,
         "status": "completed", "duration_ms": 900, "summary": NOT_READY_SUMMARY,
         "workflow_handoff": sidecar, "result_outputs": outputs},
    ]
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            const store = H.stores.orchestration.useOrchestrationStore.getState();
            store.adoptPersistedPlan(spec.conversation, spec.turn, spec.plan, spec.records);
            store.setActiveTurn(spec.conversation, spec.turn);
            H.mount('mount-b', 'OrchestrationRunView',
                { conversationId: spec.conversation, turnId: spec.turn }, { strictMode: true });
        }""",
        {"conversation": CONVERSATION, "turn": TURN, "plan": plan, "records": records},
    )
    step = handoff_row(page)
    expect(step.get_by_text(NOT_READY_SUMMARY, exact=True)).to_be_visible()
    expect(step.get_by_text("Completed", exact=True).first).to_be_visible()
    page.wait_for_timeout(300)
    assert_no_sentinels(page, RESULT_SENTINELS)
    assert api.runs() == []
