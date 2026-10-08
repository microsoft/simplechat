# test_v2_orchestration_m365_inline_approval.py
"""
Real-component browser coverage for deciding a Microsoft 365 approval inside the chat.
Version: 0.261.302
Implemented in: 0.261.302

A plan step that had to read more of a SharePoint file than a quick read covers stopped for
the user's extended-analysis approval. The stopped attempt's message now offers that decision
inline. Choosing an option saves it through the approvals API and continues the plan at once:
no trip to Approvals, and no "Retry this failed step?" confirmation, because a Microsoft 365
plan step only reads data. The retry's answer then replaces the stopped attempt in the thread,
with no attempt notice; the saved attempts stay reachable from the answer's message details.

The production notice, inline card, controller, stores, message list, inspector and Review
drawer run in Chromium. Only HTTP responses are deterministic.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_m365_inline_approval.py -q
"""

import copy
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_recovery as recovery_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    RUN,
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
APPROVAL_ID = "m365-" + "a" * 64
CSRF_TOKEN = "m365-inline-approval-test-csrf-token-0001"
# The server's own message for this failure, from FAILURE_MESSAGES.
APPROVAL_MESSAGE = (
    "This step needs your approval before it can use Microsoft 365. Review it in Approvals, "
    "then select Retry from failed step."
)
ANSWER = "Comparison from saved reports and the recovered agent."


class InlineApprovalApi(recovery_tests.RecoveryApi):
    """The recovery API, a pending extended-analysis approval, and an optionally held retry run."""

    def __init__(self, assets):
        super().__init__(assets)
        self.failure = {
            "code": "m365_approval_required", "message": APPROVAL_MESSAGE,
            "m365_sources": ["spo"], "approval_id": APPROVAL_ID,
        }
        self.approval = {
            "id": APPROVAL_ID, "request_type": "m365_extended_analysis", "approval_scope": "user",
            "status": "pending", "group_name": "Microsoft 365", "context": {"shared": False},
            "sources": {"spo": {
                "maximum_sharing_acknowledgement": "always",
                "allowed_durations": ["request", "today", "always"], "generation": 1,
            }},
            "proposal": {"file_count": 1, "download_count": 1, "total_bytes": 2516582, "context_tokens": 18400},
            "can_approve": True, "can_deny": True,
        }
        self.approval_status = 200
        self.decisions = []
        self.hold_retry_run = False
        self.metadata_reads = []

    def recovery(self, run_id):
        recovery = super().recovery(run_id)
        # The server's projection: an action step that stopped for Microsoft 365 changed nothing.
        recovery["requires_confirmation"] = False
        return recovery

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        body = request.post_data_json if request.post_data else None
        if path == f"/api/m365/approvals/{APPROVAL_ID}" and request.method == "GET":
            self.requests.append({"path": path, "method": "GET", "body": None})
            if self.approval_status != 200:
                route.fulfill(status=self.approval_status, json={"error": "not_found"})
                return
            route.fulfill(json={"approval": copy.deepcopy(self.approval), "csrf_token": CSRF_TOKEN})
            return
        if path == f"/api/m365/approvals/{APPROVAL_ID}/decision" and request.method == "POST":
            self.requests.append({"path": path, "method": "POST", "body": body})
            self.decisions.append({"body": body, "csrf": request.headers.get("x-m365-csrf-token")})
            self.approval.update(
                status="denied" if body.get("choice") == "fast" else "approved",
                analysis_choice=body.get("choice"), can_approve=False, can_deny=False,
            )
            route.fulfill(json={"approval": copy.deepcopy(self.approval), "csrf_token": CSRF_TOKEN})
            return
        if path.startswith("/api/message/") and path.endswith("/metadata"):
            self.requests.append({"path": path, "method": request.method, "body": None})
            self.metadata_reads.append(path)
            route.fulfill(json={})
            return
        if path.endswith("/retry") and request.method == "POST":
            self.requests.append({"path": path, "method": "POST", "body": body})
            # No external-effect consent is sent, or needed, for a Microsoft 365 stop.
            assert body["confirm_external_effects"] is False, body
            run_id = path.split("/")[-2]
            child_plan = copy.deepcopy(self.records[run_id]["plan"])
            child_plan.update(
                run_id="retry-attempt", plan_id="retry-plan", status="awaiting_approval",
                edit_version="retry-plan-version",
            )
            child_plan["approval"] = {"mode": "manual", "timeout_seconds": 0, "state": "pending"}
            child = self.add_record(child_plan, 2, run_id)
            self.records[run_id].update(latest_attempt_run_id=child["run_id"])
            self.records[run_id]["recovery"].update(eligible=False, current_run_id=child["run_id"])
            route.fulfill(json={"run": child})
            return
        if (path == RUN and self.hold_retry_run and body
                and self.records.get(body.get("run_id"), {}).get("retry_of_run_id")):
            self.requests.append({"path": path, "method": "POST", "body": body})
            run_id = body["run_id"]
            self.records[run_id].update(status="running", started_at="2026-09-08T12:00:30Z")

            def finish_later():
                event = self.finish(run_id, "completed")
                steps = [{"type": "orchestration_step", **step} for step in self.steps[run_id]]
                self.stream(route, steps + [event])

            self.waiting.append(finish_later)
            return
        super().handle(route)


class HeldRetryApi(InlineApprovalApi):
    """A failed agent step: its retry needs confirmation, and its run streams only when released."""

    def __init__(self, assets):
        super().__init__(assets)
        self.failure = {"code": "step_timeout", "message": recovery_tests.FAILURE}
        self.hold_retry_run = True

    def recovery(self, run_id):
        return recovery_tests.RecoveryApi.recovery(self, run_id)

    def handle(self, route):
        path = urlsplit(route.request.url).path
        if path.endswith("/retry"):
            recovery_tests.RecoveryApi.handle(self, route)
            return
        super().handle(route)


