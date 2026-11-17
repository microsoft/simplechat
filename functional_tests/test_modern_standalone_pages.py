#!/usr/bin/env python3
# test_modern_standalone_pages.py
"""
Functional test for the modern standalone pages.
Version: 0.261.445
Implemented in: 0.261.445

The Acceptable Use Policy, the rate-limit (429) page, the landing page for signed-out and
no-role visitors, and the Microsoft 365 sign-in result stay server-rendered, so each has a
modern variant under templates/modern that looks like V2 without the classic chrome.
functions_ui_pages.render_page picks between the two by asking functions_ui_mode.get_ui_mode,
which answers classic for everyone until the interface selector exists.

This test ensures that:
- by default every page renders its classic template with exactly the context it always had;
- when get_ui_mode answers modern each state renders the expected content, a signed-in
  application user is sent to /v2 only when the V2 bundle exists, and the 429 JSON path, the
  Retry-After header and the plain-text fallback are unchanged;
- the modern templates stay out of the classic chrome, load nothing from outside the
  application, keep administrator text escaped and keep the landing Markdown sanitised;
- the design tokens keep WCAG AA contrast in both themes.

The index, Acceptable Use Policy and 429 functions are the ones in app.py, executed from
source against the real templates, because importing app.py needs Cosmos DB.
"""

import ast
import importlib.util
import json
import logging
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import bleach
import markdown2
import pytest
from bs4 import BeautifulSoup
from flask import Blueprint, Flask, abort, jsonify, make_response, redirect, request, session, url_for
from flask import render_template as flask_render_template
from markupsafe import Markup
from werkzeug.exceptions import TooManyRequests

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.append(str(Path(__file__).resolve().parent))

import functions_rate_limit  # noqa: E402
import functions_ui_mode  # noqa: E402
import functions_ui_pages  # noqa: E402
import functions_ui_redirect  # noqa: E402
from test_support.app_source import run_definitions  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


TEMPLATES = APP_ROOT / "templates"
MODERN_TEMPLATES = TEMPLATES / "modern"
MODERN_CSS = APP_ROOT / "static" / "css" / "modern-standalone.css"
CLASSIC_TEMPLATES = ("index.html", "acceptable_use_policy.html", "errors/429.html", "m365_connection_result.html")

APP_PAGE_DEFINITIONS = {
    "markdown_filter", "nl2br_filter", "rate_limited_caller_wants_json",
    "handle_rate_limited_request", "public_app_bp", "index", "acceptable_use_policy",
}

SIGNED_OUT = None
NO_ROLE = {"oid": "user-1", "name": "Pat Doe", "preferred_username": "pat.doe@contoso.example", "roles": []}
APP_USER = {"oid": "user-2", "name": "Sam Roe", "preferred_username": "sam.roe@contoso.example", "roles": ["User"]}
ADMIN_USER = {"oid": "user-3", "name": "Ada Lin", "roles": ["Admin"]}

DEFAULT_SETTINGS = {
    "app_title": "Contoso Chat",
    "show_logo": True,
    "hide_app_title": False,
    "custom_logo_base64": "",
    "custom_logo_dark_base64": "",
    "custom_favicon_base64": "",
    "logo_version": 1,
    "logo_dark_version": 1,
    "favicon_version": 1,
    "landing_page_text": "Welcome to **Contoso**. Read the [acceptable use policy](acceptable_use_policy.html).",
    "landing_page_alignment": "left",
    "landing_page_logo_scale_percent": 100,
    "access_denied_message": "You are signed in but do not have access.\nContact an administrator.",
    "access_request_button_enabled": False,
    "access_request_button_text": "Request Access",
    "access_request_page_url": "/custom/request-access",
    "classification_banner_enabled": False,
    "classification_banner_text": "",
    "azure_search_admin_key": "must-never-reach-a-template",
}

SENSITIVE_TERMS = ("key", "secret", "password", "connection", "base64", "storage_account_url")
UNSAFE_TEXT = '<img src=x onerror="window.injected=true"><script>window.injected=true</script>'


def sanitize_settings(settings):
    """A stand-in for sanitize_settings_for_user: drop secrets, keep logo flags as booleans."""
    sanitized = {
        key: value for key, value in settings.items()
        if not any(term in key.lower() for term in SENSITIVE_TERMS)
    }
    for key in ("custom_logo_base64", "custom_logo_dark_base64", "custom_favicon_base64"):
        if key in settings:
            sanitized[key] = bool(settings[key])
    return sanitized


