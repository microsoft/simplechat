# test_v2_workflow_plan_replay_card.py
"""
Real-component browser tests for saving a completed chat orchestration plan as a replay workflow.
Version: 0.261.338
Implemented in: 0.261.308
Calendar message action implemented in: 0.261.338
Refs: microsoft/simplechat#1550, microsoft/simplechat#1543

The production MessageList, PlanReplaySaveCard, WorkflowEditorDialog and WorkflowRunHistory run in
Chromium with production CSS. HTTP routes are stubbed at the plan-replay, workflow editor-options,
and workflow run-history boundaries. The shared empty pending-actions list stub answers V2's
conversation read without adding unrelated requests to the replay assertions.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_workflow_plan_replay_card.py -q
"""

import copy
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import functions_workflow_editor  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from v2_pending_action_stubs import is_pending_actions_list, pending_actions_payload  # noqa: E402


pytestmark = pytest.mark.ui
IMPLEMENTED_IN = "0.261.308"
ACTION_IMPLEMENTED_IN = "0.261.338"
CONVERSATION = "plan-replay-chat"
RUN_ID = "plan-replay-run"
WORKFLOW_ID = "plan-replay-workflow"
WORKFLOW_RUN_ID = "plan-replay-workflow-run"
HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
PREVIEW_PATH = f"/api/v2/orchestration/runs/{RUN_ID}/plan-replay"
EDITOR_OPTIONS_PATH = "/api/user/workflows/editor-options"
WORKFLOW_HREF = f"/workspace/workflows?workflow_id={WORKFLOW_ID}"
HOSTILE_REQUEST = '<img src=x onerror="window.__hostile = 1"> summarize <script>bad()</script>'
HOSTILE_TITLE = '"><svg onload="window.__hostile = 2">Find invoices'
HOSTILE_WORKFLOW = '<img src=x onerror="window.__hostile = 3"> Replay invoices'
STEP_REFUSAL = "Step 1 (Search the web) needs your signed-in session, which a repeated run doesn't have."
PLAN_REFUSAL = "This plan delivers something a saved workflow can't create."
ALERT_NOTICE = "If a run fails, you'll get a 'Run failed' notification in the bell. You can change this in the workflow's alerts."


def editor_options():
    return functions_workflow_editor.build_workflow_editor_options(
        scope_type="personal", scope_id="plan-replay-tester", can_manage=True, max_tasks=5, agents=[], endpoints=[],
        default_model={"label": "Default GPT", "valid": True},
    )


def preview(eligible=True):
    # Server-shaped refusals: a step refusal already starts with "Step N (label)"; a whole-plan one is step 0.
    refusals = [] if eligible else [
        {"code": "role_required", "step_number": 1, "step_id": "web", "capability_id": "web_search",
         "message": STEP_REFUSAL},
        {"code": "capability_not_replayable", "step_number": 0, "step_id": "", "capability_id": "",
         "message": PLAN_REFUSAL},
    ]
    first_step = (
        {"number": 1, "step_id": "search", "title": HOSTILE_TITLE, "capability_id": "document_search",
         "capability_label": "Search documents", "enabled": True}
        if eligible else
        {"number": 1, "step_id": "web", "title": HOSTILE_TITLE, "capability_id": "web_search",
         "capability_label": "Search the web", "enabled": True}
    )
    return {
        "eligible": eligible,
        "request": HOSTILE_REQUEST,
        "steps": [
            first_step,
            {"number": 2, "step_id": "compose", "title": "Write answer", "capability_id": "compose",
             "capability_label": "Prepare content", "enabled": True},
        ],
        "refusals": refusals,
        "plan_sha256": HASH,
        "time_handling": "frozen_with_run_time_line",
        "time_zone": "America/New_York",
        "min_interval_seconds": 900,
        "allowlist_version": "plan-replay-allowlist-v1",
        "max_steps": 8,
    }


