# test_v2_review_center_ai_assist.py
"""
Browser coverage for AI assist in the V2 admin Review center.
Version: 0.261.299
Implemented in: 0.261.299

Serve the real built SPA through Playwright request interception with a closed API boundary.
Check that the AI suggestions queue lists what each suggestion would change and why, flags stale
and locked rows, lets the reviewer edit a warning before approving it, leaves suspensions and
blocks out of "Approve all" and out of "select all", says how many users an approval warns and how
many requests it creates before it runs, never asks again for a suspension the violation already
records, shows in full and marks the text each record's user will read, applies each suggestion
through the bulk save with its suggestion id and the version and fingerprint it read, dismisses by
suggestion id alone, and reports a refused record on its own row in the reviewer's terms; that
Triage with AI sends the checked records ten at a time with each user's records together, sends
again the records the server didn't reach, and reports every record's outcome with a link to the
queue; that the editors save with the version and fingerprint they read; that the
editors' Ask AI panel fills the unsaved draft, marks what it changed, undoes it, and saves a
stored triage suggestion through that suggestion; that the Feedback dashboard's themes open the
filtered list; and that nothing about AI assist shows while it is turned off. Unexpected requests
fail.
"""

import copy
import hashlib
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options  # noqa: E402,F401
from v2_notification_stubs import is_notification_count, notification_count_payload  # noqa: E402


pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = REPO_ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC_ROOT / "v2" / "index.html"
ORIGIN = "http://simplechat.test"
DATES = [f"2026-10-{day:02d}" for day in range(2, 9)]
SUGGESTION_IDS = {name: name[0] * 32 for name in ("a", "b", "c", "d", "e", "f")}


def _suggestion(letter, payload, status="pending", rationale="It fits the record.", confidence="high"):
    return {
        "id": letter * 32, "status": status, "created_at": "2026-10-07T12:00:00Z", "created_by": {"name": "Rita Reviewer"},
        "model": "review-model", "payload": payload, "rationale": rationale, "confidence": confidence,
    }


WARN = {
    "status": "Resolved", "action": "WarnUser", "notes": "A hateful remark, first time.",
    "notification_title": "Safety warning", "notification_message": "Please keep messages respectful.", "archive": False,
}
SUSPEND = {
    "status": "Resolved", "action": "SuspendUser", "notes": "Repeated hateful content.", "notification_title": "Suspended",
    "notification_message": "Your access is suspended for 7 days.", "suspend_duration": "7d", "archive": False,
}
DISMISS = {"status": "Dismissed", "action": "None", "notes": "A false positive.", "archive": True}
FEEDBACK_SUGGESTION = {
    "acknowledged": True, "analysisNotes": "The answer missed the per diem rules.", "actionTaken": "",
    "responseToUser": "Thanks, we are checking the travel sources.", "theme": "retrieval", "archive": False,
}


def _violation(log_id, **fields):
    record = {
        "id": log_id, "user_id": "user-2", "user_display_name": "Sam Sender", "user_email": "sam@contoso.test",
        "message": f"Flagged message {log_id}", "status": "New", "action": "None", "notes": "",
        "created_at": "2026-10-07T09:00:00", "triggered_categories": [{"category": "Hate", "severity": 4}],
        "content_origin": "user", "isArchived": False, "action_request_status": None, "etag": f"etag-{log_id}",
        "fingerprint": hashlib.md5(f"fp-{log_id}".encode("utf-8")).hexdigest(), "ai_suggestion": None,
    }
    record.update(fields)
    return record


def _feedback(index, **fields):
    record = {
        "id": f"fb-{index}", "userId": "user-1", "userDisplayName": "Uma User", "userEmail": "uma@contoso.test",
        "prompt": f"Question number {index} about the travel policy", "aiResponse": f"Answer {index}.",
        "feedbackType": "Negative", "reason": "Not helpful", "timestamp": f"2026-10-0{1 + index % 7}T10:00:00",
        "isArchived": False, "adminReview": {"acknowledged": False}, "etag": f"etag-fb-{index}",
        "fingerprint": hashlib.md5(f"fp-fb-{index}".encode("utf-8")).hexdigest(), "ai_suggestion": None,
    }
    record.update(fields)
    return record


