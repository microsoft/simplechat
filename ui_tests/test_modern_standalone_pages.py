# test_modern_standalone_pages.py
"""
UI test for the modern standalone pages.
Version: 0.261.448
Implemented in: 0.261.448

The signed-out and no-role landing pages, the Acceptable Use Policy, the rate-limit (429)
page and the Microsoft 365 sign-in result stay server-rendered, so each has a modern variant
(templates/modern) that wears the V2 look without the classic navigation. This test renders
the real templates, with the real stylesheet and completion script, and drives them in
Chromium from one fake origin. Nothing here needs the application, a sign-in or the network.

It checks the headings, landmarks and links people and assistive technology rely on, the
theme (the V2 choice in localStorage, then the operating system, then no script at all),
rendered text contrast against the WCAG AA threshold in both themes, the layout at 390 px and
320 px with hostile long content, keyboard order with a visible focus indicator, and the
Microsoft 365 result page's popup contract.

The rendered contrast here is measured against the opaque page colour and the translucent
panel. The functional test of the same name measures the design tokens over the strongest part
of the background mesh as well.

Run: python -m pytest .\\ui_tests\\test_modern_standalone_pages.py -q
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import bleach
import markdown2
import pytest
from flask import Blueprint, Flask, session
from flask import render_template as flask_render_template
from markupsafe import Markup
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
for entry in (ROOT, ROOT / "functional_tests", APP_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

# The selector module is imported before the Microsoft 365 helper below, so the result page
# that helper renders shares this process's single copy of it.
import functions_ui_mode  # noqa: E402
import functions_ui_pages  # noqa: E402,F401
from test_support.app_source import run_definitions  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.color_contrast import CONTRAST_RATIO_SCRIPT  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from test_m365_connection_result_page import _routes_module, serve_static  # noqa: E402


pytestmark = pytest.mark.ui

ORIGIN = "https://simplechat.test"
DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 390, "height": 844}
NARROW = {"width": 320, "height": 640}

LIGHT_BACKDROP = "rgb(238, 242, 251)"
DARK_BACKDROP = "rgb(7, 11, 24)"
AA_TEXT = 4.5
UNSAFE_TEXT = '<img src=x onerror="window.injected=true"><script>window.injected=true</script>'
LONG_WORD = "Supercalifragilistic" * 12

SETTINGS = {
    "app_title": "Contoso Chat",
    "show_logo": True,
    "hide_app_title": False,
    "custom_logo_base64": False,
    "custom_logo_dark_base64": False,
    "custom_favicon_base64": False,
    "landing_page_alignment": "left",
    "landing_page_logo_scale_percent": 100,
    "access_denied_message": "You are signed in but do not have access.\nContact an administrator.",
    "access_request_button_enabled": True,
    "access_request_button_text": "Request Access",
    "access_request_page_url": "/custom/request-access",
    "classification_banner_enabled": True,
    "classification_banner_text": "UNCLASSIFIED // FOR TRAINING",
    "classification_banner_color": "#1a7f37",
    "classification_banner_text_color": "#ffffff",
}
NO_ROLE = {"oid": "user-1", "roles": []}
LANDING_TEXT = "# Welcome\n\nUse the assistant to **draft** and search. Read the [acceptable use policy](acceptable_use_policy.html)."
RATE_LIMIT_TEXT = "**You have reached the request limit.** Please wait a moment and [try again](/)."

OPENER_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8" /><title>Opener</title></head>
<body><button type="button" id="open">Sign in</button>
<script>
window.received = [];
window.addEventListener('message', (event) => window.received.push({ origin: event.origin, data: event.data }));
document.getElementById('open').addEventListener('click', () => {
    window.open('/getAToken?code=ui&state=fixture', 'simplechat-m365-connect', 'popup,width=600,height=600');
});
</script></body></html>"""
PROFILE_HTML = "<!doctype html><title>Profile</title><h1>Profile fixture</h1>"

