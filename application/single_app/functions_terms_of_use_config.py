# functions_terms_of_use_config.py
"""Pure Terms configuration and revision helpers shared by settings and acceptance."""

import hashlib
import json
from urllib.parse import urlparse


TERMS_OF_USE_FREQUENCIES = ("every_session", "daily", "once")
TERMS_OF_USE_DEFAULT_FREQUENCY = "once"
TERMS_OF_USE_DEFAULT_REDIRECT = "/"
TERMS_OF_USE_MAX_TITLE_LENGTH = 160
TERMS_OF_USE_MAX_MESSAGE_LENGTH = 10000
TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH = 80
TERMS_OF_USE_REVISION_KEY = "terms_of_use_revision"
TERMS_OF_USE_MAX_VERSION = 9007199254740991


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


def _get_terms_of_use_revision(settings):
    revision = settings.get(TERMS_OF_USE_REVISION_KEY)
    if revision is None:
        return None
    if (
        not isinstance(revision, dict)
        or type(revision.get("version")) is not int
        or not 1 <= revision["version"] <= TERMS_OF_USE_MAX_VERSION
        or not isinstance(revision.get("hash"), str)
        or len(revision["hash"]) != 64
        or any(char not in "0123456789abcdef" for char in revision["hash"])
    ):
        raise ValueError("Invalid persisted Terms of Use revision metadata.")
    return revision


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
    terms_hash = compute_terms_of_use_hash(title, message, frequency)
    revision = _get_terms_of_use_revision(source_settings)

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
        "hash": terms_hash,
        "version": revision["version"] if revision and revision["hash"] == terms_hash else None,
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


def normalize_terms_of_use_revision(settings):
    """Assign a baseline or advance the revision inside the settings write transaction."""
    config = get_terms_of_use_config(settings)
    revision = _get_terms_of_use_revision(settings)
    if revision and revision["hash"] == config["hash"]:
        return False
    if revision is None and not config["message"]:
        return False
    version = revision["version"] + 1 if revision else 1
    if version > TERMS_OF_USE_MAX_VERSION:
        raise ValueError("Terms of Use revision limit reached.")
    settings[TERMS_OF_USE_REVISION_KEY] = {"version": version, "hash": config["hash"]}
    return True


def format_terms_of_use_version(version):
    """Format recorded numbers without inventing revisions for legacy audit events."""
    if type(version) is int and 1 <= version <= TERMS_OF_USE_MAX_VERSION:
        return f"v{version}"
    return "Legacy"
