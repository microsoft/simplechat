# test_v2_access_restricted_and_safety_warning.py
"""
Browser coverage for the V2 Access restricted page and the safety warning dialog.
Version: 0.261.297
Implemented in: 0.261.297

Serve the real built SPA through Playwright request interception with a closed API
boundary. Check that a restricted user whose first call is refused lands on the Access
restricted page instead of an error, sees the administrator's notice as text, when access
returns in their own locale, the violation reference and a Sign out link; that a block and
a restored account read differently; that a safety warning appears in a dialog that Escape
does not dismiss, is acknowledged with "I understand" naming when the warning read was sent,
shows the next waiting warning, shows the newer warning when the one on screen was replaced,
and stays when an acknowledgment fails; and that warnings are read only when bootstrap counts
some, including when the reader comes back to the tab. Unexpected requests and page errors
fail.
"""

import copy
import sys
from pathlib import Path
from urllib.parse import urlsplit

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

SUSPENSION = {
    "restricted": True,
    "restriction": {
        "kind": "suspended",
        "until": "2031-03-04T15:30:00+00:00",
        "title": "Account Suspension Notice",
        "message": "Your access is suspended pending review.\n<b>Not bold</b>",
        "reference_id": "safety-log-42",
    },
    "branding": {"app_title": "SimpleChat", "hide_app_title": False, "show_logo": False, "classification_banner": None},
}

WARNINGS = [
    {
        "id": "log-1",
        "violation_id": "log-1",
        "title": "Safety Violation Warning",
        "message": "A safety review has been completed.\n<i>Plain text</i>",
        "issued_at": "2026-10-07T12:00:00+00:00",
        "acknowledged_at": None,
        "triggered_categories": [{"category": "Hate", "severity": 4}],
    },
    {
        "id": "log-2",
        "violation_id": "log-2",
        "title": "Second warning",
        "message": "Please review the acceptable use policy.",
        "issued_at": "2026-10-07T13:00:00+00:00",
        "acknowledged_at": None,
        "triggered_categories": [],
    },
]


class RestrictionFixture:
    """The V2 app with an in-memory API for access restrictions and safety warnings."""

    def __init__(self, page: Page):
        self.page = page
        self.restricted_bootstrap = False
        self.restriction_payload = copy.deepcopy(SUSPENSION)
        self.warnings = []
        self.pending_reads = 0
        self.acknowledgments = []
        self.acknowledgment_bodies = []
        self.fail_next_acknowledgment = False
        self.errors = []
        self.unexpected_requests = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self._route)

    def _bootstrap(self):
        return {
            "version": "0.261.297",
            "user": {"id": "user-1", "display_name": "Test User", "email": "test.user@contoso.test",
                     "is_admin": False, "roles": ["User"]},
            "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
            "features": {},
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {"custom_pages": {"enabled": False, "items": []},
                           "external_links": {"enabled": False, "items": []}},
            "workspace": {"sections": {}},
            "safety_warnings": {"pending": len(self.warnings)},
            "settings": {},
        }

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        method = request.method
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
            return
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
            if self.restricted_bootstrap:
                route.fulfill(status=403, json={
                    "error": "access_restricted",
                    "message": "Your access to this application is temporarily suspended.",
                    "restriction": self.restriction_payload.get("restriction"),
                    "restricted_url": "/v2/access-restricted",
                })
            else:
                route.fulfill(json=self._bootstrap())
        elif method == "GET" and path == "/api/v2/access-restriction":
            route.fulfill(json=self.restriction_payload, headers={"Cache-Control": "no-store"})
        elif path == "/api/user/settings":
            if self.restricted_bootstrap:
                route.fulfill(status=403, json={"error": "access_restricted", "message": "Restricted."})
            elif method == "GET":
                route.fulfill(json={"settings": self.preferences})
            else:
                self.preferences.update(request.post_data_json["settings"])
                route.fulfill(json={"message": "Saved."})
        elif is_notification_count(method, path):
            route.fulfill(json=notification_count_payload())
        elif method == "GET" and path == "/api/approvals":
            route.fulfill(json={"approvals": [], "total_count": 0, "total_pages": 1})
        elif method == "GET" and path == "/api/safety/warnings/pending":
            self.pending_reads += 1
            route.fulfill(json={"warnings": self.warnings, "count": len(self.warnings)})
        elif method == "POST" and path.startswith("/api/safety/warnings/") and path.endswith("/acknowledge"):
            warning_id = path.removeprefix("/api/safety/warnings/").removesuffix("/acknowledge")
            body = request.post_data_json or {}
            self.acknowledgments.append(warning_id)
            self.acknowledgment_bodies.append(body)
            if self.fail_next_acknowledgment:
                self.fail_next_acknowledgment = False
                route.fulfill(status=500, json={"error": "Your acknowledgment could not be saved. Try again."})
                return
            current = next((item for item in self.warnings if item["id"] == warning_id), None)
            if current and body.get("issued_at") and body["issued_at"] != current["issued_at"]:
                route.fulfill(status=409, json={
                    "error": "A newer warning replaced this one. Read the newer warning, then acknowledge it.",
                    "code": "safety_warning_replaced",
                })
                return
            self.warnings = [item for item in self.warnings if item["id"] != warning_id]
            route.fulfill(json={"success": True, "already_acknowledged": False, "warning": {"id": warning_id}})
        else:
            self.unexpected_requests.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, path, *, width=1440, height=900):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.preferences = {"darkModeEnabled": False, "v2RailCollapsed": width < 1024}
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}{path}", wait_until="networkidle")

    def assert_clean(self):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors


