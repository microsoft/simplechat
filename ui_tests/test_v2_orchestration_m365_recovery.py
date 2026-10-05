# test_v2_orchestration_m365_recovery.py
"""
Real-component browser coverage for plan steps that stopped for Microsoft 365.
Version: 0.261.238
Implemented in: 0.261.238

A step that stopped for Microsoft 365 sign-in offers Connect Microsoft 365 in its run's
recovery notice, and a step that stopped for approval links to Approvals. The production
notice, connect flow, controller, stores, and message list run in Chromium. Only HTTP
responses are deterministic, including the sign-in window's last page: a stand-in for the
Profile page, which either tells its opener it connected or closes without saying so.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_m365_recovery.py -q
"""

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_recovery as recovery_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
# The server's own messages for these failures, from FAILURE_MESSAGES.
SIGN_IN_MESSAGE = (
    "Microsoft 365 needs you to sign in or grant access before this step can read your data. "
    "Select Connect Microsoft 365, then Retry from failed step."
)
APPROVAL_MESSAGE = (
    "This step needs your approval before it can use Microsoft 365. Review it in Approvals, "
    "then select Retry from failed step."
)
CONNECTED = "Microsoft 365 is connected. Select Retry from failed step to continue."
NOT_COMPLETED = "Microsoft 365 sign-in was not completed. Connect again when you are ready."
CSRF_TOKEN = "m365-recovery-test-csrf-token-000000000001"
PROFILE_PATH = "/profile"
SIGN_IN_URL = (
    "https://simplechat.test/profile?tab=settings&m365_chat_connection=connected#m365-chat-connection"
)
EARLIER = "2026-09-01T08:00:00+00:00"
LATER = "2026-09-08T12:02:00+00:00"


class M365RecoveryApi(recovery_tests.RecoveryApi):
    """The recovery API plus the Profile connection routes the notice uses."""

    def __init__(self, assets):
        super().__init__(assets)
        self.connection = {"status": "available", "sources": ["calendar"], "connected_at": EARLIER}
        self.connects = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/api/m365/chat/connection" and request.method == "GET":
            self.requests.append({"path": path, "method": "GET", "body": None})
            route.fulfill(json={"connection": dict(self.connection), "csrf_token": CSRF_TOKEN})
            return
        if path == "/api/m365/chat/connection/connect" and request.method == "POST":
            body = request.post_data_json
            self.requests.append({"path": path, "method": "POST", "body": body})
            self.connects.append({"body": body, "csrf": request.headers.get("x-m365-csrf-token")})
            route.fulfill(json={"authorization_url": SIGN_IN_URL})
            return
        super().handle(route)


@pytest.fixture
def m365_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = M365RecoveryApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def sign_in_window(page, api, *, reports, saves=True):
    """Serve the sign-in window's last page, which only the popup ever requests.

    ``reports`` posts the Profile page's message to the opener. Without it the window
    closes without a word, as when the message is lost; ``saves`` decides whether the
    sign-in was saved first.
    """
    def finish(route):
        if urlsplit(route.request.url).path != PROFILE_PATH:
            route.fulfill(status=204)
            return
        if saves:
            api.connection = {"status": "available", "sources": ["calendar", "email"], "connected_at": LATER}
        script = (
            "window.opener.postMessage({ type: 'm365-profile-reconnected' }, window.location.origin);"
            if reports else "window.close();"
        )
        route.fulfill(content_type="text/html", body=f"<!doctype html><title>Profile</title><script>{script}</script>")

    # Context routes reach the popup; the page's own route still answers the chat page first.
    page.context.route("**/*", finish)


def start(page, api, message):
    recovery_tests.mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text(message, exact=True).first).to_be_visible()
    expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    return page.get_by_label("Microsoft 365 follow-up").first


def wait_closed(popup):
    if not popup.is_closed():
        popup.wait_for_event("close")


