#!/usr/bin/env python3
# test_custom_pages_embed_mode.py
"""
Functional test for custom pages shown inside V2 (embed mode).
Version: 0.261.448
Implemented in: 0.261.448

The V2 interface shows a custom page by framing a chrome-less, same-origin copy of it:
`/custom/<slug>?embed=1`. The classic route must not change, and the one relaxation the framing
needs, `X-Frame-Options: SAMEORIGIN` instead of `DENY`, must reach that embed document and
nothing else.

Real modules run. The templates are rendered by a minimal Flask app, and the route, the security
headers, the navigation payload and the Python extension contract run in fresh processes that
import the real web app with network access blocked. Only external I/O is doubled.

Covers: the embed document has none of the classic chrome and carries the page's declared CSS and
JavaScript, its HTML, local assets only and the theme and ready messages the V2 host relies on;
`X-Frame-Options` is `SAMEORIGIN` on a flagged embed response and `DENY` everywhere else, a
Content-Security-Policy that never changes, and nothing at all under Teams SSO; a Python extension
receives the embed flag only when it opted in with `supports_embed`; a page open to any signed-in
user is served chrome-less as a full page in the modern interface and unchanged in the classic
one; an unsafe slug, a missing page, a forbidden page and a disabled feature are still refused; the
V2 navigation payload says which pages are embeddable; and the address behind V2's "Open in a new
tab" is the chrome-less document, which the classic-to-V2 redirect never touches, while every other
link V2 draws to a classic custom page address is one that redirect leaves alone.
"""

import ast
import importlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from flask import Flask, render_template_string, session

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(TESTS))

