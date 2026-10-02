# test_v2_orchestration_workflow_results_input.py
"""
Real-component browser tests for plans that read saved workflow results.
Version: 0.261.217
Implemented in: 0.261.217
Refs: microsoft/simplechat#1546

The production OrchestrationPlanCard and OrchestrationRunView run in Chromium with the
production CSS. Only HTTP boundaries are stubbed. SERVER_PLAN mirrors the server shape for
workflow_results inputs: workflow result steps name request-local handles in arguments, while
the review UI resolves user-facing workflow names from `plan.inputs.workflow_results`.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_workflow_results_input.py -q
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
IMPLEMENTED_IN = "0.261.217"
CONVERSATION = "conversation-1"
TURN = "workflow-results-turn"
RUN = "/api/v2/orchestration/run"
RUNS = "/api/v2/orchestration/runs"
PLAN = "/api/v2/orchestration/plan"
REQUEST = "What did my saved workflow runs find?"
RUN_HANDLE = "workflow-weekly-digest-702b6c"
ALPHA_HANDLE = "workflow-board-report-126ace"
BETA_HANDLE = "workflow-renewal-digest-485fed"
HOSTILE_HANDLE = "workflow-hostile-name-a11y00"
MISSING_HANDLE = "workflow-missing-result-912abc"
ALPHA_NAME = "Board report workflow"
BETA_NAME = "Customer renewal digest"
HOSTILE_NAME = "<b>x</b><script>window.__hostile = 1</script> result reader"
COMPOSE_INSTRUCTION = "Summarize the workflow notes for the user."
RESULTS_STEP_IDS = [
    "read_alpha_latest",
    "read_beta_failed",
    "read_hostile_date",
    "read_run_handle_date_completed",
    "read_missing_latest",
]
RESULTS_HANDLES = [ALPHA_HANDLE, BETA_HANDLE, HOSTILE_HANDLE, RUN_HANDLE, MISSING_HANDLE]
RESULT_ARGUMENT_KEYS = ["workflow", "selector", "completed_on", "status"]


def workflow_results_step(step_id, workflow, arguments):
    args = {"workflow": workflow, **arguments}
    return {
        "step_id": step_id,
        "capability_id": "workflow_results",
        "title": f"Read {step_id.replace('_', ' ')}",
        "rationale": "",
        "arguments": args,
        "depends_on": [],
        "inputs": {},
        "outputs": [{"name": "result", "kind": "structured-v1"}],
        "optional": False,
        "enabled": True,
        "estimated_cost": "low",
        "role": "gather",
        "status": "pending",
    }


SERVER_PLAN = {
    "kind": "plan",
    "steps": [
        {
            "step_id": "compose_answer", "capability_id": "compose", "title": "Compose answer",
            "rationale": "", "arguments": {"instruction": COMPOSE_INSTRUCTION},
            "depends_on": ["read_alpha_latest"], "inputs": {},
            "outputs": [{"name": "answer", "kind": "markdown-v1"}],
            "optional": False, "enabled": True, "estimated_cost": "low", "role": "reason",
            "status": "pending",
        },
        {
            "step_id": "start_digest", "capability_id": "workflow_run", "title": "Run saved workflow",
            "rationale": "", "arguments": {"workflow": RUN_HANDLE}, "depends_on": [], "inputs": {},
            "outputs": [{"name": "run", "kind": "structured-v1"}],
            "optional": False, "enabled": True, "estimated_cost": "low", "role": "gather",
            "status": "pending",
        },
        workflow_results_step("read_alpha_latest", ALPHA_HANDLE, {"selector": "latest"}),
        workflow_results_step("read_beta_failed", BETA_HANDLE, {"selector": "latest", "status": "failed"}),
        workflow_results_step(
            "read_hostile_date",
            HOSTILE_HANDLE,
            {"selector": "completed_on", "completed_on": "2026-09-29"},
        ),
        # Invalid server data on purpose: this pins the client's fallback and proves a
        # workflow_results step does not resolve its handle from plan.inputs.workflows.
        workflow_results_step(
            "read_run_handle_date_completed",
            RUN_HANDLE,
            {"selector": "completed_on", "completed_on": "2026-09-29", "status": "completed"},
        ),
        # Invalid server data on purpose: unknown result handles get a neutral user-facing label.
        workflow_results_step("read_missing_latest", MISSING_HANDLE, {"selector": "latest"}),
    ],
    "final_response": {
        "version": "orchestration-input-binding-v1", "step_id": "compose_answer",
        "output_name": "answer", "existing_result": None,
    },
    "plan_id": "plan_workflow_results_inputs",
    "run_id": "run_workflow_results_inputs",
    "turn_id": TURN,
    "revision": 0,
    "conversation_id": CONVERSATION,
    "user_id": "owner",
    "planner_contract_version": 2,
    "intent": {"summary": "", "complexity": "simple", "confidence": None},
    "assumptions": [],
    "approval": {
        "mode": "manual", "timeout_seconds": 10, "state": "pending", "approved_at": None,
        "approved_by": None, "edited": False,
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
            "handle": RUN_HANDLE, "name": "Weekly digest",
            "trigger_summary": "Mondays 08:00 America/New_York", "paused": False,
        }],
        "workflow_results": [
            {"handle": HOSTILE_HANDLE, "name": HOSTILE_NAME},
            {"handle": BETA_HANDLE, "name": BETA_NAME},
            {"handle": ALPHA_HANDLE, "name": ALPHA_NAME},
        ],
    },
    "outputs": [
        {"kind": "message"},
        {"kind": "markdown-v1", "source_step_id": "compose_answer", "name": "answer"},
        {"kind": "structured-v1", "source_step_id": "start_digest", "name": "run"},
        {"kind": "structured-v1", "source_step_id": "read_alpha_latest", "name": "result"},
        {"kind": "structured-v1", "source_step_id": "read_beta_failed", "name": "result"},
        {"kind": "structured-v1", "source_step_id": "read_hostile_date", "name": "result"},
        {"kind": "structured-v1", "source_step_id": "read_run_handle_date_completed", "name": "result"},
        {"kind": "structured-v1", "source_step_id": "read_missing_latest", "name": "result"},
    ],
    "status": "awaiting_approval",
    "planner_model": "gpt-4o",
    "planner": {"label": "gpt-4o", "source": "default"},
    "reasoning_adjustments": [],
}


def server_plan():
    return copy.deepcopy(SERVER_PLAN)


def stream(route, event):
    route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")


class WorkflowResultsApi:
    """The orchestration routes the card and run view call, recording unexpected requests."""

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
            plan.update(conversation_id=body["conversation_id"], turn_id=body["turn_id"])
            stream(route, {"type": "orchestration_plan", "plan": plan, "done": True})
            return
        if path == RUN and request.method == "POST":
            stream(route, {"done": True, "message_id": "saved-answer", "content": "Read workflow results."})
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


@pytest.fixture
def workflow_results_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = WorkflowResultsApi(editor_assets)
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
                version: '0.261.217', settings: {}, branding: { app_title: 'SimpleChat' },
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
                conversations: [{ id: spec.conversation, title: 'Workflow results' }],
                messages: [{ id: 'user-1', conversation_id: spec.conversation, role: 'user',
                    content: spec.request, metadata: { orchestration_turn_id: spec.turn } }],
            });
        }""",
        {"conversation": CONVERSATION, "turn": TURN, "theme": theme, "request": REQUEST},
    )