# Throws the way a browser does when storage is blocked, before any page script runs.
BLOCKED_STORAGE = (
    "Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('blocked', 'SecurityError'); } });"
)

_FILTERS = {}


def app_filters():
    """The markdown and nl2br filters exactly as app.py defines them."""
    if not _FILTERS:
        namespace = {"markdown2": markdown2, "bleach": bleach, "re": re, "Markup": Markup}
        run_definitions("app.py", {"markdown_filter", "nl2br_filter"}, namespace)
        _FILTERS.update(markdown=namespace["markdown_filter"], nl2br=namespace["nl2br_filter"])
    return _FILTERS


def make_app(settings=None):
    """A Flask app with the real templates, the application's filters, route names and settings context."""
    app = Flask("modern_pages_ui", template_folder=str(APP_ROOT / "templates"), static_folder=str(APP_ROOT / "static"))
    app.secret_key = "ui-test-only"
    app.jinja_env.filters.update(app_filters())
    merged = {**SETTINGS, **(settings or {})}
    for blueprint_name, rule, endpoint in (
        ("public_app", "/", "index"), ("frontend_authentication", "/login", "login"), ("frontend_chats", "/chats", "chats"),
    ):
        blueprint = Blueprint(blueprint_name, __name__)
        blueprint.add_url_rule(rule, endpoint, lambda: "")
        app.register_blueprint(blueprint)

    @app.context_processor
    def inject_settings():
        return {"app_settings": merged}

    return app


def render_modern(template, *, user=None, settings=None, **context):
    with make_app(settings).test_request_context("/"):
        if user is not None:
            session["user"] = user
        return flask_render_template(template, **context)


