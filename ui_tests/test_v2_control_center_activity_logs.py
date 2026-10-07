# test_v2_control_center_activity_logs.py
"""
Browser coverage for V2 Activity Logs.
Version: 0.261.285
Implemented in: 0.261.284

Uses local built assets and intercepted APIs, with the shared Azure Playwright
connection helper when a workspace is configured. Covers desktop and mobile.
"""

import sys
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from test_v2_control_center_users import ORIGIN, UsersFixture


RECORD = {
    "id": "record-1", "timestamp": "2026-10-01T12:00:00Z", "activity_type": "user_login",
    "user_id": "user-1", "workspace_type": "group", "workspace_context": {"group_id": "group-1"},
    "public_workspace_id": "workspace-1", "approval_id": "approval-1",
    "description": "<img src=x onerror=alert(1)>",
}


class ActivityFixture(UsersFixture):
    def __init__(self, page):
        self.fail = False
        self.empty = False
        self.allowed = True
        self.console_errors = []
        super().__init__(page)
        page.on("pageerror", lambda error: self.console_errors.append(str(error)))

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        path = parsed.path
        if path.startswith("/api/v2/control-center/activity-logs"):
            self.requests.append((route.request.method, path, parsed.query))
            if self.fail:
                route.fulfill(status=500, json={"error": "Unable to load activity logs. Retry."})
            elif path.endswith("/summary"):
                route.fulfill(json={
                    "facets": [{"activity_type": "user_login", "count": 5000}],
                    "histogram": [{"date": "2026-10-01", "count": 5000}],
                    "sample_size": 5000, "sample_limit": 5000, "truncated": True, "bucket_days": 1,
                })
            elif path.endswith("/export.csv"):
                route.fulfill(content_type="text/csv", body="timestamp,id,user_id\n2026-10-01,record-1,user-1\n",
                              headers={"Content-Disposition": 'attachment; filename="activity_logs.csv"'})
            else:
                second = "cursor" in parse_qs(parsed.query)
                record = {**RECORD, "id": "record-2"} if second else RECORD
                route.fulfill(json={"items": [] if self.empty else [record], "next_cursor": None if second else "test-cursor",
                                    "snapshot": "2026-10-07T12:00:00"})
        elif path == "/api/v2/bootstrap" and not self.allowed:
            route.fulfill(json={
                "version": "0.261.284", "user": {"id": "reader", "display_name": "Reader", "is_admin": False, "roles": ["ControlCenterDashboardReader"]},
                "branding": {"app_title": "SimpleChat", "show_logo": False}, "features": {},
                "control_center": {"can_view_dashboard": True, "can_manage_users": False, "can_manage_groups": False,
                                   "can_manage_workspaces": False, "can_view_activity_logs": False, "can_run_maintenance": False},
                "catalogs": {"models": [], "agents": [], "prompts": []}, "scope": {"groups": [], "public_workspaces": []},
                "navigation": {"custom_pages": {"enabled": False, "items": []}, "external_links": {"enabled": False, "items": []}},
                "workspace": {"sections": {}}, "admin_nav": [], "notices": {"ai": {}, "web_search": {}}, "settings": {},
            })
        else:
            super()._route(route)

    def open(self, query="?date=2026-10-01&activity_type=user_login&workspace_type=group&workspace_id=group-1", mobile=False):
        self.page.set_viewport_size({"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/activity-logs{query}", wait_until="networkidle")

    def assert_clean(self):
        super().assert_clean()
        assert not self.console_errors, self.console_errors


@pytest.fixture
def activity_ui(page):
    fixture = ActivityFixture(page)
    yield fixture
    fixture.assert_clean()


pytestmark = pytest.mark.ui


@pytest.mark.parametrize("mobile", [False, True])
def test_filters_paging_details_and_safe_links(activity_ui, mobile):
    activity_ui.open(mobile=mobile)
    page = activity_ui.page
    expect(page.get_by_role("heading", name="Activity Logs", exact=True)).to_be_visible()
    expect(page.get_by_label("Start date (UTC)")).to_have_value("2026-10-01")
    expect(page.get_by_text("Sampled: newest 5,000 matching records.", exact=False)).to_be_visible()
    page.get_by_role("button", name="Inspect activity record-1").click()
    drawer = page.get_by_role("dialog", name="Activity details")
    expect(drawer).to_be_visible()
    expect(drawer.locator("pre")).to_contain_text("<img src=x onerror=alert(1)>")
    expect(page.locator("img[src=x]")).to_have_count(0)
    expect(drawer.get_by_role("link", name="View user")).to_have_attribute("href", "/v2/control-center/users?user_id=user-1")
    expect(drawer.get_by_role("link", name="View group")).to_have_attribute("href", "/v2/control-center/groups?id=group-1")
    expect(drawer.get_by_role("link", name="View workspace")).to_have_attribute("href", "/v2/control-center/public-workspaces?id=workspace-1")
    expect(drawer.get_by_role("link", name="View approval")).to_have_attribute("href", "/v2/approvals/all/approval-1?group_id=group-1")
    page.keyboard.press("Escape")
    expect(drawer).not_to_be_visible()
    expect(page.get_by_role("button", name="Inspect activity record-1")).to_be_focused()
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.get_by_role("button", name="Inspect activity record-2")).to_be_visible()
    page.get_by_role("button", name="Previous", exact=True).click()
    expect(page.get_by_role("button", name="Inspect activity record-1")).to_be_visible()
    page.get_by_label("Search activity").fill("file")
    page.get_by_role("button", name="Apply filters").click()
    expect(page).to_have_url(re.compile("search=file"))
    expect(page.get_by_role("button", name="Inspect activity record-1")).to_be_visible()
    latest = [parse_qs(query) for _, path, query in activity_ui.requests if path.endswith("activity-logs")][-1]
    assert latest["search"] == ["file"] and "cursor" not in latest
    page.get_by_label("Density").select_option("compact")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_saved_views_filters_export_and_histogram(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    page.get_by_label("View name", exact=True).fill("Group logins")
    page.get_by_role("button", name="Save current filters").click()
    page.get_by_role("button", name="Clear filters").click()
    page.get_by_label("Saved views", exact=True).select_option("Group logins")
    expect(page.get_by_label("Workspace ID", exact=True)).to_have_value("group-1")
    page.reload(wait_until="networkidle")
    expect(page.get_by_label("Saved views").locator("option")).to_have_count(2)
    page.get_by_role("button", name="token usage", exact=True).click()
    expect(page).to_have_url(re.compile("activity_type=token_usage"))
    with page.expect_download() as download:
        page.get_by_role("button", name="Export CSV", exact=True).click()
    assert download.value.suggested_filename == "activity_logs.csv"
    export_query = [parse_qs(query) for _, path, query in activity_ui.requests if path.endswith("export.csv")][-1]
    assert export_query["activity_type"] == ["user_login", "token_usage"]
    page.get_by_text("Histogram data and date drill-through", exact=True).click()
    page.get_by_role("button", name="2026-10-01", exact=True).click()
    expect(page.get_by_label("End date (UTC)")).to_have_value("2026-10-01")
    page.get_by_role("button", name="Recent logins", exact=True).click()
    expect(page).to_have_url(re.compile("activity_type=user_login"))
    expect(page.get_by_label("Workspace ID", exact=True)).to_have_value("")


def test_empty_error_retry_and_permission_gating(activity_ui):
    activity_ui.empty = True
    activity_ui.open()
    page = activity_ui.page
    expect(page.get_by_text("No activity matches these filters.", exact=False)).to_be_visible()
    activity_ui.empty = False
    activity_ui.fail = True
    page.get_by_role("button", name="Refresh", exact=True).click()
    expect(page.get_by_role("button", name="Retry", exact=True)).to_be_visible()
    activity_ui.fail = False
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Inspect activity record-1")).to_be_visible()
    activity_ui.allowed = False
    activity_ui.requests.clear()
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("heading", name="Access unavailable")).to_be_visible()
    assert not activity_ui.requests
