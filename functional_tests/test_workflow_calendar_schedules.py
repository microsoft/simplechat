# test_workflow_calendar_schedules.py
#!/usr/bin/env python3
"""
Functional test for calendar workflow schedules and the administrator's minimum schedule interval.
Version: 0.261.192
Implemented in: 0.261.192

This test ensures that:

* a calendar schedule (daily, weekdays, weekly or monthly, at a local HH:MM in an IANA time zone)
  computes its next run at the right UTC instant across daylight saving changes. A local time in
  the spring-forward gap runs at the instant the offset before the gap names (02:30 runs at 03:30
  in New York). An ambiguous time in the fall-back overlap runs once, at its first occurrence. A
  monthly day that a month does not have runs on that month's last day;
* a year of runs, in zones with hour, half-hour and midnight transitions, matches an independent
  day-by-day computation, so no local day is skipped or run twice;
* catch-up is unchanged: a workflow that missed runs runs once, then schedules the first
  occurrence after now;
* both save routes refuse an invalid calendar schedule with its reviewed message, and store,
  label and reschedule "Mondays 08:00 America/New_York" the same way in personal and group scope;
* the administrator's minimum interval governs only new or changed interval schedules;
* interval schedules keep their stored bytes, Microsoft 365 Run-as fingerprint, definition
  revision and approval exactly as they were before calendar schedules existed.

The real schedule, personal and group modules run over the doubled I/O of
``test_group_workflow_round_trip_preservation.py``. The save routes are the real route bodies,
compiled by ``test_workflow_alert_reviewed_messages.py``.
"""

import ast
import calendar
import copy
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

import test_group_workflow_round_trip_preservation as harness  # noqa: E402  (shared real-module harness)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_alert_reviewed_messages import SaveRoutes, _payload  # noqa: E402  (real save routes)


APP_ROOT = harness.APP_ROOT
OWNER_ID = harness.OWNER_ID
GROUP_ID = harness.GROUP_ID
SCOPES = ("personal", "group")
SETTINGS_CODE = "invalid_workflow_settings"
MIN_SETTING = "workflow_min_schedule_interval_seconds"
GENERIC_400 = "Invalid workflow settings. Review the task, runner, trigger, and document inputs."
MARKER = "PRIVATE-MARKER-4c1d"
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# A Sunday. The next Monday, 2 March 2026, is before New York's daylight saving change on 8 March.
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

KIND_ERROR = "Schedule kind must be interval or calendar."
FREQUENCY_ERROR = "Schedule frequency must be daily, weekdays, weekly or monthly."
DAYS_ERROR = "Schedule days of the week must be day names from monday to sunday."
DAYS_REQUIRED_ERROR = "Choose at least one day of the week for a weekly schedule."
DAY_OF_MONTH_TYPE_ERROR = "Schedule day of the month must be a whole number."
DAY_OF_MONTH_RANGE_ERROR = "Schedule day of the month must be between 1 and 31."
TIME_ERROR = "Schedule time must use 24-hour HH:MM format, such as 08:00."
ZONE_ERROR = "Schedule time zone must be an IANA time zone name, such as America/New_York."


def _minimum_message(duration):
    return ("This schedule runs more often than the administrator allows. "
            f"Choose an interval of at least {duration}.")


def _calendar(frequency, time_of_day, zone, *, days=(), day_of_month=None):
    """A calendar schedule in its stored shape."""
    return {
        "kind": "calendar", "frequency": frequency, "days_of_week": list(days), "day_of_month": day_of_month,
        "time_of_day": time_of_day, "timezone": zone,
    }


MONDAYS_NY = _calendar("weekly", "08:00", "America/New_York", days=["monday"])
WEEKDAYS_TOKYO = _calendar("weekdays", "07:00", "Asia/Tokyo")
EVERY_MINUTE = {"unit": "minutes", "value": 1}


def _raw(**fields):
    """A weekly calendar payload with the named fields replaced; a value of ``...`` drops the field."""
    payload = copy.deepcopy(MONDAYS_NY)
    for key, value in fields.items():
        if value is ...:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def _edited(record, **fields):
    """What the V2 editor sends back: the loaded record, with its id and opened revision, plus edits."""
    payload = {
        key: copy.deepcopy(value) for key, value in record.items()
        if key not in {"user_id", "created_at", "created_by", "modified_at", "modified_by", "updated_at"}
    }
    payload.update(copy.deepcopy(fields))
    return payload


class CalendarRoutes(SaveRoutes):
    """Both save routes over the real stores, with a fixed clock for the next-run computation."""

    def __init__(self):
        super().__init__()
        self.personal = self.store.modules["functions_personal_workflows"]
        self.schedules = self.store.modules["functions_workflow_schedules"]
        self.binding = self.store.modules["functions_m365_workflow_binding"]
        self.definitions = self.store.modules["functions_workflow_definitions"]
        # Both scopes compute next_run_at with the personal module's clock.
        self.personal._utc_now = lambda: NOW

    def container(self, scope):
        return self.store.container if scope == "group" else self.personal_container

    def partition(self, scope):
        return GROUP_ID if scope == "group" else OWNER_ID

    def created(self, scope, **fields):
        response = self.post(scope, _payload(scope, **fields))
        assert response.status_code == 201, response.get_data(as_text=True)
        return response.json["workflow"]

    def load(self, scope, workflow_id):
        record = (self.personal.get_personal_workflow(OWNER_ID, workflow_id) if scope == "personal"
                  else self.store.load(workflow_id))
        return {key: value for key, value in record.items() if not key.startswith("_")}

    def resave(self, scope, workflow_id, **fields):
        """Save the stored workflow as the V2 editor would, with the given edits."""
        return self.post(scope, _edited(self.load(scope, workflow_id), **fields))

    def approve(self, scope, workflow_id, approval_id):
        """Record a Run-as approval on the stored workflow, as the approval service does."""
        self.container(scope).items[(self.partition(scope), workflow_id)]["m365_binding_approval_id"] = approval_id


@pytest.fixture(scope="module")
def routes():
    return CalendarRoutes()


@pytest.fixture(scope="module")
def schedules(routes):
    return routes.schedules


@pytest.fixture
def minimum(routes):
    """Set the administrator's minimum interval for one test; the default is restored afterwards."""
    def set_minimum(value):
        routes.store.settings[MIN_SETTING] = value

    yield set_minimum
    routes.store.settings.pop(MIN_SETTING, None)


def _next(schedules, schedule, from_time):
    return schedules.next_workflow_schedule_run(schedule, from_time)


def test_the_application_version_includes_calendar_schedules():
    assert_app_version_at_least("0.261.192")


# ---------------------------------------------------------------------------------------------
# Next runs
# ---------------------------------------------------------------------------------------------