def render_m365(settings=None, **options):
    """The Microsoft 365 result page as route_backend_m365 renders it in the modern interface."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(functions_ui_mode, "get_ui_mode", lambda settings=None, user_settings=None: "modern")
        with make_app(settings).test_request_context("/getAToken"):
            response = _routes_module()._connection_result_page(**options)
    return response.get_data(as_text=True)


def landing_markdown(text=LANDING_TEXT):
    return app_filters()["markdown"](text)


@pytest.fixture(scope="module")
def pages():
    assert_app_version_at_least("0.261.448")
    return {
        "landing-signed-out": render_modern("modern/landing.html", landing_html=landing_markdown()),
        "landing-no-role": render_modern(
            "modern/landing.html", user=NO_ROLE, landing_html=landing_markdown(),
            signed_in_account={"name": "Pat Doe", "account": "pat.doe@contoso.example"},
        ),
        "aup": render_modern("modern/acceptable_use_policy.html"),
        "rate-limited": render_modern(
            "modern/errors/429.html", rate_limit_message_html=app_filters()["markdown"](RATE_LIMIT_TEXT),
        ),
        "m365-failed": render_m365(
            kind="chat", outcome="failed", completion="auto", status=400, code="m365_auth_state_invalid",
            message="Consent was not completed.", continue_url="/profile?tab=settings#m365-chat-connection",
        ),
    }


class Site:
    """Serves rendered pages and the application's static files from one fake origin."""

    def __init__(self, browser, pages):
        self.browser = browser
        self.pages = {f"/{name}": html for name, html in pages.items()}
        self.pages["/opener"] = OPENER_HTML
        self.pages["/profile"] = PROFILE_HTML
        self.callback = ""
        self.contexts = []
        self.errors = []
        self.external = []
        self.unexpected = []

    def handle(self, route):
        parsed = urlsplit(route.request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.external.append(route.request.url)
            route.abort()
        elif parsed.path.startswith("/static/"):
            serve_static(route, parsed.path)
        elif parsed.path == "/getAToken":
            route.fulfill(content_type="text/html", body=self.callback)
        elif parsed.path in self.pages:
            route.fulfill(content_type="text/html", body=self.pages[parsed.path])
        else:
            self.unexpected.append(route.request.url)
            route.fulfill(status=404, body="")

    def open(self, name, *, viewport=DESKTOP, scheme="light", javascript=True, init_script=None, html=None):
        if html is not None:
            self.pages[f"/{name}"] = html
        context = self.browser.new_context(viewport=viewport, color_scheme=scheme, java_script_enabled=javascript)
        self.contexts.append(context)
        context.route("**/*", self.handle)
        if init_script:
            context.add_init_script(init_script)
        page = context.new_page()
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on("console", lambda message: self.errors.append(message.text) if message.type == "error" else None)
        page.goto(f"{ORIGIN}/{name}")
        return page

    def close(self):
        for context in self.contexts:
            context.close()


@pytest.fixture
def site(browser, pages):
    fixture = Site(browser, pages)
    yield fixture
    fixture.close()
    assert not fixture.errors, fixture.errors
    assert not fixture.external, fixture.external
    assert not fixture.unexpected, fixture.unexpected


# ---------------------------------------------------------------------------
# Structure: headings, landmarks and links
# ---------------------------------------------------------------------------

STRUCTURE = {
    "landing-signed-out": {
        "title": "Home - Contoso Chat", "h1": ["Contoso Chat", "Welcome"], "brand_header": False,
        "links": {"Sign in": "/login", "acceptable use policy": "acceptable_use_policy.html"},
        "text": ["Please sign in to continue.", "Use the assistant to draft and search."],
        "absent": ["Request Access", "Sign in with another account", "Signed in as"],
    },
    "landing-no-role": {
        "title": "Home - Contoso Chat", "h1": ["Contoso Chat"], "brand_header": False,
        "links": {"Request Access": "/custom/request-access", "Sign in with another account": "/login?select_account=1"},
        "text": [
            "You are signed in but do not have access.", "Contact an administrator.", "Signed in as", "Pat Doe",
            "pat.doe@contoso.example",
        ],
        "absent": ["Please sign in to continue."],
    },
    "aup": {
        "title": "Acceptable Use Policy - Contoso Chat", "h1": ["Acceptable Use Policy"], "brand_header": True,
        "links": {"Return to the home page": "/"},
        "text": ["This is an example.", "1. Prohibited Activities", "5. Changes to This Policy", "Last Updated: January 30, 2025"],
        "absent": [],
    },
    "rate-limited": {
        "title": "Rate limited - Contoso Chat", "h1": ["Rate limited"], "brand_header": True,
        "links": {"try again": "/", "Return to the home page": "/"},
        "text": ["You have reached the request limit."],
        "absent": [],
    },
    "m365-failed": {
        "title": "Microsoft 365 was not connected - Contoso Chat", "h1": ["Microsoft 365 was not connected"],
        "brand_header": True,
        "links": {"Return to settings": "/profile?tab=settings#m365-chat-connection"},
        "text": ["Consent was not completed."],
        "absent": [],
    },
}


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
@pytest.mark.parametrize("name", sorted(STRUCTURE))
def test_page_has_one_main_landmark_a_leading_h1_and_working_links(site, name, viewport):
    expected = STRUCTURE[name]
    page = site.open(name, viewport=viewport)

    expect(page).to_have_title(expected["title"])
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.get_by_role("main")).to_have_count(1)
    # The page's own h1 comes first; only text an administrator wrote can add another.
    expect(page.get_by_role("heading", level=1)).to_have_text(expected["h1"])
    # The skip link leads to the main landmark.
    expect(page.get_by_role("link", name="Skip to main content")).to_have_attribute("href", "#main-content")
    expect(page.locator("main#main-content")).to_have_attribute("tabindex", "-1")
    for text, href in expected["links"].items():
        expect(page.get_by_role("link", name=text, exact=True)).to_have_attribute("href", href)
    for text in expected["text"]:
        expect(page.get_by_text(text).first).to_be_visible()
    for text in expected["absent"]:
        expect(page.get_by_text(text)).to_have_count(0)
    # The compact brand sits above every page but the landing page, which keeps it in its panel.
    expect(page.get_by_role("banner")).to_have_count(1 if expected["brand_header"] else 0)
    # The administrator's classification banner leads the page in the colours they chose.
    banner = page.locator("#classification-banner")
    expect(banner).to_have_text("UNCLASSIFIED // FOR TRAINING")
    expect(banner).to_have_css("background-color", "rgb(26, 127, 55)")
    expect(banner).to_have_css("color", "rgb(255, 255, 255)")
    expect(banner).to_have_attribute("role", "note")
    assert banner.bounding_box()["y"] == 0 and banner.bounding_box()["width"] == viewport["width"]
    # No classic chrome and no Bootstrap: nothing a classic page loads is here.
    expect(page.locator("nav, .navbar, #sidebar-nav, link[href*='bootstrap']")).to_have_count(0)


