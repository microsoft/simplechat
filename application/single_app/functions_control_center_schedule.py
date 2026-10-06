# functions_control_center_schedule.py
"""Daily schedule rules for the Control Center metrics refresh.

The refresh runs once a day at a wall-clock time in an IANA timezone, and the next
run is stored as a UTC timestamp that the scheduler compares against. The
scheduler and the Control Center routes need these rules, and so do both admin
surfaces: the server-rendered Admin Settings form and the V2 admin settings PATCH.

The module imports nothing from the application. ``functions_control_center``
reaches ``config``, which builds Azure clients on import, so keeping the pure rules
here is what lets the V2 settings normalizer share them without pulling that
chain into ``admin_settings_fields``. ``functions_control_center`` re-exports every
name, so existing imports keep working.
"""

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CONTROL_CENTER_DEFAULT_AUTO_REFRESH_HOUR = 2
CONTROL_CENTER_DEFAULT_AUTO_REFRESH_MINUTE = 0
CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIME = '02:00'
CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIMEZONE = 'America/New_York'

# A refresh time as a browser time input submits it: 24-hour HH:MM, with seconds
# tolerated because some browsers add them. Seconds are dropped on save.
CONTROL_CENTER_AUTO_REFRESH_TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$')

_TRUE_STRINGS = ('true', 'on', 'yes', '1')


