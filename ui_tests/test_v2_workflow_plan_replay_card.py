# test_v2_workflow_plan_replay_card.py
"""
Real-component browser tests for saving a completed chat orchestration plan as a replay workflow.
Version: 0.261.308
Implemented in: 0.261.308
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
from urllib.parse import parse_qs, unquote, urlsplit

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
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        if is_pending_actions_list(request.method, path):
            route.fulfill(json=pending_actions_payload())
            return
        query = parse_qs(parsed.query)
        body = request.post_data_json if request.method == "POST" else None
        self.requests.append({"method": request.method, "path": path, "query": query, "body": body})
        if path == PREVIEW_PATH and request.method == "GET":
            self.expect(query == {"conversation_id": [CONVERSATION]}, f"preview query {query}")
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


def mount_messages(page, *, feature=True, messages=None, kind="personal", conversation=CONVERSATION):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.308', settings: {}, branding: { app_title: 'SimpleChat' },
                features: {
                    enable_chat_orchestration: true,
                    allow_user_workflows: true,
                    enable_workflow_plan_replay: spec.feature,
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
            H.mount('mount-a', 'MessageList', {}, { strictMode: true });
        }""",
        {"feature": feature, "conversation": conversation, "kind": kind,
         "messages": messages if messages is not None else answer(conversation)},
    )
    expect(page.get_by_text("Summarize invoices.")).to_be_visible()


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


def test_card_absent_when_feature_flag_is_off(plan_replay_ui):
    page, api = plan_replay_ui
    mount_messages(page, feature=False)
    expect(page.get_by_role("button", name="Repeat on a schedule")).to_have_count(0)
    assert not api.requests


def test_card_fetches_on_click_discloses_steps_and_saves_paused(plan_replay_ui):
    page, api = plan_replay_ui
    mount_messages(page)
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


def test_ineligible_preview_shows_refusals_without_save_form(plan_replay_ui):
    page, api = plan_replay_ui
    api.preview = preview(eligible=False)
    mount_messages(page)
    page.get_by_role("button", name="Repeat on a schedule").click()
    notes = page.get_by_role("status").filter(has_text="This plan has replay notes:")
    expect(notes.get_by_role("listitem")).to_have_text([STEP_REFUSAL, f"Whole plan: {PLAN_REFUSAL}"])
    expect(page.get_by_text("Step 1: Step 1")).to_have_count(0)
    expect(page.get_by_role("button", name="Save workflow")).to_have_count(0)


def test_existing_state_and_hostile_strings_stay_inert(plan_replay_ui):
    page, api = plan_replay_ui
    api.save_created = False
    mount_messages(page)
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
