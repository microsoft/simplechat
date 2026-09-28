# test_v2_workflow_calendar_schedules.py
"""
UI tests for calendar schedules in the native V2 workflow editor, in both workflow scopes.
Version: 0.261.193
Implemented in: 0.261.193

These tests use the real V2 SPA bundle with the closed workflow fixture, whose save routes validate
each schedule with the server's `_normalize_schedule` and the administrator's minimum interval,
and whose editor options carry the server's schedule choices and IANA time zone list. They cover:

* "Mondays 08:00 America/New_York" chosen in a new personal and a new group workflow: the browser's
  zone is the default, the preview and the list read the schedule, the save sends the calendar
  schedule the server stores, and the workflow reopens with the same fields and saves an edit;
* stored calendar schedules (a personal month-end schedule and a group File Sync monitor on
  weekdays) opening as saved and re-saving byte for byte;
* a browser zone the server does not list, which starts the schedule in UTC with a note;
* calendar problems named before saving with the server's messages;
* the administrator's minimum, which refuses a new or changed interval but leaves a saved interval
  and every calendar schedule alone.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import (  # noqa: E402
    GROUP_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from functions_workflow_schedules import (  # noqa: E402  (the server's reviewed messages)
    SCHEDULE_DAYS_REQUIRED_ERROR,
    SCHEDULE_TIME_ERROR,
    SCHEDULE_TIMEZONE_ERROR,
)
from test_v2_group_workflow_file_sync import (  # noqa: E402  (shared record and page helpers)
    MONITOR_ID,
    labelled,
    monitored_workflow,
    open_group_workflows,
    workflow_post,
)


pytestmark = pytest.mark.ui
MONDAYS_NEW_YORK = {
    "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "day_of_month": None,
    "time_of_day": "08:00", "timezone": "America/New_York",
}
MONTH_END_TOKYO = {
    "kind": "calendar", "frequency": "monthly", "days_of_week": [], "day_of_month": 31,
    "time_of_day": "18:00", "timezone": "Asia/Tokyo",
}
WEEKDAYS_LONDON = {
    "kind": "calendar", "frequency": "weekdays", "days_of_week": [], "day_of_month": None,
    "time_of_day": "07:30", "timezone": "Europe/London",
}
HOURLY_MINIMUM = (
    "This schedule runs more often than the administrator allows. Choose an interval of at least 1 hour."
)
ZONE_NOTE = "Your browser's time zone, Europe/Berlin, isn't available, so this schedule starts in UTC."
DST_NOTE = "Runs follow local time in this zone, including daylight saving changes."
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def save(page):
    page.get_by_role("button", name="Save workflow", exact=True).click()


def open_scope(ui, scope):
    if scope == "group":
        open_group_workflows(ui)
    else:
        ui.open("/workspace/workflows")
        expect(ui.page.get_by_role("button", name="Create workflow", exact=True)).to_be_visible()


def start_workflow(page, name):
    """Open a new workflow with a valid runner and task, on the Interval trigger."""
    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    labelled(page, "Workflow name").fill(name)
    labelled(page, "Model").select_option(label="Workspace GPT · aoai")
    labelled(page, "Instructions").first.fill("Summarize this week's updates.")
    labelled(page, "Trigger").select_option("interval")


def preview(page, label):
    """The editor's reading of a calendar schedule."""
    return page.get_by_text(f"Schedule: {label}. {DST_NOTE}", exact=True)


def listed(page, label):
    """The workflow list's reading of a schedule."""
    return page.get_by_text(f"Schedule: {label}", exact=True)


def day(page, name):
    return page.get_by_role("checkbox", name=name, exact=True)


def status(page, message):
    return page.get_by_role("status").filter(has_text=message)


def expect_days(page, chosen):
    for name in WEEKDAYS:
        if name in chosen:
            expect(day(page, name)).to_be_checked()
        else:
            expect(day(page, name)).not_to_be_checked()