# name: (schedule, from, [each following run]). Each run is computed from the one before it, so
# every case also proves that a run exactly at from_time is never returned again.
CHAINS = {
    "weekly_monday_new_york_across_spring_forward": (
        MONDAYS_NY, "2026-03-02T00:00:00+00:00",
        ["2026-03-02T13:00:00+00:00", "2026-03-09T12:00:00+00:00", "2026-03-16T12:00:00+00:00"],
    ),
    "weekly_monday_new_york_across_fall_back": (
        MONDAYS_NY, "2026-10-25T00:00:00+00:00",
        ["2026-10-26T12:00:00+00:00", "2026-11-02T13:00:00+00:00", "2026-11-09T13:00:00+00:00"],
    ),
    "a_second_before_the_run_still_gets_it": (
        MONDAYS_NY, "2026-03-02T12:59:59+00:00", ["2026-03-02T13:00:00+00:00"],
    ),
    "spring_forward_gap_runs_at_the_same_instant_as_before_the_gap": (
        _calendar("daily", "02:30", "America/New_York"), "2026-03-07T12:00:00+00:00",
        ["2026-03-08T07:30:00+00:00", "2026-03-09T06:30:00+00:00"],
    ),
    "fall_back_overlap_runs_once_at_its_first_occurrence": (
        _calendar("daily", "01:30", "America/New_York"), "2026-10-31T12:00:00+00:00",
        ["2026-11-01T05:30:00+00:00", "2026-11-02T06:30:00+00:00"],
    ),
    "weekly_on_several_days_in_berlin": (
        _calendar("weekly", "09:00", "Europe/Berlin", days=["monday", "wednesday", "friday"]),
        "2026-03-01T00:00:00+00:00",
        ["2026-03-02T08:00:00+00:00", "2026-03-04T08:00:00+00:00", "2026-03-06T08:00:00+00:00",
         "2026-03-09T08:00:00+00:00"],
    ),
    "weekly_on_several_days_across_the_berlin_change": (
        _calendar("weekly", "09:00", "Europe/Berlin", days=["monday", "friday"]),
        "2026-03-26T00:00:00+00:00",
        ["2026-03-27T08:00:00+00:00", "2026-03-30T07:00:00+00:00"],
    ),
    "weekdays_skip_the_weekend_in_tokyo": (
        WEEKDAYS_TOKYO, "2026-03-05T23:00:00+00:00",
        ["2026-03-08T22:00:00+00:00", "2026-03-09T22:00:00+00:00"],
    ),
    "weekdays_use_the_local_date_not_the_utc_date": (
        WEEKDAYS_TOKYO, "2026-03-04T21:00:00+00:00", ["2026-03-04T22:00:00+00:00"],
    ),
    "monthly_day_31_runs_on_the_last_day_of_short_months": (
        _calendar("monthly", "06:00", "UTC", day_of_month=31), "2026-01-31T06:00:00+00:00",
        ["2026-02-28T06:00:00+00:00", "2026-03-31T06:00:00+00:00", "2026-04-30T06:00:00+00:00",
         "2026-05-31T06:00:00+00:00"],
    ),
    "monthly_day_31_in_a_leap_february": (
        _calendar("monthly", "06:00", "UTC", day_of_month=31), "2028-01-31T06:00:00+00:00",
        ["2028-02-29T06:00:00+00:00", "2028-03-31T06:00:00+00:00"],
    ),
    "monthly_day_29_in_a_common_february": (
        _calendar("monthly", "06:00", "UTC", day_of_month=29), "2027-01-29T06:00:00+00:00",
        ["2027-02-28T06:00:00+00:00", "2027-03-29T06:00:00+00:00"],
    ),
    "monthly_day_29_in_a_leap_february": (
        _calendar("monthly", "06:00", "UTC", day_of_month=29), "2028-01-29T06:00:00+00:00",
        ["2028-02-29T06:00:00+00:00", "2028-03-29T06:00:00+00:00"],
    ),
    "monthly_day_30_in_february_then_back_to_30": (
        _calendar("monthly", "06:00", "UTC", day_of_month=30), "2027-01-30T06:00:00+00:00",
        ["2027-02-28T06:00:00+00:00", "2027-03-30T06:00:00+00:00"],
    ),
    "monthly_uses_the_local_month_ahead_of_utc": (
        _calendar("monthly", "00:30", "Pacific/Auckland", day_of_month=1), "2026-03-31T00:00:00+00:00",
        ["2026-03-31T11:30:00+00:00"],
    ),
    "monthly_across_the_year_end": (
        _calendar("monthly", "06:00", "UTC", day_of_month=31), "2026-12-31T06:00:00+00:00",
        ["2027-01-31T06:00:00+00:00", "2027-02-28T06:00:00+00:00"],
    ),
}


@pytest.mark.parametrize("name", sorted(CHAINS))
def test_calendar_next_runs_land_on_the_right_utc_instant(schedules, name):
    schedule, start, expected = CHAINS[name]
    runs = []
    current = start
    for _ in expected:
        current = _next(schedules, schedule, current)
        runs.append(current)
    assert runs == expected


def test_next_runs_accept_datetimes_and_text_and_read_naive_times_as_utc(schedules):
    expected = "2026-03-02T13:00:00+00:00"
    assert _next(schedules, MONDAYS_NY, NOW) == expected
    assert _next(schedules, MONDAYS_NY, NOW.isoformat()) == expected
    assert _next(schedules, MONDAYS_NY, NOW.replace(tzinfo=None)) == expected
    # An aware time in another zone names the same instant.
    assert _next(schedules, MONDAYS_NY, NOW.astimezone(ZoneInfo("Asia/Tokyo"))) == expected


def test_calendar_next_runs_are_utc_text_the_due_query_orders_correctly(schedules):
    """get_due_personal_workflows compares next_run_at with the current UTC ISO text."""
    run = _next(schedules, MONDAYS_NY, NOW)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+00:00", run)
    instant = datetime.fromisoformat(run)
    assert (instant - timedelta(microseconds=1)).isoformat() < run
    assert run < (instant + timedelta(microseconds=1)).isoformat()


def test_next_run_refuses_an_interval_or_invalid_schedule(schedules):
    error = schedules.WorkflowPublicValidationError
    with pytest.raises(error, match=re.escape(KIND_ERROR)):
        _next(schedules, {"unit": "minutes", "value": 5}, NOW)
    with pytest.raises(error, match=re.escape(ZONE_ERROR)):
        _next(schedules, _raw(timezone="Mars/Olympus"), NOW)


def test_every_offered_time_zone_computes_a_next_run(schedules):
    for zone in sorted(schedules.workflow_schedule_timezones()):
        run = datetime.fromisoformat(_next(schedules, _calendar("daily", "02:30", zone), NOW))
        assert NOW < run <= NOW + timedelta(days=2), zone


