#!/usr/bin/env python3
# test_v2_control_center_dashboard.py
"""
Browser coverage for the V2 Control Center dashboard.
Version: 0.261.300
Implemented in: 0.261.279

Validates the dashboard's sections and plain-language definitions, named rankings, token
filters that sit inside (and only change) the Token usage section, capability-aware
drill-through links, CSV export, and "Chat with this dashboard": the requirements checklist
when something is missing, and a new orchestrated chat with the prompt ready to send when
everything is set up. Reworked in 0.261.300, when the dashboard stopped calling the classic
activity-trends API and the broken "Chat with these trends" endpoint was retired.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_notification_stubs import is_notification_count, notification_count_payload


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC / "v2" / "index.html"
ORIGIN = "http://simplechat.test"
START = "2026-09-08"
TODAY = "2026-10-07"
DAYS = ["2026-10-05", "2026-10-06", TODAY]
READINESS_PATH = "/api/v2/control-center/dashboard/chat-readiness"
COMPOSER_PLACEHOLDER = "Send a message, or type # to add a document…"


def metric(value, delta=None, previous=None):
    return {
        "value": value,
        "delta": delta,
        "previous": previous,
        "percent_change": None if previous in (None, 0) else round((delta or 0) / previous * 100, 1),
    }


def dashboard_payload():
    return {
        "period": {"start_date": START, "end_date": TODAY, "days": 30, "timezone": "UTC"},
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
                "upload_disabled": metric(2),
                "inactive": metric(0),
            },
        },
        "public_workspaces": {
            "total": metric(4),
            "by_status": {
                "active": metric(3),
                "locked": metric(0),
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
    }


def insights_payload():
    return {
        "period": {"start_date": START, "end_date": TODAY, "days": 30, "timezone": "UTC"},
        "refreshed_at": "2026-10-07T12:00:00Z",
        "daily_activity": [
            {"date": day, "sign_ins": index + 2, "conversations_created": index + 1,
             "uploads_personal": 1, "uploads_group": 1, "uploads_public": 0}
            for index, day in enumerate(DAYS)
        ],
        "token_usage_by_type": [{"date": day, "chat": 20, "embedding": 10, "web_search": 0} for day in DAYS],
        "token_usage_by_model": [{"date": "2026-10-06", "model": "gpt-4o", "tokens": 1500}],
        "top_tokens": {
            "users": [{"id": "user-1", "tokens": 1500, "name": "Jane Doe", "detail": "jane@contoso.com", "found": True}],
            "groups": [
                {"id": "group-1", "tokens": 700, "name": "Finance", "detail": "", "found": True},
                {"id": "group-gone", "tokens": 50, "name": "Deleted group", "detail": "", "found": False},
            ],
            "public_workspaces": [{"id": "workspace-1", "tokens": 200, "name": "Policies", "detail": "", "found": True}],
        },
        "top_activity": {
            "users": [{"id": "user-1", "activity_count": 9, "name": "Jane Doe", "detail": "jane@contoso.com", "found": True}],
            "groups": [{"id": "group-1", "activity_count": 5, "name": "Finance", "detail": "", "found": True}],
            "public_workspaces": [],
        },
        "login_heatmap": {
            "weekday_convention": "Monday=0 through Sunday=6",
            "timezone": "UTC",
            "cells": [{"weekday": 0, "hour": 9, "count": 2}],
        },
    }


def requirement(requirement_id, label, met, link=None):
    return {
        "id": requirement_id,
        "label": label,
        "met": met,
        "detail": "" if met else f"{label} is not set up.",
        "remedy": "" if met else f"Fix {label.lower()} in Admin Settings.",
        "settings_link": link,
    }


NOT_READY = {
    "ready": False,
    "action": None,
    "requirements": [
        requirement("agents", "Agents and actions are turned on", False, "/admin/settings/agents-config"),
        requirement("orchestration", "Chat Orchestration is turned on", True),
        requirement("action_access", "Orchestration can use actions", False, "javascript:alert(1)"),
        requirement("control_center_action", "A Control Center action is set up for you", False,
                    "/admin/actions/new?type=control_center"),
    ],
}
READY = {
    "ready": True,
    "action": {"name": "Usage insights"},
    "requirements": [
        requirement("agents", "Agents and actions are turned on", True),
        requirement("orchestration", "Chat Orchestration is turned on", True),
        requirement("action_access", "Orchestration can use actions", True),
        requirement("control_center_action", "A Control Center action is set up for you", True),
    ],
}


def bootstrap_payload(admin):
    capabilities = {
        "can_view_dashboard": True,
        "can_manage_users": admin,
        "can_manage_groups": admin,
        "can_manage_workspaces": admin,
        "can_view_activity_logs": admin,
        "can_run_maintenance": admin,
    }
    return {
        "version": "0.261.300",
        "user": {
            "id": "admin-user" if admin else "dashboard-reader",
            "display_name": "Admin" if admin else "Dashboard Reader",
            "is_admin": admin,
            "roles": ["Admin"] if admin else ["User", "ControlCenterDashboardReader"],
        },
        "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
        "features": {"enable_chat_orchestration": True},
        "orchestration": {
            "enabled": True,
            "default_approval_mode": "manual",
            "timed_approval_seconds": 30,
            "allow_user_approval_override": False,
            "show_manual_controls": False,
            "max_steps": 6,
            "capabilities": [],
        },
        "control_center": capabilities,
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
    }


class DashboardFixture:
    def __init__(self, page: Page, admin=False):
        self.page = page
        self.admin = admin
        self.readiness = NOT_READY
        self.requests = []
        self.readiness_calls = 0
        self.chat_requests = []
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
            route.fulfill(json=bootstrap_payload(self.admin))
        elif path == "/api/user/settings" and request.method == "GET":
            route.fulfill(json={"settings": {}})
        elif is_notification_count(request.method, path):
            route.fulfill(json=notification_count_payload())
        elif path == "/api/admin/control-center/token-filters" and request.method == "GET":
            route.fulfill(json={"success": True, "filters": {
                "users": [{"id": "user-1", "label": "Jane Doe"}],
                "groups": [{"id": "group-1", "name": "Finance"}],
                "public_workspaces": [{"id": "workspace-1", "name": "Policies"}],
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
            route.fulfill(json=insights_payload())
        elif path == READINESS_PATH and request.method == "GET":
            self.readiness_calls += 1
            route.fulfill(json=self.readiness, headers={"Cache-Control": "no-store"})
        elif path == "/api/admin/control-center/activity-trends/export" and request.method == "POST":
            self.requests.append(("POST", path, json.loads(request.post_data or "{}")))
            route.fulfill(status=200, content_type="text/csv", body="date,count\n2026-10-01,3\n")
        elif path.startswith("/api/v2/control-center/activity"):
            # Where a chart drills through to: the Activity Logs section.
            self.requests.append((request.method, path, parsed.query))
            if path.endswith("/summary"):
                route.fulfill(json={"facets": [], "histogram": [], "bucket_days": 1, "sample_size": 0,
                                    "sample_limit": 5000, "truncated": False})
            else:
                route.fulfill(json={"items": [], "next_cursor": None, "snapshot": "fixture"})
        elif self.page.url.startswith(f"{ORIGIN}/v2/chat") and path.startswith("/api/"):
            # The chat page loads its own lists; empty answers keep it on a blank new chat.
            self.chat_requests.append(f"{request.method} {path}")
            route.fulfill(json=self._chat_answer(path))
        else:
            self.unexpected.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    @staticmethod
    def _chat_answer(path):
        if path in {"/api/get_messages", "/api/v2/chat/messages"}:
            return {"messages": []}
        if "conversation" in path:
            return {"conversations": [], "has_more": False, "next_cursor": None}
        return {}

    def open(self):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/dashboard", wait_until="networkidle")
        expect(self.page.get_by_role("heading", name="Most active")).to_be_visible()

    def section(self, name):
        return self.page.get_by_role("region", name=name, exact=True)

    def assert_clean(self):
        assert not self.unexpected, self.unexpected


@pytest.fixture
def dashboard_ui(page):
    fixture = DashboardFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def admin_dashboard_ui(page):
    fixture = DashboardFixture(page, admin=True)
    yield fixture
    fixture.assert_clean()


pytestmark = pytest.mark.ui


def test_reader_sees_defined_sections_and_named_rankings(dashboard_ui):
    dashboard_ui.open()
    page = dashboard_ui.page

    for name in ("Directory", "Sign-ins", "Conversations and documents", "Token usage", "Most active"):
        expect(dashboard_ui.section(name)).to_be_visible()

    sign_ins = dashboard_ui.section("Sign-ins")
    expect(sign_ins.get_by_text("People who signed in on Oct 7, 2026.", exact=True)).to_be_visible()
    expect(sign_ins.get_by_text("People who signed in during the 7 days ending Oct 7, 2026.", exact=True)).to_be_visible()
    expect(sign_ins.get_by_text("Up 2 (11.1%) from the previous 30 days", exact=True)).to_be_visible()
    expect(sign_ins.get_by_role("img", name="Daily sign-in counts.", exact=True)).to_be_visible()
    expect(sign_ins.get_by_role("table", name="Sign-ins by weekday and hour, UTC")).to_be_visible()
    expect(dashboard_ui.section("Conversations and documents").get_by_role(
        "img", name="Daily conversation creation counts.", exact=True,
    )).to_be_visible()

    tokens = dashboard_ui.section("Token usage")
    rankings = tokens.locator("ol")
    expect(rankings.get_by_text("Jane Doe", exact=True)).to_be_visible()
    expect(rankings.get_by_text("jane@contoso.com", exact=True)).to_be_visible()
    expect(rankings.get_by_text("Finance", exact=True)).to_be_visible()
    expect(rankings.get_by_text("Deleted group", exact=True)).to_be_visible()
    expect(rankings.get_by_title("ID user-1")).to_have_text("Jane Doe")
    expect(page.get_by_text("user-1", exact=True)).to_have_count(0)
    expect(page.get_by_text("group-1", exact=True)).to_have_count(0)

    # A dashboard reader cannot open Users, Groups or Activity Logs, so nothing links there.
    expect(page.get_by_role("link", name="Jane Doe")).to_have_count(0)
    for name in ("Directory", "Sign-ins", "Conversations and documents", "Token usage", "Most active"):
        expect(dashboard_ui.section(name).locator('a[href*="/control-center/"]')).to_have_count(0)
    expect(dashboard_ui.section("Directory").get_by_role("link", name="Pending approvals")).to_have_attribute(
        "href", "/v2/approvals",
    )
    expect(dashboard_ui.section("Directory").get_by_text("Uploads disabled: 2", exact=True)).to_be_visible()
    expect(dashboard_ui.section("Directory").get_by_text("Inactive: 0", exact=True)).to_have_count(0)


def test_token_filters_live_in_token_usage_and_change_only_token_figures(dashboard_ui):
    dashboard_ui.open()
    page = dashboard_ui.page
    tokens = dashboard_ui.section("Token usage")

    expect(tokens.get_by_text("These filters change only the token figures in this section.")).to_be_visible()
    expect(dashboard_ui.section("Sign-ins").locator("select")).to_have_count(0)
    expect(dashboard_ui.section("Conversations and documents").locator("select")).to_have_count(0)
    model = tokens.get_by_label("Model", exact=True)
    expect(model).to_have_value("")
    with page.expect_request(lambda request: "/dashboard/insights" in request.url and "model=gpt-4o" in request.url):
        model.select_option("gpt-4o")
    expect(tokens.get_by_text("Tokens matching model gpt-4o.", exact=True)).to_be_visible()
    tokens.get_by_role("button", name="Clear filters").click()
    expect(model).to_have_value("")
    expect(tokens.get_by_role("button", name="Clear filters")).to_have_count(0)


def test_admin_links_and_chart_drillthrough_follow_capabilities_and_filters(admin_dashboard_ui):
    ui = admin_dashboard_ui
    ui.open()
    page = ui.page

    expect(page.get_by_role("link", name="Jane Doe").first).to_have_attribute(
        "href", "/v2/control-center/users?user_id=user-1",
    )
    expect(ui.section("Token usage").get_by_role("link", name="Finance")).to_have_attribute(
        "href", "/v2/control-center/groups?id=group-1",
    )
    expect(ui.section("Token usage").get_by_role("link", name="Deleted group")).to_have_count(0)
    expect(ui.section("Directory").get_by_role("link", name="Uploads disabled: 2")).to_have_attribute(
        "href", "/v2/control-center/groups?status=upload_disabled",
    )
    expect(ui.section("Directory").get_by_role("link", name="Groups", exact=True)).to_have_attribute(
        "href", "/v2/control-center/groups",
    )
    expect(ui.section("Sign-ins").get_by_role("link").first).to_have_attribute(
        "href", "/v2/control-center/users?last_login=30",
    )

    ui.section("Token usage").get_by_label("User", exact=True).select_option("user-1")
    tokens_used = ui.section("Token usage").get_by_role("link").filter(has_text="Tokens used")
    expect(tokens_used).to_have_attribute("href", f"/v2/control-center/activity-logs?activity_type=token_usage&start_date={START}&end_date={TODAY}&user_id=user-1")

    chart = ui.section("Sign-ins").get_by_role("img", name="Daily sign-in counts. Select a point to open the matching activity logs.")
    box = chart.bounding_box()
    assert box is not None
    chart.click(position={"x": box["width"] * 0.5, "y": box["height"] * 0.5})
    expect(page).to_have_url(re.compile(r"/v2/control-center/activity-logs\?"))
    query = parse_qs(urlsplit(page.url).query)
    assert query["activity_type"] == ["user_login"]
    assert query["date"][0] in DAYS

    # A click on one segment of a stacked bar opens that series, not the first one at that date.
    page.go_back()
    uploads = ui.section("Conversations and documents").get_by_role("img", name=re.compile(r"^Daily document uploads"))
    uploads.scroll_into_view_if_needed()
    page.wait_for_function("""() => {
        const canvas = [...document.querySelectorAll('canvas')]
            .find((item) => (item.getAttribute('aria-label') || '').startsWith('Daily document uploads'));
        return Boolean(canvas && window.Chart && window.Chart.getChart(canvas));
    }""")
    segment = page.evaluate("""() => {
        const canvas = [...document.querySelectorAll('canvas')]
            .find((item) => (item.getAttribute('aria-label') || '').startsWith('Daily document uploads'));
        const bar = window.Chart.getChart(canvas).getDatasetMeta(1).data[2].getProps(['x', 'y', 'base'], true);
        return { x: bar.x, y: (bar.y + bar.base) / 2 };
    }""")
    uploads.click(position=segment)
    expect(page).to_have_url(re.compile(r"activity_type=document_creation"))
    query = parse_qs(urlsplit(page.url).query)
    assert query["workspace_type"] == ["group"]
    assert query["date"] == [TODAY]


def test_range_refresh_and_export_use_the_dashboard_apis(dashboard_ui):
    dashboard_ui.open()
    page = dashboard_ui.page

    page.get_by_label("Date range").select_option("7")
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    page.get_by_role("button", name="Refresh").click()
    expect(page.get_by_role("heading", name="Most active")).to_be_visible()
    summary_queries = [query for method, path, query in dashboard_ui.requests
                       if method == "GET" and path == "/api/v2/control-center/dashboard/summary"]
    assert any("force_refresh=1" in query for query in summary_queries)
    assert not any(path == "/api/admin/control-center/activity-trends" for _method, path, _query in dashboard_ui.requests)

    with page.expect_download():
        page.get_by_role("button", name="Export").click()
    export = next(body for method, path, body in dashboard_ui.requests if method == "POST")
    assert export["time_window"] == "custom"


def test_dashboard_chat_lists_requirements_until_they_are_met(dashboard_ui):
    dashboard_ui.open()
    page = dashboard_ui.page

    page.get_by_role("button", name="Chat with this dashboard").click()
    dialog = page.get_by_role("dialog", name="Set up dashboard chat")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("3 of 4 requirements need set-up before dashboard chat can run.")).to_be_visible()
    rows = dialog.get_by_role("list", name="Dashboard chat requirements").get_by_role("listitem")
    expect(rows).to_have_count(4)
    expect(rows.nth(0)).to_contain_text("Needs set-up")
    expect(rows.nth(1)).to_contain_text("Ready")
    expect(rows.nth(0).get_by_role("link", name="Open the setting")).to_have_attribute(
        "href", "/v2/admin/settings/agents-config",
    )
    # An unexpected link from the server is dropped rather than rendered.
    expect(rows.nth(2).get_by_role("link")).to_have_count(0)
    expect(rows.nth(3).get_by_role("link", name="Open the setting")).to_have_attribute(
        "href", "/v2/admin/actions/new?type=control_center",
    )
    expect(dialog.get_by_role("button", name="Start chat")).to_be_disabled()

    dashboard_ui.readiness = READY
    dialog.get_by_role("button", name="Check again").click()
    expect(dialog.get_by_text("Everything is ready. Start the chat to open it with a prompt about this dashboard.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Start chat")).to_be_enabled()
    assert dashboard_ui.readiness_calls == 2


def test_ready_dashboard_chat_opens_an_orchestrated_chat_with_the_prompt(dashboard_ui):
    dashboard_ui.readiness = READY
    dashboard_ui.open()
    page = dashboard_ui.page

    dashboard_ui.section("Token usage").get_by_label("Model", exact=True).select_option("gpt-4o")
    expect(dashboard_ui.section("Token usage").get_by_text("Tokens matching model gpt-4o.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Chat with this dashboard").click()
    expect(page).to_have_url(re.compile(r"/v2/chat"))
    composer = page.get_by_placeholder(COMPOSER_PLACEHOLDER)
    expect(composer).to_have_value(
        "Using the Usage insights action, help me understand the SimpleChat Control Center dashboard "
        f"for {START} to {TODAY} (UTC). Summarize sign-ins and active users, conversations, document "
        "uploads and token usage, compare them with the previous period of the same length, call out "
        "anything unusual, and chart the daily trends. For token usage, use the same filters as the "
        "dashboard: model gpt-4o."
    )
    expect(page.get_by_role("button", name="Orchestrate")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not any(entry.startswith("POST") for entry in dashboard_ui.chat_requests), dashboard_ui.chat_requests

    # The prompt travels in router state only, so a reload does not apply it again.
    page.reload(wait_until="networkidle")
    expect(page.get_by_placeholder(COMPOSER_PLACEHOLDER)).to_have_value("")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-m", "ui"]))
