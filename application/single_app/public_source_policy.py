# public_source_policy.py
"""UI-specific public discovery, independent of source selection and authorization."""

from contextlib import contextmanager
from contextvars import ContextVar

from flask import has_request_context, request


LEGACY_VISIBLE = "legacy_visible"
ALL_AVAILABLE = "all_available"
_POLICY = ContextVar("public_source_policy", default=None)


def normalize_public_source_policy(value):
    if value not in (LEGACY_VISIBLE, ALL_AVAILABLE):
        raise ValueError("Invalid public source policy.")
    return value


def current_public_source_policy(user_id=None):
    """A worker binding wins over HTTP state; an unmarked request remains classic."""
    bound = _POLICY.get()
    if bound is not None:
        return bound[1] if user_id is None or bound[0] == user_id else LEGACY_VISIBLE
    if has_request_context():
        if (
            request.path.startswith("/api/v2/")
            or request.headers.get("X-SimpleChat-UI") == "v2"
            or request.args.get("ui_version") == "v2"
        ):
            return ALL_AVAILABLE
    return LEGACY_VISIBLE


def uses_all_public_sources(user_id=None):
    return current_public_source_policy(user_id) == ALL_AVAILABLE


@contextmanager
def public_source_policy_context(user_id, policy):
    token = _POLICY.set((user_id, normalize_public_source_policy(policy)))
    try:
        yield
    finally:
        _POLICY.reset(token)
