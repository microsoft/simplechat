# test_v2_orchestration_merge_arguments.py
"""
Real-component browser tests for how the plan review states spreadsheet merge settings.
Version: 0.261.219
Implemented in: 0.261.219
Refs: microsoft/simplechat#1619

The production OrchestrationPlanCard and OrchestrationRunView run in Chromium with the
production CSS. Only HTTP boundaries are stubbed. The plan mirrors the server shape for a
tabular_inspect step, a compose step preparing a tabular_column_mapping_v1 mapping, and a
tabular_merge step whose union, alias, exclusion, duplicate and sort settings must read in
words, without raw argument names, with column names kept as plain text.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_merge_arguments.py -q
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
IMPLEMENTED_IN = "0.261.219"
CONVERSATION = "conversation-merge"
TURN = "merge-turn"
RUN = "/api/v2/orchestration/run"
RUNS = "/api/v2/orchestration/runs"
REQUEST = "Merge these sales files into one spreadsheet."
HOSTILE_COLUMN = '<img src=x onerror="window.__hostile = 1"> cust id'
RAW_KEYS = [
    "schema_policy", "column_aliases", "on_incompatible", "dedupe", "dedupe_columns", "dedupe_keep",
    "sort_by", "doc_scope", "include_source_column", "source_column_name", "header_row",
    "sample_rows", "document_ids",
]


def plan_step(step_id, capability_id, role, arguments, *, inputs=None, outputs=None, title=None):
    return {
        "step_id": step_id, "capability_id": capability_id, "title": title or step_id.title(),
        "rationale": "", "arguments": arguments, "depends_on": [], "inputs": inputs or {},
        "outputs": outputs or [], "optional": False, "enabled": True, "estimated_cost": "low",
        "role": role, "status": "pending",
    }


SERVER_PLAN = {
    "kind": "plan",
    "steps": [
        plan_step("inspect", "tabular_inspect", "gather", {
            "document_ids": ["doc-east", "doc-west"], "doc_scope": "all", "sheets": "all",
            "header_row": 2, "sample_rows": 5,
        }, outputs=[{"name": "inspection", "kind": "structured-v1"}], title="Inspect spreadsheets"),
        plan_step("merge", "tabular_merge", "reason", {
            "document_ids": ["doc-east", "doc-west"], "doc_scope": "all", "schema_policy": "union",
            "include_source_column": True, "source_column_name": "Source File",
            "column_aliases": {"Customer ID": [HOSTILE_COLUMN, "CustomerID"]},
            "on_incompatible": "exclude", "dedupe": "key_columns", "dedupe_columns": ["Customer ID"],
            "dedupe_keep": "last",
            "sort_by": [{"column": "Amount", "value_type": "number", "descending": True}],
        }, outputs=[{"name": "records", "kind": "records-v1"}, {"name": "report", "kind": "structured-v1"}],
            title="Merge spreadsheets"),
        plan_step("plain_merge", "tabular_merge", "reason", {
            "document_ids": ["doc-east", "doc-west"], "doc_scope": "all", "schema_policy": "by_name",
            "include_source_column": True, "source_column_name": "Source File",
        }, outputs=[{"name": "records", "kind": "records-v1"}, {"name": "report", "kind": "structured-v1"}],
            title="Merge matching spreadsheets"),
    ],
    "plan_id": "plan_merge_arguments",
    "run_id": "run_merge_arguments",
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
    "deliverables": [],
    "validation": {"ok": True, "errors": [], "repairs": []},
    "inputs": {
        "documents": [
            {"document_id": "doc-east", "title": "east.csv", "scope": "personal"},
            {"document_id": "doc-west", "title": "west.xlsx", "scope": "personal"},
        ],
        "image_reference_documents": [], "image_reference_messages": [], "web": False,
        "required_capabilities": [], "actions": [], "agent": None,
        "model": {"model_deployment": "gpt-4o", "model_provider": "aoai"}, "prompt": None,
    },
    "outputs": [
        {"kind": "structured-v1", "source_step_id": "inspect", "name": "inspection"},
        {"kind": "records-v1", "source_step_id": "merge", "name": "records"},
    ],
    "status": "awaiting_approval",
    "planner_model": "gpt-4o",
    "planner": {"label": "gpt-4o", "source": "default"},
    "reasoning_adjustments": [],
}


def server_plan():
    return copy.deepcopy(SERVER_PLAN)


class MergeApi:
    """The orchestration routes the card and run view call, recording unexpected requests."""

    def __init__(self, assets):
        self.assets = assets
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
        if path == RUN and request.method == "POST":
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps({'done': True})}\n\n")
            return
        if path == RUNS and request.method == "GET":
            route.fulfill(json={"runs": []})
            return
        if re.fullmatch(re.escape(RUNS) + r"/[^/]+/steps", path) and request.method == "GET":
            route.fulfill(json={"steps": []})
            return
        if path.startswith("/api/") and request.method == "GET":
            route.fulfill(json={})
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})


@pytest.fixture
def merge_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = MergeApi(editor_assets)
    errors = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    try:
        yield page, api
        hostile = page.evaluate("() => window.__hostile ?? null")
        assert hostile is None, hostile
    finally:
        context.close()
    assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
    assert not errors, f"Unexpected browser errors: {errors}"


def mount_plan(page, api, plan, *, theme="light"):
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
                version: '0.261.219', settings: {}, branding: { app_title: 'SimpleChat' },
                features: { enable_chat_orchestration: true },
                user: { id: 'owner', display_name: 'Merge Owner' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, allow_user_approval_override: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Merge files' }],
                messages: [{ id: 'user-1', conversation_id: spec.conversation, role: 'user',
                    content: spec.request, metadata: { orchestration_turn_id: spec.turn } }],
            });
            const store = H.stores.orchestration.useOrchestrationStore.getState();
            store.setPlan(spec.conversation, spec.turn, spec.plan);
            store.setActiveTurn(spec.conversation, spec.turn);
            const props = { conversationId: spec.conversation, turnId: spec.turn };
            H.mount('mount-a', 'OrchestrationPlanCard', props, { strictMode: true });
            H.mount('mount-b', 'OrchestrationRunView', props, { strictMode: true });
        }""",
        {"conversation": CONVERSATION, "turn": TURN, "plan": plan, "theme": theme, "request": REQUEST},
    )
    expect(page.locator("#mount-a").get_by_role("button", name="Approve and run the plan")).to_be_visible()
    review = page.locator("#mount-b")
    for step_id in ("inspect", "merge", "plain_merge"):
        expect(review.locator(f'li[data-step-id="{step_id}"]')).to_be_visible()
    return review