class ReviewAssistFixture:
    """The Review center with an in-memory feedback, safety and AI assist API."""

    def __init__(self, page: Page, *, assist_on=True):
        self.page = page
        self.features = {"enable_user_feedback": True, "enable_content_safety": True}
        if assist_on:
            self.features["enable_admin_review_ai_assistant"] = True
        self.safety = [
            _violation("log-1", ai_suggestion=_suggestion("a", WARN)),
            _violation("log-2", ai_suggestion=_suggestion("b", SUSPEND)),
            _violation("log-3", ai_suggestion=_suggestion("c", WARN, status="stale")),
            _violation("log-4", action="BlockUser", action_request_status="pending", action_request_id="approval-1",
                       ai_suggestion=_suggestion("d", DISMISS)),
            _violation("log-5", ai_suggestion=_suggestion("e", DISMISS)),
            _violation("log-6"),
        ]
        self.feedback = [_feedback(index) for index in range(1, 13)]
        self.feedback[0]["ai_suggestion"] = _suggestion("f", FEEDBACK_SUGGESTION)
        self.requests = []
        self.bulk_calls = []
        self.patches = []
        self.assist_calls = []
        self.fail_bulk = {}
        # Ids the assistant answers "deferred" the first time it is asked about them.
        self.defer_once = set()
        self.errors = []
        self.unexpected_requests = []
        self.preferences = {}
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self._route)

    def _bootstrap(self):
        return {
            "version": "0.261.299",
            "user": {"id": "admin-1", "display_name": "Ada Admin", "email": "ada@contoso.test", "is_admin": True,
                     "roles": ["User", "Admin"]},
            "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
            "features": self.features,
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {"custom_pages": {"enabled": False, "items": []}, "external_links": {"enabled": False, "items": []}},
            "workspace": {"sections": {}},
            "settings": {},
        }

    # -- Records --------------------------------------------------------------------------

    @staticmethod
    def _pending(record):
        return (record.get("ai_suggestion") or {}).get("status") in ("pending", "stale")

    def _page(self, items, query, key):
        page_number = int(query.get("page", ["1"])[0])
        size = int(query.get("page_size", ["20"])[0])
        chunk = items[(page_number - 1) * size:page_number * size]
        return {key: copy.deepcopy(chunk), "page": page_number, "page_size": size, "total_count": len(items)}

    def _apply(self, records, operation, section):
        record = next((item for item in records if item["id"] == operation["id"]), None)
        base = {"index": operation.get("index"), "id": operation["id"], "op": operation["op"]}
        if operation["id"] in self.fail_bulk:
            return {**base, "ok": False, "status": 409, **self.fail_bulk[operation["id"]]}
        if record is None:
            return {**base, "ok": False, "status": 404, "code": "not_found", "error": "Not found"}
        suggestion = record.get("ai_suggestion") or {}
        if operation["op"] == "dismiss_suggestion":
            record["ai_suggestion"] = {**suggestion, "status": "dismissed"}
            return {**base, "ok": True, "status": 200, "message": "AI suggestion dismissed."}
        if operation["op"] == "archive":
            record["isArchived"] = operation["archived"]
            return {**base, "ok": True, "status": 200}
        if operation.get("suggestion_id"):
            if suggestion.get("id") != operation["suggestion_id"] or suggestion.get("status") != "pending":
                return {**base, "ok": False, "status": 409, "code": "suggestion_not_pending", "error": "Already decided."}
            record["ai_suggestion"] = {**suggestion, "status": "applied"}
        changes = operation["changes"]
        if section == "safety":
            previous_action = record.get("action") or "None"
            record.update({key: changes[key] for key in ("status", "action", "notes") if key in changes})
            body = {"message": "Warning sent to the user.", "approval_required": False}
            if changes.get("action") in ("SuspendUser", "BlockUser"):
                if changes["action"] == previous_action and changes.get("reissue") is not True:
                    body = {"message": "Safety log updated. The suspension was already applied, so it was not requested again.",
                            "approval_required": False, "remediation_already_applied": True}
                else:
                    record["action_request_status"] = "pending"
                    body = {"message": "Safety log updated and remediation approval request created.", "approval_required": True}
        else:
            record["adminReview"].update({key: value for key, value in changes.items() if key not in ("etag", "notify_user")})
            body = {"success": True, "notified": False}
        return {**base, "ok": True, "status": 200, **body,
                "suggestion": {"id": operation.get("suggestion_id"), "status": "applied", "edited": False}}

    def _assist(self, section, body):
        self.assist_calls.append((section, body))
        records = self.safety if section == "safety" else self.feedback
        results = []
        for record_id in body["ids"]:
            record = next((item for item in records if item["id"] == record_id), None)
            if record is None:
                results.append({"id": record_id, "outcome": "not_found", "message": "This record no longer exists."})
                continue
            if record_id in self.defer_once:
                self.defer_once.discard(record_id)
                results.append({"id": record_id, "outcome": "deferred",
                                "message": "The assistant ran out of time before it reached this record, so it is sent again."})
                continue
            if record_id in ("fb-3",):
                results.append({"id": record_id, "outcome": "content_filtered",
                                "message": "The AI service's content filter declined this record, so no suggestion was made. Review it yourself."})
                continue
            payload = WARN if section == "safety" else FEEDBACK_SUGGESTION
            if body["mode"] == "analyze":
                suggestion = {"id": None, "status": "unsaved", "created_at": "2026-10-08T00:00:00Z", "created_by": None,
                              "model": "review-model", "payload": payload, "rationale": "Severity 4, first time.", "confidence": "medium"}
            else:
                suggestion = _suggestion("9", payload)
                suggestion["id"] = hashlib.md5(record_id.encode("utf-8")).hexdigest()
                record["ai_suggestion"] = suggestion
            results.append({"id": record_id, "outcome": "suggested", "suggestion": suggestion})
        return {"section": section, "mode": body["mode"], "results": results}

    # -- Routing --------------------------------------------------------------------------

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path, query, method = parsed.path, parse_qs(parsed.query), request.method
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
            return
        if not (path == "/v2" or path.startswith(("/v2/", "/static/"))):
            self.requests.append((method, path, parsed.query))
        if method == "GET" and (path == "/v2" or path.startswith("/v2/")):
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
        elif method == "GET" and path.startswith("/static/"):
            asset = (STATIC_ROOT / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC_ROOT.resolve()) and asset.is_file():
                route.fulfill(path=str(asset))
            else:
                self.unexpected_requests.append(path)
                route.fulfill(status=404, body="Fixture asset not found")
        elif method == "GET" and path == "/api/v2/bootstrap":
            route.fulfill(json=self._bootstrap())
        elif path == "/api/user/settings":
            if method == "GET":
                route.fulfill(json={"settings": self.preferences})
            else:
                self.preferences.update(request.post_data_json["settings"])
                route.fulfill(json={"message": "Saved."})
        elif is_notification_count(method, path):
            route.fulfill(json=notification_count_payload())
        elif method == "POST" and path in ("/api/admin/review/feedback/assist", "/api/admin/review/safety/assist"):
            section = "feedback" if "/feedback/" in path else "safety"
            route.fulfill(json=self._assist(section, request.post_data_json),
                          headers={"Cache-Control": "no-store, private"})
        elif method == "GET" and path == "/feedback/review/stats":
            route.fulfill(json={
                "total_count": 12, "window": {"days": 30, "start_date": "2026-09-09", "end_date": "2026-10-08"},
                "received_count": 12, "awaiting_review_count": 12, "negative_count_in_window": 12,
                "acknowledged_count_in_window": 0, "acknowledgement_rate": 0, "archived_count": 0,
                "daily_by_rating": {"dates": DATES, "series": [{"key": "Negative", "counts": [2, 2, 2, 2, 2, 2, 0]}]},
                "theme_mix": [{"theme": "retrieval", "count": 3}, {"theme": "tone", "count": 1}],
                "unthemed_count_in_window": 8, "oldest_awaiting": [],
            })
        elif method == "GET" and path == "/api/safety/logs/stats":
            route.fulfill(json={
                "total_count": 6, "window": {"days": 30, "start_date": "2026-09-09", "end_date": "2026-10-08"},
                "received_count": 6, "open_count": 6, "pending_remediation_count": 1, "restricted_user_count": 0,
                "warnings_sent_count": 0, "warnings_acknowledged_count": 0, "warnings_pending_count": 0,
                "unchecked_chat_count": 0,
                "daily_by_category": {"dates": DATES, "series": [{"key": "Hate", "counts": [0, 0, 0, 0, 0, 6, 0]}]},
                "severity_mix": [{"severity": 4, "count": 6}], "action_mix": [{"action": "None", "count": 6}],
                "repeat_users": [],
            })
        elif method == "GET" and path == "/feedback/review":
            items = [item for item in self.feedback if not item["isArchived"] or query.get("archive") == ["all"]]
            if query.get("ai") == ["pending"]:
                items = [item for item in items if self._pending(item)]
            if query.get("theme"):
                items = [item for item in items if item["adminReview"].get("theme") == query["theme"][0]]
            route.fulfill(json=self._page(items, query, "feedback"))
        elif method == "POST" and path in ("/feedback/review/bulk", "/api/safety/logs/bulk"):
            section = "feedback" if path.startswith("/feedback") else "safety"
            operations = request.post_data_json["operations"]
            self.bulk_calls.append((section, operations))
            records = self.feedback if section == "feedback" else self.safety
            results = [self._apply(records, {**operation, "index": index}, section) for index, operation in enumerate(operations)]
            succeeded = sum(1 for result in results if result["ok"])
            route.fulfill(json={"results": results, "succeeded": succeeded, "failed": len(results) - succeeded})
        elif path.startswith("/feedback/review/"):
            record = next((item for item in self.feedback if item["id"] == path.rsplit("/", 1)[-1]), None)
            if record is None:
                route.fulfill(status=404, json={"error": "Feedback not found"})
            elif method == "GET":
                route.fulfill(json=copy.deepcopy(record))
            elif method == "PATCH":
                self.patches.append(("feedback", record["id"], request.post_data_json))
                route.fulfill(json={"success": True, "notified": False})
            else:
                self.unexpected_requests.append(f"{method} {path}")
                route.fulfill(status=404, json={"error": "Unexpected fixture request."})
        elif method == "GET" and path == "/api/safety/logs":
            items = [item for item in self.safety if not item["isArchived"] or query.get("archive") == ["all"]]
            if query.get("ai") == ["pending"]:
                items = [item for item in items if self._pending(item)]
            route.fulfill(json=self._page(items, query, "logs"))
        elif path.startswith("/api/safety/logs/") and path.count("/") == 4:
            record = next((item for item in self.safety if item["id"] == path.rsplit("/", 1)[-1]), None)
            if record is None:
                route.fulfill(status=404, json={"error": "Safety violation not found"})
            elif method == "GET":
                route.fulfill(json={**copy.deepcopy(record), "user_access": {"restricted": False}, "user_violation_count": 1})
            elif method == "PATCH":
                self.patches.append(("safety", record["id"], request.post_data_json))
                route.fulfill(json={"message": "Warning sent to the user.", "approval_required": False})
            else:
                self.unexpected_requests.append(f"{method} {path}")
                route.fulfill(status=404, json={"error": "Unexpected fixture request."})
        else:
            self.unexpected_requests.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, path, *, width=1440, height=900):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.preferences = {"darkModeEnabled": False, "v2RailCollapsed": width < 1024}
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}{path}", wait_until="networkidle")

    def requested(self, prefix):
        return [entry for entry in self.requests if entry[1].startswith(prefix)]

    def assert_clean(self):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors


