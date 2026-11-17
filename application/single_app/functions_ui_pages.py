# functions_ui_pages.py
"""Serve a server-rendered page in the interface a request is meant to see.

Most SimpleChat pages have a React (V2) counterpart under ``/v2``, but a few must stay
server-rendered because the people who see them cannot use V2: visitors who are not signed
in, users who are signed in without an application role, the rate-limit page and the
Microsoft 365 sign-in result. Each of those has a classic template that extends
``base.html`` and a modern one under ``templates/modern`` that carries the V2 look without
the classic navigation.

``render_page`` is the one place that picks between them, by asking
``functions_ui_mode.get_ui_mode``. A call site names both templates and never decides for
itself. Until the interface selector exists ``get_ui_mode`` answers classic for everyone, so
the modern templates are inactive and every page renders exactly as it did before.

``is_modern_ui_available`` is the one test for "send this request to V2": the modern interface
is selected *and* the compiled V2 bundle exists. ``/v2`` answers 503 without the bundle, so a
deployment that selected the modern interface but shipped no bundle must keep serving the
classic pages rather than send every visitor into an error. The landing page and the classic to
V2 redirect (``functions_ui_redirect``) both ask it, so they can never disagree. It writes one
throttled ``[UI_MODE]`` warning per process when the bundle is the reason a request stays classic.

This module deliberately imports only Flask and ``functions_ui_mode`` at load time. The pages
that use it are public or error pages, and the rate-limit page in particular has to render
while the rest of the application is struggling, so it must not pull in the settings or Cosmos
stack. The V2 route module and the logger are imported when they are needed.
"""

import logging
import threading
import time

from flask import render_template

import functions_ui_mode

# V2 answers at /v2 and /v2/<path>; /v2/ is not a registered route and returns 404.
V2_HOME_PATH = "/v2"

# A process that keeps serving classic because the bundle is missing says so once, then again
# after this long, so the cause survives log rotation without a line per request.
BUNDLE_WARNING_INTERVAL_SECONDS = 3600

_APPLICATION_ROLES = ("User", "Admin")

_bundle_warning_lock = threading.Lock()
_bundle_warning_logged_at = None


def choose_page_template(classic_template, modern_template, settings=None, user_settings=None):
    """Return the template name for the interface this request is served."""
    mode = functions_ui_mode.get_ui_mode(settings, user_settings)
    if mode == functions_ui_mode.UI_MODE_MODERN:
        return modern_template
    return classic_template


def render_page(classic_template, modern_template, *, settings=None, user_settings=None, **context):
    """Render the classic or the modern template with the same template context.

    ``settings`` and ``user_settings`` are handed to ``get_ui_mode`` only, so a caller that
    already holds them spares the selector a lookup. They are never passed to the template,
    which keeps raw settings away from the browser.
    """
    template = choose_page_template(classic_template, modern_template, settings, user_settings)
    return render_template(template, **context)


def has_app_user_role(user):
    """Return True when the signed-in user holds the User or Admin application role.

    This is the test ``user_required`` applies and the classic landing page uses to tell a
    user who can enter the application from one who is signed in without a role.
    """
    roles = user.get("roles") if isinstance(user, dict) else None
    if not isinstance(roles, (list, tuple, set, frozenset)):
        return False
    return any(role in roles for role in _APPLICATION_ROLES)


def _probe_v2_bundle():
    """Return True when the compiled V2 shell exists on disk.

    ``route_frontend_v2`` is imported here, not at load time: it pulls in authentication and
    settings, which this module must be importable without.
    """
    from route_frontend_v2 import is_v2_bundle_available

    return bool(is_v2_bundle_available())


def _log_bundle_missing():
    """Write the ``[UI_MODE]`` warning. Kept apart so a test can observe it without the logger."""
    from functions_appinsights import log_event

    log_event(
        "[UI_MODE] The modern interface is selected but the V2 bundle (static/v2/index.html) "
        "is not built, so classic pages are being served instead. Build it with "
        "'npm install' and 'npm run build' in application/v2_ui; container images do this "
        "automatically.",
        level=logging.WARNING,
    )


def _warn_bundle_missing_once(now=None):
    """Log the missing bundle at most once per interval for this process.

    Returns True when it logged. A failure to log never reaches the caller: the warning is a
    diagnostic, and it must not turn a classic page that would have rendered into an error.
    """
    global _bundle_warning_logged_at
    moment = time.monotonic() if now is None else now
    with _bundle_warning_lock:
        last = _bundle_warning_logged_at
        if last is not None and 0 <= moment - last < BUNDLE_WARNING_INTERVAL_SECONDS:
            return False
        _bundle_warning_logged_at = moment
    try:
        _log_bundle_missing()
    except Exception:
        return False
    return True


def reset_bundle_warning_throttle():
    """Forget when the missing-bundle warning was last written, for tests."""
    global _bundle_warning_logged_at
    with _bundle_warning_lock:
        _bundle_warning_logged_at = None


def is_v2_bundle_ready(bundle_available=None):
    """Return True when the V2 bundle can answer ``/v2``; warn (throttled) when it cannot.

    ``bundle_available`` replaces the probe: a boolean or a function returning one. Ask this
    only for a request the modern interface would otherwise take, so the warning is written
    when the missing bundle is why a request stays classic and not for requests that were
    classic anyway.
    """
    probe = _probe_v2_bundle if bundle_available is None else bundle_available
    ready = bool(probe() if callable(probe) else probe)
    if not ready:
        _warn_bundle_missing_once()
    return ready


def is_modern_ui_available(settings=None, user_settings=None, *, bundle_available=None):
    """Return True when this request should be sent to V2 and V2 can answer it.

    The modern interface is selected (``functions_ui_mode.get_ui_mode``) and the compiled
    bundle exists. A missing bundle means classic, never a 503 loop: see ``is_v2_bundle_ready``.
    """
    mode = functions_ui_mode.get_ui_mode(settings, user_settings)
    if mode != functions_ui_mode.UI_MODE_MODERN:
        return False
    return is_v2_bundle_ready(bundle_available)