def replay_task():
    return {
        "id": "task-replay",
        "type": "plan_replay",
        "name": "Repeat saved plan",
        "instructions": HOSTILE_REQUEST,
        "runner": {"type": "inherit"},
        "plan_replay": {
            "version": 1,
            "allowlist_version": "plan-replay-allowlist-v1",
            "request": HOSTILE_REQUEST,
            "frozen_plan": {"steps": [
                {"step_id": "search", "title": HOSTILE_TITLE, "capability_id": "document_search", "arguments": {}, "enabled": True},
                {"step_id": "compose", "title": "Write answer", "capability_id": "compose", "arguments": {}, "enabled": True},
            ]},
            "frozen_seeds": {},
            "plan_sha256": HASH,
            "approval": {"approved_by": "plan-replay-tester", "approved_at": "2026-10-08T10:00:00Z", "plan_sha256": HASH},
            "provenance": {
                "source_run_id": RUN_ID, "source_conversation_id": CONVERSATION, "created_by": "plan-replay-tester",
                "frozen_at": "2026-10-08T10:00:00Z", "time_handling": "frozen_with_run_time_line",
                "time_zone": "America/New_York",
            },
        },
    }


def replay_workflow(name=HOSTILE_WORKFLOW):
    return {
        "id": WORKFLOW_ID,
        "definition_version": 2,
        "definition_revision": "rev-1",
        "name": name,
        "description": "",
        "runner_type": "model",
        "chat_capabilities_enabled": False,
        "trigger_type": "manual",
        "schedule": {"unit": "hours", "value": 24},
        "is_enabled": False,
        "error_handling": {"strategy": "halt", "retry_count": 0},
        "tasks": [replay_task()],
        "reference_inputs": [],
        "durable_execution": False,
    }


def answer(conversation=CONVERSATION, *, flags=True, masked=False, outcome="completed", capabilities=("compose",)):
    metadata = {"orchestration": {
        "run_id": RUN_ID, "turn_id": "turn-1", "outcome": outcome, "finalization_status": "saved",
        "message_saved": True,
        "plan_summary": {"plan_id": "plan-1", "turn_id": "turn-1", "status": "completed",
                         "intent_summary": "Save this plan", "step_count": 2,
                         "capabilities_used": list(capabilities)},
    }}
    if masked:
        metadata["masked_ranges"] = [{"start": 0, "end": 5}]
    return [
        {"id": "user-1", "conversation_id": conversation, "role": "user", "content": "Summarize invoices.",
         "metadata": {"orchestration_turn_id": "turn-1"}},
        {"id": "answer-1", "conversation_id": conversation, "role": "assistant", "content": "Done.",
         "metadata": metadata},
    ]


