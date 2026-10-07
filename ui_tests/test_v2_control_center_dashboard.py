#!/usr/bin/env python3
# test_v2_control_center_dashboard.py
"""
Browser coverage for the V2 Control Center dashboard.
Version: 0.261.279
Implemented in: 0.261.279

Validates dashboard loading, range selection, chart access, drill-through links,
CSV export, and chat-with-trends against a local SPA fixture.
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
TODAY = "2026-10-07"


def metric(value, delta=None, previous=None):
    return {
        "value": value,
        "delta": delta,
        "previous": previous,
        "percent_change": None if previous in (None, 0) else round((delta or 0) / previous * 100, 1),
    }


def dashboard_payload():
    return {
        "period": {"start_date": "2026-09-08", "end_date": TODAY, "days": 30, "timezone": "UTC"},
        "refreshed_at": "2026-10-07T12:00:00Z",
        "users": {
            "total": metric(100),
            "active": metric(20, 2, 18),
            "dau": metric(5),
            "wau": metric(12),
            "mau": metric(20),
            "blocked": metric(3),
        },
        "groups": {
            "total": metric(8),
            "by_status": {
                "active": metric(5),
                "locked": metric(1),
                "upload_disabled": metric(1),
                "inactive": metric(1),
            },
        },
        "public_workspaces": {
            "total": metric(4),
            "by_status": {
                "active": metric(2),
                "locked": metric(1),
                "upload_disabled": metric(0),
                "inactive": metric(1),
            },
        },
        "conversations": metric(10, 2, 8),
        "document_uploads": {
            "total": metric(6, 1, 5),
            "by_workspace_type": {
                "personal": metric(3, 1, 2),
                "group": metric(2, 0, 2),
                "public": metric(1, 0, 1),
            },
        },
        "document_processing_failures": {**metric(1, 1, 0), "available": True},
        "tokens": metric(2400, 400, 2000),
        "pending_approvals": metric(2),
        "status_history_available": False,
        "cached": False,
    }


class DashboardFixture:
    def __init__(self, page: Page):
        self.page = page
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
                "version": "0.261.279",
                "user": {"id": "dashboard-reader", "display_name": "Dashboard Reader", "is_admin": False, "roles": ["ControlCenterDashboardReader"]},
                "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
                "features": {},
                "control_center": {
                    "can_view_dashboard": True,
                    "can_manage_users": False,
                    "can_manage_groups": False,
                    "can_manage_workspaces": False,
                    "can_view_activity_logs": False,
                    "can_run_maintenance": False,
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
        elif path == "/api/admin/control-center/token-filters" and request.method == "GET":
            route.fulfill(json={"success": True, "filters": {
                "users": [{"id": "user-1", "label": "User One"}],
                "groups": [{"id": "group-1", "name": "Group One"}],
                "public_workspaces": [{"id": "workspace-1", "name": "Workspace One"}],
                "models": [{"value": "gpt-4o", "label": "gpt-4o"}],
                "workspace_types": [
                    {"value": "personal", "label": "Personal"},
                    {"value": "group", "label": "Group"},
                    {"value": "public", "label": "Public"},
                ],
                "token_types": [
                    {"value": "chat", "label": "Chat"},
                    {"value": "embedding", "label": "Embedding"},
                    {"value": "web_search", "label": "Web Search"},
                ],
            }})
        elif path == "/api/v2/control-center/dashboard/summary" and request.method == "GET":
            self.requests.append(("GET", path, parsed.query))
            route.fulfill(json=dashboard_payload())
        elif path == "/api/v2/control-center/dashboard/insights" and request.method == "GET":
            self.requests.append(("GET", path, parsed.query))
            route.fulfill(json={
                "period": {"start_date": "2026-09-08", "end_date": TODAY, "days": 30, "timezone": "UTC"},
                "token_usage_by_model": [
                    {"date": "2026-10-06", "model": "gpt-4o", "tokens": 1500},
                ],
                "top_tokens": {
                    "users": [{"id": "user-1", "tokens": 1500}],
                    "groups": [{"id": "group-1", "tokens": 700}],
                    "public_workspaces": [{"id": "workspace-1", "tokens": 200}],
                },
                "top_activity": {
                    "users": [{"id": "user-1", "activity_count": 9}],
                    "groups": [{"id": "group-1", "activity_count": 5}],
                    "public_workspaces": [{"id": "workspace-1", "activity_count": 2}],
                },
                "login_heatmap": {
                    "weekday_convention": "Monday=0 through Sunday=6",
                    "timezone": "UTC",
                    "cells": [{"weekday": 0, "hour": 9, "count": 2}],
                },
            })
        elif path == "/api/admin/control-center/activity-trends" and request.method == "GET":
            self.requests.append(("GET", path, parsed.query))
            days = ["2026-10-01", "2026-10-02", "2026-10-03"]
            route.fulfill(json={"success": True, "activity_data": {
                "chats": {date: index + 1 for index, date in enumerate(days)},
                "logins": {date: index + 2 for index, date in enumerate(days)},
                "personal_documents_created": {date: 1 for date in days},
                "group_documents_created": {date: 1 for date in days},
                "public_documents_created": {date: 1 for date in days},
                "tokens": {date: {"chat": 20, "embedding": 10, "web_search": 0} for date in days},
            }})
        elif path == "/api/admin/control-center/activity-trends/export" and request.method == "POST":
            self.requests.append(("POST", path, json.loads(request.post_data or "{}")))
            route.fulfill(status=200, content_type="text/csv", body="date,count\n2026-10-01,3\n")
        elif path == "/api/admin/control-center/activity-trends/chat" and request.method == "POST":
            self.requests.append(("POST", path, json.loads(request.post_data or "{}")))
            route.fulfill(json={"success": True, "conversation_id": "conversation-123"})
        else:
            self.unexpected.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/dashboard", wait_until="networkidle")

    def assert_clean(self):
        assert not self.unexpected, self.unexpected


@pytest.fixture
def dashboard_ui(page):
    fixture = DashboardFixture(page)
    yield fixture
    fixture.assert_clean()


pytestmark = pytest.mark.ui


def test_dashboard_reader_loads_metrics_charts_and_drillthrough(dashboard_ui):
    dashboard_ui.open()
    page = dashboard_ui.page

    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page.get_by_text("Total users", exact=True)).to_be_visible()
    expect(page.get_by_text("100", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Token usage by model")).to_be_visible()
    expect(page.get_by_role("img", name="Daily conversation creation and login counts. Select a point to open filtered activity logs.")).to_be_visible()
    expect(page.get_by_role("table", name="Logins by weekday and hour (UTC; Monday = 0)")).to_be_visible()
    model_filter = page.locator("#dashboard-filter-model")
    expect(model_filter).to_have_value("")
    model_filter.select_option("gpt-4o")
    expect(model_filter).to_have_value("gpt-4o")
    page.get_by_role("link", name="Groups locked: 1").click()
    expect(page).to_have_url(f"{ORIGIN}/v2/control-center/groups?status=locked")


def test_dashboard_range_refresh_export_and_trends_chat(dashboard_ui):
    dashboard_ui.open()
    page = dashboard_ui.page

    page.get_by_label("Date range").select_option("7")
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    assert any(
        path == "/api/v2/control-center/dashboard/summary" and "start_date=" in query
        for method, path, query in dashboard_ui.requests if method == "GET"
    )

    page.get_by_role("button", name="Refresh").click()
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    assert any(
        path == "/api/v2/control-center/dashboard/summary" and "force_refresh=1" in query
        for method, path, query in dashboard_ui.requests if method == "GET"
    )

    with page.expect_download():
        page.get_by_role("button", name="Export").click()
    page.get_by_role("button", name="Chat with these trends").click()
    expect(page.get_by_role("link", name="Open conversation")).to_have_attribute("href", "/v2/chat/conversation-123")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-m", "ui"]))