from test_support.app_stubs import stubbed_config  # noqa: E402
from test_support.custom_page_embed_render import (  # noqa: E402
    build_embed_app,
    render_embed_shell,
    static_page,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402

CLASSIC_CHROME = (
    "custom-page-hero",
    'id="custom-page-title"',
    "navigation.js",
    "sidebar.js",
    "notifications.js",
    "idle-logout-warning.js",
    "dark-mode.js",
    "user-agreement.js",
    "idleTimeoutWarningModal",
)
PAGE_HTML = '<section class="x"><h1 id="page-heading">Hello</h1></section>'


def _chrome_in(body):
    return [marker for marker in CLASSIC_CHROME if marker in body]


# ---------------------------------------------------------------------------------------
# The embed templates, rendered for real
# ---------------------------------------------------------------------------------------


def test_the_version_carries_the_embed_mode():
    assert_app_version_at_least("0.261.448")


def test_embed_document_has_no_classic_chrome_and_carries_the_page():
    app = build_embed_app()
    page = static_page("probe", css_files=["probe.css", "second.css"], js_files=["probe.js"])
    body = render_embed_shell(app, page, PAGE_HTML)

    assert not _chrome_in(body), f"The embed document must not carry the classic shell: {_chrome_in(body)}"
    assert "<nav" not in body and "navbar" not in body
    assert body.lstrip().startswith("<!DOCTYPE html>"), "Nothing may precede the doctype"

    # The page's own HTML, the stylesheets in declared order, and its module scripts.
    assert PAGE_HTML in body
    css = [
        "/custom/assets/probe/css/probe.css",
        "/custom/assets/probe/css/second.css",
    ]
    assert all(url in body for url in css) and body.index(css[0]) < body.index(css[1])
    assert '<script type="module" src="/custom/assets/probe/js/probe.js"></script>' in body
    assert body.index(PAGE_HTML) < body.index("/custom/assets/probe/js/probe.js"), (
        "Module scripts run after the markup they query"
    )
    assert 'data-custom-page-slug="probe"' in body
    assert "<title>Probe page</title>" in body

    # What typical pages assume is there, and all of it is local.
    for local in (
        "/static/css/bootstrap.min.css",
        "/static/css/bootstrap-icons.css",
        "/static/js/chat/jquery.min.js",
        "/static/js/chat/bootstrap.bundle.min.js",
        "/static/js/toast.js",
    ):
        assert local in body, local
    assert 'id="toast-container"' in body

    remote = re.findall(r'(?:src|href)\s*=\s*"(?:https?:)?//[^"]*"', body)
    assert not remote, f"The embed document must load nothing from a remote host: {remote}"


def test_the_classic_shell_is_unchanged_and_not_the_embed_shell():
    shell = (APP / "templates" / "custom_page_shell.html").read_text(encoding="utf-8")
    assert '{% extends "base.html" %}' in shell
    assert "custom-page-hero" in shell and "{{ custom_page_html | safe }}" in shell
    embed_shell = (APP / "templates" / "custom_page_embed_shell.html").read_text(encoding="utf-8")
    base = (APP / "templates" / "custom_page_embed_base.html").read_text(encoding="utf-8")
    assert '{% extends "custom_page_embed_base.html" %}' in embed_shell
    base_tags = re.sub(r"\{#.*?#\}", "", base, flags=re.DOTALL)
    assert "{% extends" not in base_tags, (
        "The embed base is a standalone document and must not extend the classic base"
    )
    assert "custom-page-hero" not in embed_shell and "custom-page-hero" not in base

    # The trusted HTML boundary is documented in the same way as in the classic shell.
    assert "xss-check: ignore" in embed_shell and "{{ custom_page_html | safe }}" in embed_shell


def test_standalone_bar_is_hidden_for_a_frame_and_names_the_way_back():
    app = build_embed_app()
    page = static_page("probe")

    framed = render_embed_shell(app, page, PAGE_HTML, standalone=False)
    assert 'class="custom-page-embed-bar d-none"' in framed
    standalone = render_embed_shell(app, page, PAGE_HTML, standalone=True)
    assert 'class="custom-page-embed-bar"' in standalone, (
        "A full page the server knows is standalone must show its bar without needing a script"
    )
    # Either way the script settles it from where the document really is.
    assert 'bar.classList.toggle("d-none", window.self !== window.top)' in standalone

    # Whoever can use V2 goes back there; whoever cannot has the home page instead.
    assert 'href="/v2"' in render_embed_shell(app, page, PAGE_HTML, standalone=True, roles=["User"])
    assert 'href="/v2"' in render_embed_shell(app, page, PAGE_HTML, standalone=True, roles=["Admin"])
    no_role = render_embed_shell(app, page, PAGE_HTML, standalone=True, roles=[])
    assert 'href="/"' in no_role and 'href="/v2"' not in no_role

    # Administrator text is escaped, not trusted.
    hostile = render_embed_shell(
        app,
        static_page("probe", title='<script>alert("t")</script>'),
        PAGE_HTML,
        standalone=True,
        app_settings={"app_title": '<img src=x onerror="alert(1)">'},
    )
    assert "<script>alert(" not in hostile and "<img src=x" not in hostile
    assert "&lt;script&gt;alert(" in hostile and "&lt;img src=x" in hostile


def test_theme_starts_from_the_saved_preference_and_follows_the_host():
    app = build_embed_app()
    page = static_page("probe")

    def theme(user_settings=None, app_settings=None):
        body = render_embed_shell(
            app, page, PAGE_HTML, user_settings=user_settings, app_settings=app_settings
        )
        return re.search(r'<html lang="en" data-bs-theme="(\w+)"', body).group(1)

    assert theme() == "light"
    assert theme({"settings": {"darkModeEnabled": True}}) == "dark"
    assert theme({"settings": {"darkModeEnabled": False}}, {"enable_dark_mode_default": True}) == "light"
    assert theme({"settings": {}}, {"enable_dark_mode_default": True}) == "dark"

    body = render_embed_shell(app, page, PAGE_HTML)
    # Stored choice before first paint: the V2 key first, then the classic one.
    assert body.index('"simplechat.v2.theme"') < body.index('"simplechat-theme"')
    # The conversation with the host: a ready message to this origin only, and a theme message
    # accepted only from the parent window and this origin.
    assert '"simplechat-custom-page-ready"' in body
    assert "window.parent.postMessage(" in body and "window.location.origin" in body
    assert "event.origin !== window.location.origin || event.source !== window.parent" in body
    assert 'message.theme === "dark" || message.theme === "light"' in body


def test_a_python_template_can_extend_the_embed_base_with_the_classic_block_names():
    app = build_embed_app()
    template = (
        '{% extends "custom_page_embed_base.html" %}'
        '{% block head %}<link rel="stylesheet" href="/x.css" />{% endblock %}'
        '{% block content %}<p id="py-content">{{ greeting }}</p>{% endblock %}'
        '{% block scripts %}<script src="/x.js"></script>{% endblock %}'
    )
    with app.test_request_context("/custom/py"):
        session["user"] = {"roles": ["User"]}
        body = render_template_string(
            template, greeting="hi", app_settings={"app_title": "Contoso"}, user_settings={}
        )
    assert '<p id="py-content">hi</p>' in body
    assert '<link rel="stylesheet" href="/x.css" />' in body and '<script src="/x.js"></script>' in body
    assert "<title>Contoso</title>" in body, "The default title is the application title"
    assert not _chrome_in(body)


# ---------------------------------------------------------------------------------------
# functions_custom_pages: the embed contract, without the web app
# ---------------------------------------------------------------------------------------


@contextmanager
def custom_pages_module():
    """Import functions_custom_pages against a stub config, and forget it afterwards."""
    before = set(sys.modules)
    with stubbed_config(cosmos_custom_pages_container=object(), cosmos_settings_container=object()):
        try:
            yield importlib.import_module("functions_custom_pages")
        finally:
            for name in set(sys.modules) - before:
                module_file = getattr(sys.modules.get(name), "__file__", None) or ""
                if module_file.startswith(str(APP)):
                    sys.modules.pop(name, None)


def _python_page(supports_embed):
    from custom_page_extension import CustomPageExtension

    class Extension(CustomPageExtension):
        pass

    if supports_embed is not None:
        Extension.supports_embed = supports_embed
    return {
        "slug": "py", "entry_type": "python", "extension": Extension(), "enabled": True,
        "show_in_nav": True, "nav_label": "Py", "access_level": "app_user", "roles": [],
    }


def test_embeddable_is_true_for_static_pages_and_opted_in_python_pages_only():
    with custom_pages_module() as pages:
        assert pages.is_custom_page_embeddable({"entry_type": "static"}) is True
        assert pages.is_custom_page_embeddable({"slug": "legacy"}) is True
        assert pages.is_custom_page_embeddable(_python_page(None)) is False, "Opt-in, never opt-out"
        assert pages.is_custom_page_embeddable(_python_page(False)) is False
        assert pages.is_custom_page_embeddable(_python_page(True)) is True
        assert pages.is_custom_page_embeddable({"entry_type": "python"}) is False

    sys.path.insert(0, str(APP))
    from custom_page_extension import CustomPageExtension

    assert CustomPageExtension.supports_embed is False
    assert CustomPageExtension().supports_embed is False


def test_context_carries_the_embed_flag_without_the_extension_object():
    with custom_pages_module() as pages:
        app = Flask("probe")
        app.secret_key = "probe"
        page = _python_page(True)
        with app.test_request_context("/"):
            session["user"] = {"oid": "u", "roles": ["User"]}
            default = pages.build_custom_page_context(page, {"x": 1})
            embedded = pages.build_custom_page_context(page, {"x": 1}, embed=True)
        assert default["embed"] is False and embedded["embed"] is True
        assert "extension" not in default["page"] and embedded["roles"] == ["User"]


def test_navigation_items_say_whether_the_page_is_embeddable():
    with custom_pages_module() as pages:
        catalog = [
            {**_python_page(True), "slug": "opted", "nav_order": 20},
            {**_python_page(None), "slug": "plain", "nav_order": 30},
            {
                "slug": "handbook", "entry_type": "static", "enabled": True, "show_in_nav": True,
                "nav_label": "Handbook", "nav_order": 10, "access_level": "app_user", "roles": [],
                "open_in_new_tab": True,
            },
        ]
        app = build_embed_app()
        pages.list_custom_pages = lambda include_python=True: catalog
        with app.test_request_context("/"):
            session["user"] = {"roles": ["User"]}
            items = pages._build_custom_pages_nav({"enable_custom_pages": True})
    assert [(item["slug"], item["embeddable"]) for item in items] == [
        ("handbook", True), ("opted", True), ("plain", False),
    ]
    assert items[0]["open_in_new_tab"] is True, "A page's own new-tab choice is carried unchanged"


def test_navigation_cache_key_changes_with_the_item_shape():
    """Items cached before the field existed are never served to code that reads it."""
    with custom_pages_module() as pages:
        keys = []
        pages.get_shared_cache_entry = lambda namespace, key, redis_client=None: keys.append(key)
        pages.set_shared_cache_entry = lambda *args, **kwargs: None
        pages._get_shared_cache_redis_client = lambda: None
        pages._get_custom_pages_cache_version = lambda: 1
        pages._build_custom_pages_nav = lambda settings: []
        app = Flask("probe")
        app.secret_key = "probe"
        with app.test_request_context("/"):
            session["user"] = {"roles": ["User"]}
            pages.get_custom_pages_nav({"enable_custom_pages": True})
        legacy = "nav:" + pages._stable_hash({"roles": ["User"], "enabled": True})
        assert keys and keys[0] != legacy, "The navigation cache key must change with the schema"
        assert keys[0] == "nav:" + pages._stable_hash(
            {"roles": ["User"], "enabled": True, "schema": pages.CUSTOM_PAGES_NAV_SCHEMA_VERSION}
        )


def test_framing_flag_is_scoped_to_one_request():
    with custom_pages_module() as pages:
        assert pages.is_same_origin_framing_allowed() is False, "No app context, no framing"
        app = Flask("probe")
        with app.app_context():
            assert pages.is_same_origin_framing_allowed() is False
            pages.allow_same_origin_framing()
            assert pages.is_same_origin_framing_allowed() is True
        with app.app_context():
            assert pages.is_same_origin_framing_allowed() is False, "It must not outlive the request"


def test_the_ui_fixture_sends_the_content_security_policy_the_application_sends():
    """The browser test is only as good as the headers it serves; hold them to config.py."""
    fixture = (ROOT / "ui_tests" / "test_v2_custom_pages.py").read_text(encoding="utf-8")
    csp = next(
        ast.literal_eval(node.value)
        for node in ast.parse(fixture).body
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "PRODUCTION_CSP" for t in node.targets)
    )
    config = (APP / "config.py").read_text(encoding="utf-8")
    directives = [directive.strip() for directive in csp.split(";") if directive.strip()]
    assert len(directives) >= 9
    for directive in directives:
        assert directive in config, f"config.py no longer sends: {directive}"
    assert "frame-ancestors 'self'" in csp


