# test_v2_orchestration_workflow_handoff_card.py
"""
Real-component browser tests for the workflow hand-off card under an orchestration answer.
Version: 0.261.253
Implemented in: 0.261.288
Refs: microsoft/simplechat#1549, microsoft/simplechat#1543

The production MessageList, WorkflowHandoffCards, ConfirmDialog and WorkflowEditorDialog run in
Chromium with the production CSS. Only HTTP boundaries are stubbed, in the shapes the server's
hand-off routes return:

- The list items follow `_assess`, `_actions` and `_describe` in
  `functions_orchestration_workflow_handoff_decisions.py`. PENDING, QUEUED, the accept answer and
  DRAFT are the real routes' answers for a one-document contract review, captured through
  `functional_tests/test_orchestration_workflow_handoff_routes.py`'s harness.
- The refusals are `HandoffError.payload()`: the server's own `ERROR_MESSAGES` sentence, the
  code, `errors[]`, and `state` and `reason` when set. The route decorators' refusals carry no
  code, exactly as `enabled_required` and `workflow_user_required` send them.
- The reason, run-conflict and disclosure text comes from the server modules themselves.

The server side of every decision, including an edited accept through the real draft and save
functions, is covered by the functional tests named in the hand-off feature documentation.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_workflow_handoff_card.py -q
"""

import ast
import copy
import re
import sys
from datetime import datetime, timedelta, timezone
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

import functions_orchestration_workflow_handoffs as handoffs  # noqa: E402  (the hand-off reason text)
import functions_orchestration_workflow_runs as workflow_runs  # noqa: E402  (the run-conflict reason text)
import functions_workflow_editor  # noqa: E402  (the editor options the server sends)
import functions_workflow_handoff_builder as builder  # noqa: E402  (the disclosure the card shows)
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
DECISIONS = "functions_orchestration_workflow_handoff_decisions"
ERROR_MESSAGES = server_literal(DECISIONS, "ERROR_MESSAGES")
ERROR_STATUS = server_literal(DECISIONS, "_ERROR_STATUS")
URL_ACCESS_NOTE = server_literal("functions_orchestration_workflow_proposals", "URL_ACCESS_NOTE")
LEGACY_PLAN_MESSAGE = server_literal("functions_orchestration_schema", "LEGACY_PLAN_MESSAGE")
HANDOFF_EDIT_LOOP_MESSAGE = server_literal("functions_workflow_drafts", "HANDOFF_EDIT_LOOP_MESSAGE")

CONVERSATION = "handoff-chat"
TURN = "handoff-turn"
RUN_ID = "handoff-run-1"
HANDOFF_ID = "f1712e2d-af01-5e8a-af14-f7b4911c9bc8"
WORKFLOW_ID = "264a4cf4-de4a-50ee-a30f-fb13bfa84df9"
WORKFLOW_RUN_ID = "78a1c0eb-0025-511d-b225-c6b28c39ee8a"
CREATED_AT = "2026-10-07T02:43:07+00:00"
EXPIRES_AT = "2026-10-21T02:43:07+00:00"
NAME = "Review contracts"
EDITED_NAME = "Review renewal terms"
HANDOFFS_PATH = f"/api/v2/orchestration/runs/{RUN_ID}/workflow-handoffs"
ACCEPT_PATH = f"{HANDOFFS_PATH}/{HANDOFF_ID}/accept"
DENY_PATH = f"{HANDOFFS_PATH}/{HANDOFF_ID}/deny"
EDITOR_OPTIONS_PATH = "/api/user/workflows/editor-options"
WORKFLOW_HREF = f"/workspace/workflows?workflow_id={WORKFLOW_ID}"
RUN_HREF = f"/workspace/workflows?workflow_id={WORKFLOW_ID}&run_id={WORKFLOW_RUN_ID}"
CLOCK_START = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

# V2's own copy, for what the server sends no text for.
EDIT_LIMITS = (
    "Edits keep the trigger manual and keep the For each over documents or a workspace search. "
    "Tasks can use only your own local agents, and URL Access and Run as aren't available."
)
DRAFT_RETAINED = "Your draft has been retained."
DELIVERY_TEXT = "The run's outcome is posted in this chat when it ends."
STATIC_FOOTNOTE = "Status when this message loaded. Open the run for its progress and results."
WORKFLOWS_OFF = "Personal workflows are turned off in SimpleChat right now."
WORKFLOW_ACCESS = "You need workflow access to use this hand-off. Ask your administrator."
V2_REASON_TEXT = {
    "workflow_handoff_disabled": "Handing work off to a workflow is turned off, so this hand-off is not available.",
    "workflow_results_disabled": "Workflow results in chat are turned off, so this hand-off is not available.",
    "workflow_role_required": "You need workflow access to use this hand-off.",
    "workflow_shared_conversation": "Workflow hand-offs are available only in your own conversations.",
    "content_review": "This response is in content review, so its hand-off cannot be used.",
}
GATE_REASONS = (
    "workflow_handoff_disabled", "workflow_results_disabled", "workflow_role_required",
    "workflow_shared_conversation",
)
# A hand-off the server could describe but not prepare: unavailable or invalid, per `_status_for`.
SIDECAR_STATES = {
    "workflow_context_unavailable": "unavailable",
    "handoff_unavailable": "unavailable",
    "handoff_sources_unavailable": "unavailable",
    "handoff_prepare_failed": "unavailable",
    "workflow_handoff_invalid": "invalid",
    "handoff_loop_limit": "invalid",
    "handoff_agent_unsupported": "invalid",
}

HOSTILE_NAME = '<img src=x onerror="window.__hostile = 1"> Review <b>contracts</b>'
HOSTILE_DESCRIPTION = "<script>window.__hostile = 2</script>Lists the renewal terms of every contract."
HOSTILE_TITLE = "Review <i>one</i> contract"
HOSTILE_AGENT = '<img src=x onerror="window.__hostile = 3">Contract helper'
HOSTILE_SCOPE = '<img src=x onerror="window.__hostile = 4">Legal <b>team</b>'
LEGAL_HANDLE = "scope-legal-3f2a91"
PERSONAL_HANDLE = "scope-personal-9c0d12"

# The list route's summary and disclosure for the one-document contract review.
SUMMARY = {
    "alerts": {"mode": "every_run", "severity": "info"},
    "description": "",
    "durable": True,
    "name": NAME,
    "one_time": True,
    "tasks": [
        {"agent_name": "", "runner": "model", "title": "Review one"},
        {"agent_name": "", "runner": "model", "title": "Report"},
    ],
}
DISCLOSURE = {
    "count": 1, "kind": "documents", "limit_behavior": "exact", "scope_count": 0, "scope_names": [],
    "text": "1 document",
}

