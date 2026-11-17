#!/usr/bin/env python3
# test_ui_redirect_edge.py
"""
Functional test for the classic to V2 edge redirect.
Version: 0.261.449
Implemented in: 0.261.448

When the modern interface is selected, a GET of a classic page is answered with a 302 to its V2
counterpart, so notification links, emails and bookmarks keep working. The tests
explicitly select each interface to verify routing independently of deployment defaults.

This test ensures that:
- every native, alias and partial registry row redirects, in the modern interface, to a path V2
  declares, and does nothing in the classic one; every other row never redirects;
- a redirect target is itself skipped, so a loop is impossible, and ``ui=classic`` (the "Open this
  page in classic" escape hatch) works when administrator policy permits it;
- only a signed-in person with an application role, who is opening a page, with the V2 bundle built,
  is redirected: not a form post, an API call, a static file, a fetch, a frame, a signed-out visitor,
  a user without the role, or a custom page V2 cannot host;
- a hostile path or query can never produce anything but a same-site path under /v2, and only the
  query keys a row maps cross over;
- the missing-bundle fallback is shared with the landing page, writes one throttled [UI_MODE]
  warning, and never turns into a redirect;
- the hook the real web app registers sits ahead of the Terms of Use and idle-timeout hooks, redirects
  the documented examples, leaves classic mode and every other request alone, and never echoes a host.
"""

import os
import re
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import pytest
from flask import Flask

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))
sys.path.append(str(TESTS_ROOT))

import functions_ui_mode  # noqa: E402
import functions_ui_pages  # noqa: E402
import functions_ui_redirect as redirect_module  # noqa: E402
import ui_routing  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_ui_route_parity_registry import app_declared_routes, declared_covering  # noqa: E402


MODERN = functions_ui_mode.UI_MODE_MODERN
CLASSIC = functions_ui_mode.UI_MODE_CLASSIC
ROUTE_MAP = ui_routing.load_ui_route_map()
CLASSIC_TOKEN_RE = re.compile(r"<(?:[a-z_]+:)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)>")

# What a representative request to each row carries, beyond its path.
REPRESENTATIVE_QUERIES = {
    "chat": "conversationId=abc&utm_source=mail",
    "workflow-activity": "runId=r1&workflowId=w1&scope=group&groupId=g1",
    "profile": "tab=feedback",
    "approvals": "m365_approval=a1",
    "content-review": "review_id=r1",
    "terms-of-use": "next=%2Fchats%3FconversationId%3Dabc",
}


def representative_path(classic):
    return CLASSIC_TOKEN_RE.sub(lambda match: "handbook" if match.group("name") == "slug" else "abc-123", classic)


def modern(**overrides):
    """The inputs of a signed-in application user opening a page in the modern interface."""
    inputs = dict(
        method="GET", path="/chats", query_string="", accept="text/html,application/xhtml+xml,*/*;q=0.8",
        xhr=False, fetch_dest="document", fetch_mode="navigate", signed_in=True, has_app_role=True,
        ui_mode=MODERN, bundle_available=True, custom_page_embeddable=lambda slug: True,
    )
    inputs.update(overrides)
    return inputs


def evaluate(**overrides):
    return redirect_module.evaluate_ui_redirect(**modern(**overrides))


def location_of(**overrides):
    return redirect_module.decide_ui_redirect(**modern(**overrides))


RESOLVABLE_ROWS = [row for row in ROUTE_MAP.routes if row.resolvable and "GET" in row.methods]
OTHER_ROWS = [row for row in ROUTE_MAP.routes if not row.resolvable and "GET" in row.methods]


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.448")


# ---------------------------------------------------------------------------
# The registry, row by row
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row", RESOLVABLE_ROWS, ids=lambda row: row.key)
def test_every_resolvable_row_redirects_in_modern_mode_to_a_path_v2_declares(row):
    path = representative_path(row.classic)
    query = REPRESENTATIVE_QUERIES.get(row.key, "")
    decision = evaluate(path=path, query_string=query)

    assert decision.reason == redirect_module.REASON_REDIRECT, f"{path}?{query}: {decision}"
    assert decision.key == row.key
    parts = urlsplit(decision.location)
    assert parts.scheme == "" and parts.netloc == "" and parts.fragment == "", decision.location
    assert parts.path == "/v2" or parts.path.startswith("/v2/"), decision.location
    router_path = parts.path[len("/v2"):] or "/"
    assert declared_covering(router_path, app_declared_routes()), (
        f"{decision.location} is not a route App.tsx declares; fix the row or the router."
    )

    classic = evaluate(path=path, query_string=query, ui_mode=CLASSIC)
    assert classic.location is None and classic.reason == redirect_module.REASON_CLASSIC_MODE


@pytest.mark.parametrize("row", OTHER_ROWS, ids=lambda row: row.key)
def test_rows_without_a_v2_page_never_redirect(row):
    decision = evaluate(path=representative_path(row.classic))
    assert decision.location is None
    assert decision.reason in (redirect_module.REASON_NO_V2_PAGE, redirect_module.REASON_NOT_A_PAGE_PATH)


@pytest.mark.parametrize("row", RESOLVABLE_ROWS, ids=lambda row: row.key)
def test_a_redirect_target_is_never_redirected_again(row):
    decision = evaluate(path=representative_path(row.classic), query_string=REPRESENTATIVE_QUERIES.get(row.key, ""))
    parts = urlsplit(decision.location)
    again = evaluate(path=parts.path, query_string=parts.query)
    assert again.location is None and again.reason == redirect_module.REASON_NOT_A_PAGE_PATH, (
        f"{decision.location} would be redirected again: {again}"
    )


def test_the_documented_examples():
    assert location_of(path="/chats", query_string="conversationId=x") == "/v2/chat?conversationId=x"
    assert location_of(path="/chats", query_string="conversation_id=x&junk=1") == "/v2/chat?conversationId=x"
    assert location_of(path="/profile", query_string="tab=feedback") == "/v2/settings?tab=feedback"
    assert location_of(path="/profile", query_string="tab=settings") == "/v2/settings?tab=preferences"
    assert location_of(path="/group_workspaces") == "/v2/groups"
    assert location_of(path="/groups/g-1") == "/v2/groups/g-1"
    assert location_of(path="/my_groups") == "/v2/settings?tab=groups"
    assert location_of(path="/notifications") == "/v2/notifications"
    assert location_of(path="/workflow-activity", query_string="runId=r&workflowId=w") == "/v2/workflow-activity?workflowId=w&runId=r"
    assert location_of(path="/approvals", query_string="m365_approval=a1") == "/v2/approvals?m365_approval=a1"
    assert location_of(path="/") == "/v2"
    # The mapping carries the stored link; the fragment, which a server never sees, is V2's to read.
    assert location_of(path="/workspace") == "/v2/workspace"