@pytest.fixture
def assist_ui(page):
    fixture = ReviewAssistFixture(page)
    yield fixture
    fixture.assert_clean()


def test_the_queue_flags_rows_and_approves_with_counted_confirmation(assist_ui):
    assist_ui.open("/v2/admin/review/safety/suggestions")
    page = assist_ui.page
    expect(page.get_by_test_id("v2-review-rail-safety-suggestions")).to_be_visible()
    queue = page.get_by_test_id("v2-safety-suggestions")
    expect(queue).to_be_visible()
    for record_id in ("log-1", "log-2", "log-3", "log-4", "log-5"):
        expect(page.get_by_test_id(f"v2-safety-suggestion-{record_id}")).to_be_visible()
    expect(page.get_by_test_id("v2-safety-suggestion-log-6")).to_have_count(0)
    expect(page.get_by_test_id("v2-safety-suggestion-log-1-summary")).to_contain_text(
        "Status New → Resolved · Warn user · Notes: A hateful remark, first time.",
    )
    expect(page.get_by_test_id("v2-safety-suggestion-log-1")).to_contain_text("Why the AI suggests this: It fits the record.")
    expect(page.get_by_test_id("v2-safety-suggestion-log-2")).to_contain_text("Needs a second reviewer")
    expect(page.get_by_test_id("v2-safety-suggestion-log-2-summary")).to_contain_text("Suspend user for 7 days")
    expect(page.get_by_test_id("v2-safety-suggestion-log-3")).to_contain_text("Out of date")
    expect(page.get_by_test_id("v2-safety-suggestion-log-3-approve")).to_be_disabled()
    expect(page.get_by_test_id("v2-safety-suggestion-log-4")).to_contain_text("Held by a request")
    expect(page.get_by_test_id("v2-safety-suggestion-log-4-approve")).to_be_disabled()

    # Selecting the page never ticks a suspension or block.
    page.get_by_test_id("v2-safety-suggestions-select-page").check()
    expect(page.get_by_test_id("v2-safety-suggestion-log-1-check")).to_be_checked()
    expect(page.get_by_test_id("v2-safety-suggestion-log-2-check")).not_to_be_checked()
    page.get_by_test_id("v2-safety-suggestions-select-page").uncheck()

    # Edit the warning, then Approve all ready: the suspension is left out, and the count is said first.
    page.get_by_test_id("v2-safety-suggestion-log-1-message").fill("Edited: please keep messages respectful.")
    expect(page.get_by_test_id("v2-safety-suggestions-approve-all")).to_have_text("Approve all ready (2)")
    page.get_by_test_id("v2-safety-suggestions-approve-all").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Apply 2 suggestions?")
    expect(dialog).to_contain_text("1 user is sent a warning straight away.")
    expect(dialog).to_contain_text("1 violation will be archived.")
    dialog.get_by_role("button", name="Apply 2 suggestions").click()
    expect(page.get_by_test_id("v2-safety-suggestions-bulk-report")).to_contain_text("Applied 2 suggestions. 1 warning was sent.")
    section, operations = assist_ui.bulk_calls[0]
    assert section == "safety" and [operation["id"] for operation in operations] == ["log-1", "log-5"], operations
    warn = operations[0]
    assert warn["op"] == "update" and warn["suggestion_id"] == "a" * 32 and warn["etag"] == "etag-log-1", warn
    assert warn["changes"]["notification_message"] == "Edited: please keep messages respectful.", warn
    assert warn["changes"]["fingerprint"] == assist_ui.safety[0]["fingerprint"], warn
    assert assist_ui.bulk_calls[1] == ("safety", [{"id": "log-5", "op": "archive", "archived": True}]), assist_ui.bulk_calls
    expect(page.get_by_test_id("v2-safety-suggestion-log-1")).to_have_count(0)

    # The suspension is approved with its own tick, and still waits for a second reviewer.
    page.get_by_test_id("v2-safety-suggestion-log-2-approve").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("1 suspension or block is requested; each applies only after another eligible reviewer approves it.")
    dialog.get_by_role("button", name="Apply 1 suggestion").click()
    expect(page.get_by_test_id("v2-safety-suggestions-bulk-report")).to_contain_text("1 suspension or block request waits for another reviewer.")
    _section, operations = assist_ui.bulk_calls[-1]
    assert operations[0]["id"] == "log-2" and operations[0]["changes"]["action"] == "SuspendUser", operations
    assert operations[0]["changes"]["datetime_to_allow"], operations

    # A stale suggestion is dismissed; a record that changed underneath is reported on its row.
    assist_ui.fail_bulk = {"log-3": {"code": "record_changed", "error": "This violation changed after you opened it."}}
    page.get_by_test_id("v2-safety-suggestion-log-3-dismiss").click()
    expect(page.get_by_test_id("v2-safety-suggestion-log-3-result")).to_contain_text(
        "The record changed since this suggestion was shown, so nothing was saved.",
    )
    expect(page.get_by_test_id("v2-safety-suggestions-bulk-report")).to_contain_text("triage the record again")
    # A dismissal names only the suggestion: a stale one may always be dismissed.
    assert assist_ui.bulk_calls[-1][1] == [
        {"id": "log-3", "op": "dismiss_suggestion", "suggestion_id": "c" * 32},
    ], assist_ui.bulk_calls[-1]


