# test_v2_custom_pages.py
"""
Browser coverage for custom pages shown inside V2.

Version: 0.261.448
Implemented in: 0.261.448

Custom pages are trusted server-rendered documents, and the classic interface wraps each one in
its own navigation. They cannot become React pages, so V2 frames the chrome-less copy the server
renders at `/custom/<slug>?embed=1` inside its own content pane and keeps its rail on screen. The
shell here is the real built V2 bundle. The embedded document is the real
`custom_page_embed_shell.html`, rendered by a minimal Flask app, and every response carries the
security headers the application sends: a Content-Security-Policy with `frame-ancestors 'self'`,
`X-Frame-Options: DENY`, and `X-Frame-Options: SAMEORIGIN` on the embed document only. Real
Chromium therefore accepts or refuses the same-origin frame exactly as it does in production, and
only HTTP is stubbed.

Checks that the frame loads and fills the pane while the rail stays on screen, that the page's own
CSS, script and `/api/custom/...` call work inside it, and that the rail entry is a router link
with an active state. Then the theme follows V2 and ignores messages that are not the parent's; a
slug that is not in the user's navigation is "Page not available"; a page that cannot or should not
be framed offers a new tab; a 403, a 404 and a server error never show their error page in the
frame and can be retried; a late page replaces the failure panel; keyboard and phone layouts work;
and a document opened on its own gets the slim bar. Unexpected requests and console errors fail the
test.

The fixture also plays the part of the modern interface's classic-to-V2 redirect, with the
application's own `evaluate_ui_redirect` and route registry deciding every `/custom/<slug>`
navigation. That is what makes the new-tab links testable: the classic address of a page V2 hosts
is answered with a redirect back to the host, so a link to it would open a second host. The header
action and the failure panel therefore have to open `/custom/<slug>?embed=1`, the one address the
redirect never touches, at desktop and phone widths, and the tab that opens must show the chrome-less
page by itself, or the real error, never the V2 shell.
"""

import copy
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from playwright_connection import connect_options  # noqa: E402,F401
from v2_notification_stubs import is_notification_count, notification_count_payload  # noqa: E402
from test_support.custom_page_embed_render import (  # noqa: E402
    build_embed_app,
    render_embed_shell,
    static_page,
)
import functions_ui_mode  # noqa: E402
import functions_ui_redirect  # noqa: E402


pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = REPO_ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC_ROOT / "v2" / "index.html"
ARTIFACTS = REPO_ROOT / "ui_tests" / "artifacts" / "v2_custom_pages"
ORIGIN = "http://simplechat.test"
VERSION = "0.261.448"

# The Content-Security-Policy of config.SECURITY_HEADERS, as far as it bears on framing and on what
# an embedded page may load. functional_tests/test_custom_pages_embed_mode.py checks every directive
# against config.py, so this cannot drift from what the application sends.
PRODUCTION_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https: blob:; "
    "font-src 'self'; "
    "connect-src 'self' https: wss: ws:; "
    "frame-src 'self' blob:; "
    "object-src 'none'; "
    "frame-ancestors 'self'; "
    "base-uri 'self';"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": PRODUCTION_CSP,
    "X-Frame-Options": "DENY",
}

HANDBOOK_HTML = """
<section class="handbook" data-handbook>
    <h1>Employee handbook</h1>
    <p class="handbook-summary">Everything you need in one place.</p>
    <button type="button" class="btn btn-primary" data-handbook-button>Count</button>
    <output data-handbook-count-value>0</output>
    <output data-handbook-status>Waiting</output>
</section>
"""
HANDBOOK_CSS = ".handbook-summary { color: rgb(1, 2, 3); }"
HANDBOOK_JS = """
const root = document.querySelector("[data-handbook]");
const count = root.querySelector("[data-handbook-count-value]");
const status = root.querySelector("[data-handbook-status]");
root.querySelector("[data-handbook-button]").addEventListener("click", () => {
    count.textContent = String(Number(count.textContent) + 1);
});
fetch("/api/custom/handbook/status", { credentials: "same-origin" })
    .then((response) => response.json())
    .then((payload) => { status.textContent = payload.status; });
"""
PLAIN_HTML = '<section><h1 data-plain-heading>Plain page</h1><p>Nothing more.</p></section>'