# ---------------------------------------------------------------------------------------
# The real web app, in fresh processes with the network blocked
# ---------------------------------------------------------------------------------------

APP_PROBE = r'''
import re
import sys
from contextlib import ExitStack
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports


def check(condition, message):
    if not condition:
        raise AssertionError(message)


CLASSIC_CHROME = (
    "custom-page-hero", 'id="custom-page-title"', "navigation.js", "sidebar.js",
    "notifications.js", "idle-logout-warning.js", "dark-mode.js", "idleTimeoutWarningModal",
)


def chrome_in(body):
    return [marker for marker in CLASSIC_CHROME if marker in body]


with offline_app_imports() as environment:
    import app as web
    import functions_custom_pages as pages
    import functions_settings as settings_owner
    import functions_ui_mode
    import functions_ui_pages
    import route_backend_v2
    import route_custom_pages as route
    from custom_page_extension import CustomPageExtension
    from flask import make_response, render_template_string

    settings = settings_owner.get_settings()
    settings.update({"enable_custom_pages": True})
    web.app.config.update(TESTING=True)

    def static_page(slug, **overrides):
        page = {
            "id": slug, "slug": slug, "title": f"Page {slug}", "description": "", "enabled": True,
            "entry_type": "static", "access_level": "app_user", "nav_label": slug.title(),
            "nav_icon": "bi-file-earmark-text", "nav_order": 100, "roles": [], "show_in_nav": True,
            "open_in_new_tab": False, "render_jinja": False, "html_file": "request-access.html",
            "css_files": ["request-access.css"], "js_files": ["probe.js"], "asset_files": [],
            "json_files": [], "source": "cosmos",
        }
        page.update(overrides)
        return page

    rendered = []

    class Opted(CustomPageExtension):
        supports_embed = True

        def render(self, context):
            rendered.append(("pyopt", context["embed"]))
            return render_template_string(
                '{% extends "custom_page_embed_base.html" if embed else "custom_page_shell.html" %}'
                '{% block content %}<p id="py-content">opted</p>{% endblock %}',
                embed=context["embed"], app_settings=context["settings"], custom_page=context["page"],
                custom_page_html="", user_settings={},
            )

    class Plain(CustomPageExtension):
        def render(self, context):
            rendered.append(("pyplain", context["embed"]))
            return "plain python page"

    def python_page(slug, extension):
        page = static_page(slug, entry_type="python", source="python", html_file="", css_files=[], js_files=[])
        page["extension"] = extension
        return page

    statics = [
        static_page("probe"),
        static_page("restricted", roles=["Nobody"]),
        static_page("switched-off", enabled=False),
        static_page("auth-page", access_level="authenticated"),
    ]
    pythons = {"pyopt": python_page("pyopt", Opted()), "pyplain": python_page("pyplain", Plain())}

    def client_for(roles):
        client = web.app.test_client()
        with client.session_transaction() as user_session:
            user_session["user"] = {
                "oid": "embed-user", "roles": list(roles), "name": "Embed User",
                "preferred_username": "embed@example.test",
            }
        return client

    with ExitStack() as patches:
        patches.enter_context(patch.object(web, "get_request_settings", return_value=settings))
        patches.enter_context(patch.object(web, "get_custom_pages_nav", return_value=[]))
        patches.enter_context(patch.object(route, "get_settings", return_value=settings))
        patches.enter_context(patch.object(settings_owner, "get_user_ui_settings", return_value={"id": "u", "settings": {}}))
        # The real get_custom_page, with its own slug validation, over a doubled catalog.
        patches.enter_context(patch.object(pages, "list_cosmos_custom_pages", return_value=statics))
        patches.enter_context(patch.object(pages, "discover_python_custom_pages", return_value=pythons))

        user = client_for(["User"])

        # ---- The classic route is unchanged -------------------------------------------------
        classic = user.get("/custom/probe")
        classic_body = classic.get_data(as_text=True)
        check(classic.status_code == 200, "classic page no longer renders")
        check(classic.headers.get("X-Frame-Options") == "DENY", "classic page must stay DENY")
        for marker in ("custom-page-hero", 'id="custom-page-title"', "navigation.js"):
            check(marker in classic_body, "classic shell lost " + marker)
        csp = classic.headers["Content-Security-Policy"]
        check("frame-ancestors 'self'" in csp, "CSP lost frame-ancestors")
        alias = user.get("/custom/probe.html")
        check(alias.status_code == 200 and alias.headers.get("X-Frame-Options") == "DENY", "the .html alias changed")
        check("custom-page-hero" in alias.get_data(as_text=True), "the .html alias lost the classic shell")

        # ---- The embed document -------------------------------------------------------------
        embed = user.get("/custom/probe?embed=1")
        body = embed.get_data(as_text=True)
        check(embed.status_code == 200, "embed did not render")
        check(embed.headers.get("X-Frame-Options") == "SAMEORIGIN", "embed must be frameable by this origin")
        check(embed.headers["Content-Security-Policy"] == csp, "the CSP must not change for the embed document")
        check(not chrome_in(body), "embed carries classic chrome: " + str(chrome_in(body)))
        check("Request access to SimpleChat" in body, "embed lost the page HTML")
        check("/custom/assets/probe/css/request-access.css" in body, "embed lost the declared CSS")
        check('<script type="module" src="/custom/assets/probe/js/probe.js"></script>' in body, "embed lost the declared JS")
        check("custom-page-embed-bar d-none" in body, "a frame request must hide the standalone bar")
        check(not re.findall(r'(?:src|href)\s*=\s*"(?:https?:)?//', body), "embed loads a remote asset")
        framed_again = user.get("/custom/probe?embed=1&x=2")
        check(framed_again.headers.get("X-Frame-Options") == "SAMEORIGIN", "extra parameters changed embed mode")
        framed_alias = user.get("/custom/probe.html?embed=1")
        check(framed_alias.status_code == 200 and framed_alias.headers.get("X-Frame-Options") == "SAMEORIGIN", "the .html alias must support embed mode")
        check(not chrome_in(framed_alias.get_data(as_text=True)), "the .html alias embed carries classic chrome")

        # Only exactly embed=1 asks for it.
        for query in ("embed=0", "embed=true", "embed=", "embed=yes", "embedded=1"):
            other = user.get("/custom/probe?" + query)
            check(other.headers.get("X-Frame-Options") == "DENY", query + " must stay DENY")
            check("custom-page-hero" in other.get_data(as_text=True), query + " must be the classic page")

        # ---- Everything else keeps DENY -------------------------------------------------------
        asset = user.get("/custom/assets/probe/css/request-access.css?embed=1")
        check(asset.status_code == 200 and asset.headers.get("X-Frame-Options") == "DENY", "an asset must stay DENY")
        check(user.get("/static/css/bootstrap.min.css").headers.get("X-Frame-Options") == "DENY", "static must stay DENY")
        check(user.get("/no-such-page?embed=1").headers.get("X-Frame-Options") == "DENY", "a 404 elsewhere must stay DENY")

        # ---- Refusals keep their behaviour, and are never frameable -------------------------
        for path, status, text in (
            ("/custom/unknown?embed=1", 404, "Not Found"),
            ("/custom/switched-off?embed=1", 404, "Not Found"),
            ("/custom/restricted?embed=1", 403, "Forbidden"),
            ("/custom/..%2F..%2Fsecret?embed=1", 404, None),
            ("/custom/Bad_Slug?embed=1", 404, "Not Found"),
            ("/custom/%2e%2e?embed=1", 404, None),
        ):
            refused = user.get(path)
            check(refused.status_code == status, path + " answered " + str(refused.status_code))
            check(refused.headers.get("X-Frame-Options") == "DENY", path + " must stay DENY")
            check("Request access to SimpleChat" not in refused.get_data(as_text=True), path + " leaked a page")
            if text:
                check(refused.get_data(as_text=True) == text, path + " changed its body")
        with patch.object(route, "get_settings", return_value={**settings, "enable_custom_pages": False}):
            off = user.get("/custom/probe?embed=1")
            check(off.status_code == 404 and off.headers.get("X-Frame-Options") == "DENY", "a disabled feature must fail closed")
        check(web.app.test_client().get("/custom/probe?embed=1").status_code == 302, "an anonymous request must still be sent to sign in")

        # ---- Python-backed pages --------------------------------------------------------------
        opted = user.get("/custom/pyopt?embed=1")
        check(rendered[-1] == ("pyopt", True), "an opted-in extension must be told it is embedded")
        check(opted.headers.get("X-Frame-Options") == "SAMEORIGIN", "an opted-in embed must be frameable")
        opted_body = opted.get_data(as_text=True)
        check('id="py-content"' in opted_body and not chrome_in(opted_body), "the extension did not render chrome-less")
        user.get("/custom/pyopt")
        check(rendered[-1] == ("pyopt", False), "a classic request must not be told it is embedded")
        check(user.get("/custom/pyopt").headers.get("X-Frame-Options") == "DENY", "a classic python page must stay DENY")
        plain = user.get("/custom/pyplain?embed=1")
        check(rendered[-1] == ("pyplain", False), "an extension that did not opt in must never be told to embed")
        check(plain.headers.get("X-Frame-Options") == "DENY", "a page that did not opt in must never be frameable")
        check(plain.get_data(as_text=True) == "plain python page", "the page's own response changed")

        # ---- The documented Python example opts in and works in both interfaces -----------------
        import importlib.util
        import pathlib
        import shutil
        import tempfile

        example_source = pathlib.Path(sys.argv[1]).parents[1] / "docs" / "how-to" / "custom_pages_examples" / "python-jinja-api"
        with tempfile.TemporaryDirectory() as folder:
            deployed = pathlib.Path(folder)
            (deployed / "python").mkdir()
            (deployed / "html").mkdir()
            shutil.copy(example_source / "example_python_dashboard.py", deployed / "python")
            shutil.copy(example_source / "example-python-dashboard.html", deployed / "html")
            spec = importlib.util.spec_from_file_location("example_python_dashboard", deployed / "python" / "example_python_dashboard.py")
            example_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(example_module)
            example = example_module.ExamplePythonDashboard()
            check(example.supports_embed is True, "the documented example must opt in to V2")
            example_page = python_page("example-python-dashboard", example)
            example_page.update(css_files=example.metadata["css_files"], js_files=example.metadata["js_files"])
            pythons["example-python-dashboard"] = example_page

            example_embed = user.get("/custom/example-python-dashboard?embed=1")
            example_body = example_embed.get_data(as_text=True)
            check(example_embed.status_code == 200, "the documented example did not render in embed mode")
            check(example_embed.headers.get("X-Frame-Options") == "SAMEORIGIN", "the documented example must be frameable")
            check("data-python-example" in example_body and not chrome_in(example_body), "the example must render chrome-less in V2")
            example_classic = user.get("/custom/example-python-dashboard")
            check(example_classic.status_code == 200 and "navigation.js" in example_classic.get_data(as_text=True),
                  "the documented example must still render the classic shell")
            check(example_classic.headers.get("X-Frame-Options") == "DENY", "the classic example must stay DENY")
            api = user.get("/api/custom/example-python-dashboard/status")
            check(api.status_code == 200 and api.get_json()["healthy"] is True, "the documented example's API stopped working")
            del pythons["example-python-dashboard"]

        # ---- Pages open to any signed-in user ---------------------------------------------------
        nobody = client_for([])
        classic_auth = nobody.get("/custom/auth-page")
        check(classic_auth.status_code == 200 and "custom-page-hero" in classic_auth.get_data(as_text=True),
              "in the classic interface an any-signed-in-user page must be unchanged")
        check(classic_auth.headers.get("X-Frame-Options") == "DENY", "classic any-user page must stay DENY")

        with patch.object(functions_ui_mode, "get_ui_mode", return_value=functions_ui_mode.UI_MODE_MODERN):
            standalone = nobody.get("/custom/auth-page")
            standalone_body = standalone.get_data(as_text=True)
            check(standalone.status_code == 200, "the modern page did not render for a user without the app role")
            check(not chrome_in(standalone_body), "the modern page must be chrome-less: " + str(chrome_in(standalone_body)))
            check("Request access to SimpleChat" in standalone_body, "the modern page lost its content")
            check('class="custom-page-embed-bar"' in standalone_body, "the standalone bar must be visible without a script")
            check('href="/"' in standalone_body and 'href="/v2"' not in standalone_body, "without the app role the way back is home")
            check(standalone.headers.get("X-Frame-Options") == "DENY", "a standalone page is not meant to be framed")
            check('href="/v2"' in user.get("/custom/auth-page").get_data(as_text=True), "with the app role the way back is V2")
            framed_auth = user.get("/custom/auth-page?embed=1")
            check(framed_auth.headers.get("X-Frame-Options") == "SAMEORIGIN" and "custom-page-embed-bar d-none" in framed_auth.get_data(as_text=True),
                  "an explicit embed request is still the framed variant")
            # The route leaves a page for app users alone in modern mode: with the V2 bundle missing, or with
            # the ui=classic escape. With the bundle, the redirect hook sends it to the page V2 hosts.
            with patch.object(functions_ui_pages, "is_v2_bundle_ready", return_value=False):
                check("custom-page-hero" in user.get("/custom/probe").get_data(as_text=True), "an app-user page changed in modern mode")
                check(user.get("/custom/pyopt").headers.get("X-Frame-Options") == "DENY", "a python page must stay DENY without embed=1")
            with patch.object(functions_ui_pages, "is_v2_bundle_ready", return_value=True):
                hosted = user.get("/custom/probe")
                check(hosted.status_code == 302 and hosted.headers.get("Location") == "/v2/custom/probe",
                      "in modern mode with the V2 bundle an app-user page must open inside V2")
                # The address behind V2's "Open in a new tab" is served as the chrome-less page, not sent back to V2.
                new_tab = user.get("/custom/probe?embed=1")
                new_tab_body = new_tab.get_data(as_text=True)
                check(new_tab.status_code == 200 and "Location" not in new_tab.headers,
                      "the new-tab address was redirected: " + str(new_tab.status_code))
                check(not chrome_in(new_tab_body) and "data-custom-page-embed-bar" in new_tab_body,
                      "the new-tab address must serve the chrome-less page with its slim bar")
                check(new_tab.headers.get("X-Frame-Options") == "SAMEORIGIN", "the new-tab address is the framed variant")
                check("custom-page-hero" in user.get("/custom/probe?ui=classic").get_data(as_text=True),
                      "ui=classic must reach the classic page")

        # ---- The navigation payload -------------------------------------------------------------
        # The cached wrapper is covered on its own; here the real item builder feeds the real payload.
        with web.app.test_request_context("/"):
            from flask import session as flask_session
            flask_session["user"] = {"roles": ["User"]}
            nav_items = pages._build_custom_pages_nav(settings)
            with patch.object(route_backend_v2, "get_custom_pages_nav", side_effect=lambda current: nav_items):
                payload = route_backend_v2._build_navigation(settings, ["User"])
        flags = {item["slug"]: item["embeddable"] for item in nav_items}
        check(flags == {"probe": True, "pyopt": True, "pyplain": False, "auth-page": True}, "nav flags: " + str(flags))
        sent = {item["slug"]: item for item in payload["custom_pages"]["items"]}
        check(all(set(item) == {"slug", "label", "icon", "url", "open_in_new_tab", "embeddable"} for item in sent.values()),
              "the payload must carry only the sanitized fields")
        check(sent["pyopt"]["embeddable"] is True and sent["pyplain"]["embeddable"] is False, "bootstrap lost the flag")
        with patch.object(route_backend_v2, "get_custom_pages_nav", return_value=[{"slug": "old", "url": "/custom/old", "label": "Old"}]):
            old = route_backend_v2._build_navigation(settings, ["User"])["custom_pages"]["items"][0]
        check(old["embeddable"] is False, "an item without the flag must read as not embeddable")

        # ---- The header function itself ---------------------------------------------------------
        with web.app.test_request_context("/custom/x?embed=1"):
            unflagged = web.add_security_headers(make_response("x"))
            pages.allow_same_origin_framing()
            flagged = web.add_security_headers(make_response("x"))
        check(unflagged.headers["X-Frame-Options"] == "DENY", "unflagged responses must be DENY")
        check(flagged.headers["X-Frame-Options"] == "SAMEORIGIN", "flagged responses must be SAMEORIGIN")
        check(flagged.headers["Content-Security-Policy"] == unflagged.headers["Content-Security-Policy"], "the CSP must not depend on the flag")
        check(flagged.headers["X-Content-Type-Options"] == "nosniff", "other security headers must survive")

    check(not environment.network_attempts, "the probe attempted external I/O")
print("PASS: embed mode on the real web app")
'''