NONE_ACTION = {
    "active_group_ids": [], "active_public_workspace_id": [], "analysis_mode": "combined", "doc_scope": "all",
    "document_ids": [], "left_document_id": "", "max_retries_per_window": 1, "recent_window_minutes": 10,
    "right_document_ids": [], "target_mode": "selected", "type": "none", "window_percent": None,
    "window_size": None, "window_unit": "pages",
}
ITERABLE = {
    "documents": [{"document_id": "5c1e7b1f-2d3e-4f60-9bac-00000000d001", "scope_type": "personal"}],
    "kind": "documents",
}
# The draft route's answer for the contract review, as the server returns it.
DRAFT = {
    "alert_evaluation": {"on_error": "skip"},
    "alert_mode": "rules",
    "alert_priority": "none",
    "alert_rules": [
        {"condition": {"statuses": ["completed"], "type": "run_status"}, "delivery": "notify_only",
         "enabled": True, "id": "6f6c76b6-820e-506a-a518-d57e8d2d761f", "name": "Run completed", "order": 1,
         "scope": {"task_id": "", "type": "final"}, "severity": "info"},
        {"condition": {"statuses": ["failed", "completed_with_task_errors"], "type": "run_status"},
         "delivery": "notify_only", "enabled": True, "id": "c677bfd6-2f6e-57b7-9563-db16fb590a78",
         "name": "Run had errors", "order": 2, "scope": {"task_id": "", "type": "final"}, "severity": "low"},
    ],
    "analyze": {
        "active_group_ids": [], "active_public_workspace_id": [], "analysis_mode": "combined", "doc_scope": "all",
        "document_ids": [], "enabled": False, "max_retries_per_window": 1, "recent_window_minutes": 10,
        "target_mode": "selected", "window_percent": None, "window_size": None, "window_unit": "pages",
    },
    "chat_capabilities_enabled": False,
    "definition_version": 3,
    "description": "",
    "document_action": copy.deepcopy(NONE_ACTION),
    "durable_execution": True,
    "error_handling": {"retry_count": 0, "strategy": "halt"},
    "file_sync": {
        "continue_mode": "always", "enabled": False, "sources": [], "use_changed_documents": True,
        "wait_mode": "complete",
    },
    "flow": {
        "id": "root",
        "nodes": [
            {
                "body": {
                    "id": "body-region",
                    "nodes": [{"id": "body-node", "kind": "task", "task_id": "bcd8fd38-42bd-5c57-b97d-1519fd4233ec"}],
                    "outputs": [{
                        "allow_partial": False, "expected_kind": "records", "name": "findings", "required": True,
                        "source": {"kind": "node_output", "node_id": "body-node", "output": "records",
                                   "scope": "current"},
                    }],
                },
                "id": "each",
                "inputs": [],
                "item_key": "source_identity",
                "iterable": copy.deepcopy(ITERABLE),
                "kind": "for_each",
                "max_items": 1,
            },
            {
                "id": "collect",
                "kind": "collect",
                "output_contract": {
                    "allow_partial": False, "kind": "records", "require_complete_coverage": True,
                    "schema": {"items": {"type": "object"}, "type": "array"},
                },
                "source": {"loop_id": "each", "output": "findings"},
            },
            {"id": "report-node", "kind": "task", "task_id": "de5e45eb-2ecf-5dd2-a7cf-b3a9f25c3c93"},
        ],
        "outputs": [{
            "allow_partial": False, "expected_kind": "text", "name": "report", "required": True,
            "source": {"kind": "node_output", "node_id": "report-node", "output": "text", "scope": "current"},
        }],
    },
    "is_enabled": False,
    "limits": {"deadline_seconds": 86400, "max_executions": 5000},
    "m365_run_as_user_id": "",
    "model_binding_summary": {
        "endpoint_id": "", "label": "Default app model", "mode": "legacy_default", "model_id": "",
        "provider": "aoai", "valid": False,
    },
    "model_endpoint_id": "",
    "model_id": "",
    "model_provider": "aoai",
    "name": NAME,
    "reference_inputs": [],
    "runner_type": "model",
    "schedule": {},
    "selected_agent": {},
    "task_prompt": NAME,
    "tasks": [
        {
            "document_action": {
                "analysis_mode": "combined", "loop_id": "each", "target_mode": "current_item", "type": "analyze",
            },
            "id": "bcd8fd38-42bd-5c57-b97d-1519fd4233ec",
            "inputs": [{
                "allow_partial": False, "expected_kind": "json", "name": "item", "required": True,
                "source": {"kind": "loop_item", "loop_id": "each", "scope": "current"},
            }],
            "instructions": "Review this contract.",
            "name": "Review one",
            "order": 1,
            "output_contract": {
                "allow_partial": False, "kind": "records", "require_complete_coverage": False,
                "schema": {"items": {"type": "object"}, "type": "array"},
            },
            "reference_ids": [],
            "runner": {"type": "inherit"},
            "type": "instructions",
        },
        {
            "document_action": copy.deepcopy(NONE_ACTION),
            "id": "de5e45eb-2ecf-5dd2-a7cf-b3a9f25c3c93",
            "input_processing": "saved_record_report",
            "inputs": [{
                "allow_partial": False, "expected_kind": "records", "name": "findings", "required": True,
                "source": {"kind": "node_output", "node_id": "collect", "output": "records", "scope": "current"},
            }],
            "instructions": "Write the report.",
            "name": "Report",
            "order": 2,
            "output_contract": {"allow_partial": False, "kind": "text", "require_complete_coverage": False},
            "reference_ids": [],
            "runner": {"type": "inherit"},
            "type": "instructions",
        },
    ],
    "trigger_type": "manual",
    "url_access_enabled": False,
}


def query_disclosure(selection, *, count=None, scope_name=HOSTILE_SCOPE, max_items=500):
    """The server's disclosure for a search of a group workspace and the personal workspace."""
    loop = {"source": builder.HANDOFF_LOOP_SOURCE_QUERY, "scopes": [LEGAL_HANDLE, PERSONAL_HANDLE],
            "selection": selection}
    if count is not None:
        loop["count"] = count
    handles = {"scopes": {
        LEGAL_HANDLE: {"scope_type": "group", "scope_id": "group-legal", "name": scope_name},
        PERSONAL_HANDLE: {"scope_type": "personal"},
    }}
    return builder.handoff_disclosure({"loop": loop}, handles, max_items=max_items)