# ---------------------------------------------------------------------------
# What is never a person opening a classic page
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "post", None, 5])
def test_only_reads_are_redirected(method):
    decision = evaluate(method=method)
    assert decision.location is None and decision.reason == redirect_module.REASON_METHOD


@pytest.mark.parametrize("method", ["GET", "HEAD", "get", "head"])
def test_get_and_head_are_redirected(method):
    assert location_of(method=method, path="/notifications") == "/v2/notifications"


@pytest.mark.parametrize("path", [
    "/api/conversations", "/api/v2/bootstrap", "/static/js/chat/chat.js", "/static/v2/index.html", "/external/healthcheck",
    "/custom/assets/handbook/css/handbook.css", "/.well-known/oauth-authorization-server",
    "/v2", "/v2/", "/v2/chat", "/v2/chat?x=1", "/v2/custom/handbook", "/v2/access-restricted",
])
def test_api_static_and_v2_paths_are_never_redirected(path):
    decision = evaluate(path=path)
    assert decision.location is None and decision.reason == redirect_module.REASON_NOT_A_PAGE_PATH


@pytest.mark.parametrize("path", [
    "/login", "/logout", "/logout/local", "/getAToken", "/getATokenApi", "/ci-auth/session", "/auth/teams/token-exchange",
    "/terms-of-use/accept", "/terms-of-use/decline", "/api/m365/connections/callback", "/acceptable_use_policy.html",
    "/set_active_group", "/upload", "/view_pdf", "/swagger", "/robots933456.txt", "/favicon.ico", "/no/such/page",
])
def test_sign_in_callbacks_form_handlers_and_unknown_paths_stay_where_they_are(path):
    assert evaluate(path=path).location is None


def test_a_request_that_is_not_a_person_opening_a_page_is_left_alone():
    assert evaluate(xhr=True).reason == redirect_module.REASON_XHR
    for accept in ("application/json", "application/json, text/event-stream", "text/event-stream", "image/png", "application/json;q=1, text/html;q=0"):
        assert evaluate(accept=accept).reason == redirect_module.REASON_NOT_HTML, accept
    for fetch_dest, fetch_mode, reason in (
        ("empty", "cors", redirect_module.REASON_NOT_A_NAVIGATION),
        ("empty", "same-origin", redirect_module.REASON_NOT_A_NAVIGATION),
        ("script", "no-cors", redirect_module.REASON_NOT_A_NAVIGATION),
        ("document", "cors", redirect_module.REASON_NOT_A_NAVIGATION),
        ("document", "websocket", redirect_module.REASON_NOT_A_NAVIGATION),
        ("iframe", "navigate", redirect_module.REASON_FRAMED),
        ("IFRAME", "navigate", redirect_module.REASON_FRAMED),
        ("frame", "navigate", redirect_module.REASON_FRAMED),
        ("embed", "navigate", redirect_module.REASON_FRAMED),
        ("object", "navigate", redirect_module.REASON_FRAMED),
    ):
        decision = evaluate(fetch_dest=fetch_dest, fetch_mode=fetch_mode)
        assert decision.location is None and decision.reason == reason, (fetch_dest, fetch_mode, decision)


def test_a_client_that_sends_no_fetch_metadata_or_accept_header_is_opening_a_page():
    # curl, an older browser or a link checker: the redirect is harmless to them, so it applies.
    for kwargs in (dict(fetch_dest=None, fetch_mode=None), dict(fetch_dest="", fetch_mode=""), dict(accept=None), dict(accept=""), dict(accept="*/*")):
        assert location_of(**kwargs) == "/v2/chat", kwargs
    assert location_of(accept="application/json, text/plain, */*") == "/v2/chat", "Flask reads */* as willing to take a page too"


def test_accept_parsing_agrees_with_flask_wherever_flask_calls_a_request_json_only():
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request

    headers = [
        "", "*/*", "application/json", "application/json, */*", "application/json, text/plain, */*", "text/html", "text/*",
        "application/xhtml+xml", "text/html;q=0", "application/json;q=0.9, text/html;q=0.1", "TEXT/HTML", "application/*",
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    ]
    for header in headers:
        builder = EnvironBuilder(headers={"Accept": header} if header else {})
        accept = Request(builder.get_environ()).accept_mimetypes
        flask_calls_it_json_only = accept.accept_json and not accept.accept_html
        if flask_calls_it_json_only:
            assert not redirect_module._accepts_html(header), f"{header!r} is JSON-only for Flask but would be redirected here"
    assert not redirect_module._accepts_html("application/json")
    assert redirect_module._accepts_html("text/html;q=0.5")
    assert not redirect_module._accepts_html("text/html;q=0")
    assert not redirect_module._accepts_html("text/html;q=zero")
    assert redirect_module._accepts_html("x" * 5000 + ", text/html") is False, "An oversized header is not parsed past its cap"


# ---------------------------------------------------------------------------
# The escape hatch
# ---------------------------------------------------------------------------

def test_ui_classic_is_never_redirected_and_other_values_are():
    for query in ("ui=classic", "conversationId=x&ui=classic", "ui=Classic", "ui=CLASSIC", "ui=%63lassic", "?ui=classic", "ui=classic&ui=modern"):
        decision = evaluate(path="/chats", query_string=query)
        assert decision.location is None and decision.reason == redirect_module.REASON_ESCAPE_HATCH, query
    assert evaluate(path="/chats", query_string=b"ui=classic").reason == redirect_module.REASON_ESCAPE_HATCH
    assert evaluate(path="/chats", query_string=bytearray(b"ui=classic")).reason == redirect_module.REASON_ESCAPE_HATCH
    # Only the first ui value decides, and only the exact key does.
    for query in ("ui=modern", "ui=modern&ui=classic", "UI=classic", "ui=", "ui", "ui=classic2", "xui=classic", "other=ui%3Dclassic"):
        assert location_of(path="/chats", query_string=query) == "/v2/chat", query