@pytest.mark.browser_context_args(timezone_id="America/New_York")
@pytest.mark.parametrize("scope", ["personal", "group"])
def test_mondays_at_eight_in_new_york_saves_lists_and_reopens(workflow_ui, scope):
    ui, page = workflow_ui, workflow_ui.page
    open_scope(ui, scope)
    start_workflow(page, "Monday digest")
    repeats = labelled(page, "Repeats")
    expect(repeats).to_have_value("interval")
    expect(labelled(page, "Interval value")).to_have_value("15")

    repeats.select_option("weekly")
    expect(page.get_by_role("group", name="Days of the week", exact=True)).to_be_visible()
    expect_days(page, {"Monday"})
    expect(labelled(page, "Interval value")).to_have_count(0)
    expect(labelled(page, "Time")).to_have_value("09:00")
    # A new calendar schedule starts in the browser's zone, which the server lists.
    expect(labelled(page, "Time zone")).to_have_value("America/New_York")
    expect(page.get_by_text("isn't available, so this schedule starts in UTC", exact=False)).to_have_count(0)
    labelled(page, "Time").fill("08:00")
    expect(preview(page, "Mondays 08:00 America/New_York")).to_be_visible()

    save(page)
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    write = workflow_post(ui)
    assert write.path == ("/api/group/workflows" if scope == "group" else "/api/user/workflows")
    if scope == "group":
        assert write.body["group_id"] == GROUP_ID
    assert write.body["trigger_type"] == "interval"
    assert write.body["schedule"] == MONDAYS_NEW_YORK
    expect(listed(page, "Mondays 08:00 America/New_York")).to_be_visible()

    page.get_by_role("button", name="Edit Monday digest", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(dialog).to_be_visible()
    expect(labelled(page, "Trigger")).to_have_value("interval")
    expect(labelled(page, "Repeats")).to_have_value("weekly")
    expect_days(page, {"Monday"})
    expect(labelled(page, "Time")).to_have_value("08:00")
    expect(labelled(page, "Time zone")).to_have_value("America/New_York")
    expect(preview(page, "Mondays 08:00 America/New_York")).to_be_visible()
    # Trying another cadence and coming back keeps the chosen days, time and zone.
    labelled(page, "Repeats").select_option("daily")
    expect(preview(page, "Daily 08:00 America/New_York")).to_be_visible()
    labelled(page, "Repeats").select_option("weekly")
    expect_days(page, {"Monday"})
    day(page, "Wednesday").check()
    expect(preview(page, "Mondays and Wednesdays 08:00 America/New_York")).to_be_visible()

    save(page)
    expect(dialog).to_have_count(0)
    assert len(ui.workflow_writes) == 2
    edited = workflow_post(ui).body
    assert edited["definition_revision"]
    assert edited["schedule"] == {**MONDAYS_NEW_YORK, "days_of_week": ["monday", "wednesday"]}
    expect(listed(page, "Mondays and Wednesdays 08:00 America/New_York")).to_be_visible()


@pytest.mark.browser_context_args(timezone_id="America/New_York")
@pytest.mark.parametrize("scope", ["personal", "group"])
def test_a_stored_calendar_schedule_opens_as_saved_and_resaves_unchanged(workflow_ui, scope):
    ui, page = workflow_ui, workflow_ui.page
    if scope == "group":
        stored = WEEKDAYS_LONDON
        record = monitored_workflow()
        record["schedule"] = copy.deepcopy(stored)
        ui.group_workflows[GROUP_ID][MONITOR_ID] = record
        name, listing, cadence = "Monitor finance drops", "Monitor File Sync: Weekdays 07:30 Europe/London", "weekdays"
        reading, zone, at = "Weekdays 07:30 Europe/London", "Europe/London", "07:30"
    else:
        stored = MONTH_END_TOKYO
        ui.personal_workflows[WORKFLOW_ID].update(trigger_type="interval", schedule=copy.deepcopy(stored))
        name, listing, cadence = "Quarterly review workflow", "Monthly on day 31 (or last day), 18:00 Asia/Tokyo", "monthly"
        reading, zone, at = listing, "Asia/Tokyo", "18:00"
    open_scope(ui, scope)
    expect(listed(page, listing)).to_be_visible()

    page.get_by_role("button", name=f"Edit {name}", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(dialog).to_be_visible()
    expect(labelled(page, "Repeats")).to_have_value(cadence)
    expect(labelled(page, "Time")).to_have_value(at)
    expect(labelled(page, "Time zone")).to_have_value(zone)
    expect(preview(page, reading)).to_be_visible()
    expect(page.get_by_role("group", name="Days of the week", exact=True)).to_have_count(0)
    if scope == "personal":
        expect(labelled(page, "Day of the month")).to_have_value("31")
        expect(labelled(page, "Day of the month")).to_have_accessible_description(
            "Months without this day run on their last day.",
        )
    else:
        expect(labelled(page, "Day of the month")).to_have_count(0)
    # A stored schedule is the author's choice, so the browser's zone is never offered in its place.
    expect(page.get_by_text("isn't available, so this schedule starts in UTC", exact=False)).to_have_count(0)

    labelled(page, "Description").first.fill("Edited without touching the schedule.")
    save(page)
    expect(dialog).to_have_count(0)
    body = workflow_post(ui).body
    assert body["description"] == "Edited without touching the schedule."
    assert body["schedule"] == stored
    expect(listed(page, listing)).to_be_visible()


@pytest.mark.browser_context_args(timezone_id="Europe/Berlin")
def test_a_browser_zone_the_server_does_not_list_starts_in_utc_with_a_note(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.unlisted_schedule_timezones = {"Europe/Berlin"}
    open_scope(ui, "personal")
    start_workflow(page, "Berlin digest")
    labelled(page, "Repeats").select_option("daily")
    zone = labelled(page, "Time zone")
    expect(zone).to_have_value("UTC")
    note = status(page, ZONE_NOTE)
    expect(note).to_be_visible()
    expect(note).to_contain_text("Choose the time zone it should follow.")
    expect(zone).to_have_accessible_description(re.compile(re.escape(ZONE_NOTE)))
    expect(preview(page, "Daily 09:00 UTC")).to_be_visible()

    # The browser's zone is still refused, because the server cannot run it.
    zone.fill("Europe/Berlin")
    expect(note).to_have_count(0)
    expect(status(page, SCHEDULE_TIMEZONE_ERROR)).to_be_visible()
    zone.fill("Europe/Paris")
    expect(status(page, SCHEDULE_TIMEZONE_ERROR)).to_have_count(0)
    save(page)
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    assert workflow_post(ui).body["schedule"] == {
        "kind": "calendar", "frequency": "daily", "days_of_week": [], "day_of_month": None,
        "time_of_day": "09:00", "timezone": "Europe/Paris",
    }


@pytest.mark.browser_context_args(timezone_id="America/New_York")
def test_calendar_problems_are_named_before_saving_with_the_server_messages(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    open_scope(ui, "personal")
    start_workflow(page, "Friday wrap-up")
    labelled(page, "Repeats").select_option("weekly")
    day(page, "Monday").uncheck()
    expect(status(page, SCHEDULE_DAYS_REQUIRED_ERROR)).to_be_visible()
    save(page)
    expect(page.get_by_role("alert").filter(has_text=SCHEDULE_DAYS_REQUIRED_ERROR)).to_be_visible()
    assert not ui.workflow_writes

    day(page, "Friday").check()
    expect(status(page, SCHEDULE_DAYS_REQUIRED_ERROR)).to_have_count(0)
    labelled(page, "Time").fill("")
    expect(status(page, SCHEDULE_TIME_ERROR)).to_be_visible()
    labelled(page, "Time").fill("17:45")
    # Zone names are exact, as the server matches them.
    labelled(page, "Time zone").fill("america/new_york")
    expect(status(page, SCHEDULE_TIMEZONE_ERROR)).to_be_visible()
    save(page)
    expect(page.get_by_role("alert").filter(has_text=SCHEDULE_TIMEZONE_ERROR)).to_be_visible()
    assert not ui.workflow_writes

    labelled(page, "Time zone").fill("America/New_York")
    expect(status(page, SCHEDULE_TIMEZONE_ERROR)).to_have_count(0)
    save(page)
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    assert workflow_post(ui).body["schedule"] == {
        **MONDAYS_NEW_YORK, "days_of_week": ["friday"], "time_of_day": "17:45",
    }
    expect(listed(page, "Fridays 17:45 America/New_York")).to_be_visible()


@pytest.mark.browser_context_args(timezone_id="America/New_York")
def test_the_minimum_leaves_a_saved_interval_alone_but_refuses_a_changed_one(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.min_schedule_interval_seconds = 3600
    # Saved before the administrator raised the minimum: every 30 minutes.
    ui.personal_workflows[WORKFLOW_ID]["trigger_type"] = "interval"
    open_scope(ui, "personal")
    expect(listed(page, "Every 30 minutes")).to_be_visible()

    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(labelled(page, "Interval value")).to_have_value("30")
    labelled(page, "Description").first.fill("Still every 30 minutes.")
    expect(status(page, HOURLY_MINIMUM)).to_have_count(0)
    save(page)
    expect(dialog).to_have_count(0)
    assert workflow_post(ui).body["schedule"] == {"unit": "minutes", "value": 30}

    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    labelled(page, "Interval value").fill("45")
    expect(status(page, HOURLY_MINIMUM)).to_be_visible()
    save(page)
    expect(page.get_by_role("alert").filter(has_text=HOURLY_MINIMUM)).to_be_visible()
    assert len(ui.workflow_writes) == 1

    labelled(page, "Interval unit").select_option("hours")
    labelled(page, "Interval value").fill("1")
    expect(status(page, HOURLY_MINIMUM)).to_have_count(0)
    save(page)
    expect(dialog).to_have_count(0)
    assert workflow_post(ui).body["schedule"] == {"unit": "hours", "value": 1}
    expect(listed(page, "Every hour")).to_be_visible()


@pytest.mark.browser_context_args(timezone_id="America/New_York")
def test_the_minimum_refuses_a_new_group_interval_but_not_a_calendar_schedule(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.min_schedule_interval_seconds = 3600
    open_scope(ui, "group")
    start_workflow(page, "Group standup digest")
    # A new workflow starts on every 15 minutes, below the administrator's hour.
    expect(status(page, HOURLY_MINIMUM)).to_be_visible()
    save(page)
    expect(page.get_by_role("alert").filter(has_text=HOURLY_MINIMUM)).to_be_visible()
    assert not ui.workflow_writes

    labelled(page, "Repeats").select_option("weekdays")
    expect(status(page, HOURLY_MINIMUM)).to_have_count(0)
    expect(preview(page, "Weekdays 09:00 America/New_York")).to_be_visible()
    save(page)
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["group_id"] == GROUP_ID
    assert body["schedule"] == {**WEEKDAYS_LONDON, "time_of_day": "09:00", "timezone": "America/New_York"}