def test_no_role_landing_puts_the_request_before_the_account_switch_and_centres_the_panel(site):
    page = site.open("landing-no-role")
    request_access = page.get_by_role("link", name="Request Access", exact=True).bounding_box()
    switch = page.get_by_role("link", name="Sign in with another account", exact=True).bounding_box()
    panel = page.locator(".ms-panel").bounding_box()

    assert request_access["x"] < switch["x"] and abs(request_access["y"] - switch["y"]) < 2, "Side by side on a wide screen"
    assert panel["width"] <= 640 + 1
    assert abs(panel["x"] - (DESKTOP["width"] - panel["x"] - panel["width"])) < 2


def test_actions_stack_at_phone_width_with_touch_sized_targets(site):
    page = site.open("landing-no-role", viewport=PHONE)
    request_access = page.get_by_role("link", name="Request Access", exact=True).bounding_box()
    switch = page.get_by_role("link", name="Sign in with another account", exact=True).bounding_box()

    assert switch["y"] >= request_access["y"] + request_access["height"], "Stacked, not side by side"
    assert request_access["height"] >= 44 and switch["height"] >= 44
    assert request_access["width"] == pytest.approx(switch["width"], abs=1), "Both fill the panel"


def test_landing_logo_height_follows_the_main_page_logo_size_setting(site):
    html = render_modern(
        "modern/landing.html", settings={"landing_page_logo_scale_percent": 64}, landing_html=landing_markdown(),
    )
    page = site.open("logo-size", html=html)
    assert page.locator("img.ms-logo-light").bounding_box()["height"] == pytest.approx(64, abs=1)


# ---------------------------------------------------------------------------
# Theme: the stored V2 choice, then the operating system, then no script
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scheme, stored, expected", [
    ("light", None, "light"),
    ("dark", None, "dark"),
    ("light", "dark", "dark"),
    ("dark", "light", "light"),
    ("dark", "system", "dark"),
])
def test_theme_follows_the_v2_choice_then_the_operating_system(site, scheme, stored, expected):
    init = f"try {{ localStorage.setItem('simplechat.v2.theme', {json.dumps(stored)}); }} catch (error) {{}}" if stored else None
    page = site.open("landing-signed-out", scheme=scheme, init_script=init)
    other = "dark" if expected == "light" else "light"

    assert page.evaluate("document.documentElement.className") == expected
    expect(page.locator("body")).to_have_css("background-color", DARK_BACKDROP if expected == "dark" else LIGHT_BACKDROP)
    expect(page.locator("html")).to_have_css("color-scheme", expected)
    # The logo that matches the theme is the one on screen.
    expect(page.locator(f"img.ms-logo-{expected}")).to_be_visible()
    expect(page.locator(f"img.ms-logo-{other}")).to_be_hidden()
    assert page.locator("img.ms-logo-light").get_attribute("src").endswith("logo-lightmode.png")
    assert page.locator("img.ms-logo-dark").get_attribute("src").endswith("logo-darkmode.png")


