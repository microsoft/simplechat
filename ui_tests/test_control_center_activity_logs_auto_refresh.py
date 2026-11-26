# test_control_center_activity_logs_auto_refresh.py
"""
UI test for Control Center Activity Logs auto-refresh.

Version: 0.261.489
Implemented in: 0.241.028; restored in 0.261.489

This test ensures that admins can enable Activity Logs auto-refresh, adjust the
interval, keep the choice across reloads, and that polling pauses when the tab is
left, access is lost, or requests keep failing. It runs the shipped JavaScript
and toolbar markup in a local browser page, so it needs no running SimpleChat.
"""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
ORIGIN = "http://activity-logs.test"


def toolbar_markup():
    """Return the shipped toolbar, which contains no Jinja expressions."""
    template = (APP_DIR / "templates" / "control_center.html").read_text(encoding="utf-8")
    match = re.search(
        r'<div class="activity-log-auto-refresh-toolbar.*?(?=<div id="runtimeUsagePanel")',
        template,
        re.DOTALL,
    )
    assert match, "The auto-refresh toolbar is missing from control_center.html."
    assert "{{" not in match.group(0) and "{%" not in match.group(0)
    return match.group(0)


def page_html():
    return f"""<!doctype html><html><body>
    <button id="activity-logs-tab">Activity Logs</button>
    <div id="activity-logs" class="active">
        <input id="activityLogsSearchInput">
        <button id="refreshActivityLogsBtn">Reload</button>
        {toolbar_markup()}
        <table id="activityLogsTable"><tbody id="activityLogsTableBody"></tbody></table>
        <div id="activityLogsPaginationInfo"></div><ul id="activityLogsPagination"></ul>
    </div>
    <script type="module" src="/static/js/control-center.js"></script></body></html>"""


class ActivityLogsServer:
    """Serve the page and count Activity Logs requests."""

    def __init__(self, page):
        self.requests = []
        self.status = 200
        self.held = None
        self.hold_next = False
        page.route(f"{ORIGIN}/**", self.handle)

    def handle(self, route):
        url = route.request.url
        if "/static/js/" in url:
            route.fulfill(
                content_type="text/javascript",
                body=(APP_DIR / url[len(ORIGIN) + 1:].split("?")[0]).read_text(encoding="utf-8"),
            )
        elif "/control-center/activity-logs?" in url:
            self.requests.append(url)
            if self.hold_next:
                self.hold_next = False
                self.held = route
                return
            self.answer(route, f"user-{len(self.requests)}")
        elif "/api/" in url:
            route.fulfill(content_type="application/json", body='{"success": false}')
        else:
            route.fulfill(content_type="text/html", body=page_html())

    def answer(self, route, user):
        body = {"error": "refused"} if self.status != 200 else {
            "logs": [{
                "id": user, "timestamp": "2026-05-16T18:41:38Z", "activity_type": "user_login",
                "user_id": user, "workspace_type": "personal",
            }],
            "user_map": {user: {"email": f"{user}@example.com", "display_name": user}},
            "pagination": {
                "page": 1, "per_page": 50, "total_items": 1, "total_pages": 1,
                "has_prev": False, "has_next": False,
            },
        }
        route.fulfill(status=self.status, content_type="application/json", body=json.dumps(body))

    def wait_for(self, page, count):
        for _ in range(100):
            if len(self.requests) >= count:
                return
            page.wait_for_timeout(50)
        raise AssertionError(f"Expected {count} Activity Logs requests, saw {len(self.requests)}.")


@pytest.fixture
def server(page):
    stub = ActivityLogsServer(page)
    page.goto(ORIGIN)
    page.wait_for_function("() => Boolean(window.controlCenter)")
    return stub


def toggle(page):
    return page.locator("#activityLogsAutoRefreshToggle")


def status(page):
    return page.locator("#activityLogsAutoRefreshStatus")


def enable_every_second(page):
    page.locator("[data-activity-logs-refresh-preset='1']").click()
    toggle(page).check()


@pytest.mark.ui
def test_enable_poll_and_persist(page, server):
    expect(toggle(page)).not_to_be_checked()
    expect(page.locator("#activityLogsAutoRefreshIntervalInput")).to_have_value("30")
    page.locator("#refreshActivityLogsBtn").click()
    server.wait_for(page, 1)
    page.wait_for_timeout(1300)
    assert len(server.requests) == 1, "Nothing may poll while auto-refresh is off."

    enable_every_second(page)
    expect(status(page)).to_contain_text("Every 1 sec")
    server.wait_for(page, 4)

    page.locator("#activityLogsAutoRefreshIntervalInput").fill("300")
    expect(page.locator("#activityLogsAutoRefreshIntervalValue")).to_have_text("5 min")
    page.locator("#activityLogsAutoRefreshIntervalInput").fill("")
    expect(page.locator("#activityLogsAutoRefreshIntervalValue")).to_have_text("5 min")

    page.reload()
    page.wait_for_function("() => Boolean(window.controlCenter)")
    expect(toggle(page)).to_be_checked()
    expect(page.locator("#activityLogsAutoRefreshIntervalInput")).to_have_value("300")


@pytest.mark.ui
def test_polling_stops_when_the_tab_is_left(page, server):
    enable_every_second(page)
    server.wait_for(page, 2)
    page.evaluate("document.getElementById('activity-logs').classList.remove('active')")
    page.wait_for_timeout(300)
    seen = len(server.requests)
    page.wait_for_timeout(1800)
    assert len(server.requests) == seen
    expect(status(page)).to_have_text("Auto-refresh paused")


@pytest.mark.ui
def test_losing_access_turns_polling_off(page, server):
    enable_every_second(page)
    server.wait_for(page, 1)
    server.status = 403
    expect(status(page)).to_have_text("Auto-refresh paused because access changed.")
    expect(toggle(page)).not_to_be_checked()


@pytest.mark.ui
def test_three_failures_turn_polling_off(page, server):
    server.status = 500
    enable_every_second(page)
    expect(status(page)).to_have_text("Auto-refresh paused after repeated refresh errors.", timeout=8000)
    assert len(server.requests) == 3


@pytest.mark.ui
def test_a_search_replaces_a_refresh_still_running(page, server):
    server.hold_next = True
    page.locator("#refreshActivityLogsBtn").click()
    server.wait_for(page, 1)
    page.locator("#activityLogsSearchInput").fill("ada")
    server.wait_for(page, 2)
    assert "search=ada" in server.requests[-1]
    expect(page.locator("#activityLogsTableBody")).to_contain_text("user-2")
    server.answer(server.held, "stale-user")
    page.wait_for_timeout(300)
    expect(page.locator("#activityLogsTableBody")).not_to_contain_text("stale-user")
