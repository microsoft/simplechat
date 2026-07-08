# functions_terms_of_use.py
"""Helpers for the terms of use acceptance flow."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import has_request_context, session

from functions_activity_logging import (
    log_terms_of_use_accepted,
    log_terms_of_use_declined,
)
from functions_appinsights import log_event
from functions_settings import get_user_settings, update_user_settings


TERMS_OF_USE_FREQUENCIES = ("every_session", "daily", "once")
TERMS_OF_USE_DEFAULT_FREQUENCY = "once"
TERMS_OF_USE_SESSION_KEY = "terms_of_use_acceptance"
TERMS_OF_USE_PRE_AUTH_SESSION_KEY = "terms_of_use_pre_auth_acceptance"
TERMS_OF_USE_RETURN_PATH_SESSION_KEY = "terms_of_use_return_path"
TERMS_OF_USE_USER_SETTINGS_KEY = "termsOfUse"
TERMS_OF_USE_DEFAULT_REDIRECT = "/"
TERMS_OF_USE_MAX_TITLE_LENGTH = 160
TERMS_OF_USE_MAX_MESSAGE_LENGTH = 10000
TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH = 80


def normalize_terms_of_use_frequency(value):
    """Normalize the configured Terms of Use frequency."""
    normalized_value = str(value or "").strip().lower().replace("-", "_")
    if normalized_value in {"session", "every_session", "per_session"}:
        return "every_session"
    if normalized_value in {"daily", "once_per_day", "per_day"}:
        return "daily"
    if normalized_value in {"once", "one_time", "just_once"}:
        return "once"
    return TERMS_OF_USE_DEFAULT_FREQUENCY


def normalize_terms_of_use_text(value, fallback="", max_length=TERMS_OF_USE_MAX_MESSAGE_LENGTH):
    """Normalize administrator-entered Terms of Use text."""
    normalized_value = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized_value:
        normalized_value = fallback
    return normalized_value[:max_length]


def normalize_terms_of_use_redirect_url(value):
    """Return a safe local or admin-configured HTTP(S) redirect target."""
    candidate = str(value or "").strip()
    if not candidate:
        return TERMS_OF_USE_DEFAULT_REDIRECT
    if "\\" in candidate:
        return TERMS_OF_USE_DEFAULT_REDIRECT
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate

    parsed = urlparse(candidate)
    if (
        parsed.scheme == "https"
        and parsed.netloc
        and not parsed.username
        and not parsed.password
    ):
        return candidate
    return TERMS_OF_USE_DEFAULT_REDIRECT


def normalize_terms_of_use_return_path(value, fallback="/"):
    """Normalize a return target so user-controlled redirects stay local."""
    candidate = str(value or "").strip()
    if not candidate:
        return fallback
    if "\\" in candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return fallback
    return candidate


def get_terms_of_use_config(settings):
    """Build the normalized terms of use config from app settings."""
    source_settings = settings or {}
    title = normalize_terms_of_use_text(
        source_settings.get("terms_of_use_title"),
        fallback="Terms of Use",
        max_length=TERMS_OF_USE_MAX_TITLE_LENGTH,
    )
    message = normalize_terms_of_use_text(
        source_settings.get("terms_of_use_message"),
        max_length=TERMS_OF_USE_MAX_MESSAGE_LENGTH,
    )
    frequency = normalize_terms_of_use_frequency(
        source_settings.get("terms_of_use_frequency")
    )
    accept_button_text = normalize_terms_of_use_text(
        source_settings.get("terms_of_use_accept_button_text"),
        fallback="Accept and continue",
        max_length=TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH,
    )
    decline_button_text = normalize_terms_of_use_text(
        source_settings.get("terms_of_use_decline_button_text"),
        fallback="Cancel",
        max_length=TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH,
    )
    enabled = bool(source_settings.get("enable_terms_of_use", False) and message)

    return {
        "enabled": enabled,
        "title": title,
        "message": message,
        "frequency": frequency,
        "decline_redirect_url": normalize_terms_of_use_redirect_url(
            source_settings.get("terms_of_use_decline_redirect_url")
        ),
        "accept_button_text": accept_button_text,
        "decline_button_text": decline_button_text,
        "hash": compute_terms_of_use_hash(title, message, frequency),
    }


def compute_terms_of_use_hash(title, message, frequency):
    """Compute the hash used to invalidate old acceptances when terms change."""
    payload = {
        "title": str(title or "").strip(),
        "message": str(message or "").replace("\r\n", "\n").replace("\r", "\n").strip(),
        "frequency": normalize_terms_of_use_frequency(frequency),
    }
    encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded_payload).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc)


def _build_acceptance_record(terms_config, accepted_at=None):
    accepted_at = accepted_at or _utc_now()
    return {
        "hash": terms_config["hash"],
        "frequency": terms_config["frequency"],
        "accepted_at": accepted_at.isoformat(),
        "accepted_date": accepted_at.strftime("%Y-%m-%d"),
    }


def _session_acceptance_matches(terms_config):
    if not has_request_context():
        return False
    acceptance_record = session.get(TERMS_OF_USE_SESSION_KEY)
    if not isinstance(acceptance_record, dict):
        return False
    return (
        acceptance_record.get("hash") == terms_config["hash"]
        and acceptance_record.get("frequency") == terms_config["frequency"]
    )


def _user_acceptance_matches(terms_config, user_id):
    if not user_id:
        return False

    user_settings = get_user_settings(user_id)
    terms_settings = (user_settings or {}).get("settings", {}).get(TERMS_OF_USE_USER_SETTINGS_KEY, {})
    if not isinstance(terms_settings, dict):
        return False
    if terms_settings.get("hash") != terms_config["hash"]:
        return False
    if terms_settings.get("frequency") != terms_config["frequency"]:
        return False

    if terms_config["frequency"] == "once":
        return True
    if terms_config["frequency"] == "daily":
        return terms_settings.get("accepted_date") == _utc_now().strftime("%Y-%m-%d")
    return False


def has_terms_of_use_acceptance(settings, user_id=None):
    """Return True when the user/session has satisfied the current Terms of Use."""
    terms_config = get_terms_of_use_config(settings)
    if not terms_config["enabled"]:
        return True
    if not user_id and _session_acceptance_matches(terms_config):
        return True
    if terms_config["frequency"] == "every_session":
        return _session_acceptance_matches(terms_config)
    return _user_acceptance_matches(terms_config, user_id)


def mark_pre_auth_terms_of_use_acceptance(settings):
    """Record anonymous pre-auth acceptance in the current Flask session."""
    terms_config = get_terms_of_use_config(settings)
    if not terms_config["enabled"]:
        return None

    acceptance_record = _build_acceptance_record(terms_config)
    session[TERMS_OF_USE_PRE_AUTH_SESSION_KEY] = acceptance_record
    session[TERMS_OF_USE_SESSION_KEY] = acceptance_record
    session.modified = True
    return acceptance_record


def record_terms_of_use_acceptance(user_id, settings, source="post_auth"):
    """Persist and audit acceptance for an authenticated user."""
    terms_config = get_terms_of_use_config(settings)
    if not terms_config["enabled"]:
        return None

    if terms_config["frequency"] != "every_session" and _user_acceptance_matches(terms_config, user_id):
        return None

    acceptance_record = _build_acceptance_record(terms_config)
    if has_request_context():
        session[TERMS_OF_USE_SESSION_KEY] = acceptance_record
        session.pop(TERMS_OF_USE_PRE_AUTH_SESSION_KEY, None)
        session.modified = True

    if terms_config["frequency"] in {"daily", "once"}:
        if not update_user_settings(
            user_id,
            {TERMS_OF_USE_USER_SETTINGS_KEY: acceptance_record},
        ):
            raise RuntimeError("Terms of Use acceptance could not be saved.")

    log_terms_of_use_accepted(
        user_id=user_id,
        terms_hash=acceptance_record["hash"],
        frequency=acceptance_record["frequency"],
        source=source,
        accepted_date=acceptance_record["accepted_date"],
        auth_state="authenticated",
    )
    return acceptance_record


def apply_pending_pre_auth_terms_of_use(user_id, settings, source="pre_auth"):
    """Persist a matching pre-auth acceptance after authentication succeeds."""
    if not has_request_context():
        return None

    terms_config = get_terms_of_use_config(settings)
    pending_acceptance = session.get(TERMS_OF_USE_PRE_AUTH_SESSION_KEY)
    if not terms_config["enabled"] or not isinstance(pending_acceptance, dict):
        return None

    if (
        pending_acceptance.get("hash") != terms_config["hash"]
        or pending_acceptance.get("frequency") != terms_config["frequency"]
    ):
        session.pop(TERMS_OF_USE_PRE_AUTH_SESSION_KEY, None)
        session.pop(TERMS_OF_USE_SESSION_KEY, None)
        session.modified = True
        return None

    if terms_config["frequency"] != "every_session" and _user_acceptance_matches(terms_config, user_id):
        session.pop(TERMS_OF_USE_PRE_AUTH_SESSION_KEY, None)
        session[TERMS_OF_USE_SESSION_KEY] = pending_acceptance
        session.modified = True
        return None

    if terms_config["frequency"] in {"daily", "once"}:
        if not update_user_settings(
            user_id,
            {TERMS_OF_USE_USER_SETTINGS_KEY: pending_acceptance},
        ):
            raise RuntimeError("Pre-auth terms of use acceptance could not be saved.")

    session[TERMS_OF_USE_SESSION_KEY] = pending_acceptance
    session.pop(TERMS_OF_USE_PRE_AUTH_SESSION_KEY, None)
    session.modified = True
    log_terms_of_use_accepted(
        user_id=user_id,
        terms_hash=pending_acceptance["hash"],
        frequency=pending_acceptance["frequency"],
        source=source,
        accepted_date=pending_acceptance["accepted_date"],
        auth_state="authenticated",
    )
    return pending_acceptance


def record_terms_of_use_decline(user_id, settings, source="post_auth"):
    """Audit an authenticated decline of the current Terms of Use."""
    terms_config = get_terms_of_use_config(settings)
    if not terms_config["enabled"] or not user_id:
        return None
    log_terms_of_use_declined(
        user_id=user_id,
        terms_hash=terms_config["hash"],
        frequency=terms_config["frequency"],
        source=source,
        redirect_url=terms_config["decline_redirect_url"],
        auth_state="authenticated",
    )
    return terms_config


def log_pre_auth_terms_of_use_issue(message, extra=None):
    """Log non-fatal pre-auth Terms of Use issues without exposing terms content."""
    log_event(
        f"[TermsOfUse] {message}",
        extra=extra or {},
        level=logging.WARNING,
    )
