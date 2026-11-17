#!/usr/bin/env python3
# test_v2_control_center_refresh.py
"""
Browser coverage for the V2 Control Center "Refresh data" strip.
Version: 0.261.445
Implemented in: 0.261.445

The Users and Groups views read stored snapshots of each user's and group's activity, which a
refresh recalculates. The classic Control Center had a button for it and a readout of the last
refresh and the daily schedule; V2 had neither, only a link to the classic page. Exercise the
built application with the refresh routes intercepted: the strip shows when the data was last
refreshed and when it runs next; Refresh data calls the route once, shows a busy state, says
what it covered, re-reads the status and reloads the section on screen; a refresh that skipped
people is a warning rather than a success; a failure is reported and reloads nothing; a
dashboard reader, who the server refuses, sees no strip; and the strip never overflows a phone.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v2_control_center_dashboard import ORIGIN, DashboardFixture  # noqa: E402

pytestmark = pytest.mark.ui

STATUS_PATH = "/api/admin/control-center/refresh-status"
REFRESH_PATH = "/api/admin/control-center/refresh"
SUMMARY_PATH = "/api/v2/control-center/dashboard/summary"
ACTIVITY_PATH = "/api/v2/control-center/activity-logs"

STATUS = {
    "last_refresh": "2026-10-06T10:30:00+00:00",
    "last_refresh_formatted": "10/06/2026 10:30 AM UTC",
    "auto_refresh_enabled": True,
    "auto_refresh_time": "02:00",
    "auto_refresh_timezone": "UTC",
    "auto_refresh_next_run_utc": "2026-10-08T02:00:00+00:00",
}
CLEAN = {
    "success": True,
    "message": "Control Center data refreshed successfully",
    "refreshed_users": 5,
    "failed_users": 0,
    "refreshed_groups": 2,
    "failed_groups": 0,
    "refresh_timestamp": "2026-10-07T12:00:00+00:00",
}


class RefreshFixture(DashboardFixture):
    """The dashboard fixture plus the two refresh routes, answering from memory."""

    def __init__(self, page, admin=True):
        self.status = dict(STATUS)
        self.status_calls = 0
        self.refresh_calls = []
        self.refresh_status = 200
        self.refresh_response = dict(CLEAN)
        self.hold = False
        self.held = []
        self.activity_loads = 0
        super().__init__(page, admin=admin)

    def _route(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == STATUS_PATH and request.method == "GET":
            self.status_calls += 1
            route.fulfill(json=self.status)
        elif path == REFRESH_PATH and request.method == "POST":
            self.refresh_calls.append(json.loads(request.post_data or "{}"))
            if self.hold:
                self.held.append(route)
            else:
                route.fulfill(status=self.refresh_status, json=self.refresh_response)
        else:
            if path == ACTIVITY_PATH and request.method == "GET":
                self.activity_loads += 1
            super()._route(route)

    def release(self):
        self.hold = False
        while self.held:
            self.held.pop(0).fulfill(status=self.refresh_status, json=self.refresh_response)

    def summaries(self):
        return [query for method, path, query in self.requests if path == SUMMARY_PATH]

    def strip(self):
        return self.page.get_by_test_id("control-center-refresh")


@pytest.fixture
def refresh_ui(page):
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    fixture = RefreshFixture(page, admin=True)
    fixture.console_errors = errors
    yield fixture
    fixture.assert_clean()
    unexpected = [error for error in errors if "status of 500" not in error]
    assert not unexpected, unexpected


@pytest.fixture
def reader_ui(page):
    fixture = RefreshFixture(page, admin=False)
    yield fixture
    fixture.assert_clean()


def test_the_strip_says_when_data_was_last_refreshed_and_when_it_runs_next(refresh_ui):
    ui = refresh_ui
    ui.open()
    strip = ui.strip()

    expect(strip.get_by_text(re.compile(r"^Data last refreshed .* \(.*\)\.$"))).to_be_visible()
    expect(strip.get_by_text(re.compile(r"^Automatic refresh daily at .* UTC; next .*\.$"))).to_be_visible()
    expect(strip.get_by_role("button", name="Refresh data", exact=True)).to_be_enabled()
    assert ui.status_calls == 1
    assert ui.refresh_calls == []


def test_refreshing_shows_progress_says_what_it_covered_and_reloads_the_section(refresh_ui):
    ui = refresh_ui
    ui.open()
    page = ui.page
    strip = ui.strip()
    button = strip.get_by_role("button")
    ui.hold = True
    before = len(ui.summaries())

    button.click()
    expect(button).to_have_attribute("aria-busy", "true")
    expect(button).to_have_text("Refreshing data…")
    # A second click while it works is ignored rather than starting another run. The button stays
    # focusable (aria-disabled), so Playwright needs force to click it the way a keyboard user could.
    button.click(force=True)
    expect(page.get_by_role("status").filter(has_text="Data refreshed")).to_have_count(0)
    assert ui.refresh_calls == [{}]

    ui.status = {**STATUS, "last_refresh": "2026-10-07T12:00:00+00:00"}
    with page.expect_request(
        lambda request: SUMMARY_PATH in request.url and "force_refresh=1" in request.url,
    ):
        ui.release()
    expect(strip.get_by_role("status")).to_have_text("Data refreshed. Updated 5 users and 2 groups.")
    expect(button).not_to_have_attribute("aria-busy", "true")
    expect(button).to_have_text("Refresh data")
    assert ui.refresh_calls == [{}], "The second click must not start a second run."
    assert ui.status_calls == 2, "The status is read again once the run has finished."
    assert len(ui.summaries()) > before
    assert any(parse_qs(query).get("force_refresh") == ["1"] for query in ui.summaries()[before:])


def test_a_refresh_that_skipped_people_is_a_warning_that_stays(refresh_ui):
    ui = refresh_ui
    ui.refresh_response = {**CLEAN, "failed_users": 1, "failed_groups": 3}
    ui.open()
    strip = ui.strip()

    strip.get_by_role("button").click()
    message = strip.get_by_role("status")
    expect(message).to_have_text(
        "Data refreshed with problems. Updated 5 users and 2 groups; 1 user and 3 groups could not be refreshed."
    )
    expect(message.locator("p")).to_have_class(re.compile("text-warn"))
    # A problem stays until the next run; only a clean result clears itself.
    ui.page.wait_for_timeout(500)
    expect(message).to_contain_text("could not be refreshed")


def test_a_failed_refresh_is_reported_and_reloads_nothing(refresh_ui):
    ui = refresh_ui
    ui.refresh_status = 500
    ui.refresh_response = {"success": False, "error": "Data refreshed, but the refresh timestamp could not be saved."}
    ui.open()
    strip = ui.strip()
    before = len(ui.summaries())

    strip.get_by_role("button").click()
    expect(strip.get_by_role("alert")).to_have_text("Data refreshed, but the refresh timestamp could not be saved.")
    expect(strip.get_by_role("button")).to_have_text("Refresh data")
    assert len(ui.summaries()) == before, "A failed refresh must not reload the section as if it had worked."
    assert ui.status_calls == 1

    # Trying again after the cause is fixed clears the failure.
    ui.refresh_status = 200
    ui.refresh_response = dict(CLEAN)
    strip.get_by_role("button").click()
    expect(strip.get_by_role("alert")).to_have_count(0)
    expect(strip.get_by_role("status")).to_have_text("Data refreshed. Updated 5 users and 2 groups.")


def test_an_answer_that_does_not_say_it_finished_is_not_called_a_success(refresh_ui):
    ui = refresh_ui
    ui.refresh_response = {"message": "queued"}
    ui.open()
    strip = ui.strip()

    strip.get_by_role("button").click()
    expect(strip.get_by_role("alert")).to_have_text("The refresh did not report that it finished.")
    expect(strip.get_by_role("status")).to_have_text("")


def test_a_status_that_cannot_be_read_does_not_hide_the_action(refresh_ui):
    ui = refresh_ui
    ui.status = ["not", "an", "object"]
    ui.open()
    strip = ui.strip()

    expect(strip.get_by_role("alert")).to_have_text("The refresh status was not in a form this page understands.")
    expect(strip.get_by_role("button", name="Refresh data", exact=True)).to_be_enabled()


def test_other_sections_reload_too(refresh_ui):
    ui = refresh_ui
    ui.open()
    page = ui.page
    page.goto(f"{ORIGIN}/v2/control-center/activity-logs", wait_until="networkidle")
    expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_visible()
    before = ui.activity_loads

    with page.expect_request(lambda request: urlsplit(request.url).path == ACTIVITY_PATH):
        ui.strip().get_by_role("button").click()
    expect(ui.strip().get_by_role("status")).to_have_text("Data refreshed. Updated 5 users and 2 groups.")
    assert ui.activity_loads > before, "The activity log should be read again after a refresh"


def test_a_dashboard_reader_is_not_offered_a_refresh_the_server_would_refuse(reader_ui):
    ui = reader_ui
    ui.open()

    expect(ui.strip()).to_have_count(0)
    expect(ui.page.get_by_role("button", name=re.compile("^Refresh data"))).to_have_count(0)
    assert ui.status_calls == 0 and ui.refresh_calls == []


@pytest.mark.parametrize("width", [390, 1440])
def test_the_strip_fits_the_screen(refresh_ui, width):
    ui = refresh_ui
    ui.page.set_viewport_size({"width": width, "height": 900})
    ui.open()
    page = ui.page
    ui.page.set_viewport_size({"width": width, "height": 900})

    strip = ui.strip()
    expect(strip.get_by_role("button", name="Refresh data", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    overflow = strip.evaluate("element => element.scrollWidth - element.clientWidth")
    assert overflow <= 1, f"The strip overflows by {overflow}px at {width}px"