def test_sign_in_stop_connects_only_known_sources_then_waits_for_retry(m365_ui):
    page, api = m365_ui
    api.failure = {
        "code": "m365_sign_in_required", "message": SIGN_IN_MESSAGE,
        "m365_sources": ["email", "not-a-source"],
    }
    sign_in_window(page, api, reports=True)
    notice = start(page, api, SIGN_IN_MESSAGE)
    expect(notice.get_by_text("For Email.", exact=True)).to_be_visible()

    with page.expect_popup() as opened:
        notice.get_by_role("button", name="Connect Microsoft 365").click()
    expect(notice.get_by_role("status")).to_have_text(CONNECTED)
    wait_closed(opened.value)

    assert api.connects == [{"body": {"sources": ["email"]}, "csrf": CSRF_TOKEN}]
    expect(notice.get_by_role("button", name="Connect Microsoft 365")).to_have_count(0)
    expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    # Connecting saves the sign-in only; the user retries the failed step.
    assert not api.calls("/retry") and len(api.calls("/run")) == 1


def test_closed_sign_in_window_without_a_saved_sign_in_can_connect_again(m365_ui):
    page, api = m365_ui
    api.failure = {"code": "m365_sign_in_required", "message": SIGN_IN_MESSAGE, "m365_sources": ["email"]}
    sign_in_window(page, api, reports=False, saves=False)
    notice = start(page, api, SIGN_IN_MESSAGE)

    with page.expect_popup() as opened:
        notice.get_by_role("button", name="Connect Microsoft 365").click()
    wait_closed(opened.value)
    expect(notice.get_by_role("alert")).to_have_text(NOT_COMPLETED)
    expect(notice.get_by_role("button", name="Connect Microsoft 365")).to_be_enabled()
    expect(notice.get_by_role("status")).to_have_count(0)
    assert len(api.connects) == 1 and not api.calls("/retry")


def test_saved_sign_in_is_confirmed_when_the_window_closes_without_reporting(m365_ui):
    # A Profile page on another origin can't message the chat page, so the saved
    # connection confirms the sign-in once the window closes.
    page, api = m365_ui
    api.failure = {"code": "m365_sign_in_required", "message": SIGN_IN_MESSAGE, "m365_sources": ["email"]}
    sign_in_window(page, api, reports=False)
    notice = start(page, api, SIGN_IN_MESSAGE)

    with page.expect_popup() as opened:
        notice.get_by_role("button", name="Connect Microsoft 365").click()
    wait_closed(opened.value)
    expect(notice.get_by_role("status")).to_have_text(CONNECTED)
    expect(notice.get_by_role("alert")).to_have_count(0)


def test_sign_in_stop_without_sources_links_to_profile(m365_ui):
    page, api = m365_ui
    api.failure = {"code": "m365_sign_in_required", "message": SIGN_IN_MESSAGE}
    notice = start(page, api, SIGN_IN_MESSAGE)
    expect(notice.get_by_role("link", name="Connect Microsoft 365 in Profile settings")).to_have_attribute(
        "href", "/profile?tab=settings#m365-chat-connection",
    )
    expect(notice.get_by_role("button", name="Connect Microsoft 365")).to_have_count(0)


def test_approval_stop_links_to_approvals_without_connecting(m365_ui):
    page, api = m365_ui
    api.failure = {"code": "m365_approval_required", "message": APPROVAL_MESSAGE, "m365_sources": ["onedrive"]}
    notice = start(page, api, APPROVAL_MESSAGE)
    expect(notice.get_by_role("link", name="Review the Microsoft 365 approval")).to_have_attribute(
        "href", "/approvals",
    )
    expect(notice.get_by_role("button", name="Connect Microsoft 365")).to_have_count(0)
    assert not api.connects


def test_other_step_failures_have_no_microsoft_365_follow_up(m365_ui):
    page, api = m365_ui
    recovery_tests.start_failure(page, api)
    expect(page.get_by_label("Microsoft 365 follow-up")).to_have_count(0)
    assert not any(request["path"].startswith("/api/m365/") for request in api.requests)
