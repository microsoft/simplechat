# functions_stats_windows.py
"""Shared helpers for stats pages that support selectable date windows."""

from datetime import datetime, timedelta, timezone


DEFAULT_STATS_WINDOW_DAYS = 30
ALLOWED_STATS_WINDOW_DAYS = (7, 30, 90)


def _get_request_value(source, key, default=None):
    if source is None:
        return default
    if hasattr(source, 'get'):
        return source.get(key, default)
    return default


def _parse_date_value(value, field_name):
    normalized_value = str(value or '').strip()
    if not normalized_value:
        raise ValueError(f'{field_name} is required.')

    try:
        parsed_date = datetime.fromisoformat(normalized_value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{field_name} must use YYYY-MM-DD format.') from exc

    if parsed_date.tzinfo is not None:
        parsed_date = parsed_date.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed_date


def _normalize_days(raw_days, default_days=DEFAULT_STATS_WINDOW_DAYS):
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return default_days

    if days not in ALLOWED_STATS_WINDOW_DAYS:
        return default_days

    return days


def _format_display_date(date_value):
    return f'{date_value.month}/{date_value.day}/{date_value.year}'


def resolve_stats_time_window(source=None, default_days=DEFAULT_STATS_WINDOW_DAYS):
    """Resolve a 7/30/90/custom stats window from request args or a dict."""
    custom_start = _get_request_value(source, 'start_date')
    custom_end = _get_request_value(source, 'end_date')

    if custom_start or custom_end:
        start_date = _parse_date_value(custom_start, 'start_date').replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end_date = _parse_date_value(custom_end, 'end_date').replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
        if start_date > end_date:
            raise ValueError('start_date must be before or equal to end_date.')

        days = (end_date.date() - start_date.date()).days + 1
        label = f'{_format_display_date(start_date)} - {_format_display_date(end_date)}'
        window_type = 'custom'
    else:
        days = _normalize_days(_get_request_value(source, 'days', default_days), default_days=default_days)
        end_date = datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=999999)
        start_date = (end_date - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        label = f'Last {days} Days'
        window_type = 'days'

    return {
        'type': window_type,
        'days': days,
        'label': label,
        'start_date': start_date,
        'end_date': end_date,
        'start_date_iso': start_date.isoformat(),
        'end_date_iso': end_date.isoformat(),
    }


def build_stats_date_series(start_date, end_date):
    """Return inclusive date keys and short labels between two datetimes."""
    current_date = start_date.date()
    final_date = end_date.date()
    series = []

    while current_date <= final_date:
        series.append({
            'date': current_date.isoformat(),
            'label': f'{current_date.month}/{current_date.day}',
        })
        current_date += timedelta(days=1)

    return series


def timestamp_to_stats_date_key(timestamp_value):
    """Normalize an activity timestamp into a YYYY-MM-DD bucket key."""
    if not timestamp_value:
        return None

    try:
        parsed_timestamp = datetime.fromisoformat(str(timestamp_value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None

    if parsed_timestamp.tzinfo is not None:
        parsed_timestamp = parsed_timestamp.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed_timestamp.strftime('%Y-%m-%d')


def stats_window_response_payload(stats_window):
    """Return the JSON-safe subset of a resolved stats window."""
    return {
        'type': stats_window.get('type', 'days'),
        'days': stats_window.get('days', DEFAULT_STATS_WINDOW_DAYS),
        'label': stats_window.get('label', f'Last {DEFAULT_STATS_WINDOW_DAYS} Days'),
        'startDate': stats_window.get('start_date_iso', ''),
        'endDate': stats_window.get('end_date_iso', ''),
    }