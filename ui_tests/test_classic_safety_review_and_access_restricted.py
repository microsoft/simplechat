# test_classic_safety_review_and_access_restricted.py
"""
Browser coverage for the classic safety review changes and the classic Access restricted page.
Version: 0.261.298
Implemented in: 0.261.297
Requesting a suspension or block again: 0.261.298
Reading the action select through a fixed list of actions: 0.261.298

Render the real classic templates with Jinja and run the real local scripts behind a closed,
in-memory API. Check that the admin review no longer offers Escalate, labels a legacy
escalated record and offers its legacy action only on that record, describes which actions
wait for a second reviewer, shows whether a sent warning was acknowledged without offering to
resend it, and shows Blocked statistics with legacy escalations only when there are some;
that saving a suspension or block the violation already records requests nothing unless the
reviewer asks for it again, which sends the new notification and restore time; that only a
known action, never other text placed in the action select, reaches the review's data
attributes or a save; and that the classic Access restricted page renders the notice as text
and shows the restore time in the reader's locale. Unexpected requests, page errors and
browser dialogs fail.
"""

import copy
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from jinja2 import ChainableUndefined, ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import Page, expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "application" / "single_app" / "templates"
STATIC = REPO_ROOT / "application" / "single_app" / "static"
ORIGIN = "http://classic-safety.test"