@pytest.mark.parametrize("scheme, backdrop", [("dark", DARK_BACKDROP), ("light", LIGHT_BACKDROP)])
def test_theme_still_follows_the_operating_system_when_storage_is_blocked(site, scheme, backdrop):
    page = site.open("aup", scheme=scheme, init_script=BLOCKED_STORAGE)
    assert page.evaluate("document.documentElement.className") == ""
    expect(page.locator("body")).to_have_css("background-color", backdrop)
    expect(page.locator(f"img.ms-logo-{scheme}").first).to_be_visible()


@pytest.mark.parametrize("scheme, backdrop", [("dark", DARK_BACKDROP), ("light", LIGHT_BACKDROP)])
def test_theme_still_follows_the_operating_system_without_script(site, scheme, backdrop):
    page = site.open("rate-limited", scheme=scheme, javascript=False)
    expect(page.locator("body")).to_have_css("background-color", backdrop)
    expect(page.get_by_role("heading", level=1)).to_have_text("Rate limited")
    expect(page.locator(f"img.ms-logo-{scheme}").first).to_be_visible()


# ---------------------------------------------------------------------------
# Contrast: rendered text against the colour behind it, in both themes
# ---------------------------------------------------------------------------

TEXT_SELECTORS = (
    "h1", "h2", ".ms-landing-title", ".ms-lead", ".ms-prose p", ".ms-prose li", ".ms-prose a", ".ms-prose strong",
    ".ms-brand-title", ".ms-button-primary", ".ms-button-secondary", ".ms-account dt", ".ms-account-name",
    ".ms-account-email", ".ms-note-text", ".ms-title",
)


def measure(page):
    results = {}
    for selector in TEXT_SELECTORS:
        for index, element in enumerate(page.locator(selector).all()):
            if element.is_visible():
                results[f"{selector}[{index}]"] = element.evaluate(CONTRAST_RATIO_SCRIPT, "color")
    return results


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("name", sorted(STRUCTURE))
def test_text_and_controls_meet_wcag_aa_contrast(site, name, scheme):
    ratios = measure(site.open(name, scheme=scheme))

    assert len(ratios) >= 4, ratios
    assert {key: ratio for key, ratio in ratios.items() if ratio < AA_TEXT} == {}


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_skip_link_is_legible_when_it_appears(site, scheme):
    page = site.open("landing-signed-out", scheme=scheme)
    page.keyboard.press("Tab")
    skip = page.get_by_role("link", name="Skip to main content")

    expect(skip).to_be_focused()
    assert skip.evaluate(CONTRAST_RATIO_SCRIPT, "color") >= AA_TEXT


# ---------------------------------------------------------------------------
# Layout: no sideways scrolling, even with hostile long content
# ---------------------------------------------------------------------------

HOSTILE_HTML = (
    f"<table><tr><td>{LONG_WORD}</td><td>{LONG_WORD}</td></tr></table>"
    f"<pre>{LONG_WORD}{LONG_WORD}</pre><p>{LONG_WORD} https://example.contoso.example/{'segment/' * 30}</p>"
)


