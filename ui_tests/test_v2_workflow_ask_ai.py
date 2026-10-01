# test_v2_workflow_ask_ai.py
"""
Offline real-bundle browser regressions for the workflow editor's Ask AI tab (Phase 3c).
Version: 0.261.211
Implemented in: 0.261.211
Refs: microsoft/simplechat#1548

Covers the "Done when" instruction end to end (highlights, Previously, Undo this change, a single
field Revert and Confirm and save, with the Run as case), the three `#` placement outcomes and a
document read only as context, immediate send with the editor lock, its timer, Cancel and Retry,
the stale-draft guard, the request each kind of draft sends, code-point counting, Undo with a key
that changed later, every status the assist route answers, a reload after a conflict that is closed,
superseded or overtaken by a save while it loads or that fails, hostile model text, Jump to on a
task field and on a flow block, where the tab is hidden, the keyboard, a narrow screen, Draft with
AI on a List task and on a Flow block (each under 6x CPU throttling, so focus must reach the
drafted instructions before their highlight renders and must stay there), the quick actions, and a
card from an earlier editing session.

`POST /api/user/workflows/assist` is answered in the page by 3b's real pipeline with a scripted
model (see `fixtures/workflow_ask_ai.py`), so no live model, workflow run, approval or Azure
service is contacted. Reuses the closed Flow authoring harness, its local production assets and
the real compiler. Run with PLAYWRIGHT_SERVICE_URL='' and PYTHONPATH including
application/single_app, functional_tests and ui_tests/fixtures.
"""

import copy
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# The shared fixtures import pure application helpers after setting their paths.
from ui_tests import test_v2_workflow_flow_authoring as authoring
from ui_tests.fixtures.workflow_ask_ai import (
    ASSIST_ROUTE,
    DRAFT_INSTRUCTIONS_ROUTE,
    AssistStub,
    DraftInstructionsStub,
    core,
)
from ui_tests.fixtures.workflow_editor import OWNER_ID, WORKFLOW_ID
from ui_tests.fixtures.workflow_flow import FLOW_WORKFLOW_ID, GROUP_ID
from ui_tests.fixtures.workspace_authoring import ORIGIN
from ui_tests.test_v2_workflow_change_tracking import (
    RUN_AS_NOTE,
    UNSUPPORTED_SCHEDULE,
    assert_dialog_fits,
    author,
    changed,
    changes_toggle,
    open_classic,
    open_panel,
    previously,
    side_panel,
    task_item,
)
from ui_tests.test_v2_workflow_flow_authoring import connect_options  # noqa: F401
from functions_workflow_definitions import workflow_definition_revision  # noqa: E402
from functions_workflow_flow import compile_workflow_flow  # noqa: E402


TIME_ZONE = "America/Chicago"
pytestmark = [pytest.mark.ui, pytest.mark.browser_context_args(timezone_id=TIME_ZONE)]

DONE_WHEN = "run this at 7 AM on weekdays and only alert me when something is urgent"
WEEKDAYS_AT_SEVEN = {"op": "set_schedule_calendar", "frequency": "weekdays", "time_of_day": "07:00"}
URGENT_ONLY = [
    {"op": "set_alert_mode", "mode": "rules"},
    {
        "op": "add_alert_rule", "name": "Urgent findings", "severity": "high",
        "condition": {"type": "model_evaluation", "prompt": "The results include something urgent."},
    },
]
REQUEST_KEYS = {"submission_id", "base", "instruction", "conversation", "focus", "time_zone", "draft", "references"}
SUBMISSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
BRIEF_REF = {"kind": "document", "id": "personal-brief", "scope": {"kind": "personal", "id": None}, "label": "Private brief"}
BRIEF_KEY = "reference:personal%3Aworkspace-editor-user%3Apersonal-brief"
STALE_DRAFT = "Nothing was applied because the draft changed while Ask AI was working. Send it again to use the current draft."
CANCELLED = "Cancelled. Nothing was changed."
EMAIL_MESSAGE = (
    "This task sends email, which needs an agent with the Microsoft 365 action. "
    "Choose such an agent for the task or the workflow."
)
M365_MESSAGE = "Connect your Microsoft 365 account so this workflow can send email."
DRAFT_ERRORS_MESSAGE = "The draft already had a problem that saving will report. The assistant did not cause it; fix it before saving."
RUN_AS_WARNING = "Saving this change requires re-approving Run as, because it changes how the workflow runs."
NEEDS_NAME = "Name the workflow or this task first, so the assistant knows what to draft."
UNREADABLE = "The assistant's answer couldn't be read. Nothing was changed."
UNUSABLE = "The assistant's answer couldn't be used. Nothing was changed. Try again."
EXPLAIN = "Explain what this workflow does, step by step. Don't change anything."
WAIT_NOTE = re.compile(r"^You can send again in [1-9]\d* s\.$")
# Model and admin text that would run, link or format if it were ever rendered as HTML or Markdown.
HOSTILE = (
    '<img src=x onerror="window.__hostile = 1"> [Open this](javascript:window.__hostile=2) '
    "**urgent** <script>window.__hostile = 3</script>"
)
RATE_LIMIT_TEXT = (
    "**Slow down.**\n\nSee [the policy](https://example.com/policy) "
    '<img src=x onerror="window.__hostile = 4"> and <b>wait</b> a moment.'
)
MARKUP = "img, script, a, strong, b, em, i"


class AskAiFixture(authoring.WorkflowAuthoringFixture):
    """The Flow authoring harness with Ask AI on for this user and its two routes stubbed in the page."""

    def __init__(self, page):
        super().__init__(page)
        self.ask_ai_enabled = True
        self.document_searches = []

        def record_error(url, status):
            self.expected_http_errors.add((url, status))

        self.assist = AssistStub(
            user_id=OWNER_ID, record_error=record_error, options=self._assist_options,
            read_base=self._read_base, resolve=self._resolve,
        )
        self.drafts = DraftInstructionsStub(record_error=record_error)
        # page.route takes precedence over the harness's context route, so neither request reaches it.
        page.route(ASSIST_ROUTE, self.assist.handle)
        page.route(DRAFT_INSTRUCTIONS_ROUTE, self.drafts.handle)

    def _bootstrap(self):
        payload = super()._bootstrap()
        # The bootstrap sends this per user: on only where the setting, personal workflows and the role allow it.
        payload["features"]["enable_workflow_ai_assistant"] = self.ask_ai_enabled
        return payload

    def _options(self, group):
        options = super()._options(group)
        options["schedule"]["timezones"] = [
            zone for zone in options["schedule"]["timezones"] if zone not in self.unlisted_schedule_timezones
        ]
        return options

    def _assist_options(self):
        """The personal editor options the browser was given, which the pipeline checks the draft against."""
        options = self._options(False)
        options["max_tasks"] = self.max_tasks
        options["can_manage"] = True
        return options

    def _read_base(self, user_id, workflow_id):
        stored = self.personal_workflows.get(workflow_id)
        if stored is None or user_id != OWNER_ID:
            return None
        record = copy.deepcopy(stored)
        record.setdefault("user_id", OWNER_ID)
        return record

    def _resolve(self, user_id, references):
        """`resolve_scope_references` for this user's own documents; anything else is unavailable."""
        documents = {document["id"]: document for document in self.documents}
        resolved = []
        for reference in references:
            document = documents.get(reference.get("id"))
            if reference.get("kind") != "document" or (reference.get("scope") or {}).get("kind") != "personal" \
                    or document is None:
                raise core.WorkflowAssistError("reference_unavailable")
            resolved.append({
                "kind": "document", "id": document["id"], "label": document["file_name"],
                "scope": {"kind": "personal", "id": user_id, "name": "Personal"},
            })
        return resolved

    def _dispatch(self, route, entry):
        # The # menu searches personal and group documents, the group route with one comma-joined list.
        if entry.method == "GET" and entry.path in ("/api/documents", "/api/group_documents"):
            if entry.path == "/api/documents":
                documents = self.documents
            else:
                group_ids = [
                    group_id for value in entry.query.get("group_ids", []) for group_id in value.split(",") if group_id
                ]
                if not group_ids or any(group_id not in self.group_workflows for group_id in group_ids):
                    self.unexpected_requests.append(f"GET {entry.path} for {group_ids}")
                documents = [document for group_id in group_ids for document in self.group_documents.get(group_id, [])]
            search = entry.query.get("search", [""])[0].strip().lower()
            if search:
                self.document_searches.append((entry.path, search))
                documents = [
                    document for document in documents
                    if search in f"{document.get('title', '')} {document.get('file_name', '')}".lower()
                ]
            self._json(route, {"documents": documents, "total_count": len(documents)})
            return
        super()._dispatch(route, entry)

    def fail_held_responses(self, status=503):
        """Answer every held request with a failure, as a `reject_next` that waited would."""
        pending, self.pending_responses = self.pending_responses, []
        for route, _ in pending:
            self._json(route, {"error": "Fixture request failed."}, status)

    def release_held(self, method, path):
        """Answer the one held `method path` request, and leave the others held."""
        matches = [
            index for index, (_, entry) in enumerate(self.pending_responses)
            if (entry.method, entry.path) == (method, path)
        ]
        assert len(matches) == 1, f"Expected one held {method} {path}, found {len(matches)}."
        route, entry = self.pending_responses.pop(matches[0])
        self._dispatch(route, entry)

    def assert_clean(self):
        self.assist.assert_clean()
        self.drafts.assert_clean()
        for page in self.pages:
            if not page.is_closed() and page.url.startswith(ORIGIN):
                assert page.evaluate("() => window.__hostile ?? null") is None, "Model text ran as HTML."
        super().assert_clean()