def _ui(editor_browser, editor_assets, api_class):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = api_class(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    return context, page, api


@pytest.fixture
def inline_ui(editor_browser, editor_assets):
    context, page, api = _ui(editor_browser, editor_assets, InlineApprovalApi)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


@pytest.fixture
def held_ui(editor_browser, editor_assets):
    context, page, api = _ui(editor_browser, editor_assets, HeldRetryApi)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def failed_message(api):
    return f'[id="message-assistant-{api.plan["run_id"]}"]'


def start_stopped_plan(page, api):
    recovery_tests.mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    card = page.get_by_test_id("v2-m365-inline-approval")
    expect(card).to_be_visible()
    return card


def test_extended_analysis_stop_is_decided_inline_and_continues_without_a_dialog(inline_ui):
    page, api = inline_ui
    card = start_stopped_plan(page, api)
    expect(card.get_by_text("SharePoint needs your OK to read more", exact=True)).to_be_visible()
    expect(card).to_contain_text("Ask the selected agent")
    expect(card).to_contain_text("about 18,400 tokens of file content, 1 file, 2.4 MB")
    expect(card.get_by_role("link", name="Settings")).to_have_attribute(
        "href", "/settings?tab=preferences&section=m365-sharing",
    )
    # The card owns the next step: no separate retry button competes with it.
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)

    card.get_by_role("button", name="Allow this time").click()

    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    assert api.decisions == [{"body": {"choice": "request"}, "csrf": CSRF_TOKEN}]
    assert len(api.calls("/retry")) == 1
    assert [entry["body"]["run_id"] for entry in api.calls("/run")] == [api.plan["run_id"], "retry-attempt"]
    expect(page.get_by_role("dialog")).to_have_count(0)
    # The retry's answer replaces the stopped attempt, without an attempt notice.
    expect(page.locator(failed_message(api))).to_have_count(0)
    expect(page.get_by_text(APPROVAL_MESSAGE, exact=True)).to_have_count(0)
    expect(page.get_by_text("Saved execution attempt", exact=False)).to_have_count(0)
    expect(page.get_by_role("button", name="View previous attempt")).to_have_count(0)


@pytest.mark.parametrize(("label", "choice"), [
    ("Always allow for SharePoint", "always"),
    ("Quick read only", "fast"),
])
def test_each_inline_choice_is_saved_before_the_plan_continues(inline_ui, label, choice):
    page, api = inline_ui
    card = start_stopped_plan(page, api)
    card.get_by_role("button", name=label).click()
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    assert api.decisions == [{"body": {"choice": choice}, "csrf": CSRF_TOKEN}]
    decision_index = next(i for i, entry in enumerate(api.requests) if entry["path"].endswith("/decision"))
    retry_index = next(i for i, entry in enumerate(api.requests) if entry["path"].endswith("/retry"))
    assert decision_index < retry_index, "The plan must continue only after the choice is saved."


def test_an_approval_decided_in_approvals_offers_continue(inline_ui):
    page, api = inline_ui
    api.approval.update(status="approved", analysis_choice="always", can_approve=False, can_deny=False)
    card = start_stopped_plan(page, api)
    expect(card.get_by_text("Deeper reads are always allowed for SharePoint.", exact=True)).to_be_visible()
    expect(card.get_by_role("button", name="Allow this time")).to_have_count(0)
    card.get_by_role("button", name="Continue").click()
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    assert not api.decisions
    assert len(api.calls("/retry")) == 1


def test_an_approval_that_cannot_be_opened_falls_back_to_approvals(inline_ui):
    page, api = inline_ui
    api.approval_status = 404
    recovery_tests.mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    section = page.get_by_label("Microsoft 365 approval").first
    expect(section.get_by_role("link", name="Review the Microsoft 365 approval")).to_have_attribute(
        "href", "/approvals/m365",
    )
    section.get_by_role("button", name="Retry from failed step").click()
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    assert not api.decisions


def test_retried_answer_keeps_its_attempts_in_message_details(inline_ui):
    page, api = inline_ui
    card = start_stopped_plan(page, api)
    card.get_by_role("button", name="Allow this time").click()
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()

    answer = page.locator('[id="message-assistant-retry-attempt"]')
    answer.get_by_role("button", name="Message details").click()
    expect(page.get_by_text("This answer came from retrying a plan that stopped earlier.", exact=False)).to_be_visible()
    page.get_by_role("button", name="Review saved attempt").click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    expect(drawer.get_by_text("Reused saved result", exact=True).first).to_be_visible()
    # Only the retried answer's details were read (StrictMode mounts can read them twice).
    assert set(api.metadata_reads) == {"/api/message/assistant-retry-attempt/metadata"}


def test_confirmed_retry_closes_its_dialog_while_the_retry_runs(held_ui):
    page, api = held_ui
    recovery_tests.start_failure(page, api)
    page.get_by_role("button", name="Retry from failed step").click()
    dialog = page.get_by_role("dialog", name="Retry this failed step?")
    expect(dialog).to_be_visible()
    with page.expect_request(f"**{RUN}"):
        dialog.get_by_role("button", name="Confirm retry").click()
    # Admitted: the confirmation is gone although the retry's run is still streaming.
    expect(dialog).to_have_count(0)
    assert api.waiting, "The retry's run should still be in progress."
    expect(page.get_by_text("A newer attempt of this plan exists.", exact=True)).to_be_visible()

    api.release()
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    expect(page.locator(failed_message(api))).to_have_count(0)
    expect(page.get_by_text("Saved execution attempt", exact=False)).to_have_count(0)
    assert len(api.calls("/retry")) == 1