class PlanReplayApi:
    def __init__(self, assets):
        self.assets = assets
        self.requests = []
        self.unexpected = []
        self.preview = preview()
        self.preview_paths = {PREVIEW_PATH}
        self.preview_error = None
        self.save_created = True
        self.expected_errors = set()

    def expect(self, condition, description):
        if not condition:
            self.unexpected.append(description)

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path == HARNESS:
            styles = "".join(
                f'<link rel="stylesheet" href="{url}">'
                for url in self.assets if url.endswith(".css")
            )
            document = self.assets[path].read_text(encoding="utf-8")
            route.fulfill(content_type="text/html", body=document.replace("</head>", styles + "</head>"))
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        if is_pending_actions_list(request.method, path):
            route.fulfill(json=pending_actions_payload())
            return
        if request.method == "GET" and path == "/api/action-credentials/pending":
            route.fulfill(json={"requests": []})
            return
        query = parse_qs(parsed.query)
        body = request.post_data_json if request.method == "POST" else None
        self.requests.append({"method": request.method, "path": path, "query": query, "body": body})
        if path == "/api/message/answer-1/metadata" and request.method == "GET":
            route.fulfill(json=answer()[-1])
            return
        if path in self.preview_paths and request.method == "GET":
            self.expect(query == {"conversation_id": [CONVERSATION]}, f"preview query {query}")
            if self.preview_error:
                route.fulfill(status=503, json=self.preview_error)
                return
            route.fulfill(json=copy.deepcopy(self.preview))
            return
        if path == PREVIEW_PATH and request.method == "POST":
            self.expect(body["conversation_id"] == CONVERSATION, f"save conversation {body}")
            self.expect(body["plan_sha256"] == HASH, f"save hash {body}")
            workflow = replay_workflow(body.get("name") or HOSTILE_WORKFLOW)
            workflow["is_enabled"] = body.get("enabled") is True
            workflow["trigger_type"] = body.get("trigger_type", "manual")
            if body.get("schedule"):
                workflow["schedule"] = body["schedule"]
            route.fulfill(status=201 if self.save_created else 200,
                          json={"ok": True, "workflow": workflow, "created": self.save_created})
            return
        if path == EDITOR_OPTIONS_PATH and request.method == "GET":
            route.fulfill(json=editor_options())
            return
        workflow_lists = {
            f"/api/v2/orchestration/runs/{RUN_ID}/workflow-proposals": "proposals",
            f"/api/v2/orchestration/runs/{RUN_ID}/workflow-runs": "workflow_runs",
            f"/api/v2/orchestration/runs/{RUN_ID}/workflow-handoffs": "handoffs",
        }
        if path in workflow_lists and request.method == "GET":
            route.fulfill(json={"run_id": RUN_ID, workflow_lists[path]: []})
            return
        if path == "/api/user/workflows/file-sync-sources" and request.method == "GET":
            route.fulfill(json={"sources": [], "file_sync_enabled": True})
            return
        if path == "/api/workflows/m365-run-as-users" and request.method == "GET":
            route.fulfill(json={"users": []})
            return
        if path == f"/api/user/workflows/{WORKFLOW_ID}/runs" and request.method == "GET":
            route.fulfill(json={"runs": [{"id": WORKFLOW_RUN_ID, "workflow_id": WORKFLOW_ID, "status": "completed",
                                           "started_at": "2026-10-08T10:00:00Z", "completed_at": "2026-10-08T10:01:00Z"}]})
            return
        if path == f"/api/user/workflows/{WORKFLOW_ID}/runs/{WORKFLOW_RUN_ID}/items" and request.method == "GET":
            # Mirrors the runner: outputs hold only result refs, the typed projection sits on the item.
            route.fulfill(json={"items": [{
                "id": "item-1", "item_type": "task", "task_id": "task-replay", "label": "Repeat saved plan",
                "status": "completed", "workflow_result": {"outputs": {"json": {
                    "kind": "json", "result_ref": {"storage": "blob", "sha256": HASH},
                }}},
                "plan_replay": {
                    "contract": "plan-replay-result-v1", "orchestration_run_id": RUN_ID,
                    "conversation_id": CONVERSATION, "plan_sha256": HASH, "status": "completed", "outcome": "completed",
                    "steps": [{"step_id": "compose", "capability_id": "compose", "label": "Prepare content", "status": "completed"}],
                    "final_response": {"message_id": "message-1", "text": "Final <script>inert</script> answer",
                                       "truncated": True},
                    "artifacts": [{"id": "image-1", "kind": "image"}],
                },
            }]})
            return
        if path.endswith("/result") and request.method == "GET":
            route.fulfill(status=404, json={"error": "No stored text result"})
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})