@pytest.fixture
def ask_ui(page):
    fixture = AskAiFixture(page)
    yield fixture
    try:
        fixture.assert_clean()
    finally:
        fixture.assist.release()
        fixture.release_flow_responses()
        fixture.release_save_responses()
        fixture.flow_response_gates.clear()


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------

def ask_toggle(editor):
    return editor.get_by_role("button", name="Ask AI", exact=True)


def composer(scope):
    return scope.get_by_role("textbox", name="Message Ask AI", exact=True)


def send_button(scope):
    return scope.get_by_role("button", name="Send to Ask AI", exact=True)


def open_ask_ai(editor):
    toggle = ask_toggle(editor)
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    panel = side_panel(editor)
    expect(panel.get_by_role("tab", name="Ask AI", exact=True)).to_have_attribute("aria-selected", "true")
    expect(composer(panel)).to_be_focused()
    return panel


def exchanges(panel):
    return panel.locator("li[data-testid='assist-exchange']")


def card(panel, submission_id):
    return panel.locator(f"[data-workflow-assist-card='{submission_id}']")


def type_and_send(panel, text):
    box = composer(panel)
    box.fill(text)
    box.press("Enter")


def ask(ui, panel, text):
    """Send `text` and return the request body the assist route received."""
    count = len(ui.assist.bodies)
    type_and_send(panel, text)
    return ui.assist.wait_for_requests(ui.page, count + 1)


def answered(panel, body):
    """The answer card for a request, once it is in."""
    found = card(panel, body["submission_id"])
    expect(found).to_be_visible()
    return found


def failed(panel):
    exchange = exchanges(panel).last
    expect(exchange).to_have_attribute("data-status", "failed")
    return exchange


def change_keys(found):
    return found.locator("li[data-workflow-assist-change]").evaluate_all(
        "items => items.map((item) => item.dataset.workflowAssistChange)")


def undo_button(found):
    return found.get_by_role("button", name=re.compile(r"^Undo this change: "))


def with_warnings(answer, *warnings):
    """An answer with more warnings after the pipeline's own, for the codes a fixture can't provoke."""

    def wrapped(raw):
        status, payload, headers = answer(raw)
        payload = copy.deepcopy(payload)
        payload["warnings"] = [*payload.get("warnings", []), *copy.deepcopy(warnings)]
        return status, payload, headers

    return wrapped


def confirm_save(ui, editor, *, run_as=False):
    """Save with AI changes: Review before saving opens first, and only Confirm and save writes."""
    before = len(ui.workflow_writes)
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    panel = side_panel(editor)
    expect(panel.get_by_role("tab", name="Changes", exact=True)).to_have_attribute("aria-selected", "true")
    review = panel.get_by_role("region", name="Review before saving", exact=True)
    expect(review.get_by_role("heading", name="Review before saving", exact=True)).to_be_focused()
    # The Run as note also heads the tab, so the review's own line is the one checked.
    expect(review.locator("li").filter(has_text=RUN_AS_NOTE)).to_have_count(1 if run_as else 0)
    assert len(ui.workflow_writes) == before, "Save wrote before Confirm and save."
    review.get_by_role("button", name="Confirm and save", exact=True).click()
    expect(editor).to_have_count(0)
    assert len(ui.workflow_writes) == before + 1
    ui.assert_authoring_only()
    return ui.workflow_writes[-1].body


def pick_brief(ui, panel, before="Use "):
    """Type `before`, then pick Private brief from the # menu by keyboard."""
    box = composer(panel)
    box.fill(before)
    # Typed, not filled: fill() sends no key events, so the # menu would not open until the next key.
    box.press_sequentially("#priv")
    options = ui.page.get_by_role("listbox", name="Context suggestions").get_by_role("option")
    expect(options.first).to_contain_text("Private brief")
    expect(options.first).to_have_attribute("aria-selected", "true")
    box.press("Enter")
    expect(box).to_have_value(f"{before}#[Private brief] ")
    return box


# ---------------------------------------------------------------------------------------------
# Done when
# ---------------------------------------------------------------------------------------------

def test_done_when_instruction_is_highlighted_undone_reverted_and_confirmed(ask_ui):
    ui, page = ask_ui, ask_ui.page
    reply = "Scheduled for 7 AM on weekdays, with alerts only for urgent results."
    ui.assist.queue(
        ui.assist.changed(WEEKDAYS_AT_SEVEN, *URGENT_ONLY, text=reply),
        ui.assist.changed(WEEKDAYS_AT_SEVEN, *URGENT_ONLY, text=reply),
    )
    editor = open_classic(ui)
    panel = open_ask_ai(editor)

    body = ask(ui, panel, DONE_WHEN)
    assert set(body) == REQUEST_KEYS
    assert SUBMISSION_ID.fullmatch(body["submission_id"])
    stored = ui.personal_workflows[WORKFLOW_ID]
    assert body["base"] == {"workflow_id": WORKFLOW_ID, "definition_revision": stored["definition_revision"]}
    assert body["draft"]["id"] == WORKFLOW_ID
    assert body["instruction"] == DONE_WHEN
    assert body["conversation"] == [] and body["references"] == [] and body["focus"] is None
    assert body["time_zone"] == TIME_ZONE

    first = answered(panel, body)
    expect(first).to_have_attribute("data-outcome", "changed")
    expect(first).to_have_attribute("data-state", "applied")
    expect(first.locator("[data-workflow-assist-reply]")).to_have_text(reply)
    expect(first.locator("[data-workflow-assist-state]")).to_have_text(
        "Changed 2 things in the draft. Review before saving.")
    assert change_keys(first) == ["schedule", "alerts"]
    expect(first.locator("li[data-workflow-assist-change='schedule']")).to_contain_text("Workflow: Trigger and schedule")
    expect(first.locator("li[data-workflow-assist-change='alerts']")).to_contain_text("Workflow: Alerts")
    expect(composer(panel)).to_be_focused()

    schedule, alerts = changed(editor, "schedule"), changed(editor, "alerts")
    expect(author(schedule)).to_have_text("AI assist")
    expect(author(schedule)).to_have_attribute("data-workflow-change-author", "ai")
    expect(author(alerts)).to_have_text("AI assist")
    expect(previously(schedule)).to_contain_text("Manual")
    expect(editor.get_by_label("Trigger", exact=True)).to_have_value("interval")
    expect(editor.get_by_label("Repeats", exact=True)).to_have_value("weekdays")
    expect(editor.get_by_label("Time", exact=True)).to_have_value("07:00")
    expect(editor.get_by_label("Time zone", exact=True)).to_have_value(TIME_ZONE)
    expect(editor.get_by_label("Alert rule 1 name", exact=True)).to_have_value("Urgent findings")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (2 unsaved)")

    undo_button(first).click()
    result = first.locator("[data-workflow-assist-undo]")
    expect(result).to_have_attribute("data-workflow-assist-undo", "applied")
    expect(result).to_be_focused()
    expect(result.locator("p").first).to_have_text("Undone: 2 reverted.")
    expect(result.get_by_role("list", name="Reverted").get_by_role("listitem")).to_have_text(
        ["Trigger and schedule", "Alerts"])
    expect(first).to_have_attribute("data-state", "undone")
    expect(first.locator("[data-workflow-assist-state]")).to_have_text("These changes were undone.")
    expect(changed(editor, "schedule")).to_have_count(0)
    expect(changed(editor, "alerts")).to_have_count(0)
    expect(editor.get_by_label("Trigger", exact=True)).to_have_value("manual")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")

    # The next turn replays the first as its reply plus what happened to its changes.
    again = ask(ui, panel, "Apply that schedule and alert again.")
    assert again["conversation"] == [
        {"role": "user", "text": DONE_WHEN},
        {"role": "assistant", "text": (
            f"{reply}\n\nThese changes were applied and later undone: "
            "Workflow: Trigger and schedule; Workflow: Alerts."
        )},
    ]
    second = answered(panel, again)
    expect(second).to_have_attribute("data-state", "applied")
    expect(author(changed(editor, "alerts"))).to_have_text("AI assist")

    changed(editor, "alerts").get_by_role("button", name="Revert", exact=True).click()
    expect(changed(editor, "alerts")).to_have_count(0)
    expect(author(changed(editor, "schedule"))).to_have_text("AI assist")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")

    payload = confirm_save(ui, editor)
    assert payload["trigger_type"] == "interval"
    assert payload["schedule"]["kind"] == "calendar"
    assert payload["schedule"]["frequency"] == "weekdays"
    assert payload["schedule"]["time_of_day"] == "07:00"
    assert payload["schedule"]["timezone"] == TIME_ZONE
    assert "Urgent findings" not in json.dumps(payload)
    assert len(ui.assist.bodies) == 2
    page.wait_for_timeout(100)