def test_a_suspension_already_on_its_violation_is_not_requested_again(assist_ui):
    assist_ui.safety.append(_violation(
        "log-7", status="Resolved", action="SuspendUser", action_request_status="executed",
        ai_suggestion=_suggestion("7", SUSPEND),
    ))
    assist_ui.open("/v2/admin/review/safety/suggestions")
    page = assist_ui.page
    row = page.get_by_test_id("v2-safety-suggestion-log-7")
    expect(row).to_contain_text("Already on this violation")
    expect(row).not_to_contain_text("Needs a second reviewer")
    expect(page.get_by_test_id("v2-safety-suggestion-log-7-repeat")).to_contain_text(
        "This suspension was approved and applied. Approving updates the review only and requests nothing new.",
    )
    # Approve all and select-all still leave it out; only its own tick approves it.
    expect(page.get_by_test_id("v2-safety-suggestions-approve-all")).to_have_text("Approve all ready (2)")
    page.get_by_test_id("v2-safety-suggestions-select-page").check()
    expect(page.get_by_test_id("v2-safety-suggestion-log-7-check")).not_to_be_checked()
    page.get_by_test_id("v2-safety-suggestions-select-page").uncheck()

    page.get_by_test_id("v2-safety-suggestion-log-7-approve").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("1 suspension or block is already on its violation, so nothing new is requested for it.")
    expect(dialog).not_to_contain_text("each applies only after another eligible reviewer approves it")
    dialog.get_by_role("button", name="Apply 1 suggestion").click()
    expect(page.get_by_test_id("v2-safety-suggestions-bulk-report")).to_contain_text(
        "1 suspension or block already on its violation was not requested again.",
    )
    _section, operations = assist_ui.bulk_calls[-1]
    assert operations[0]["id"] == "log-7" and operations[0]["suggestion_id"] == "7" * 32, operations
    assert "reissue" not in operations[0]["changes"], "the queue asked for the suspension again"


