# route_access_restriction.py
"""The Access restricted screen, in both interfaces, and the call behind the V2 page.

A user whose access an administrator suspended or blocked can still sign in, but
``functions_authentication.user_required`` refuses every app surface and sends them here.
These routes are therefore login-only on purpose: they must stay reachable by exactly the
users ``user_required`` refuses. They only ever describe the signed-in user's own
restriction, read from their own settings, and never accept a user id from the request.

The Admin role is not subject to access restrictions, so an Admin is always told they are
not restricted, matching what ``user_required`` enforces.
"""

from flask import jsonify, make_response, render_template, session

from functions_access_restriction import (
    ACCESS_RESTRICTION_KIND_SUSPENDED,
    parse_access_restore_time,
    public_access_restriction,
)
from functions_authentication import get_user_access_restriction, login_required
from functions_branding_urls import build_custom_logo_urls
from functions_settings import get_settings, sanitize_settings_for_user
from route_frontend_v2 import _serve_v2_shell
from swagger_wrapper import get_auth_security, swagger_route


NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def _session_user():
    user = session.get("user")
    return user if isinstance(user, dict) else {}


def _current_restriction():
    """Return the signed-in user's own restriction, as ``user_required`` would enforce it."""
    user = _session_user()
    if "Admin" in (user.get("roles") or []):
        return None
    user_id = user.get("oid") or user.get("sub")
    if not user_id:
        return None
    return get_user_access_restriction(user_id)


def _restore_display(restriction):
    """Return a UTC rendering of a suspension's restore time for the server-rendered page."""
    if not restriction or restriction.get("kind") != ACCESS_RESTRICTION_KIND_SUSPENDED:
        return ""
    restore_at = parse_access_restore_time(restriction.get("until"))
    return restore_at.strftime("%Y-%m-%d %H:%M UTC") if restore_at else ""


def _restricted_page_branding(raw_settings, public_settings):
    """Return the branding the V2 page draws: the fields the V2 Terms of Use page receives.

    Read from the same settings as ``route_backend_v2._build_branding``. Only the logo URLs
    are returned, never the stored image data.
    """
    show_logo = bool(raw_settings.get("show_logo", False))
    logo_url, logo_dark_url = build_custom_logo_urls(raw_settings)
    classification_banner = None
    if raw_settings.get("classification_banner_enabled") and raw_settings.get("classification_banner_text"):
        classification_banner = {
            "enabled": True,
            "text": raw_settings.get("classification_banner_text"),
            "color": raw_settings.get("classification_banner_color") or "#ffc107",
            "text_color": raw_settings.get("classification_banner_text_color") or "#ffffff",
        }
    return {
        "app_title": public_settings.get("app_title") or "SimpleChat",
        "hide_app_title": bool(raw_settings.get("hide_app_title", False)),
        "show_logo": show_logo,
        "logo_url": logo_url if show_logo else None,
        "logo_dark_url": logo_dark_url if show_logo else None,
        "classification_banner": classification_banner,
    }


def register_route_access_restriction(bp):
    @bp.route("/v2/access-restricted", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    def v2_access_restricted():
        """Serve the V2 SPA shell for the Access restricted page.

        This static rule is matched ahead of the ``/v2/<path:subpath>`` catch-all, which
        requires the User role and an unrestricted account. The page itself loads nothing
        but ``/api/v2/access-restriction``.
        """
        return _serve_v2_shell()

    @bp.route("/api/v2/access-restriction", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    def v2_access_restriction():
        """Return the signed-in user's own access restriction for the V2 page.

        ``restricted`` is False once a suspension has ended -- the read restores it -- or
        an administrator has restored access, and the page then offers to continue.
        """
        restriction = _current_restriction()
        settings = get_settings() or {}
        payload = {
            "restricted": restriction is not None,
            "branding": _restricted_page_branding(settings, sanitize_settings_for_user(settings)),
        }
        if restriction is not None:
            payload["restriction"] = public_access_restriction(restriction)
        return jsonify(payload), 200, NO_STORE_HEADERS

    @bp.route("/access-restricted", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    def access_restricted():
        """Render the classic Access restricted page for the signed-in user."""
        restriction = _current_restriction()
        public_settings = sanitize_settings_for_user(get_settings() or {})
        response = make_response(render_template(
            "access_restricted.html",
            app_settings=public_settings,
            restriction=public_access_restriction(restriction) if restriction else None,
            restore_display=_restore_display(restriction),
        ))
        response.headers["Cache-Control"] = "no-store"
        return response
