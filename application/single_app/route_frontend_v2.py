# route_frontend_v2.py

"""Serves the V2 React single-page application.

The V2 UI is a Vite build that lives in application/v2_ui and compiles into
application/single_app/static/v2. It is deliberately served from the same origin and the
same App Service as the Flask API so the existing Entra/MSAL session cookie, the
same-origin CSRF check and the ``default-src 'self'`` CSP all continue to apply without
any cross-origin configuration.

Hashed bundle assets are addressed at /static/v2/... and are handled by Flask's built-in
static route. This module only serves the SPA shell, which every /v2 path falls back to so
that client-side routing survives deep links and page refreshes.

The shell is not returned verbatim. Its ``<title>`` and favicon link are rewritten from
settings on the way out, because the compiled ``index.html`` is a build artefact and
cannot know an administrator's branding. The server-rendered interface does the same thing
in ``base.html``; without it a custom favicon never replaces the shipped one, since the
static file keeps a stable name and the browser keeps serving the copy it already cached.
"""

import html
import logging
import os
import re

from flask import Response, render_template_string

from functions_appinsights import log_event
from functions_authentication import login_required, user_required
from functions_branding_urls import FAVICON_STATIC_URL, build_favicon_url
from swagger_wrapper import get_auth_security, swagger_route

V2_BUILD_SUBDIR = os.path.join("static", "v2")

# Matches the shell's icon link and title regardless of attribute order, so a Vite
# upgrade that reformats index.html does not silently stop the rewrite.
ICON_LINK_PATTERN = re.compile(r"<link\b[^>]*\brel=(\"|')icon\1[^>]*>", re.IGNORECASE)
TITLE_PATTERN = re.compile(r"<title\b[^>]*>.*?</title>", re.IGNORECASE | re.DOTALL)
HEAD_CLOSE_PATTERN = re.compile(r"</head>", re.IGNORECASE)

# Matches the fallback in ``_build_branding`` so the tab title the shell paints is the
# same one the SPA sets once bootstrap resolves, rather than flickering between two
# spellings of the product name.
DEFAULT_APP_TITLE = "SimpleChat"

# Shown when Flask is running against a checkout where the SPA has not been compiled.
# The build output is gitignored, so this is the normal state of a fresh clone and needs
# to explain itself rather than returning a bare 404.
_MISSING_BUNDLE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SimpleChat V2 UI is not built</title>
</head>
<body style="font-family: system-ui, sans-serif; max-width: 42rem; margin: 4rem auto; padding: 0 1.5rem; line-height: 1.6;">
<h1>The V2 UI bundle has not been built</h1>
<p>
    The React V2 interface compiles into
    <code>application/single_app/static/v2</code>, which is not committed to the
    repository. Build it once and this page will be replaced by the application:
</p>
<pre style="background:#f3f4f6;padding:1rem;border-radius:.5rem;overflow:auto;"><code>cd application/v2_ui
npm install
npm run build</code></pre>
<p>
    Container images build this automatically, so this message only appears for local
    development checkouts.
</p>
<p><a href="/chats">Return to the current SimpleChat interface</a></p>
</body>
</html>
"""


def get_v2_build_root():
    """Return the absolute path of the compiled V2 bundle directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), V2_BUILD_SUBDIR)


def get_v2_index_path():
    """Return the absolute path of the compiled V2 SPA shell."""
    return os.path.join(get_v2_build_root(), "index.html")


def is_v2_bundle_available():
    """Return True when the compiled V2 SPA shell exists on disk."""
    return os.path.isfile(get_v2_index_path())


def _resolve_shell_branding():
    """Return ``(favicon_url, app_title)`` for the SPA shell.

    ``functions_settings`` is imported here rather than at module scope so that serving
    the shell never depends on the settings stack being importable. A failure here means
    a default icon and title on an otherwise working application, which is the right
    trade: the SPA replaces the title from bootstrap moments later anyway.
    """
    try:
        from functions_settings import get_settings

        settings = get_settings() or {}
        app_title = str(settings.get("app_title") or "").strip() or DEFAULT_APP_TITLE
        return build_favicon_url(settings), app_title
    except Exception as exc:
        log_event(
            f"[V2_UI] Could not resolve shell branding, serving defaults: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return FAVICON_STATIC_URL, DEFAULT_APP_TITLE


def _apply_shell_branding(shell_html):
    """Rewrite the compiled shell's favicon link and title from settings.

    Both values are escaped because ``app_title`` is administrator-supplied free text.
    The replacements are passed as callables so ``re.sub`` treats them literally; a title
    containing a backslash would otherwise be read as a group reference.
    """
    favicon_url, app_title = _resolve_shell_branding()

    icon_link = (
        f'<link rel="icon" href="{html.escape(favicon_url, quote=True)}" '
        'type="image/x-icon">'
    )
    shell_html, replaced = ICON_LINK_PATTERN.subn(lambda _match: icon_link, shell_html, count=1)
    if not replaced:
        # A shell without an icon link would fall back to /favicon.ico, which is the
        # shipped default rather than the administrator's.
        shell_html = HEAD_CLOSE_PATTERN.sub(
            lambda _match: f"{icon_link}</head>", shell_html, count=1
        )

    shell_html = TITLE_PATTERN.sub(
        lambda _match: f"<title>{html.escape(app_title)}</title>", shell_html, count=1
    )

    return shell_html


def _serve_v2_shell():
    """Return the SPA shell, or a build hint when the bundle is missing."""
    if not is_v2_bundle_available():
        log_event(
            "[V2_UI] Bundle requested but static/v2/index.html is missing",
            level=logging.WARNING,
        )
        return Response(
            render_template_string(_MISSING_BUNDLE_TEMPLATE),
            status=503,
            mimetype="text/html",
        )

    try:
        with open(get_v2_index_path(), "r", encoding="utf-8") as index_file:
            shell_html = index_file.read()
    except OSError as exc:
        log_event(
            f"[V2_UI] Failed to read the V2 SPA shell: {exc}",
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return Response("Failed to load the V2 interface", status=500)

    response = Response(_apply_shell_branding(shell_html), mimetype="text/html")
    # The shell references content-hashed assets, so it must never be cached itself or a
    # deploy would keep serving the previous bundle's asset URLs. The branding rewrite
    # above relies on the same header: it is per-request, and a cached copy would pin one
    # administrator's icon and title for everybody.
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def register_route_frontend_v2(bp):
    @bp.route("/v2", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def v2_app_root():
        """Serve the V2 single-page application shell."""
        return _serve_v2_shell()

    @bp.route("/v2/<path:subpath>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def v2_app_deep_link(subpath):
        """Serve the SPA shell for any client-side route beneath /v2.

        The compiled assets live under /static/v2, so nothing that reaches this handler is
        a real file; every path is a client-side route and gets the shell.
        """
        del subpath
        return _serve_v2_shell()