# slug -> what the stub knows about the page. `embeddable` and `open_in_new_tab` are what the
# bootstrap navigation reports; the rest is what the server would read from the deployed files.
PAGES = {
    "handbook": {
        "label": "Handbook",
        "title": "Employee handbook",
        "embeddable": True,
        "open_in_new_tab": False,
        "html": HANDBOOK_HTML,
        "css_files": {"handbook.css": HANDBOOK_CSS},
        "js_files": {"handbook.js": HANDBOOK_JS},
    },
    "dash": {
        "label": "Python Dashboard",
        "title": "Python Dashboard",
        "embeddable": False,
        "open_in_new_tab": False,
        "html": PLAIN_HTML,
    },
    "policy": {
        "label": "Policy Portal",
        "title": "Policy Portal",
        "embeddable": True,
        "open_in_new_tab": True,
        "html": PLAIN_HTML,
    },
    "finance": {
        "label": "Finance",
        "title": "Finance",
        "embeddable": True,
        "open_in_new_tab": False,
        "html": PLAIN_HTML,
    },
    "slowpoke": {
        "label": "Slow Page",
        "title": "Slow Page",
        "embeddable": True,
        "open_in_new_tab": False,
        "html": PLAIN_HTML,
    },
}

ERROR_BODIES = {403: "Forbidden", 404: "Not Found", 500: "Internal Server Error"}

# A document that has loaded but only reports in well after the host has given up waiting. The gap
# between the host's 3 second grace and this delay is the window in which the failure panel shows.
SLOW_DOCUMENT = """<!DOCTYPE html>
<html lang="en"><head><title>Slow Page</title></head>
<body><h1 data-slow-heading>Slow page content</h1>
<script>
setTimeout(function () {
    window.parent.postMessage(
        { type: "simplechat-custom-page-ready", slug: "slowpoke" }, window.location.origin);
}, 6500);
</script></body></html>"""


