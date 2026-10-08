# test_v2_review_center.py
"""
Browser coverage for the V2 admin Review center.
Version: 0.261.298
Implemented in: 0.261.298

Serve the real built SPA through Playwright request interception with a closed API
boundary. Check that each role sees only the Review center sections it may open, with a
clear not-available state otherwise and the old addresses redirecting; that a dashboard
figure opens the workbench filtered as it says; that the workbench checks rows with click
and Shift+click, offers every matching record, and reports a bulk action on each record;
that a record's editor asks before discarding unsaved changes, returns to the same list
after a save, and offers a reload when the record changed underneath it; that the
violation editor prefills its notification and suspension length; and that unchecked chat
content is rechecked one message after another. Unexpected requests fail.
"""

import copy
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


def _feedback(index, **fields):
    record = {
        "id": f"fb-{index}",
        "userId": "user-1",
        "userDisplayName": "Uma User",
        "userEmail": "uma@contoso.test",
        "prompt": f"Question number {index} about the quarterly report",
        "aiResponse": f"Answer {index}.",
        "feedbackType": "Negative" if index % 2 else "Positive",
        "reason": "Not helpful",
        "timestamp": f"2026-10-0{1 + index % 7}T10:00:00",
        "isArchived": False,
        "adminReview": {"acknowledged": False},
        "etag": "v1",
    }
    record.update(fields)
    return record


def _violation(log_id, **fields):
    record = {
        "id": log_id,
        "user_id": "user-2",
        "user_display_name": "Sam Sender",
        "user_email": "sam@contoso.test",
        "message": f"Flagged message {log_id}",
        "status": "New",
        "action": "None",
        "created_at": "2026-10-07T09:00:00",
        "triggered_categories": [{"category": "Hate", "severity": 4}],
        "content_origin": "user",
        "isArchived": False,
        "action_request_status": None,
        "etag": "s1",
    }
    record.update(fields)
    return record


