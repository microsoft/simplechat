# functions_ai_notice.py
"""Helpers for the configurable AI notice shown below the chat composer."""

import hashlib
import json
import re
from datetime import datetime, timezone


AI_NOTICE_FREQUENCIES = ("non_dismissible", "every_session", "daily", "once")
AI_NOTICE_DEFAULT_FREQUENCY = "non_dismissible"
AI_NOTICE_MAX_MESSAGE_LENGTH = 1000
AI_NOTICE_USER_SETTINGS_KEY = "aiNoticeDismissal"
_AI_NOTICE_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def normalize_ai_notice_frequency(value):
    """Normalize the configured AI notice display frequency."""
    normalized_value = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "always": "non_dismissible",
        "non_dismissible": "non_dismissible",
        "persistent": "non_dismissible",
        "session": "every_session",
        "every_session": "every_session",
        "per_session": "every_session",
        "daily": "daily",
        "once_per_day": "daily",
        "per_day": "daily",
        "once": "once",
        "one_time": "once",
        "just_once": "once",
    }
    return aliases.get(normalized_value, AI_NOTICE_DEFAULT_FREQUENCY)


def normalize_ai_notice_message(value):
    """Normalize administrator-entered AI notice text."""
    return (
        str(value or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()[:AI_NOTICE_MAX_MESSAGE_LENGTH]
    )


def compute_ai_notice_hash(message, frequency):
    """Compute the version hash used to invalidate stale dismissals."""
    payload = {
        "message": normalize_ai_notice_message(message),
        "frequency": normalize_ai_notice_frequency(frequency),
    }
    encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded_payload).hexdigest()


def get_ai_notice_config(settings):
    """Build normalized browser-safe AI notice configuration."""
    source_settings = settings or {}
    message = normalize_ai_notice_message(source_settings.get("ai_notice_message"))
    frequency = normalize_ai_notice_frequency(source_settings.get("ai_notice_frequency"))
    return {
        "enabled": bool(source_settings.get("enable_ai_notice", False) and message),
        "message": message,
        "frequency": frequency,
        "hash": compute_ai_notice_hash(message, frequency),
    }


def build_ai_notice_dismissal_record(value, dismissed_at=None):
    """Validate a requested dismissal and create a server-timestamped record."""
    if not isinstance(value, dict):
        raise ValueError("AI notice dismissal must be an object.")

    notice_hash = str(value.get("hash") or "").strip().lower()
    if not _AI_NOTICE_HASH_PATTERN.fullmatch(notice_hash):
        raise ValueError("AI notice dismissal hash is invalid.")

    frequency = normalize_ai_notice_frequency(value.get("frequency"))
    if frequency not in {"daily", "once"}:
        raise ValueError("AI notice dismissal frequency is invalid.")

    dismissed_at = dismissed_at or datetime.now(timezone.utc)
    return {
        "hash": notice_hash,
        "frequency": frequency,
        "dismissed_at": dismissed_at.isoformat(),
        "dismissed_date": dismissed_at.strftime("%Y-%m-%d"),
    }


def is_ai_notice_dismissed(ai_notice_config, user_settings, current_time=None):
    """Return whether the current persisted dismissal hides this notice."""
    if not ai_notice_config.get("enabled"):
        return True

    frequency = ai_notice_config.get("frequency")
    if frequency not in {"daily", "once"}:
        return False

    dismissal = (user_settings or {}).get(AI_NOTICE_USER_SETTINGS_KEY, {})
    if not isinstance(dismissal, dict):
        return False
    if dismissal.get("hash") != ai_notice_config.get("hash"):
        return False
    if dismissal.get("frequency") != frequency:
        return False
    if frequency == "once":
        return True

    current_time = current_time or datetime.now(timezone.utc)
    return dismissal.get("dismissed_date") == current_time.strftime("%Y-%m-%d")