class CustomPagesFixture:
    """The V2 shell with an in-memory API, and custom pages served as the application serves them."""

    def __init__(self, page: Page):
        self.page = page
        self.context: BrowserContext = page.context
        self.app = build_embed_app(VERSION)
        self.pages = copy.deepcopy(PAGES)
        self.embed_status = {}
        self.embed_requests = []
        self.classic_requests = []
        self.redirects = []
        self.api_requests = []
        self.settings_posts = []
        self.document_loads = 0
        self.preferences = {}
        self.viewer_roles = ["User"]
        self.errors = []
        self.unexpected_requests = []
        self.attach(page)
        self.context.on("page", self.attach)
        self.context.route("**/*", self._route)

    def attach(self, page: Page):
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on(
            "console",
            lambda message: self.errors.append(message.text) if message.type == "error" else None,
        )

    # -- what the server sends ------------------------------------------------------------

    def _bootstrap(self):
        items = [
            {
                "slug": slug,
                "label": details["label"],
                "icon": "bi-file-earmark-text",
                "url": f"/custom/{slug}",
                "open_in_new_tab": details["open_in_new_tab"],
                "embeddable": details["embeddable"],
            }
            for slug, details in self.pages.items()
        ]
        return {
            "version": VERSION,
            "user": {
                "id": "user-1",
                "display_name": "Riley Analyst",
                "email": "riley@contoso.test",
                "is_admin": False,
                "roles": ["User"],
            },
            "branding": {"app_title": "Contoso Chat", "show_logo": False, "hide_app_title": False},
            "features": {},
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {
                "custom_pages": {
                    "enabled": True,
                    "menu_name": "Company Pages",
                    "force_menu": False,
                    "items": items,
                },
                "external_links": {"enabled": False, "items": []},
            },
            "workspace": {"sections": {}},
            "settings": {},
        }

    def _render_embed(self, slug, *, standalone=False):
        details = self.pages[slug]
        metadata = static_page(
            slug,
            title=details["title"],
            css_files=list(details.get("css_files", {})),
            js_files=list(details.get("js_files", {})),
        )
        return render_embed_shell(
            self.app,
            metadata,
            details["html"],
            standalone=standalone,
            roles=self.viewer_roles,
            app_settings={"app_title": "Contoso Chat"},
            user_settings={"settings": dict(self.preferences)},
        )

    @staticmethod
    def _fulfill(route: Route, *, headers=None, **kwargs):
        route.fulfill(headers={**SECURITY_HEADERS, **(headers or {})}, **kwargs)

    def _hostable(self, slug):
        """Whether V2 hosts the page, the facts `custom_page_opens_in_modern_ui` reads from the navigation.

        The page is in the user's list, embeddable, and not asking for its own tab.
        functional_tests/test_custom_pages_embed_mode.py holds the application's function to the same
        facts, so this stand-in cannot drift from it.
        """
        details = self.pages.get(slug)
        return bool(details and details["embeddable"] and not details["open_in_new_tab"])

    @staticmethod
    def _fetch_destination(request):
        """`Sec-Fetch-Dest` for a navigation: `iframe` inside a frame, `document` for a tab.

        A new tab's first request is issued before its frame exists, which Playwright reports as an
        error from `request.frame`. Such a request is the tab's own document.
        """
        try:
            return "iframe" if request.frame.parent_frame else "document"
        except PlaywrightError:
            return "document"

    def _redirect_to_v2(self, route: Route):
        """The modern interface's classic-to-V2 redirect, decided by the application's own function.

        It runs ahead of the page for every `/custom/<slug>` navigation, as the `before_request`
        hook does, with the real route registry. Returns whether it answered the request.

        The server answers a 302. Playwright does not route the second hop of a redirect that a
        handler fulfilled, so the answer is an immediate refresh to the same location instead: the
        browser makes a new navigation to the V2 page and lands where the 302 would have sent it.
        """
        request = route.request
        parsed = urlsplit(request.url)
        decision = functions_ui_redirect.evaluate_ui_redirect(
            method=request.method,
            path=parsed.path,
            query_string=parsed.query,
            accept=request.headers.get("accept", ""),
            fetch_dest=self._fetch_destination(request),
            fetch_mode="navigate",
            signed_in=True,
            has_app_role=bool(set(self.viewer_roles) & {"User", "Admin"}),
            ui_mode=functions_ui_mode.UI_MODE_MODERN,
            bundle_available=True,
            custom_page_embeddable=self._hostable,
        )
        if decision.location is None:
            return False
        self.redirects.append({"from": parsed.path + (f"?{parsed.query}" if parsed.query else ""), "to": decision.location})
        self._fulfill(
            route,
            headers={"Cache-Control": "no-store"},
            body=f'<!DOCTYPE html><meta http-equiv="refresh" content="0; url={decision.location}">',
            content_type="text/html; charset=utf-8",
        )
        return True

    def _serve_custom_page(self, route: Route, slug, query):
        if slug not in self.pages:
            self._fulfill(route, status=404, body="Not Found", content_type="text/plain")
            return
        if "embed" not in query:
            # The classic address, which the "opens in a new tab" card for a page V2 does not frame
            # follows. A page V2 hosts never gets here: the redirect sends it back to the host.
            self.classic_requests.append(slug)
            self._fulfill(
                route,
                body=f"<!DOCTYPE html><title>Classic {slug}</title><h1>Classic page: {slug}</h1>",
                content_type="text/html; charset=utf-8",
            )
            return

        self.embed_requests.append({"slug": slug, "query": query})
        status = self.embed_status.get(slug)
        if status:
            self._fulfill(route, status=status, body=ERROR_BODIES[status], content_type="text/plain")
        elif slug == "slowpoke":
            self._fulfill(
                route,
                headers={"X-Frame-Options": "SAMEORIGIN"},
                body=SLOW_DOCUMENT,
                content_type="text/html; charset=utf-8",
            )
        else:
            # The application relaxes X-Frame-Options to SAMEORIGIN for the embed document only.
            self._fulfill(
                route,
                headers={"X-Frame-Options": "SAMEORIGIN"},
                body=self._render_embed(slug),
                content_type="text/html; charset=utf-8",
            )

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
            return
        method = request.method
        asset = re.fullmatch(r"/custom/assets/([^/]+)/(css|js)/([^/]+)", path)
        custom = re.fullmatch(r"/custom/([^/]+)", path)

        if method == "GET" and (path == "/v2" or path.startswith("/v2/")):
            self.document_loads += 1
            self._fulfill(route, path=str(SPA_INDEX), content_type="text/html")
        elif method == "GET" and path.startswith("/static/"):
            file = (STATIC_ROOT / unquote(path.removeprefix("/static/"))).resolve()
            if file.is_relative_to(STATIC_ROOT.resolve()) and file.is_file():
                self._fulfill(route, path=str(file))
            else:
                self.unexpected_requests.append(path)
                self._fulfill(route, status=404, body="Fixture asset not found", content_type="text/plain")
        elif method == "GET" and asset:
            slug, folder, name = asset.groups()
            files = self.pages.get(slug, {}).get(f"{folder}_files", {})
            if name in files:
                mime = "text/css" if folder == "css" else "application/javascript"
                self._fulfill(route, body=files[name], content_type=mime)
            else:
                self.unexpected_requests.append(path)
                self._fulfill(route, status=404, body="Not Found", content_type="text/plain")
        elif method == "GET" and custom:
            if not self._redirect_to_v2(route):
                self._serve_custom_page(route, custom.group(1), parse_qs(parsed.query))
        elif method == "GET" and path == "/api/custom/handbook/status":
            self.api_requests.append(path)
            self._fulfill(route, json={"status": "Healthy"})
        elif method == "GET" and path == "/api/v2/bootstrap":
            self._fulfill(route, json=self._bootstrap())
        elif path == "/api/user/settings":
            if method == "GET":
                self._fulfill(route, json={"settings": copy.deepcopy(self.preferences)})
            else:
                posted = request.post_data_json["settings"]
                self.settings_posts.append(posted)
                self.preferences.update(posted)
                self._fulfill(route, json={"message": "Saved."})
        elif is_notification_count(method, path):
            self._fulfill(route, json=notification_count_payload())
        else:
            self.unexpected_requests.append(f"{method} {path}")
            self._fulfill(route, status=404, json={"error": "Unexpected fixture request."})

    # -- driving the browser --------------------------------------------------------------

    def open(self, path, *, width=1440, height=900, preferences=None):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.preferences = {"darkModeEnabled": False, "v2RailCollapsed": False, **(preferences or {})}
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}{path}", wait_until="networkidle")

    def rail(self):
        return self.page.get_by_role("navigation", name="Primary")

    def frame(self, title="Handbook"):
        return self.page.frame_locator(f'iframe[title="{title}"]')

    def screenshot(self, name):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)

    def forget_errors(self, *fragments):
        """Drop console errors the browser logs for a response the test caused on purpose."""
        self.errors = [error for error in self.errors if not any(f in error for f in fragments)]

    def assert_clean(self):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors


@pytest.fixture
def custom_ui(page):
    fixture = CustomPagesFixture(page)
    yield fixture
    fixture.assert_clean()


def _box(locator):
    box = locator.bounding_box()
    assert box is not None, "The element has no layout box"
    return box


def test_page_fills_the_pane_beside_the_rail(custom_ui):
    custom_ui.open("/v2/custom/handbook")
    page = custom_ui.page
    frame = custom_ui.frame()

    expect(custom_ui.rail()).to_be_visible()
    expect(page.get_by_role("heading", level=1, name="Handbook")).to_be_visible()
    # The pane is showing the page, not hidden behind the loading or failure panel.
    expect(page.get_by_test_id("custom-page-frame")).to_be_visible()
    expect(page.get_by_test_id("custom-page-loading")).to_have_count(0)
    expect(page.get_by_test_id("custom-page-failed")).to_have_count(0)
    expect(frame.get_by_role("heading", name="Employee handbook")).to_be_visible()
    custom_ui.screenshot("page-desktop")

    # The rail entry names the page, links inside V2 and is the current page.
    entry = custom_ui.rail().get_by_role("link", name="Handbook", exact=True)
    expect(entry).to_have_attribute("href", "/v2/custom/handbook")
    expect(entry).to_have_attribute("aria-current", "page")

    # The frame is hardened without being able to leave: same-origin referrers, no delegated
    # features, and no flag that would let the page replace the whole application.
    iframe = page.locator('iframe[title="Handbook"]')
    expect(iframe).to_have_attribute("referrerpolicy", "same-origin")
    expect(iframe).to_have_attribute("allow", "")
    sandbox = (iframe.get_attribute("sandbox") or "").split()
    assert {"allow-scripts", "allow-same-origin"} <= set(sandbox), sandbox
    assert not [flag for flag in sandbox if flag.startswith("allow-top-navigation")], sandbox

    # The page carries no second title or classic chrome: the V2 header has the title.
    expect(frame.locator("[data-custom-page-embed-bar]")).to_be_hidden()
    expect(frame.locator("nav, .custom-page-hero, #classification-banner")).to_have_count(0)

    # It runs as it does in the classic shell: the declared stylesheet applies, the module script
    # runs, and the page reaches its own API with the signed-in session.
    expect(frame.locator(".handbook-summary")).to_have_css("color", "rgb(1, 2, 3)")
    expect(frame.locator("[data-handbook-status]")).to_have_text("Healthy")
    frame.get_by_role("button", name="Count").click()
    frame.get_by_role("button", name="Count").click()
    expect(frame.locator("[data-handbook-count-value]")).to_have_text("2")
    assert custom_ui.api_requests == ["/api/custom/handbook/status"]

    # The frame fills everything under the header, down to the bottom of the window.
    pane = _box(page.get_by_test_id("custom-page-pane"))
    framed = _box(page.get_by_test_id("custom-page-frame"))
    for edge in ("x", "y", "width", "height"):
        assert abs(pane[edge] - framed[edge]) <= 1, (edge, pane, framed)
    assert pane["y"] + pane["height"] >= 899 and framed["height"] > 600

    assert custom_ui.embed_requests == [{"slug": "handbook", "query": {"embed": ["1"]}}]
    assert custom_ui.document_loads == 1