def test_run_as_warnings_and_review_before_saving(ask_ui):
    ui = ask_ui
    ui.personal_workflows[WORKFLOW_ID]["m365_run_as_user_id"] = OWNER_ID
    instructions = "Collect only signed evidence."
    ui.assist.queue(with_warnings(
        ui.assist.changed({"op": "set_task_instructions", "task": "task_1", "instructions": instructions}),
        {"code": "email_requires_m365_agent", "message": EMAIL_MESSAGE, "target": {"focus_key": "task:task-b"}},
        {"code": "m365_not_connected", "message": M365_MESSAGE},
        {"code": "draft_has_errors", "message": DRAFT_ERRORS_MESSAGE},
    ))
    editor = open_classic(ui)
    expect(editor.get_by_label("Microsoft 365 Run as", exact=True)).to_have_value(OWNER_ID)
    panel = open_ask_ai(editor)
    found = answered(panel, ask(ui, panel, "Collect only signed evidence in the first task."))

    assert change_keys(found) == ["task:task-a:instructions"]
    warnings = found.get_by_role("list", name="Warnings").locator("li[data-workflow-assist-warning]")
    expect(warnings).to_have_count(4)
    assert warnings.evaluate_all("items => items.map((item) => item.dataset.workflowAssistWarning)") == [
        "run_as_reapproval", "email_requires_m365_agent", "m365_not_connected", "draft_has_errors",
    ]
    expect(warnings).to_have_text([RUN_AS_WARNING, f"{EMAIL_MESSAGE}Jump to", M365_MESSAGE, DRAFT_ERRORS_MESSAGE])
    frame = changed(editor, "task:task-a:instructions")
    expect(author(frame)).to_have_text("AI assist")
    expect(frame.get_by_label("Instructions", exact=True)).to_have_value(instructions)

    found.get_by_role("button", name=f"Jump to: {EMAIL_MESSAGE}", exact=True).click()
    expect(task_item(editor, "task-b").get_by_label("Task name", exact=True)).to_be_focused()

    payload = confirm_save(ui, editor, run_as=True)
    assert payload["m365_run_as_user_id"] == OWNER_ID
    assert payload["tasks"][0]["instructions"] == instructions


# ---------------------------------------------------------------------------------------------
# # references
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("placement", ["shared", "document", "question", "context"])
def test_hash_document_placements_and_context(ask_ui, placement):
    ui = ask_ui
    answers = {
        "shared": ui.assist.changed({"op": "bind_reference", "document": "ref_1", "tasks": ["task_2"]}),
        "document": ui.assist.changed({
            "op": "set_task_document_target", "task": "task_2", "action": "analyze", "documents": ["ref_1"],
        }),
        "question": ui.assist.said("question", "Should both tasks read Private brief, or only the summary?"),
        "context": ui.assist.said("explained", "The brief asks for a quarterly review of signed evidence."),
    }
    ui.assist.queue(answers[placement])
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    box = pick_brief(ui, panel)
    box.press_sequentially("for the summary task")
    box.press("Enter")
    body = ui.assist.wait_for_requests(ui.page, 1)
    assert body["instruction"] == "Use #[Private brief] for the summary task"
    assert body["references"] == [BRIEF_REF]
    assert ui.document_searches and all(search == "priv" for _, search in ui.document_searches[-2:])

    found = answered(panel, body)
    expect(exchanges(panel).last.get_by_test_id("assist-reference-chip")).to_have_text("Document: Private brief")
    context = found.locator("[data-workflow-assist-context]")
    if placement == "shared":
        assert change_keys(found) == [BRIEF_KEY, "task:task-a:reference_ids"]
        expect(author(changed(editor, "task:task-a:reference_ids"))).to_have_text("AI assist")
        shared = editor.get_by_role("region", name="Workflow shared references", exact=True)
        expect(shared.locator(f"[data-workflow-change-key='{BRIEF_KEY}'] [data-workflow-change-author='ai']")).to_have_text(
            "Added · AI assist")
        expect(context).to_have_count(0)
    elif placement == "document":
        assert change_keys(found) == ["task:task-b:document_action"]
        expect(author(changed(editor, "task:task-b:document_action"))).to_have_text("AI assist")
        expect(context).to_have_count(0)
    else:
        expect(found).to_have_attribute("data-outcome", "question" if placement == "question" else "explained")
        expect(found.get_by_text("Question", exact=True)).to_have_count(1 if placement == "question" else 0)
        expect(found.locator("li[data-workflow-assist-change]")).to_have_count(0)
        expect(context).to_have_text("Read as context: private-brief.pdf")
        expect(editor.locator("[data-workflow-change-key]")).to_have_count(0)
        expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")
    assert not ui.workflow_writes


# ---------------------------------------------------------------------------------------------
# Sending, the lock, Cancel and Retry
# ---------------------------------------------------------------------------------------------

def test_send_is_immediate_and_locks_the_editor_until_cancel_then_retry(ask_ui):
    ui, page = ask_ui, ask_ui.page
    description = "Reviews signed evidence every quarter."
    ui.assist.hold = 1
    ui.assist.queue(
        ui.assist.changed({"op": "set_description", "description": description}),
        ui.assist.changed({"op": "set_description", "description": description}),
    )
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    box = composer(panel)
    type_and_send(panel, "Describe what this workflow reviews.")

    exchange = exchanges(panel).last
    expect(exchange).to_have_attribute("data-status", "pending")
    expect(exchange).to_contain_text("Describe what this workflow reviews.")
    expect(exchange).to_contain_text("Working…")
    expect(box).to_have_value("")
    expect(box).to_be_focused()
    body = ui.assist.wait_for_requests(page, 1)

    lock = editor.locator("[data-workflow-assist-lock]")
    expect(lock).to_contain_text("Ask AI is working. The editor is locked until it answers.")
    expect(lock.get_by_test_id("workflow-assist-lock-elapsed")).to_have_text(re.compile(r"^[1-9]\d* s$"), timeout=4000)
    # A disabled fieldset disables every control in it; Playwright's to_be_disabled ignores the fieldset itself.
    expect(editor.locator("fieldset[aria-busy='true']")).to_have_attribute("disabled", "")
    expect(editor.get_by_label("Workflow name", exact=True)).to_be_disabled()
    expect(editor.get_by_role("button", name="Save workflow", exact=True)).to_be_disabled()
    expect(send_button(panel)).to_be_disabled()
    quick = panel.get_by_role("group", name="Quick actions", exact=True).get_by_role("button")
    expect(quick).to_have_count(5)
    for index in range(5):
        expect(quick.nth(index)).to_be_disabled()

    lock.get_by_role("button", name="Cancel request", exact=True).click()
    expect(exchange).to_have_attribute("data-status", "cancelled")
    expect(exchange).to_contain_text(CANCELLED)
    expect(lock).to_have_count(0)
    expect(editor.get_by_label("Workflow name", exact=True)).to_be_enabled()
    expect(box).to_be_focused()

    # The answer that arrives after Cancel changes nothing.
    ui.assist.release()
    page.wait_for_timeout(300)
    expect(exchange).to_have_attribute("data-status", "cancelled")
    expect(changed(editor, "description")).to_have_count(0)
    expect(editor.locator("section[aria-label='Workflow basics']").get_by_label("Description", exact=True)).to_have_value(
        ui.personal_workflows[WORKFLOW_ID]["description"])

    exchange.get_by_role("button", name="Retry", exact=True).click()
    retried = ui.assist.wait_for_requests(page, 2)
    assert retried["submission_id"] == body["submission_id"]
    assert retried["conversation"] == []
    found = answered(panel, retried)
    expect(found).to_have_attribute("data-state", "applied")
    expect(author(changed(editor, "description"))).to_have_text("AI assist")
    expect(exchanges(panel)).to_have_count(1)
    assert not ui.workflow_writes


def basics_description(editor):
    return editor.locator("section[aria-label='Workflow basics']").get_by_label("Description", exact=True)


def test_an_answer_for_a_draft_that_changed_meanwhile_applies_nothing(ask_ui):
    ui, page = ask_ui, ask_ui.page
    instructions, description = "Collect only signed evidence.", "Reviews signed evidence."
    operation = {"op": "set_task_instructions", "task": "task_1", "instructions": instructions}
    ui.assist.hold = 1
    ui.assist.queue(ui.assist.changed(operation), ui.assist.changed(operation))
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    type_and_send(panel, "Collect only signed evidence in the first task.")
    body = ui.assist.wait_for_requests(page, 1)

    # The lock is the first guard. This stands in for any edit that gets past it.
    fieldset = editor.locator("fieldset[aria-busy='true']")
    expect(fieldset).to_have_attribute("disabled", "")
    fieldset.evaluate("(element) => { element.disabled = false; }")
    basics_description(editor).fill(description)
    expect(author(changed(editor, "description"))).to_have_text("Edited")
    ui.assist.release()

    exchange = failed(panel)
    expect(exchange.get_by_role("alert")).to_have_text(STALE_DRAFT)
    expect(card(panel, body["submission_id"])).to_have_count(0)
    expect(editor.locator("[data-workflow-change-author='ai']")).to_have_count(0)
    expect(task_item(editor, "task-a").get_by_label("Instructions", exact=True)).to_have_value("Collect source evidence.")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")

    # Retry is the same turn, sent with the draft as it is now.
    exchange.get_by_role("button", name="Retry", exact=True).click()
    retried = ui.assist.wait_for_requests(page, 2)
    assert retried["submission_id"] == body["submission_id"]
    assert retried["draft"]["description"] == description
    assert retried["conversation"] == []
    found = answered(panel, retried)
    assert change_keys(found) == ["task:task-a:instructions"]
    expect(author(changed(editor, "task:task-a:instructions"))).to_have_text("AI assist")
    expect(author(changed(editor, "description"))).to_have_text("Edited")
    expect(basics_description(editor)).to_have_value(description)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (2 unsaved)")
    assert not ui.workflow_writes


