# test_v2_control_center_groups.py
"""
Browser workflows for V2 Control Center Groups.
Version: 0.261.282
Implemented in: 0.261.282

Uses the built local bundle with intercepted APIs. Shared Azure Playwright
connection support uses DefaultAzureCredential when a workspace is configured.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from test_v2_control_center_users import ORIGIN, UsersFixture


GROUP_ID = "group-1"
GROUP_NAME = "Research <img src=x onerror=alert(1)>"


def group_row():
    return {
        "id": GROUP_ID, "name": GROUP_NAME, "description": "Research documents",
        "owner": {"id": "owner-1", "display_name": "Olive Owner", "email": "owner@example.test"},
        "status": "active", "members": 2, "documents": 3, "tokens": 120,
        "created_at": "2026-09-01T00:00:00Z", "last_activity": "2026-10-06T00:00:00Z",
        "metrics_calculated_at": None,
    }


class GroupsFixture(UsersFixture):
    def __init__(self, page):
        self.group = group_row()
        self.member_manager = True
        self.members = [
            {"id": "owner-1", "display_name": "Olive Owner", "email": "owner@example.test", "role": "Owner"},
            {"id": "member-1", "display_name": "Max Member", "email": "max@example.test", "role": "User"},
        ]
        self.mutations = []
        self.status_history = []
        self.retention = {"conversation_retention_days": "default", "document_retention_days": 30}
        self.fail_bulk = False
        self.console_errors = []
        super().__init__(page)
        page.on("pageerror", lambda error: self.console_errors.append(str(error)))

    def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        method = request.method
        if path == "/api/v2/control-center/groups" and method == "GET":
            self.requests.append((method, path, parsed.query))
            route.fulfill(json={
                "groups": [self.group],
                "pagination": {"page": 1, "total_items": 2},
                "metrics_freshness": {"calculated_at": "2026-10-07T00:00:00Z", "ttl_seconds": 90},
            })
        elif path == f"/api/v2/control-center/groups/{GROUP_ID}" and method == "GET":
            route.fulfill(json={
                "group": self.group, "members": self.members, "status_history": self.status_history,
                "retention": {**self.retention, "enabled": True, "can_edit": self.member_manager},
                "permissions": {"can_edit_members": self.member_manager, "current_role": "Admin" if self.member_manager else None},
                "documents_summary": {"count": 3, "cached_metrics": {"total_documents": 3}, "metrics_calculated_at": None},
                "tokens": 120, "metrics_calculated_at": "2026-10-07T00:00:00Z",
                "activity": [{"id": "activity-1", "timestamp": "2026-10-06T00:00:00Z",
                              "activity_type": "group_status_change", "description": "<script>alert(1)</script>"}],
            })
        elif path == "/api/v2/control-center/groups/bulk-status" and method == "POST":
            payload = json.loads(request.post_data)
            self.bulk_payloads.append(payload)
            if self.fail_bulk:
                route.fulfill(json={"success_count": 1, "failed_count": 1, "failed_groups": [{"id": "missing", "error": "Group not found."}]})
            else:
                self.group["status"] = payload["status"]
                route.fulfill(json={"success_count": 2, "failed_count": 0, "failed_groups": []})
        elif path == f"/api/v2/control-center/groups/{GROUP_ID}/status" and method == "PUT":
            payload = json.loads(request.post_data)
            self.mutations.append((method, path, payload))
            self.status_history.append({
                "old_status": self.group["status"], "new_status": payload["status"],
                "changed_by_email": "admin@example.test", "changed_at": "2026-10-07T00:00:00Z", "reason": payload["reason"],
            })
            self.group["status"] = payload["status"]
            route.fulfill(json={"new_status": payload["status"]})
        elif path.startswith(f"/api/admin/control-center/groups/{GROUP_ID}") and method in ("POST", "DELETE"):
            payload = json.loads(request.post_data or "{}")
            self.mutations.append((method, path, payload))
            if path.endswith("/add-member"):
                self.members.append({"id": payload["userId"], "display_name": payload["displayName"], "email": payload["email"], "role": "User"})
                route.fulfill(json={"skipped": False})
            else:
                route.fulfill(json={"approval_id": "approval-42", "status": "pending"})
        elif path.startswith(f"/api/groups/{GROUP_ID}/members/") and method in ("DELETE", "PATCH"):
            member_id = path.rsplit("/", 1)[1]
            payload = json.loads(request.post_data or "{}")
            self.mutations.append((method, path, payload))
            if method == "DELETE":
                self.members = [member for member in self.members if member["id"] != member_id]
            else:
                for member in self.members:
                    if member["id"] == member_id:
                        member["role"] = payload["role"]
            route.fulfill(json={"success": True})
        elif path == f"/api/retention-policy/group/{GROUP_ID}" and method == "POST":
            self.retention = json.loads(request.post_data)
            self.mutations.append((method, path, self.retention))
            route.fulfill(json={"success": True})
        elif path == "/api/userSearch" and method == "GET":
            route.fulfill(json=[{"id": "new-1", "displayName": "New Member", "mail": "new@example.test", "userPrincipalName": "new@example.test"}])
        elif path == "/api/v2/control-center/groups/export.csv":
            route.fulfill(content_type="text/csv", body="id,name\ngroup-1,Research\n",
                          headers={"Content-Disposition": 'attachment; filename="groups.csv"'})
        else:
            super()._route(route)

    def open(self, query="", mobile=False):
        self.page.set_viewport_size({"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/groups{query}", wait_until="networkidle")

    def drawer(self):
        self.page.get_by_role("button", name=f"Open details for {GROUP_NAME}").click()
        expect(self.page.get_by_role("dialog", name=GROUP_NAME)).to_be_visible()

    def assert_clean(self):
        super().assert_clean()
        assert not self.console_errors, self.console_errors


@pytest.fixture
def groups_ui(page):
    fixture = GroupsFixture(page)
    yield fixture
    fixture.assert_clean()


pytestmark = pytest.mark.ui


def test_filters_cross_page_bulk_reason_and_export(groups_ui):
    groups_ui.open()
    page = groups_ui.page
    page.get_by_label("Filter by group status").select_option("active")
    expect(page).to_have_url(f"{ORIGIN}/v2/control-center/groups?status=active")
    expect(page.get_by_role("link", name="Export CSV")).to_have_attribute(
        "href", "/api/v2/control-center/groups/export.csv?status=active",
    )
    page.get_by_label("Select all rows on this page").check()
    page.get_by_role("button", name="Select all 2 matching records").click()
    page.get_by_role("button", name="Apply bulk status").click()
    expect(page.get_by_role("button", name="Apply bulk status").last).to_be_disabled()
    page.get_by_label("Reason (required)").fill("Governance review")
    page.get_by_role("button", name="Apply bulk status").last.click()
    expect(page.get_by_text("2 groups updated.")).to_be_visible()
    assert groups_ui.bulk_payloads[-1] == {
        "filter": {"status": "active"}, "exclude_ids": [], "status": "locked", "reason": "Governance review",
    }
    page.get_by_role("button", name="Refresh groups").click()
    expect(page.get_by_role("button", name="Refresh groups")).to_be_enabled()
    assert "force_refresh=1" in groups_ui.requests[-1][2]
    page.get_by_label("Filter by group status").select_option("locked")
    expect(page.get_by_role("button", name="Refresh groups")).to_be_enabled()
    assert "force_refresh" not in groups_ui.requests[-1][2]


def test_partial_bulk_failure_survives_reload(groups_ui):
    groups_ui.fail_bulk = True
    groups_ui.open()
    page = groups_ui.page
    page.get_by_label("Select all rows on this page").check()
    page.get_by_role("button", name="Apply bulk status").click()
    page.get_by_label("Reason (required)").fill("Review")
    page.get_by_role("button", name="Apply bulk status").last.click()
    expect(page.get_by_text("1 succeeded; 1 failed. missing: Group not found.")).to_be_visible()


@pytest.mark.parametrize("mobile", [False, True])
def test_detail_tabs_status_history_raw_json_and_approval(groups_ui, mobile):
    groups_ui.open(query="?id=group-1", mobile=mobile)
    page = groups_ui.page
    expect(page.get_by_role("dialog", name=GROUP_NAME)).to_be_visible()
    expect(page.locator("img[src=x]")).to_have_count(0)
    page.get_by_role("tab", name="Status", exact=True).click()
    page.get_by_label("Group status", exact=True).select_option("locked")
    page.get_by_role("button", name="Change status").click()
    page.get_by_label("Reason (required)").fill("Review documents")
    page.get_by_role("button", name="Apply status").click()
    expect(page.get_by_text("Review documents", exact=True)).to_be_visible()
    page.get_by_role("tab", name="Activity", exact=True).click()
    expect(page.get_by_text("<script>alert(1)</script>", exact=True)).to_be_visible()
    page.get_by_role("button", name="Raw JSON").click()
    expect(page.locator("pre")).to_contain_text("group_status_change")
    expect(page.get_by_role("link", name="View in Activity Logs")).to_have_attribute(
        "href", "/v2/control-center/activity-logs?workspace_type=group&workspace_id=group-1&group_id=group-1",
    )
    page.get_by_role("tab", name="Documents", exact=True).click()
    page.get_by_role("button", name="Request deletion of all documents").click()
    page.get_by_label("Reason (required)").fill("Approved cleanup process")
    page.get_by_role("button", name="Submit approval request").click()
    expect(page.get_by_text("Request approval-42 submitted for approval.", exact=False)).to_be_visible()
    assert groups_ui.mutations[-1][1].endswith("/delete-documents")
    expect(page.get_by_role("link", name="View approval requests")).to_have_attribute(
        "href", "/v2/approvals/all/approval-42?group_id=group-1",
    )


def test_members_add_csv_role_remove_and_retention(groups_ui):
    groups_ui.open()
    groups_ui.drawer()
    page = groups_ui.page
    page.get_by_role("tab", name="Members", exact=True).click()
    page.get_by_role("button", name="Add member", exact=True).click()
    page.get_by_label("Search the directory").fill("new")
    page.get_by_role("button", name="Choose New Member").click()
    page.get_by_role("button", name="Add member", exact=True).last.click()
    expect(page.get_by_role("link", name="New Member", exact=True)).to_be_visible()
    page.get_by_label("Role for Max Member").select_option("Admin")
    expect(page.get_by_label("Role for Max Member")).to_have_value("Admin")
    page.get_by_role("button", name="Import CSV").click()
    page.get_by_label("CSV file").set_input_files({
        "name": "members.csv", "mimeType": "text/csv",
        "buffer": b"userId,displayName,email,role\n00000000-0000-0000-0000-000000000001,CSV Member,csv@example.test,user\n",
    })
    page.get_by_role("button", name="Add 1 member", exact=True).click()
    expect(page.get_by_text("1 added, 0 already members, 0 failed.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.get_by_role("link", name="CSV Member", exact=True)).to_be_visible()
    assert any(payload.get("source") == "csv" for _, path, payload in groups_ui.mutations if path.endswith("/add-member"))
    page.get_by_role("button", name="Remove member", exact=True).first.click()
    page.get_by_role("button", name="Remove member", exact=True).last.click()
    expect(page.get_by_role("link", name="Max Member", exact=True)).to_have_count(0)
    page.get_by_role("tab", name="Retention", exact=True).click()
    page.get_by_label("Document retention days", exact=True).fill("90")
    page.get_by_role("button", name="Save retention").click()
    expect(page.get_by_text("Retention policy saved.", exact=True)).to_be_visible()
    assert groups_ui.retention["document_retention_days"] == "90"


def test_nonmember_admin_permissions_and_ownership_requests(groups_ui):
    groups_ui.member_manager = False
    groups_ui.open()
    groups_ui.drawer()
    page = groups_ui.page
    page.get_by_role("tab", name="Members", exact=True).click()
    expect(page.get_by_role("button", name="Remove member", exact=True)).to_have_count(0)
    page.get_by_role("tab", name="Retention", exact=True).click()
    expect(page.get_by_role("button", name="Save retention")).to_be_disabled()
    page.get_by_role("tab", name="Ownership", exact=True).click()
    page.get_by_label("Transfer to a member").select_option("member-1")
    page.get_by_role("button", name="Request ownership transfer").click()
    page.get_by_label("Reason (required)").fill("New project lead")
    page.get_by_role("button", name="Submit approval request").click()
    expect(page.get_by_text("Request approval-42 submitted for approval.", exact=False)).to_be_visible()
    assert groups_ui.mutations[-1][2]["newOwnerId"] == "member-1"
    assert groups_ui.group["owner"]["id"] == "owner-1"


def test_drawer_keyboard_tabs_and_nested_escape(groups_ui):
    groups_ui.open()
    opener = groups_ui.page.get_by_role("button", name=f"Open details for {GROUP_NAME}")
    groups_ui.drawer()
    page = groups_ui.page
    overview = page.get_by_role("tab", name="Overview", exact=True)
    overview.focus()
    overview.press("ArrowRight")
    expect(page.get_by_role("tab", name="Members", exact=True)).to_be_focused()
    page.get_by_role("button", name="Add member", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(2)
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(1)
    expect(page.get_by_role("dialog", name=GROUP_NAME)).to_be_visible()
    expect(page.get_by_role("button", name="Add member", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(opener).to_be_focused()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-m", "ui", "-q"]))
