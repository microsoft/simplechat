# test_v2_approvals_dashboard.py
"""
Browser coverage for the V2 Approvals dashboard and Safety remediation category.
Version: 0.261.298
Implemented in: 0.261.298

Serve the real built SPA through Playwright request interception with a closed API
boundary. Check that All requests stays the landing category while a Dashboard category
summarizes what the caller can see; that a dashboard figure opens the request list filtered
through its address; that Safety remediation lists warn, suspend and block requests while
Group requests no longer does; and that the category is offered only to the roles that
raise or decide those requests. Unexpected requests fail.
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

APPROVALS = [
    {
        "id": "appr-group-1", "group_id": "group-1", "group_name": "Finance", "request_type": "delete_documents",
        "status": "pending", "requester_name": "Riley Owner", "requester_email": "riley@contoso.test",
        "reason": "Quarterly cleanup", "created_at": "2026-10-01T12:00:00+00:00", "can_approve": True, "can_deny": True,
    },
    {
        "id": "appr-suspend-1", "group_id": "user-7", "group_name": "Sam Sender", "request_type": "suspend_user",
        "status": "pending", "requester_name": "Sky Safety", "requester_email": "sky@contoso.test",
        "reason": "Repeated violations", "created_at": "2026-10-02T12:00:00+00:00", "can_approve": True, "can_deny": True,
    },
]

STATS = {
    "window": {"days": 30},
    "waiting_on_me": 2,
    "my_pending_requests": 0,
    "expiring_within_24h": 1,
    "pending_visible": 2,
    "decided_in_window": {"approved": 3, "denied": 1, "executed": 2, "failed": 0, "expired": 1},
    "pending_by_type": [{"request_type": "delete_documents", "count": 1}, {"request_type": "suspend_user", "count": 1}],
    "oldest_actionable": [{"id": "appr-group-1", "group_id": "group-1", "request_type": "delete_documents",
                           "group_name": "Finance", "created_at": "2026-10-01T12:00:00+00:00",
                           "expires_at": "2026-10-04T12:00:00+00:00"}],
}


class ApprovalsDashboardFixture:
    def __init__(self, page: Page, roles):
        self.page = page
        self.roles = list(roles)
        self.approvals = copy.deepcopy(APPROVALS)
        self.stats_requests = []
        self.errors = []
        self.unexpected_requests = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self._route)

    def _bootstrap(self):
        return {
            "version": "0.261.298",
            "user": {"id": "user-1", "display_name": "Test User", "email": "test.user@contoso.test",
                     "is_admin": "Admin" in self.roles, "roles": self.roles},
            "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
            "features": {},
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {"custom_pages": {"enabled": False, "items": []}, "external_links": {"enabled": False, "items": []}},
            "workspace": {"sections": {}},
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
            route.fulfill(json=self._bootstrap())
        elif path == "/api/user/settings":
            if method == "GET":
                route.fulfill(json={"settings": self.preferences})
            else:
                self.preferences.update(request.post_data_json["settings"])
                route.fulfill(json={"message": "Saved."})
        elif is_notification_count(method, path):
            route.fulfill(json=notification_count_payload())
        elif method == "GET" and path == "/api/approvals/stats":
            self.stats_requests.append(parse_qs(parsed.query))
            route.fulfill(json=STATS)
        elif method == "GET" and path == "/api/approvals":
            status = parse_qs(parsed.query).get("status", ["pending"])[0]
            items = [item for item in self.approvals if status == "all" or item["status"] == status]
            route.fulfill(json={"approvals": items, "total_count": len(items), "total_pages": 1})
        else:
            self.unexpected_requests.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, path):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.preferences = {"darkModeEnabled": False, "v2RailCollapsed": False}
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}{path}", wait_until="networkidle")

    def assert_clean(self):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors


def test_dashboard_summarizes_and_opens_the_filtered_list(page):
    fixture = ApprovalsDashboardFixture(page, roles=["User", "Admin"])
    fixture.open("/v2/approvals")
    # All requests stays where the page lands; the dashboard is one choice away.
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/all")
    assert not fixture.stats_requests, "the dashboard was loaded before it was opened"
    page.get_by_test_id("v2-approvals-category-dashboard").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/dashboard")
    waiting = page.get_by_test_id("v2-approvals-dashboard-waiting")
    expect(waiting).to_contain_text("2")
    expect(page.get_by_test_id("v2-approvals-dashboard-types")).to_contain_text("Suspend User")
    expect(page.get_by_test_id("v2-approvals-dashboard-oldest")).to_contain_text("Finance")
    assert fixture.stats_requests[-1] == {"days": ["30"]}

    with page.expect_request(lambda request: "/api/approvals/stats?days=7" in request.url):
        page.get_by_label("Period").select_option("7")
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/dashboard?days=7")
    assert fixture.stats_requests[-1] == {"days": ["7"]}

    waiting.click()
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/all?show=mine")
    expect(page.get_by_test_id("v2-approval-row-appr-group-1")).to_be_visible()
    fixture.assert_clean()


def test_safety_remediation_has_its_own_category(page):
    fixture = ApprovalsDashboardFixture(page, roles=["User", "SafetyViolationAdmin"])
    fixture.open("/v2/approvals/safety-remediation")
    expect(page.get_by_test_id("v2-approvals-category-safety-remediation")).to_be_visible()
    expect(page.get_by_test_id("v2-approval-row-appr-suspend-1")).to_be_visible()
    expect(page.get_by_test_id("v2-approval-row-appr-group-1")).to_have_count(0)

    page.get_by_test_id("v2-approvals-category-group").click()
    expect(page.get_by_test_id("v2-approval-row-appr-group-1")).to_be_visible()
    expect(page.get_by_test_id("v2-approval-row-appr-suspend-1")).to_have_count(0)
    fixture.assert_clean()


def test_safety_remediation_is_hidden_from_other_roles(page):
    fixture = ApprovalsDashboardFixture(page, roles=["User"])
    fixture.open("/v2/approvals")
    expect(page.get_by_test_id("v2-approvals-category-all")).to_be_visible()
    expect(page.get_by_test_id("v2-approvals-category-safety-remediation")).to_have_count(0)
    # An address for it leads back to All requests.
    page.goto(f"{ORIGIN}/v2/approvals/safety-remediation", wait_until="networkidle")
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/all")
    fixture.assert_clean()