def test_rail_entry_routes_inside_v2_and_leaves_other_pages_alone(custom_ui):
    custom_ui.open("/v2")
    page = custom_ui.page
    rail = custom_ui.rail()

    page.evaluate("window.__railMarker = 'kept'")
    entry = rail.get_by_role("link", name="Handbook", exact=True)
    expect(entry).not_to_have_attribute("aria-current", "page")
    entry.click()
    expect(page).to_have_url(f"{ORIGIN}/v2/custom/handbook")
    assert page.evaluate("window.__railMarker") == "kept", "The rail reloaded the document"
    expect(entry).to_have_attribute("aria-current", "page")
    expect(custom_ui.frame().get_by_role("heading", name="Employee handbook")).to_be_visible()
    assert custom_ui.document_loads == 1

    # A page that cannot be framed, and one that asks for its own tab, keep their anchors to the
    # classic page and are never the current page.
    dash = rail.get_by_role("link", name="Python Dashboard", exact=True)
    expect(dash).to_have_attribute("href", "/custom/dash")
    expect(dash).not_to_have_attribute("target", "_blank")
    policy = rail.get_by_role("link", name="Policy Portal", exact=True)
    expect(policy).to_have_attribute("href", "/custom/policy")
    expect(policy).to_have_attribute("target", "_blank")
    assert "noopener" in (policy.get_attribute("rel") or "")
    for link in (dash, policy):
        expect(link).not_to_have_attribute("aria-current", "page")


def test_theme_follows_v2_and_ignores_foreign_messages(custom_ui):
    custom_ui.open("/v2/custom/handbook")
    page = custom_ui.page
    frame_html = custom_ui.frame().locator("html")
    expect(custom_ui.frame().get_by_role("heading", name="Employee handbook")).to_be_visible()
    expect(frame_html).to_have_attribute("data-bs-theme", "light")

    page.get_by_role("button", name="Switch to dark theme").click()
    expect(frame_html).to_have_attribute("data-bs-theme", "dark")
    custom_ui.screenshot("page-dark-desktop")
    page.get_by_role("button", name="Switch to light theme").click()
    expect(frame_html).to_have_attribute("data-bs-theme", "light")

    # The page accepts the theme only from its parent window and only from its own origin. The
    # first message claims another origin, the second comes from the page's own window.
    frame = page.locator('iframe[title="Handbook"]').element_handle().content_frame()
    for source, origin in (("parent", "https://evil.test"), ("self", ORIGIN)):
        frame.evaluate(
            """([source, origin]) => {
                window.dispatchEvent(new MessageEvent('message', {
                    data: { type: 'simplechat-theme', theme: 'dark' },
                    origin,
                    source: source === 'self' ? window : window.parent,
                }));
            }""",
            [source, origin],
        )
    expect(frame_html).to_have_attribute("data-bs-theme", "light")