class Pages:
    """The real app.py page functions behind a Flask app that renders the real templates."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.settings = dict(DEFAULT_SETTINGS)
        self.classic_renders = []
        self.mode_requests = []
        self.logged = []
        self.bundle_available = False
        self.render_failure = None

        self.app = Flask("modern_standalone_pages", template_folder=str(TEMPLATES), static_folder=str(APP_ROOT / "static"))
        self.app.secret_key = "unit-test-only"
        self.app.config["TESTING"] = True

        monkeypatch.setattr(functions_ui_pages, "render_template", self.render_template)
        # The index route asks the shared predicate, which warns (throttled) when the bundle is the
        # reason a modern request stays classic. Observe the warning instead of writing it.
        functions_ui_pages.reset_bundle_warning_throttle()
        monkeypatch.setattr(functions_ui_pages, "_log_bundle_missing", lambda: self.logged.append("[UI_MODE] bundle missing"))
        self.set_mode("classic")

        namespace = {
            "__name__": "app_pages_under_test",
            "app": self.app, "Blueprint": Blueprint, "redirect": redirect, "url_for": url_for,
            "session": session, "request": request, "jsonify": jsonify, "make_response": make_response,
            "render_template": self.render_template, "markdown2": markdown2, "bleach": bleach, "re": re,
            "Markup": Markup, "logging": logging,
            "swagger_route": lambda **kwargs: (lambda function: function), "get_auth_security": lambda: [],
            "get_settings": lambda: dict(self.settings), "sanitize_settings_for_user": sanitize_settings,
            "ENABLE_AUTO_LOGIN_ON_INDEX": False,
            "build_rate_limit_error_payload": functions_rate_limit.build_rate_limit_error_payload,
            "get_rate_limit_message": functions_rate_limit.build_rate_limit_message,
            "log_event": lambda message, **kwargs: self.logged.append(message),
            "render_page": functions_ui_pages.render_page,
            "has_app_user_role": functions_ui_pages.has_app_user_role,
            "V2_HOME_PATH": functions_ui_pages.V2_HOME_PATH,
            # The real shared predicate, with the V2 bundle probe replaced by the test's switch.
            "is_modern_ui_available": lambda settings=None, user_settings=None: functions_ui_pages.is_modern_ui_available(
                settings, user_settings, bundle_available=lambda: self.bundle_available,
            ),
            "has_classic_escape": functions_ui_redirect.has_classic_escape,
        }
        run_definitions("app.py", APP_PAGE_DEFINITIONS, namespace)
        run_definitions("functions_authentication.py", {"get_signed_in_account_display"}, namespace)
        self.namespace = namespace
        self.app.jinja_env.filters["markdown"] = namespace["markdown_filter"]
        self.app.jinja_env.filters["nl2br"] = namespace["nl2br_filter"]
        self.app.register_blueprint(namespace["public_app_bp"])

        auth = Blueprint("frontend_authentication", __name__)
        auth.add_url_rule("/login", "login", lambda: "login")
        chats = Blueprint("frontend_chats", __name__)
        chats.add_url_rule("/chats", "chats", lambda: "chats")
        self.app.register_blueprint(auth)
        self.app.register_blueprint(chats)

        @self.app.context_processor
        def inject_settings():
            return {"app_settings": sanitize_settings(self.settings)}

        self.app.add_url_rule("/throttled", "throttled", lambda: abort(429))
        self.app.add_url_rule("/waiting", "waiting", self.raise_waiting)
        self.app.add_url_rule("/api/throttled", "api_throttled", self.raise_waiting)

    @staticmethod
    def raise_waiting():
        raise TooManyRequests(retry_after=30)

    def set_mode(self, mode):
        def get_ui_mode(settings=None, user_settings=None):
            self.mode_requests.append((settings, user_settings))
            return mode

        self.monkeypatch.setattr(functions_ui_mode, "get_ui_mode", get_ui_mode)

    def render_template(self, template_name, **context):
        """Real rendering for the modern templates; classic pages are recorded, not rendered."""
        if self.render_failure is not None:
            raise self.render_failure
        if template_name.startswith("modern/"):
            return flask_render_template(template_name, **context)
        self.classic_renders.append((template_name, context))
        return f"classic:{template_name}"

    def get(self, path, user=SIGNED_OUT, **kwargs):
        client = self.app.test_client()
        if user is not None:
            with client.session_transaction() as session_state:
                session_state["user"] = user
        kwargs.setdefault("headers", {"Accept": "text/html"})
        return client.get(path, **kwargs)

    def soup(self, path, user=SIGNED_OUT, **kwargs):
        response = self.get(path, user, **kwargs)
        assert response.status_code in (200, 429), response.status_code
        return BeautifulSoup(response.get_data(as_text=True), "html.parser")

    def render_modern(self, template, **context):
        with self.app.test_request_context("/"):
            html = flask_render_template(template, **context)
        return BeautifulSoup(html, "html.parser")


@pytest.fixture
def pages(monkeypatch):
    return Pages(monkeypatch)


def link(soup, name):
    return soup.find("a", string=lambda text: text is not None and text.strip() == name)


def page_text(soup):
    return " ".join(soup.get_text(" ").split())


def load_m365_routes():
    """The real Microsoft 365 route module with its authentication and logging seams stubbed."""
    spec = importlib.util.spec_from_file_location("m365_standalone_pages_routes", APP_ROOT / "route_backend_m365.py")
    module = importlib.util.module_from_spec(spec)

    def stub(name, **values):
        stand_in = types.ModuleType(name)
        stand_in.__dict__.update(values)
        return stand_in

    stubs = {
        "functions_appinsights": stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_authentication": stub(
            "functions_authentication", login_required=lambda function: function,
            user_required=lambda function: function, user_required_blueprint=lambda: (lambda: None),
        ),
        "swagger_wrapper": stub(
            "swagger_wrapper", swagger_route=lambda **kwargs: (lambda function: function), get_auth_security=lambda: [],
        ),
    }
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


def render_m365_result(**options):
    """The callback result page exactly as route_backend_m365 renders it, in a bare Flask app."""
    app = Flask("m365_result", template_folder=str(TEMPLATES), static_folder=str(APP_ROOT / "static"))
    with app.test_request_context("/getAToken"):
        response = load_m365_routes()._connection_result_page(**options)
    return response, BeautifulSoup(response.get_data(as_text=True), "html.parser")


@pytest.fixture
def modern_mode(monkeypatch):
    monkeypatch.setattr(functions_ui_mode, "get_ui_mode", lambda settings=None, user_settings=None: "modern")


# ---------------------------------------------------------------------------
# The seam: classic by default, so nothing changes for anyone
# ---------------------------------------------------------------------------

def test_default_interface_renders_every_classic_page_with_its_original_context(pages):
    assert_app_version_at_least("0.261.445")
    pages.bundle_available = True

    for user in (SIGNED_OUT, NO_ROLE, APP_USER, ADMIN_USER):
        pages.classic_renders.clear()
        response = pages.get("/", user)
        assert response.status_code == 200
        assert response.get_data(as_text=True) == "classic:index.html"
        (template, context), = pages.classic_renders
        assert template == "index.html"
        # Raw settings never reach a template, and the context is the one the page always had.
        assert set(context) == {"app_settings", "landing_html", "signed_in_account"}
        assert "azure_search_admin_key" not in context["app_settings"]
        assert context["landing_html"] == pages.namespace["markdown_filter"](DEFAULT_SETTINGS["landing_page_text"])
    assert context["signed_in_account"] == {"name": "Ada Lin", "account": ""}

    pages.classic_renders.clear()
    assert pages.get("/acceptable_use_policy.html").get_data(as_text=True) == "classic:acceptable_use_policy.html"
    assert pages.classic_renders == [("acceptable_use_policy.html", {})]

    pages.classic_renders.clear()
    throttled = pages.get("/waiting")
    assert throttled.status_code == 429
    assert throttled.get_data(as_text=True) == "classic:errors/429.html"
    (template, context), = pages.classic_renders
    assert template == "errors/429.html"
    assert set(context) == {"rate_limit_message_html"}
    assert isinstance(context["rate_limit_message_html"], Markup)


def test_default_interface_serves_the_real_m365_result_page_in_the_classic_shell():
    response, soup = render_m365_result(
        kind="workflow", outcome="connected", completion="auto", continue_url="/profile?tab=settings",
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert soup.find("link", href=lambda href: href and href.endswith("css/bootstrap.min.css"))
    assert not soup.find("link", href=lambda href: href and "modern-standalone" in href)


def test_without_a_selector_every_page_choice_is_classic():
    assert functions_ui_mode.get_ui_mode() == "classic"
    assert functions_ui_pages.choose_page_template("a.html", "modern/b.html") == "a.html"


def test_chooser_picks_the_template_for_the_mode_and_forwards_only_the_mode_inputs(pages):
    assert functions_ui_pages.render_page("a.html", "b.html", value=1) == "classic:a.html"
    assert pages.classic_renders[-1] == ("a.html", {"value": 1})

    pages.set_mode("modern")
    settings, user_settings = {"mode": "modern", "secret": "x"}, {"theme": "dark"}
    rendered = functions_ui_pages.render_page("a.html", "b.html", settings=settings, user_settings=user_settings, value=2)
    assert rendered == "classic:b.html"
    # The settings only go to the selector; they never become template context.
    assert pages.classic_renders[-1] == ("b.html", {"value": 2})
    assert pages.mode_requests[-1] == (settings, user_settings)

    # A mode the chooser does not know falls back to the classic page.
    pages.set_mode("something-else")
    assert functions_ui_pages.choose_page_template("a.html", "modern/b.html") == "a.html"


@pytest.mark.parametrize("user, expected", [
    (None, False), ({}, False), ({"roles": None}, False), ({"roles": []}, False),
    ({"roles": ["Reader"]}, False), ({"roles": "User"}, False), ({"roles": ["User"]}, True),
    ({"roles": ["Admin"]}, True), ({"roles": ("Reader", "User")}, True), ("User", False),
])
def test_application_role_test_matches_user_required(user, expected):
    assert functions_ui_pages.has_app_user_role(user) is expected


# ---------------------------------------------------------------------------
# Modern landing page: every state of the home page V2 cannot serve
# ---------------------------------------------------------------------------

def test_modern_landing_for_a_signed_out_visitor(pages):
    pages.set_mode("modern")
    soup = pages.soup("/")

    assert soup.html["lang"] == "en"
    assert soup.title.string == "Home - Contoso Chat"
    assert len(soup.find_all("main")) == 1 and soup.main["id"] == "main-content"
    assert soup.find("a", class_="ms-skip-link")["href"] == "#main-content"
    assert [heading.get_text(strip=True) for heading in soup.find_all("h1")] == ["Contoso Chat"]
    # The sanitised Markdown, with its own link, and a plain sign-in link.
    assert soup.find("strong", string="Contoso")
    assert soup.find("a", href="acceptable_use_policy.html")
    assert link(soup, "Sign in")["href"] == "/login"
    assert "Please sign in to continue." in page_text(soup)
    assert link(soup, "Sign in with another account") is None
    assert "Signed in as" not in page_text(soup)
    assert soup.find("link", rel="stylesheet")["href"] == "/static/css/modern-standalone.css"
    assert not soup.find("link", href=lambda href: href and "bootstrap" in href)


def test_modern_landing_for_a_user_signed_in_without_a_role(pages):
    pages.set_mode("modern")
    soup = pages.soup("/", NO_ROLE)

    message = soup.find("p", class_="ms-lead")
    assert message.get_text("|", strip=True) == "You are signed in but do not have access.|Contact an administrator."
    assert message.find("br") is not None
    account = soup.find("dl", class_="ms-account")
    assert account.find("dt").get_text(strip=True) == "Signed in as"
    assert account.find(class_="ms-account-name").get_text(strip=True) == "Pat Doe"
    assert account.find(class_="ms-account-email").get_text(strip=True) == "pat.doe@contoso.example"
    assert link(soup, "Sign in with another account")["href"] == "/login?select_account=1"
    assert link(soup, "Request Access") is None, "The button is off until an administrator enables it"
    assert link(soup, "Sign in") is None
    assert "Please sign in to continue." not in page_text(soup)


def test_modern_landing_names_an_account_without_a_display_name(pages):
    pages.set_mode("modern")
    soup = pages.soup("/", {"roles": [], "oid": "user-9"})
    assert soup.find(class_="ms-account-name").get_text(strip=True) == "Microsoft account"
    assert soup.find(class_="ms-account-email") is None


@pytest.mark.parametrize("url, visible", [
    ("/custom/request-access", True),
    ("https://access.contoso.example/request?team=ai", True),
    ("http://access.contoso.example/request", True),
    ("mailto:help@contoso.example", True),
    ("  /custom/request-access  ", True),
    ("javascript:window.injected=true", False),
    ("JAVASCRIPT:window.injected=true", False),
    ("data:text/html,<script>window.injected=true</script>", False),
    ("//evil.example/request", False),
    ("/\\evil.example/request", False),
    ("relative/path", False),
    ("", False),
])
def test_request_access_button_only_links_to_a_safe_destination(pages, url, visible):
    pages.set_mode("modern")
    pages.settings.update(access_request_button_enabled=True, access_request_button_text="Ask for access", access_request_page_url=url)
    soup = pages.soup("/", NO_ROLE)

    button = link(soup, "Ask for access")
    if visible:
        assert button is not None and button["href"] == url.strip()
        assert button.parent.find_all("a")[0] is button, "Request Access comes before the account switch"
    else:
        assert button is None
        assert not soup.find("a", href=lambda href: href and href.lower().startswith(("javascript:", "data:")))


def test_request_access_stays_hidden_when_the_administrator_switched_it_off(pages):
    pages.set_mode("modern")
    pages.settings.update(access_request_button_enabled=False)
    assert link(pages.soup("/", NO_ROLE), "Request Access") is None


def test_modern_landing_aligns_the_markdown_as_the_administrator_chose(pages):
    pages.set_mode("modern")
    for chosen, expected in (("left", "ms-align-start"), ("center", "ms-align-center"), ("right", "ms-align-end"), ("", "ms-align-start")):
        pages.settings["landing_page_alignment"] = chosen
        copy = pages.soup("/").find(class_="ms-landing-copy")
        assert expected in copy["class"], chosen


def test_signed_in_application_user_is_sent_to_v2_only_when_the_bundle_exists(pages):
    pages.set_mode("modern")

    pages.bundle_available = True
    for user in (APP_USER, ADMIN_USER):
        redirected = pages.get("/", user)
        assert redirected.status_code == 302
        assert redirected.headers["Location"] == "/v2"
    # A signed-out visitor and a user without a role stay on the landing page.
    for user in (SIGNED_OUT, NO_ROLE):
        assert pages.get("/", user).status_code == 200

    pages.bundle_available = False
    pages.classic_renders.clear()
    fallback = pages.get("/", APP_USER)
    assert fallback.status_code == 200
    assert fallback.get_data(as_text=True) == "classic:index.html", "Without a bundle /v2 answers 503, so the classic page stays"
    assert [template for template, _context in pages.classic_renders] == ["index.html"]


def test_classic_interface_never_redirects_to_v2_even_when_the_bundle_exists(pages):
    pages.bundle_available = True
    response = pages.get("/", APP_USER)
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "classic:index.html"


def test_open_this_page_in_classic_keeps_the_index_page_classic_in_the_modern_interface(pages):
    # V2's "Open this page in classic" adds ui=classic; the landing page must not undo that choice.
    pages.set_mode("modern")
    pages.bundle_available = True
    for query in ("?ui=classic", "?ui=Classic&x=1"):
        pages.classic_renders.clear()
        response = pages.get("/" + query, APP_USER)
        assert response.status_code == 200 and response.get_data(as_text=True) == "classic:index.html", query
    assert pages.get("/?ui=modern", APP_USER).status_code == 302
    assert pages.get("/", APP_USER).status_code == 302


def test_v2_home_path_is_a_registered_v2_route_not_a_404():
    # Flask matches /v2 and /v2/<path>; /v2/ is neither, so a redirect there would 404.
    source = (APP_ROOT / "route_frontend_v2.py").read_text(encoding="utf-8")
    assert f'@bp.route("{functions_ui_pages.V2_HOME_PATH}", methods=["GET"])' in source
    assert not functions_ui_pages.V2_HOME_PATH.endswith("/")


def test_modern_mode_still_honors_auto_login_on_the_index(pages):
    pages.set_mode("modern")
    pages.namespace["ENABLE_AUTO_LOGIN_ON_INDEX"] = True

    redirected = pages.get("/")
    assert redirected.status_code == 302
    assert redirected.headers["Location"] == "/login"
    assert pages.get("/", NO_ROLE).status_code == 200


def test_modern_landing_renders_for_a_signed_in_user_if_a_caller_asks_for_it(pages):
    # The index route redirects or renders classic for these users; the template still has to
    # answer correctly for a caller that renders it anyway, rather than claim access is denied.
    pages.set_mode("modern")
    with pages.app.test_request_context("/"):
        session["user"] = APP_USER
        html = flask_render_template("modern/landing.html", landing_html=Markup("<p>Hello</p>"))
    soup = BeautifulSoup(html, "html.parser")
    assert link(soup, "Start Chatting")["href"] == "/chats"
    assert "do not have access" not in page_text(soup)


# ---------------------------------------------------------------------------
# Acceptable Use Policy
# ---------------------------------------------------------------------------

def test_modern_acceptable_use_policy_keeps_the_policy_text_and_gains_a_way_back(pages):
    pages.set_mode("modern")
    soup = pages.soup("/acceptable_use_policy.html")

    assert soup.title.string == "Acceptable Use Policy - Contoso Chat"
    assert [heading.get_text(strip=True) for heading in soup.find_all("h1")] == ["Acceptable Use Policy"]
    assert [heading.get_text(strip=True) for heading in soup.find_all("h2")] == [
        "1. Prohibited Activities", "2. Data Privacy", "3. Responsible AI Use", "4. Enforcement", "5. Changes to This Policy",
    ]
    assert len(soup.find("h2").find_next("ul").find_all("li")) == 7
    assert "This is an example." in soup.find(id="example-notice").get_text()
    assert "By using this service, you agree to this Acceptable Use Policy." in page_text(soup)
    assert link(soup, "Return to the home page")["href"] == "/"


def test_acceptable_use_policy_text_matches_the_classic_page(pages):
    def words(html):
        return " ".join(BeautifulSoup(html, "html.parser").get_text(" ").split())

    classic = (TEMPLATES / "acceptable_use_policy.html").read_text(encoding="utf-8")
    classic_body = classic.split("{% block content %}")[1].split("{% endblock %}")[0]
    modern_text = page_text(pages.render_modern("modern/acceptable_use_policy.html"))
    # Every sentence of the classic policy is on the modern page, so the two cannot drift apart unseen.
    for sentence in re.split(r"(?<=[.:])\s+", words(classic_body)):
        assert sentence in modern_text, sentence


# ---------------------------------------------------------------------------
# Rate limit (429)
# ---------------------------------------------------------------------------

def test_modern_rate_limit_page_keeps_the_status_and_retry_after(pages):
    pages.set_mode("modern")
    response = pages.get("/waiting")
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.mimetype == "text/html"
    assert soup.title.string == "Rate limited - Contoso Chat"
    assert [heading.get_text(strip=True) for heading in soup.find_all("h1")] == ["Rate limited"]
    assert soup.find("strong", string="You have reached the request limit.")
    assert link(soup, "Return to the home page")["href"] == "/"


def test_rate_limit_without_a_retry_after_sends_no_header(pages):
    pages.set_mode("modern")
    response = pages.get("/throttled")
    assert response.status_code == 429
    assert "Retry-After" not in response.headers


def test_rate_limit_message_markdown_is_sanitised_in_the_modern_page(pages):
    pages.set_mode("modern")
    pages.settings.update(
        enable_custom_rate_limit_message=True,
        rate_limit_message=f"**Slow down** [help](javascript:window.injected=true) [docs](https://docs.contoso.example) {UNSAFE_TEXT}",
    )
    html = pages.get("/waiting").get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")

    assert soup.find("strong", string="Slow down")
    assert soup.find("a", href="https://docs.contoso.example")["target"] == "_blank"
    assert "javascript:" not in html and "onerror" not in html
    assert soup.find("img", attrs={"src": "x"}) is None
    assert len(soup.find_all("script")) == 1, "Only the theme script remains"


@pytest.mark.parametrize("mode", ["classic", "modern"])
def test_rate_limit_json_callers_never_get_a_page(pages, mode):
    pages.set_mode(mode)
    for response in (
        pages.get("/api/throttled", headers={"Accept": "application/json"}),
        pages.get("/waiting", headers={"Accept": "application/json"}),
        pages.get("/waiting", headers={"X-Requested-With": "XMLHttpRequest"}),
    ):
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "30"
        assert response.get_json() == {
            "error": functions_rate_limit.RATE_LIMIT_MESSAGE_DEFAULT, "rate_limited": True, "retry_after": 30,
        }
    assert pages.classic_renders == []


@pytest.mark.parametrize("mode", ["classic", "modern"])
def test_rate_limit_falls_back_to_plain_text_when_the_page_cannot_render(pages, mode):
    pages.set_mode(mode)
    pages.render_failure = RuntimeError("template missing")
    response = pages.get("/waiting")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.mimetype == "text/plain"
    assert response.get_data(as_text=True) == functions_rate_limit.RATE_LIMIT_MESSAGE_DEFAULT
    assert any(message.startswith("[RATE_LIMIT]") for message in pages.logged)


def test_rate_limit_page_needs_no_script_bundle_or_api(pages):
    pages.set_mode("modern")
    soup = pages.soup("/waiting")
    sources = [tag.get("src") for tag in soup.find_all("script") if tag.get("src")]
    assert sources == []
    assert not soup.find("a", href=lambda href: href and href.startswith("/v2"))


# ---------------------------------------------------------------------------
# Microsoft 365 sign-in result
# ---------------------------------------------------------------------------

def test_modern_m365_result_keeps_every_id_the_completion_script_uses(modern_mode):
    result_options = dict(
        kind="chat", outcome="connected", completion="popup", continue_url="/profile?tab=settings#m365-chat-connection",
    )
    response, soup = render_m365_result(**result_options)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store" and response.headers["Pragma"] == "no-cache"
    assert soup.find("meta", attrs={"name": "robots"})["content"] == "noindex"
    assert soup.title.string == "Microsoft 365 is connected - SimpleChat"
    assert [heading.get_text(strip=True) for heading in soup.find_all("h1")] == ["Microsoft 365 is connected"]
    assert soup.find(id="m365-connection-result").find(id="m365-connection-result-title")
    status = soup.find(attrs={"role": "status"})
    assert status["id"] == "m365-connection-result-message" and status["aria-live"] == "polite"
    assert "You can return to SimpleChat." in status.get_text()
    assert "d-none" in soup.find(id="m365-connection-result-closing")["class"]
    assert "d-none" in soup.find(id="m365-connection-result-close")["class"]
    assert soup.find(id="m365-connection-result-close").name == "button"
    assert soup.find(id="m365-connection-result-continue")["href"] == "/profile?tab=settings#m365-chat-connection"
    assert link(soup, "Return to settings") is soup.find(id="m365-connection-result-continue")

    data = json.loads(soup.find("script", id="m365-connection-result-data").string)
    assert data == {
        "type": "m365-profile-reconnected", "kind": "chat", "outcome": "connected", "completion": "popup",
        "code": None, "message": "Sign-in completed. You can return to SimpleChat.",
        "continue_url": "/profile?tab=settings#m365-chat-connection",
    }
    completion_script = soup.find("script", src=True)
    assert completion_script["src"] == "/static/js/profile/profile-m365-connection-result.js"


def test_modern_m365_failure_shows_the_error_as_text_and_cannot_break_out_of_the_data_block(modern_mode):
    hostile = f"Consent was not completed. </script><script>window.injected=true</script> {UNSAFE_TEXT}"
    response, soup = render_m365_result(
        kind="workflow", outcome="failed", completion="auto", status=400,
        code="m365_consent_required", message=hostile, continue_url="/profile?tab=settings#m365-connection-status",
    )

    assert response.status_code == 400
    assert [heading.get_text(strip=True) for heading in soup.find_all("h1")] == ["Microsoft 365 was not connected"]
    assert soup.find(attrs={"role": "status"}).get_text() == hostile
    assert not soup.find("img")
    scripts = soup.find_all("script")
    # The theme script, the JSON data block and the completion script; the hostile text added none.
    assert len(scripts) == 3
    assert json.loads(soup.find("script", id="m365-connection-result-data").string)["message"] == hostile
    assert "</script><script>window" not in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Administrator text and branding
# ---------------------------------------------------------------------------

def test_administrator_text_is_escaped_on_every_modern_page(pages):
    pages.set_mode("modern")
    pages.settings.update(
        app_title=f"Title {UNSAFE_TEXT}",
        access_denied_message=f"Denied {UNSAFE_TEXT}\nSecond line",
        access_request_button_enabled=True,
        access_request_button_text=f"Ask {UNSAFE_TEXT}",
        classification_banner_enabled=True,
        classification_banner_text=f"Banner {UNSAFE_TEXT}",
    )
    user = dict(NO_ROLE, name=f"Name {UNSAFE_TEXT}", preferred_username=f"mail-{UNSAFE_TEXT}@contoso.example")

    for path, who in (("/", user), ("/", SIGNED_OUT), ("/acceptable_use_policy.html", SIGNED_OUT), ("/waiting", SIGNED_OUT)):
        html = pages.get(path, who).get_data(as_text=True)
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find("img", attrs={"src": "x"}) is None, path
        assert soup.find(attrs={"onerror": True}) is None and "<img src=x" not in html, path
        assert len(soup.find_all("script")) == 1, (path, "only the theme script may exist")
        assert "&lt;script&gt;" in html, path
    denied = pages.soup("/", user)
    assert "&lt;img src=x onerror" in str(denied.find("p", class_="ms-lead"))
    assert denied.find("br") is not None, "The access denied message keeps its line breaks"


def test_landing_markdown_is_sanitised_and_a_plain_string_is_escaped(pages):
    pages.set_mode("modern")
    pages.settings["landing_page_text"] = (
        f"# Hello\n\n[click](javascript:window.injected=true) [fine](https://ok.contoso.example)\n\n{UNSAFE_TEXT}\n"
    )
    html = pages.get("/").get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.find("a", string="fine")["href"] == "https://ok.contoso.example"
    assert "javascript:" not in html and "onerror" not in html
    assert len(soup.find_all("script")) == 1 and soup.find("img", attrs={"src": "x"}) is None

    # A caller that hands the template an ordinary string gets it escaped, never parsed as markup.
    soup = pages.render_modern("modern/landing.html", landing_html="<b>bold</b><script>window.injected=true</script>")
    assert soup.find("b") is None
    assert "<b>bold</b>" in soup.find(class_="ms-landing-copy").get_text()
    assert len(soup.find_all("script")) == 1


@pytest.mark.parametrize("settings, light, dark", [
    ({}, "/static/images/logo-lightmode.png", "/static/images/logo-darkmode.png"),
    ({"custom_logo_base64": "x", "logo_version": 3}, "/static/images/custom_logo.png?v=3", "/static/images/custom_logo.png?v=3"),
    ({"custom_logo_dark_base64": "x", "logo_dark_version": 4}, "/static/images/logo-lightmode.png", "/static/images/custom_logo_dark.png?v=4"),
    (
        {"custom_logo_base64": "x", "custom_logo_dark_base64": "x", "logo_version": 3, "logo_dark_version": 4},
        "/static/images/custom_logo.png?v=3", "/static/images/custom_logo_dark.png?v=4",
    ),
])
def test_modern_pages_pick_the_same_logos_as_the_classic_landing_page(pages, settings, light, dark):
    pages.set_mode("modern")
    pages.settings.update(settings, landing_page_logo_scale_percent=72)

    landing = pages.soup("/")
    assert landing.find("img", class_="ms-logo-light")["src"] == light
    assert landing.find("img", class_="ms-logo-dark")["src"] == dark
    assert landing.find("img", class_="ms-logo-light")["height"] == "72"
    compact = pages.soup("/acceptable_use_policy.html")
    assert compact.find("header").find("img", class_="ms-logo-light")["src"] == light
    assert compact.find("header").find("img", class_="ms-logo-dark")["src"] == dark
    assert "height" not in compact.find("header").find("img").attrs


def test_hidden_title_and_hidden_logo_follow_the_branding_settings(pages):
    pages.set_mode("modern")

    pages.settings.update(hide_app_title=True, show_logo=True)
    landing = pages.soup("/")
    assert "ms-visually-hidden" in landing.find("h1")["class"], "The page keeps a heading for screen readers"
    assert landing.find("img")["alt"] == "Contoso Chat", "A logo with no visible title names the application"
    assert pages.soup("/acceptable_use_policy.html").find("p", class_="ms-brand-title") is None

    pages.settings.update(hide_app_title=False, show_logo=False)
    landing = pages.soup("/")
    assert landing.find("img") is None and "ms-visually-hidden" not in landing.find("h1")["class"]
    assert pages.soup("/acceptable_use_policy.html").find("p", class_="ms-brand-title").get_text() == "Contoso Chat"

    pages.settings.update(hide_app_title=True, show_logo=False)
    assert pages.soup("/acceptable_use_policy.html").find("header") is None


def test_classification_banner_and_favicon_follow_the_classic_rules(pages):
    pages.set_mode("modern")
    assert pages.soup("/").find(id="classification-banner") is None
    assert pages.soup("/").find("link", rel="icon")["href"] == "/static/images/favicon.ico"

    pages.settings.update(
        classification_banner_enabled=True, classification_banner_text="CUI // INTERNAL",
        classification_banner_color="#123456", classification_banner_text_color="#fedcba",
        custom_favicon_base64="x", favicon_version=7,
    )
    soup = pages.soup("/")
    banner = soup.find(id="classification-banner")
    assert banner["role"] == "note" and banner.get_text(strip=True) == "CUI // INTERNAL"
    assert banner["style"] == "background: #123456; color: #fedcba;"
    assert soup.find("link", rel="icon")["href"] == "/static/images/favicon.ico?v=7"
    assert soup.body.find().name == "a", "The skip link is the first thing in the page, ahead of the banner"

    pages.settings.update(classification_banner_color="", classification_banner_text_color="")
    assert pages.soup("/").find(id="classification-banner")["style"] == "background: #ffc107; color: #ffffff;"


def test_stylesheet_url_carries_the_application_version(pages):
    # A new release can rename classes; the version keeps a cache from serving the old stylesheet.
    pages.set_mode("modern")
    pages.app.config["VERSION"] = "9.8.7"
    assert pages.soup("/").find("link", rel="stylesheet")["href"] == "/static/css/modern-standalone.css?v=9.8.7"


def test_modern_templates_render_without_any_settings_in_the_context():
    # A bare Flask app has no context processor, as in the M365 callback tests; the pages must
    # not need app_settings to render.
    bare = Flask("bare", template_folder=str(TEMPLATES), static_folder=str(APP_ROOT / "static"))
    bare.add_url_rule("/", endpoint="public_app.index", view_func=lambda: "home")
    with bare.test_request_context("/"):
        soup = BeautifulSoup(flask_render_template("modern/acceptable_use_policy.html"), "html.parser")
    assert soup.title.string == "Acceptable Use Policy - SimpleChat"
    assert soup.find("header") is not None and soup.find("img") is None


# ---------------------------------------------------------------------------
# What the modern templates and stylesheet must never contain
# ---------------------------------------------------------------------------

def modern_template_files():
    files = sorted(path for path in MODERN_TEMPLATES.rglob("*.html"))
    assert len(files) >= 6, files
    return files


def test_no_modern_template_extends_the_classic_base_or_includes_classic_chrome():
    chrome = re.compile(r"""\{%-?\s*(?:extends|include|import|from)\s+["'](?:base\.html|_[a-z_]*nav[a-z_]*\.html|_custom_pages_drawer\.html)["']""")
    layouts = []
    for path in modern_template_files():
        source = path.read_text(encoding="utf-8")
        assert not chrome.search(source), path.name
        layouts += re.findall(r"""\{%-?\s*extends\s+["']([^"']+)["']""", source)
    assert set(layouts) == {"modern/standalone_base.html"}
    assert not re.search(r"\{%-?\s*extends", (MODERN_TEMPLATES / "standalone_base.html").read_text(encoding="utf-8"))


def test_classic_templates_keep_their_classic_chrome():
    for name in ("index.html", "acceptable_use_policy.html", "errors/429.html"):
        assert '{% extends "base.html" %}' in (TEMPLATES / name).read_text(encoding="utf-8"), name
    assert "css/bootstrap.min.css" in (TEMPLATES / "m365_connection_result.html").read_text(encoding="utf-8")


def test_modern_templates_and_stylesheet_load_nothing_from_outside_the_application():
    remote = re.compile(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}|@import|url\(\s*['\"]?https?:", re.IGNORECASE)
    for path in [*modern_template_files(), MODERN_CSS]:
        source = path.read_text(encoding="utf-8")
        assert not remote.search(source), (path.name, remote.search(source).group(0))
    for path in modern_template_files():
        for tag in BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").find_all(["script", "link", "img"]):
            reference = tag.get("src") or tag.get("href") or ""
            if reference and "{{" not in reference:
                assert reference.startswith("#") or not re.match(r"^(?:https?:)?//", reference), (path.name, reference)


def test_modern_templates_use_no_unsafe_browser_sinks():
    unsafe = re.compile(r"\|\s*safe\b|innerHTML|outerHTML|insertAdjacentHTML|\bon[a-z]+\s*=\s*[\"']|javascript:|\balert\s*\(|document\.write|\beval\s*\(", re.IGNORECASE)
    for path in modern_template_files():
        source = path.read_text(encoding="utf-8")
        assert not unsafe.search(source), (path.name, unsafe.search(source).group(0))


def css_declarations(block):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def css_block(source, selector):
    start = source.index(selector + " {") + len(selector) + 2
    depth, end = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(source[end], 0)
        end += 1
    return source[start:end - 1]


def test_dark_tokens_match_between_the_class_and_the_os_preference():
    source = MODERN_CSS.read_text(encoding="utf-8")
    light = css_declarations(css_block(source, ":root"))
    dark_class = css_declarations(css_block(source, ":root.dark"))
    dark_media = css_declarations(css_block(css_block(source, "@media (prefers-color-scheme: dark)"), ":root:not(.light):not(.dark)"))

    assert dark_class == dark_media, "Keep the two dark token blocks identical"
    assert set(dark_class) <= set(light)
    assert set(light) - set(dark_class) == {"--blur-glass", "--font-sans", "--font-mono"}


def test_stylesheet_is_the_one_the_templates_and_the_v2_tokens_agree_on():
    source = MODERN_CSS.read_text(encoding="utf-8")
    v2 = (APP_ROOT.parents[1] / "application" / "v2_ui" / "src" / "styles" / "theme.css").read_text(encoding="utf-8")
    light = css_declarations(css_block(source, ":root"))
    v2_light = css_declarations(css_block(v2, ":root"))
    v2_dark = css_declarations(css_block(v2, ".dark"))
    dark = css_declarations(css_block(source, ":root.dark"))
    # Every token the standalone pages repeat from V2 keeps V2's value; only the --ms-* tokens differ on purpose.
    for name, value in light.items():
        if not name.startswith("--ms-") and name in v2_light:
            assert v2_light[name] == value, name
    for name, value in dark.items():
        if not name.startswith("--ms-") and name in v2_dark:
            assert v2_dark[name] == value, name
    assert {name for name in light if not name.startswith("--ms-")} - set(v2_light) <= {"--font-sans", "--font-mono"}


# ---------------------------------------------------------------------------
# Contrast of the tokens, without a browser (the UI test measures the rendered pages)
# ---------------------------------------------------------------------------

def parse_color(value):
    value = value.strip()
    if value.startswith("#"):
        digits = value[1:]
        return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4)) + (1.0,)
    channels = re.match(r"rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:/\s*([\d.]+))?\s*\)", value)
    assert channels, value
    red, green, blue, alpha = channels.groups()
    return int(red), int(green), int(blue), float(alpha if alpha is not None else 1)


def over(top, bottom):
    alpha = top[3]
    return tuple(top[index] * alpha + bottom[index] * (1 - alpha) for index in range(3)) + (1.0,)


def luminance(color):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def contrast(foreground, background):
    foreground = over(foreground, background)
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_design_tokens_meet_wcag_aa_on_the_panel_over_every_part_of_the_mesh(theme):
    source = MODERN_CSS.read_text(encoding="utf-8")
    tokens = css_declarations(css_block(source, ":root"))
    if theme == "dark":
        tokens.update(css_declarations(css_block(source, ":root.dark")))
    color = {name: parse_color(value) for name, value in tokens.items() if name != "--blur-glass" and not name.startswith("--font") and not name.startswith("--shadow") and name != "--ms-control-border"}
    base = color["--backdrop-base"]
    backdrops = [base, *(over(color[tint], base) for tint in ("--backdrop-tint-a", "--backdrop-tint-b", "--backdrop-tint-c"))]

    def worst(foreground, *layers, minimum):
        ratios = []
        for backdrop in backdrops:
            surface = backdrop
            for layer in layers:
                surface = over(layer, surface)
            ratios.append(contrast(foreground, surface))
        assert min(ratios) >= minimum, (theme, foreground, layers, min(ratios))

    panel = color["--surface-3"]
    worst(color["--text-1"], panel, minimum=7)
    worst(color["--text-2"], panel, minimum=4.5)
    worst(color["--ms-link"], panel, minimum=4.5)
    worst(color["--ms-link-hover"], panel, minimum=4.5)
    worst(color["--text-1"], panel, color["--surface-sunken"], minimum=4.5)
    worst(color["--text-2"], panel, color["--surface-sunken"], minimum=4.5)
    worst(color["--text-1"], panel, color["--info-soft"], minimum=4.5)
    worst(color["--text-1"], panel, color["--surface-2"], minimum=4.5)
    worst(color["--text-1"], panel, color["--surface-3"], minimum=4.5)
    worst(color["--accent"], panel, minimum=3)
    worst(color["--info"], panel, color["--info-soft"], minimum=3)
    for icon, soft in (("--ms-icon-ok", "--ok-soft"), ("--ms-icon-danger", "--danger-soft"), ("--ms-icon-warn", "--warn-soft")):
        worst(color[icon], panel, color[soft], minimum=3)
    for fill in ("--ms-button-fill", "--ms-button-fill-hover"):
        assert contrast(color["--ms-button-text"], color[fill]) >= 4.5, (theme, fill)
        worst(color[fill], panel, minimum=3)


# ---------------------------------------------------------------------------
# The call sites
# ---------------------------------------------------------------------------

def called_names(source, function_name):
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    return {
        call.func.id for call in ast.walk(function)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


def test_call_sites_name_both_templates_and_keep_the_classic_template_literals():
    app_source = (APP_ROOT / "app.py").read_text(encoding="utf-8")
    assert re.search(r"render_page\(\s*'acceptable_use_policy\.html',\s*'modern/acceptable_use_policy\.html'\s*\)", app_source)
    assert re.search(r"render_page\(\s*'errors/429\.html',\s*'modern/errors/429\.html',", app_source)
    assert re.search(r"render_page\(\s*'index\.html',\s*'modern/landing\.html',\s*settings=settings,", app_source)
    assert "errors/429.html" in app_source, "test_rate_limit_message_configuration looks for the classic template name"
    for function in ("index", "acceptable_use_policy", "handle_rate_limited_request"):
        assert "render_page" in called_names(app_source, function), function

    m365_source = (APP_ROOT / "route_backend_m365.py").read_text(encoding="utf-8")
    assert 'CONNECTION_RESULT_TEMPLATE = "m365_connection_result.html"' in m365_source
    assert 'MODERN_CONNECTION_RESULT_TEMPLATE = "modern/m365_connection_result.html"' in m365_source
    names = called_names(m365_source, "_connection_result_page")
    assert "render_page" in names and "render_template" not in names


def test_the_chooser_stays_free_of_the_settings_and_cosmos_stack():
    source = (APP_ROOT / "functions_ui_pages.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:from|import)\s+([\w.]+)", source, re.MULTILINE))
    # Standard-library imports (the throttle for the bundle warning) are fine; anything that is
    # not Flask or the mode seam would drag the application stack into the 429 page's import.
    # The V2 route module and the logger are imported inside the functions that need them.
    assert imported - set(sys.stdlib_module_names) == {"flask", "functions_ui_mode"}, imported


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
