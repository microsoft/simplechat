# functions_ui_redirect.py
"""Send classic page URLs to their V2 counterparts when the modern interface is selected.

SimpleChat writes classic URLs everywhere: notifications, approvals, emails, bookmarks, the
Microsoft 365 sign-in returns, the post-sign-in landing page. When the modern interface is
selected those links must still arrive, in V2, so one edge redirect translates them instead of
about sixty call sites being rewritten. The translation itself is data: ``ui_route_map.json``
says which V2 route replaces each classic page and how its query string crosses over, and
``ui_routing.resolve_v2_target`` applies it.

Nothing here changes what anyone sees today. ``functions_ui_mode.get_ui_mode`` answers classic
for everyone until the interface selector exists, and every rule below starts from the modern
interface being selected.

``decide_ui_redirect`` is the decision and is pure: it takes what the request and the session
say and answers with a same-site ``Location`` or ``None``. ``redirect_classic_page_to_modern_ui``
is the thin Flask wiring that gathers those inputs for the ``before_request`` hook in ``app.py``.

A request is redirected only when all of these hold:

* it is a GET or HEAD of a page. Other methods are form posts and API calls; ``/api/*``,
  ``/static/*``, ``/v2*``, ``/external/*``, ``/custom/assets/*`` and ``/.well-known/*`` are
  never classic pages; a request the browser marks as a fetch, a prefetch or a frame (``Sec-Fetch-Dest``
  other than ``document``), an ``XMLHttpRequest`` or one that does not accept HTML is not a person
  opening a page. A frame is left alone so a classic page linked from inside a V2 custom page frame
  never loads V2 inside V2;
* the query does not carry ``ui=classic``, the escape hatch the V2 "Back to classic UI" link uses;
* the modern interface is selected and the V2 bundle exists. Without the bundle ``/v2`` answers 503,
  so the request stays classic (``functions_ui_pages.is_v2_bundle_ready`` writes one throttled
  ``[UI_MODE]`` warning);
* the visitor is signed in with an application role. ``/v2`` answers 403 without the role, and the
  registry's ``home`` and ``terms-of-use`` rows are partial because their signed-out and pre-sign-in
  states stay classic;
* the registry has a V2 page for the URL (``native``, ``alias`` or ``partial``). Sign-in, sign-out,
  OAuth callbacks, form handlers, developer tools and anything unknown stay where they are;
* for a custom page, V2 can host it: it is in the user's navigation, embeddable, not asking for its
  own tab, and not open to any signed-in user (those stay classic because ``/v2`` needs the role).

The answer is always a path under ``/v2`` built from registry data and validated segments, never
anything the caller supplied, so it cannot be an open redirect, and it can never be redirected again
because the first thing the decision skips is ``/v2``.

The hook runs ahead of the Terms of Use and idle-timeout hooks on purpose; see ``app.py``.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl

from flask import redirect, request, session

import functions_ui_mode
import functions_ui_pages
import ui_routing


# "Open this page in classic" in V2 appends this to the classic URL. It is harmless when the modern
# interface is not selected, because nothing reads it then. Who may use it is a decision for the
# interface selector plan (docs/explanation/features/V2_INTERFACE_SELECTION_PREREQUISITES.md).
ESCAPE_QUERY_KEY = "ui"
ESCAPE_QUERY_VALUE = "classic"

# A 302, not a 301 or 308: the answer depends on the visitor's interface, which can change, so no
# client or cache may remember it.
REDIRECT_STATUS_CODE = 302

# Namespaces that hold no classic page. The registry already refuses most of them; skipping them
# first keeps the hot paths (API calls, static files) free of any further work.
NEVER_REDIRECT_PREFIXES = ("/api/", "/external/", "/static/", "/custom/assets/", "/.well-known/")

# The registry rows for /custom/<slug> and /custom/<slug>.html.
CUSTOM_PAGE_KEYS = frozenset({"custom-page", "custom-page-html"})

# Sec-Fetch-Dest values of a navigation that is not a person opening a page in the window.
FRAMED_DESTINATIONS = frozenset({"iframe", "frame", "embed", "object"})

REASON_REDIRECT = "redirect"
REASON_METHOD = "method"
REASON_NOT_A_PAGE_PATH = "not_a_page_path"
REASON_FRAMED = "framed"
REASON_NOT_A_NAVIGATION = "not_a_navigation"
REASON_XHR = "xhr"
REASON_NOT_HTML = "not_html"
REASON_ESCAPE_HATCH = "escape_hatch"
REASON_NO_V2_PAGE = "no_v2_page"
REASON_CLASSIC_MODE = "classic_mode"
REASON_SIGNED_OUT = "signed_out"
REASON_NO_APP_ROLE = "no_app_role"
REASON_BUNDLE_MISSING = "bundle_missing"
REASON_CUSTOM_PAGE = "custom_page_stays_classic"
REASON_UNSAFE_LOCATION = "unsafe_location"

_MAX_ACCEPT_LENGTH = 1024


@dataclass(frozen=True)
class UiRedirectDecision:
    """The answer for one request: where to send it (or None) and why."""

    location: Optional[str]
    reason: str
    key: Optional[str] = None


def _skip(reason, key=None):
    return UiRedirectDecision(location=None, reason=reason, key=key)


def _resolve(value):
    """A state input is a value, or a function that returns it and is only called when needed."""
    return value() if callable(value) else value


def _is_v2_path(path):
    base = ui_routing.V2_BASE_PATH
    return path == base or path.startswith(base + "/")


def _accepts(accept, media_type):
    """Whether an ``Accept`` header allows ``media_type``, the way Flask's ``accept_mimetypes`` does.

    A missing or empty header allows everything, and ``*/*`` and ``type/*`` count, so a browser's
    ``text/html,...,*/*;q=0.8`` and a bare ``curl`` both read as willing to take a page.
    """
    text = str(accept or "")[:_MAX_ACCEPT_LENGTH].strip()
    if not text:
        return True
    top_level = media_type.partition("/")[0]
    for part in text.split(","):
        pieces = [piece.strip() for piece in part.split(";")]
        wanted = pieces[0].lower()
        if not wanted:
            continue
        quality = 1.0
        for parameter in pieces[1:]:
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0 and wanted in ("*/*", media_type, f"{top_level}/*"):
            return True
    return False


def _accepts_html(accept):
    return _accepts(accept, "text/html") or _accepts(accept, "application/xhtml+xml")


def has_classic_escape(query_string):
    """Whether the query's first ``ui`` value is ``classic``: the visitor asked for the classic page.

    "Open this page in classic" in V2 appends ``ui=classic``. Every place that sends a classic URL to V2
    (this module's hook and the landing page) honours it, so the choice made in V2 is not undone.
    """
    if isinstance(query_string, (bytes, bytearray)):
        query_string = bytes(query_string).decode("utf-8", "replace")
    if not isinstance(query_string, str) or not query_string:
        return False
    text = query_string[1:] if query_string.startswith("?") else query_string
    if len(text) > ui_routing.MAX_QUERY_LENGTH:
        return False
    try:
        pairs = parse_qsl(
            text, keep_blank_values=True, max_num_fields=ui_routing.MAX_QUERY_FIELDS, errors="replace",
        )
    except ValueError:
        return False
    for key, value in pairs:
        if key == ESCAPE_QUERY_KEY:
            return value.strip().lower() == ESCAPE_QUERY_VALUE
    return False


def _is_safe_location(location):
    """The last check before a Location is sent: a path under /v2, one leading slash, nothing odd."""
    base = ui_routing.V2_BASE_PATH
    return (
        isinstance(location, str)
        and (location == base or location.startswith((base + "/", base + "?")))
        and "//" not in location.partition("?")[0]
        and "\\" not in location
        and " " not in location
        and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in location)
    )


def evaluate_ui_redirect(
    *,
    method,
    path,
    query_string="",
    accept="",
    xhr=False,
    fetch_dest=None,
    fetch_mode=None,
    signed_in,
    has_app_role,
    ui_mode,
    bundle_available,
    custom_page_embeddable=None,
    route_map=None,
):
    """Decide whether a request is redirected to V2 and say why.

    ``signed_in``, ``has_app_role``, ``ui_mode`` and ``bundle_available`` are each a value or a
    function returning one. A function is called only after the cheaper rules have not already
    skipped the request, so the hook costs an API call or a static file nothing, and settings are
    read only for a request that could be redirected. ``custom_page_embeddable`` is a function
    from a custom page slug to whether V2 can host that page for this visitor; without it a custom
    page is never redirected.

    ``fetch_dest`` and ``fetch_mode`` are the ``Sec-Fetch-Dest`` and ``Sec-Fetch-Mode`` headers.
    A client that sends neither (curl, an older browser) is treated as opening a page.
    """
    if not isinstance(method, str) or method.upper() not in ("GET", "HEAD"):
        return _skip(REASON_METHOD)
    if not isinstance(path, str) or _is_v2_path(path) or path.startswith(NEVER_REDIRECT_PREFIXES):
        return _skip(REASON_NOT_A_PAGE_PATH)

    destination = str(fetch_dest or "").strip().lower()
    if destination in FRAMED_DESTINATIONS:
        return _skip(REASON_FRAMED)
    if destination not in ("", "document") or str(fetch_mode or "").strip().lower() not in ("", "navigate"):
        return _skip(REASON_NOT_A_NAVIGATION)
    if xhr:
        return _skip(REASON_XHR)
    if not _accepts_html(accept):
        return _skip(REASON_NOT_HTML)
    if has_classic_escape(query_string):
        return _skip(REASON_ESCAPE_HATCH)

    target = ui_routing.resolve_v2_target(path, query_string, method=method, route_map=route_map)
    if target is None:
        return _skip(REASON_NO_V2_PAGE)
    key = target["key"]

    if _resolve(ui_mode) != functions_ui_mode.UI_MODE_MODERN:
        return _skip(REASON_CLASSIC_MODE, key)
    if not _resolve(signed_in):
        return _skip(REASON_SIGNED_OUT, key)
    if not _resolve(has_app_role):
        return _skip(REASON_NO_APP_ROLE, key)
    if not _resolve(bundle_available):
        return _skip(REASON_BUNDLE_MISSING, key)

    if key in CUSTOM_PAGE_KEYS:
        slug = (target.get("params") or {}).get("slug")
        if not (isinstance(slug, str) and slug and custom_page_embeddable is not None
                and custom_page_embeddable(slug)):
            return _skip(REASON_CUSTOM_PAGE, key)

    location = target["path"]
    if not _is_safe_location(location):
        return _skip(REASON_UNSAFE_LOCATION, key)
    return UiRedirectDecision(location=location, reason=REASON_REDIRECT, key=key)


def decide_ui_redirect(**inputs):
    """The ``Location`` to redirect a request to, or None to serve it as it is.

    Takes the keyword arguments of ``evaluate_ui_redirect`` and answers only with the location.
    """
    return evaluate_ui_redirect(**inputs).location


def custom_page_opens_in_modern_ui(slug, settings):
    """Whether V2 will host this custom page for the signed-in user.

    The same facts V2's own host reads from the bootstrap navigation: the page is in the user's
    navigation list (which is already filtered by role and by the page being enabled), it is
    embeddable and it does not ask for its own tab. A page open to any signed-in user stays
    classic, because ``/v2`` needs the application role and those pages exist for people without
    it. Any failure answers False, so the page keeps being served as it always has.
    """
    try:
        import functions_custom_pages as custom_pages

        if not custom_pages.is_custom_pages_enabled(settings):
            return False
        item = next(
            (entry for entry in custom_pages.get_custom_pages_nav(settings) if entry.get("slug") == slug),
            None,
        )
        if item is None or item.get("open_in_new_tab") or item.get("embeddable") is not True:
            return False
        page = custom_pages.get_custom_page(slug, include_python=True)
        return isinstance(page, dict) and page.get("access_level") != "authenticated"
    except Exception as error:
        _log_redirect_failure(f"[UI_MODE] Could not check custom page '{slug}' for the modern interface: {error}")
        return False


def _log_redirect_failure(message):
    """A diagnostic must never be the reason a page request fails."""
    try:
        from functions_appinsights import log_event

        log_event(message, level=logging.WARNING, exceptionTraceback=True)
    except Exception:
        pass


def redirect_classic_page_to_modern_ui(settings_provider=None):
    """The ``before_request`` body: a 302 to the V2 counterpart of a classic page, or None.

    ``settings_provider`` returns the request's settings, so a page request reads them once and
    only when it is a candidate. Any failure here leaves the request to be served as it was.
    """
    def settings():
        return settings_provider() if settings_provider is not None else None

    try:
        decision = evaluate_ui_redirect(
            method=request.method,
            path=request.path,
            query_string=request.query_string,
            accept=request.headers.get("Accept", ""),
            xhr=request.headers.get("X-Requested-With", "").strip().lower() == "xmlhttprequest",
            fetch_dest=request.headers.get("Sec-Fetch-Dest"),
            fetch_mode=request.headers.get("Sec-Fetch-Mode"),
            signed_in=lambda: bool(session.get("user")),
            has_app_role=lambda: functions_ui_pages.has_app_user_role(session.get("user")),
            ui_mode=lambda: functions_ui_mode.get_ui_mode(settings()),
            bundle_available=functions_ui_pages.is_v2_bundle_ready,
            custom_page_embeddable=lambda slug: custom_page_opens_in_modern_ui(slug, settings()),
        )
    except Exception as error:
        _log_redirect_failure(f"[UI_MODE] The classic page redirect failed; serving the page as requested: {error}")
        return None

    if decision.location is None:
        return None
    response = redirect(decision.location, code=REDIRECT_STATUS_CODE)
    response.headers["Cache-Control"] = "no-store"
    return response
