#!/usr/bin/env python3
# test_v2_control_center_data_health_removed.py
"""
Browser coverage for the V2 Control Center section rail after Data health was removed.
Version: 0.261.291
Implemented in: 0.261.291

Validates that the rail offers no Data health section even to maintenance-capable
administrators, that an old data-health bookmark opens the Dashboard without calling the
removed activity-log backfill APIs, and that sections still follow capabilities.
"""

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
ALL_CAPABILITIES = {
    "can_view_dashboard": True,
    "can_manage_users": True,
    "can_manage_groups": True,
    "can_manage_workspaces": True,
    "can_view_activity_logs": True,
    "can_run_maintenance": True,
}
SECTION_LABELS = ["Dashboard", "Users", "Groups", "Public Workspaces", "Activity Logs"]


def metric(value):
    return {"value": value, "delta": None, "previous": None, "percent_change": None}


def dashboard_summary():
    statuses = {status: metric(0) for status in ("active", "locked", "upload_disabled", "inactive")}
    return {
        "period": {"start_date": "2026-09-08", "end_date": "2026-10-07", "days": 30, "timezone": "UTC"},
        "refreshed_at": "2026-10-07T12:00:00Z",
        "users": {key: metric(1) for key in ("total", "active", "dau", "wau", "mau", "blocked")},
        "groups": {"total": metric(0), "by_status": statuses},
        "public_workspaces": {"total": metric(0), "by_status": statuses},
        "conversations": metric(0),
        "document_uploads": {
            "total": metric(0),
            "by_workspace_type": {key: metric(0) for key in ("personal", "group", "public")},
        },
        "document_processing_failures": {**metric(0), "available": True},
        "tokens": metric(0),
        "pending_approvals": metric(0),
        "status_history_available": False,
        "cached": False,
    }


def dashboard_insights():
    return {
        "period": {"start_date": "2026-09-08", "end_date": "2026-10-07", "days": 30, "timezone": "UTC"},
        "token_usage_by_model": [],
        "top_tokens": {"users": [], "groups": [], "public_workspaces": []},
        "top_activity": {"users": [], "groups": [], "public_workspaces": []},
        "login_heatmap": {"weekday_convention": "Monday=0 through Sunday=6", "timezone": "UTC", "cells": []},
    }


class ControlCenterFixture:
    def __init__(self, page: Page, capabilities=None):
        self.page = page
        self.capabilities = capabilities or ALL_CAPABILITIES
        self.removed_api_requests = []
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
        if path.startswith("/api/admin/control-center/migrate"):
            self.removed_api_requests.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Not found."})
        elif request.method == "GET" and path.startswith("/v2"):
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
                "version": "0.261.291",
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
        elif path == "/api/admin/control-center/token-filters" and request.method == "GET":
            route.fulfill(json={"success": True, "filters": {
                "users": [], "groups": [], "public_workspaces": [], "models": [],
                "workspace_types": [], "token_types": [],
            }})
        elif path == "/api/v2/control-center/dashboard/summary" and request.method == "GET":
            route.fulfill(json=dashboard_summary())
        elif path == "/api/v2/control-center/dashboard/insights" and request.method == "GET":
            route.fulfill(json=dashboard_insights())
        elif path == "/api/admin/control-center/activity-trends" and request.method == "GET":
            route.fulfill(json={"success": True, "activity_data": {}})
        else:
            self.unexpected.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, section, *, width=1440):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.page.set_viewport_size({"width": width, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/{section}", wait_until="networkidle")

    def assert_clean(self):
        assert not self.unexpected, self.unexpected
        assert not self.removed_api_requests, self.removed_api_requests


pytestmark = pytest.mark.ui


def test_data_health_bookmark_opens_dashboard_without_backfill_calls(page):
    fixture = ControlCenterFixture(page)
    fixture.open("data-health")

    rail = page.get_by_role("complementary", name="Control Center sections")
    expect(rail.get_by_role("link")).to_have_text(SECTION_LABELS)
    expect(rail.get_by_role("link", name="Data health")).to_have_count(0)
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page.get_by_text("Activity-log data health")).to_have_count(0)
    expect(page.get_by_role("button", name="Run backfill")).to_have_count(0)
    fixture.assert_clean()


def test_mobile_section_picker_has_no_data_health_option(page):
    fixture = ControlCenterFixture(page)
    fixture.open("data-health", width=390)

    picker = page.get_by_label("Control Center section", exact=True)
    expect(picker).to_be_visible()
    expect(picker.locator("option")).to_have_text(SECTION_LABELS)
    expect(picker).to_have_value("dashboard")
    fixture.assert_clean()


def test_control_center_sections_follow_capabilities(page):
    fixture = ControlCenterFixture(page, capabilities={
        **{key: False for key in ALL_CAPABILITIES},
        "can_view_dashboard": True,
        "can_run_maintenance": True,
    })
    fixture.open("users")

    expect(page.get_by_role("alert")).to_contain_text("permissions do not include this section")
    rail = page.get_by_role("complementary", name="Control Center sections")
    expect(rail.get_by_role("link")).to_have_text(["Dashboard"])
    rail.get_by_role("link", name="Dashboard").click()
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    fixture.assert_clean()