def _coerce_bool(value):
    """Read a stored or submitted switch value as a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    return bool(value)


def normalize_control_center_auto_refresh_time(
    schedule_time=None,
    schedule_hour=None,
    schedule_minute=None,
    schedule_timezone=None,
):
    """Return a normalized daily refresh rule with an IANA timezone."""
    normalized_hour = CONTROL_CENTER_DEFAULT_AUTO_REFRESH_HOUR
    normalized_minute = CONTROL_CENTER_DEFAULT_AUTO_REFRESH_MINUTE

    if isinstance(schedule_time, str) and schedule_time.strip():
        time_parts = schedule_time.strip().split(':')
        if len(time_parts) >= 2:
            try:
                parsed_hour = int(time_parts[0])
                parsed_minute = int(time_parts[1])
                if 0 <= parsed_hour <= 23 and 0 <= parsed_minute <= 59:
                    normalized_hour = parsed_hour
                    normalized_minute = parsed_minute
            except (TypeError, ValueError):
                pass
    else:
        try:
            parsed_hour = int(schedule_hour)
            if 0 <= parsed_hour <= 23:
                normalized_hour = parsed_hour
        except (TypeError, ValueError):
            pass

        try:
            parsed_minute = int(schedule_minute)
            if 0 <= parsed_minute <= 59:
                normalized_minute = parsed_minute
        except (TypeError, ValueError):
            pass

    normalized_timezone = (
        schedule_timezone.strip()
        if isinstance(schedule_timezone, str) and schedule_timezone.strip()
        else CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIMEZONE
    )
    try:
        ZoneInfo(normalized_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        normalized_timezone = CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIMEZONE

    return {
        'hour': normalized_hour,
        'minute': normalized_minute,
        'time': f"{normalized_hour:02d}:{normalized_minute:02d}",
        'timezone': normalized_timezone,
    }


def get_control_center_auto_refresh_schedule(settings=None):
    """Normalize schedule fields from app settings."""
    settings = settings or {}
    return normalize_control_center_auto_refresh_time(
        settings.get('control_center_auto_refresh_time'),
        settings.get('control_center_auto_refresh_hour'),
        settings.get('control_center_auto_refresh_minute'),
        settings.get('control_center_auto_refresh_timezone'),
    )


def calculate_next_control_center_auto_refresh_run(settings=None, current_time=None):
    """Calculate the next daily Control Center refresh as a UTC datetime."""
    current_time = current_time or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    schedule = get_control_center_auto_refresh_schedule(settings)
    schedule_timezone = ZoneInfo(schedule['timezone'])
    local_current_time = current_time.astimezone(schedule_timezone)
    next_run_local = local_current_time.replace(
        hour=schedule['hour'],
        minute=schedule['minute'],
        second=0,
        microsecond=0,
    )
    if next_run_local <= local_current_time:
        next_run_local += timedelta(days=1)

    return next_run_local.astimezone(timezone.utc)


def parse_control_center_auto_refresh_datetime(timestamp_value):
    """Parse an ISO timestamp as a timezone-aware UTC datetime."""
    if not timestamp_value:
        return None

    try:
        if isinstance(timestamp_value, datetime):
            parsed_datetime = timestamp_value
        else:
            normalized_value = timestamp_value.replace('Z', '+00:00') if isinstance(timestamp_value, str) else timestamp_value
            parsed_datetime = datetime.fromisoformat(normalized_value)
        if parsed_datetime.tzinfo is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
        return parsed_datetime.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def is_control_center_auto_refresh_due(settings=None, current_time=None):
    """Return whether an enabled schedule has reached its saved UTC next run."""
    settings = settings or {}
    if not settings.get('control_center_auto_refresh_enabled', True):
        return False

    next_run = parse_control_center_auto_refresh_datetime(
        settings.get('control_center_auto_refresh_next_run')
    )
    if not next_run:
        return False

    current_time = current_time or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    return current_time >= next_run


def is_valid_control_center_auto_refresh_time(value):
    """Whether a submitted refresh time is a 24-hour ``HH:MM`` value.

    ``normalize_control_center_auto_refresh_time`` quietly falls back to 02:00 for
    anything it cannot read, which is right for a stored value but wrong for one
    an administrator just typed: the V2 surface reports it on the field instead.
    """
    return isinstance(value, str) and bool(
        CONTROL_CENTER_AUTO_REFRESH_TIME_PATTERN.match(value.strip())
    )


def is_valid_control_center_auto_refresh_timezone(value):
    """Whether a submitted value names an IANA timezone this server knows."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def resolve_control_center_auto_refresh_settings(incoming, existing=None, current_time=None):
    """Return the schedule settings a save leaves behind.

    ``incoming`` holds any of ``control_center_auto_refresh_enabled``,
    ``control_center_auto_refresh_time`` and ``control_center_auto_refresh_timezone``;
    anything it does not carry keeps its stored value from ``existing``. The
    server-rendered form submits all three and the V2 PATCH only the edited ones.

    The next run is recalculated only when the switch, time or timezone changed, or
    when none is stored, so saving an unrelated setting does not move a scheduled
    refresh. It is cleared while the schedule is off.
    """
    existing = existing or {}

    def merged(key, default):
        if key in incoming:
            return incoming[key]
        stored = existing.get(key)
        return default if stored is None else stored

    enabled = _coerce_bool(merged('control_center_auto_refresh_enabled', True))
    schedule = get_control_center_auto_refresh_schedule({
        'control_center_auto_refresh_time': merged(
            'control_center_auto_refresh_time',
            CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIME,
        ),
        'control_center_auto_refresh_hour': existing.get(
            'control_center_auto_refresh_hour',
            CONTROL_CENTER_DEFAULT_AUTO_REFRESH_HOUR,
        ),
        'control_center_auto_refresh_minute': existing.get(
            'control_center_auto_refresh_minute',
            CONTROL_CENTER_DEFAULT_AUTO_REFRESH_MINUTE,
        ),
        'control_center_auto_refresh_timezone': merged(
            'control_center_auto_refresh_timezone',
            CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIMEZONE,
        ),
    })
    existing_schedule = get_control_center_auto_refresh_schedule(existing)
    existing_enabled = _coerce_bool(existing.get('control_center_auto_refresh_enabled', True))
    existing_next_run = existing.get('control_center_auto_refresh_next_run')

    schedule_changed = (
        enabled != existing_enabled
        or schedule['time'] != existing_schedule['time']
        or schedule['timezone'] != existing_schedule['timezone']
    )

    if not enabled:
        next_run = None
    elif schedule_changed or not existing_next_run:
        next_run = calculate_next_control_center_auto_refresh_run(
            {
                'control_center_auto_refresh_time': schedule['time'],
                'control_center_auto_refresh_hour': schedule['hour'],
                'control_center_auto_refresh_minute': schedule['minute'],
                'control_center_auto_refresh_timezone': schedule['timezone'],
            },
            current_time=current_time or datetime.now(timezone.utc),
        ).isoformat()
    else:
        next_run = existing_next_run

    return {
        'control_center_auto_refresh_enabled': enabled,
        'control_center_auto_refresh_time': schedule['time'],
        'control_center_auto_refresh_hour': schedule['hour'],
        'control_center_auto_refresh_minute': schedule['minute'],
        'control_center_auto_refresh_timezone': schedule['timezone'],
        'control_center_auto_refresh_next_run': next_run,
    }
