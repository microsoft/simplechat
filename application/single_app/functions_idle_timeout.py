# functions_idle_timeout.py

"""Idle-session timeout settings, shared by the web app and the V2 bootstrap payload.

``app.py`` enforces the idle timeout in a ``before_request`` hook and hands the values to the
classic templates. The V2 SPA cannot read template context, so ``route_backend_v2`` sends the
same values in its bootstrap payload. Route modules are imported by ``app.py``, which means
they cannot import anything from it; both sides import this module instead, so the server and
the browser read one definition of what the timeout and the warning are.

Everything here works on the settings dictionary it is handed. Nothing is imported from
``config``, ``functions_settings`` or ``app``, so the module loads before any of them.
"""

import logging

from functions_appinsights import log_event

# Matches the admin schema (``IDLE_TIMEOUT_MIN_MINUTES`` and ``IDLE_WARNING_MIN_MINUTES`` in
# ``admin_settings_fields``): a timeout under ten minutes signs people out mid-task, and the
# warning cannot arrive before the activity it follows.
IDLE_TIMEOUT_MIN_MINUTES = 10
IDLE_WARNING_MIN_MINUTES = 0
IDLE_WARNING_MESSAGE_MAX_LENGTH = 200
IDLE_WARNING_DEFAULT_MESSAGE = "You've been inactive for a while."


def get_idle_timeout_settings(settings):
    """
    Resolve and normalize idle timeout settings used for warning and logout enforcement.

    Args:
        settings (dict): Settings dictionary to read.

    Returns:
        tuple[int, int]: A tuple of (idle_timeout_minutes, idle_warning_minutes)
                         after parsing, fallback handling, and boundary normalization.

    Raises:
        None: Invalid values are handled via fallback defaults and warning logs.
    """
    timeout_raw = settings.get('idle_timeout_minutes', 30)
    warning_raw = settings.get('idle_warning_minutes', 28)

    try:
        timeout_minutes = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_minutes = 30
        log_event(
            "[IDLE_TIMEOUT] Invalid idle timeout value detected; using default.",
            extra={
                "setting": "idle_timeout_minutes",
                "raw_value": str(timeout_raw),
                "fallback_value": 30
            },
            level=logging.WARNING
        )

    try:
        warning_minutes = int(warning_raw)
    except (TypeError, ValueError):
        warning_minutes = 28
        log_event(
            "[IDLE_TIMEOUT] Invalid idle warning value detected; using default.",
            extra={
                "setting": "idle_warning_minutes",
                "raw_value": str(warning_raw),
                "fallback_value": 28
            },
            level=logging.WARNING
        )

    normalized_timeout = max(IDLE_TIMEOUT_MIN_MINUTES, timeout_minutes)
    if normalized_timeout != timeout_minutes:
        log_event(
            "[IDLE_TIMEOUT] Idle timeout value normalized to minimum allowed value.",
            extra={
                "setting": "idle_timeout_minutes",
                "original_value": timeout_minutes,
                "normalized_value": normalized_timeout
            },
            level=logging.WARNING
        )
    timeout_minutes = normalized_timeout

    normalized_warning = max(IDLE_WARNING_MIN_MINUTES, warning_minutes)
    if normalized_warning != warning_minutes:
        log_event(
            "[IDLE_TIMEOUT] Idle warning value normalized to minimum allowed value.",
            extra={
                "setting": "idle_warning_minutes",
                "original_value": warning_minutes,
                "normalized_value": normalized_warning
            },
            level=logging.WARNING
        )
    warning_minutes = normalized_warning

    if warning_minutes > timeout_minutes:
        previous_warning_minutes = warning_minutes
        warning_minutes = timeout_minutes
        log_event(
            "[IDLE_TIMEOUT] Idle warning value adjusted to not exceed idle timeout.",
            extra={
                "idle_timeout_minutes": timeout_minutes,
                "original_idle_warning_minutes": previous_warning_minutes,
                "adjusted_idle_warning_minutes": warning_minutes
            },
            level=logging.WARNING
        )

    return timeout_minutes, warning_minutes


def is_idle_timeout_enabled(settings):
    """
    Determine whether idle-timeout enforcement is enabled.

    Args:
        settings (dict): Settings dictionary to read.

    Returns:
        bool: True when idle-timeout enforcement should run; otherwise False.

    Raises:
        None: Unexpected values are coerced to boolean-compatible behavior.
    """
    enabled_raw = settings.get('enable_idle_timeout', False)

    if isinstance(enabled_raw, str):
        return enabled_raw.strip().lower() in ('1', 'true', 'yes', 'on')

    return bool(enabled_raw)


def get_idle_warning_message(settings):
    """
    Return the administrator's idle-warning sentence, or the default when it is blank.

    Args:
        settings (dict): Settings dictionary to read.

    Returns:
        str: Plain text no longer than ``IDLE_WARNING_MESSAGE_MAX_LENGTH`` characters. The
             caller renders it as text, never as markup.

    Raises:
        None
    """
    message = settings.get('idle_warning_message')
    if not isinstance(message, str):
        return IDLE_WARNING_DEFAULT_MESSAGE
    return message.strip()[:IDLE_WARNING_MESSAGE_MAX_LENGTH].strip() or IDLE_WARNING_DEFAULT_MESSAGE


def build_idle_timeout_bootstrap(settings):
    """
    Build the idle-timeout block the V2 bootstrap payload carries under ``session``.

    Args:
        settings (dict): Settings dictionary to read. Only the four idle-timeout keys are
                         read, and only normalized values leave this function.

    Returns:
        dict: ``enabled``, ``timeout_minutes``, ``warning_minutes`` and ``warning_message``,
              normalized exactly as the server enforces them.

    Raises:
        None
    """
    timeout_minutes, warning_minutes = get_idle_timeout_settings(settings)
    return {
        "enabled": is_idle_timeout_enabled(settings),
        "timeout_minutes": timeout_minutes,
        "warning_minutes": warning_minutes,
        "warning_message": get_idle_warning_message(settings),
    }