# ---------------------------------------------------------------------------------------------
# A year of runs against an independent day-by-day computation
# ---------------------------------------------------------------------------------------------

# New York and London: 1-hour changes at 02:00 and 01:00. Sydney: southern hemisphere. Lord Howe:
# a 30-minute change at 02:00. Santiago: changes at local midnight. Kolkata and UTC: none.
YEAR_ZONES = (
    "America/New_York", "Europe/London", "Australia/Sydney", "Australia/Lord_Howe", "America/Santiago",
    "Asia/Kolkata", "UTC",
)
YEAR_TIMES = ("00:00", "00:30", "01:30", "02:00", "02:15", "02:30", "03:30", "23:30")
YEAR_SCHEDULES = {
    "daily": {"frequency": "daily"},
    "weekdays": {"frequency": "weekdays"},
    "weekly_monday_wednesday_friday": {"frequency": "weekly", "days": ["monday", "wednesday", "friday"]},
    "weekly_sunday": {"frequency": "weekly", "days": ["sunday"]},
    "monthly_day_1": {"frequency": "monthly", "day_of_month": 1},
    "monthly_day_29": {"frequency": "monthly", "day_of_month": 29},
    "monthly_day_31": {"frequency": "monthly", "day_of_month": 31},
}


def _runs_on(schedule, day):
    frequency = schedule["frequency"]
    if frequency == "daily":
        return True
    if frequency == "weekdays":
        return day.weekday() < 5
    if frequency == "weekly":
        return DAYS[day.weekday()] in schedule["days_of_week"]
    return day.day == min(schedule["day_of_month"], calendar.monthrange(day.year, day.month)[1])


def _day_by_day_runs(schedule, first_day, last_day):
    """Each local day's run, from RFC 5545's rule (fold=0), without the module's search windows."""
    zone = ZoneInfo(schedule["timezone"])
    hour, minute = (int(part) for part in schedule["time_of_day"].split(":"))
    runs = []
    day = first_day
    while day <= last_day:
        if _runs_on(schedule, day):
            runs.append(datetime.combine(day, time(hour, minute), tzinfo=zone).astimezone(timezone.utc))
        day += timedelta(days=1)
    return runs


@pytest.mark.parametrize("zone", YEAR_ZONES)
@pytest.mark.parametrize("name", sorted(YEAR_SCHEDULES))
def test_a_year_of_runs_matches_a_day_by_day_computation(schedules, name, zone):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    fields = YEAR_SCHEDULES[name]
    for time_of_day in YEAR_TIMES:
        schedule = _calendar(
            fields["frequency"], time_of_day, zone,
            days=fields.get("days", ()), day_of_month=fields.get("day_of_month"),
        )
        expected = [
            run for run in _day_by_day_runs(schedule, date(2025, 12, 30), date(2027, 1, 2))
            if start < run <= end
        ]
        runs = []
        current = start
        # Bounded, so a next run that fails to advance fails the test instead of looping forever.
        for _ in range(len(expected) + 2):
            current = datetime.fromisoformat(_next(schedules, schedule, current))
            if current > end:
                break
            runs.append(current)
        assert runs == expected, (name, zone, time_of_day)
        # Each run is the requested local time, or later by the size of a gap it fell in.
        local_zone = ZoneInfo(zone)
        wanted = time(*(int(part) for part in time_of_day.split(":")))
        for run in runs:
            local = run.astimezone(local_zone)
            shift = datetime.combine(local.date(), local.time()) - datetime.combine(local.date(), wanted)
            assert timedelta(0) <= shift <= timedelta(hours=1), (name, zone, time_of_day, run)


# ---------------------------------------------------------------------------------------------
# compute_next_run_at and catch-up
# ---------------------------------------------------------------------------------------------

def test_catch_up_runs_once_and_then_schedules_the_first_run_after_now(routes):
    compute = routes.personal.compute_next_run_at
    missed = {
        "id": "missed", "trigger_type": "interval", "is_enabled": True, "schedule": MONDAYS_NY,
        "next_run_at": "2026-03-02T13:00:00+00:00",
    }
    # Three Mondays were missed. The scheduler finds the workflow due, runs it once, then stores the
    # first run after now instead of any missed one.
    now = datetime(2026, 3, 25, 15, 0, tzinfo=timezone.utc)
    assert datetime.fromisoformat(missed["next_run_at"]) <= now
    assert compute(missed, from_time=now) == "2026-03-30T12:00:00+00:00"
    # A year of missed daily runs still produces a single next run.
    daily = {**missed, "schedule": _calendar("daily", "08:00", "America/New_York")}
    assert compute(daily, from_time=datetime(2027, 3, 1, 15, 0, tzinfo=timezone.utc)) == "2027-03-02T13:00:00+00:00"
    # An interval schedule keeps counting from now.
    interval = {**missed, "schedule": {"unit": "minutes", "value": 30}}
    assert compute(interval, from_time=now) == (now + timedelta(minutes=30)).isoformat()


def test_every_scheduler_reschedule_counts_from_now():
    """Catch-up is unchanged: each reschedule after a run starts from the current time."""
    tree = ast.parse((APP_ROOT / "background_tasks.py").read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "compute_next_run_at"
    ]
    assert len(calls) >= 7
    for call in calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "from_time" in keywords, ast.unparse(call)
        assert ast.unparse(keywords["from_time"]) == "datetime.now(timezone.utc)", ast.unparse(call)


def test_compute_next_run_at_uses_the_save_clock_without_a_reference(routes):
    compute = routes.personal.compute_next_run_at
    assert compute({"trigger_type": "interval", "is_enabled": True, "schedule": MONDAYS_NY}) == (
        "2026-03-02T13:00:00+00:00"
    )
    assert compute({"trigger_type": "file_sync", "is_enabled": True, "schedule": WEEKDAYS_TOKYO}) == (
        "2026-03-01T22:00:00+00:00"
    )


@pytest.mark.parametrize("workflow", [
    {"trigger_type": "manual", "is_enabled": True, "schedule": MONDAYS_NY},
    {"trigger_type": "interval", "is_enabled": False, "schedule": MONDAYS_NY},
    {"trigger_type": "interval", "is_enabled": True, "schedule": {}},
    {"trigger_type": "interval", "is_enabled": True, "schedule": _raw(timezone="Mars/Olympus")},
    {"trigger_type": "interval", "is_enabled": True, "schedule": _raw(frequency="hourly")},
    {"trigger_type": "interval", "is_enabled": True, "schedule": _raw(time_of_day="25:00")},
])
def test_an_unscheduled_or_unreadable_calendar_workflow_has_no_next_run(routes, workflow):
    assert routes.personal.compute_next_run_at(workflow, from_time=NOW) is None