class ReviewCenterFixture:
    """The Review center with an in-memory feedback, safety and chat-check API."""

    def __init__(self, page: Page, *, roles=("User", "Admin"), features=None, settings=None):
        self.page = page
        self.roles = list(roles)
        self.features = features if features is not None else {"enable_user_feedback": True, "enable_content_safety": True}
        self.settings = settings or {}
        self.feedback = [_feedback(index) for index in range(1, 13)]
        self.safety = [
            _violation("log-1"),
            _violation("log-2", status="In-Review", action="WarnUser", action_request_status="executed",
                       warning_acknowledgment_status="pending"),
            _violation("log-3", status="Resolved"),
        ]
        self.unchecked = [
            {"source": "chat", "conversation_id": "conv-1", "message_id": "msg-1", "etag": "e1",
             "check": {"checkpoint": "chat_output", "attempted_at": "2026-10-07T08:00:00",
                       "scanners": [{"scanner": "content_safety", "complete": False, "error_code": "timeout"}]}},
            {"source": "chat", "conversation_id": "conv-2", "message_id": "msg-2", "etag": "e2",
             "check": {"checkpoint": "chat_input", "attempted_at": "2026-10-07T08:05:00",
                       "scanners": [{"scanner": "content_screening", "complete": False}]}},
        ]
        self.requests = []
        self.bulk_calls = []
        self.patches = []
        self.rechecks = []
        self.fail_bulk_ids = set()
        self.errors = []
        self.unexpected_requests = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self._route)

    def _bootstrap(self):
        return {
            "version": "0.261.298",
            "user": {
                "id": "admin-1",
                "display_name": "Ada Admin",
                "email": "ada@contoso.test",
                "is_admin": "Admin" in self.roles,
                "roles": self.roles,
            },
            "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
            "features": self.features,
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {
                "custom_pages": {"enabled": False, "items": []},
                "external_links": {"enabled": False, "items": []},
            },
            "workspace": {"sections": {}},
            "settings": self.settings,
        }

    # -- Feedback ---------------------------------------------------------------------------

    def _feedback_matches(self, record, query):
        ack = query.get("ack", [""])[0]
        archive = query.get("archive", ["active"])[0]
        rating = query.get("type", [""])[0]
        search = query.get("search", [""])[0].lower()
        acknowledged = bool(record["adminReview"].get("acknowledged"))
        if ack and acknowledged != (ack == "true"):
            return False
        if archive == "active" and record["isArchived"] or archive == "archived" and not record["isArchived"]:
            return False
        if rating and record["feedbackType"] != rating:
            return False
        return not search or search in record["prompt"].lower()

    def _feedback_stats(self):
        return {
            "total_count": len(self.feedback), "positive_count": 6, "negative_count": 6, "neutral_count": 0,
            "acknowledged_count": 0, "unacknowledged_count": 12, "recent_30_day_count": 12,
            "window": {"days": 30, "start_date": "2026-09-09", "end_date": "2026-10-08"},
            "received_count": 12, "awaiting_review_count": 12, "negative_count_in_window": 6,
            "acknowledged_count_in_window": 0, "acknowledgement_rate": 0, "archived_count": 0,
            "daily_by_rating": {"dates": DATES, "series": [{"key": "Negative", "counts": [1, 1, 1, 1, 1, 1, 0]}]},
            "oldest_awaiting": [{"id": "fb-1", "feedbackType": "Negative", "timestamp": "2026-10-02T10:00:00",
                                 "userId": "user-1", "userDisplayName": "Uma User",
                                 "promptExcerpt": "Question number 1 about the quarterly report"}],
        }

    def _apply_feedback_op(self, operation):
        record = next((item for item in self.feedback if item["id"] == operation["id"]), None)
        base = {"index": operation.get("index"), "id": operation["id"], "op": operation["op"]}
        if operation["id"] in self.fail_bulk_ids:
            return {**base, "ok": False, "status": 409, "code": "record_changed",
                    "error": "This feedback changed after you opened it. Reload it to see the latest version, then try again."}
        if record is None:
            return {**base, "ok": False, "status": 404, "code": "not_found", "error": "Feedback not found"}
        if operation["op"] == "update":
            record["adminReview"].update(operation["changes"])
        elif operation["op"] == "archive":
            record["isArchived"] = operation["archived"]
        else:
            self.feedback.remove(record)
        return {**base, "ok": True, "status": 200}

    # -- Safety -----------------------------------------------------------------------------

    def _safety_matches(self, record, query):
        status = query.get("status", [""])[0]
        archive = query.get("archive", ["active"])[0]
        if status == "open" and record["status"] not in ("New", "In-Review"):
            return False
        if status and status != "open" and record["status"] != status:
            return False
        return not (archive == "active" and record["isArchived"])

    def _safety_stats(self):
        return {
            "total_count": 3, "new_count": 1, "in_review_count": 1, "resolved_count": 1, "dismissed_count": 0,
            "warn_user_count": 1, "suspend_user_count": 0, "escalate_count": 0, "block_user_count": 0,
            "none_action_count": 2, "recent_30_day_count": 3,
            "window": {"days": 30, "start_date": "2026-09-09", "end_date": "2026-10-08"},
            "received_count": 3, "open_count": 2, "pending_remediation_count": 0, "restricted_user_count": 0,
            "warnings_sent_count": 1, "warnings_acknowledged_count": 0, "warnings_pending_count": 1,
            "unchecked_chat_count": len(self.unchecked),
            "daily_by_category": {"dates": DATES, "series": [{"key": "Hate", "counts": [0, 0, 0, 0, 0, 3, 0]}]},
            "severity_mix": [{"severity": 4, "count": 3}],
            "action_mix": [{"action": "None", "count": 2}, {"action": "WarnUser", "count": 1}],
            "repeat_users": [{"user_id": "user-2", "display_name": "Sam Sender", "email": "sam@contoso.test", "count": 3}],
        }

    # -- Routing ----------------------------------------------------------------------------

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        query = parse_qs(parsed.query)
        method = request.method
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
        elif method == "GET" and path == "/feedback/review/stats":
            route.fulfill(json=self._feedback_stats())
        elif method == "GET" and path == "/feedback/review":
            items = [item for item in self.feedback if self._feedback_matches(item, query)]
            page_number = int(query.get("page", ["1"])[0])
            size = int(query.get("page_size", ["20"])[0])
            chunk = items[(page_number - 1) * size:page_number * size]
            route.fulfill(json={"feedback": copy.deepcopy(chunk), "page": page_number, "page_size": size,
                                "total_count": len(items)})
        elif method == "GET" and path == "/feedback/review/ids":
            ids = [item["id"] for item in self.feedback if self._feedback_matches(item, query)]
            route.fulfill(json={"ids": ids, "total": len(ids), "capped": False, "cap": 500})
        elif method == "POST" and path == "/feedback/review/bulk":
            operations = request.post_data_json["operations"]
            self.bulk_calls.append(("feedback", operations))
            results = [self._apply_feedback_op({**operation, "index": index}) for index, operation in enumerate(operations)]
            succeeded = sum(1 for result in results if result["ok"])
            route.fulfill(json={"results": results, "succeeded": succeeded, "failed": len(results) - succeeded})
        elif path.startswith("/feedback/review/"):
            record = next((item for item in self.feedback if item["id"] == path.rsplit("/", 1)[-1]), None)
            if record is None:
                route.fulfill(status=404, json={"error": "Feedback not found"})
            elif method == "GET":
                route.fulfill(json=copy.deepcopy(record))
            elif method == "PATCH":
                body = request.post_data_json
                self.patches.append(("feedback", record["id"], body))
                if body.get("etag") != record["etag"]:
                    route.fulfill(status=409, json={
                        "error": "This feedback changed after you opened it. Reload it to see the latest version, then try again.",
                        "code": "record_changed",
                    })
                    return
                for field in ("acknowledged", "analysisNotes", "actionTaken", "responseToUser"):
                    if field in body:
                        record["adminReview"][field] = body[field]
                record["etag"] = record["etag"] + "+"
                route.fulfill(json={"success": True, "etag": record["etag"], "notified": bool(body.get("notify_user"))})
            else:
                self.unexpected_requests.append(f"{method} {path}")
                route.fulfill(status=404, json={"error": "Unexpected fixture request."})
        elif method == "GET" and path == "/api/safety/logs/stats":
            route.fulfill(json=self._safety_stats())
        elif method == "GET" and path == "/api/safety/logs":
            items = [item for item in self.safety if self._safety_matches(item, query)]
            route.fulfill(json={"logs": copy.deepcopy(items), "page": 1, "page_size": 20, "total_count": len(items)})
        elif path.startswith("/api/safety/logs/") and path.count("/") == 4:
            record = next((item for item in self.safety if item["id"] == path.rsplit("/", 1)[-1]), None)
            if record is None:
                route.fulfill(status=404, json={"error": "Safety violation not found"})
            elif method == "GET":
                route.fulfill(json={**copy.deepcopy(record), "user_access": {"restricted": False},
                                    "user_violation_count": 2})
            elif method == "PATCH":
                body = request.post_data_json
                self.patches.append(("safety", record["id"], body))
                record["status"] = body.get("status", record["status"])
                record["action"] = body.get("action", record["action"])
                record["etag"] = record["etag"] + "+"
                route.fulfill(json={"message": "Safety log updated and remediation approval request created.",
                                    "approval_required": True, "approval_id": "approval-9"})
            else:
                self.unexpected_requests.append(f"{method} {path}")
                route.fulfill(status=404, json={"error": "Unexpected fixture request."})
        elif method == "GET" and path == "/api/safety/chat-checks":
            route.fulfill(json={"items": copy.deepcopy(self.unchecked), "continuation": None})
        elif method == "POST" and path == "/api/safety/chat-checks/recheck":
            body = request.post_data_json
            self.rechecks.append(body["message_id"])
            if body["message_id"] == "msg-1":
                self.unchecked = [item for item in self.unchecked if item["message_id"] != "msg-1"]
                route.fulfill(json={"check": {"status": "passed"}})
            else:
                route.fulfill(json={"check": {"status": "incomplete"}})
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
def review_ui(page):
    fixture = ReviewCenterFixture(page)
    yield fixture
    fixture.assert_clean()