def terms(step):
    arguments = step.get_by_test_id("orchestration-step-arguments")
    return arguments.locator("dt").evaluate_all("(nodes) => nodes.map((node) => node.textContent?.trim() || '')")


def definitions(step):
    arguments = step.get_by_test_id("orchestration-step-arguments")
    return arguments.locator("dd").evaluate_all("(nodes) => nodes.map((node) => node.textContent?.trim() || '')")


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_merge_settings_read_in_words(merge_ui, theme, width):
    page, api = merge_ui
    page.set_viewport_size({"width": width, "height": 900})
    review = mount_plan(page, api, server_plan(), theme=theme)

    merge = review.locator('li[data-step-id="merge"]')
    assert terms(merge) == ["columns", "same column as", "files that don\u2019t fit", "duplicates", "sort by"]
    assert definitions(merge) == [
        "Keep every column from every file",
        f"Customer ID \u2190 {HOSTILE_COLUMN}, CustomerID",
        "Left out and reported",
        "Remove rows with the same Customer ID, keeping the last",
        "Amount (number, descending)",
    ]
    for tag in ("img", "script"):
        expect(merge.locator(f"dd {tag}")).to_have_count(0)
    box = merge.bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= width, (box, width)

    plain = review.locator('li[data-step-id="plain_merge"]')
    assert terms(plain) == ["columns"]
    assert definitions(plain) == ["Same columns, in any order"]

    inspect = review.locator('li[data-step-id="inspect"]')
    assert terms(inspect) == ["sheets", "header row", "sample rows"]
    assert definitions(inspect) == ["Every visible sheet", "Row 2", "5"]

    for step_id in ("inspect", "merge", "plain_merge"):
        shown = terms(review.locator(f'li[data-step-id="{step_id}"]'))
        for key in RAW_KEYS:
            assert key not in shown, (step_id, key, shown)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