def test_the_escape_parameter_is_not_copied_into_the_redirect():
    assert location_of(path="/chats", query_string="conversationId=x&ui=modern&utm_source=a") == "/v2/chat?conversationId=x"


def test_the_escape_check_is_shared_with_the_landing_page():
    has_escape = redirect_module.has_classic_escape
    for yes in ("ui=classic", "a=1&ui=Classic", "?ui=classic", b"ui=classic", bytearray(b"ui=classic"), "ui=%63lassic"):
        assert has_escape(yes) is True, yes
    for no in ("", None, "ui=modern", "ui=", "UI=classic", "ui=classic2", "a=ui%3Dclassic", "&".join(f"k{i}=v" for i in range(200)) + "&ui=classic", 5):
        assert has_escape(no) is False, no


def test_the_escape_hatch_applies_to_every_resolvable_row():
    for row in RESOLVABLE_ROWS:
        decision = evaluate(path=representative_path(row.classic), query_string="ui=classic")
        assert decision.reason == redirect_module.REASON_ESCAPE_HATCH, row.key


# ---------------------------------------------------------------------------
# State: who is asking, and whether V2 can answer
# ---------------------------------------------------------------------------

def test_signed_out_visitors_and_users_without_the_application_role_stay_on_the_classic_pages():
    assert evaluate(signed_in=False).reason == redirect_module.REASON_SIGNED_OUT
    assert evaluate(has_app_role=False).reason == redirect_module.REASON_NO_APP_ROLE
    for path in ("/", "/terms-of-use", "/chats"):
        assert location_of(path=path, signed_in=False) is None, path
        assert location_of(path=path, has_app_role=False) is None, path


def test_home_and_terms_of_use_redirect_signed_in_application_users_only():
    assert location_of(path="/") == "/v2"
    assert location_of(path="/terms-of-use") == "/v2/terms-of-use"
    assert location_of(path="/terms-of-use", query_string="next=%2Fchats%3FconversationId%3Dabc") == (
        "/v2/terms-of-use?next=%2Fchats%3FconversationId%3Dabc"
    )
    for path in ("/", "/terms-of-use"):
        assert location_of(path=path, signed_in=False) is None
        assert location_of(path=path, has_app_role=False) is None


def test_the_return_path_of_the_terms_page_is_carried_only_when_it_is_a_local_path():
    for hostile in ("//evil.example", "/\\evil.example", "https://evil.example/x", "%2F%2Fevil.example", "%2f%5cevil.example", "evil.example"):
        assert location_of(path="/terms-of-use", query_string=f"next={hostile}") == "/v2/terms-of-use", hostile


def test_the_modern_interface_without_the_bundle_serves_classic():
    decision = evaluate(bundle_available=False)
    assert decision.location is None and decision.reason == redirect_module.REASON_BUNDLE_MISSING


def test_state_inputs_are_read_lazily_and_in_order():
    """An API call or a static file costs nothing, and settings are read only for a real candidate."""
    calls = []

    def probe(name, value):
        def read():
            calls.append(name)
            return value
        return read

    def run(path="/chats", **overrides):
        calls.clear()
        state = dict(
            signed_in=probe("signed_in", True), has_app_role=probe("has_app_role", True),
            ui_mode=probe("ui_mode", MODERN), bundle_available=probe("bundle_available", True),
        )
        state.update(overrides)
        decision = redirect_module.evaluate_ui_redirect(method="GET", path=path, **state)
        return decision, list(calls)

    decision, read = run()
    assert decision.location == "/v2/chat"
    assert read == ["ui_mode", "signed_in", "has_app_role", "bundle_available"], "Cheapest and most decisive first"

    for path in ("/api/x", "/static/x.js", "/v2/chat", "/login", "/no/such/page"):
        decision, read = run(path)
        assert decision.location is None and read == [], f"{path} must not read any state, it read {read}"

    classic, read = run(ui_mode=probe("ui_mode", CLASSIC))
    assert classic.reason == redirect_module.REASON_CLASSIC_MODE and read == ["ui_mode"]
    signed_out, read = run(signed_in=probe("signed_in", False))
    assert signed_out.reason == redirect_module.REASON_SIGNED_OUT and read == ["ui_mode", "signed_in"]
    no_role, read = run(has_app_role=probe("has_app_role", False))
    assert no_role.reason == redirect_module.REASON_NO_APP_ROLE and read == ["ui_mode", "signed_in", "has_app_role"]
    no_bundle, read = run(bundle_available=probe("bundle_available", False))
    assert no_bundle.reason == redirect_module.REASON_BUNDLE_MISSING and read[-1] == "bundle_available"


# ---------------------------------------------------------------------------
# Custom pages
# ---------------------------------------------------------------------------

def test_a_custom_page_is_redirected_only_when_v2_can_host_it():
    asked = []

    def hostable(slug):
        asked.append(slug)
        return slug == "handbook"

    assert location_of(path="/custom/handbook", custom_page_embeddable=hostable) == "/v2/custom/handbook"
    assert location_of(path="/custom/handbook.html", custom_page_embeddable=hostable) == "/v2/custom/handbook"
    assert asked == ["handbook", "handbook"], "The .html alias asks about the same page"
    for slug in ("policy", "dash", "request-access"):
        decision = evaluate(path=f"/custom/{slug}", custom_page_embeddable=hostable)
        assert decision.location is None and decision.reason == redirect_module.REASON_CUSTOM_PAGE, slug
    # Without a predicate nothing is known about the page, so it stays classic.
    assert evaluate(path="/custom/handbook", custom_page_embeddable=None).reason == redirect_module.REASON_CUSTOM_PAGE


def test_the_frame_v2_itself_loads_is_never_redirected():
    for path in ("/custom/handbook", "/custom/handbook.html"):
        decision = evaluate(path=path, query_string="embed=1")
        assert decision.location is None and decision.reason == redirect_module.REASON_NO_V2_PAGE
        assert evaluate(path=path, query_string="x=1&embed=1").location is None
        # Only exactly embed=1 is the frame; anything else is a person opening the page.
        assert location_of(path=path, query_string="embed=0") == "/v2/custom/handbook"
        assert location_of(path=path, query_string="embed=true") == "/v2/custom/handbook"


def test_custom_page_assets_and_unsafe_slugs_are_never_redirected():
    assert evaluate(path="/custom/assets/handbook/css/handbook.css").location is None
    for slug in ("..", ".", "a%2Fb", "a b", "a%00b"):
        assert evaluate(path=f"/custom/{slug}").location is None, slug


