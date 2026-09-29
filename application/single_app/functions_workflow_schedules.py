# functions_workflow_schedules.py
"""Workflow schedule rules: interval and calendar normalization, next runs and labels.

An interval schedule keeps its original stored shape, ``{'unit', 'value'}``, exactly. The
schedule is part of the Microsoft 365 Run-as approval fingerprint, so re-saving an unchanged
interval workflow must never change its stored record or its approval.

A calendar schedule (``kind: 'calendar'``) runs at a local wall-clock time in an IANA time zone.
Its next run follows RFC 5545: a local time that does not exist, in the spring-forward gap, runs
at the same instant the time before the gap would name (02:30 becomes 03:30 in New York), an
ambiguous local time in the fall-back overlap runs once, at its first occurrence, and a monthly
day that a month does not have runs on that month's last day.

This module imports only the standard library and the reviewed validation error, so the save
paths, the editor options, the V2 editor harnesses and the functional tests share one copy.
"""

import calendar
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

from functions_workflow_definitions import WorkflowCadenceError, WorkflowPublicValidationError


WORKFLOW_SCHEDULE_UNITS = {'seconds', 'minutes', 'hours'}
WORKFLOW_SCHEDULE_KIND_INTERVAL = 'interval'
WORKFLOW_SCHEDULE_KIND_CALENDAR = 'calendar'
WORKFLOW_SCHEDULE_KINDS = (WORKFLOW_SCHEDULE_KIND_INTERVAL, WORKFLOW_SCHEDULE_KIND_CALENDAR)
WORKFLOW_SCHEDULE_FREQUENCIES = ('daily', 'weekdays', 'weekly', 'monthly')
WORKFLOW_SCHEDULE_DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
WORKFLOW_SCHEDULED_TRIGGER_TYPES = frozenset({'interval', 'file_sync'})
WORKFLOW_SCHEDULE_TIME_PATTERN = re.compile(r'([01][0-9]|2[0-3]):([0-5][0-9])')

# tzdata ships these beside the real zones; none of them names a place a schedule could mean.
_EXCLUDED_TIMEZONES = frozenset({'Factory', 'localtime', 'posixrules'})
_UNIT_SECONDS = {'seconds': 1, 'minutes': 60, 'hours': 3600}
_WEEKDAY_INDEX = {day: index for index, day in enumerate(WORKFLOW_SCHEDULE_DAYS)}
_DAY_LABELS = {day: f'{day.capitalize()}s' for day in WORKFLOW_SCHEDULE_DAYS}
# Fixed English names, so a run's time context never depends on the server's locale.
_RUN_TIME_DAY_NAMES = tuple(day.capitalize() for day in WORKFLOW_SCHEDULE_DAYS)
_RUN_TIME_MONTH_NAMES = (
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
)

SCHEDULE_KIND_ERROR = 'Schedule kind must be interval or calendar.'
SCHEDULE_FREQUENCY_ERROR = 'Schedule frequency must be daily, weekdays, weekly or monthly.'
SCHEDULE_DAYS_ERROR = 'Schedule days of the week must be day names from monday to sunday.'
SCHEDULE_DAYS_REQUIRED_ERROR = 'Choose at least one day of the week for a weekly schedule.'
SCHEDULE_DAY_OF_MONTH_TYPE_ERROR = 'Schedule day of the month must be a whole number.'
SCHEDULE_DAY_OF_MONTH_RANGE_ERROR = 'Schedule day of the month must be between 1 and 31.'
SCHEDULE_TIME_ERROR = 'Schedule time must use 24-hour HH:MM format, such as 08:00.'
SCHEDULE_TIMEZONE_ERROR = 'Schedule time zone must be an IANA time zone name, such as America/New_York.'


@lru_cache(maxsize=1)
def workflow_schedule_timezones():
    """The IANA time zone names a calendar schedule may use.

    ``available_timezones()`` walks the whole tzdata package, which is slow, so it runs once per
    process. Names are case-sensitive and must match exactly.
    """
    return frozenset(available_timezones() - _EXCLUDED_TIMEZONES)


@lru_cache(maxsize=1)
def _sorted_workflow_schedule_timezones():
    return tuple(sorted(workflow_schedule_timezones()))