def test_a_page_opened_while_v2_is_dark_is_drawn_dark(custom_ui):
    custom_ui.open("/v2/custom/handbook", preferences={"darkModeEnabled": True})
    expect(custom_ui.frame().get_by_role("heading", name="Employee handbook")).to_be_visible()
    expect(custom_ui.frame().locator("html")).to_have_attribute("data-bs-theme", "dark")


def test_a_slug_that_is_not_in_the_navigation_is_not_available(custom_ui):
    page = custom_ui.page
    for path in ("/v2/custom/unknown", "/v2/custom/Handbook", "/v2/custom/..%2Fadmin"):
        custom_ui.open(path)
        expect(page.get_by_role("heading", level=1, name="Page not available")).to_be_visible()
        expect(page.get_by_text("This page is not available")).to_be_visible()
        expect(page.locator("iframe")).to_have_count(0)
        expect(custom_ui.rail()).to_be_visible()
    page.get_by_role("link", name="Go to home").click()
    expect(page).to_have_url(re.compile(rf"^{re.escape(ORIGIN)}/v2/?$"))
    assert custom_ui.embed_requests == [], "An unlisted page must not be requested at all"


def test_pages_that_cannot_be_framed_offer_a_new_tab(custom_ui):
    page = custom_ui.page
    reasons = {
        "dash": ("Python Dashboard", "cannot be shown inside this one"),
        "policy": ("Policy Portal", "set this page to open in its own tab"),
    }
    for slug, (label, reason) in reasons.items():
        custom_ui.open(f"/v2/custom/{slug}")
        expect(page.get_by_role("heading", level=1, name=label)).to_be_visible()
        expect(page.get_by_text(f"{label} opens in a new tab")).to_be_visible()
        expect(page.get_by_text(reason, exact=False)).to_be_visible()
        expect(page.locator("iframe")).to_have_count(0)

        link = page.get_by_role("link", name="Open in a new tab")
        expect(link).to_have_attribute("href", f"/custom/{slug}")
        expect(link).to_have_attribute("target", "_blank")
        assert "noopener" in (link.get_attribute("rel") or "")

    with page.expect_popup() as popup_info:
        link.click()
    popup = popup_info.value
    popup.wait_for_load_state()
    expect(popup.get_by_role("heading", name="Classic page: policy")).to_be_visible()
    assert custom_ui.embed_requests == [], "A page that is not framed must not be embedded"
    assert custom_ui.classic_requests == ["policy"]
    popup.close()


def test_an_error_page_is_never_shown_in_the_frame(custom_ui):
    page = custom_ui.page
    for status in (403, 404, 500):
        custom_ui.embed_status["finance"] = status
        custom_ui.open("/v2/custom/finance")
        failed = page.get_by_test_id("custom-page-failed")
        # The browser fires the frame's load event for an error page, so the host waits for the
        # page to report in before it believes there is anything to show.
        expect(failed).to_be_visible(timeout=10_000)
        expect(failed).to_contain_text("This page could not be loaded")
        expect(page.get_by_test_id("custom-page-frame")).to_be_hidden()
        expect(failed.get_by_role("link", name="Open in a new tab")).to_have_attribute(
            "href", "/custom/finance?embed=1"
        )
        custom_ui.screenshot(f"page-failed-{status}")
    custom_ui.forget_errors("403", "404", "500")


def test_try_again_makes_a_fresh_request_and_recovers(custom_ui):
    custom_ui.embed_status["finance"] = 403
    custom_ui.open("/v2/custom/finance")
    page = custom_ui.page
    failed = page.get_by_test_id("custom-page-failed")
    expect(failed).to_be_visible(timeout=10_000)
    assert len(custom_ui.embed_requests) == 1

    custom_ui.embed_status.pop("finance")
    failed.get_by_role("button", name="Try again").click()
    expect(page.get_by_test_id("custom-page-frame")).to_be_visible()
    expect(custom_ui.frame("Finance").locator("[data-plain-heading]")).to_be_visible()
    expect(failed).to_have_count(0)
    assert len(custom_ui.embed_requests) == 2, "Try again must request the page again"
    custom_ui.forget_errors("403")


# The two links a framed page has to a tab of its own are checked at both widths: the header action
# is an icon on a phone and a label on a desktop, and the failure panel fills the pane either way.
VIEWPORTS = [
    pytest.param((1440, 900), id="desktop"),
    pytest.param((390, 844), id="phone"),
]
CLASSIC_CHROME = (
    "custom-page-hero",
    "navigation.js",
    "sidebar.js",
    "notifications.js",
    "idle-logout-warning.js",
    "idleTimeoutWarningModal",
)