def test_a_new_draft_sends_no_base_and_no_id_and_saves_after_review(ask_ui):
    ui, page = ask_ui, ask_ui.page
    name, instructions = "Evidence review", "Collect the quarter's signed evidence."
    ui.assist.queue(ui.assist.changed(
        {"op": "set_name", "name": name},
        {"op": "set_task_instructions", "task": "task_1", "instructions": instructions},
    ))
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    editor = page.get_by_role("dialog", name="Create workflow", exact=True)
    expect(editor).to_be_visible()
    editor.get_by_label("Model", exact=True).select_option(label="Workspace GPT · aoai")
    panel = open_ask_ai(editor)

    body = ask(ui, panel, "Call this Evidence review and have the task collect signed evidence.")
    assert set(body) == REQUEST_KEYS
    assert body["base"] is None
    assert "id" not in body["draft"]
    assert body["draft"]["name"] == ""
    task_id = body["draft"]["tasks"][0]["id"]
    found = answered(panel, body)
    assert change_keys(found) == ["name", f"task:{task_id}:instructions"]
    # A new draft points out only what the assistant changed.
    expect(author(changed(editor, "name"))).to_have_text("AI assist")
    expect(author(changed(editor, f"task:{task_id}:instructions"))).to_have_text("AI assist")
    expect(editor.locator("[data-workflow-change-author='user']")).to_have_count(0)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (2 unsaved)")

    payload = confirm_save(ui, editor)
    assert payload["name"] == name
    assert payload["tasks"][0]["instructions"] == instructions
    assert not payload.get("id")


def test_task_focus_scopes_turns_and_only_completed_turns_are_replayed(ask_ui):
    ui, page = ask_ui, ask_ui.page
    # A browser zone the schedule editor doesn't list is left out, so the server uses its default.
    ui.unlisted_schedule_timezones = {TIME_ZONE}
    reply, later = "The summary task condenses the evidence into findings.", "Both tasks run in order."
    ui.assist.queue(
        ui.assist.refused("assistant_output_invalid"),
        ui.assist.said("explained", "This answer arrives after Cancel."),
        ui.assist.said("explained", reply),
        ui.assist.said("explained", later),
    )
    editor = open_classic(ui)
    editor.get_by_role("button", name="Ask AI about this task: Summarize evidence", exact=True).click()
    panel = side_panel(editor)
    expect(panel.get_by_role("tab", name="Ask AI", exact=True)).to_have_attribute("aria-selected", "true")
    chip = panel.locator("[data-workflow-assist-focus='task-b']")
    expect(chip).to_contain_text("About: Summarize evidence")
    expect(composer(panel)).to_be_focused()
    expect(composer(panel)).to_have_attribute("aria-describedby", re.compile(r"\S"))

    first = ask(ui, panel, "Make this task shorter.")
    assert first["focus"] == "task-b"
    assert "time_zone" not in first
    expect(failed(panel).get_by_role("alert")).to_have_text(core._ERRORS["assistant_output_invalid"][1])

    ui.assist.hold = 1
    second = ask(ui, panel, "What does it read?")
    assert second["focus"] == "task-b" and second["conversation"] == []
    editor.locator("[data-workflow-assist-lock]").get_by_role("button", name="Cancel request", exact=True).click()
    expect(exchanges(panel).last).to_have_attribute("data-status", "cancelled")
    ui.assist.release()

    # The failed and the cancelled turns are never replayed, and the focus holds until it is cleared.
    third = ask(ui, panel, "What does this task do?")
    assert third["focus"] == "task-b" and third["conversation"] == []
    expect(answered(panel, third).locator("[data-workflow-assist-reply]")).to_have_text(reply)
    expect(chip).to_be_visible()
    panel.get_by_role("button", name="Stop asking about Summarize evidence", exact=True).click()
    expect(chip).to_have_count(0)
    expect(composer(panel)).to_be_focused()

    fourth = ask(ui, panel, "And the whole workflow?")
    assert fourth["focus"] is None
    assert fourth["conversation"] == [
        {"role": "user", "text": "What does this task do?"},
        {"role": "assistant", "text": reply},
    ]
    answered(panel, fourth)
    assert not ui.workflow_writes


def rename_flow_node(record, old, new):
    """Give a task's flow node an ID of its own, so the node and the task can't be confused."""
    nodes = record["flow"]["nodes"]
    next(node for node in nodes if node["id"] == old)["id"] = new
    for node in nodes:
        if (node.get("target") or {}).get("node_id") == old:
            node["target"]["node_id"] = new
    for output in record["flow"]["outputs"]:
        if output["source"]["node_id"] == old:
            output["source"]["node_id"] = new
    compile_workflow_flow(record)
    record["definition_revision"] = workflow_definition_revision(record)


def test_flow_focus_sends_the_node_and_jump_selects_its_block(ask_ui):
    ui = ask_ui
    rename_flow_node(ui.personal_workflows[FLOW_WORKFLOW_ID], "finish", "finish-step")
    instructions = "Produce the finish result as three short bullet points."

    def finish_instructions(body):
        handle = [task["id"] for task in body["draft"]["tasks"]].index("finish") + 1
        return {"op": "set_task_instructions", "task": f"task_{handle}", "instructions": instructions}

    ui.assist.queue(ui.assist.changed(finish_instructions))
    editor = authoring.open_editor(ui)
    view = authoring.switch_surface(editor, "Flow")
    fields = authoring.select_node(view, "finish-step")
    fields.get_by_role("button", name="Ask AI about this task: Finish", exact=True).click()
    panel = side_panel(editor)
    expect(panel.locator("[data-workflow-assist-focus='finish']")).to_contain_text("About: Finish")
    expect(composer(panel)).to_be_focused()

    body = ask(ui, panel, "Make the finish result three bullet points.")
    assert body["draft"]["definition_version"] == 3
    assert body["focus"] == "finish-step"
    found = answered(panel, body)
    assert change_keys(found) == ["task:finish:instructions"]

    authoring.select_node(view, "evaluate")
    found.get_by_role("button", name="Jump to Finish: Instructions", exact=True).click()
    expect(authoring.node_button(view, "finish-step")).to_have_attribute("aria-pressed", "true")
    field = authoring.configuration(view).get_by_label("Instructions", exact=True)
    expect(field).to_be_focused()
    expect(field).to_have_value(instructions)
    expect(author(changed(authoring.configuration(view), "task:finish:instructions"))).to_have_text("AI assist")
    assert not ui.workflow_writes


# ---------------------------------------------------------------------------------------------
# The instruction limit and Undo
# ---------------------------------------------------------------------------------------------

def test_the_instruction_limit_counts_code_points_like_the_server(ask_ui):
    ui, page = ask_ui, ask_ui.page
    reply = "That is a lot of stars."
    ui.assist.queue(ui.assist.said("explained", reply))
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    box = composer(panel)
    # Each star is two UTF-16 units, so counting units would refuse both of these.
    star = "\U0001F31F"

    over = star * 2001
    box.fill(over)
    expect(panel.get_by_text("2001/2000", exact=True)).to_be_visible()
    expect(panel.get_by_text("This is 1 character over the limit. Shorten it to send.", exact=True)).to_be_visible()
    expect(box).to_have_attribute("aria-invalid", "true")
    expect(send_button(panel)).to_be_disabled()
    box.press("Enter")
    page.wait_for_timeout(300)
    assert not ui.assist.bodies
    expect(box).to_have_value(over)

    exact = star * 2000
    box.fill(exact)
    expect(panel.get_by_text("2000/2000", exact=True)).to_be_visible()
    expect(box).not_to_have_attribute("aria-invalid", "true")
    expect(send_button(panel)).to_be_enabled()
    box.press("Enter")
    body = ui.assist.wait_for_requests(page, 1)
    # Python counts code points, as the server does.
    assert body["instruction"] == exact and len(body["instruction"]) == 2000
    expect(answered(panel, body).locator("[data-workflow-assist-reply]")).to_have_text(reply)