def _normalize_interval_schedule(schedule_payload):
    # The original interval rules, unchanged: stored interval schedules and their approval
    # fingerprints depend on this exact output.
    unit = str(schedule_payload.get('unit') or '').strip().lower()
    if unit not in WORKFLOW_SCHEDULE_UNITS:
        raise WorkflowPublicValidationError('Schedule unit must be seconds, minutes or hours.')

    try:
        value = int(schedule_payload.get('value'))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: the request JSON parser accepts Infinity, which int() cannot convert.
        raise WorkflowPublicValidationError('Schedule value must be a whole number.')

    max_value = 59 if unit in ('seconds', 'minutes') else 24
    if value < 1 or value > max_value:
        # The unit is one of WORKFLOW_SCHEDULE_UNITS and the limit is fixed, so no caller text is echoed.
        raise WorkflowPublicValidationError(f'Schedule value for {unit} must be between 1 and {max_value}.')

    return {
        'unit': unit,
        'value': value,
    }


def _normalize_days_of_week(value):
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise WorkflowPublicValidationError(SCHEDULE_DAYS_ERROR)
    selected = set()
    for day in value:
        if not isinstance(day, str) or day.strip().lower() not in _WEEKDAY_INDEX:
            raise WorkflowPublicValidationError(SCHEDULE_DAYS_ERROR)
        selected.add(day.strip().lower())
    if not selected:
        raise WorkflowPublicValidationError(SCHEDULE_DAYS_REQUIRED_ERROR)
    return [day for day in WORKFLOW_SCHEDULE_DAYS if day in selected]


def _normalize_day_of_month(value):
    if isinstance(value, bool):
        raise WorkflowPublicValidationError(SCHEDULE_DAY_OF_MONTH_TYPE_ERROR)
    if isinstance(value, float):
        if not value.is_integer():
            raise WorkflowPublicValidationError(SCHEDULE_DAY_OF_MONTH_TYPE_ERROR)
        value = int(value)
    if not isinstance(value, int):
        raise WorkflowPublicValidationError(SCHEDULE_DAY_OF_MONTH_TYPE_ERROR)
    if value < 1 or value > 31:
        raise WorkflowPublicValidationError(SCHEDULE_DAY_OF_MONTH_RANGE_ERROR)
    return value


def _normalize_calendar_schedule(schedule_payload):
    frequency = str(schedule_payload.get('frequency') or '').strip().lower()
    if frequency not in WORKFLOW_SCHEDULE_FREQUENCIES:
        raise WorkflowPublicValidationError(SCHEDULE_FREQUENCY_ERROR)

    days_of_week = []
    day_of_month = None
    if frequency == 'weekly':
        days_of_week = _normalize_days_of_week(schedule_payload.get('days_of_week'))
    elif frequency == 'monthly':
        day_of_month = _normalize_day_of_month(schedule_payload.get('day_of_month'))

    time_of_day = schedule_payload.get('time_of_day')
    time_of_day = time_of_day.strip() if isinstance(time_of_day, str) else ''
    if not WORKFLOW_SCHEDULE_TIME_PATTERN.fullmatch(time_of_day):
        raise WorkflowPublicValidationError(SCHEDULE_TIME_ERROR)

    timezone_name = schedule_payload.get('timezone')
    timezone_name = timezone_name.strip() if isinstance(timezone_name, str) else ''
    if timezone_name not in workflow_schedule_timezones():
        raise WorkflowPublicValidationError(SCHEDULE_TIMEZONE_ERROR)

    return {
        'kind': WORKFLOW_SCHEDULE_KIND_CALENDAR,
        'frequency': frequency,
        'days_of_week': days_of_week,
        'day_of_month': day_of_month,
        'time_of_day': time_of_day,
        'timezone': timezone_name,
    }


def normalize_workflow_schedule(schedule_payload):
    """Return the stored form of a workflow schedule, or raise a reviewed validation error.

    A payload without ``kind``, or with ``kind: 'interval'``, is an interval schedule and returns
    exactly ``{'unit', 'value'}``, as it always has. ``kind: 'calendar'`` returns every calendar
    field, with ``days_of_week`` only for weekly schedules and ``day_of_month`` only for monthly.
    """
    schedule_payload = schedule_payload if isinstance(schedule_payload, dict) else {}
    kind = str(schedule_payload.get('kind') or WORKFLOW_SCHEDULE_KIND_INTERVAL).strip().lower()
    if kind == WORKFLOW_SCHEDULE_KIND_INTERVAL:
        return _normalize_interval_schedule(schedule_payload)
    if kind == WORKFLOW_SCHEDULE_KIND_CALENDAR:
        return _normalize_calendar_schedule(schedule_payload)
    raise WorkflowPublicValidationError(SCHEDULE_KIND_ERROR)