def hostile_summary():
    return {
        "alerts": {"mode": "every_run", "severity": "info"},
        "description": HOSTILE_DESCRIPTION,
        "durable": True,
        "name": HOSTILE_NAME,
        "one_time": True,
        "tasks": [
            {"agent_name": HOSTILE_AGENT, "runner": "agent", "title": HOSTILE_TITLE},
            {"agent_name": "", "runner": "model", "title": "Report"},
        ],
    }


def handoff(state="pending", reason=None, **overrides):
    """One list item, as `_assess`, `_actions` and `_describe` give it for ``state`` and ``reason``."""
    actions = {"pending": ["accept", "edit", "deny"], "created": ["accept"]}.get(state, [])
    item = {
        "handoff_id": HANDOFF_ID, "step_id": "handoff", "state": state, "reason": reason,
        "created_at": CREATED_AT, "expires_at": EXPIRES_AT, "actions": actions,
        "summary": copy.deepcopy(SUMMARY), "disclosure": copy.deepcopy(DISCLOSURE),
    }
    if reason in GATE_REASONS:
        # A closed gate discloses nothing and offers nothing.
        item.update(actions=[], summary=None, disclosure=None)
    elif reason == "content_review":
        item.update(actions=["deny"], summary=None, disclosure=None)
    elif reason in SIDECAR_STATES or state in ("unavailable", "invalid"):
        # The summary comes from the blueprint; the disclosure needs a dry run that passed.
        item.update(actions=["deny"], disclosure=None)
    if state in ("created", "queued"):
        if reason == "workflow_deleted":
            item["actions"] = []
        else:
            item["workflow"] = {"id": WORKFLOW_ID, "is_enabled": False, "name": NAME}
    if state == "queued":
        item["run"] = {"id": WORKFLOW_RUN_ID, "status": "queued"}
        item["chat_delivery"] = True
    item.update(copy.deepcopy(overrides))
    return item


def refusal(code, *, state=None, reason=None, errors=()):
    """``HandoffError.payload()`` for ``code``, with its status."""
    payload = {"error": ERROR_MESSAGES[code], "code": code, "errors": list(errors)}
    if state:
        payload["state"] = state
    if reason:
        payload["reason"] = reason
    return ERROR_STATUS[code], payload


# The route decorators refuse before any hand-off logic, without a code.
WORKFLOWS_OFF_REFUSAL = (400, {"error": "Allow User Workflows is disabled."})
ROLE_REFUSAL = (403, {"error": "Forbidden", "message": "Personal workflows require the WorkflowUser app role."})


def editor_options():
    return functions_workflow_editor.build_workflow_editor_options(
        scope_type="personal", scope_id="handoff-tester", can_manage=True, max_tasks=5, agents=[], endpoints=[],
        default_model={"label": "Default GPT", "valid": True},
    )


class HandoffApi:
    """The hand-off routes for one run, answered from `self.item` the way the server decides."""

    def __init__(self, assets):
        self.assets = assets
        self.item = handoff()
        self.draft = copy.deepcopy(DRAFT)
        self.requests = []
        self.unexpected = []
        self.expected_errors = set()
        self.status_error = None
        self.accept_errors = []
        self.draft_error = None

    def error(self, route, status, payload):
        self.expected_errors.add((urlsplit(route.request.url).path, status))
        route.fulfill(status=status, json=payload)

    def expect(self, condition, description):
        # A raise inside a route handler would leave the request hanging; the fixture reports these.
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
        query = parse_qs(parsed.query)
        body = request.post_data_json if request.method == "POST" else None
        self.requests.append({"method": request.method, "path": path, "query": query, "body": body})
        if path == HANDOFFS_PATH and request.method == "GET":
            self.expect(query == {"conversation_id": [CONVERSATION]}, f"GET {path}?{parsed.query}")
            if self.status_error:
                self.error(route, *self.status_error)
            else:
                route.fulfill(json={"run_id": RUN_ID, "handoffs": [copy.deepcopy(self.item)]})
            return
        match = re.fullmatch(re.escape(HANDOFFS_PATH) + r"/([^/]+)/(accept|deny|draft)", path)
        if match and unquote(match[1]) == HANDOFF_ID:
            operation = match[2]
            if operation == "draft" and request.method == "GET":
                self.expect(query == {"conversation_id": [CONVERSATION]}, f"draft query {query}")
                if self.draft_error:
                    self.error(route, *self.draft_error)
                    return
                route.fulfill(json={
                    "handoff_id": HANDOFF_ID, "workflow": copy.deepcopy(self.draft),
                    "url_access_note": URL_ACCESS_NOTE,
                })
                return
            if operation == "accept" and request.method == "POST":
                self.accept(route, body or {})
                return
            if operation == "deny" and request.method == "POST":
                self.expect(body == {"conversation_id": CONVERSATION}, f"deny body {body}")
                self.item = handoff("denied", summary=self.item["summary"], disclosure=self.item["disclosure"])
                route.fulfill(json={"handoff_id": HANDOFF_ID, "state": "denied"})
                return
        if path == EDITOR_OPTIONS_PATH and request.method == "GET":
            route.fulfill(json=editor_options())
            return
        if path == "/api/documents" and request.method == "GET":
            route.fulfill(json={"documents": [], "total_count": 0, "page": 1, "page_size": 10})
            return
        # The editor lists the requester's File Sync sources and Microsoft 365 run-as accounts.
        if path == "/api/user/workflows/file-sync-sources" and request.method == "GET":
            self.expect(not query, f"file-sync-sources query {query}")
            route.fulfill(json={"sources": [], "file_sync_enabled": True})
            return
        if path == "/api/workflows/m365-run-as-users" and request.method == "GET":
            self.expect(query == {"scope": ["personal"]}, f"m365-run-as-users query {query}")
            route.fulfill(json={"users": []})
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})

    def accept(self, route, body):
        mode = body.get("mode")
        if mode == "edited":
            self.expect(set(body) == {"conversation_id", "mode", "workflow"}, f"edited accept keys {sorted(body)}")
            self.expect(isinstance(body.get("workflow"), dict) and bool(body["workflow"]), "edited accept workflow")
        else:
            self.expect(body == {"conversation_id": CONVERSATION, "mode": "as_proposed"}, f"accept body {body}")
        self.expect(body.get("conversation_id") == CONVERSATION, f"accept conversation {body}")
        if self.accept_errors:
            status, payload = self.accept_errors.pop(0)
            if payload.get("state") == "created":
                # The workflow was created before the run failed to queue, so it now reads as created.
                self.item = handoff("created", summary=self.item["summary"], disclosure=self.item["disclosure"])
            self.error(route, status, payload)
            return
        created = self.item["state"] != "created"
        workflow = {
            "id": WORKFLOW_ID, "is_enabled": False,
            "name": (body.get("workflow") or {}).get("name") or (self.item.get("workflow") or {}).get("name") or NAME,
        }
        run = {"id": WORKFLOW_RUN_ID, "status": "queued"}
        self.item = handoff("queued", summary=self.item["summary"], disclosure=self.item["disclosure"],
                            workflow=workflow, run=run, chat_delivery=True)
        route.fulfill(status=201 if created else 200, json={
            "handoff_id": HANDOFF_ID, "state": "queued", "created": created, "workflow": workflow, "run": run,
            "chat_delivery": True,
        })

    def calls(self, method, suffix=""):
        return [call for call in self.requests
                if call["method"] == method and call["path"].startswith(HANDOFFS_PATH)
                and call["path"].endswith(suffix)]

    def status_reads(self):
        return [call for call in self.calls("GET") if call["path"] == HANDOFFS_PATH]

    def writes(self):
        return self.calls("POST")