def test_undo_skips_a_field_changed_later_and_jump_reaches_a_task_field(ask_ui):
    ui = ask_ui
    described, instructions, mine = "Reviews the quarter.", "Collect only signed evidence.", "Reviews the signed quarter."
    ui.assist.queue(ui.assist.changed(
        {"op": "set_description", "description": described},
        {"op": "set_task_instructions", "task": "task_1", "instructions": instructions},
    ))
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    found = answered(panel, ask(ui, panel, "Describe the review and have the first task collect signed evidence."))
    assert change_keys(found) == ["description", "task:task-a:instructions"]

    field = task_item(editor, "task-a").get_by_label("Instructions", exact=True)
    found.get_by_role("button", name="Jump to Collect evidence: Instructions", exact=True).click()
    expect(field).to_be_focused()
    expect(field).to_have_value(instructions)
    # At this width the panel sits beside the editor, so it stays open.
    expect(ask_toggle(editor)).to_have_attribute("aria-expanded", "true")

    basics_description(editor).fill(mine)
    expect(author(changed(editor, "description"))).to_have_text("Edited")
    undo_button(found).click()
    result = found.locator("[data-workflow-assist-undo='applied']")
    expect(result).to_be_focused()
    expect(result.locator("p").first).to_have_text("Undone: 1 reverted, 1 skipped because it changed later.")
    expect(result.get_by_role("list", name="Reverted").get_by_role("listitem")).to_have_text(
        ["Collect evidence · Instructions"])
    expect(result.get_by_role("list", name="Skipped").get_by_role("listitem")).to_have_text(
        ["Description: Changed after this turn."])
    expect(found).to_have_attribute("data-state", "partly_undone")
    expect(found.locator("[data-workflow-assist-state]")).to_have_text("Some of these changes were undone.")
    expect(undo_button(found)).to_have_count(0)
    expect(field).to_have_value("Collect source evidence.")
    expect(changed(editor, "task:task-a:instructions")).to_have_count(0)
    expect(basics_description(editor)).to_have_value(mine)
    expect(author(changed(editor, "description"))).to_have_text("Edited")
    # Jump to still reaches a field the turn no longer changes, which has no highlight to find.
    found.get_by_role("button", name="Jump to Collect evidence: Instructions", exact=True).click()
    expect(field).to_be_focused()
    assert not ui.workflow_writes


# ---------------------------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------------------------

def another_turns_answer(body):
    """A well-formed answer, but for a different turn."""
    return 200, {
        "submission_id": f"{body['submission_id']}-other", "outcome": "explained", "reply": "This is for another turn.",
        "candidate": None, "changes": [], "warnings": [], "context_documents": [],
    }, {}


def test_every_failure_changes_nothing_and_says_why(ask_ui):
    ui, page = ask_ui, ask_ui.page
    stub = ui.assist
    cases = [
        # The route's decorators answer before the assistant runs.
        (stub.canned(400, {"error": "Allow User Workflows is disabled."}), "Allow User Workflows is disabled."),
        (stub.canned(403, {"error": "Forbidden", "message": "Personal workflows require the WorkflowUser app role."}),
         "Personal workflows require the WorkflowUser app role."),
        (stub.canned(403, {"error": "The AI workflow assistant is not available.", "code": "workflow_assistant_disabled"}),
         "The AI workflow assistant is not available."),
        *[(stub.refused(code), core._ERRORS[code][1]) for code in (
            "time_zone_invalid", "assistant_input_too_large", "workflow_not_found", "request_too_large",
            "assistant_failed", "assistant_refused", "assistant_timeout", "assistant_limit_unavailable",
            "reference_check_failed",
        )],
        (stub.canned(502, None), UNUSABLE),
        (stub.custom(another_turns_answer), UNREADABLE),
    ]
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    for index, (answer, message) in enumerate(cases, 1):
        stub.queue(answer)
        ask(ui, panel, f"Change attempt {index}.")
        exchange = failed(panel)
        expect(exchange.get_by_role("alert")).to_have_text(message)
        expect(exchange.get_by_role("button", name="Retry", exact=True)).to_be_enabled()
        expect(panel.locator("[data-workflow-assist-wait]")).to_have_count(0)
    expect(panel.locator("[data-workflow-assist-reload]")).to_have_count(0)
    expect(editor.locator("[data-workflow-change-key]")).to_have_count(0)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")

    # A 502 changed nothing, so Retry sends the same turn again.
    explained = "It collects evidence, then summarizes it."
    stub.queue(stub.refused("assistant_output_invalid"), stub.said("explained", explained))
    body = ask(ui, panel, "What does this workflow do?")
    exchange = failed(panel)
    expect(exchange.get_by_role("alert")).to_have_text(core._ERRORS["assistant_output_invalid"][1])
    sent = len(stub.bodies)
    exchange.get_by_role("button", name="Retry", exact=True).click()
    retried = stub.wait_for_requests(page, sent + 1)
    assert retried["submission_id"] == body["submission_id"]
    expect(answered(panel, retried).locator("[data-workflow-assist-reply]")).to_have_text(explained)

    # A 429, or a 503 from a throttled provider, asks for a wait; Send waits that long.
    stub.settings.update({"enable_custom_rate_limit_message": True, "rate_limit_message": RATE_LIMIT_TEXT})
    note = panel.locator("[data-workflow-assist-wait]")
    waits = [
        ("assistant_unavailable", core._ERRORS["assistant_unavailable"][1]),
        ("assistant_busy", core._ERRORS["assistant_busy"][1]),
        # The admin's Markdown is shown as the text it is, with its whitespace collapsed.
        ("assistant_rate_limited", " ".join(RATE_LIMIT_TEXT.split())),
    ]
    for code, message in waits:
        stub.queue(stub.refused(code, retry_after=5))
        sent = len(stub.bodies)
        ask(ui, panel, f"Try {code}.")
        exchange = failed(panel)
        expect(exchange.get_by_role("alert")).to_have_text(message)
        expect(exchange.locator(MARKUP)).to_have_count(0)
        expect(note).to_have_text(WAIT_NOTE)
        box = composer(panel)
        box.fill("Try once more.")
        expect(send_button(panel)).to_be_disabled()
        expect(exchange.get_by_role("button", name="Retry", exact=True)).to_be_disabled()
        expect(panel.get_by_role("group", name="Quick actions", exact=True).get_by_role("button").first).to_be_disabled()
        box.press("Enter")
        page.wait_for_timeout(200)
        assert len(stub.bodies) == sent + 1
        expect(box).to_have_value("Try once more.")
        expect(note).to_have_count(0, timeout=8000)
        expect(send_button(panel)).to_be_enabled()
        expect(exchange.get_by_role("button", name="Retry", exact=True)).to_be_enabled()
        box.fill("")

    expect(editor.locator("[data-workflow-change-key]")).to_have_count(0)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")
    assert not ui.workflow_writes


def test_a_conflict_keeps_the_draft_and_offers_a_reload(ask_ui):
    ui, page = ask_ui, ask_ui.page
    stored = ui.personal_workflows[WORKFLOW_ID]
    mine = "Quarterly review, my draft"
    editor = open_classic(ui)
    name = editor.get_by_label("Workflow name", exact=True)
    name.fill(mine)
    panel = open_ask_ai(editor)

    stored["deleting"] = True
    ui.assist.queue(ui.assist.pipeline())
    ask(ui, panel, "Add a description.")
    expect(failed(panel).get_by_role("alert")).to_have_text(
        f"{core._ERRORS['workflow_deleted'][1]} Your draft is still in the editor.")
    expect(panel.locator("[data-workflow-assist-reload]")).to_have_count(0)
    expect(name).to_have_value(mine)

    del stored["deleting"]
    ui.mutate_revision()
    ui.assist.queue(ui.assist.pipeline())
    ask(ui, panel, "Add a description.")
    expect(failed(panel).get_by_role("alert")).to_have_text(core._ERRORS["workflow_definition_conflict"][1])
    expect(name).to_have_value(mine)
    expect(author(changed(editor, "name"))).to_have_text("Edited")
    assert not ui.workflow_writes

    group = panel.get_by_role("group", name="Reload workflow", exact=True)
    expect(group.locator("p").first).to_have_text(
        "The saved workflow changed after you opened it. Reload it to keep using Ask AI.")
    reload = group.get_by_role("button", name="Reload workflow", exact=True)
    reload.click()
    expect(group.locator("p").first).to_have_text("Reloading discards your unsaved changes to this workflow.")
    keep = group.get_by_role("button", name="Keep editing", exact=True)
    expect(keep).to_be_focused()
    keep.click()
    expect(reload).to_be_focused()
    expect(name).to_have_value(mine)
    reload.click()
    group.get_by_role("button", name="Discard and reload", exact=True).click()

    # The editor opens again on the saved workflow as it is now.
    editor = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(editor.get_by_label("Workflow name", exact=True)).to_have_value("Quarterly review workflow")
    expect(side_panel(editor)).to_have_count(0)
    expect(editor.locator("[data-workflow-change-key]")).to_have_count(0)
    ui.assist.queue(ui.assist.said("explained", "It reviews the quarter."))
    panel = open_ask_ai(editor)
    expect(panel.locator("[data-workflow-assist-reload]")).to_have_count(0)
    body = ask(ui, panel, "What does it review?")
    assert body["base"] == {"workflow_id": WORKFLOW_ID, "definition_revision": "revision:external-change"}
    assert body["conversation"] == []
    answered(panel, body)
    assert not ui.workflow_writes


RELOAD_READS = ("/api/user/workflows", "/api/user/workflows/editor-options")