class StubCustomPages:
    """functions_custom_pages with only what custom_page_opens_in_modern_ui reads."""

    def __init__(self, nav, pages, enabled=True):
        self.nav, self.pages, self.enabled = nav, pages, enabled

    def module(self):
        stub = types.ModuleType("functions_custom_pages")
        stub.is_custom_pages_enabled = lambda settings: bool(self.enabled and (settings or {}).get("enable_custom_pages"))
        stub.get_custom_pages_nav = lambda settings: list(self.nav)
        stub.get_custom_page = lambda slug, include_python=True: self.pages.get(slug)
        return stub


def nav_item(slug, **overrides):
    item = {"slug": slug, "label": slug.title(), "url": f"/custom/{slug}", "open_in_new_tab": False, "embeddable": True}
    item.update(overrides)
    return item


def test_the_wiring_asks_the_same_navigation_list_v2_reads():
    nav = [
        nav_item("handbook"),
        nav_item("policy", open_in_new_tab=True),
        nav_item("dash", embeddable=False),
        nav_item("request-access"),
        nav_item("legacy-item", embeddable=None),
    ]
    pages = {
        "handbook": {"slug": "handbook", "access_level": "app_user"},
        "policy": {"slug": "policy", "access_level": "app_user"},
        "dash": {"slug": "dash", "access_level": "app_user"},
        "request-access": {"slug": "request-access", "access_level": "authenticated"},
        "legacy-item": {"slug": "legacy-item", "access_level": "app_user"},
        "unlisted": {"slug": "unlisted", "access_level": "app_user"},
    }
    settings = {"enable_custom_pages": True}
    with mock.patch.dict(sys.modules, {"functions_custom_pages": StubCustomPages(nav, pages).module()}):
        opens = redirect_module.custom_page_opens_in_modern_ui
        assert opens("handbook", settings) is True
        assert opens("policy", settings) is False, "A page that asks for its own tab"
        assert opens("dash", settings) is False, "A page that cannot be framed"
        assert opens("request-access", settings) is False, "A page open to any signed-in user exists for people /v2 refuses"
        assert opens("legacy-item", settings) is False, "An item without the embeddable flag reads as not embeddable"
        assert opens("unlisted", settings) is False, "Not in the user's navigation, so V2 would say 'Page not available'"
        assert opens("missing", settings) is False
        assert opens("handbook", {"enable_custom_pages": False}) is False
        assert opens("handbook", None) is False

    logged = []
    broken = types.ModuleType("functions_custom_pages")
    broken.is_custom_pages_enabled = lambda settings: True
    broken.get_custom_pages_nav = mock.Mock(side_effect=RuntimeError("cache down"))
    fake_insights = types.ModuleType("functions_appinsights")
    fake_insights.log_event = lambda message, **kwargs: logged.append((message, kwargs.get("level")))
    with mock.patch.dict(sys.modules, {"functions_custom_pages": broken, "functions_appinsights": fake_insights}):
        assert redirect_module.custom_page_opens_in_modern_ui("handbook", settings) is False
    assert logged and logged[0][0].startswith("[UI_MODE]") and "cache down" in logged[0][0]


# ---------------------------------------------------------------------------
# Hostile input
# ---------------------------------------------------------------------------

HOSTILE_PATHS = (
    "//evil.example", "///evil.example", "/\\evil.example", "/\\\\evil.example", "/%2e%2e//evil.example", "/%2E%2E/evil",
    "https://evil.example/chats", "http:evil.example", "data:text/html,x", "evil.example/chats", "/chats\x00",
    "/chats\r\nSet-Cookie: a=b", "/chats%0d%0aSet-Cookie:a=b", "/groups/..", "/groups/%2e%2e", "/groups/a%2fb", "/groups/a b",
    "/groups//x", "/groups/a/../b", "/./chats", "/chats/", "/chats?x=1", "/chats#frag", "", "/chats\\..\\x", None, 5, b"/chats",
)


def test_a_hostile_path_never_produces_a_redirect():
    for path in HOSTILE_PATHS:
        assert evaluate(path=path).location is None, f"{path!r} must not be redirected"


def test_a_hostile_query_never_produces_anything_but_a_same_site_path_under_v2():
    queries = (
        "conversationId=//evil.example", "conversationId=https://evil.example", "next=//evil.example", "next=/\\evil",
        "next=https://evil.example", "next=%2F%2Fevil.example", "evil=1&__proto__=x", "conversationId=a%00b",
        "conversationId=a%0d%0aSet-Cookie:x=1", "conversationId=" + "x" * 5000, "&".join(f"k{index}=v" for index in range(200)),
        "conversationId", "=x", "%zz=1&conversationId=ok", "conversationId=%E0%A4%A", "m365_approval=<script>x</script>",
    )
    for path in ("/chats", "/terms-of-use", "/approvals", "/profile", "/workflow-activity"):
        for query in queries:
            location = location_of(path=path, query_string=query)
            if location is None:
                continue
            parts = urlsplit(location)
            assert parts.scheme == "" and parts.netloc == "", (path, query, location)
            assert location == "/v2" or location.startswith(("/v2/", "/v2?")), (path, query, location)
            assert "\\" not in location and " " not in location and not any(ord(char) < 0x20 for char in location), location
            assert "<" not in location and ">" not in location, location


def test_only_mapped_query_keys_cross_over_and_values_are_encoded_again():
    assert location_of(path="/chats", query_string="conversationId=a%26b%3Dc&unmapped=1&next=/x") == "/v2/chat?conversationId=a%26b%3Dc"
    assert location_of(path="/profile", query_string="tab=not-a-tab&junk=1") == "/v2/settings"
    assert location_of(path="/approvals", query_string="m365_approval=a%20b") == "/v2/approvals?m365_approval=a%20b"


def test_the_location_check_is_the_last_line_of_defence():
    for unsafe in ("//evil.example", "/v2//evil", "https://evil.example/v2", "/v2\\evil", "/v2 x", "/v2/x\r\ny", "/chats", "v2", "", None):
        assert redirect_module._is_safe_location(unsafe) is False, unsafe
    for safe in ("/v2", "/v2/chat", "/v2/chat?conversationId=abc", "/v2?x=1"):
        assert redirect_module._is_safe_location(safe) is True, safe
    with mock.patch.object(ui_routing, "resolve_v2_target", return_value={"path": "//evil.example", "key": "chat", "status": "native", "params": {}}):
        decision = evaluate()
    assert decision.location is None and decision.reason == redirect_module.REASON_UNSAFE_LOCATION