# ---------------------------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------------------------

ACCEPTED = {
    "stored_shape_is_unchanged": (MONDAYS_NY, MONDAYS_NY),
    "days_are_ordered_and_deduplicated": (
        _raw(days_of_week=["Friday", " monday ", "MONDAY"]),
        _calendar("weekly", "08:00", "America/New_York", days=["monday", "friday"]),
    ),
    "text_is_trimmed_and_case_folded": (
        _raw(kind=" Calendar ", frequency=" WEEKLY ", time_of_day=" 08:00 ", timezone=" America/New_York "),
        MONDAYS_NY,
    ),
    "weekly_ignores_a_day_of_the_month": (_raw(day_of_month=12), MONDAYS_NY),
    "monthly_accepts_a_whole_float_and_ignores_days": (
        _raw(frequency="monthly", day_of_month=31.0),
        _calendar("monthly", "08:00", "America/New_York", day_of_month=31),
    ),
    "daily_ignores_days_and_day_of_month": (
        _raw(frequency="daily", day_of_month=3),
        _calendar("daily", "08:00", "America/New_York"),
    ),
    "weekdays": (_raw(frequency="weekdays", days_of_week=...), _calendar("weekdays", "08:00", "America/New_York")),
    "fields_the_rules_do_not_define_are_dropped": (
        {**MONDAYS_NY, "unit": "minutes", "value": 5, "note": MARKER}, MONDAYS_NY,
    ),
    "midnight_and_last_minute": (_raw(time_of_day="00:00"), {**MONDAYS_NY, "time_of_day": "00:00"}),
    "last_minute_of_the_day": (_raw(time_of_day="23:59"), {**MONDAYS_NY, "time_of_day": "23:59"}),
}


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_calendar_schedules_normalize_to_their_stored_shape(schedules, name):
    raw, expected = ACCEPTED[name]
    assert schedules.normalize_workflow_schedule(copy.deepcopy(raw)) == expected


# name: (raw schedule, reviewed message)
INVALID = {
    "kind_unknown": ({"kind": f"cron-{MARKER}", "unit": "minutes", "value": 5}, KIND_ERROR),
    "frequency_missing": (_raw(frequency=...), FREQUENCY_ERROR),
    "frequency_hourly": (_raw(frequency="hourly"), FREQUENCY_ERROR),
    "frequency_caller_text": (_raw(frequency=MARKER), FREQUENCY_ERROR),
    "weekly_days_empty": (_raw(days_of_week=[]), DAYS_REQUIRED_ERROR),
    "weekly_days_missing": (_raw(days_of_week=...), DAYS_REQUIRED_ERROR),
    "weekly_day_unknown": (_raw(days_of_week=["monday", f"funday-{MARKER}"]), DAYS_ERROR),
    "weekly_day_number": (_raw(days_of_week=[1]), DAYS_ERROR),
    "weekly_days_text": (_raw(days_of_week="monday"), DAYS_ERROR),
    "monthly_day_missing": (_raw(frequency="monthly"), DAY_OF_MONTH_TYPE_ERROR),
    "monthly_day_text": (_raw(frequency="monthly", day_of_month="5"), DAY_OF_MONTH_TYPE_ERROR),
    "monthly_day_boolean": (_raw(frequency="monthly", day_of_month=True), DAY_OF_MONTH_TYPE_ERROR),
    "monthly_day_fraction": (_raw(frequency="monthly", day_of_month=5.5), DAY_OF_MONTH_TYPE_ERROR),
    "monthly_day_zero": (_raw(frequency="monthly", day_of_month=0), DAY_OF_MONTH_RANGE_ERROR),
    "monthly_day_32": (_raw(frequency="monthly", day_of_month=32), DAY_OF_MONTH_RANGE_ERROR),
    "time_missing": (_raw(time_of_day=...), TIME_ERROR),
    "time_single_digit_hour": (_raw(time_of_day="8:00"), TIME_ERROR),
    "time_hour_24": (_raw(time_of_day="24:00"), TIME_ERROR),
    "time_minute_60": (_raw(time_of_day="08:60"), TIME_ERROR),
    "time_with_seconds": (_raw(time_of_day="08:00:00"), TIME_ERROR),
    "time_twelve_hour": (_raw(time_of_day="8:00 AM"), TIME_ERROR),
    "time_number": (_raw(time_of_day=800), TIME_ERROR),
    "time_caller_text": (_raw(time_of_day=MARKER), TIME_ERROR),
    "zone_missing": (_raw(timezone=...), ZONE_ERROR),
    "zone_empty": (_raw(timezone=""), ZONE_ERROR),
    "zone_unknown": (_raw(timezone="Mars/Olympus"), ZONE_ERROR),
    "zone_wrong_case": (_raw(timezone="america/new_york"), ZONE_ERROR),
    "zone_offset": (_raw(timezone="UTC+05:00"), ZONE_ERROR),
    "zone_path": (_raw(timezone="../../etc/passwd"), ZONE_ERROR),
    "zone_factory": (_raw(timezone="Factory"), ZONE_ERROR),
    "zone_localtime": (_raw(timezone="localtime"), ZONE_ERROR),
    "zone_posixrules": (_raw(timezone="posixrules"), ZONE_ERROR),
    "zone_number": (_raw(timezone=5), ZONE_ERROR),
    "zone_caller_text": (_raw(timezone=f"America/{MARKER}"), ZONE_ERROR),
}


@pytest.mark.parametrize("name", sorted(INVALID))
def test_invalid_calendar_schedules_raise_their_reviewed_message(schedules, name):
    raw, message = INVALID[name]
    with pytest.raises(schedules.WorkflowPublicValidationError) as raised:
        schedules.normalize_workflow_schedule(copy.deepcopy(raw))
    assert raised.value.public_message == message


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("name", sorted(INVALID))
def test_both_save_routes_refuse_an_invalid_calendar_schedule(routes, scope, name):
    raw, message = INVALID[name]
    writes = routes.writes()

    response = routes.post(scope, _payload(scope, trigger_type="interval", schedule=raw))

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": message, "code": SETTINGS_CODE}
    assert MARKER not in response.get_data(as_text=True)
    assert routes.writes() == writes


def _legacy_interval_schedule(schedule_payload):
    """The interval normalizer before calendar schedules (0.261.190), verbatim apart from the error type."""
    schedule_payload = schedule_payload if isinstance(schedule_payload, dict) else {}
    unit = str(schedule_payload.get('unit') or '').strip().lower()
    if unit not in {'seconds', 'minutes', 'hours'}:
        raise ValueError('Schedule unit must be seconds, minutes or hours.')

    try:
        value = int(schedule_payload.get('value'))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Schedule value must be a whole number.')

    max_value = 59 if unit in ('seconds', 'minutes') else 24
    if value < 1 or value > max_value:
        raise ValueError(f'Schedule value for {unit} must be between 1 and {max_value}.')

    return {
        'unit': unit,
        'value': value,
    }