def mount_plan(page, api, plan, *, theme="light"):
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
    for step_id in RESULTS_STEP_IDS:
        expect(page.locator("#mount-b").locator(f'li[data-step-id="{step_id}"]')).to_be_visible()
    return card


def step(review, step_id):
    return review.locator(f'li[data-step-id="{step_id}"]')


def text_list(locator):
    return locator.evaluate_all("(nodes) => nodes.map((node) => node.textContent?.trim() || '')")


def assert_workflow_results_row(dl, workflow_name, run_text):
    expect(dl.locator("dd").nth(0)).to_have_text(workflow_name, use_inner_text=True)
    expect(dl.locator("dd").nth(1)).to_have_text(run_text, use_inner_text=True)


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_workflow_results_inputs_render_by_handle_and_selection(workflow_results_ui, theme, width):
    page, api = workflow_results_ui
    page.set_viewport_size({"width": width, "height": 900})
    mount_plan(page, api, server_plan(), theme=theme)

    review = page.locator("#mount-b")
    expect(review.get_by_test_id("orchestration-workflow-results-input")).to_have_count(len(RESULTS_STEP_IDS))
    expect(step(review, "compose_answer").get_by_test_id("orchestration-workflow-results-input")).to_have_count(0)
    workflow_run = step(review, "start_digest")
    expect(workflow_run.get_by_test_id("orchestration-workflow-results-input")).to_have_count(0)
    expect(workflow_run.get_by_test_id("orchestration-workflow-run-input")).to_have_count(1)

    expected_rows = {
        "read_alpha_latest": (ALPHA_NAME, "Latest run"),
        "read_beta_failed": (BETA_NAME, "Latest failed run"),
        "read_hostile_date": (HOSTILE_NAME, "Run finished on 2026-09-29"),
        "read_run_handle_date_completed": ("Workflow details unavailable", "Completed run finished on 2026-09-29"),
        "read_missing_latest": ("Workflow details unavailable", "Latest run"),
    }
    for step_id, (workflow_name, run_text) in expected_rows.items():
        results = step(review, step_id).get_by_test_id("orchestration-workflow-results-input")
        expect(results).to_have_count(1)
        assert_workflow_results_row(results, workflow_name, run_text)
        box = results.bounding_box()
        assert box is not None, step_id
        assert box["x"] >= 0 and box["x"] + box["width"] <= width, (step_id, box, width)

    hostile = step(review, "read_hostile_date").get_by_test_id("orchestration-workflow-results-input")
    expect(hostile.get_by_text(HOSTILE_NAME, exact=True)).to_be_visible()
    for tag in ("b", "script", "img"):
        expect(hostile.locator(tag)).to_have_count(0)

    body_text = page.locator("body").inner_text()
    for handle in RESULTS_HANDLES:
        assert handle not in body_text, handle


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_workflow_results_arguments_are_hidden_but_generic_arguments_still_render(workflow_results_ui, theme, width):
    page, api = workflow_results_ui
    page.set_viewport_size({"width": width, "height": 900})
    mount_plan(page, api, server_plan(), theme=theme)

    review = page.locator("#mount-b")
    compose = step(review, "compose_answer")
    compose_terms = text_list(compose.locator("dt"))
    assert "instruction" in compose_terms, compose_terms
    expect(compose.locator("dd").filter(has_text=COMPOSE_INSTRUCTION)).to_be_visible()
    workflow_run_terms = text_list(step(review, "start_digest").locator("dt"))
    assert "workflow" not in workflow_run_terms, workflow_run_terms

    for step_id in RESULTS_STEP_IDS:
        terms = text_list(step(review, step_id).locator("dt"))
        for key in RESULT_ARGUMENT_KEYS:
            assert key not in terms, (step_id, terms)

    body_text = page.locator("body").inner_text()
    for handle in RESULTS_HANDLES:
        assert handle not in body_text, handle


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