# ---------------------------------------------------------------------------
# The Flask wiring
# ---------------------------------------------------------------------------

class Wiring:
    """A bare Flask app with the hook, a few classic pages and the V2 shell routes."""

    def __init__(self, monkeypatch, settings=None):
        self.monkeypatch = monkeypatch
        self.settings = {"enable_custom_pages": True} if settings is None else settings
        self.mode_calls = []
        self.bundle_present = True
        self.warnings = []
        self.mode = MODERN
        self.settings_reads = 0

        self.app = Flask("redirect_wiring", static_folder=None)
        self.app.secret_key = "unit-test-only"
        self.app.config["TESTING"] = True

        def settings_provider():
            self.settings_reads += 1
            if isinstance(self.settings, Exception):
                raise self.settings
            return self.settings

        @self.app.before_request
        def hook():
            return redirect_module.redirect_classic_page_to_modern_ui(settings_provider)

        for path in ("/chats", "/", "/notifications", "/custom/<slug>", "/api/ping", "/static/x.js", "/v2", "/v2/chat", "/login"):
            self.app.add_url_rule(
                path, "page_" + re.sub(r"\W", "_", path), lambda **kwargs: "served",
                methods=["GET", "POST"] if path in ("/chats", "/api/ping") else ["GET"],
            )

        def get_ui_mode(settings=None, user_settings=None):
            self.mode_calls.append(settings)
            if isinstance(self.mode, Exception):
                raise self.mode
            return self.mode

        monkeypatch.setattr(functions_ui_mode, "get_ui_mode", get_ui_mode)
        monkeypatch.setattr(functions_ui_pages, "_probe_v2_bundle", lambda: self.bundle_present)
        monkeypatch.setattr(functions_ui_pages, "_log_bundle_missing", lambda: self.warnings.append("[UI_MODE]"))
        functions_ui_pages.reset_bundle_warning_throttle()

    def client(self, user="app", base_url=None):
        client = self.app.test_client()
        roles = {"app": ["User"], "admin": ["Admin"], "none": []}.get(user)
        if roles is not None:
            kwargs = {"base_url": base_url} if base_url else {}
            with client.session_transaction(**kwargs) as state:
                state["user"] = {"oid": "user-1", "name": "Pat", "roles": roles}
        return client


@pytest.fixture
def wiring(monkeypatch):
    return Wiring(monkeypatch)