@pytest.fixture
def card_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = HandoffApi(editor_assets)
    errors = []
    dialogs = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)

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
        hostile = page.evaluate("() => window.__hostile ?? null")
        assert hostile is None, hostile
    finally:
        context.close()
    assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
    assert not errors, f"Unexpected browser errors: {errors}"
    assert not dialogs, f"Unexpected browser dialogs: {dialogs}"


def answer(masked=False, capabilities=("compose", "workflow_handoff"), conversation=CONVERSATION):
    metadata = {"orchestration": {
        "run_id": RUN_ID, "turn_id": TURN, "outcome": "completed", "finalization_status": "saved",
        "message_saved": True,
        "plan_summary": {
            "plan_id": "handoff-plan", "turn_id": TURN, "status": "completed",
            "intent_summary": "Review every contract and list the renewal terms", "step_count": 2,
            "capabilities_used": list(capabilities),
        },
    }}
    if masked:
        metadata["masked_ranges"] = [{"start": 0, "end": 5}]
    return [
        {"id": "user-1", "conversation_id": conversation, "role": "user",
         "content": "Review every contract in my Legal workspace and list the renewal terms.",
         "metadata": {"orchestration_turn_id": TURN}},
        {"id": "answer-1", "conversation_id": conversation, "role": "assistant",
         "content": "Prepared a one-time workflow for this request. Nothing runs until you approve it on the "
                    "hand-off card.",
         "metadata": metadata},
    ]