def test_admin_sees_both_sections_and_old_addresses_redirect(review_ui):
    review_ui.open("/v2/admin/review")
    page = review_ui.page
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback")
    expect(page.get_by_test_id("v2-feedback-dashboard")).to_be_visible()
    rail = page.get_by_test_id("v2-review-rail")
    for entry in ("feedback-dashboard", "feedback-queue", "safety-dashboard", "safety-violations", "safety-unchecked"):
        expect(page.get_by_test_id(f"v2-review-rail-{entry}")).to_be_visible()
    expect(rail.get_by_role("group", name="Safety")).to_be_visible()

    page.get_by_test_id("v2-review-rail-safety-unchecked").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/safety/unchecked")
    expect(page.get_by_test_id("v2-unchecked-chat")).to_be_visible()

    # The pages the Review center replaced redirect, keeping their filters.
    page.goto(f"{ORIGIN}/v2/admin/safety-violations?status=open", wait_until="networkidle")
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/safety/violations?status=open")
    expect(page.get_by_test_id("v2-safety-filter-status")).to_have_value("open")
    page.goto(f"{ORIGIN}/v2/admin/feedback-review", wait_until="networkidle")
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue")


def test_a_safety_reviewer_sees_only_safety(page):
    fixture = ReviewCenterFixture(
        page,
        roles=("User", "SafetyViolationAdmin"),
        settings={"require_member_of_safety_violation_admin": True, "require_member_of_feedback_admin": True},
    )
    fixture.open("/v2/admin/review")
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/safety")
    expect(page.get_by_test_id("v2-safety-dashboard")).to_be_visible()
    expect(page.get_by_test_id("v2-review-rail-feedback-dashboard")).to_have_count(0)
    expect(page.get_by_test_id("v2-review-rail-safety-violations")).to_be_visible()

    # A feedback address is refused in the page, and never asks the feedback API.
    page.goto(f"{ORIGIN}/v2/admin/review/feedback/queue", wait_until="networkidle")
    expect(page.get_by_test_id("v2-review-not-available")).to_contain_text("Feedback review is not available to you")
    assert not fixture.requested("/feedback/"), fixture.requested("/feedback/")
    fixture.assert_clean()