LEGACY_INTERVAL_INPUTS = [
    {"unit": "minutes", "value": 30}, {"unit": " Hours ", "value": "2"}, {"unit": "MINUTES", "value": 7},
    {"unit": "seconds", "value": True}, {"unit": "seconds", "value": False}, {"unit": "hours", "value": 5.9},
    {"unit": "minutes", "value": "1.5"}, {"unit": "minutes", "value": " 12 "}, {"unit": "minutes", "value": [1]},
    {"unit": "minutes", "value": None}, {"unit": "minutes", "value": float("inf")}, {"unit": "minutes"},
    {"value": 5}, {"unit": "weeks", "value": 1}, {"unit": 5, "value": 5}, {}, None, [], "every minute",
    # A kind the calendar rules read as interval, and calendar fields without a calendar kind.
    {"unit": "seconds", "value": 45, "kind": "interval"}, {"unit": "minutes", "value": 5, "kind": " INTERVAL "},
    {"unit": "minutes", "value": 5, "kind": ""}, {"unit": "minutes", "value": 5, "kind": None},
    {"unit": "minutes", "value": 5, "frequency": "weekly", "time_of_day": "08:00", "timezone": "UTC"},
    {"unit": "minutes", "value": 7, "timezone": "UTC"},
] + [{"unit": unit, "value": value} for unit in ("seconds", "minutes", "hours") for value in range(-1, 62)]


def _outcome(normalize, raw):
    try:
        return json.dumps(normalize(copy.deepcopy(raw)), sort_keys=True, separators=(",", ":"))
    except ValueError as exc:
        return f"error: {exc}"


@pytest.mark.parametrize("index", range(len(LEGACY_INTERVAL_INPUTS)))
def test_interval_schedules_normalize_byte_for_byte_as_before(schedules, index):
    raw = LEGACY_INTERVAL_INPUTS[index]
    assert _outcome(schedules.normalize_workflow_schedule, raw) == _outcome(_legacy_interval_schedule, raw)


# ---------------------------------------------------------------------------------------------
# Labels, summaries and editor options
# ---------------------------------------------------------------------------------------------

LABELS = [
    ("interval", MONDAYS_NY, "Mondays 08:00 America/New_York"),
    ("interval", _calendar("weekly", "09:00", "Europe/Berlin", days=["monday", "wednesday", "friday"]),
     "Mondays, Wednesdays and Fridays 09:00 Europe/Berlin"),
    ("interval", _calendar("weekly", "10:00", "UTC", days=["saturday", "sunday"]), "Saturdays and Sundays 10:00 UTC"),
    ("interval", _calendar("daily", "06:30", "Asia/Kolkata"), "Daily 06:30 Asia/Kolkata"),
    ("interval", WEEKDAYS_TOKYO, "Weekdays 07:00 Asia/Tokyo"),
    ("interval", _calendar("monthly", "06:00", "UTC", day_of_month=15), "Monthly on day 15, 06:00 UTC"),
    ("interval", _calendar("monthly", "06:00", "UTC", day_of_month=28), "Monthly on day 28, 06:00 UTC"),
    ("interval", _calendar("monthly", "06:00", "UTC", day_of_month=29), "Monthly on day 29 (or last day), 06:00 UTC"),
    ("interval", _calendar("monthly", "06:00", "UTC", day_of_month=31), "Monthly on day 31 (or last day), 06:00 UTC"),
    ("file_sync", WEEKDAYS_TOKYO, "Monitor File Sync: Weekdays 07:00 Asia/Tokyo"),
    ("interval", {"unit": "minutes", "value": 30}, "Every 30 minutes"),
    ("interval", {"unit": "hours", "value": 1}, "Every hour"),
    ("interval", {"unit": "seconds", "value": 1}, "Every second"),
    ("file_sync", {"unit": "minutes", "value": 30}, "Monitor File Sync every 30 minutes"),
    (" Interval ", MONDAYS_NY, "Mondays 08:00 America/New_York"),
    ("manual", MONDAYS_NY, ""),
    ("", MONDAYS_NY, ""),
    ("interval", _raw(timezone="Mars/Olympus"), ""),
    ("interval", {}, ""),
    ("interval", None, ""),
]


@pytest.mark.parametrize("index", range(len(LABELS)))
def test_schedule_labels_read_naturally(schedules, index):
    trigger_type, schedule, label = LABELS[index]
    assert schedules.workflow_schedule_label(trigger_type, copy.deepcopy(schedule)) == label