def mount(page, api, *, kind="personal", theme="light", messages=None):
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
                version: '0.261.288', settings: {}, branding: { app_title: 'SimpleChat' },
                features: {
                    enable_chat_orchestration: true, allow_user_workflows: true,
                    enable_chat_orchestration_workflow_handoff: true,
                },
                user: { id: 'handoff-tester', display_name: 'Handoff Tester' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: spec.kind,
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [], messages: spec.messages,
                conversations: [{ id: spec.conversation, title: 'Contract review' }],
            });
            H.mount('mount-a', 'MessageList', {}, { strictMode: true });
        }""",
        {"conversation": CONVERSATION, "kind": kind, "theme": theme,
         "messages": messages if messages is not None else answer()},
    )
    expect(page.get_by_text("Review every contract in my Legal workspace", exact=False)).to_be_visible()


def card(page, name=NAME):
    region = page.get_by_role("region", name="Workflow hand-offs")
    expect(region).to_be_visible()
    article = region.get_by_role("article", name=name, exact=True)
    expect(article).to_be_visible()
    return article


def chip(article):
    # The state chip is the card's first status; a queued run adds its own below.
    return article.get_by_role("status").first


def detail(article, term):
    return article.locator(f"div:has(> dt:text-is('{term}')) > dd")


def wait_for(page, predicate, message):
    for _ in range(200):
        if predicate():
            return
        page.wait_for_timeout(25)
    raise AssertionError(message)


def text_of(locator):
    return locator.evaluate("(element) => element.textContent")


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_pending_card_discloses_the_hand_off_and_renders_planner_text_inert(card_ui, theme, width):
    page, api = card_ui
    page.set_viewport_size({"width": width, "height": 900})
    api.item = handoff(summary=hostile_summary(), disclosure=query_disclosure(builder.HANDOFF_SELECTION_ALL))
    mount(page, api, theme=theme)
    article = card(page, HOSTILE_NAME)
    expect(chip(article)).to_have_text("Awaiting your decision")
    expect(article).to_contain_text("Workflow hand-off")
    expect(detail(article, "Covers")).to_have_text(
        f"up to 500 matching documents. {builder.HANDOFF_PAUSE_NOTE}")
    expect(detail(article, "Workspaces")).to_have_text(f"{HOSTILE_SCOPE}, Your personal workspace")
    expect(detail(article, "Runs")).to_have_text("Once, when you accept. It is not scheduled.")
    expect(detail(article, "Alerts")).to_have_text("A notification after every run, severity Info.")
    expect(detail(article, "Durable")).to_have_text("Each run saves checkpoints and can resume after an interruption.")
    expect(article).to_contain_text("Nothing runs until you choose. You can decide until ")

    # Planner-written and workspace text is shown exactly as written and never becomes markup.
    expect(article.get_by_text(HOSTILE_DESCRIPTION, exact=True)).to_be_visible()
    tasks = article.get_by_role("list", name="Workflow tasks")
    expect(tasks.get_by_role("listitem")).to_have_count(2)
    expect(tasks.get_by_text(f"1. {HOSTILE_TITLE}", exact=True)).to_be_visible()
    expect(tasks.get_by_text(f"Runs with the agent {HOSTILE_AGENT}.", exact=True)).to_be_visible()
    expect(tasks.get_by_text("2. Report", exact=True)).to_be_visible()
    expect(tasks.get_by_text("Runs with the default model.", exact=True)).to_be_visible()
    for tag in ("img", "script", "b", "i"):
        expect(article.locator(tag)).to_have_count(0)

    expect(article.get_by_role("button", name="Accept", exact=True)).to_be_enabled()
    expect(article.get_by_role("button", name=f"Edit {HOSTILE_NAME} before accepting it", exact=True)).to_be_enabled()
    expect(article.get_by_role("button", name="Decline", exact=True)).to_be_enabled()
    expect(article).to_contain_text(EDIT_LIMITS)
    expect(article.get_by_role("link")).to_have_count(0)
    expect(page.get_by_role("article")).to_have_count(1)
    assert article.evaluate("(element) => element.scrollWidth <= element.clientWidth + 1")
    assert not api.writes()


def test_accept_is_confirmed_sends_as_proposed_and_shows_the_queued_run(card_ui):
    page, api = card_ui
    mount(page, api)
    article = card(page)
    accept = article.get_by_role("button", name="Accept", exact=True)
    accept.click()
    dialog = page.get_by_role("dialog", name="Accept this workflow hand-off?")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text(f"SimpleChat creates {NAME} and starts its one run now.")
    expect(detail(dialog, "Covers")).to_have_text("1 document")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(accept).to_be_focused()
    assert not api.writes()

    accept.click()
    page.get_by_role("dialog", name="Accept this workflow hand-off?").get_by_role(
        "button", name="Accept", exact=True).click()
    expect(chip(article)).to_have_text("Run queued")
    expect(article).to_contain_text("The workflow was created and its run was queued.")
    assert [call["body"] for call in api.writes()] == [{"conversation_id": CONVERSATION, "mode": "as_proposed"}]
    assert [call["path"] for call in api.writes()] == [ACCEPT_PATH]
    expect(article.get_by_text("Run: Queued", exact=True)).to_be_visible()
    expect(article.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(article.get_by_text(DELIVERY_TEXT, exact=True)).to_be_visible()
    expect(article.get_by_text(STATIC_FOOTNOTE, exact=True)).to_be_visible()
    # The run link replaces the workflow link, and no decision is left to make.
    expect(article.get_by_role("link", name="Open workflow")).to_have_count(0)
    for name in ("Accept", "Start its run", "Decline", "Check now"):
        expect(article.get_by_role("button", name=name, exact=True)).to_have_count(0)
    expect(article.get_by_role("button", name=re.compile("^Edit"))).to_have_count(0)
    expect(article).to_be_focused()

    # A reload reads the same decision back from the server.
    wait_for(page, lambda: len(api.status_reads()) >= 2, "The card did not re-read the hand-off after accepting.")
    mount(page, api)
    article = card(page)
    expect(chip(article)).to_have_text("Run queued")
    expect(article.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)


def test_a_created_hand_off_starts_the_run_of_its_existing_workflow(card_ui):
    page, api = card_ui
    api.item = handoff("created")
    mount(page, api)
    article = card(page)
    expect(chip(article)).to_have_text("Workflow created")
    expect(article).to_contain_text("The workflow was created, but its run has not started.")
    expect(article.get_by_role("link", name="Open workflow", exact=True)).to_have_attribute("href", WORKFLOW_HREF)
    expect(article.get_by_role("button", name="Decline")).to_have_count(0)
    expect(article.get_by_role("button", name=re.compile("^Edit"))).to_have_count(0)
    expect(article).not_to_contain_text(EDIT_LIMITS)

    article.get_by_role("button", name="Start its run", exact=True).click()
    dialog = page.get_by_role("dialog", name="Start the run of this workflow?")
    expect(dialog).to_contain_text(f"SimpleChat starts the one run of {NAME} now.")
    expect(dialog).to_contain_text("It runs once and is not scheduled.")
    dialog.get_by_role("button", name="Start its run", exact=True).click()
    expect(chip(article)).to_have_text("Run queued")
    assert [call["body"] for call in api.writes()] == [{"conversation_id": CONVERSATION, "mode": "as_proposed"}]
    expect(article.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)


def test_decline_is_confirmed_and_focus_follows_the_decision(card_ui):
    page, api = card_ui
    mount(page, api)
    article = card(page)
    decline = article.get_by_role("button", name="Decline", exact=True)
    decline.click()
    dialog = page.get_by_role("dialog", name="Decline this workflow hand-off?")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text(f"SimpleChat will not create {NAME}.")
    expect(dialog).to_contain_text("You can ask again in chat at any time.")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(decline).to_be_focused()
    assert not api.writes()

    decline.click()
    page.get_by_role("dialog", name="Decline this workflow hand-off?").get_by_role(
        "button", name="Decline", exact=True).click()
    expect(chip(article)).to_have_text("Declined")
    expect(article).to_contain_text("You declined this hand-off. Nothing was created.")
    assert [call["body"] for call in api.writes()] == [{"conversation_id": CONVERSATION}]
    assert [call["path"] for call in api.writes()] == [DENY_PATH]
    for name in ("Accept", "Decline"):
        expect(article.get_by_role("button", name=name, exact=True)).to_have_count(0)
    expect(article).to_be_focused()
    wait_for(page, lambda: len(api.status_reads()) >= 2, "The card did not re-read the hand-off after declining.")
    mount(page, api)
    expect(chip(card(page))).to_have_text("Declined")


def open_editor(page, article, name=NAME):
    article.get_by_role("button", name=f"Edit {name} before accepting it", exact=True).click()
    dialog = page.get_by_role("dialog", name="Create workflow", exact=True)
    expect(dialog).to_be_visible()
    field = dialog.get_by_label(re.compile(r"^Workflow name(?:\s*\*)?\s*$"))
    expect(field).to_have_value(name)
    return dialog, field


def save_confirm(page):
    dialog = page.get_by_role("dialog", name="Save and start this workflow?")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Saving creates this workflow and starts its one run now.")
    expect(dialog).to_contain_text(EDIT_LIMITS)
    return dialog


def test_edit_saves_through_an_edited_accept_after_confirming(card_ui):
    page, api = card_ui
    mount(page, api)
    article = card(page)
    dialog, name = open_editor(page, article)
    assert len(api.calls("GET", "/draft")) == 1
    name.fill(EDITED_NAME)
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    save_confirm(page).get_by_role("button", name="Save and start", exact=True).click()
    expect(dialog).to_have_count(0)

    bodies = [call["body"] for call in api.writes()]
    assert len(bodies) == 1, bodies
    body = bodies[0]
    # Saving an edited hand-off only ever accepts it, with the edited workflow and no saved id.
    assert set(body) == {"conversation_id", "mode", "workflow"}, sorted(body)
    assert (body["conversation_id"], body["mode"]) == (CONVERSATION, "edited")
    workflow = body["workflow"]
    assert workflow["name"] == EDITED_NAME
    assert "id" not in workflow
    # The server sets a version 3 workflow's task prompt from its name, as it did for the prepared one.
    assert "task_prompt" not in workflow
    assert workflow.get("url_access_enabled") is not True
    assert not workflow.get("m365_run_as_user_id")
    assert workflow["trigger_type"] == "manual"
    assert (workflow["definition_version"], workflow["durable_execution"]) == (3, True)
    each = workflow["flow"]["nodes"][0]
    assert (each["kind"], each["max_items"], each["iterable"]) == ("for_each", 1, ITERABLE)
    assert [task["instructions"] for task in workflow["tasks"]] == ["Review this contract.", "Write the report."]
    assert not [call for call in api.requests if call["path"].startswith("/api/user/workflows")
                and call["method"] == "POST"], "The editor saved a workflow directly."

    # The card names the workflow as it was created, and follows its run.
    article = card(page, EDITED_NAME)
    expect(chip(article)).to_have_text("Run queued")
    expect(article.get_by_role("link", name=f"Open run of {EDITED_NAME}", exact=True)).to_have_attribute(
        "href", RUN_HREF)
    expect(article).to_be_focused()


def test_cancelling_the_save_confirm_keeps_the_editor_and_its_draft(card_ui):
    page, api = card_ui
    mount(page, api)
    dialog, name = open_editor(page, card(page))
    name.fill(EDITED_NAME)
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    confirm = save_confirm(page)
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    expect(confirm).to_have_count(0)
    expect(dialog.get_by_role("alert").filter(has_text=DRAFT_RETAINED)).to_have_text(
        f"Not saved. {DRAFT_RETAINED}")
    expect(dialog).to_be_visible()
    expect(name).to_have_value(EDITED_NAME)
    assert not api.writes()


@pytest.mark.parametrize("refused,text", [
    (refusal("handoff_busy"), ERROR_MESSAGES["handoff_busy"]),
    (refusal("handoff_access_lost"), ERROR_MESSAGES["handoff_access_lost"]),
    (refusal("handoff_not_found"), ERROR_MESSAGES["handoff_not_found"]),
    (refusal("handoff_edit_invalid", errors=[
        {"code": "handoff_edit_invalid", "message": HANDOFF_EDIT_LOOP_MESSAGE, "path": "/flow"},
        {"code": "handoff_edit_invalid", "message": HANDOFF_EDIT_LOOP_MESSAGE, "path": "/flow"},
    ]), f"{ERROR_MESSAGES['handoff_edit_invalid']} {HANDOFF_EDIT_LOOP_MESSAGE}"),
    (ROLE_REFUSAL, WORKFLOW_ACCESS),
], ids=["busy-409", "access-lost-403", "not-found-404", "invalid-edit-400", "decorator-403"])
def test_a_refused_edited_accept_keeps_the_editor_and_its_draft(card_ui, refused, text):
    page, api = card_ui
    api.accept_errors.append(refused)
    mount(page, api)
    article = card(page)
    dialog, name = open_editor(page, article)
    name.fill(EDITED_NAME)
    reads = len(api.status_reads())
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    save_confirm(page).get_by_role("button", name="Save and start", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text=DRAFT_RETAINED)).to_have_text(f"{text} {DRAFT_RETAINED}")
    # The editor discards a draft on a 403 or 404 and calls a 409 stale; neither happens here.
    expect(dialog).to_be_visible()
    expect(name).to_have_value(EDITED_NAME)
    expect(dialog).not_to_contain_text("Forbidden")
    expect(dialog).not_to_contain_text("reload the saved workflow")
    assert len(api.writes()) == 1
    wait_for(page, lambda: len(api.status_reads()) > reads, "A refused save did not re-read the hand-off.")

    page.keyboard.press("Escape")
    page.get_by_role("dialog", name="Discard unsaved workflow changes?").get_by_role(
        "button", name="Discard changes", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(chip(article)).to_have_text("Awaiting your decision")


def test_url_access_in_a_draft_is_refused_before_anything_is_sent(card_ui):
    page, api = card_ui
    api.draft["url_access_enabled"] = True
    mount(page, api)
    dialog, _ = open_editor(page, card(page))
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="URL Access")).to_have_text(
        f"URL Access is not available for workflows created from chat. {URL_ACCESS_NOTE}")
    expect(page.get_by_role("dialog", name="Save and start this workflow?")).to_have_count(0)
    assert not api.writes()


def test_a_draft_that_cannot_be_opened_says_why_and_stays_on_the_card(card_ui):
    page, api = card_ui
    api.draft_error = refusal("handoff_limit_changed")
    mount(page, api)
    article = card(page)
    article.get_by_role("button", name=f"Edit {NAME} before accepting it", exact=True).click()
    expect(article.get_by_role("alert")).to_have_text(ERROR_MESSAGES["handoff_limit_changed"])
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(article.get_by_role("alert").get_by_role("button", name="Try again")).to_have_count(0)
    assert not api.writes()


@pytest.mark.parametrize("reason", sorted(SIDECAR_STATES))
def test_a_hand_off_the_server_could_not_prepare_reads_its_reason_and_can_be_declined(card_ui, reason):
    page, api = card_ui
    state = SIDECAR_STATES[reason]
    api.item = handoff(state, reason)
    mount(page, api)
    article = card(page)
    expect(chip(article)).to_have_text("Unavailable" if state == "unavailable" else "Can't be used")
    expect(article).to_contain_text(handoffs.WORKFLOW_HANDOFF_REASON_TEXT[reason])
    # Without a dry run that passed, the card shows what it would do but not what it covers.
    expect(article.get_by_role("list", name="Workflow tasks")).to_be_visible()
    expect(detail(article, "Covers")).to_have_count(0)
    for name in ("Accept", "Start its run"):
        expect(article.get_by_role("button", name=name, exact=True)).to_have_count(0)
    expect(article.get_by_role("button", name=re.compile("^Edit"))).to_have_count(0)
    expect(article.get_by_role("button", name="Decline", exact=True)).to_be_enabled()


@pytest.mark.parametrize("reason", [*GATE_REASONS, "content_review", "something_new"])
def test_a_closed_gate_or_a_removed_response_discloses_nothing(card_ui, reason):
    page, api = card_ui
    api.item = handoff("unavailable", reason)
    if reason == "something_new":
        api.item.update(actions=[], summary=None, disclosure=None)
    mount(page, api)
    # Without the summary there is no workflow name to show.
    article = card(page, "Workflow hand-off")
    expect(chip(article)).to_have_text("Unavailable")
    expect(article).to_contain_text(V2_REASON_TEXT.get(reason, "This hand-off is not available."))
    expect(article.get_by_role("list", name="Workflow tasks")).to_have_count(0)
    expect(article.locator("dl")).to_have_count(0)
    expect(article.get_by_role("button", name="Accept")).to_have_count(0)
    expect(article.get_by_role("button", name="Decline")).to_have_count(1 if reason == "content_review" else 0)


@pytest.mark.parametrize("state", ["created", "queued"])
def test_a_deleted_workflow_offers_nothing_and_links_nowhere(card_ui, state):
    page, api = card_ui
    api.item = handoff(state, "workflow_deleted")
    mount(page, api)
    article = card(page)
    expect(chip(article)).to_have_text("Workflow deleted")
    expect(article).to_contain_text("The workflow this hand-off created was deleted.")
    expect(article.get_by_role("link")).to_have_count(0)
    expect(article.get_by_role("button")).to_have_count(0)
    expect(article).not_to_contain_text("Run: ")
    expect(article).not_to_contain_text(DELIVERY_TEXT)


@pytest.mark.parametrize("state,badge,note", [
    ("expired", "Expired", "This hand-off expired. Ask again in chat for a new one."),
    ("denied", "Declined", "You declined this hand-off. Nothing was created."),
])
def test_a_decided_or_expired_hand_off_offers_nothing(card_ui, state, badge, note):
    page, api = card_ui
    api.item = handoff(state)
    mount(page, api)
    article = card(page)
    expect(chip(article)).to_have_text(badge)
    expect(article).to_contain_text(note)
    expect(article).not_to_contain_text("You can decide until")
    expect(article.get_by_role("button")).to_have_count(0)
    expect(article.get_by_role("link")).to_have_count(0)


@pytest.mark.parametrize("disclosure,covers,workspaces", [
    (DISCLOSURE, "1 document", None),
    (builder.handoff_disclosure({"loop": {"source": builder.HANDOFF_LOOP_SOURCE_DOCUMENTS,
                                          "documents": ["doc-a-111111", "doc-b-222222", "doc-c-333333"]}},
                                {}, max_items=500), "3 documents", None),
    (query_disclosure(builder.HANDOFF_SELECTION_BEST, count=10, scope_name="Legal"),
     "up to 10 best-matching documents", "Legal, Your personal workspace"),
    (query_disclosure(builder.HANDOFF_SELECTION_ALL, scope_name="Legal", max_items=500),
     f"up to 500 matching documents. {builder.HANDOFF_PAUSE_NOTE}", "Legal, Your personal workspace"),
], ids=["one-document", "named-documents", "best-matches", "every-match"])
def test_the_accept_confirm_repeats_what_the_hand_off_covers(card_ui, disclosure, covers, workspaces):
    page, api = card_ui
    api.item = handoff(disclosure=disclosure)
    mount(page, api)
    article = card(page)
    expect(detail(article, "Covers")).to_have_text(covers)
    article.get_by_role("button", name="Accept", exact=True).click()
    dialog = page.get_by_role("dialog", name="Accept this workflow hand-off?")
    expect(detail(dialog, "Covers")).to_have_text(covers)
    if workspaces is None:
        expect(detail(article, "Workspaces")).to_have_count(0)
        expect(detail(dialog, "Workspaces")).to_have_count(0)
    else:
        expect(detail(article, "Workspaces")).to_have_text(workspaces)
        expect(detail(dialog, "Workspaces")).to_have_text(workspaces)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert not api.writes()


def test_creating_polls_briefly_waits_while_hidden_and_can_check_again(card_ui):
    page, api = card_ui
    api.item = handoff("creating")
    # A paused clock, so only the checks this test runs happen.
    page.clock.install(time=CLOCK_START)
    page.clock.pause_at(CLOCK_START + timedelta(seconds=1))
    page.add_init_script(
        "Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.__hidden === true });"
    )
    mount(page, api)
    article = card(page)
    expect(chip(article)).to_have_text("Creating")
    expect(article).to_contain_text("Creating the workflow.")
    expect(article.get_by_role("button")).to_have_count(0)
    wait_for(page, lambda: len(api.status_reads()) >= 1, "The card never read the hand-off.")
    page.wait_for_timeout(200)
    reads = len(api.status_reads())

    page.clock.run_for(3000)
    wait_for(page, lambda: len(api.status_reads()) == reads + 1, "A creating hand-off was not checked again.")

    page.evaluate("() => { window.__hidden = true; document.dispatchEvent(new Event('visibilitychange')); }")
    page.clock.run_for(30000)
    page.wait_for_timeout(300)
    assert len(api.status_reads()) == reads + 1, "A hidden tab kept polling."
    page.evaluate("() => { window.__hidden = false; document.dispatchEvent(new Event('visibilitychange')); }")
    wait_for(page, lambda: len(api.status_reads()) == reads + 2, "Showing the tab did not check again.")

    # The server's claim window is 120 seconds; after it the card stops and offers a manual check.
    for _ in range(45):
        page.clock.run_for(3000)
        page.wait_for_timeout(20)
    expect(article).to_contain_text("This is taking longer than expected.")
    stopped_at = len(api.status_reads())
    assert stopped_at - reads <= 41, f"Polling was not bounded: {stopped_at - reads} reads."
    page.clock.run_for(60000)
    page.wait_for_timeout(300)
    assert len(api.status_reads()) == stopped_at, "Polling continued after it stopped."

    api.item = handoff("created")
    article.get_by_role("button", name="Check again", exact=True).click()
    expect(chip(article)).to_have_text("Workflow created")
    expect(article).not_to_contain_text("This is taking longer than expected.")
    settled = len(api.status_reads())
    page.clock.run_for(30000)
    page.wait_for_timeout(300)
    assert len(api.status_reads()) == settled, "A created hand-off kept polling."


@pytest.mark.parametrize("refused,text,badge", [
    (refusal("handoff_busy"), ERROR_MESSAGES["handoff_busy"], "Awaiting your decision"),
    (refusal("handoff_queue_failed", state="created"), ERROR_MESSAGES["handoff_queue_failed"], "Workflow created"),
    (refusal("handoff_run_conflict", state="created", reason="workflow_already_running"),
     f"{ERROR_MESSAGES['handoff_run_conflict']} "
     f"{workflow_runs.WORKFLOW_RUN_REASON_TEXT['workflow_already_running']}", "Workflow created"),
    (refusal("handoff_run_conflict", state="created"),
     f"{ERROR_MESSAGES['handoff_run_conflict']} "
     f"{workflow_runs.WORKFLOW_RUN_REASON_TEXT[workflow_runs.REASON_NOT_STARTED]}", "Workflow created"),
], ids=["busy", "queue-failed", "run-conflict", "run-conflict-without-reason"])
def test_an_accept_that_can_succeed_again_offers_try_again(card_ui, refused, text, badge):
    page, api = card_ui
    api.accept_errors.append(refused)
    mount(page, api)
    article = card(page)
    article.get_by_role("button", name="Accept", exact=True).click()
    page.get_by_role("dialog", name="Accept this workflow hand-off?").get_by_role(
        "button", name="Accept", exact=True).click()
    alert = article.get_by_role("alert")
    expect(alert).to_have_text(re.compile(r"^" + re.escape(text) + r"\s*Try again$"))
    expect(chip(article)).to_have_text(badge)

    # Trying again sends the same accept without asking twice; the server queues the same run.
    alert.get_by_role("button", name="Try again", exact=True).click()
    expect(chip(article)).to_have_text("Run queued")
    expect(article.get_by_role("alert")).to_have_count(0)
    bodies = [call["body"] for call in api.writes()]
    assert bodies == [{"conversation_id": CONVERSATION, "mode": "as_proposed"}] * 2, bodies


@pytest.mark.parametrize("code", ["handoff_unavailable", "handoff_access_lost"])
def test_a_created_workflow_that_cannot_run_now_offers_no_try_again(card_ui, code):
    page, api = card_ui
    api.accept_errors.append(refusal(code, state="created"))
    mount(page, api)
    article = card(page)
    article.get_by_role("button", name="Accept", exact=True).click()
    page.get_by_role("dialog", name="Accept this workflow hand-off?").get_by_role(
        "button", name="Accept", exact=True).click()
    expect(article.get_by_role("alert")).to_have_text(ERROR_MESSAGES[code])
    expect(article.get_by_role("button", name="Try again")).to_have_count(0)
    # The workflow exists, so the card still offers to start its run once the problem is fixed.
    expect(chip(article)).to_have_text("Workflow created")
    expect(article.get_by_role("button", name="Start its run", exact=True)).to_be_enabled()
    assert len(api.writes()) == 1


@pytest.mark.parametrize("refused,text", [
    (refusal("handoff_daily_limit"), ERROR_MESSAGES["handoff_daily_limit"]),
    (refusal("handoff_expired"), ERROR_MESSAGES["handoff_expired"]),
    (refusal("workflow_shared_conversation"), ERROR_MESSAGES["workflow_shared_conversation"]),
    ((409, {"error": "Something the server added later.", "code": "handoff_new_code", "errors": []}),
     "The hand-off could not be updated. Try again."),
    ((401, {"error": "Unauthorized", "message": "Authentication required"}), "Sign in again to continue."),
    (WORKFLOWS_OFF_REFUSAL, WORKFLOWS_OFF),
    (ROLE_REFUSAL, WORKFLOW_ACCESS),
], ids=["daily-limit", "expired", "shared", "unknown-code", "signed-out", "decorator-400", "decorator-403"])
def test_a_refused_accept_reads_v2s_copy_of_the_servers_sentence(card_ui, refused, text):
    page, api = card_ui
    api.accept_errors.append(refused)
    mount(page, api)
    article = card(page)
    article.get_by_role("button", name="Accept", exact=True).click()
    page.get_by_role("dialog", name="Accept this workflow hand-off?").get_by_role(
        "button", name="Accept", exact=True).click()
    expect(article.get_by_role("alert")).to_have_text(text)
    expect(article).not_to_contain_text("Forbidden")
    expect(article).not_to_contain_text("Something the server added later.")
    expect(article.get_by_role("button", name="Try again")).to_have_count(0)


def test_a_run_the_reader_cannot_open_shows_nothing(card_ui):
    page, api = card_ui
    api.status_error = refusal("run_not_found")
    mount(page, api)
    wait_for(page, lambda: api.status_reads(), "The card never asked for the hand-off.")
    page.wait_for_timeout(300)
    expect(page.get_by_role("region", name="Workflow hand-offs")).to_have_count(0)
    expect(page.get_by_role("alert")).to_have_count(0)


@pytest.mark.parametrize("refused,text", [
    (WORKFLOWS_OFF_REFUSAL, WORKFLOWS_OFF),
    (ROLE_REFUSAL, WORKFLOW_ACCESS),
    (refusal("service_unavailable"), ERROR_MESSAGES["service_unavailable"]),
    ((409, {"error": LEGACY_PLAN_MESSAGE, "code": "legacy_plan"}), LEGACY_PLAN_MESSAGE),
], ids=["workflows-off", "no-workflow-role", "unavailable", "legacy-plan"])
def test_a_refused_read_is_a_state_of_the_answer_with_try_again(card_ui, refused, text):
    page, api = card_ui
    api.status_error = refused
    mount(page, api)
    region = page.get_by_role("region", name="Workflow hand-offs")
    status = region.get_by_role("status")
    expect(status).to_have_text(re.compile(r"^" + re.escape(text) + r"\s*Try again$"))
    expect(region).not_to_contain_text("Forbidden")
    expect(region.get_by_role("alert")).to_have_count(0)
    api.status_error = None
    status.get_by_role("button", name="Try again", exact=True).click()
    expect(chip(card(page))).to_have_text("Awaiting your decision")
    expect(region.get_by_text(text, exact=True)).to_have_count(0)


@pytest.mark.parametrize("kind,messages", [
    ("collaborative", answer()),
    ("personal", answer(capabilities=("compose",))),
    ("personal", answer(masked=True)),
    ("personal", answer(conversation="another-chat")),
], ids=["shared-conversation", "no-hand-off-step", "masked-answer", "another-conversation"])
def test_no_card_and_no_request_outside_a_personal_hand_off_answer(card_ui, kind, messages):
    page, api = card_ui
    mount(page, api, kind=kind, messages=messages)
    page.wait_for_timeout(400)
    expect(page.get_by_role("region", name="Workflow hand-offs")).to_have_count(0)
    assert not api.calls("GET") and not api.writes(), api.requests