def is_calendar_workflow_schedule(schedule):
    """Whether a stored schedule is a calendar schedule, without validating it."""
    return isinstance(schedule, Mapping) and schedule.get('kind') == WORKFLOW_SCHEDULE_KIND_CALENDAR


def workflow_schedule_interval_seconds(schedule):
    """The length of a normalized interval schedule in seconds, or None for any other schedule."""
    if not isinstance(schedule, Mapping) or schedule.get('kind') is not None:
        return None
    unit_seconds = _UNIT_SECONDS.get(schedule.get('unit'))
    value = schedule.get('value')
    if unit_seconds is None or type(value) is not int:
        return None
    return value * unit_seconds


def format_workflow_schedule_duration(seconds):
    """Name a whole number of seconds in the largest unit that divides it evenly."""
    for unit, size in (('hour', 3600), ('minute', 60)):
        if seconds % size == 0:
            count = seconds // size
            return f'{count} {unit}' if count == 1 else f'{count} {unit}s'
    return '1 second' if seconds == 1 else f'{seconds} seconds'


def workflow_schedule_minimum_applies(schedule, existing_workflow=None):
    """Whether the administrator's minimum interval governs saving this schedule.

    Only a new or changed interval schedule is checked. A calendar schedule never is, and an
    interval that the stored workflow already runs on keeps working when the minimum is raised.
    """
    if workflow_schedule_interval_seconds(schedule) is None:
        return False
    existing = existing_workflow if isinstance(existing_workflow, Mapping) else {}
    if str(existing.get('trigger_type') or '').strip().lower() not in WORKFLOW_SCHEDULED_TRIGGER_TYPES:
        return True
    try:
        previous = normalize_workflow_schedule(existing.get('schedule'))
    except WorkflowPublicValidationError:
        return True
    return previous != schedule


def enforce_workflow_schedule_minimum(schedule, min_interval_seconds):
    """Refuse an interval schedule that runs more often than the administrator allows."""
    seconds = workflow_schedule_interval_seconds(schedule)
    if seconds is not None and seconds < min_interval_seconds:
        # The minimum is administrator policy, not caller text, so naming it is safe.
        raise WorkflowPublicValidationError(
            'This schedule runs more often than the administrator allows. '
            f'Choose an interval of at least {format_workflow_schedule_duration(min_interval_seconds)}.'
        )
    return schedule


def enforce_orchestration_workflow_cadence(schedule, min_interval_seconds):
    """Refuse an interval that runs a workflow created from chat more often than its own floor.

    Calendar schedules repeat at most daily, so they always pass.
    """
    seconds = workflow_schedule_interval_seconds(schedule)
    if seconds is not None and seconds < min_interval_seconds:
        # The minimum is administrator policy, not caller text, so naming it is safe.
        raise WorkflowCadenceError(
            'Workflows created from chat cannot run this often. '
            f'Choose an interval of at least {format_workflow_schedule_duration(min_interval_seconds)}, '
            'or a daily, weekly or monthly schedule.'
        )
    return schedule


def _utc_reference(from_time):
    reference = from_time or datetime.now(timezone.utc)
    if isinstance(reference, str):
        reference = datetime.fromisoformat(reference)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc)


def _calendar_candidate_dates(schedule, local_today):
    # Starting a day early covers a gap that moves the previous day's time past midnight.
    if schedule['frequency'] == 'monthly':
        month_index = local_today.year * 12 + local_today.month - 1
        for offset in range(-1, 3):
            year, month = divmod(month_index + offset, 12)
            last_day = calendar.monthrange(year, month + 1)[1]
            yield date(year, month + 1, min(schedule['day_of_month'], last_day))
        return

    if schedule['frequency'] == 'daily':
        weekdays = set(range(7))
    elif schedule['frequency'] == 'weekdays':
        weekdays = set(range(5))
    else:
        weekdays = {_WEEKDAY_INDEX[day] for day in schedule['days_of_week']}
    for offset in range(-1, 15):
        candidate = local_today + timedelta(days=offset)
        if candidate.weekday() in weekdays:
            yield candidate


def next_workflow_schedule_run(schedule, from_time=None):
    """Return the first run of a calendar schedule strictly after ``from_time``, as UTC ISO text.

    Raises a reviewed validation error when the schedule is not a valid calendar schedule.
    """
    normalized = normalize_workflow_schedule(schedule)
    if normalized.get('kind') != WORKFLOW_SCHEDULE_KIND_CALENDAR:
        raise WorkflowPublicValidationError(SCHEDULE_KIND_ERROR)

    reference = _utc_reference(from_time)
    zone = ZoneInfo(normalized['timezone'])
    hour, minute = (int(part) for part in normalized['time_of_day'].split(':'))
    local_today = reference.astimezone(zone).date()
    for candidate_date in _calendar_candidate_dates(normalized, local_today):
        # fold=0 is RFC 5545's rule: the offset before a transition names both gap and overlap times.
        candidate = datetime.combine(candidate_date, time(hour, minute), tzinfo=zone).astimezone(timezone.utc)
        if candidate > reference:
            return candidate.isoformat()
    return None


