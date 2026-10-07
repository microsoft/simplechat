# test_v2_approvals_and_terms_pages.py
"""
Browser coverage for the V2 Approval Requests page and the V2 Terms of Use page.
Version: 0.261.281
Implemented in: 0.261.281

Serve the real built SPA through Playwright request interception with a closed API
boundary. Check that the approvals page lays out a category rail, a request list and a
detail pane like Admin Settings; that a decision posts to the real approvals endpoint;
that the admin-only agent template category is hidden from other users; that a phone
width swaps the rail for a picker; and that the terms page renders the configured text
as text and follows the server's redirect after acceptance. Unexpected requests fail.
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

GROUP_APPROVAL = {
    "id": "appr-group-1",
    "group_id": "group-1",
    "group_name": "Finance",
    "request_type": "delete_documents",
    "status": "pending",
    "requester_name": "Riley Owner",
    "requester_email": "riley@contoso.test",
    "reason": "Quarterly cleanup",
    "created_at": "2026-10-01T12:00:00+00:00",
    "can_approve": True,
    "can_deny": True,
}


class ApprovalsFixture:
    """The approvals and terms pages with an in-memory API."""

    def __init__(self, page: Page, *, is_admin=False):
        self.page = page
        self.is_admin = is_admin
        self.approvals = [copy.deepcopy(GROUP_APPROVAL)]
        self.decisions = []
        self.terms_posts = []
        self.terms_payload = {
            "enabled": True,
            "required": True,
            "title": "Acceptable Use",
            "message": "Line one <b>not bold</b>\nLine two",
            "accept_button_text": "I agree",
            "decline_button_text": "No thanks",
            "return_path": "/v2/approvals",
            "branding": {"app_title": "SimpleChat", "hide_app_title": False, "show_logo": False},
        }
        self.errors = []
        self.unexpected_requests = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self._route)

    def _bootstrap(self):
        return {
            "version": "0.261.281",
            "user": {
                "id": "user-1",
                "display_name": "Test User",
                "email": "test.user@contoso.test",
                "is_admin": self.is_admin,
                "roles": ["Admin"] if self.is_admin else [],
            },
            "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
            "features": {},
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {
                "custom_pages": {"enabled": False, "items": []},
                "external_links": {"enabled": False, "items": []},
            },
            "workspace": {"sections": {}},
            "settings": {},
        }

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
            return
        method = request.method
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
        elif method == "GET" and path == "/api/approvals":
            status = parse_qs(parsed.query).get("status", ["pending"])[0]
            items = [item for item in self.approvals if status == "all" or item["status"] == status]
            route.fulfill(json={"approvals": items, "total_count": len(items), "total_pages": 1})
        elif method == "GET" and path.startswith("/api/approvals/"):
            approval_id = path.removeprefix("/api/approvals/")
            match = next((item for item in self.approvals if item["id"] == approval_id), None)
            if match:
                route.fulfill(json=match)
            else:
                route.fulfill(status=404, json={"error": "Not found"})
        elif method == "POST" and path.startswith("/api/approvals/") and path.endswith(("/approve", "/deny")):
            approval_id, action = path.removeprefix("/api/approvals/").rsplit("/", 1)
            self.decisions.append((approval_id, action, request.post_data_json))
            for item in self.approvals:
                if item["id"] == approval_id:
                    item["status"] = "approved" if action == "approve" else "denied"
                    item["can_approve"] = item["can_deny"] = False
            route.fulfill(json={"success": True})
        elif method == "GET" and path == "/api/v2/terms-of-use":
            route.fulfill(json=self.terms_payload)
        elif method == "POST" and path in ("/api/v2/terms-of-use/accept", "/api/v2/terms-of-use/decline"):
            self.terms_posts.append(path.rsplit("/", 1)[-1])
            target = "/v2/approvals" if path.endswith("accept") else "/logout"
            route.fulfill(json={"success": True, "redirect_url": target})
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
def approvals_ui(page):
    fixture = ApprovalsFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def admin_approvals_ui(page):
    fixture = ApprovalsFixture(page, is_admin=True)
    yield fixture
    fixture.assert_clean()


def test_approvals_page_lays_out_rail_list_and_detail(approvals_ui):
    approvals_ui.open("/v2/approvals")
    page = approvals_ui.page
    expect(page.get_by_test_id("v2-approvals-page")).to_be_visible()
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/all")

    rail = page.get_by_test_id("v2-approvals-rail")
    expect(rail).to_be_visible()
    for category in ("all", "group", "m365", "outgoing", "paused"):
        expect(page.get_by_test_id(f"v2-approvals-category-{category}")).to_be_visible()
    # Agent templates are an admin queue, and content screening follows its feature flag.
    expect(page.get_by_test_id("v2-approvals-category-agent-templates")).to_have_count(0)
    expect(page.get_by_test_id("v2-approvals-category-content-screening")).to_have_count(0)
    expect(page.get_by_test_id("v2-approvals-active-count")).to_have_text("1")

    row = page.get_by_test_id("v2-approval-row-appr-group-1")
    expect(row).to_contain_text("Delete All Documents")
    row.click()
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/all/appr-group-1?group_id=group-1")
    expect(page.get_by_test_id("v2-approval-decision")).to_be_visible()

    rail_box = rail.bounding_box()
    row_box = row.bounding_box()
    decision_box = page.get_by_test_id("v2-approval-decision").bounding_box()
    assert rail_box["x"] + rail_box["width"] <= row_box["x"] + 1, "The list sits right of the rail"
    assert row_box["x"] + row_box["width"] <= decision_box["x"] + 1, "The detail pane sits right of the list"

    page.get_by_test_id("v2-approval-comment").fill("Looks fine")
    page.get_by_test_id("v2-approval-approve").click()
    expect(page.get_by_test_id("v2-approval-decision")).to_have_count(0)
    assert approvals_ui.decisions == [
        ("appr-group-1", "approve", {"group_id": "group-1", "comment": "Looks fine"}),
    ]


def test_classic_deep_link_opens_the_request(approvals_ui):
    approvals_ui.open("/v2/approvals?approval_id=appr-group-1&group_id=group-1")
    page = approvals_ui.page
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/all/appr-group-1?group_id=group-1")
    expect(page.get_by_test_id("v2-approval-decision")).to_be_visible()


def test_admins_see_the_agent_template_queue(admin_approvals_ui):
    admin_approvals_ui.open("/v2/approvals")
    expect(admin_approvals_ui.page.get_by_test_id("v2-approvals-category-agent-templates")).to_be_visible()


def test_phone_width_swaps_the_rail_for_a_picker(approvals_ui):
    approvals_ui.open("/v2/approvals", width=390, height=844)
    page = approvals_ui.page
    expect(page.get_by_test_id("v2-approvals-rail")).to_be_hidden()
    picker = page.get_by_test_id("v2-approvals-category-select")
    expect(picker).to_be_visible()
    picker.select_option("group")
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/group")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_terms_page_renders_text_and_follows_the_accept_redirect(approvals_ui):
    approvals_ui.open("/v2/terms-of-use?next=/v2/approvals")
    page = approvals_ui.page
    expect(page.get_by_test_id("v2-terms-of-use")).to_be_visible()
    expect(page.get_by_role("heading", name="Acceptable Use")).to_be_visible()
    message = page.get_by_test_id("v2-terms-of-use-message")
    expect(message).to_contain_text("<b>not bold</b>")
    expect(message.locator("b")).to_have_count(0)
    expect(page.get_by_test_id("v2-terms-decline")).to_have_text("No thanks")

    page.get_by_test_id("v2-terms-accept").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/approvals/all")
    assert approvals_ui.terms_posts == ["accept"]