def test_a_user_without_a_reviewer_role_sees_a_clear_not_available_state(page):
    fixture = ReviewCenterFixture(page, roles=("User",))
    fixture.open("/v2/admin/review")
    expect(page.get_by_test_id("v2-review-not-available")).to_contain_text("The Review center is not available to you")
    expect(page.get_by_test_id("v2-review-rail")).to_have_count(0)
    assert not fixture.requested("/feedback/") and not fixture.requested("/api/safety/")
    fixture.assert_clean()


def test_dashboard_figures_open_the_filtered_workbench(review_ui):
    review_ui.open("/v2/admin/review/safety")
    page = review_ui.page
    open_tile = page.get_by_test_id("v2-safety-dashboard-open")
    expect(open_tile).to_contain_text("2")
    expect(page.get_by_text("View violations by category as a data table")).to_be_visible()
    open_tile.click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/safety/violations?status=open")
    expect(page.get_by_test_id("v2-safety-row-log-1")).to_be_visible()
    expect(page.get_by_test_id("v2-safety-row-log-3")).to_have_count(0)
    lists = [entry for entry in review_ui.requested("/api/safety/logs") if entry[1] == "/api/safety/logs"]
    assert lists and "status=open" in lists[-1][2], lists

    page.get_by_test_id("v2-review-rail-feedback-dashboard").click()
    page.get_by_test_id("v2-feedback-dashboard-awaiting").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue?ack=false")
    expect(page.get_by_test_id("v2-feedback-filter-ack")).to_have_value("false")