TEAMS_PROBE = r'''
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with offline_app_imports() as environment:
    import app as web
    import config
    import functions_custom_pages as pages
    from flask import make_response

    check(config.ENABLE_TEAMS_SSO is True, "the probe did not run with Teams SSO enabled")
    check("X-Frame-Options" not in config.SECURITY_HEADERS, "Teams SSO deployments send no X-Frame-Options")
    with web.app.test_request_context("/custom/x?embed=1"):
        ordinary = web.add_security_headers(make_response("x"))
        pages.allow_same_origin_framing()
        embed = web.add_security_headers(make_response("x"))
    for name, response in (("ordinary", ordinary), ("embed", embed)):
        check("X-Frame-Options" not in response.headers, name + " response must not gain an X-Frame-Options under Teams SSO")
        csp = response.headers["Content-Security-Policy"]
        check("frame-ancestors 'self' https://teams.microsoft.com" in csp, name + " lost the Teams frame ancestors: " + csp)
    check(embed.headers["Content-Security-Policy"] == ordinary.headers["Content-Security-Policy"], "the CSP must not depend on the flag")
    check(not environment.network_attempts, "the probe attempted external I/O")
print("PASS: Teams SSO framing is untouched")
'''


def run_probe(probe, env_overrides=None):
    environment = {**os.environ, **(env_overrides or {})}
    process = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(APP), str(TESTS)],
        capture_output=True, text=True, timeout=300, check=False, env=environment,
    )
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS:" in process.stdout, process.stdout[-3000:]