@pytest.fixture(scope="module")
def stress_pages():
    return {
        "stress-landing-signed-out": render_modern("modern/landing.html", landing_html=landing_markdown(HOSTILE_HTML)),
        "stress-landing-no-role": render_modern(
            "modern/landing.html", user=NO_ROLE,
            settings={"access_denied_message": f"{LONG_WORD}\nhttps://example.contoso.example/{'segment/' * 30}"},
            signed_in_account={"name": LONG_WORD, "account": f"{LONG_WORD}@{LONG_WORD}.example"},
        ),
        "stress-rate-limited": render_modern(
            "modern/errors/429.html", rate_limit_message_html=app_filters()["markdown"](HOSTILE_HTML),
        ),
        "stress-m365": render_m365(
            kind="workflow", outcome="failed", completion="auto", status=400, code="x", message=LONG_WORD * 3,
            continue_url="/profile?tab=settings",
        ),
        "stress-title": render_modern(
            "modern/acceptable_use_policy.html", settings={"app_title": LONG_WORD, "classification_banner_text": LONG_WORD},
        ),
    }


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("viewport", [PHONE, NARROW], ids=["390px", "320px"])
@pytest.mark.parametrize("name", [
    "stress-landing-signed-out", "stress-landing-no-role", "stress-rate-limited", "stress-m365", "stress-title",
])
def test_layout_never_scrolls_sideways_with_hostile_content(site, stress_pages, name, viewport, scheme):
    page = site.open(name, viewport=viewport, scheme=scheme, html=stress_pages[name])

    layout = page.evaluate("""() => ({
        scroll: document.documentElement.scrollWidth, width: window.innerWidth,
        panels: [...document.querySelectorAll('.ms-panel')].map((panel) => {
            const box = panel.getBoundingClientRect();
            return {left: box.left, right: box.right};
        }),
    })""")
    assert layout["scroll"] <= layout["width"], layout
    assert layout["panels"] and all(0 <= panel["left"] and panel["right"] <= layout["width"] for panel in layout["panels"]), layout
    # A wide table or code block scrolls inside its own box instead of widening the page.
    for selector in ("pre", "table"):
        for element in page.locator(f".ms-prose {selector}").all():
            assert element.evaluate("(node) => getComputedStyle(node).overflowX") == "auto", selector


def test_a_long_policy_scrolls_vertically_and_its_last_link_is_reachable_on_a_phone(site):
    page = site.open("aup", viewport=PHONE)
    assert page.evaluate("document.documentElement.scrollHeight") > PHONE["height"], "The policy is longer than one screen"

    back = page.get_by_role("link", name="Return to the home page")
    back.scroll_into_view_if_needed()
    expect(back).to_be_in_viewport()


# ---------------------------------------------------------------------------
# Keyboard: order, visible focus, skip link
# ---------------------------------------------------------------------------

FOCUS_ORDER = {
    "landing-signed-out": ["Skip to main content", "acceptable use policy", "Sign in"],
    "landing-no-role": ["Skip to main content", "Request Access", "Sign in with another account"],
    "aup": ["Skip to main content", "Return to the home page"],
    "rate-limited": ["Skip to main content", "try again", "Return to the home page"],
    "m365-failed": ["Skip to main content", "Return to settings"],
}