def test_workbench_checks_rows_and_reports_each_bulk_result(review_ui):
    review_ui.open("/v2/admin/review/feedback/queue?size=10")
    page = review_ui.page
    expect(page.get_by_test_id("v2-feedback-row-fb-1")).to_be_visible()
    expect(page.get_by_test_id("v2-feedback-bulk-bar")).to_have_count(0)

    page.get_by_test_id("v2-feedback-check-fb-1").click()
    page.get_by_test_id("v2-feedback-check-fb-3").click(modifiers=["Shift"])
    expect(page.get_by_test_id("v2-feedback-bulk-summary")).to_have_text("3 feedback records selected")
    for record_id in ("fb-1", "fb-2", "fb-3"):
        expect(page.get_by_test_id(f"v2-feedback-check-{record_id}")).to_be_checked()

    review_ui.fail_bulk_ids = {"fb-2"}
    page.get_by_test_id("v2-feedback-bulk-acknowledge").click()
    report = page.get_by_test_id("v2-feedback-bulk-report")
    expect(report).to_contain_text("Acknowledged 2 of 3 feedback records. 1 was not changed.")
    expect(report).to_contain_text("Question number 2 about the quarterly report")
    expect(report).to_contain_text("changed after you opened it")
    assert review_ui.bulk_calls[-1] == ("feedback", [
        {"id": record_id, "op": "update", "changes": {"acknowledged": True}} for record_id in ("fb-1", "fb-2", "fb-3")
    ])
    # Only the record that could not be changed stays checked.
    expect(page.get_by_test_id("v2-feedback-bulk-summary")).to_have_text("1 feedback record selected")
    expect(page.get_by_test_id("v2-feedback-check-fb-2")).to_be_checked()

    # The whole page, then every matching record, then a confirmed delete with the count.
    review_ui.fail_bulk_ids = set()
    page.get_by_test_id("v2-feedback-bulk-clear").click()
    page.get_by_test_id("v2-feedback-select-page").check()
    expect(page.get_by_test_id("v2-feedback-bulk-summary")).to_have_text("10 feedback records selected")
    page.get_by_test_id("v2-feedback-select-matching").click()
    expect(page.get_by_test_id("v2-feedback-bulk-summary")).to_have_text("All 12 feedback records matching these filters selected")
    page.get_by_test_id("v2-feedback-bulk-delete").click()
    dialog = page.get_by_role("dialog", name="Permanently delete 12 feedback records?")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_have_count(0)
    assert all(call[1][0]["op"] != "delete" for call in review_ui.bulk_calls)