def test_real_web_app_embed_route_headers_context_and_navigation():
    run_probe(APP_PROBE)


def test_teams_sso_framing_headers_are_untouched():
    run_probe(TEAMS_PROBE, {"ENABLE_TEAMS_SSO": "true"})


# ---------------------------------------------------------------------------------------
# V2 logic (TypeScript executed in Node)
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    ["test_v2_custom_page_host_logic.mjs", "test_v2_navigation_groups_logic.mjs"],
)
def test_v2_embed_logic_runs_in_node(script):
    try:
        result = subprocess.run(
            ["node", str(TESTS / script)], cwd=str(ROOT), capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        pytest.skip("Node is not installed; it runs the V2 TypeScript directly")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime checks passed" in result.stdout


# ---------------------------------------------------------------------------------------
# V2's links to a tab of its own, against the real classic-to-V2 redirect
# ---------------------------------------------------------------------------------------
#
# Once the modern interface is selected the redirect sends `/custom/<slug>` for a page V2 can host to
# `/v2/custom/<slug>`. A new tab opened on that address from the host page is another host, and from
# the "could not be loaded" panel it reloads the same failing frame. These tests build V2's links with
# the real TypeScript and put each one through the real `evaluate_ui_redirect` and route registry.

BROWSER_NAVIGATION = {
    "method": "GET",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "fetch_dest": "document",
    "fetch_mode": "navigate",
}

# slug, what differs in its navigation entry, and the access level the server holds for it.
V2_LINK_PAGES = (
    ("probe", {}, "app_user"),
    ("policy", {"open_in_new_tab": True}, "app_user"),
    ("dash", {"embeddable": False}, "app_user"),
    ("lobby", {}, "authenticated"),
)

V2_LINKS_PROBE = """
import './functional_tests/test_support/tsResolve.mjs';
const embed = await import('./application/v2_ui/src/lib/customPageEmbed.ts');
const groups = await import('./application/v2_ui/src/lib/navigationGroups.ts');
const group = JSON.parse(process.argv[1]);
const bySlug = (build) => Object.fromEntries(group.items.map((page) => [page.slug, build(page.slug)]));
console.log(JSON.stringify({
    rail: groups.toCustomPageLinks(group),
    host: bySlug((slug) => embed.resolveCustomPageHost(slug, { custom_pages: group }).kind),
    standalone: bySlug((slug) => embed.safeCustomPageStandaloneHref(slug)),
    classic: bySlug((slug) => embed.safeCustomPageUrl(slug)),
}));
"""


def _node_json(source, *arguments):
    """Run a snippet against the real V2 TypeScript and read back the JSON it prints."""
    try:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", source, *arguments],
            cwd=str(ROOT), capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        pytest.skip("Node is not installed; it runs the V2 TypeScript directly")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def v2_links():
    """The links V2 draws for each kind of page, from the real TypeScript, with the data behind them."""
    items = [
        {
            "slug": slug, "label": slug.title(), "icon": "bi-file-earmark-text", "url": f"/custom/{slug}",
            "open_in_new_tab": False, "embeddable": True, **overrides,
        }
        for slug, overrides, _level in V2_LINK_PAGES
    ]
    group = {"enabled": True, "menu_name": "Pages", "force_menu": False, "items": items}
    records = {slug: {"slug": slug, "access_level": level} for slug, _overrides, level in V2_LINK_PAGES}
    return {"items": items, "records": records, **_node_json(V2_LINKS_PROBE, json.dumps(group))}


@contextmanager
def modern_redirect(items, records):
    """``decide(href)``: what the real redirect does when an app user opens ``href`` in the modern interface.

    The facts about the pages are the navigation items and records above, served through the real
    ``custom_page_opens_in_modern_ui``, so the hosted-page decision is the application's own.
    """
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    import functions_ui_mode
    import functions_ui_redirect as redirect

    with custom_pages_module() as pages:
        pages.is_custom_pages_enabled = lambda settings: True
        pages.get_custom_pages_nav = lambda settings: items
        pages.get_custom_page = lambda slug, include_python=True: records.get(slug)

        def decide(href, embeddable=None):
            parts = urlsplit(href)
            assert not parts.scheme and not parts.netloc, f"{href} is not a path on this site"
            return redirect.evaluate_ui_redirect(
                path=parts.path,
                query_string=parts.query,
                signed_in=True,
                has_app_role=True,
                ui_mode=functions_ui_mode.UI_MODE_MODERN,
                bundle_available=True,
                custom_page_embeddable=embeddable or (lambda slug: redirect.custom_page_opens_in_modern_ui(slug, {})),
                **BROWSER_NAVIGATION,
            )

        yield decide, redirect


def test_the_host_new_tab_address_is_not_a_redirect_candidate_in_the_modern_interface(v2_links):
    href = v2_links["standalone"]["probe"]
    parts = urlsplit(href)
    assert (parts.path, parts.query) == ("/custom/probe", "embed=1"), href

    with modern_redirect(v2_links["items"], v2_links["records"]) as (decide, redirect):
        # Whatever V2 can host: the embed pair alone keeps this request out of the redirect.
        for embeddable in (lambda slug: True, None):
            standalone = decide(href, embeddable)
            assert standalone.location is None, standalone
            assert standalone.reason == redirect.REASON_NO_V2_PAGE, standalone

        # The same request without the pair is what the redirect sends into V2, so it is the pair
        # that keeps the new tab out of it, and dropping the pair from V2's link fails this test.
        bare = decide(parts.path)
        assert (bare.location, bare.reason) == ("/v2/custom/probe", redirect.REASON_REDIRECT), bare
        assert decide(parts.path, lambda slug: True).location == "/v2/custom/probe"


def test_every_other_link_v2_draws_to_a_classic_custom_page_is_left_alone_by_the_redirect(v2_links):
    # What V2 does with each page: it frames the two it can host, and links to the classic address of
    # the two it cannot, from the rail and from the "opens in a new tab" card.
    assert v2_links["host"] == {"probe": "frame", "policy": "new-tab", "dash": "new-tab", "lobby": "frame"}
    anchors = [link for link in v2_links["rail"] if "customPageSlug" not in link]
    assert sorted(link["key"] for link in anchors) == ["custom-page:dash", "custom-page:policy"]

    with modern_redirect(v2_links["items"], v2_links["records"]) as (decide, redirect):
        # The premise, so none of the checks below can pass for lack of a working setup.
        assert decide(v2_links["classic"]["probe"]).location == "/v2/custom/probe"

        links = {f"rail anchor {link['key']}": link["href"] for link in anchors}
        links.update({
            f"new-tab card {slug}": v2_links["classic"][slug]
            for slug, kind in v2_links["host"].items() if kind == "new-tab"
        })
        assert len(links) == 4
        for name, href in links.items():
            decision = decide(href)
            assert (decision.location, decision.reason) == (None, redirect.REASON_CUSTOM_PAGE), (name, decision)

        # A page open to any signed-in user is framed for people with the app role and stays classic
        # at its own address, which has to serve people who cannot open V2. Its new tab is the embed
        # address, like every framed page's.
        lobby = decide(v2_links["classic"]["lobby"])
        assert (lobby.location, lobby.reason) == (None, redirect.REASON_CUSTOM_PAGE), lobby
        assert decide(v2_links["standalone"]["lobby"]).location is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
