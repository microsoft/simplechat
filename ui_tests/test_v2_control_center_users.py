#!/usr/bin/env python3
# test_v2_control_center_users.py
"""
Browser coverage for the V2 Control Center Users section.
Version: 0.261.282
Implemented in: 0.261.280

Validates filtered users, cross-page selection, detail tabs, reconciled access
updates, approval-gated document deletion and server-side CSV export.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_notification_stubs import is_notification_count, notification_count_payload


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC / "v2" / "index.html"
ORIGIN = "http://simplechat.test"
USER_ID = "user-123"


def user_row():
    return {
        "id": USER_ID,
        "email": "ada@example.test",
        "display_name": "Ada Admin",
        "access": {"status": "deny", "expires_at": None},
        "file_uploads": {"status": "allow", "expires_at": None},
        "last_login": "2026-10-06T10:00:00Z",
        "total_logins": 4,
        "conversations": 9,
        "documents": 2,
        "tokens": 120,
        "metrics_calculated_at": "2026-10-07T00:00:00Z",
    }


def user_detail():
    row = user_row()
    return {
        "user": {key: row[key] for key in ("id", "email", "display_name", "access", "file_uploads")},
        "usage": {
            "last_login": row["last_login"],
            "total_logins": 4,
            "conversations": 9,
            "documents": 2,
            "tokens": 120,
            "metrics_calculated_at": row["metrics_calculated_at"],
        },
        "activity": [{
            "id": "activity-1",
            "activity_type": "user_login",
            "timestamp": "2026-10-06T10:00:00Z",
            "resource_name": None,
            "workspace_type": None,
            "token_type": None,
            "status": None,
            "usage": None,
        }],
        "memberships": {
            "groups": [{"id": "group-1", "name": "Research", "role": "Owner", "owned": True}],
            "public_workspaces": [],
        },
    }


class UsersFixture:
    def __init__(self, page: Page):
        self.page = page
        self.requests = []
        self.bulk_payloads = []
        self.patch_requests = []
        self.unexpected = []
        page.route("**/*", self._route)

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path.startswith("/v2"):
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
        elif request.method == "GET" and path.startswith("/static/"):
            asset = (STATIC / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC.resolve()) and asset.is_file():
                route.fulfill(path=str(asset))
            else:
                self.unexpected.append(path)
                route.fulfill(status=404, body="Fixture asset not found")
        elif path == "/api/v2/bootstrap" and request.method == "GET":
            route.fulfill(json={
                "version": "0.261.280",
                "user": {"id": "admin-1", "display_name": "Admin", "is_admin": True, "roles": ["ControlCenterAdmin"]},
                "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
                "features": {},
                "control_center": {
                    "can_view_dashboard": True,
                    "can_manage_users": True,
                    "can_manage_groups": True,
                    "can_manage_workspaces": True,
                    "can_view_activity_logs": True,
                    "can_run_maintenance": True,
                },
                "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
                "scope": {"groups": [], "public_workspaces": []},
                "navigation": {
                    "custom_pages": {"enabled": False, "items": []},
                    "external_links": {"enabled": False, "items": []},
                },
                "workspace": {"sections": {}},
                "admin_nav": [],
                "notices": {"ai": {}, "web_search": {}},
                "settings": {},
            })
        elif path == "/api/user/settings" and request.method == "GET":
            route.fulfill(json={"settings": {}})
        elif is_notification_count(request.method, path):
            route.fulfill(json=notification_count_payload())
        elif path == "/api/v2/control-center/users" and request.method == "GET":
            self.requests.append((request.method, path, parsed.query))
            route.fulfill(json={
                "users": [user_row()],
                "pagination": {"page": 1, "per_page": 25, "total_items": 2, "total_pages": 1},
                "metrics_freshness": {
                    "oldest_calculated_at": "2026-10-07T00:00:00Z",
                    "newest_calculated_at": "2026-10-07T00:00:00Z",
                    "missing_count": 0,
                    "source": "user metrics refresh cache",
                },
            })
        elif path == f"/api/v2/control-center/users/{USER_ID}" and request.method == "GET":
            self.requests.append((request.method, path, parsed.query))
            route.fulfill(json=user_detail())
        elif path == "/api/v2/control-center/users/bulk-action" and request.method == "POST":
            payload = json.loads(request.post_data or "{}")
            self.bulk_payloads.append(payload)
            route.fulfill(json={"success_count": 2, "failed_count": 0, "failed_user_ids": []})
        elif path.startswith("/api/admin/control-center/users/") and request.method == "PATCH":
            self.patch_requests.append((path, json.loads(request.post_data or "{}")))
            route.fulfill(json={"message": "Updated."})
        elif path.startswith("/api/admin/control-center/users/") and request.method == "POST":
            route.fulfill(json={"success": True, "approval_id": "approval-42"})
        elif path == "/api/v2/control-center/users/export.csv" and request.method == "GET":
            self.requests.append((request.method, path, parsed.query))
            route.fulfill(status=200, content_type="text/csv",
                          headers={"Content-Disposition": 'attachment; filename="control-center-users.csv"'},
                          body="id,email\nuser-123,ada@example.test\n")
        else:
            self.unexpected.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/users", wait_until="networkidle")

    def assert_clean(self):
        assert not self.unexpected, self.unexpected


@pytest.fixture
def users_ui(page):
    fixture = UsersFixture(page)
    yield fixture
    fixture.assert_clean()


pytestmark = pytest.mark.ui


def test_users_filters_cross_page_selection_and_bulk_action(users_ui):
    users_ui.open()
    page = users_ui.page

    expect(page.get_by_role("heading", name="Users")).to_be_visible()
    expect(page.get_by_text("Ada Admin", exact=True)).to_be_visible()
    page.get_by_label("Filter by access status").select_option("deny")
    expect(page).to_have_url(f"{ORIGIN}/v2/control-center/users?access_status=deny")
    assert any("access_status=deny" in query for _, path, query in users_ui.requests if path.endswith("/users"))

    page.get_by_label("Select all rows on this page").check()
    page.get_by_role("button", name="Select all 2 matching records").click()
    expect(page.get_by_text("All 2 matching users selected")).to_be_visible()
    page.get_by_role("button", name="Apply access").click()
    expect(page.get_by_text("2 users updated.")).to_be_visible()
    assert users_ui.bulk_payloads[-1]["filter"]["access_status"] == "deny"
    assert users_ui.bulk_payloads[-1]["exclude_ids"] == []


def test_user_detail_activity_reconciled_update_and_approval(users_ui):
    users_ui.open()
    page = users_ui.page

    page.get_by_role("button", name="Open details for Ada Admin").click()
    expect(page.get_by_role("dialog", name="Ada Admin")).to_be_visible()
    page.get_by_role("tab", name="Activity").click()
    expect(page.get_by_text("user login", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="View all in Activity Logs")).to_have_attribute(
        "href", "/v2/control-center/activity-logs?user_id=user-123",
    )

    page.get_by_role("tab", name="Overview").click()
    page.get_by_role("button", name="Deny").first.click()
    assert any(path.endswith("/access") for path, _ in users_ui.patch_requests)

    page.get_by_role("button", name="Request deletion of all documents").click()
    page.get_by_label("Reason (required)").fill("Requested account cleanup")
    page.get_by_role("button", name="Submit approval request").click()
    expect(page.get_by_text("Document deletion approval approval-42 was submitted")).to_be_visible()
    expect(page.get_by_role("link", name="View approval requests")).to_have_attribute(
        "href", "/v2/approvals/all/approval-42",
    )


def test_users_export_uses_server_filter_endpoint(users_ui):
    users_ui.open()
    page = users_ui.page
    page.get_by_label("Filter by file-upload status").select_option("deny")
    expect(page.get_by_role("link", name="Export CSV")).to_have_attribute(
        "href", "/api/v2/control-center/users/export.csv?upload_status=deny",
    )
    with page.expect_download():
        page.get_by_role("link", name="Export CSV").click()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-m", "ui"]))