def workflow_run_time_context(schedule, run_started_at):
    """Tell the model when a calendar workflow run started, in the schedule's own time zone.

    Returns, for example, ``Current date and time: Monday, 28 September 2026, 09:00
    (America/New_York)``, so a prompt such as "list this week's to-dos" resolves against the
    run's local date. Any schedule that is not a valid calendar schedule, and any start time that
    cannot be read, returns an empty string; this never raises. A naive start time is UTC. The line
    is prompt context only: it is never stored in a workflow definition or its fingerprint.
    """
    if not isinstance(schedule, dict):
        return ''
    try:
        normalized = normalize_workflow_schedule(schedule)
        if normalized.get('kind') != WORKFLOW_SCHEDULE_KIND_CALENDAR:
            return ''
        started = datetime.fromisoformat(run_started_at.strip()) if isinstance(run_started_at, str) else run_started_at
        if not isinstance(started, datetime):
            return ''
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        local = started.astimezone(ZoneInfo(normalized['timezone']))
    except (WorkflowPublicValidationError, KeyError, ValueError, TypeError, OverflowError):
        return ''
    return (
        f'Current date and time: {_RUN_TIME_DAY_NAMES[local.weekday()]}, {local.day} '
        f'{_RUN_TIME_MONTH_NAMES[local.month - 1]} {local.year}, {local.hour:02d}:{local.minute:02d} '
        f"({normalized['timezone']})"
    )


def _join_labels(labels):
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def _calendar_label(schedule):
    frequency = schedule['frequency']
    at = f"{schedule['time_of_day']} {schedule['timezone']}"
    if frequency == 'daily':
        return f'Daily {at}'
    if frequency == 'weekdays':
        return f'Weekdays {at}'
    if frequency == 'weekly':
        return f"{_join_labels([_DAY_LABELS[day] for day in schedule['days_of_week']])} {at}"
    day = schedule['day_of_month']
    suffix = ' (or last day)' if day > 28 else ''
    return f'Monthly on day {day}{suffix}, {at}'


def _interval_label(schedule):
    unit = schedule['unit']
    value = schedule['value']
    if value == 1:
        return f'Every {unit[:-1]}'
    return f'Every {value} {unit}'


def workflow_schedule_label(trigger_type, schedule):
    """A short, readable description of when a scheduled workflow runs, or '' when it does not."""
    trigger = str(trigger_type or '').strip().lower()
    if trigger not in WORKFLOW_SCHEDULED_TRIGGER_TYPES:
        return ''
    try:
        normalized = normalize_workflow_schedule(schedule)
    except WorkflowPublicValidationError:
        return ''
    if normalized.get('kind') == WORKFLOW_SCHEDULE_KIND_CALENDAR:
        cadence = _calendar_label(normalized)
        return f'Monitor File Sync: {cadence}' if trigger == 'file_sync' else cadence
    cadence = _interval_label(normalized)
    return f'Monitor File Sync {cadence[0].lower()}{cadence[1:]}' if trigger == 'file_sync' else cadence


def workflow_schedule_summary(trigger_type, schedule):
    """The normalized schedule of a scheduled workflow, or {} for a manual or unreadable one.

    Normalizing drops any field the schedule rules do not define, so a summary never repeats
    stray stored data.
    """
    if str(trigger_type or '').strip().lower() not in WORKFLOW_SCHEDULED_TRIGGER_TYPES:
        return {}
    try:
        return normalize_workflow_schedule(schedule)
    except WorkflowPublicValidationError:
        return {}


def build_workflow_schedule_editor_options(*, min_interval_seconds):
    """The schedule choices and limits the V2 workflow editor offers."""
    return {
        'kinds': list(WORKFLOW_SCHEDULE_KINDS),
        'units': ['seconds', 'minutes', 'hours'],
        'frequencies': list(WORKFLOW_SCHEDULE_FREQUENCIES),
        'days_of_week': list(WORKFLOW_SCHEDULE_DAYS),
        'timezones': list(_sorted_workflow_schedule_timezones()),
        'min_interval_seconds': min_interval_seconds,
    }