@pytest.fixture
def restriction_ui(page):
    fixture = RestrictionFixture(page)
    yield fixture
    fixture.assert_clean()


def test_restricted_user_lands_on_the_access_restricted_page(restriction_ui):
    restriction_ui.restricted_bootstrap = True
    restriction_ui.open("/v2/approvals")
    page = restriction_ui.page

    expect(page).to_have_url(f"{ORIGIN}/v2/access-restricted")
    panel = page.get_by_test_id("v2-access-restricted")
    expect(panel).to_be_visible()
    expect(page.get_by_role("heading", name="Account Suspension Notice")).to_be_visible()
    message = page.get_by_test_id("v2-access-restricted-message")
    expect(message).to_contain_text("<b>Not bold</b>")
    expect(message.locator("b")).to_have_count(0)
    expect(page.get_by_text("Could not start SimpleChat")).to_have_count(0)
    expect(page.get_by_text("Your session has expired")).to_have_count(0)

    until = page.get_by_test_id("v2-access-restricted-until").locator("time")
    expect(until).to_have_attribute("datetime", "2031-03-04T15:30:00+00:00")
    expected_local = page.evaluate(
        "new Date('2031-03-04T15:30:00+00:00').toLocaleString(undefined, { dateStyle: 'full', timeStyle: 'short' })"
    )
    expect(until).to_have_text(expected_local)
    expect(page.get_by_test_id("v2-access-restricted-reference")).to_have_text("safety-log-42")
    expect(page.get_by_test_id("v2-access-restricted-signout")).to_have_attribute("href", "/logout")
    assert page.title() == "Access restricted - SimpleChat"


def test_block_and_restored_account_read_differently(restriction_ui):
    restriction_ui.restriction_payload = {
        "restricted": True,
        "restriction": {"kind": "blocked", "until": None, "title": "Account Access Blocked",
                        "message": "Blocked for repeated violations.", "reference_id": None},
        "branding": {"app_title": "SimpleChat", "hide_app_title": False, "show_logo": False},
    }
    restriction_ui.open("/v2/access-restricted", width=390, height=844)
    page = restriction_ui.page
    expect(page.get_by_role("heading", name="Account Access Blocked")).to_be_visible()
    expect(page.get_by_test_id("v2-access-restricted-until")).to_contain_text("No automatic restore date")
    expect(page.get_by_test_id("v2-access-restricted-reference")).to_have_count(0)
    expect(page.get_by_test_id("v2-access-restricted-signout")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    restriction_ui.restriction_payload = {"restricted": False, "branding": {"app_title": "SimpleChat"}}
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("heading", name="Your access is available")).to_be_visible()
    expect(page.get_by_test_id("v2-access-restricted-continue")).to_have_attribute("href", "/v2")