def test_the_mcp_workflow_summary_includes_the_schedule(schedules):
    namespace = harness._compiled(
        APP_ROOT / "functions_mcp_server_tools.py",
        (
            "INBOUND_MCP_WORKFLOW_DESCRIPTION_MAX_CHARS", "_stringify_message_content", "_truncate_text",
            "_coerce_nonnegative_int", "_serialize_personal_workflow_summary",
        ),
        {
            "json": json,
            "workflow_schedule_label": schedules.workflow_schedule_label,
            "workflow_schedule_summary": schedules.workflow_schedule_summary,
        },
    )
    summarize = namespace["_serialize_personal_workflow_summary"]

    stored = {"id": "weekly", "trigger_type": "interval", "is_enabled": True,
              "schedule": {**MONDAYS_NY, "note": MARKER}}
    summary = summarize(stored)
    assert summary["schedule"] == MONDAYS_NY
    assert summary["schedule_label"] == "Mondays 08:00 America/New_York"
    assert MARKER not in json.dumps(summary)

    interval = summarize({"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 30}})
    assert (interval["schedule"], interval["schedule_label"]) == ({"unit": "minutes", "value": 30}, "Every 30 minutes")
    monitor = summarize({"trigger_type": "file_sync", "schedule": WEEKDAYS_TOKYO})
    assert monitor["schedule_label"] == "Monitor File Sync: Weekdays 07:00 Asia/Tokyo"
    for unscheduled in (
        {"trigger_type": "manual", "schedule": MONDAYS_NY},
        {"trigger_type": "interval", "schedule": _raw(timezone=f"America/{MARKER}")},
        {"trigger_type": "interval"},
    ):
        summary = summarize(unscheduled)
        assert (summary["schedule"], summary["schedule_label"]) == ({}, "")
        assert MARKER not in json.dumps(summary)


def test_the_schedule_editor_options_offer_every_calendar_choice(schedules):
    options = schedules.build_workflow_schedule_editor_options(min_interval_seconds=300)

    assert options["kinds"] == ["interval", "calendar"]
    assert options["units"] == ["seconds", "minutes", "hours"]
    assert options["frequencies"] == ["daily", "weekdays", "weekly", "monthly"]
    assert options["days_of_week"] == list(DAYS)
    assert options["min_interval_seconds"] == 300
    zones = options["timezones"]
    assert zones == sorted(set(zones))
    assert set(zones) == schedules.workflow_schedule_timezones()
    assert {"America/New_York", "Europe/Berlin", "Asia/Tokyo", "Australia/Lord_Howe", "UTC"} <= set(zones)
    assert not {"Factory", "localtime", "posixrules"} & set(zones)
    for zone in zones:
        assert schedules.normalize_workflow_schedule(_calendar("daily", "08:00", zone))["timezone"] == zone
    # The zone list is built once per process.
    assert schedules.workflow_schedule_timezones() is schedules.workflow_schedule_timezones()


def test_the_editor_options_carry_the_schedule_block_and_validate_the_minimum():
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    # Imported as test_workflow_editor_options.py does; the editor module imports no Azure clients.
    from functions_workflow_editor import build_workflow_editor_options  # noqa: E402

    def options(**kwargs):
        return build_workflow_editor_options(
            scope_type="group", scope_id=GROUP_ID, can_manage=True, max_tasks=50, agents=[], endpoints=[], **kwargs,
        )

    assert options()["schedule"]["min_interval_seconds"] == 1
    assert options(min_schedule_interval_seconds=900)["schedule"]["min_interval_seconds"] == 900
    assert options(min_schedule_interval_seconds=" 900 ")["schedule"]["min_interval_seconds"] == 900
    assert options()["schedule"]["kinds"] == ["interval", "calendar"]
    for invalid in (0, 86401, "soon", True, None):
        with pytest.raises(ValueError) as raised:
            options(min_schedule_interval_seconds=invalid)
        # Compared by name: other test files may have loaded their own copy of the limits module.
        assert type(raised.value).__name__ == "WorkflowLoopLimitError"


# ---------------------------------------------------------------------------------------------
# Personal and group saves
# ---------------------------------------------------------------------------------------------

# name: (schedule, next run after NOW, label)
SAVED = {
    "weekly_mondays_new_york": (MONDAYS_NY, "2026-03-02T13:00:00+00:00", "Mondays 08:00 America/New_York"),
    "weekdays_tokyo": (WEEKDAYS_TOKYO, "2026-03-01T22:00:00+00:00", "Weekdays 07:00 Asia/Tokyo"),
    "daily_london": (_calendar("daily", "18:00", "Europe/London"), "2026-03-01T18:00:00+00:00",
                     "Daily 18:00 Europe/London"),
    "monthly_day_31_utc": (_calendar("monthly", "06:00", "UTC", day_of_month=31), "2026-03-31T06:00:00+00:00",
                           "Monthly on day 31 (or last day), 06:00 UTC"),
}


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("name", sorted(SAVED))
def test_each_frequency_saves_with_its_next_run_and_label(routes, scope, name):
    schedule, next_run_at, label = SAVED[name]

    saved = routes.created(scope, trigger_type="interval", schedule=schedule)

    assert saved["schedule"] == schedule
    assert saved["next_run_at"] == next_run_at
    assert routes.schedules.workflow_schedule_label(saved["trigger_type"], saved["schedule"]) == label
    stored = routes.container(scope).items[(routes.partition(scope), saved["id"])]
    assert stored["schedule"] == schedule
    assert stored["next_run_at"] == next_run_at


@pytest.mark.parametrize("scope", SCOPES)
def test_mondays_in_new_york_saves_edits_and_reschedules_in_both_scopes(routes, scope, monkeypatch):
    created = routes.created(scope, trigger_type="interval", schedule=MONDAYS_NY)
    assert created["schedule"] == MONDAYS_NY
    assert created["next_run_at"] == "2026-03-02T13:00:00+00:00"

    # Three days later (Wednesday 4 March), an edit that leaves the schedule alone keeps the next run.
    monkeypatch.setattr(routes.personal, "_utc_now", lambda: NOW + timedelta(days=3))
    response = routes.resave(scope, created["id"], description="Edited later.")
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["workflow"]["schedule"] == MONDAYS_NY
    assert response.json["workflow"]["next_run_at"] == "2026-03-02T13:00:00+00:00"

    # Moving it to Tuesdays computes the next run from now; 10 March is after the change to EDT.
    response = routes.resave(scope, created["id"], schedule={**MONDAYS_NY, "days_of_week": ["tuesday"]})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["workflow"]["next_run_at"] == "2026-03-10T12:00:00+00:00"

    # Changing only the zone reschedules too.
    london = {**MONDAYS_NY, "days_of_week": ["tuesday"], "timezone": "Europe/London"}
    response = routes.resave(scope, created["id"], schedule=london)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["workflow"]["next_run_at"] == "2026-03-10T08:00:00+00:00"

    # Pausing clears the next run, and moving to manual drops the schedule.
    response = routes.resave(scope, created["id"], is_enabled=False)
    assert (response.json["workflow"]["schedule"], response.json["workflow"]["next_run_at"]) == (london, None)
    response = routes.resave(scope, created["id"], trigger_type="manual", is_enabled=True)
    assert (response.json["workflow"]["schedule"], response.json["workflow"]["next_run_at"]) == ({}, None)


def test_a_group_file_sync_monitor_can_run_on_a_calendar(routes):
    response = routes.post("group", harness.monitored_workflow(schedule=WEEKDAYS_TOKYO))

    assert response.status_code == 201, response.get_data(as_text=True)
    saved = response.json["workflow"]
    assert (saved["trigger_type"], saved["schedule"]) == ("file_sync", WEEKDAYS_TOKYO)
    assert saved["next_run_at"] == "2026-03-01T22:00:00+00:00"
    assert routes.schedules.workflow_schedule_label(saved["trigger_type"], saved["schedule"]) == (
        "Monitor File Sync: Weekdays 07:00 Asia/Tokyo"
    )


# ---------------------------------------------------------------------------------------------
# The administrator's minimum interval
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seconds, duration", [
    (1, "1 second"), (45, "45 seconds"), (60, "1 minute"), (90, "90 seconds"), (300, "5 minutes"),
    (3600, "1 hour"), (5400, "90 minutes"), (86400, "24 hours"),
])
def test_the_minimum_is_named_in_its_largest_whole_unit(schedules, seconds, duration):
    assert schedules.format_workflow_schedule_duration(seconds) == duration


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("setting", [300, "300", " 300 "])
def test_the_minimum_refuses_a_new_interval_that_runs_too_often(routes, scope, minimum, setting):
    minimum(setting)
    writes = routes.writes()

    for schedule in (EVERY_MINUTE, {"unit": "seconds", "value": 59}, {"unit": "minutes", "value": 4}):
        response = routes.post(scope, _payload(scope, trigger_type="interval", schedule=schedule))
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.json == {"error": _minimum_message("5 minutes"), "code": SETTINGS_CODE}
    assert routes.writes() == writes

    for schedule in ({"unit": "minutes", "value": 5}, {"unit": "hours", "value": 1}):
        assert routes.created(scope, trigger_type="interval", schedule=schedule)["schedule"] == schedule