@pytest.fixture
def plan_replay_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = PlanReplayApi(editor_assets)
    errors = []
    dialogs = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

    def console_error(message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        if any(path == expected and str(status) in message.text for expected, status in api.expected_errors):
            return
        errors.append(message.text)

    page.on("console", console_error)
    try:
        yield page, api
        assert page.evaluate("() => window.__hostile ?? null") is None
    finally:
        context.close()
    assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
    assert not errors, f"Unexpected browser errors: {errors}"
    assert not dialogs, f"Unexpected browser dialogs: {dialogs}"


def mount_messages(page, *, feature=True, features=None, messages=None, kind="personal", conversation=CONVERSATION):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.338', settings: {}, branding: { app_title: 'SimpleChat' },
                features: {
                    enable_chat_orchestration: true,
                    allow_user_workflows: true,
                    enable_workflow_plan_replay: spec.feature,
                    enable_user_feedback: true,
                    ...spec.features,
                },
                user: { id: 'plan-replay-tester', display_name: 'Plan Replay Tester' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: spec.kind,
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [], messages: spec.messages,
                conversations: [{ id: spec.conversation, title: 'Plan replay' }],
            });
            H.stores.orchestration.useOrchestrationStore.setState({
                runRecovery: Object.fromEntries(spec.messages
                    .filter((message) => message.metadata?.orchestration?.run_id)
                    .map((message) => [message.metadata.orchestration.run_id, {
                        ...message.metadata.orchestration, detailLoaded: true,
                    }])),
            });
            H.mount('mount-a', 'MessageList', {}, { strictMode: true });
        }""",
        {"feature": feature, "features": features or {}, "conversation": conversation, "kind": kind,
         "messages": messages if messages is not None else answer(conversation)},
    )
    expect(page.get_by_text("Summarize invoices.")).to_be_visible()


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)
    assert_app_version_at_least(ACTION_IMPLEMENTED_IN)


def test_card_absent_when_feature_flag_is_off(plan_replay_ui):
    page, api = plan_replay_ui
    mount_messages(page, feature=False)
    expect(page.get_by_role("button", name="Repeat on a schedule")).to_have_count(0)
    assert not api.requests


def test_card_fetches_on_click_discloses_steps_and_saves_paused(plan_replay_ui):
    page, api = plan_replay_ui
    mount_messages(page)
    page.locator("#message-answer-1").hover()
    expect(page.get_by_role("button", name="Repeat on a schedule")).to_be_visible()
    assert not api.requests

    page.get_by_role("button", name="Repeat on a schedule").click()
    expect(page.get_by_text(HOSTILE_REQUEST)).to_be_visible()
    expect(page.get_by_text(HOSTILE_TITLE)).to_be_visible()
    expect(page.get_by_text("Search documents")).to_be_visible()
    expect(page.get_by_text("Prepare content")).to_be_visible()
    expect(page.get_by_text("At least every 15 minutes.")).to_be_visible()
    expect(page.get_by_text(ALERT_NOTICE, exact=True)).to_be_visible()
    assert [request["method"] for request in api.requests[:2]] == ["GET", "GET"]

    page.get_by_role("button", name="Save workflow").click()
    expect(page.get_by_text("Saved as a paused workflow.")).to_be_visible()
    expect(page.get_by_role("link", name="Open workflow")).to_have_attribute("href", WORKFLOW_HREF)
    post = [request for request in api.requests if request["method"] == "POST"][0]
    assert post["body"]["enabled"] is False
    assert post["body"]["trigger_type"] == "manual"


@pytest.mark.parametrize("width,dark", [(1440, False), (390, True)])
def test_calendar_action_reveals_on_hover_and_keyboard_and_expands_inline(plan_replay_ui, width, dark):
    page, api = plan_replay_ui
    page.set_viewport_size({"width": width, "height": 900})
    mount_messages(page)
    page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", dark)
    row = page.locator("#message-answer-1")
    actions = row.get_by_role("group", name="Message actions")
    calendar = actions.get_by_role("button", name="Repeat on a schedule", exact=True)
    panel = row.get_by_role("region", name="Save chat plan as workflow")
    reveal = actions.locator("..")
    page.mouse.move(0, 0)
    expect(reveal).to_have_css("opacity", "0")
    expect(panel).to_have_count(0)
    expect(calendar).to_have_attribute("aria-expanded", "false")
    expect(calendar).to_have_attribute("title", "Repeat on a schedule")
    expect(calendar.locator("svg.lucide-calendar-clock")).to_have_count(1)
    assert calendar.text_content().strip() == ""
    assert not api.requests

    row.hover()
    expect(reveal).to_have_css("opacity", "1")
    expect(actions.get_by_role("button", name="Copy", exact=True)).to_be_visible()
    expect(actions.get_by_role("button", name="Retry", exact=True)).to_be_visible()
    expect(actions.get_by_role("button", name="Good response")).to_be_visible()
    assert not api.requests
    page.mouse.move(0, 0)
    actions.get_by_role("button", name="Copy", exact=True).focus()
    page.keyboard.press("Tab")
    expect(actions.get_by_role("button", name="Retry", exact=True)).to_be_focused()
    page.keyboard.press("Tab")
    expect(calendar).to_be_focused()
    expect(reveal).to_have_css("opacity", "1")
    page.keyboard.press("Enter")
    expect(panel).to_be_visible()
    expect(calendar).to_have_attribute("aria-expanded", "true")
    expect(panel).to_have_attribute("id", calendar.get_attribute("aria-controls"))
    expect(panel.get_by_text(HOSTILE_REQUEST)).to_be_visible()
    assert actions.locator("section").count() == 0
    assert row.evaluate("(row) => row.scrollWidth <= row.clientWidth") is True
    assert calendar.evaluate("(el) => el.getBoundingClientRect().right <= innerWidth") is True
    panel.get_by_role("textbox", name="Workflow name").fill("My recurring summary")
    actions.get_by_role("button", name="Message details").click()
    expect(row.get_by_text("Message ID", exact=True)).to_be_visible()
    expect(row.get_by_role("button", name="Close message details")).to_be_visible()
    expect(panel).to_be_visible()
    page.mouse.move(0, 0)
    expect(reveal).to_have_css("opacity", "1")

    screenshot = Path(__file__).resolve().parent / "artifacts" / f"plan-replay-calendar-{width}.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot), full_page=True)
    panel.get_by_role("button", name="Collapse", exact=True).click()
    expect(panel).to_have_count(0)
    expect(calendar).to_be_focused()
    expect(calendar).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("Space")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("textbox", name="Workflow name")).to_have_value("My recurring summary")
    assert len([request for request in api.requests if request["path"] == PREVIEW_PATH]) == 2
    calendar.click()
    expect(panel).to_have_count(0)


@pytest.mark.parametrize("disabled", [
    "enable_workflow_plan_replay", "enable_chat_orchestration", "allow_user_workflows",
])
def test_calendar_requires_all_prerequisite_flags(plan_replay_ui, disabled):
    page, api = plan_replay_ui
    mount_messages(page, features={disabled: False})
    expect(page.get_by_role("button", name="Repeat on a schedule")).to_have_count(0)
    assert not api.requests


@pytest.mark.parametrize("case", [
    "shared", "inactive", "user", "masked", "fully-masked", "missing-run",
    "failed", "partial", "cancelled", "running",
    "workflow_propose", "workflow_run", "workflow_handoff",
])
def test_calendar_preserves_answer_eligibility(plan_replay_ui, case):
    page, api = plan_replay_ui
    messages = answer()
    metadata = messages[-1]["metadata"]
    if case == "user":
        messages[-1]["role"] = "user"
    elif case == "masked":
        metadata["masked_ranges"] = [{"start": 0, "end": 2}]
    elif case == "fully-masked":
        metadata["masked"] = True
    elif case == "missing-run":
        del metadata["orchestration"]["run_id"]
    elif case in {"failed", "partial", "cancelled", "running"}:
        metadata["orchestration"]["outcome"] = case
    elif case.startswith("workflow_"):
        metadata["orchestration"]["plan_summary"]["capabilities_used"] = [case]
    mount_messages(page, messages=messages,
                   kind="collaborative" if case == "shared" else "personal",
                   conversation="another-chat" if case == "inactive" else CONVERSATION)
    expect(page.get_by_role("button", name="Repeat on a schedule")).to_have_count(0)
    expect(page.get_by_role("region", name="Save chat plan as workflow")).to_have_count(0)
    assert not [request for request in api.requests if request["path"] in {PREVIEW_PATH, EDITOR_OPTIONS_PATH}]


def test_open_panel_closes_when_answer_becomes_masked_or_changes_run(plan_replay_ui):
    page, api = plan_replay_ui
    mount_messages(page)
    row = page.locator("#message-answer-1")
    calendar = row.get_by_role("button", name="Repeat on a schedule")
    panel = row.get_by_role("region", name="Save chat plan as workflow")
    row.hover()
    calendar.click()
    expect(panel.get_by_role("textbox", name="Workflow name")).to_be_visible()
    panel.get_by_role("textbox", name="Workflow name").fill("Old plan name")

    masked = answer(masked=True)
    page.evaluate("(messages) => window.OrchHarness.stores.chat.useChatStore.setState({ messages })", masked)
    expect(calendar).to_have_count(0)
    expect(panel).to_have_count(0)
    page.evaluate("(messages) => window.OrchHarness.stores.chat.useChatStore.setState({ messages })", answer())
    expect(calendar).to_have_attribute("aria-expanded", "false")
    row.hover()
    calendar.click()
    expect(panel.get_by_role("textbox", name="Workflow name")).to_be_visible()
    panel.get_by_role("textbox", name="Workflow name").fill("Another old name")

    next_messages = answer()
    next_messages[-1]["metadata"]["orchestration"]["run_id"] = RUN_ID + "-next"
    next_path = PREVIEW_PATH.replace(RUN_ID, RUN_ID + "-next")
    api.preview_paths.add(next_path)
    page.evaluate("(messages) => window.OrchHarness.stores.chat.useChatStore.setState({ messages })", next_messages)
    expect(panel).to_have_count(0)
    expect(calendar).to_have_attribute("aria-expanded", "false")
    row.hover()
    calendar.click()
    expect(panel.get_by_role("textbox", name="Workflow name")).not_to_have_value("Another old name")
    expect(panel.get_by_text(HOSTILE_REQUEST)).to_be_visible()
    assert any(request["path"] == next_path for request in api.requests)


def test_calendar_preview_failure_stays_visible_and_can_be_collapsed(plan_replay_ui):
    page, api = plan_replay_ui
    api.preview_error = {"error": "Provider details must not reach the UI", "code": "unavailable"}
    api.expected_errors.add((PREVIEW_PATH, 503))
    mount_messages(page)
    page.locator("#message-answer-1").hover()
    calendar = page.get_by_role("button", name="Repeat on a schedule")
    calendar.click()
    panel = page.get_by_role("region", name="Save chat plan as workflow")
    expect(panel.get_by_role("alert")).to_be_visible()
    expect(page.get_by_text("Provider details must not reach the UI")).to_have_count(0)
    expect(panel.get_by_role("button", name="Save workflow")).to_have_count(0)
    panel.get_by_role("button", name="Collapse", exact=True).click()
    expect(panel).to_have_count(0)
    expect(calendar).to_be_focused()


def test_ineligible_preview_shows_refusals_without_save_form(plan_replay_ui):
    page, api = plan_replay_ui
    api.preview = preview(eligible=False)
    mount_messages(page)
    page.locator("#message-answer-1").hover()
    page.get_by_role("button", name="Repeat on a schedule").click()
    notes = page.get_by_role("status").filter(has_text="This plan has replay notes:")
    expect(notes.get_by_role("listitem")).to_have_text([STEP_REFUSAL, f"Whole plan: {PLAN_REFUSAL}"])
    expect(page.get_by_text("Step 1: Step 1")).to_have_count(0)
    expect(page.get_by_role("button", name="Save workflow")).to_have_count(0)


def test_existing_state_and_hostile_strings_stay_inert(plan_replay_ui):
    page, api = plan_replay_ui
    api.save_created = False
    mount_messages(page)
    page.locator("#message-answer-1").hover()
    page.get_by_role("button", name="Repeat on a schedule").click()
    page.get_by_role("textbox", name="Workflow name").fill(HOSTILE_WORKFLOW)
    page.get_by_role("button", name="Save workflow").click()
    expect(page.get_by_text("This plan is already saved as a workflow.")).to_be_visible()
    expect(page.locator("img")).to_have_count(0)
    expect(page.locator("script").filter(has_text="bad()")).to_have_count(0)
    expect(page.locator("svg[onload]")).to_have_count(0)


def test_editor_read_only_saved_plan_summary_still_allows_name_edit(plan_replay_ui):
    page, _api = plan_replay_ui
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.mount('mount-a', 'WorkflowEditorDialog', {
                workflow: spec.workflow,
                original: spec.workflow,
                options: spec.options,
                scope: { type: 'personal' },
                open: true,
                onClose: () => {},
                onSaved: (workflow) => { window.__savedWorkflow = workflow; },
            }, { strictMode: true });
        }""",
        {"workflow": replay_workflow(), "options": editor_options()},
    )
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("Saved chat plan")).to_be_visible()
    expect(dialog.get_by_text("The saved plan can't be edited.")).to_be_visible()
    expect(dialog.get_by_text(HOSTILE_TITLE)).to_be_visible()
    expect(dialog.get_by_text("Runner type")).to_have_count(0)
    expect(dialog.get_by_text("Task IDs stay stable")).to_have_count(0)
    dialog.get_by_role("textbox", name="Workflow name").fill("Updated replay name")
    expect(dialog.get_by_role("textbox", name="Workflow name")).to_have_value("Updated replay name")


def test_run_inspector_renders_typed_replay_result(plan_replay_ui):
    page, _api = plan_replay_ui
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.reset();
            H.mount('mount-a', 'WorkflowRunHistory', {
                scope: { type: 'personal' }, workflowId: 'plan-replay-workflow', initialRunId: 'plan-replay-workflow-run',
            }, { strictMode: true });
        }"""
    )
    expect(page.get_by_text("Saved chat plan run")).to_be_visible()
    expect(page.get_by_text("Prepare content")).to_be_visible()
    expect(page.get_by_text("Final <script>inert</script> answer")).to_be_visible()
    expect(page.get_by_text("image: image-1")).to_be_visible()
    expect(page.get_by_text("The full answer is in the workflow's conversation.", exact=False)).to_be_visible()
