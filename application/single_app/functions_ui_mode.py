# functions_ui_mode.py
"""Decide which browser interface a request is served.

SimpleChat ships two interfaces on one backend: the server-rendered classic
(legacy) interface and the React V2 (modern) interface under ``/v2``. This
module is the one seam the rest of the application asks "which one?".

Today the answer is always classic, so nothing changes for anyone. The
interface selector (an administrator default plus an optional per-user choice)
replaces the body of ``get_ui_mode`` without touching its callers, which is why
code that builds links, redirects or chooses between a classic and a modern
template asks here instead of deciding for itself.
"""

UI_MODE_CLASSIC = "classic"
UI_MODE_MODERN = "modern"
UI_MODES = (UI_MODE_CLASSIC, UI_MODE_MODERN)


def get_ui_mode(settings=None, user_settings=None):
    """Return the interface to serve: ``UI_MODE_CLASSIC`` or ``UI_MODE_MODERN``.

    ``settings`` and ``user_settings`` are accepted now so callers can pass what
    they already hold and need no change when the selector starts reading them.
    """
    return UI_MODE_CLASSIC


def is_modern_ui(settings=None, user_settings=None):
    """Return True when the request should be served the modern (V2) interface."""
    return get_ui_mode(settings, user_settings) == UI_MODE_MODERN