def conflicted_editor(ui, mine, *, applied=None):
    """The saved workflow, renamed here and changed elsewhere, so Ask AI offers to reload it.

    With `applied`, an earlier turn made that change first, and its card is returned as well.
    """
    editor = open_classic(ui)
    name = editor.get_by_label("Workflow name", exact=True)
    name.fill(mine)
    panel = open_ask_ai(editor)
    found = None
    if applied:
        ui.assist.queue(ui.assist.changed(applied))
        found = answered(panel, ask(ui, panel, "Collect only signed evidence in the first task."))
        expect(undo_button(found)).to_be_enabled()
    ui.mutate_revision()
    ui.assist.queue(ui.assist.pipeline())
    ask(ui, panel, "Add a description.")
    expect(failed(panel).get_by_role("alert")).to_have_text(core._ERRORS["workflow_definition_conflict"][1])
    return editor, panel, name, found


def held(ui, method):
    return sorted(entry.path for _, entry in ui.pending_responses if entry.method == method)


def wait_until_held(ui, method, paths):
    """Wait until the page has made each of `paths`, and they are the `method` requests held."""
    waited = 0
    while len(held(ui, method)) < len(paths):
        assert waited < 10000, f"The held {method} requests never arrived."
        ui.page.wait_for_timeout(50)
        waited += 50
    assert held(ui, method) == sorted(paths)


def hold_reload(ui, panel):
    """Choose Discard and reload with both of the reload's reads held, so it is still loading."""
    group = panel.get_by_role("group", name="Reload workflow", exact=True)
    group.get_by_role("button", name="Reload workflow", exact=True).click()
    for path in RELOAD_READS:
        ui.defer_next("GET", path)
    group.get_by_role("button", name="Discard and reload", exact=True).click()
    expect(group.get_by_role("button", name="Reloading…", exact=True)).to_be_disabled()
    wait_until_held(ui, "GET", RELOAD_READS)
    return group


def finished(path, method="GET"):
    return lambda request: request.method == method and urlsplit(request.url).path == path


def release_reload(ui):
    """Answer the held reads, and wait until the page has read both before anything is checked."""
    page = ui.page
    with page.expect_event("requestfinished", predicate=finished(RELOAD_READS[0])):
        with page.expect_event("requestfinished", predicate=finished(RELOAD_READS[1])):
            ui.release_responses()
    # The page acts on the answers once it has read them; give it time to do the wrong thing.
    page.wait_for_timeout(500)


def discard_and_close(page, editor):
    page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True).get_by_role(
        "button", name="Discard changes", exact=True).click()
    expect(editor).to_have_count(0)


def test_a_closed_editor_stays_closed_when_its_reload_finishes(ask_ui):
    ui, page = ask_ui, ask_ui.page
    mine = "Quarterly review, my draft"
    editor, panel, name, _ = conflicted_editor(ui, mine)
    hold_reload(ui, panel)

    # The draft the reload is about to discard is locked while it loads. Closing is not.
    expect(name).to_be_disabled()
    expect(name).to_have_value(mine)
    expect(editor.get_by_role("button", name="Save workflow", exact=True)).to_be_disabled()
    expect(panel.get_by_role("group", name="Quick actions", exact=True).get_by_role("button").first).to_be_disabled()
    expect(editor.get_by_role("button", name="Cancel", exact=True)).to_be_enabled()
    page.keyboard.press("Escape")
    discard_and_close(page, editor)

    release_reload(ui)
    expect(editor).to_have_count(0)
    expect(page.get_by_role("button", name="Edit Quarterly review workflow", exact=True)).to_be_visible()
    assert not ui.workflow_writes


def test_a_reload_never_replaces_another_workflows_editor(ask_ui):
    ui, page = ask_ui, ask_ui.page
    other = ui.personal_workflows[FLOW_WORKFLOW_ID]["name"]
    editor, panel, _, _ = conflicted_editor(ui, "Quarterly review, my draft")
    hold_reload(ui, panel)
    editor.get_by_role("button", name="Cancel", exact=True).click()
    discard_and_close(page, editor)

    # Another workflow is opened and edited while the first one's reload is still loading.
    page.get_by_role("button", name=f"Edit {other}", exact=True).click()
    name = editor.get_by_label("Workflow name", exact=True)
    expect(name).to_have_value(other)
    typed = f"{other}, my draft"
    name.fill(typed)

    release_reload(ui)
    expect(editor).to_have_count(1)
    expect(name).to_have_value(typed)
    expect(name).to_be_enabled()
    expect(page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True)).to_have_count(0)
    assert not ui.workflow_writes


def test_a_failed_reload_unlocks_the_draft_it_kept(ask_ui):
    ui = ask_ui
    mine = "Quarterly review, my draft"
    operation = {"op": "set_task_instructions", "task": "task_1", "instructions": "Collect only signed evidence."}
    editor, panel, name, found = conflicted_editor(ui, mine, applied=operation)
    group = hold_reload(ui, panel)
    expect(name).to_be_disabled()
    expect(undo_button(found)).to_be_disabled()

    ui.fail_held_responses()
    expect(group.get_by_role("alert")).to_have_text("Couldn't reload the workflow. Try again.")
    expect(group.get_by_role("button", name="Reload workflow", exact=True)).to_be_focused()
    expect(name).to_be_enabled()
    expect(name).to_have_value(mine)
    expect(undo_button(found)).to_be_enabled()
    expect(author(changed(editor, "task:task-a:instructions"))).to_have_text("AI assist")
    expect(editor.get_by_role("button", name="Save workflow", exact=True)).to_be_enabled()
    expect(panel.get_by_role("group", name="Quick actions", exact=True).get_by_role("button").first).to_be_enabled()
    assert not ui.workflow_writes


def test_a_save_that_lands_during_a_reload_keeps_the_editor_closed(ask_ui):
    ui, page = ask_ui, ask_ui.page
    stored = ui.personal_workflows[WORKFLOW_ID]
    opened = stored["definition_revision"]
    mine = "Quarterly review, my draft"
    editor, panel, _, _ = conflicted_editor(ui, mine)

    # Saving locks the form, not the side panel, so Discard and reload can be chosen mid-save.
    ui.defer_next("POST", "/api/user/workflows")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    wait_until_held(ui, "POST", ["/api/user/workflows"])
    hold_reload(ui, panel)

    # The change made elsewhere is undone, so the save is accepted and lands first. The editor
    # closes on the saved workflow, and the list is read again.
    stored["definition_revision"] = opened
    with page.expect_event("requestfinished", predicate=finished(RELOAD_READS[0])):
        ui.release_held("POST", "/api/user/workflows")
    expect(editor).to_have_count(0)
    assert len(ui.workflow_writes) == 1
    assert ui.workflow_writes[0].body["name"] == mine

    # The reload finishes after the save, and is ignored.
    release_reload(ui)
    expect(editor).to_have_count(0)
    expect(page.get_by_role("button", name=f"Edit {mine}", exact=True)).to_be_visible()
    assert len(ui.workflow_writes) == 1


# ---------------------------------------------------------------------------------------------
# Undo and redo keys while the draft is locked
# ---------------------------------------------------------------------------------------------

HISTORY_KEYS = ("Control+z", "Control+y", "Control+Shift+z")
FIRST_NAME, SECOND_NAME = "Branch review, first edit", "Branch review, second edit"


def history_button(editor, direction):
    return editor.get_by_role("button", name=f"{direction} workflow edit", exact=True)


def structured_editor_with_history(ui):
    """The structured workflow with one edit left to undo and one to redo, so every key has work to do.

    Also returns a block: it is not a text field, and it stays focusable inside the locked fieldset,
    so its keys reach workflow history rather than a field's own undo.
    """
    editor = authoring.open_editor(ui)
    name = editor.get_by_label("Workflow name", exact=True)
    for typed in (FIRST_NAME, SECOND_NAME):
        name.fill(typed)
        name.press("Tab")
    history_button(editor, "Undo").click()
    expect(name).to_have_value(FIRST_NAME)
    expect(history_button(editor, "Undo")).to_have_attribute("aria-disabled", "false")
    expect(history_button(editor, "Redo")).to_have_attribute("aria-disabled", "false")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")
    return editor, name, authoring.list_block(editor, "evaluate")


def expect_history_keys_ignored(ui, editor, name, block, reason):
    """Each undo and redo key on the block changes nothing, and says nothing."""
    for direction in ("Undo", "Redo"):
        expect(history_button(editor, direction)).to_have_attribute("title", reason)
    alerts = editor.get_by_role("alert").count()
    block.focus()
    expect(block).to_be_focused()
    for key in HISTORY_KEYS:
        ui.page.keyboard.press(key)
        # Give a key that got through time to change the draft.
        ui.page.wait_for_timeout(200)
        expect(name).to_have_value(FIRST_NAME)
        expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")
        expect(editor.get_by_role("alert")).to_have_count(alerts)
    expect(block).to_be_focused()


def expect_history_keys_work(ui, name, block, original):
    """The same keys on the same block undo and redo once the draft is unlocked."""
    for key, value in zip(HISTORY_KEYS, (original, FIRST_NAME, SECOND_NAME)):
        block.focus()
        ui.page.keyboard.press(key)
        expect(name).to_have_value(value)


