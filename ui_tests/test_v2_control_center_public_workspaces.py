# test_v2_control_center_public_workspaces.py
"""
Browser tests for public workspace management using the built local V2 assets.
Version: 0.261.283
Implemented in: 0.261.283

Shared fixture supports Azure Playwright with DefaultAzureCredential when configured.
"""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from test_v2_control_center_users import ORIGIN, UsersFixture


NAME = "Public <img src=x onerror=alert(1)>"
ID = "public-1"


class WorkspacesFixture(UsersFixture):
    def __init__(self, page):
        self.workspace = {
            "id": ID, "name": NAME, "description": "Shared knowledge", "status": "active",
            "owner": {"id": "owner", "display_name": "Owner", "email": "owner@example.test"},
            "members": 2, "documents": None, "tokens": None, "last_activity": None,
            "created_at": "2026-10-01T00:00:00Z", "metrics_calculated_at": None,
        }
        self.members = [
            {"id": "owner", "display_name": "Owner", "email": "owner@example.test", "role": "Owner"},
            {"id": "manager", "display_name": "Manager", "email": "manager@example.test", "role": "DocumentManager"},
        ]
        self.can_edit = True
        self.mutations = []
        self.fail_bulk = False
        self.fail_list = False
        self.history = []
        self.retention = {"conversation_retention_days": "default", "document_retention_days": 30}
        self.errors = []
        super().__init__(page)
        page.on("pageerror", lambda error: self.errors.append(str(error)))

    def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path, method = parsed.path, request.method
        base = "/api/v2/control-center/public-workspaces"
        admin = f"/api/admin/control-center/public-workspaces/{ID}"
        if path == base and method == "GET":
            self.requests.append((method, path, parsed.query))
            route.fulfill(status=500 if self.fail_list else 200, json={"error": "Inventory unavailable."} if self.fail_list else {
                "workspaces": [self.workspace], "pagination": {"page": int(parse_qs(parsed.query).get("page", ["1"])[0]), "total_items": 30},
            })
        elif path == f"{base}/{ID}" and method == "GET":
            route.fulfill(json={
                "workspace": self.workspace, "members": self.members, "status_history": self.history,
                "permissions": {"can_edit_members": self.can_edit, "current_user_id": "admin"},
                "retention": {**self.retention, "enabled": True, "can_edit": self.can_edit},
                "documents_summary": {"count": 3, "cached_metrics": {}, "metrics_calculated_at": None},
                "tokens": 120, "metrics_calculated_at": "2026-10-07T00:00:00Z",
                "activity": [{"id": "event-1", "activity_type": "public_workspace_status_change",
                              "description": "<script>alert(1)</script>", "timestamp": "2026-10-07T00:00:00Z"}],
            })
        elif path == f"{base}/bulk-status":
            payload = json.loads(request.post_data)
            self.bulk_payloads.append(payload)
            route.fulfill(json={"success_count": 1, "failed_count": 1 if self.fail_bulk else 0,
                                "failed_workspaces": [{"id": "missing", "error": "Not found."}] if self.fail_bulk else []})
        elif path == f"{base}/{ID}/status":
            payload = json.loads(request.post_data)
            self.mutations.append((method, path, payload))
            self.history.append({"old_status": self.workspace["status"], "new_status": payload["status"],
                                 "changed_by_email": "admin@example.test", "changed_at": "2026-10-07T00:00:00Z", "reason": payload["reason"]})
            self.workspace["status"] = payload["status"]
            route.fulfill(json={"new_status": payload["status"]})
        elif path.startswith(admin) and method in ("POST", "PUT", "DELETE"):
            payload = json.loads(request.post_data or "{}")
            self.mutations.append((method, path, payload))
            if path.endswith("/add-member"):
                self.members.append({"id": payload["userId"], "display_name": payload["displayName"],
                                     "email": payload["email"], "role": "Admin" if payload["role"] == "admin" else "DocumentManager"})
                route.fulfill(json={"skipped": False})
            else:
                route.fulfill(json={"approval_id": "approval-42", "status": "pending"})
        elif path.startswith(f"/api/public_workspaces/{ID}/members/"):
            payload = json.loads(request.post_data or "{}")
            self.mutations.append((method, path, payload))
            member_id = path.rsplit("/", 1)[1]
            if method == "DELETE":
                self.members = [member for member in self.members if member["id"] != member_id]
            else:
                for member in self.members:
                    if member["id"] == member_id:
                        member["role"] = payload["role"]
            route.fulfill(json={"success": True})
        elif path == f"/api/retention-policy/public/{ID}":
            payload = json.loads(request.post_data)
            self.mutations.append((method, path, payload))
            self.retention.update(payload)
            route.fulfill(json={"success": True})
        elif path == "/api/userSearch":
            route.fulfill(json=[{"id": "new-person", "displayName": "New Manager", "mail": "new@example.test", "userPrincipalName": "new@example.test"}])
        elif path == f"{base}/export.csv":
            route.fulfill(content_type="text/csv", body="id,name\npublic-1,Public\n")
        else:
            super()._route(route)

    def open(self, query="", mobile=False):
        self.page.set_viewport_size({"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/public-workspaces{query}", wait_until="networkidle")

    def assert_clean(self):
        super().assert_clean()
        assert not self.errors


@pytest.fixture
def workspaces_ui(page):
    fixture = WorkspacesFixture(page)
    yield fixture
    fixture.assert_clean()


pytestmark = pytest.mark.ui


def test_filters_sort_page_export_and_cross_page_bulk(workspaces_ui):
    workspaces_ui.open()
    page = workspaces_ui.page
    expect(page.get_by_text("Not recorded", exact=True).first).to_be_visible()
    page.get_by_label("Filter by workspace status").select_option("active")
    expect(page).to_have_url(f"{ORIGIN}/v2/control-center/public-workspaces?status=active")
    expect(page.get_by_role("link", name="Export CSV")).to_have_attribute("href", "/api/v2/control-center/public-workspaces/export.csv?status=active")
    page.get_by_role("button", name="Sort by Recorded documents", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/control-center/public-workspaces?status=active&sort=documents&direction=asc")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/control-center/public-workspaces?status=active&sort=documents&direction=asc&page=2")
    page.get_by_label("Select all rows on this page").check()
    page.get_by_role("button", name="Select all 30 matching records").click()
    page.get_by_role("button", name="Apply bulk status").click()
    page.get_by_label("Reason (required)").fill("Review")
    page.get_by_role("button", name="Apply bulk status").last.click()
    expect(page.get_by_text("1 public workspaces updated.")).to_be_visible()
    assert workspaces_ui.bulk_payloads[-1] == {"filter": {"status": "active"}, "exclude_ids": [], "status": "locked", "reason": "Review"}


def test_partial_failure_and_list_failure_are_visible(workspaces_ui):
    workspaces_ui.fail_bulk = True
    workspaces_ui.open()
    page = workspaces_ui.page
    page.get_by_label("Select all rows on this page").check()
    page.get_by_role("button", name="Apply bulk status").click()
    page.get_by_label("Reason (required)").fill("Review")
    page.get_by_role("button", name="Apply bulk status").last.click()
    expect(page.get_by_text("1 succeeded; 1 failed. missing: Not found.")).to_be_visible()
    workspaces_ui.fail_list = True
    page.get_by_role("button", name="Refresh workspaces").click()
    expect(page.get_by_text("Inventory unavailable.", exact=True)).to_be_visible()


@pytest.mark.parametrize("mobile", [False, True])
def test_detail_status_activity_and_scoped_approval(workspaces_ui, mobile):
    workspaces_ui.open("?id=public-1", mobile=mobile)
    page = workspaces_ui.page
    expect(page.get_by_role("dialog", name=NAME)).to_be_visible()
    expect(page.locator("img[src=x]")).to_have_count(0)
    page.get_by_role("tab", name="Status", exact=True).click()
    page.get_by_label("Public workspace status", exact=True).select_option("locked")
    page.get_by_role("button", name="Change status").click()
    page.get_by_label("Reason (required)").fill("Hold uploads")
    page.get_by_role("button", name="Apply status").click()
    expect(page.get_by_text("Hold uploads", exact=True)).to_be_visible()
    page.get_by_role("tab", name="Activity", exact=True).click()
    expect(page.get_by_text("<script>alert(1)</script>", exact=True)).to_be_visible()
    page.get_by_role("button", name="Raw JSON").click()
    expect(page.locator("pre")).to_contain_text("public_workspace_status_change")
    expect(page.get_by_role("link", name="View in Activity Logs")).to_have_attribute(
        "href", "/v2/control-center/activity-logs?workspace_type=public&workspace_id=public-1&public_workspace_id=public-1")
    page.get_by_role("tab", name="Documents", exact=True).click()
    page.get_by_role("button", name="Request deletion of all documents").click()
    page.get_by_label("Reason (required)").fill("Cleanup")
    page.get_by_role("button", name="Submit approval request").click()
    expect(page.get_by_text("Request approval-42 submitted for approval.", exact=False)).to_be_visible()
    expect(page.get_by_role("link", name="View approval requests")).to_have_attribute("href", "/v2/approvals/all/approval-42?group_id=public-1")
    assert workspaces_ui.mutations[-1] == ("DELETE", "/api/admin/control-center/public-workspaces/public-1/documents", {"reason": "Cleanup"})


def test_members_supported_roles_and_existing_retention_payload(workspaces_ui):
    workspaces_ui.open("?id=public-1")
    page = workspaces_ui.page
    page.get_by_role("tab", name="Members", exact=True).click()
    page.get_by_role("button", name="Add member", exact=True).click()
    expect(page.get_by_label("Role for the new member").locator("option")).to_have_count(2)
    page.get_by_label("Search the directory").fill("new")
    page.get_by_role("button", name="Choose New Manager").click()
    page.get_by_role("button", name="Add member", exact=True).last.click()
    expect(page.get_by_role("link", name="New Manager", exact=True)).to_be_visible()
    page.get_by_label("Role for Manager", exact=True).select_option("Admin")
    expect(page.get_by_label("Role for Manager", exact=True)).to_have_value("Admin")
    page.get_by_role("button", name="Import CSV").click()
    page.get_by_label("CSV file").set_input_files({"name": "members.csv", "mimeType": "text/csv",
        "buffer": b"userId,displayName,email,role\n00000000-0000-0000-0000-000000000001,CSV Manager,csv@example.test,document_manager\n"})
    page.get_by_role("button", name="Add 1 member", exact=True).click()
    expect(page.get_by_text("1 added, 0 already members, 0 failed.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Done", exact=True).click()
    page.get_by_role("tab", name="Retention", exact=True).click()
    page.get_by_label("Document retention days", exact=True).fill("90")
    page.get_by_role("button", name="Save retention").click()
    expect(page.get_by_text("Retention policy saved.", exact=True)).to_be_visible()
    assert workspaces_ui.mutations[-1][2] == {"document_retention_days": "90"}


@pytest.mark.parametrize("action,path,method", [
    ("Request workspace deletion", "", "DELETE"),
    ("Request to take ownership", "/take-ownership", "POST"),
    ("Request ownership transfer", "/ownership", "PUT"),
])
def test_existing_destructive_and_ownership_request_shapes(workspaces_ui, action, path, method):
    workspaces_ui.can_edit = False
    workspaces_ui.open("?id=public-1")
    page = workspaces_ui.page
    if path:
        page.get_by_role("tab", name="Ownership", exact=True).click()
        if path == "/ownership":
            page.get_by_label("Transfer to a member").select_option("manager")
    page.get_by_role("button", name=action, exact=True).click()
    page.get_by_label("Reason (required)").fill("Governance")
    page.get_by_role("button", name="Submit approval request").click()
    expect(page.get_by_text("Request approval-42 submitted for approval.", exact=False)).to_be_visible()
    expected = {"reason": "Governance", **({"newOwnerId": "manager"} if path == "/ownership" else {})}
    assert workspaces_ui.mutations[-1] == (method, f"/api/admin/control-center/public-workspaces/public-1{path}", expected)
    page.get_by_role("tab", name="Members", exact=True).click()
    expect(page.get_by_role("button", name="Remove member", exact=True)).to_have_count(0)
    page.get_by_role("tab", name="Retention", exact=True).click()
    expect(page.get_by_role("button", name="Save retention")).to_be_disabled()
