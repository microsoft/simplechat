# functions_ui_mode.py
"""Decide which browser interface a request is served.

SimpleChat ships two interfaces on one backend: the server-rendered classic
(legacy) interface and the React V2 (modern) interface under ``/v2``. This
module is the one seam the rest of the application asks "which one?".

Administrator policy takes precedence over an account preference and the default.
Storage imports are deferred until a request needs them: public/error rendering
and bootstrap-free callers must not initialize Azure clients at module load.
"""

from flask import g, has_request_context, session

UI_MODE_CLASSIC = "classic"
UI_MODE_MODERN = "modern"
UI_MODES = (UI_MODE_CLASSIC, UI_MODE_MODERN)
UI_POLICIES = ("both", *UI_MODES)


def validate_ui_setting(key, value):
    """Validate persisted enums without coercing booleans, collections or null."""
    allowed = UI_POLICIES if key == "ui_mode_policy" else UI_MODES
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("Choose a valid interface option.")
    return value


def get_ui_policy(settings=None, user_settings=None):
    """Return a browser-safe policy projection, resolving request inputs lazily."""
    if settings is None:
        settings = {}
        if has_request_context():
            from functions_settings import get_settings

            settings = get_settings()
    if (settings or {}).get("ui_mode_policy") in UI_MODES:
        user_settings = {}
    if user_settings is None:
        user_settings = {}
        if has_request_context() and session.get("user"):
            from functions_authentication import get_current_user_id
            from functions_settings import read_user_settings_snapshot

            user_id = get_current_user_id()
            if user_id:
                cached = getattr(g, "_ui_mode_preferences", None)
                if cached is None or cached[0] != user_id:
                    # A different worker's lightweight chrome cache can lag a saved switch.
                    cached = (user_id, read_user_settings_snapshot(user_id))
                    g._ui_mode_preferences = cached
                user_settings = cached[1]
    settings = settings or {}
    user_settings = user_settings or {}
    preferences = user_settings.get("settings", user_settings)
    policy = settings.get("ui_mode_policy", "both")
    default = settings.get("ui_default_mode", UI_MODE_MODERN)
    policy = policy if isinstance(policy, str) and policy in UI_POLICIES else "both"
    default = default if isinstance(default, str) and default in UI_MODES else UI_MODE_MODERN
    preferred = preferences.get("preferredUiMode") if isinstance(preferences, dict) else None
    preferred = preferred if isinstance(preferred, str) and preferred in UI_MODES else default
    return {
        "policy": policy,
        "default": default,
        "effective": preferred if policy == "both" else policy,
        "can_switch": policy == "both",
    }


def allows_classic_escape(settings=None):
    """A one-page legacy link cannot override a modern-only administrator policy."""
    return get_ui_policy(settings, {})["policy"] != UI_MODE_MODERN


def get_ui_mode(settings=None, user_settings=None):
    """Return the interface to serve: ``UI_MODE_CLASSIC`` or ``UI_MODE_MODERN``.

    Explicit inputs avoid request storage reads; omitted inputs use the signed-in account.
    """
    return get_ui_policy(settings, user_settings)["effective"]


def is_modern_ui(settings=None, user_settings=None):
    """Return True when the request should be served the modern (V2) interface."""
    return get_ui_mode(settings, user_settings) == UI_MODE_MODERN