def test_undo_and_redo_keys_wait_while_ask_ai_works(ask_ui):
    ui = ask_ui
    original = ui.personal_workflows[FLOW_WORKFLOW_ID]["name"]
    editor, name, block = structured_editor_with_history(ui)
    panel = open_ask_ai(editor)
    ui.assist.hold = 1
    ui.assist.queue(ui.assist.said("explained", "It reviews each branch."))
    ask(ui, panel, "What does this workflow review?")
    lock = editor.locator("[data-workflow-assist-lock]")
    expect(lock).to_be_visible()

    expect_history_keys_ignored(ui, editor, name, block, "Wait for Ask AI to finish, or cancel it.")

    lock.get_by_role("button", name="Cancel request", exact=True).click()
    expect(lock).to_have_count(0)
    ui.assist.release()
    expect_history_keys_work(ui, name, block, original)
    assert not ui.workflow_writes


def test_undo_and_redo_keys_wait_while_the_saved_workflow_reloads(ask_ui):
    ui = ask_ui
    original = ui.personal_workflows[FLOW_WORKFLOW_ID]["name"]
    editor, name, block = structured_editor_with_history(ui)
    panel = open_ask_ai(editor)
    ui.mutate_revision(FLOW_WORKFLOW_ID)
    ui.assist.queue(ui.assist.pipeline())
    ask(ui, panel, "Add a description.")
    expect(failed(panel).get_by_role("alert")).to_have_text(core._ERRORS["workflow_definition_conflict"][1])
    group = hold_reload(ui, panel)

    expect_history_keys_ignored(ui, editor, name, block, "Wait for the saved workflow to reload.")

    ui.fail_held_responses()
    expect(group.get_by_role("alert")).to_have_text("Couldn't reload the workflow. Try again.")
    expect(name).to_be_enabled()
    expect_history_keys_work(ui, name, block, original)
    assert not ui.workflow_writes


# ---------------------------------------------------------------------------------------------
# Untrusted text and the client's own diff
# ---------------------------------------------------------------------------------------------

def test_model_text_renders_as_text_and_only_the_clients_diff_is_listed(ask_ui):
    ui, page = ask_ui, ask_ui.page
    described, instructions = "Reviews the quarter.", "Collect only signed evidence."
    answer = ui.assist.changed(
        {"op": "set_description", "description": described},
        {"op": "set_task_instructions", "task": "task_1", "instructions": instructions},
    )

    def tampered(raw):
        status, payload, headers = answer(raw)
        payload = copy.deepcopy(payload)
        reported = {change["key"]: change for change in payload["changes"]}
        description = reported["description"]
        description.update(summary=HOSTILE, label=HOSTILE)
        # The instructions entry is left out and a name change that never happened is made up.
        made_up = {**copy.deepcopy(description), "key": "name", "label": "Workflow name",
                   "summary": "Workflow: Workflow name", "target": {"focus_key": "name"}}
        payload.update(
            reply=HOSTILE, changes=[description, made_up],
            warnings=[{"code": "m365_not_connected", "message": HOSTILE}], context_documents=[HOSTILE],
        )
        return status, payload, headers

    ui.assist.queue(tampered)
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    found = answered(panel, ask(ui, panel, "Describe it and tighten the first task."))

    expect(found.locator("[data-workflow-assist-reply]")).to_have_text(HOSTILE)
    # The list is the client's diff of the draft it sent against the candidate.
    assert change_keys(found) == ["description", "task:task-a:instructions"]
    expect(found.locator("li[data-workflow-assist-change='description'] span")).to_have_text(HOSTILE)
    expect(found.locator("li[data-workflow-assist-change='task:task-a:instructions'] span")).to_have_text(
        "Collect evidence: Instructions")
    expect(found.get_by_role("button", name=f"Jump to {HOSTILE}", exact=True)).to_have_count(1)
    expect(found.locator("li[data-workflow-assist-warning='m365_not_connected'] span")).to_have_text(HOSTILE)
    expect(found.locator("[data-workflow-assist-context]")).to_have_text(f"Read as context: {HOSTILE}")
    expect(found.locator(MARKUP)).to_have_count(0)
    assert page.evaluate("() => window.__hostile ?? null") is None

    expect(author(changed(editor, "description"))).to_have_text("AI assist")
    expect(author(changed(editor, "task:task-a:instructions"))).to_have_text("AI assist")
    expect(changed(editor, "name")).to_have_count(0)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (2 unsaved)")
    assert not ui.workflow_writes


# ---------------------------------------------------------------------------------------------
# Where Ask AI is offered
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("restriction", ["setting_off", "group", "reader", "unsupported", "schedule"])
def test_ask_ai_is_offered_only_for_personal_workflows_the_editor_can_change(ask_ui, restriction):
    ui, page = ask_ui, ask_ui.page
    if restriction == "setting_off":
        # The bootstrap turns it off for this user: the setting, personal workflows or the role.
        ui.ask_ai_enabled = False
        editor = open_classic(ui)
    elif restriction == "group":
        editor = authoring.open_editor(ui, group_id=GROUP_ID)
    elif restriction == "reader":
        ui.group_can_manage = False
        ui.open("/groups")
        ui.select_group(GROUP_ID)
        page.get_by_role("button", name="View Alpha read-only Flow", exact=True).click()
        editor = page.get_by_role("dialog", name="Edit workflow", exact=True)
    elif restriction == "unsupported":
        ui.personal_workflows[FLOW_WORKFLOW_ID]["flow"]["nodes"][0]["future_executor"] = {"unchanged": True}
        ui.open(f"/workspace/workflows?workflow_id={FLOW_WORKFLOW_ID}")
        editor = page.get_by_role("dialog", name="Edit workflow", exact=True)
    else:
        ui.personal_workflows[WORKFLOW_ID].update(trigger_type="interval", schedule=copy.deepcopy(UNSUPPORTED_SCHEDULE))
        ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}")
        editor = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(editor).to_be_visible()

    if restriction in ("setting_off", "group"):
        # The editor can change these workflows, so a task with no instructions would offer Draft with
        # AI if Ask AI were available.
        instructions = editor.get_by_label("Instructions", exact=True).first
        instructions.fill("")
        expect(instructions).to_have_value("")
        panel = open_panel(editor)
        expect(panel.get_by_role("tab")).to_have_count(1)
        expect(panel.locator("[data-workflow-ask-ai]")).to_have_count(0)
    else:
        expect(editor).to_contain_text("This workflow is read-only.")
        expect(editor.locator("aside")).to_have_count(0)
    expect(ask_toggle(editor)).to_have_count(0)
    expect(editor.locator("[data-workflow-ask-ai-task]")).to_have_count(0)
    expect(editor.locator("[data-workflow-draft-ai]")).to_have_count(0)
    expect(editor.get_by_role("button", name=re.compile(r"^(Ask AI|Draft with AI)"))).to_have_count(0)
    assert not ui.assist.bodies and not ui.drafts.bodies
    assert not ui.workflow_writes


# ---------------------------------------------------------------------------------------------
# Keyboard and narrow screens
# ---------------------------------------------------------------------------------------------

def test_keyboard_tabs_the_hash_menu_and_escape(ask_ui):
    ui, page = ask_ui, ask_ui.page
    # A tag that "#brief" would match, if tags were offered.
    ui.extra_gets["/api/documents/tags"] = {"tags": [{"name": "brief-notes"}]}
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    changes_tab = panel.get_by_role("tab", name="Changes", exact=True)
    ask_tab = panel.get_by_role("tab", name="Ask AI", exact=True)
    expect(panel.get_by_role("tab")).to_have_count(2)
    ask_tab.focus()
    for key, tab, other in (
        ("ArrowRight", changes_tab, ask_tab), ("ArrowLeft", ask_tab, changes_tab),
        ("Home", changes_tab, ask_tab), ("End", ask_tab, changes_tab),
    ):
        page.keyboard.press(key)
        expect(tab).to_be_focused()
        expect(tab).to_have_attribute("aria-selected", "true")
        expect(tab).to_have_attribute("tabindex", "0")
        expect(other).to_have_attribute("aria-selected", "false")
        expect(other).to_have_attribute("tabindex", "-1")
        expect(panel.get_by_role("tabpanel")).to_have_attribute("aria-labelledby", tab.get_attribute("id"))

    # The # menu offers documents only, and Escape closes it without closing the panel.
    tag_reads = sum(1 for entry in ui.requests if entry.path.endswith("/tags"))
    box = composer(panel)
    box.fill("Use ")
    box.press_sequentially("#brief")
    menu = page.get_by_role("listbox", name="Context suggestions")
    expect(menu.get_by_role("option").first).to_contain_text("Private brief")
    expect(menu.get_by_text("Documents", exact=True)).to_be_visible()
    expect(menu.get_by_text("Tags", exact=True)).to_have_count(0)
    expect(menu.get_by_text("Workspaces", exact=True)).to_have_count(0)
    expect(menu.get_by_text(re.compile(r"^Tag ·"))).to_have_count(0)
    expect(menu.get_by_text("brief-notes")).to_have_count(0)
    assert sum(1 for entry in ui.requests if entry.path.endswith("/tags")) == tag_reads
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    expect(side_panel(editor)).to_be_visible()
    expect(box).to_be_focused()
    expect(box).to_have_value("Use #brief")

    # So does the document picker, and focus carries on in the input.
    box.fill("")
    panel.get_by_role("button", name="Add context", exact=True).click()
    search = panel.get_by_role("searchbox", name="Search documents", exact=True)
    expect(search).to_be_focused()
    page.keyboard.press("Escape")
    expect(search).to_have_count(0)
    expect(side_panel(editor)).to_be_visible()
    expect(box).to_be_focused()

    # With nothing open in it, Escape closes the panel and returns to its toggle, not the editor.
    page.keyboard.press("Escape")
    expect(side_panel(editor)).to_have_count(0)
    expect(ask_toggle(editor)).to_be_focused()
    expect(ask_toggle(editor)).to_have_attribute("aria-expanded", "false")
    expect(editor).to_be_visible()
    assert not ui.assist.bodies