def test_the_queue_reads_well_on_a_phone(assist_ui):
    assist_ui.open("/v2/admin/review/safety/suggestions", width=390, height=844)
    page = assist_ui.page
    row = page.get_by_test_id("v2-safety-suggestion-log-1")
    expect(row).to_be_visible()
    approve = page.get_by_test_id("v2-safety-suggestion-log-1-approve")
    approve.scroll_into_view_if_needed()
    expect(approve).to_be_visible()
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, f"the queue scrolls sideways at {width}px"


def test_triage_sends_ten_at_a_time_and_reports_each_record(assist_ui):
    assist_ui.open("/v2/admin/review/feedback/queue")
    page = assist_ui.page
    expect(page.get_by_test_id("v2-feedback-row-fb-1")).to_contain_text("AI suggestion")
    page.get_by_test_id("v2-feedback-select-page").check()
    triage = page.get_by_test_id("v2-feedback-bulk-triage")
    expect(triage).to_have_text("Triage with AI (12)")
    triage.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Nothing about the reviews changes now, and no one is notified.")
    dialog.get_by_role("button", name="Triage 12 feedback records").click()
    report = page.get_by_test_id("v2-feedback-bulk-report")
    expect(report).to_contain_text("AI suggested reviews for 11 of 12 feedback records.")
    expect(report).to_contain_text("content filter declined this record")
    assert [len(body["ids"]) for _section, body in assist_ui.assist_calls] == [10, 2], assist_ui.assist_calls
    assert all(body["mode"] == "triage" and set(body) == {"mode", "ids"} for _section, body in assist_ui.assist_calls)
    # Only the record without a suggestion stays checked, ready to try again or review by hand.
    expect(page.get_by_test_id("v2-feedback-check-fb-3")).to_be_checked()
    expect(page.get_by_test_id("v2-feedback-check-fb-2")).not_to_be_checked()
    page.get_by_test_id("v2-feedback-bulk-report-link").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/suggestions")
    expect(page.get_by_test_id("v2-feedback-suggestion-fb-2")).to_be_visible()


