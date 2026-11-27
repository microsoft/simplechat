# chat_link_contract.py
"""Bootstrap-free constants and validation for workspace chat launch references."""

import re


CHAT_LINK_DEFAULT_LIFETIME_DAYS = 90
CHAT_LINK_LIFETIME_DAYS = (7, 30, 90, 365)
CHAT_LINK_PENDING_SESSION_KEY = "pending_chat_link_reference"
CHAT_LINK_PENDING_MAX_AGE_SECONDS = 30 * 60
CHAT_LINK_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22}$")
CHAT_LINK_PATH_PATTERN = re.compile(r"^/l/(?P<reference>[A-Za-z0-9_-]{22})$")


def normalize_chat_link_reference(value):
    """Return a canonical opaque reference, or None when the value is invalid."""
    if not isinstance(value, str):
        return None
    reference = value.strip()
    return reference if CHAT_LINK_REFERENCE_PATTERN.fullmatch(reference) else None


def chat_link_reference_from_path(path):
    """Return the only opaque reference accepted from a chat-link navigation path."""
    if not isinstance(path, str):
        return None
    match = CHAT_LINK_PATH_PATTERN.fullmatch(path)
    return match.group("reference") if match else None