def _assert_page_on_its_own(popup, slug):
    """The tab shows the chrome-less document by itself: no V2 shell, no classic chrome, a way back."""
    assert popup.url == f"{ORIGIN}/custom/{slug}?embed=1"
    assert popup.evaluate("window.opener") is None, "The tab must not be able to reach the host"
    html = popup.content()
    assert not [marker for marker in CLASSIC_CHROME if marker in html], "The tab shows classic chrome"
    expect(popup.get_by_role("navigation", name="Primary")).to_have_count(0)
    bar = popup.locator("[data-custom-page-embed-bar]")
    expect(bar).to_be_visible()
    expect(bar.get_by_role("link", name="Back to Contoso Chat")).to_have_attribute("href", "/v2")


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_the_header_action_opens_the_page_on_its_own_never_a_second_host(custom_ui, viewport):
    width, height = viewport
    custom_ui.open("/v2/custom/handbook", width=width, height=height)
    page = custom_ui.page
    expect(custom_ui.frame().get_by_role("heading", name="Employee handbook")).to_be_visible()
    action = page.get_by_role("button", name="Open in a new tab")
    expect(action).to_be_visible()

    with page.expect_popup() as popup_info:
        action.click()
    popup = popup_info.value
    popup.wait_for_load_state()

    # The chrome-less document, not the classic address, which the modern interface sends back to
    # the host: nothing was redirected and the V2 shell was loaded once, by the page that was open.
    _assert_page_on_its_own(popup, "handbook")
    expect(popup.get_by_role("heading", name="Employee handbook")).to_be_visible()
    expect(popup.locator(".handbook-summary")).to_have_css("color", "rgb(1, 2, 3)")
    expect(popup.locator("[data-handbook-status]")).to_have_text("Healthy")
    assert custom_ui.redirects == []
    assert custom_ui.document_loads == 1
    assert [request["query"] for request in custom_ui.embed_requests] == [{"embed": ["1"]}] * 2
    popup.close()

    # The control that makes the check above mean something: the classic address of the same page
    # is what the redirect sends into V2, so it is the `embed=1` pair that keeps the new tab out.
    control = custom_ui.context.new_page()
    control.goto(f"{ORIGIN}/custom/handbook", wait_until="commit")
    expect(control).to_have_url(f"{ORIGIN}/v2/custom/handbook", timeout=10_000)
    expect(control.get_by_role("heading", level=1, name="Handbook")).to_be_visible()
    expect(control.frame_locator('iframe[title="Handbook"]').get_by_role("heading", name="Employee handbook")).to_be_visible()
    assert custom_ui.redirects == [{"from": "/custom/handbook", "to": "/v2/custom/handbook"}]
    control.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_the_failure_panel_opens_the_real_failure_on_its_own(custom_ui, viewport):
    width, height = viewport
    custom_ui.embed_status["finance"] = 403
    custom_ui.open("/v2/custom/finance", width=width, height=height)
    page = custom_ui.page
    failed = page.get_by_test_id("custom-page-failed")
    expect(failed).to_be_visible(timeout=10_000)

    link = failed.get_by_role("link", name="Open in a new tab")
    expect(link).to_be_visible()
    expect(link).to_have_attribute("href", "/custom/finance?embed=1")
    expect(link).to_have_attribute("target", "_blank")
    assert {"noopener", "noreferrer"} <= set((link.get_attribute("rel") or "").split())

    # It leads to the page's own address, which still answers 403: the real failure, not another
    # copy of the host that would show the same failing frame again.
    with page.expect_popup() as popup_info:
        link.click()
    popup = popup_info.value
    popup.wait_for_load_state()
    assert popup.url == f"{ORIGIN}/custom/finance?embed=1"
    assert popup.evaluate("window.opener") is None
    expect(popup.get_by_text("Forbidden")).to_be_visible()
    expect(popup.get_by_role("navigation", name="Primary")).to_have_count(0)
    assert custom_ui.redirects == []
    assert custom_ui.document_loads == 1
    popup.close()
    custom_ui.forget_errors("403")