def test_ask_ai_fills_the_draft_marks_it_and_undoes_it(assist_ui):
    assist_ui.open("/v2/admin/review/safety/violations/log-6")
    page = assist_ui.page
    page.get_by_test_id("v2-review-ask-ai-toggle").click()
    panel = page.get_by_test_id("v2-review-ask-ai")
    expect(panel).to_contain_text("AI suggestions are a starting point, and can be wrong.")
    panel.get_by_test_id("v2-review-ask-ai-analyze").click()
    card = page.get_by_test_id("v2-review-ask-ai-suggestion")
    expect(card).to_contain_text("Medium confidence")
    expect(card).to_contain_text("Why: Severity 4, first time.")
    assert assist_ui.assist_calls == [("safety", {"mode": "analyze", "ids": ["log-6"]})], assist_ui.assist_calls

    page.get_by_test_id("v2-review-ask-ai-suggestion-apply").click()
    expect(page.get_by_test_id("v2-review-ask-ai-applied")).to_contain_text("Applied to your draft: Status, Action, Notes, Notification.")
    status = page.get_by_test_id("v2-safety-editor-status")
    expect(status).to_have_value("Resolved")
    assert "ring-change-ai" in (status.get_attribute("class") or ""), "the changed field is not marked"
    expect(page.get_by_test_id("v2-safety-editor-action")).to_have_value("WarnUser")
    expect(page.get_by_test_id("v2-safety-editor-message")).to_have_value("Please keep messages respectful.")

    # A field the reviewer changes afterwards is kept by Undo.
    page.get_by_test_id("v2-safety-editor-notes").fill("My own notes.")
    page.get_by_test_id("v2-review-ask-ai-undo").click()
    expect(page.get_by_test_id("v2-review-ask-ai-undone")).to_contain_text("Kept because you changed it since: Notes.")
    expect(status).to_have_value("New")
    expect(page.get_by_test_id("v2-safety-editor-action")).to_have_value("None")
    expect(page.get_by_test_id("v2-safety-editor-notes")).to_have_value("My own notes.")
    assert not assist_ui.patches and not assist_ui.bulk_calls, "Ask AI saved something"