def test_safety_warning_must_be_acknowledged(restriction_ui):
    restriction_ui.warnings = copy.deepcopy(WARNINGS)
    restriction_ui.open("/v2/approvals")
    page = restriction_ui.page

    dialog = page.get_by_role("dialog", name="A warning from your administrators")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("heading", name="Safety Violation Warning")).to_be_visible()
    expect(dialog).to_contain_text("Warning 1 of 2.")
    message = dialog.get_by_test_id("v2-safety-warning-message")
    expect(message).to_contain_text("<i>Plain text</i>")
    expect(message.locator("i")).to_have_count(0)
    expect(dialog).to_contain_text("Hate (severity 4)")
    expect(dialog.get_by_role("button", name="Close")).to_have_count(0)

    page.keyboard.press("Escape")
    expect(dialog).to_be_visible()

    dialog.get_by_role("button", name="I understand").click()
    expect(dialog.get_by_role("heading", name="Second warning")).to_be_visible()
    expect(dialog).not_to_contain_text("Warning 1 of")
    dialog.get_by_role("button", name="I understand").click()
    expect(page.get_by_role("dialog", name="A warning from your administrators")).to_have_count(0)
    assert restriction_ui.acknowledgments == ["log-1", "log-2"]
    # Each acknowledgment names when the warning read was sent.
    assert restriction_ui.acknowledgment_bodies == [
        {"issued_at": WARNINGS[0]["issued_at"]},
        {"issued_at": WARNINGS[1]["issued_at"]},
    ]


def test_a_warning_replaced_while_on_screen_shows_the_newer_one(restriction_ui):
    restriction_ui.warnings = copy.deepcopy(WARNINGS[:1])
    restriction_ui.open("/v2/approvals")
    page = restriction_ui.page

    dialog = page.get_by_role("dialog", name="A warning from your administrators")
    expect(dialog.get_by_role("heading", name="Safety Violation Warning")).to_be_visible()

    # While it is on screen, a reviewer warns about the same violation again.
    restriction_ui.warnings = [{
        **copy.deepcopy(WARNINGS[0]),
        "title": "Updated warning",
        "message": "Please read this newer warning.",
        "issued_at": "2026-10-08T09:00:00+00:00",
    }]
    dialog.get_by_role("button", name="I understand").click()
    expect(dialog.get_by_role("heading", name="Updated warning")).to_be_visible()
    expect(dialog.get_by_test_id("v2-safety-warning-message")).to_have_text("Please read this newer warning.")
    expect(dialog.get_by_role("alert")).to_have_count(0)
    assert restriction_ui.pending_reads == 2

    dialog.get_by_role("button", name="I understand").click()
    expect(page.get_by_role("dialog", name="A warning from your administrators")).to_have_count(0)
    assert restriction_ui.acknowledgment_bodies == [
        {"issued_at": "2026-10-07T12:00:00+00:00"},
        {"issued_at": "2026-10-08T09:00:00+00:00"},
    ]


def test_failed_acknowledgment_keeps_the_warning(restriction_ui):
    restriction_ui.warnings = copy.deepcopy(WARNINGS[:1])
    restriction_ui.fail_next_acknowledgment = True
    restriction_ui.open("/v2/approvals")
    page = restriction_ui.page

    dialog = page.get_by_role("dialog", name="A warning from your administrators")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="I understand").click()
    expect(dialog.get_by_role("alert")).to_have_text("Your acknowledgment could not be saved. Try again.")
    expect(dialog).to_be_visible()

    dialog.get_by_role("button", name="I understand").click()
    expect(page.get_by_role("dialog", name="A warning from your administrators")).to_have_count(0)
    assert restriction_ui.acknowledgments == ["log-1", "log-1"]


def test_warnings_are_read_only_when_bootstrap_counts_some(restriction_ui):
    restriction_ui.open("/v2/approvals")
    page = restriction_ui.page
    expect(page.get_by_test_id("v2-approvals-page")).to_be_visible()
    expect(page.get_by_role("dialog", name="A warning from your administrators")).to_have_count(0)
    assert restriction_ui.pending_reads == 0

    # A warning sent while the tab was away shows when the reader comes back to it.
    restriction_ui.warnings = copy.deepcopy(WARNINGS[1:])
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    dialog = page.get_by_role("dialog", name="A warning from your administrators")
    expect(dialog.get_by_role("heading", name="Second warning")).to_be_visible()
    assert restriction_ui.pending_reads == 1
