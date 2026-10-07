#!/usr/bin/env python3
# test_v2_control_center_data_health.py
"""
Browser coverage for the V2 Control Center data-health flow.
Version: 0.261.278
Implemented in: 0.261.278

Validates capability-based discovery, on-demand status checks and the explicit confirmation
before the activity-log backfill, without contacting a live SimpleChat deployment.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options  # noqa: F401
from v2_notification_stubs import is_notification_count, notification_count_payload


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC / "v2" / "index.html"
ORIGIN = "http://simplechat.test"


class ControlCenterFixture:
    def __init__(self, page: Page, capabilities=None):
        self.page = page
        self.capabilities = capabilities or {
            "can_view_dashboard": True,
            "can_manage_users": True,
            "can_manage_groups": True,
            "can_manage_workspaces": True,
            "can_view_activity_logs": True,
            "can_run_maintenance": True,
        }
        self.requests = []
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
                "version": "0.261.278",
                "user": {"id": "test-admin", "display_name": "Test Admin", "is_admin": True, "roles": ["Admin"]},
                "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
                "features": {},
                "control_center": self.capabilities,
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
        elif path == "/api/admin/control-center/migrate/status" and request.method == "GET":
            self.requests.append(("GET", path))
            route.fulfill(json={
                "conversations_without_logs": 2,
                "personal_documents_without_logs": 1,
                "group_documents_without_logs": 0,
                "public_documents_without_logs": 3,
                "total_documents_without_logs": 4,
                "migration_needed": True,
                "estimated_total_records": 6,
            })
        elif path == "/api/admin/control-center/migrate/all" and request.method == "POST":
            self.requests.append(("POST", path))
            route.fulfill(json={
                "conversations_migrated": 0,
                "conversations_skipped_existing": 2,
                "personal_documents_migrated": 1,
                "personal_documents_skipped_existing": 0,
                "group_documents_migrated": 0,
                "group_documents_skipped_existing": 0,
                "public_documents_migrated": 0,
                "public_documents_skipped_existing": 3,
                "total_migrated": 1,
                "total_skipped_existing": 5,
                "total_failed": 0,
            })
        else:
            self.unexpected.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, *, width=1440):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.page.set_viewport_size({"width": width, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/data-health", wait_until="networkidle")

    def assert_clean(self):
        assert not self.unexpected, self.unexpected


@pytest.fixture
def control_center_ui(page):
    fixture = ControlCenterFixture(page)
    yield fixture
    fixture.assert_clean()


pytestmark = pytest.mark.ui


def test_data_health_checks_only_on_demand(control_center_ui):
    control_center_ui.open()
    page = control_center_ui.page

    expect(page.get_by_role("heading", name="Activity-log data health")).to_be_visible()
    assert control_center_ui.requests == []
    page.get_by_role("button", name="Check activity-log status").click()
    expect(page.get_by_text("Estimated records", exact=True)).to_be_visible()
    expect(page.get_by_text("6", exact=True)).to_be_visible()
    assert control_center_ui.requests == [
        ("GET", "/api/admin/control-center/migrate/status"),
    ]


def test_backfill_waits_for_confirmation(control_center_ui):
    control_center_ui.open()
    page = control_center_ui.page

    page.get_by_role("button", name="Run backfill").click()
    dialog = page.get_by_role("dialog", name="Run activity-log backfill?")
    expect(dialog).to_be_visible()
    assert control_center_ui.requests == []
    dialog.get_by_role("button", name="Run backfill").click()
    expect(page.get_by_text("1 records added; 5 existing activity records skipped; 0 failures.")).to_be_visible()
    assert control_center_ui.requests == [
        ("POST", "/api/admin/control-center/migrate/all"),
    ]


def test_control_center_menu_and_sections_follow_capabilities(page):
    fixture = ControlCenterFixture(page, capabilities={
        "can_view_dashboard": True,
        "can_manage_users": False,
        "can_manage_groups": False,
        "can_manage_workspaces": False,
        "can_view_activity_logs": False,
        "can_run_maintenance": False,
    })
    fixture.open()
    page.locator('button[aria-controls="sidebar-account-menu"]').click()
    expect(page.get_by_role("link", name="Control Center")).to_be_visible()
    page.get_by_role("link", name="Control Center").click()
    expect(page.get_by_role("complementary", name="Control Center sections").get_by_role("link")).to_have_count(1)
    expect(page.get_by_role("link", name="Dashboard")).to_be_visible()
    page.goto(f"{ORIGIN}/v2/control-center/data-health", wait_until="networkidle")
    expect(page.get_by_role("alert")).to_contain_text("permissions do not include this section")
    assert fixture.requests == []
    fixture.assert_clean()