def test_a_stored_triage_suggestion_saves_through_the_suggestion(assist_ui):
    assist_ui.open("/v2/admin/review/feedback/queue/fb-1")
    page = assist_ui.page
    page.get_by_test_id("v2-review-ask-ai-toggle").click()
    saved = page.get_by_test_id("v2-review-ask-ai-saved")
    expect(saved).to_contain_text("Suggestion from AI triage")
    expect(saved).to_contain_text("Theme: Not classified → Retrieval")
    page.get_by_test_id("v2-review-ask-ai-saved-apply").click()
    expect(page.get_by_test_id("v2-feedback-editor-theme")).to_have_value("retrieval")
    expect(page.get_by_test_id("v2-feedback-editor-analysis")).to_have_value("The answer missed the per diem rules.")
    page.get_by_role("button", name="Save review").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue?selected=fb-1")
    expect(page.get_by_test_id("v2-feedback-saved")).to_contain_text("The AI suggestion was marked as applied.")
    assert not assist_ui.patches, assist_ui.patches
    section, operations = assist_ui.bulk_calls[0]
    assert section == "feedback" and operations[0]["suggestion_id"] == "f" * 32, operations
    assert operations[0]["etag"] == "etag-fb-1" and operations[0]["changes"]["theme"] == "retrieval", operations
    assert operations[0]["changes"]["fingerprint"] == assist_ui.feedback[0]["fingerprint"], operations


def test_an_editor_save_names_the_version_and_fingerprint_it_read(assist_ui):
    assist_ui.open("/v2/admin/review/safety/violations/log-6")
    page = assist_ui.page
    page.get_by_test_id("v2-safety-editor-notes").fill("Reviewed by hand.")
    page.get_by_role("button", name="Save review").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/safety/violations?selected=log-6")
    [(section, record_id, body)] = assist_ui.patches
    assert (section, record_id) == ("safety", "log-6"), assist_ui.patches
    # An AI suggestion stored on the violation meanwhile changes its version but not this
    # fingerprint, so the server can still take the save.
    assert body["etag"] == "etag-log-6" and body["fingerprint"] == assist_ui.safety[5]["fingerprint"], body
    assert body["notes"] == "Reviewed by hand.", body