def test_a_narrow_screen_shows_ask_ai_in_place_of_the_editor(ask_ui):
    ui = ask_ui
    described = "Reviews the quarter's signed evidence."
    ui.assist.queue(ui.assist.changed({"op": "set_description", "description": described}))
    editor = open_classic(ui, width=390, height=844)
    name = editor.get_by_label("Workflow name", exact=True)
    assert_dialog_fits(ui, editor)
    panel = open_ask_ai(editor)
    expect(name).to_be_hidden()
    assert_dialog_fits(ui, editor)

    found = answered(panel, ask(ui, panel, "Describe what it reviews."))
    found.get_by_role("button", name="Jump to Workflow: Description", exact=True).click()
    expect(side_panel(editor)).to_have_count(0)
    expect(ask_toggle(editor)).to_have_attribute("aria-expanded", "false")
    description = basics_description(editor)
    expect(description).to_be_focused()
    expect(description).to_have_value(described)
    expect(author(changed(editor, "description"))).to_have_text("AI assist")
    assert_dialog_fits(ui, editor)
    assert not ui.workflow_writes


# ---------------------------------------------------------------------------------------------
# Draft with AI, quick actions and an earlier editing session
# ---------------------------------------------------------------------------------------------

@contextmanager
def cpu_throttled(page, rate=6):
    """Slow the page's CPU like a slower device, so the highlight's deferred render lands after the jump."""
    try:
        session = page.context.new_cdp_session(page)
    except Exception as error:  # noqa: BLE001 - only Chromium has the DevTools protocol
        pytest.skip(f"This browser cannot throttle the CPU: {error}")
    session.send("Emulation.setCPUThrottlingRate", {"rate": rate})
    try:
        yield
    finally:
        session.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        session.detach()


def record_focus(page):
    """Log every element that takes focus from now on, so focus that leaves and comes back is still caught."""
    page.evaluate("""() => {
        window.__workflowFocusLog = [];
        document.addEventListener('focusin', (event) => window.__workflowFocusLog.push(event.target), true);
    }""")


def stray_focus(field):
    """Everything that took focus since record_focus, other than Draft with AI's button and the field."""
    return field.evaluate("""(field) => window.__workflowFocusLog
        .filter((target) => target !== field && !target.matches('[data-workflow-draft-ai]'))
        .map((target) => target.getAttribute('aria-label') || target.id || target.tagName)""")


def test_draft_with_ai_fills_an_empty_task_as_an_undoable_ai_change(ask_ui):
    ui, page = ask_ui, ask_ui.page
    drafted = "Collect the quarter's signed evidence and list anything that is missing."
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    editor = page.get_by_role("dialog", name="Create workflow", exact=True)
    expect(editor).to_be_visible()
    editor.get_by_label("Model", exact=True).select_option(label="Workspace GPT · aoai")
    button = editor.get_by_role("button", name="Draft with AI: instructions for Task 1", exact=True)
    task_id = button.get_attribute("data-workflow-draft-ai")
    task = task_item(editor, task_id)
    status = task.locator("p[role='status']")

    # With nothing to go on, it asks for a name instead of guessing.
    button.click()
    expect(status).to_have_text(NEEDS_NAME)
    assert not ui.drafts.bodies

    editor.get_by_label("Workflow name", exact=True).fill("Evidence review")
    ui.drafts.queue(drafted)
    instructions = task.get_by_label("Instructions", exact=True)
    record_focus(page)
    # Focus reaches the drafted instructions even when the highlight renders after the jump.
    with cpu_throttled(page):
        button.click()
        expect(instructions).to_have_value(drafted, timeout=30_000)
        expect(instructions).to_be_focused(timeout=30_000)
        # And it stays there once the jump lands, with nothing else taking it on the way.
        page.wait_for_timeout(1_000)
        assert instructions.evaluate("element => element === document.activeElement")
        assert stray_focus(instructions) == []
    assert ui.drafts.bodies == [{
        "workflow_scope": "personal", "name": "Evidence review", "description": "", "brief": "Task 1",
    }]
    expect(author(changed(editor, f"task:{task_id}:instructions"))).to_have_text("AI assist")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")
    expect(button).to_have_count(0)
    assert not ui.assist.bodies

    payload = confirm_save(ui, editor)
    assert payload["name"] == "Evidence review"
    assert payload["tasks"][0]["instructions"] == drafted


def test_draft_with_ai_on_a_flow_block_focuses_its_drafted_instructions(ask_ui):
    ui = ask_ui
    drafted = "Summarize the evaluated decision as three short bullet points."
    record = ui.personal_workflows[FLOW_WORKFLOW_ID]
    # Saved without instructions, so nothing marks the field until Draft with AI fills it.
    next(task for task in record["tasks"] if task["id"] == "finish")["instructions"] = ""
    record["definition_revision"] = workflow_definition_revision(record)
    editor = authoring.open_editor(ui)
    view = authoring.switch_surface(editor, "Flow")
    fields = authoring.select_node(view, "finish")
    instructions = fields.get_by_label("Instructions", exact=True)
    expect(instructions).to_have_value("")
    expect(changed(editor, "task:finish:instructions")).to_have_count(0)

    ui.drafts.queue(drafted)
    record_focus(ui.page)
    # The change also asks the canvas to focus its block; the jump drops that request, so the drafted field keeps focus.
    with cpu_throttled(ui.page):
        fields.get_by_role("button", name="Draft with AI: instructions for Finish", exact=True).click()
        expect(instructions).to_have_value(drafted, timeout=30_000)
        expect(instructions).to_be_focused(timeout=30_000)
        ui.page.wait_for_timeout(1_000)
        assert instructions.evaluate("element => element === document.activeElement")
        # The block never took focus, even for a moment before the jump.
        assert stray_focus(instructions) == []
    expect(authoring.node_button(view, "finish")).to_have_attribute("aria-pressed", "true")
    expect(author(changed(fields, "task:finish:instructions"))).to_have_text("AI assist")
    assert ui.drafts.bodies == [{
        "workflow_scope": "personal", "name": record["name"], "description": record["description"], "brief": "Finish",
    }]
    assert not ui.assist.bodies
    assert not ui.workflow_writes


def test_quick_actions_send_visible_turns_and_cards_outlive_a_save(ask_ui):
    ui, page = ask_ui, ask_ui.page
    explained, described = "It collects evidence, then summarizes it.", "Reviews the quarter's evidence."
    ui.assist.queue(
        ui.assist.said("explained", explained),
        ui.assist.changed({"op": "set_description", "description": described}, text="Described."),
        ui.assist.said("explained", "It has a description now."),
    )
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    quick = panel.get_by_role("group", name="Quick actions", exact=True).get_by_role("button")
    expect(quick).to_have_text([
        "Explain this workflow", "Tighten task instructions", "Add a schedule", "Alert me only when urgent",
        "Check what's needed to run",
    ])
    quick.first.click()
    first = ui.assist.wait_for_requests(page, 1)
    assert first["instruction"] == EXPLAIN
    expect(exchanges(panel).first).to_contain_text(EXPLAIN)
    expect(answered(panel, first).locator("[data-workflow-assist-reply]")).to_have_text(explained)

    instruction = "Describe what it reviews."
    second = ask(ui, panel, instruction)
    expect(answered(panel, second)).to_have_attribute("data-state", "applied")
    payload = confirm_save(ui, editor)
    assert payload["description"] == described

    # The thread outlives the editor; its card now belongs to an earlier editing session.
    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    editor = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(basics_description(editor)).to_have_value(described)
    panel = open_ask_ai(editor)
    found = card(panel, second["submission_id"])
    expect(found).to_have_attribute("data-state", "earlier")
    expect(found.locator("[data-workflow-assist-state]")).to_have_text("Made in an earlier editing session.")
    expect(found.get_by_role("button", name=re.compile(r"^Jump to"))).to_have_count(0)
    undo_button(found).click()
    result = found.locator("[data-workflow-assist-undo='unavailable']")
    expect(result).to_be_focused()
    expect(result).to_have_text("This turn can no longer be undone.")
    expect(basics_description(editor)).to_have_value(described)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")

    third = ask(ui, panel, "Does it have a description?")
    assert third["conversation"] == [
        {"role": "user", "text": EXPLAIN},
        {"role": "assistant", "text": explained},
        {"role": "user", "text": instruction},
        {"role": "assistant", "text": (
            "Described.\n\nThese changes were made in an earlier editing session and may not have been saved: "
            "Workflow: Description."
        )},
    ]
    answered(panel, third)
    assert len(ui.workflow_writes) == 1
