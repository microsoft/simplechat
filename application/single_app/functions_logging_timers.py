# functions_logging_timers.py
"""Time-based automatic turnoff for the debug and file processing logs.

Each log carries three controls besides its own switch: a timer switch, a duration
and a unit. When the timer is on, saving works out a turnoff time, and the
background checker switches the log off once that time has passed.

Three callers need the same rules -- the server-rendered Admin Settings form, the
V2 admin settings PATCH and the background checker -- so they live here once:

``LOGGING_TIMER_UNIT_LIMITS``
    The durations each unit accepts.

``resolve_logging_timer_settings``
    The timer settings a save leaves behind. The turnoff time is only
    recalculated when the timer settings change, when the log has just been
    switched on, or when no usable turnoff time is stored, so saving an unrelated
    setting does not quietly extend a running timer.

``parse_logging_turnoff_time`` / ``is_logging_turnoff_due``
    Read a stored turnoff time. New values are stored as UTC with an explicit
    offset, which is what lets an administrator be shown the time in their own
    zone. Values written before that carry no offset; they were produced by
    ``datetime.now()`` on the server, so they are read as server-local time,
    which is exactly what the checker used to compare them with.

The module imports nothing from the application, so the settings normalizer can
use it without reaching ``config``.
"""

from datetime import datetime, timedelta, timezone


LOGGING_TIMER_UNIT_LIMITS = {
    'minutes': (1, 120),
    'hours': (1, 24),
    'days': (1, 7),
    'weeks': (1, 52),
}
LOGGING_TIMER_DEFAULT_UNIT = 'hours'
LOGGING_TIMER_DEFAULT_VALUE = 1

# The settings keys each log's timer is stored under.
LOGGING_TIMERS = {
    'debug': {
        'enabled_key': 'enable_debug_logging',
        'timer_key': 'debug_logging_timer_enabled',
        'value_key': 'debug_timer_value',
        'unit_key': 'debug_timer_unit',
        'turnoff_key': 'debug_logging_turnoff_time',
    },
    'file': {
        'enabled_key': 'enable_file_processing_logs',
        'timer_key': 'file_processing_logs_timer_enabled',
        'value_key': 'file_timer_value',
        'unit_key': 'file_timer_unit',
        'turnoff_key': 'file_processing_logs_turnoff_time',
    },
}

_TRUE_STRINGS = ('true', 'on', 'yes', '1')


def _coerce_bool(value):
    """Read a stored or submitted switch value as a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    return bool(value)


def _as_utc(moment):
    """Return an aware UTC datetime; a naive value is taken to already be UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def normalize_logging_timer_unit(unit):
    """Return a supported unit, falling back to hours for anything else."""
    normalized = str(unit or '').strip().lower()
    if normalized in LOGGING_TIMER_UNIT_LIMITS:
        return normalized
    return LOGGING_TIMER_DEFAULT_UNIT


def clamp_logging_timer_value(value, unit):
    """Return ``(value, unit)`` with the duration inside the unit's range.

    A value that is not a number falls back to the default duration rather than
    failing the save, because the duration is meaningless on its own and the
    unit's range is applied straight afterwards anyway.
    """
    normalized_unit = normalize_logging_timer_unit(unit)
    minimum, maximum = LOGGING_TIMER_UNIT_LIMITS[normalized_unit]
    if isinstance(value, bool):
        number = LOGGING_TIMER_DEFAULT_VALUE
    else:
        try:
            number = int(float(value))
        except (TypeError, ValueError, OverflowError):
            number = LOGGING_TIMER_DEFAULT_VALUE
    return min(max(number, minimum), maximum), normalized_unit


def calculate_logging_turnoff_time(value, unit, now=None):
    """Return the UTC moment a timer of this duration started ``now`` ends."""
    duration, normalized_unit = clamp_logging_timer_value(value, unit)
    reference = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    return reference + timedelta(**{normalized_unit: duration})


def parse_logging_turnoff_time(value):
    """Return a stored turnoff time as an aware UTC datetime, or None.

    Values stored without an offset predate UTC storage. They were written with
    the server's ``datetime.now()``, so they are interpreted as server-local
    time rather than as UTC.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def is_logging_turnoff_due(value, now=None):
    """Whether a stored turnoff time has been reached."""
    turnoff = parse_logging_turnoff_time(value)
    if turnoff is None:
        return False
    reference = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    return reference >= turnoff


def resolve_logging_timer_settings(kind, incoming, existing=None, now=None):
    """Return the timer settings a save of one log leaves behind.

    ``kind`` is ``'debug'`` or ``'file'``. ``incoming`` holds the values being
    saved, keyed by their settings keys; any key it does not carry keeps its
    stored value from ``existing``. The server-rendered form submits every key and
    the V2 PATCH only the edited ones, and both take this one path.

    The turnoff time is recalculated only when the timer switch, duration or unit
    changed, when the log has just been switched on, or when no usable turnoff time
    is stored. It is cleared whenever the log or its timer is off.
    """
    keys = LOGGING_TIMERS[kind]
    existing = existing or {}

    def merged(key, default):
        if key in incoming:
            return incoming[key]
        stored = existing.get(key)
        return default if stored is None else stored

    enabled = _coerce_bool(merged(keys['enabled_key'], False))
    timer_enabled = _coerce_bool(merged(keys['timer_key'], False))
    value, unit = clamp_logging_timer_value(
        merged(keys['value_key'], LOGGING_TIMER_DEFAULT_VALUE),
        merged(keys['unit_key'], LOGGING_TIMER_DEFAULT_UNIT),
    )

    existing_enabled = _coerce_bool(existing.get(keys['enabled_key'], False))
    existing_timer_enabled = _coerce_bool(existing.get(keys['timer_key'], False))
    existing_value = existing.get(keys['value_key'], LOGGING_TIMER_DEFAULT_VALUE)
    existing_unit = existing.get(keys['unit_key'], LOGGING_TIMER_DEFAULT_UNIT)
    existing_turnoff = parse_logging_turnoff_time(existing.get(keys['turnoff_key']))

    timer_changed = (
        timer_enabled != existing_timer_enabled
        or value != existing_value
        or unit != existing_unit
    )
    newly_enabled = enabled and not existing_enabled

    if not (enabled and timer_enabled):
        turnoff = None
    elif timer_changed or newly_enabled or existing_turnoff is None:
        turnoff = calculate_logging_turnoff_time(value, unit, now=now).isoformat()
    else:
        turnoff = existing_turnoff.isoformat()

    return {
        keys['timer_key']: timer_enabled,
        keys['value_key']: value,
        keys['unit_key']: unit,
        keys['turnoff_key']: turnoff,
    }