def test_the_queue_shows_what_the_user_will_read_in_full(assist_ui):
    long_notes = "The answer cited an outdated policy page. " * 6
    long_response = "Thanks for telling us. We are updating the travel policy sources so answers cite the current rules."
    assist_ui.feedback[0]["ai_suggestion"] = _suggestion("f", {
        **FEEDBACK_SUGGESTION, "analysisNotes": long_notes.strip(), "responseToUser": long_response,
    })
    assist_ui.feedback[0]["adminReview"] = {"acknowledged": False, "actionTaken": "Checked the index."}
    assist_ui.open("/v2/admin/review/feedback/suggestions")
    page = assist_ui.page
    visible = page.get_by_test_id("v2-feedback-suggestion-fb-1-visible")
    expect(visible).to_contain_text("Visible to the user")
    expect(page.get_by_test_id("v2-feedback-suggestion-fb-1-visible-analysisNotes")).to_have_text(long_notes.strip())
    expect(page.get_by_test_id("v2-feedback-suggestion-fb-1-visible-responseToUser")).to_have_text(long_response)
    expect(page.get_by_test_id("v2-feedback-suggestion-fb-1-visible-actionTaken")).to_have_text("Cleared")

    page.get_by_test_id("v2-feedback-suggestions-approve-all").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text('1 review saves text its user can read; check it under "Visible to the user".')
    dialog.get_by_role("button", name="Apply 1 suggestion").click()
    expect(page.get_by_test_id("v2-feedback-suggestions-bulk-report")).to_contain_text("Applied 1 suggestion.")
    _section, operations = assist_ui.bulk_calls[0]
    assert operations[0]["changes"]["analysisNotes"] == long_notes.strip(), operations

    # A violation's notes and its warning are marked the same way.
    assist_ui.open("/v2/admin/review/safety/suggestions")
    expect(page.get_by_test_id("v2-safety-suggestion-log-1-visible-notes")).to_have_text("A hateful remark, first time.")
    expect(page.get_by_test_id("v2-safety-suggestion-log-1")).to_contain_text(
        "Visible to the user: the warning they receive when you approve",
    )


def test_triage_keeps_each_users_records_together_and_resends_deferred_ones(assist_ui):
    for index, record in enumerate(assist_ui.feedback, start=1):
        record["userId"] = f"user-{(index - 1) % 3 + 1}"
    assist_ui.defer_once = {"fb-11"}
    assist_ui.open("/v2/admin/review/feedback/queue")
    page = assist_ui.page
    page.get_by_test_id("v2-feedback-select-page").check()
    page.get_by_test_id("v2-feedback-bulk-triage").click()
    page.get_by_role("dialog").get_by_role("button", name="Triage 12 feedback records").click()
    report = page.get_by_test_id("v2-feedback-bulk-report")
    expect(report).to_contain_text("AI suggested reviews for 11 of 12 feedback records.")
    calls = [body["ids"] for _section, body in assist_ui.assist_calls]
    assert calls == [
        ["fb-1", "fb-4", "fb-7", "fb-10", "fb-2", "fb-5", "fb-8", "fb-11"],
        ["fb-11"],
        ["fb-3", "fb-6", "fb-9", "fb-12"],
    ], calls
    # Only the record the content filter declined stays checked.
    expect(page.get_by_test_id("v2-feedback-check-fb-3")).to_be_checked()
    expect(page.get_by_test_id("v2-feedback-check-fb-11")).not_to_be_checked()


def test_the_feedback_dashboard_themes_open_the_filtered_list(assist_ui):
    assist_ui.open("/v2/admin/review/feedback")
    page = assist_ui.page
    themes = page.get_by_test_id("v2-feedback-dashboard-themes")
    expect(themes).to_contain_text("Retrieval")
    expect(page.get_by_test_id("v2-feedback-dashboard-unthemed")).to_contain_text("8 not classified yet.")
    themes.get_by_role("link", name="Retrieval").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue?archive=all&days=30&theme=retrieval")
    expect(page.get_by_test_id("v2-feedback-filter-theme")).to_have_value("retrieval")


def test_nothing_about_ai_assist_shows_while_it_is_off(page):
    fixture = ReviewAssistFixture(page, assist_on=False)
    fixture.open("/v2/admin/review/feedback/queue")
    expect(page.get_by_test_id("v2-feedback-row-fb-2")).to_be_visible()
    expect(page.get_by_test_id("v2-feedback-row-fb-1")).not_to_contain_text("AI suggestion")
    expect(page.get_by_test_id("v2-review-rail-feedback-suggestions")).to_have_count(0)
    page.get_by_test_id("v2-feedback-check-fb-2").click()
    expect(page.get_by_test_id("v2-feedback-bulk-bar")).to_be_visible()
    expect(page.get_by_test_id("v2-feedback-bulk-triage")).to_have_count(0)
    page.goto(f"{ORIGIN}/v2/admin/review/feedback/queue/fb-2", wait_until="networkidle")
    expect(page.get_by_test_id("v2-feedback-editor")).to_be_visible()
    expect(page.get_by_test_id("v2-review-ask-ai-toggle")).to_have_count(0)
    page.goto(f"{ORIGIN}/v2/admin/review/safety/suggestions", wait_until="networkidle")
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/safety")
    assert not fixture.assist_calls
    fixture.assert_clean()