def test_a_page_that_reports_late_replaces_the_failure_panel(custom_ui):
    custom_ui.open("/v2/custom/slowpoke")
    page = custom_ui.page
    # The document has loaded but stays silent past the grace period: shown as failed...
    expect(page.get_by_test_id("custom-page-failed")).to_be_visible(timeout=10_000)
    # ...and recovered when it does report, because a slow server is not a broken one.
    expect(page.get_by_test_id("custom-page-failed")).to_have_count(0, timeout=10_000)
    expect(page.get_by_test_id("custom-page-frame")).to_be_visible()
    expect(custom_ui.frame("Slow Page").locator("[data-slow-heading]")).to_be_visible()


def test_keyboard_can_skip_into_and_past_the_frame(custom_ui):
    custom_ui.open("/v2/custom/handbook")
    page = custom_ui.page
    expect(page.get_by_test_id("custom-page-frame")).to_be_visible()

    # The header action comes first, then the skip controls, then the frame.
    page.get_by_role("button", name="Open in a new tab").focus()
    page.keyboard.press("Tab")
    skip_in = page.get_by_role("button", name="Skip to Handbook")
    expect(skip_in).to_be_focused()
    assert _box(skip_in)["width"] > 20, "The skip control must be visible while it has focus"
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement && document.activeElement.tagName") == "IFRAME"

    page.get_by_role("button", name="Skip past Handbook").focus()
    page.keyboard.press("Enter")
    assert "End of Handbook" in page.evaluate("document.activeElement.textContent")

    # Activated from the keyboard, the header action opens the page on its own, as a click does.
    page.get_by_role("button", name="Open in a new tab").focus()
    with page.expect_popup() as popup_info:
        page.keyboard.press("Enter")
    popup = popup_info.value
    popup.wait_for_load_state()
    assert popup.url == f"{ORIGIN}/custom/handbook?embed=1"
    expect(popup.get_by_role("heading", name="Employee handbook")).to_be_visible()
    popup.close()


def test_the_embed_address_opened_on_its_own_shows_a_way_back(custom_ui):
    page = custom_ui.page
    page.goto(f"{ORIGIN}/custom/handbook?embed=1", wait_until="networkidle")
    bar = page.locator("[data-custom-page-embed-bar]")
    expect(bar).to_be_visible()
    expect(bar).to_contain_text("Employee handbook")
    expect(bar.get_by_role("link", name="Back to Contoso Chat")).to_have_attribute("href", "/v2")
    expect(page.get_by_role("heading", name="Employee handbook")).to_be_visible()

    # Someone without the app role cannot open V2, so the way back is the home page.
    custom_ui.viewer_roles = []
    page.reload(wait_until="networkidle")
    expect(bar.get_by_role("link", name="Back to Contoso Chat")).to_have_attribute("href", "/")

    # The theme is read from the V2 key first, then the classic one, before the first paint.
    html = page.locator("html")
    for stored, expected in (
        ({"simplechat.v2.theme": "dark"}, "dark"),
        ({"simplechat-theme": "dark"}, "dark"),
        ({"simplechat.v2.theme": "light", "simplechat-theme": "dark"}, "light"),
    ):
        page.evaluate(
            "keys => { localStorage.clear(); for (const [k, v] of Object.entries(keys)) localStorage.setItem(k, v); }",
            stored,
        )
        page.reload(wait_until="networkidle")
        expect(html).to_have_attribute("data-bs-theme", expected)


def test_custom_page_fits_a_phone(custom_ui):
    custom_ui.open("/v2/custom/handbook", width=390, height=844)
    page = custom_ui.page
    expect(page.get_by_role("button", name="Open navigation")).to_be_visible()
    expect(page.get_by_role("heading", level=1, name="Handbook")).to_be_visible()
    expect(page.get_by_test_id("custom-page-frame")).to_be_visible()
    expect(custom_ui.frame().get_by_role("heading", name="Employee handbook")).to_be_visible()

    framed = _box(page.get_by_test_id("custom-page-frame"))
    assert abs(framed["width"] - 390) <= 1, framed
    assert framed["height"] > 600, framed
    assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1
    overflow = custom_ui.frame().locator("html").evaluate("element => element.scrollWidth - element.clientWidth")
    assert overflow <= 1, f"The page scrolls sideways inside the frame by {overflow}px"
    custom_ui.screenshot("page-phone")