@pytest.mark.parametrize("scope", SCOPES)
def test_the_largest_minimum_allows_only_a_daily_interval(routes, scope, minimum):
    minimum(86400)
    response = routes.post(scope, _payload(scope, trigger_type="interval", schedule={"unit": "hours", "value": 23}))
    assert response.json == {"error": _minimum_message("24 hours"), "code": SETTINGS_CODE}
    routes.created(scope, trigger_type="interval", schedule={"unit": "hours", "value": 24})


@pytest.mark.parametrize("scope", SCOPES)
def test_calendar_schedules_are_never_held_to_the_interval_minimum(routes, scope, minimum):
    minimum(86400)
    for schedule, _next_run, _label in SAVED.values():
        assert routes.created(scope, trigger_type="interval", schedule=schedule)["schedule"] == schedule


@pytest.mark.parametrize("scope", SCOPES)
def test_a_saved_interval_keeps_working_after_the_minimum_is_raised(routes, scope, minimum):
    created = routes.created(scope, trigger_type="interval", schedule=EVERY_MINUTE)
    minimum(300)

    # An edit that leaves the interval alone saves, and keeps the schedule and the next run.
    response = routes.resave(scope, created["id"], description="Still every minute.")
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["workflow"]["schedule"] == EVERY_MINUTE
    assert response.json["workflow"]["next_run_at"] == created["next_run_at"]
    # Pausing and resuming keeps the saved interval too.
    for enabled in (False, True):
        response = routes.resave(scope, created["id"], is_enabled=enabled)
        assert response.status_code == 200, response.get_data(as_text=True)
    # A different interval is a new choice, held to the minimum.
    writes = routes.writes()
    response = routes.resave(scope, created["id"], schedule={"unit": "minutes", "value": 2})
    assert response.json == {"error": _minimum_message("5 minutes"), "code": SETTINGS_CODE}
    assert routes.writes() == writes
    response = routes.resave(scope, created["id"], schedule={"unit": "minutes", "value": 10})
    assert response.status_code == 200, response.get_data(as_text=True)
    # Once changed, the old interval is a change again.
    response = routes.resave(scope, created["id"], schedule=EVERY_MINUTE)
    assert response.json == {"error": _minimum_message("5 minutes"), "code": SETTINGS_CODE}


@pytest.mark.parametrize("scope", SCOPES)
def test_the_minimum_applies_when_a_manual_or_calendar_workflow_moves_to_an_interval(routes, scope, minimum):
    manual = routes.created(scope)
    weekly = routes.created(scope, trigger_type="interval", schedule=MONDAYS_NY)
    minimum(300)
    for record in (manual, weekly):
        response = routes.resave(scope, record["id"], trigger_type="interval", schedule=EVERY_MINUTE)
        assert response.json == {"error": _minimum_message("5 minutes"), "code": SETTINGS_CODE}


def test_switching_between_interval_and_monitor_file_sync_keeps_a_saved_interval(routes, minimum):
    response = routes.post("group", harness.monitored_workflow(schedule=EVERY_MINUTE))
    assert response.status_code == 201, response.get_data(as_text=True)
    workflow_id = response.json["workflow"]["id"]
    minimum(300)

    for trigger_type in ("interval", "file_sync"):
        response = routes.resave("group", workflow_id, trigger_type=trigger_type)
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.json["workflow"]["schedule"] == EVERY_MINUTE
    response = routes.resave("group", workflow_id, schedule={"unit": "minutes", "value": 2})
    assert response.json == {"error": _minimum_message("5 minutes"), "code": SETTINGS_CODE}


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("setting", [0, 86401, -5, "soon", "", True, 1.5, None, {"seconds": 300}])
def test_an_unreadable_minimum_refuses_only_the_saves_it_governs(routes, scope, minimum, setting):
    saved = routes.created(scope, trigger_type="interval", schedule=EVERY_MINUTE)
    minimum(setting)
    writes = routes.writes()

    response = routes.post(scope, _payload(scope, trigger_type="interval", schedule={"unit": "hours", "value": 1}))

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": GENERIC_400}
    assert routes.writes() == writes
    # Saves the minimum does not govern never read it.
    routes.created(scope)
    routes.created(scope, trigger_type="interval", schedule=MONDAYS_NY)
    assert routes.resave(scope, saved["id"], description="Unchanged interval.").status_code == 200


def test_the_scheduler_never_reads_the_minimum(routes, minimum):
    """A saved one-minute schedule keeps running every minute however high the minimum is."""
    minimum(86400)
    workflow = {"trigger_type": "interval", "is_enabled": True, "schedule": EVERY_MINUTE}
    assert routes.personal.compute_next_run_at(workflow, from_time=NOW) == (NOW + timedelta(minutes=1)).isoformat()
    scheduler = (APP_ROOT / "background_tasks.py").read_text(encoding="utf-8")
    for name in (MIN_SETTING, "get_workflow_min_schedule_interval_seconds", "enforce_workflow_schedule_minimum"):
        assert name not in scheduler