def test_the_hook_redirects_with_a_302_that_no_cache_may_keep(wiring):
    response = wiring.client().get("/chats?conversationId=x&utm=1", headers={"Accept": "text/html"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/v2/chat?conversationId=x"
    assert response.headers["Cache-Control"] == "no-store"
    head = wiring.client().head("/notifications", headers={"Accept": "text/html"})
    assert head.status_code == 302 and head.headers["Location"] == "/v2/notifications"
    admin = wiring.client("admin").get("/", headers={"Accept": "text/html"})
    assert admin.status_code == 302 and admin.headers["Location"] == "/v2"


def test_the_location_is_a_bare_path_whatever_host_the_caller_names(wiring):
    response = wiring.client(base_url="http://evil.example").get(
        "/chats?conversationId=x", base_url="http://evil.example",
        headers={"Accept": "text/html", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https",
                 "Origin": "https://evil.example", "Referer": "https://evil.example/x"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/v2/chat?conversationId=x", "The Location must carry no host or scheme at all"
    assert "evil" not in response.headers["Location"]


def test_nothing_changes_in_the_classic_interface(wiring):
    wiring.mode = CLASSIC
    client = wiring.client()
    for path in ("/chats?conversationId=x", "/", "/notifications", "/custom/handbook"):
        response = client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 200 and response.get_data(as_text=True) == "served", path
    assert wiring.warnings == [], "The classic interface never writes the bundle warning"


def test_the_hook_leaves_every_other_request_alone(wiring):
    client = wiring.client()
    html = {"Accept": "text/html"}
    assert client.post("/chats?conversationId=x", headers=html).status_code == 200
    assert client.post("/api/ping", headers=html).status_code == 200
    for path in ("/api/ping", "/static/x.js", "/v2", "/v2/chat", "/login", "/chats?ui=classic", "/?ui=classic"):
        response = client.get(path, headers=html)
        assert response.status_code == 200, path
    assert client.get("/chats", headers={"Accept": "application/json"}).status_code == 200
    assert client.get("/chats", headers={**html, "X-Requested-With": "XMLHttpRequest"}).status_code == 200
    assert client.get("/chats", headers={**html, "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Mode": "navigate"}).status_code == 200
    assert client.get("/chats", headers={**html, "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors"}).status_code == 200
    assert client.get("/chats", headers={**html, "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"}).status_code == 302
    assert wiring.client("signed-out").get("/chats", headers=html).status_code == 200
    assert wiring.client("none").get("/chats", headers=html).status_code == 200


def test_the_hook_reads_settings_only_for_a_request_that_could_be_redirected(wiring):
    client = wiring.client()
    for path in ("/api/ping", "/static/x.js", "/v2/chat", "/login", "/chats?ui=classic"):
        client.get(path, headers={"Accept": "text/html"})
    assert wiring.settings_reads == 2 and wiring.mode_calls == [], (
        "Direct V2 navigation and the legacy escape must read policy; assets/APIs/login must not."
    )
    client.get("/chats", headers={"Accept": "text/html"})
    assert wiring.settings_reads >= 1 and wiring.mode_calls and wiring.mode_calls[0] is wiring.settings, (
        "The mode seam receives the request's settings so the selector can read them"
    )


def test_a_missing_bundle_keeps_every_page_classic_and_warns_once(wiring):
    wiring.bundle_present = False
    client = wiring.client()
    for path in ("/chats", "/notifications", "/", "/chats?conversationId=x", "/chats"):
        response = client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 200 and response.get_data(as_text=True) == "served", path
    assert wiring.warnings == ["[UI_MODE]"], "One warning for the process, not one per request"

    wiring.bundle_present = True
    assert client.get("/chats", headers={"Accept": "text/html"}).status_code == 302, "The bundle appearing needs no restart"


def test_a_failure_inside_the_hook_serves_the_classic_page(wiring):
    logged = []
    fake_insights = types.ModuleType("functions_appinsights")
    fake_insights.log_event = lambda message, **kwargs: logged.append(message)
    client = wiring.client()
    with mock.patch.dict(sys.modules, {"functions_appinsights": fake_insights}):
        wiring.mode = RuntimeError("settings store is down")
        assert client.get("/chats", headers={"Accept": "text/html"}).get_data(as_text=True) == "served"
        wiring.mode = MODERN
        wiring.settings = RuntimeError("cache is down")
        assert client.get("/chats", headers={"Accept": "text/html"}).get_data(as_text=True) == "served"
    assert len(logged) == 2 and all(message.startswith("[UI_MODE]") for message in logged), logged
    wiring.settings = {}
    assert client.get("/chats", headers={"Accept": "text/html"}).status_code == 302, "Recovery needs no restart"


def test_a_custom_page_goes_through_the_navigation_check(wiring):
    nav = [nav_item("handbook"), nav_item("policy", open_in_new_tab=True)]
    pages = {"handbook": {"slug": "handbook", "access_level": "app_user"}, "policy": {"slug": "policy", "access_level": "app_user"}}
    client = wiring.client()
    with mock.patch.dict(sys.modules, {"functions_custom_pages": StubCustomPages(nav, pages).module()}):
        assert client.get("/custom/handbook", headers={"Accept": "text/html"}).headers["Location"] == "/v2/custom/handbook"
        assert client.get("/custom/handbook?embed=1", headers={"Accept": "text/html"}).status_code == 200
        assert client.get("/custom/policy", headers={"Accept": "text/html"}).status_code == 200
        assert client.get("/custom/unlisted", headers={"Accept": "text/html"}).status_code == 200


# ---------------------------------------------------------------------------
# The shared "modern and available" predicate and its warning
# ---------------------------------------------------------------------------

class PredicateWorld:
    def __init__(self, monkeypatch):
        self.mode = MODERN
        self.probes = 0
        self.bundle = True
        self.logged = []
        monkeypatch.setattr(functions_ui_mode, "get_ui_mode", lambda settings=None, user_settings=None: self.mode)
        monkeypatch.setattr(functions_ui_pages, "_probe_v2_bundle", self.probe)
        monkeypatch.setattr(functions_ui_pages, "_log_bundle_missing", lambda: self.logged.append("warned"))
        functions_ui_pages.reset_bundle_warning_throttle()

    def probe(self):
        self.probes += 1
        return self.bundle


def test_classic_mode_never_probes_the_bundle_or_warns(monkeypatch):
    world = PredicateWorld(monkeypatch)
    world.mode = CLASSIC
    world.bundle = False
    for _ in range(3):
        assert functions_ui_pages.is_modern_ui_available({"x": 1}) is False
    assert world.probes == 0 and world.logged == []


def test_modern_mode_with_the_bundle_is_available_and_silent(monkeypatch):
    world = PredicateWorld(monkeypatch)
    assert functions_ui_pages.is_modern_ui_available() is True
    assert functions_ui_pages.is_v2_bundle_ready() is True
    assert world.logged == []


def test_modern_mode_without_the_bundle_is_classic_with_one_throttled_warning(monkeypatch):
    world = PredicateWorld(monkeypatch)
    world.bundle = False
    for _ in range(5):
        assert functions_ui_pages.is_modern_ui_available() is False
    assert world.logged == ["warned"], "A warning per request would bury the log"

    # After the interval the process says so again; before it, it does not.
    interval = functions_ui_pages.BUNDLE_WARNING_INTERVAL_SECONDS
    started = functions_ui_pages._bundle_warning_logged_at
    assert functions_ui_pages._warn_bundle_missing_once(now=started + interval - 1) is False
    assert functions_ui_pages._warn_bundle_missing_once(now=started + interval) is True
    assert world.logged == ["warned", "warned"]


def test_the_probe_and_the_bundle_input_can_be_replaced(monkeypatch):
    world = PredicateWorld(monkeypatch)
    world.bundle = False
    assert functions_ui_pages.is_modern_ui_available(bundle_available=True) is True
    assert functions_ui_pages.is_modern_ui_available(bundle_available=lambda: True) is True
    assert world.probes == 0 and world.logged == []
    assert functions_ui_pages.is_v2_bundle_ready(False) is False and world.logged == ["warned"]


def test_the_warning_carries_the_tag_and_never_breaks_the_page(monkeypatch):
    seen = []
    fake_insights = types.ModuleType("functions_appinsights")
    fake_insights.log_event = lambda message, **kwargs: seen.append((message, kwargs))
    functions_ui_pages.reset_bundle_warning_throttle()
    with mock.patch.dict(sys.modules, {"functions_appinsights": fake_insights}):
        assert functions_ui_pages._warn_bundle_missing_once() is True
    (message, kwargs), = seen
    import logging
    assert message.startswith("[UI_MODE] ") and "V2 bundle" in message and "npm run build" in message
    assert kwargs["level"] == logging.WARNING

    def explode(message, **kwargs):
        raise RuntimeError("logger is down")

    fake_insights.log_event = explode
    functions_ui_pages.reset_bundle_warning_throttle()
    with mock.patch.dict(sys.modules, {"functions_appinsights": fake_insights}):
        assert functions_ui_pages._warn_bundle_missing_once() is False
    functions_ui_pages.reset_bundle_warning_throttle()


def test_the_probe_is_the_v2_route_modules_own_check(monkeypatch):
    stub = types.ModuleType("route_frontend_v2")
    stub.is_v2_bundle_available = lambda: True
    with mock.patch.dict(sys.modules, {"route_frontend_v2": stub}):
        assert functions_ui_pages._probe_v2_bundle() is True
        stub.is_v2_bundle_available = lambda: False
        assert functions_ui_pages._probe_v2_bundle() is False


# ---------------------------------------------------------------------------
# The real web app, in a fresh process with the network blocked
# ---------------------------------------------------------------------------

APP_PROBE = r'''
import sys
from contextlib import ExitStack
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with offline_app_imports() as environment:
    import app as web
    import functions_authentication
    import functions_custom_pages as pages
    import functions_settings as settings_owner
    import functions_ui_mode
    import functions_ui_pages
    import route_frontend_v2

    settings = settings_owner.get_settings()
    settings.update({"enable_custom_pages": True})
    web.app.config.update(TESTING=True)

    # ---- Where the hook sits among the app-level hooks ----------------------------------------
    hooks = [function.__name__ for function in web.app.before_request_funcs[None]]
    check("redirect_classic_pages_to_modern_ui" in hooks, "the hook is not registered: " + str(hooks))
    at = hooks.index("redirect_classic_pages_to_modern_ui")
    check(
        hooks.index("answer_cors_preflight_for_allowed_origins") < hooks.index("enforce_same_origin_for_state_changing_requests")
        < at < hooks.index("enforce_terms_of_use") < hooks.index("enforce_idle_session_timeout"),
        "the redirect must run after the CORS and same-origin hooks and ahead of the terms and idle-timeout hooks: " + str(hooks),
    )

    # The classic pages answer with a marker, so a request that is not redirected is easy to tell.
    for endpoint in ("public_app.index", "frontend_chats.chats", "frontend_profile.profile",
                     "frontend_group_workspaces.group_workspaces", "frontend_notifications.notifications",
                     "frontend_workspace.workspace", "custom_pages.custom_page", "custom_pages.custom_page_html_alias"):
        web.app.view_functions[endpoint] = lambda **kwargs: "classic page"

    def leaves_for_v2(response):
        return response.status_code == 302 and response.headers.get("Location", "").startswith("/v2")

    def static_page(slug, **overrides):
        page = {
            "id": slug, "slug": slug, "title": f"Page {slug}", "description": "", "enabled": True,
            "entry_type": "static", "access_level": "app_user", "nav_label": slug.title(),
            "nav_icon": "bi-file-earmark-text", "nav_order": 100, "roles": [], "show_in_nav": True,
            "open_in_new_tab": False, "render_jinja": False, "html_file": "request-access.html",
            "css_files": [], "js_files": [], "asset_files": [], "json_files": [], "source": "cosmos",
        }
        page.update(overrides)
        return page

    class Plain:
        supports_embed = False

        def render(self, context):
            return "plain"

    plain_python = static_page("pyplain", entry_type="python", source="python", html_file="")
    plain_python["extension"] = Plain()
    statics = [
        static_page("handbook"),
        static_page("newtab", open_in_new_tab=True),
        static_page("auth-page", access_level="authenticated"),
        static_page("hidden", show_in_nav=False),
    ]
    pythons = {"pyplain": plain_python}
    bundle = {"present": True}
    warnings_written = []

    def client_for(roles, base_url=None):
        client = web.app.test_client()
        if roles is not None:
            kwargs = {"base_url": base_url} if base_url else {}
            with client.session_transaction(**kwargs) as user_session:
                user_session["user"] = {"oid": "redirect-user", "roles": list(roles), "name": "Redirect User"}
        return client

    html = {"Accept": "text/html"}
    modern = patch.object(functions_ui_mode, "get_ui_mode", return_value=functions_ui_mode.UI_MODE_MODERN)

    with ExitStack() as patches:
        patches.enter_context(patch.object(web, "get_request_settings", return_value=settings))
        patches.enter_context(patch.object(web, "get_custom_pages_nav", return_value=[]))
        # A first request from a new user would otherwise ask Microsoft Graph for a profile photo.
        patches.enter_context(patch.object(functions_authentication, "get_user_profile_image", return_value=None))
        patches.enter_context(patch.object(settings_owner, "get_user_ui_settings", return_value={"id": "u", "settings": {}}))
        patches.enter_context(patch.object(route_frontend_v2, "is_v2_bundle_available", lambda: bundle["present"]))
        patches.enter_context(patch.object(functions_ui_pages, "_log_bundle_missing", lambda: warnings_written.append("warned")))
        patches.enter_context(patch.object(pages, "list_cosmos_custom_pages", return_value=statics))
        patches.enter_context(patch.object(pages, "discover_python_custom_pages", return_value=pythons))
        # The real navigation builder, uncached, over the doubled catalog.
        patches.enter_context(patch.object(pages, "get_custom_pages_nav", side_effect=lambda current: pages._build_custom_pages_nav(current)))
        functions_ui_pages.reset_bundle_warning_throttle()

        user = client_for(["User"])

        # ---- Explicit legacy default: nothing is redirected ---------------------------------------
        settings["ui_default_mode"] = "classic"
        check(functions_ui_mode.get_ui_mode(settings, {}) == "classic", "explicit legacy default")
        for path in ("/chats?conversationId=x", "/profile?tab=feedback", "/group_workspaces", "/notifications", "/custom/handbook", "/"):
            response = user.get(path, headers=html)
            check(response.status_code == 200 and response.get_data(as_text=True) == "classic page", path + " changed in classic mode: " + str(response.status_code))
        check(warnings_written == [], "classic mode must not warn about the bundle")

        # ---- The documented examples, in the modern interface ----------------------------------------
        with modern:
            def redirected(client, path, **headers):
                response = client.get(path, headers={**html, **headers})
                check(response.status_code == 302, path + " was not redirected: " + str(response.status_code))
                return response

            response = redirected(user, "/chats?conversationId=x")
            check(response.headers["Location"] == "/v2/chat?conversationId=x", "chat: " + response.headers["Location"])
            check(response.headers["Cache-Control"] == "no-store", "the redirect must not be cacheable")
            check(redirected(user, "/profile?tab=feedback").headers["Location"] == "/v2/settings?tab=feedback", "profile feedback tab")
            check(redirected(user, "/group_workspaces").headers["Location"] == "/v2/groups", "group workspaces")
            check(redirected(user, "/").headers["Location"] == "/v2", "home")
            check(redirected(user, "/notifications").headers["Location"] == "/v2/notifications", "notifications")
            head = user.head("/chats?conversationId=x", headers=html)
            check(head.status_code == 302 and head.headers["Location"] == "/v2/chat?conversationId=x", "HEAD")

            # The caller names a host; the answer never does.
            hostile = client_for(["User"], "http://evil.example").get(
                "/chats?conversationId=x", base_url="http://evil.example",
                headers={**html, "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https", "Referer": "https://evil.example/"},
            )
            check(hostile.status_code == 302, "the spoofed-host request must still be redirected: " + str(hostile.status_code))
            check(hostile.headers["Location"] == "/v2/chat?conversationId=x", "echoed a host: " + hostile.headers["Location"])

            # ---- What it leaves alone ----------------------------------------------------------------
            for path in ("/chats?ui=classic", "/?ui=classic", "/chats?conversationId=x&ui=classic"):
                response = user.get(path, headers=html)
                check(response.status_code == 200 and response.get_data(as_text=True) == "classic page", path + " is the escape hatch and must reach the classic page")
            check(not leaves_for_v2(user.post("/chats", headers=html)), "a form post must not be redirected")
            for extra in ({"Accept": "application/json"}, {"X-Requested-With": "XMLHttpRequest"},
                          {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Mode": "navigate"}, {"Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors"}):
                response = user.get("/chats?conversationId=x", headers={**html, **extra})
                check(response.get_data(as_text=True) == "classic page", str(extra) + " must be served the classic page")
            api = user.get("/api/does-not-exist", headers=html)
            check(api.status_code == 404 and not leaves_for_v2(api), "/api must not be redirected")
            check(user.get("/static/css/bootstrap.min.css", headers=html).status_code == 200, "/static must not be redirected")
            check(not leaves_for_v2(client_for(None).get("/chats", headers=html)), "a signed-out visitor goes to sign in, not to V2")
            check(not leaves_for_v2(client_for(None).get("/", headers=html)), "a signed-out visitor stays on the landing page")
            for path in ("/chats", "/notifications", "/", "/terms-of-use"):
                check(not leaves_for_v2(client_for([]).get(path, headers=html)), "a user without the application role must stay out of V2: " + path)

            # ---- Custom pages: only what V2 can host -------------------------------------------------
            check(redirected(user, "/custom/handbook").headers["Location"] == "/v2/custom/handbook", "a hostable custom page")
            check(redirected(user, "/custom/handbook.html").headers["Location"] == "/v2/custom/handbook", "the .html alias")
            for path in ("/custom/handbook?embed=1", "/custom/newtab", "/custom/pyplain", "/custom/auth-page", "/custom/hidden", "/custom/unknown"):
                response = user.get(path, headers=html)
                check(response.status_code == 200 and response.get_data(as_text=True) == "classic page", path + " must stay classic: " + str(response.status_code))

            # ---- The Terms of Use gate sees the V2 request, not the classic one ----------------------
            settings.update({"enable_terms_of_use": True, "terms_of_use_message": "Please accept.", "terms_of_use_frequency": "once"})
            first = redirected(user, "/chats?conversationId=abc")
            check(first.headers["Location"] == "/v2/chat?conversationId=abc", "the hook must answer before the terms gate: " + first.headers["Location"])
            second = user.get(first.headers["Location"], headers=html)
            check(second.status_code == 302 and second.headers["Location"].startswith("/v2/terms-of-use?next="),
                  "the terms gate must send the V2 page to the V2 terms page: " + str(second.headers.get("Location")))
            check(redirected(user, "/terms-of-use?next=%2Fchats").headers["Location"] == "/v2/terms-of-use?next=%2Fchats",
                  "a signed-in user is taken to the V2 terms page")
            check(not leaves_for_v2(client_for(None).get("/terms-of-use", headers=html)), "before sign-in the classic terms page is served")

        # The same request in the classic interface still goes to the classic terms page: nothing moved.
        classic_terms = user.get("/chats?conversationId=abc", headers=html)
        check(classic_terms.status_code == 302 and classic_terms.headers["Location"].startswith("/terms-of-use?next="),
              "classic mode must keep sending an unaccepted user to the classic terms page: " + str(classic_terms.headers.get("Location")))
        settings.update({"enable_terms_of_use": False})

        # ---- Missing bundle: classic, never a 503 loop, one warning ------------------------------------
        with modern:
            bundle["present"] = False
            for path in ("/chats?conversationId=x", "/notifications", "/", "/chats"):
                response = user.get(path, headers=html)
                check(response.status_code == 200 and response.get_data(as_text=True) == "classic page", path + " must stay classic without the bundle")
            check(warnings_written == ["warned"], "exactly one warning per process: " + str(warnings_written))
            bundle["present"] = True
            check(redirected(user, "/chats?conversationId=x").status_code == 302, "the bundle appearing needs no restart")

    check(not environment.network_attempts, "the probe attempted external I/O")
print("PASS: classic to V2 redirect on the real web app")
'''


def run_probe(probe, env_overrides=None):
    environment = {**os.environ, **(env_overrides or {})}
    process = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(APP_ROOT), str(TESTS_ROOT)],
        capture_output=True, text=True, timeout=420, check=False, env=environment,
    )
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS:" in process.stdout, process.stdout[-3000:]


def test_real_web_app_hook_order_examples_and_fallback():
    run_probe(APP_PROBE)


def test_app_source_wires_one_thin_hook_ahead_of_the_terms_gate():
    source = (APP_ROOT / "app.py").read_text(encoding="utf-8")
    assert "from functions_ui_redirect import has_classic_escape, redirect_classic_page_to_modern_ui" in source
    hook = source.index("@app.before_request\ndef redirect_classic_pages_to_modern_ui():")
    terms = source.index("@app.before_request\ndef enforce_terms_of_use():")
    idle = source.index("@app.before_request\ndef enforce_idle_session_timeout():")
    csrf = source.index("@app.before_request\ndef enforce_same_origin_for_state_changing_requests():")
    assert csrf < hook < terms < idle
    body = source[hook:terms]
    assert body.count("\n    return redirect_classic_page_to_modern_ui(get_request_settings)") == 1
    assert len([line for line in body.splitlines() if line.startswith("    ") and not line.lstrip().startswith(('"""', "#"))]) == 1, (
        "The hook in app.py stays a one-line call; the rules live in functions_ui_redirect.py"
    )
    # The landing page asks the same shared predicate as the hook, and honours the escape hatch too.
    assert "classic_escape = has_classic_escape(request.query_string) and allows_classic_escape(settings)" in source
    assert "if not classic_escape and is_modern_ui_available(settings):" in source
    assert "is_v2_bundle_available" not in source


def test_the_decision_module_does_not_reach_for_settings_cosmos_or_the_v2_routes_at_load_time():
    source = (APP_ROOT / "functions_ui_redirect.py").read_text(encoding="utf-8")
    imported = {name.split(".")[0] for name in re.findall(r"^(?:from|import)\s+([\w.]+)", source, re.MULTILINE)}
    assert imported - set(sys.stdlib_module_names) == {"flask", "functions_ui_mode", "functions_ui_pages", "ui_routing"}, imported
    assert source.startswith("# functions_ui_redirect.py")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