BASE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="UTF-8" />
<title>{% block title %}{% endblock %}</title>
<link rel="stylesheet" href="/static/css/bootstrap.min.css" />
<link rel="stylesheet" href="/static/css/bootstrap-icons.min.css" />
{% block head %}{% endblock %}
</head><body>
{% block content %}{% endblock %}
<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>
{% block scripts %}{% endblock %}
</body></html>"""

LOGS = [
    {
        "id": "log-legacy", "user_id": "user-1", "message": "Legacy escalated record.", "status": "In-Review",
        "action": "Escalate", "notes": "", "created_at": "2026-05-01T12:00:00Z", "last_updated": "2026-05-01T12:00:00Z",
        "triggered_categories": [{"category": "Hate", "severity": 4}],
    },
    {
        "id": "log-warned", "user_id": "user-2", "message": "Warned record.", "status": "Resolved",
        "action": "WarnUser", "action_request_status": "executed", "notes": "Sent.",
        "warning_requires_acknowledgment": True, "warning_acknowledgment_status": "pending",
        "warning_acknowledged_at": None, "created_at": "2026-05-02T12:00:00Z", "last_updated": "2026-05-02T12:00:00Z",
        "triggered_categories": [{"category": "Violence", "severity": 4}],
    },
    {
        "id": "log-new", "user_id": "user-3", "message": "New record.", "status": "New", "action": "None",
        "notes": "", "created_at": "2026-05-03T12:00:00Z", "last_updated": "2026-05-03T12:00:00Z",
        "triggered_categories": [{"category": "Sexual", "severity": 2}],
    },
]


class ClassicSafetyFixture:
    """The classic admin safety review and Access restricted pages behind a closed API."""

    def __init__(self, page: Page):
        self.page = page
        self.logs = copy.deepcopy(LOGS)
        self.stats = {
            "total_count": 3, "new_count": 1, "in_review_count": 1, "resolved_count": 1, "dismissed_count": 0,
            "warn_user_count": 1, "suspend_user_count": 0, "escalate_count": 1, "block_user_count": 4,
            "none_action_count": 1, "recent_30_day_count": 3,
        }
        self.restriction = None
        self.patches = []
        # Saves are answered with patch_reply, or held open until a test fulfills them.
        self.patch_reply = (200, {"message": "Warning sent to the user.", "approval_required": False})
        self.hold_patches = False
        self.held = []
        self.errors = []
        self.unexpected = []
        self.dialogs = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on("dialog", self._dialog)
        page.route("**/*", self._route)

    def _dialog(self, dialog):
        self.dialogs.append(dialog.type)
        dialog.dismiss()

    def _render(self, template, **context):
        environment = Environment(
            loader=ChoiceLoader([DictLoader({"base.html": BASE_TEMPLATE}), FileSystemLoader(str(TEMPLATES))]),
            undefined=ChainableUndefined,
            autoescape=select_autoescape(["html"]),
        )
        endpoints = {"frontend_authentication.logout": "/logout", "public_app.index": "/"}
        environment.globals["url_for"] = (
            lambda endpoint, **values: endpoints.get(endpoint) or "/static/" + values.get("filename", "")
        )
        return environment.get_template(template).render(**context)

    def _route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if not request.url.startswith(ORIGIN + "/"):
            self.unexpected.append(request.url)
            route.abort()
            return
        path = unquote(url.path)
        if path.startswith("/static/"):
            file = (STATIC / path.removeprefix("/static/")).resolve()
            if file.is_relative_to(STATIC.resolve()) and file.is_file():
                mime = "text/javascript" if file.suffix == ".js" else mimetypes.guess_type(str(file))[0] or "application/octet-stream"
                route.fulfill(path=str(file), content_type=mime)
                return
        elif path == "/admin/safety_violations":
            route.fulfill(body=self._render(
                "admin_safety_violations.html",
                app_settings={"app_title": "SimpleChat"},
                settings={"enable_content_safety": True},
            ), content_type="text/html")
            return
        elif path == "/access-restricted":
            route.fulfill(body=self._render(
                "access_restricted.html",
                app_settings={"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
                restriction=self.restriction,
                restore_display="2031-03-04 15:30 UTC",
            ), content_type="text/html")
            return
        elif path == "/api/safety/logs/stats":
            route.fulfill(json=self.stats)
            return
        elif path == "/api/safety/logs" and request.method == "GET":
            route.fulfill(json={"logs": self.logs, "page": 1, "page_size": 10, "total_count": len(self.logs)})
            return
        elif path.startswith("/api/safety/logs/") and request.method == "PATCH":
            self.patches.append((path.rsplit("/", 1)[-1], request.post_data_json))
            if self.hold_patches:
                self.held.append(route)
                return
            status, body = self.patch_reply
            route.fulfill(status=status, json=body)
            return
        elif path == "/api/safety/chat-checks":
            route.fulfill(json={"items": [], "continuation": None})
            return
        elif path.startswith("/api/user/info/"):
            route.fulfill(json={"display_name": "Test User", "email": "user@contoso.test"})
            return
        elif path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def assert_clean(self):
        assert not self.unexpected, self.unexpected
        assert not self.errors, self.errors
        assert not self.dialogs, self.dialogs


@pytest.fixture
def classic_ui(page):
    fixture = ClassicSafetyFixture(page)
    yield fixture
    fixture.assert_clean()


def _open_review(page, log_id):
    page.locator(f'#safetyLogsTable button[data-log-id="{log_id}"][data-action="view"]').click()
    modal = page.locator("#editModal")
    expect(modal).to_be_visible()
    return modal


def test_admin_review_retires_escalate_and_shows_warning_state(classic_ui):
    page = classic_ui.page
    page.goto(f"{ORIGIN}/admin/safety_violations", wait_until="networkidle")

    expect(page.locator("#safetyBlockedCount")).to_have_text("4")
    expect(page.locator("#safetyStatsBlockSummary")).to_have_text("4")
    expect(page.locator("#safetyStatsLegacyEscalateRow")).to_be_visible()
    expect(page.locator("#safetyStatsLegacyEscalateSummary")).to_have_text("1")

    page.get_by_role("tab", name="All Data").click()
    filter_values = page.locator("#filterAction option").evaluate_all("options => options.map(option => option.value)")
    assert filter_values == ["", "None", "WarnUser", "SuspendUser", "BlockUser"], filter_values
    table = page.locator("#safetyLogsTable tbody")
    expect(table).to_contain_text("Escalated (legacy)")

    # A legacy record keeps its action, labelled as legacy; other records don't offer it.
    modal = _open_review(page, "log-legacy")
    expect(page.locator("#editAction")).to_have_value("Escalate")
    expect(page.locator("#editAction option[value='Escalate']")).to_have_text("Escalated (legacy)")
    expect(page.locator("#safetyWarningAcknowledgment")).to_be_hidden()
    modal.locator(".btn-close").click()
    expect(modal).to_be_hidden()

    # A sent warning shows its acknowledgment state and is not offered for sending again.
    modal = _open_review(page, "log-warned")
    expect(page.locator("#editAction option[value='Escalate']")).to_have_count(0)
    expect(page.locator("#safetyWarningAcknowledgment")).to_have_text("Warning sent. Not yet acknowledged by the user.")
    expect(page.locator("#safetyRemediationHelp")).to_contain_text("already sent")
    expect(page.locator("#safetyNotificationGroup")).to_be_hidden()
    modal.locator(".btn-close").click()
    expect(modal).to_be_hidden()

    # A new warning is sent on save, while suspensions and blocks wait for another reviewer.
    _open_review(page, "log-new")
    page.locator("#editAction").select_option("SuspendUser")
    expect(page.locator("#safetyRemediationHelp")).to_contain_text("another eligible reviewer approves it")
    page.locator("#editAction").select_option("WarnUser")
    expect(page.locator("#safetyRemediationHelp")).to_contain_text("as soon as you save, without a second reviewer")
    expect(page.locator("#safetyNotificationGroup")).to_be_visible()
    page.locator("#saveChangesBtn").click()
    expect(page.locator("#safetyPageStatusAlert")).to_have_text("Warning sent to the user.")
    log_id, payload = classic_ui.patches[-1]
    assert log_id == "log-new" and payload["action"] == "WarnUser" and payload["notification_message"]


def test_legacy_escalations_are_only_mentioned_when_there_are_some(classic_ui):
    classic_ui.stats["escalate_count"] = 0
    page = classic_ui.page
    page.goto(f"{ORIGIN}/admin/safety_violations", wait_until="networkidle")
    expect(page.locator("#safetyBlockedCount")).to_have_text("4")
    expect(page.locator("#safetyStatsLegacyEscalateRow")).to_be_hidden()


def test_a_suspension_or_block_is_requested_again_only_on_purpose(classic_ui):
    restore_at = "2031-06-01T09:30:00Z"
    classic_ui.logs.extend([
        {
            "id": "log-denied", "user_id": "user-4", "message": "Denied suspension.", "status": "In-Review",
            "action": "SuspendUser", "action_request_status": "denied", "action_request_id": "approval-9",
            "action_notification_message": "Your access is suspended.", "action_datetime_to_allow": restore_at,
            "notes": "", "created_at": "2026-05-04T12:00:00Z", "last_updated": "2026-05-04T12:00:00Z",
            "triggered_categories": [{"category": "Hate", "severity": 6}],
        },
        {
            "id": "log-blocked", "user_id": "user-5", "message": "Applied block.", "status": "Resolved",
            "action": "BlockUser", "action_request_status": "executed", "action_request_id": "approval-8",
            "notes": "", "created_at": "2026-05-05T12:00:00Z", "last_updated": "2026-05-05T12:00:00Z",
            "triggered_categories": [{"category": "Violence", "severity": 6}],
        },
        {
            "id": "log-waiting", "user_id": "user-6", "message": "Waiting suspension.", "status": "In-Review",
            "action": "SuspendUser", "action_request_status": "pending", "action_request_id": "approval-7",
            "notes": "", "created_at": "2026-05-06T12:00:00Z", "last_updated": "2026-05-06T12:00:00Z",
            "triggered_categories": [{"category": "Hate", "severity": 4}],
        },
    ])
    page = classic_ui.page
    page.goto(f"{ORIGIN}/admin/safety_violations", wait_until="networkidle")
    page.get_by_role("tab", name="All Data").click()
    help_text = page.locator("#safetyRemediationHelp")
    reissue = page.locator("#editReissue")

    # A denied suspension: saving it as it is requests nothing, so nothing is sent with it.
    modal = _open_review(page, "log-denied")
    expect(help_text).to_contain_text(
        "This suspension request was denied. Saving updates the review only and requests nothing new."
    )
    expect(page.get_by_label("Request this suspension again")).not_to_be_checked()
    expect(page.locator("#safetyNotificationGroup")).to_be_hidden()
    expect(page.locator("#safetySuspendUntilGroup")).to_be_hidden()
    unchanged = (
        'Safety log updated. No new suspension was requested. To request it again, select '
        '"Request this suspension again" and save.'
    )
    classic_ui.patch_reply = (200, {"message": unchanged, "approval_required": False, "remediation_unchanged": True})
    page.locator("#saveChangesBtn").click()
    expect(page.locator("#safetyPageStatusAlert")).to_have_text(unchanged)
    log_id, payload = classic_ui.patches[-1]
    assert log_id == "log-denied" and payload == {"status": "In-Review", "action": "SuspendUser", "notes": ""}, payload

    # Asking for it again offers the last message and a restore time, and says what it does.
    modal = _open_review(page, "log-denied")
    expect(reissue).not_to_be_checked()
    reissue.check()
    expect(help_text).to_contain_text("saving creates an approval request")
    expect(page.locator("#editReissueHelp")).to_contain_text("notification and restore date below")
    expect(page.locator("#safetyNotificationGroup")).to_be_visible()
    expect(page.locator("#editNotificationMessage")).to_have_value("Your access is suspended.")
    expect(page.locator("#safetySuspendUntilGroup")).to_be_visible()
    expect(page.locator("#editSuspendUntil")).not_to_have_value("")
    page.locator("#editSuspendUntil").fill("2031-07-01T12:00")
    classic_ui.patch_reply = (200, {"message": "Safety log updated and remediation approval request created.", "approval_required": True})
    page.locator("#saveChangesBtn").click()
    expect(page.locator("#safetyPageStatusAlert")).to_have_text("Safety log updated and remediation approval request created.")
    _, payload = classic_ui.patches[-1]
    expected_restore = page.evaluate("new Date('2031-07-01T12:00').toISOString()")
    assert payload["reissue"] is True and payload["notification_message"] == "Your access is suspended.", payload
    assert payload["datetime_to_allow"] == expected_restore, payload

    # An applied block says so, and offers the same choice under its own name.
    modal = _open_review(page, "log-blocked")
    expect(help_text).to_contain_text("This block was approved and applied.")
    expect(page.get_by_label("Request this block again")).to_be_visible()
    expect(page.locator("#editReissueHelp")).to_contain_text("notification below")
    modal.locator(".btn-close").click()
    expect(modal).to_be_hidden()

    # One still waiting for approval offers nothing to request.
    modal = _open_review(page, "log-waiting")
    expect(help_text).to_contain_text("waiting for another eligible reviewer to approve it")
    expect(page.locator("#safetyReissueGroup")).to_be_hidden()
    expect(page.locator("#safetyNotificationGroup")).to_be_hidden()
    modal.locator(".btn-close").click()
    expect(modal).to_be_hidden()

    # Choosing a different action still requests it, as before.
    modal = _open_review(page, "log-blocked")
    page.locator("#editAction").select_option("SuspendUser")
    expect(page.locator("#safetyReissueGroup")).to_be_hidden()
    expect(help_text).to_contain_text("saving creates an approval request")
    expect(page.locator("#safetySuspendUntilGroup")).to_be_visible()
    expect(page.locator("#editSuspendUntil")).to_have_value("")
    modal.locator(".btn-close").click()
    expect(modal).to_be_hidden()


def test_only_a_known_action_reaches_the_page_or_a_save(classic_ui):
    page = classic_ui.page
    page.goto(f"{ORIGIN}/admin/safety_violations", wait_until="networkidle")
    page.get_by_role("tab", name="All Data").click()
    _open_review(page, "log-new")
    notification = page.locator("#editNotificationMessage")
    restore_time = page.locator("#editSuspendUntil")

    # A chosen action is kept as it is.
    page.locator("#editAction").select_option("SuspendUser")
    expect(notification).to_have_attribute("data-action", "SuspendUser")
    expect(restore_time).to_have_attribute("data-action", "SuspendUser")

    # Text put into the select some other way reads as no action, so it never reaches the
    # review's data attributes or the save.
    forged = '"><img src=x onerror=alert(1)>'
    page.locator("#editAction").evaluate(
        """(select, value) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = 'Forged';
            select.appendChild(option);
            select.value = value;
            select.dispatchEvent(new Event('change'));
        }""",
        forged,
    )
    expect(notification).to_have_attribute("data-action", "None")
    expect(restore_time).to_have_attribute("data-action", "None")
    expect(page.locator("#safetyRemediationFields")).to_be_hidden()
    classic_ui.patch_reply = (200, {"message": "Safety log updated successfully.", "approval_required": False})
    page.locator("#saveChangesBtn").click()
    expect(page.locator("#safetyPageStatusAlert")).to_have_text("Safety log updated successfully.")
    log_id, payload = classic_ui.patches[-1]
    assert log_id == "log-new" and payload == {"status": "New", "action": "None", "notes": ""}, payload


def test_save_waits_for_its_request_so_a_double_click_sends_one(classic_ui):
    page = classic_ui.page
    page.goto(f"{ORIGIN}/admin/safety_violations", wait_until="networkidle")
    page.get_by_role("tab", name="All Data").click()
    _open_review(page, "log-new")
    page.locator("#editAction").select_option("WarnUser")
    save = page.locator("#saveChangesBtn")

    classic_ui.hold_patches = True
    save.click()
    expect(save).to_be_disabled()
    expect(save).to_have_attribute("aria-busy", "true")
    # A second click while the save is in flight does nothing.
    save.dispatch_event("click")
    page.evaluate("() => new Promise((resolve) => setTimeout(resolve, 150))")
    assert len(classic_ui.patches) == 1, classic_ui.patches

    classic_ui.hold_patches = False
    classic_ui.held.pop().fulfill(json={"message": "Warning sent to the user.", "approval_required": False})
    expect(page.locator("#safetyPageStatusAlert")).to_have_text("Warning sent to the user.")
    expect(save).to_be_enabled()
    expect(save).not_to_have_attribute("aria-busy", "true")
    assert len(classic_ui.patches) == 1, classic_ui.patches

    # A save the server refuses gives Save back, with the reason.
    refused = (
        "Another save of this violation got there first, so this one saved nothing and sent no "
        "warning. Reload the violation in a moment to see the result."
    )
    classic_ui.patch_reply = (409, {"error": refused, "code": "safety_warning_in_progress"})
    _open_review(page, "log-new")
    page.locator("#editAction").select_option("WarnUser")
    save.click()
    expect(page.locator("#safetyEditStatus")).to_have_text(refused)
    expect(save).to_be_enabled()
    assert len(classic_ui.patches) == 2, classic_ui.patches


def test_classic_access_restricted_page_shows_the_notice_and_local_restore_time(classic_ui):
    classic_ui.restriction = {
        "kind": "suspended",
        "until": "2031-03-04T15:30:00+00:00",
        "title": "Account Suspension Notice",
        "message": "Suspended pending review.\n<b>Not bold</b>",
        "reference_id": "safety-log-42",
    }
    page = classic_ui.page
    page.goto(f"{ORIGIN}/access-restricted", wait_until="networkidle")

    expect(page.get_by_role("heading", name="Account Suspension Notice")).to_be_visible()
    message = page.get_by_test_id("access-restricted-message")
    expect(message).to_contain_text("<b>Not bold</b>")
    expect(message.locator("b")).to_have_count(0)
    expected_local = page.evaluate(
        "new Date('2031-03-04T15:30:00+00:00').toLocaleString(undefined, { dateStyle: 'full', timeStyle: 'short' })"
    )
    expect(page.locator("time[datetime='2031-03-04T15:30:00+00:00']")).to_have_text(expected_local)
    expect(page.get_by_text("safety-log-42")).to_be_visible()
    expect(page.get_by_role("link", name="Sign out")).to_have_attribute("href", "/logout")

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_classic_access_restricted_page_for_a_block_and_a_restored_account(classic_ui):
    classic_ui.restriction = {
        "kind": "blocked", "until": None, "title": "Your access has been blocked",
        "message": "An administrator has blocked your access.", "reference_id": None,
    }
    page = classic_ui.page
    page.goto(f"{ORIGIN}/access-restricted", wait_until="networkidle")
    expect(page.get_by_text("No automatic restore date")).to_be_visible()
    expect(page.locator("time")).to_have_count(0)

    classic_ui.restriction = None
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("heading", name="Your access is available")).to_be_visible()
    expect(page.get_by_role("link", name="Continue")).to_have_attribute("href", "/")