FOCUS_STATE = """() => {
    const element = document.activeElement;
    const probe = document.createElement('span');
    probe.style.color = 'var(--accent)';
    document.body.append(probe);
    const accent = getComputedStyle(probe).color;
    probe.remove();
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return {
        text: (element.textContent || '').trim(), tag: element.tagName,
        outlineStyle: style.outlineStyle, outlineWidth: parseFloat(style.outlineWidth),
        outlineColor: style.outlineColor, accent,
        onScreen: box.top >= 0 && box.bottom <= window.innerHeight && box.right <= window.innerWidth && box.left >= 0,
    };
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("name", sorted(FOCUS_ORDER))
def test_tab_order_follows_reading_order_with_a_visible_focus_indicator(site, name, scheme):
    page = site.open(name, scheme=scheme)
    expected = FOCUS_ORDER[name]

    visited = []
    for _ in expected:
        page.keyboard.press("Tab")
        state = page.evaluate(FOCUS_STATE)
        visited.append(state["text"])
        assert state["outlineStyle"] == "solid" and state["outlineWidth"] >= 2, state
        assert state["outlineColor"] == state["accent"], state
        assert state["onScreen"], state
    assert visited == expected

    # Nothing else is focusable (the popup page's hidden Close button is not in the order), so
    # the next Tab leaves the page's controls: focus returns to the document or wraps to the skip link.
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.tagName === 'BODY' || document.activeElement.classList.contains('ms-skip-link')")


def test_skip_link_is_off_screen_until_focused_and_moves_focus_to_the_main_landmark(site):
    page = site.open("aup")
    skip = page.get_by_role("link", name="Skip to main content")
    resting = skip.bounding_box()
    assert resting["y"] + resting["height"] < 0, "Hidden above the page until it is focused"

    page.keyboard.press("Tab")
    expect(skip).to_be_focused()
    expect(skip).to_be_in_viewport()
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "main-content"
    assert page.url.endswith("#main-content")


# ---------------------------------------------------------------------------
# Microsoft 365 result: the completion script still drives the modern page
# ---------------------------------------------------------------------------

def open_result_popup(site, html):
    site.callback = html
    page = site.open("opener")
    with page.expect_popup() as opened:
        page.locator("#open").click()
    popup = opened.value
    if not popup.is_closed():
        popup.wait_for_event("close")
    return page.evaluate("window.received")


def test_popup_reports_a_workflow_connection_to_its_opener_and_closes(site):
    html = render_m365(
        kind="workflow", outcome="connected", completion="popup",
        continue_url="/profile?tab=settings&m365_connection=connected#m365-connection-status",
    )
    assert open_result_popup(site, html) == [{
        "origin": ORIGIN,
        "data": {"type": "m365-workflow-connected", "kind": "workflow", "outcome": "connected"},
    }]


def test_popup_reports_a_failure_as_text_and_never_runs_the_message(site):
    hostile = f"Consent was not completed. {UNSAFE_TEXT}"
    html = render_m365(
        kind="chat", outcome="failed", completion="popup", status=400, code="m365_consent_required",
        message=hostile, continue_url="/profile?tab=settings#m365-chat-connection",
    )
    assert open_result_popup(site, html) == [{
        "origin": ORIGIN,
        "data": {
            "type": "m365-connect-failed", "kind": "chat", "outcome": "failed",
            "code": "m365_consent_required", "message": hostile,
        },
    }]


def test_failure_without_an_opener_shows_the_error_as_text_with_a_link_back(site):
    hostile = f"Consent was not completed. {UNSAFE_TEXT}"
    html = render_m365(
        kind="chat", outcome="failed", completion="auto", status=400, code="m365_auth_state_invalid",
        message=hostile, continue_url="/profile?tab=settings#m365-chat-connection",
    )
    page = site.open("m365-hostile", html=html)

    expect(page.get_by_role("heading", name="Microsoft 365 was not connected")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text(hostile)
    expect(page.locator("#m365-connection-result img")).to_have_count(0)
    expect(page.get_by_role("link", name="Return to settings")).to_have_attribute("href", "/profile?tab=settings#m365-chat-connection")
    expect(page.get_by_role("button", name="Close window")).to_be_hidden()
    expect(page.locator("#m365-connection-result-closing")).to_be_hidden()
    assert urlsplit(page.url).path == "/m365-hostile"
    assert page.evaluate("window.injected === undefined")


def test_full_page_success_continues_to_the_fixed_settings_page(site):
    html = render_m365(
        kind="workflow", outcome="connected", completion="auto",
        continue_url="/profile?tab=settings&m365_connection=connected#m365-connection-status",
    )
    page = site.open("m365-connected", html=html)

    expect(page.get_by_role("heading", name="Profile fixture")).to_be_visible()
    returned = urlsplit(page.url)
    assert (returned.path, returned.query, returned.fragment) == (
        "/profile", "tab=settings&m365_connection=connected", "m365-connection-status",
    )


def test_popup_that_lost_its_opener_offers_to_close_instead_of_navigating(site):
    html = render_m365(
        kind="chat", outcome="connected", completion="popup", continue_url="/profile?tab=settings#m365-chat-connection",
    )
    page = site.open("m365-popup", html=html)
    close = page.get_by_role("button", name="Close window")

    expect(page.get_by_role("heading", name="Microsoft 365 is connected")).to_be_visible()
    expect(close).to_be_visible()
    expect(page.locator("#m365-connection-result-closing")).to_be_hidden()
    assert urlsplit(page.url).path == "/m365-popup"
    assert close.evaluate(CONTRAST_RATIO_SCRIPT, "color") >= AA_TEXT


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