@pytest.mark.parametrize("schedule, existing, applies", [
    (EVERY_MINUTE, None, True),
    (MONDAYS_NY, None, False),
    (EVERY_MINUTE, {"trigger_type": "manual", "schedule": {}}, True),
    (EVERY_MINUTE, {"trigger_type": "interval", "schedule": EVERY_MINUTE}, False),
    (EVERY_MINUTE, {"trigger_type": " FILE_SYNC ", "schedule": EVERY_MINUTE}, False),
    (EVERY_MINUTE, {"trigger_type": "interval", "schedule": {"unit": " Minutes ", "value": "1"}}, False),
    (EVERY_MINUTE, {"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 2}}, True),
    (EVERY_MINUTE, {"trigger_type": "interval", "schedule": MONDAYS_NY}, True),
    (EVERY_MINUTE, {"trigger_type": "interval", "schedule": {"unit": "weeks", "value": 1}}, True),
    (EVERY_MINUTE, {"trigger_type": "interval"}, True),
    (MONDAYS_NY, {"trigger_type": "interval", "schedule": EVERY_MINUTE}, False),
])
def test_the_minimum_applies_only_to_new_or_changed_interval_schedules(schedules, schedule, existing, applies):
    assert schedules.workflow_schedule_minimum_applies(schedule, existing) is applies


# ---------------------------------------------------------------------------------------------
# Unchanged interval schedules, fingerprints and approvals
# ---------------------------------------------------------------------------------------------

# The record, cases and values captured by running the base save code (0.261.190, commit
# 0ee7b2a4e) before calendar schedules existed. The fingerprint is the Microsoft 365 Run-as
# revision, so a different value here would invalidate every stored interval workflow's approval.
FIXED_RECORD = {
    "id": "golden-workflow",
    "user_id": "golden-owner",
    "group_id": "",
    "name": "Golden legacy workflow",
    "description": "",
    "task_prompt": "Summarize the week.",
    "tasks": [{"id": "task-1", "type": "instructions", "name": "Summarize", "instructions": "Summarize the week.",
               "order": 1, "runner": {"type": "inherit"}, "document_action": {"type": "none"}}],
    "runner_type": "model",
    "selected_agent": {},
    "conversation_id": "",
    "trigger_type": "interval",
    "is_enabled": True,
    "document_action": {"type": "none"},
    "file_sync": {"enabled": False},
    "chat_capabilities_enabled": False,
    "url_access_enabled": False,
    "model_endpoint_id": "",
    "model_id": "",
    "m365_run_as_user_id": "golden-owner",
    "definition_version": 2,
    "reference_inputs": [],
    "durable_execution": True,
}
# name: (save fields, stored schedule JSON, Run-as fingerprint, definition revision)
GOLDEN = {
    "interval_minutes": (
        {"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 30}},
        '{"unit":"minutes","value":30}',
        "8dd9dbb2ec26f3941cc614b925c473bce82f34dcde49b83dc44eb6a1f788862a",
        "ba2d53f7c9802054ab4a206cea2b23651fa1b429a59670b92f726799ee7fdcc6",
    ),
    "interval_hours_text": (
        {"trigger_type": "interval", "schedule": {"unit": " Hours ", "value": "2"}},
        '{"unit":"hours","value":2}',
        "a4848fc1d5b79ed85a67226455fc79716e7c137cd1f0cf16a1e6a1099f2456b5",
        "6ed3c051ba6c814cc41f84e645aeec4173abe64c3b4575d0ad79e760e857e3c8",
    ),
    "interval_seconds_kind": (
        {"trigger_type": "interval", "schedule": {"unit": "seconds", "value": 45, "kind": "interval"}},
        '{"unit":"seconds","value":45}',
        "82f5717dda6394c3c5db6e55d7ed176e3d8f4ad57458d10d58fae3868897e939",
        "93384d0f5a752edbc995a896ddd076ac140a0f31022c4346b9b514f672af2473",
    ),
    "interval_bool_value": (
        {"trigger_type": "interval", "schedule": {"unit": "seconds", "value": True}},
        '{"unit":"seconds","value":1}',
        "5a492922633e6cc09fa94c0350c08a2a0deff908c297ea4d5112c03c839e13e3",
        "daefaf7737ecb9be4c7325db16a763167efd97823954f0eb4c38032f73aed3ef",
    ),
    "interval_float_value": (
        {"trigger_type": "interval", "schedule": {"unit": "hours", "value": 5.9}},
        '{"unit":"hours","value":5}',
        "dc97b64de1b5d02a518e8af22950cc960d96c7423b32dbc4696b4a88f6179280",
        "0172607a0cfab5626e6dd1b9434e8381d0591402b3d3409f8581b5c70aca88e5",
    ),
    "interval_extra_keys": (
        {"trigger_type": "interval", "schedule": {"unit": "MINUTES", "value": 7, "timezone": "UTC"}},
        '{"unit":"minutes","value":7}',
        "5fb47ea6b0f4d7e653dc83ad3bc15109b72f06a9236f4f7bb1e30fdf665188c6",
        "386dd13317ab38004ad3c90f4f61f507a3f5c7d9ead1f2eb6857f58ff413d636",
    ),
    "disabled_interval": (
        {"trigger_type": "interval", "is_enabled": False, "schedule": {"unit": "minutes", "value": 15}},
        '{"unit":"minutes","value":15}',
        "a88cc0e17df8a72e6cae4194267d8ed7519cf5175c1fb961304174eb2d55852e",
        "860a8c816e6da51bd1e598d542d511d1d6e51b4d64bb87cf80871a5fc41ea6c8",
    ),
    "manual_ignores_schedule": (
        {"trigger_type": "manual", "schedule": {"unit": "minutes", "value": 5}},
        "{}",
        "9b1f56dc92268102e09f5d527429ba9aa0a673c09db34685b4e3eafd49c40c5e",
        "47b5657019ceb1d8fa40c582ab8476e68528b1feb244f596a7dc557ff08da3ff",
    ),
}


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_interval_schedules_match_the_values_captured_before_calendar_schedules(routes, scope, name):
    fields, schedule_json, fingerprint, revision = GOLDEN[name]

    saved = routes.created(scope, **fields)

    assert json.dumps(saved["schedule"], sort_keys=True, separators=(",", ":")) == schedule_json
    record = {
        **copy.deepcopy(FIXED_RECORD), "trigger_type": saved["trigger_type"], "is_enabled": saved["is_enabled"],
        "schedule": saved["schedule"],
    }
    assert routes.binding.workflow_execution_fingerprint(record) == fingerprint
    assert routes.definitions.workflow_definition_revision(record) == revision


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("schedule, changed", [
    ({"unit": "minutes", "value": 30}, {"unit": "minutes", "value": 45}),
    (MONDAYS_NY, {**MONDAYS_NY, "time_of_day": "09:00"}),
], ids=["interval", "calendar"])
def test_an_unchanged_schedule_keeps_the_run_as_approval_and_a_changed_one_needs_a_new_one(
    routes, scope, schedule, changed,
):
    created = routes.created(scope, trigger_type="interval", schedule=schedule, m365_run_as_user_id=OWNER_ID)
    routes.approve(scope, created["id"], "approval-under-test")

    response = routes.resave(scope, created["id"], description="Only the description changed.")

    assert response.status_code == 200, response.get_data(as_text=True)
    saved = response.json["workflow"]
    assert saved["schedule"] == created["schedule"]
    assert saved["next_run_at"] == created["next_run_at"]
    assert saved["m365_revision"] == created["m365_revision"]
    assert saved["m365_binding_approval_id"] == "approval-under-test"

    response = routes.resave(scope, created["id"], schedule=changed)

    assert response.status_code == 200, response.get_data(as_text=True)
    saved = response.json["workflow"]
    assert saved["m365_revision"] != created["m365_revision"]
    assert saved["m365_binding_approval_id"] is None