def test_editor_guards_unsaved_changes_and_returns_to_the_same_list(review_ui):
    review_ui.open("/v2/admin/review/feedback/queue?type=Negative")
    page = review_ui.page
    page.get_by_test_id("v2-feedback-row-fb-3").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue?type=Negative&selected=fb-3")
    page.get_by_test_id("v2-feedback-open-editor").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue/fb-3?type=Negative&selected=fb-3")
    expect(page.get_by_test_id("v2-feedback-editor")).to_be_visible()

    notes = page.get_by_test_id("v2-feedback-editor-analysis")
    notes.fill("Looked into it.")
    page.get_by_role("button", name="Back", exact=True).click()
    prompt = page.get_by_role("dialog", name="Discard unsaved changes?")
    expect(prompt).to_be_visible()
    prompt.get_by_role("button", name="Keep editing").click()
    expect(notes).to_have_value("Looked into it.")
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue/fb-3?type=Negative&selected=fb-3")

    page.get_by_role("button", name="Save review").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue?type=Negative&selected=fb-3")
    expect(page.get_by_test_id("v2-feedback-saved")).to_have_text("Review saved.")
    assert review_ui.patches[-1] == ("feedback", "fb-3", {
        "acknowledged": False, "analysisNotes": "Looked into it.", "actionTaken": "", "responseToUser": "",
        "notify_user": False, "etag": "v1",
    })

    # A record that changed underneath the editor is reloaded rather than overwritten.
    page.get_by_test_id("v2-feedback-open-editor").click()
    review_ui.feedback[2]["etag"] = "changed-elsewhere"
    page.get_by_test_id("v2-feedback-editor-analysis").fill("Second look.")
    page.get_by_role("button", name="Save review").click()
    expect(page.get_by_role("alert")).to_contain_text("changed after you opened it")
    page.get_by_test_id("v2-feedback-editor-reload").click()
    expect(page.get_by_test_id("v2-feedback-editor-analysis")).to_have_value("Looked into it.")
    page.get_by_role("button", name="Back", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/feedback/queue?type=Negative&selected=fb-3")


def test_violation_editor_prefills_the_notice_and_suspension_length(review_ui):
    review_ui.open("/v2/admin/review/safety/violations/log-1?selected=log-1")
    page = review_ui.page
    expect(page.get_by_test_id("v2-safety-editor")).to_be_visible()
    action = page.get_by_test_id("v2-safety-editor-action")
    expect(action.locator("option")).to_have_text(["No action", "Warn user", "Suspend user", "Block user"])

    action.select_option("WarnUser")
    expect(page.get_by_test_id("v2-safety-editor-action-copy")).to_contain_text("The warning is sent to the user as soon as you save")
    expect(page.get_by_test_id("v2-safety-editor-title")).to_have_value("Safety Violation Warning")

    action.select_option("SuspendUser")
    expect(page.get_by_test_id("v2-safety-editor-action-copy")).to_contain_text("another eligible reviewer approves it")
    page.get_by_role("button", name="Save review").click()
    expect(page.get_by_role("alert")).to_contain_text("Choose how long the suspension lasts.")
    assert not review_ui.patches

    page.get_by_test_id("v2-safety-editor-preset-7d").check()
    expect(page.get_by_test_id("v2-safety-editor-restore-at")).to_contain_text("Access returns")
    message = page.get_by_test_id("v2-safety-editor-message")
    assert "Access restores automatically after:" in message.input_value()
    page.get_by_role("button", name="Save review").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/review/safety/violations?selected=log-1")
    expect(page.get_by_test_id("v2-safety-saved")).to_contain_text("remediation approval request created")
    kind, record_id, body = review_ui.patches[-1]
    assert (kind, record_id, body["action"], body["etag"]) == ("safety", "log-1", "SuspendUser", "s1")
    assert body["notification_title"] == "Account Suspension Notice" and body["datetime_to_allow"]
    assert "Access restores automatically after:" in body["notification_message"]


def test_unchecked_chat_content_is_rechecked_one_message_at_a_time(review_ui):
    review_ui.open("/v2/admin/review/safety/unchecked")
    page = review_ui.page
    expect(page.get_by_test_id("v2-unchecked-row-msg-1")).to_be_visible()
    page.get_by_test_id("v2-unchecked-select-all").check()
    page.get_by_test_id("v2-unchecked-bulk-recheck").click()
    dialog = page.get_by_role("dialog", name="Recheck 2 messages?")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Recheck 2 messages").click()
    report = page.get_by_test_id("v2-unchecked-bulk-report")
    expect(report).to_contain_text("Rechecked 2 messages: 1 passed, 1 could not finish.")
    expect(report).to_contain_text("Message msg-2")
    assert review_ui.rechecks == ["msg-1", "msg-2"]
    expect(page.get_by_test_id("v2-unchecked-row-msg-1")).to_have_count(0)
    # The message that could not finish stays selected to try again.
    expect(page.get_by_test_id("v2-unchecked-bulk-bar")).to_contain_text("1 message selected")
