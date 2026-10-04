# test_terms_of_use_ui.py
"""
UI tests for Terms of Use admin controls and Markdown rendering.
Version: 0.261.051
Implemented in: 0.250.055
Redirect hardening updated in: 0.250.057
Markdown rendering updated in: 0.261.049

Uses the actual Jinja template and Markdown filter without cloud bootstrap.
Azure Playwright is supported when configured; otherwise uses local Chromium.
"""

import ast
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import bleach
from azure.identity import DefaultAzureCredential
from azure.mgmt.playwright import PlaywrightMgmtClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
import markdown2
from markupsafe import Markup
from playwright.sync_api import expect
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
TERMS_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "terms_of_use.html"
APP_ROOT = TERMS_TEMPLATE.parent.parent
NOTICES_TEMPLATE = TERMS_TEMPLATE.parent / "admin" / "_panes" / "notices.html"
ORIGIN = "http://simplechat.test"


def _read(path):
    return path.read_text(encoding="utf-8")


@pytest.mark.ui
def test_admin_notices_tab_exposes_terms_of_use_controls():
    """Validate the included Notices pane exposes the controls and formatting help."""
    assert '{% include "admin/_panes/notices.html" %}' in _read(ADMIN_TEMPLATE)
    source = _read(NOTICES_TEMPLATE)

    assert 'id="terms-of-use-section"' in source
    assert 'name="enable_terms_of_use"' in source
    assert 'name="terms_of_use_message"' in source
    assert 'name="terms_of_use_frequency"' in source
    assert 'value="every_session"' in source
    assert 'value="daily"' in source
    assert 'value="once"' in source
    assert 'name="terms_of_use_decline_redirect_url"' in source
    assert "Terms of Use" in source
    assert "Supports Markdown" in source
    assert "Plain text is shown" not in source


@pytest.mark.ui
def test_terms_of_use_template_uses_local_assets_and_sanitized_markdown():
    """The shared filter owns sanitization; the template does not mark raw text safe."""
    source = _read(TERMS_TEMPLATE)

    assert "terms_of_use.html" in source
    assert "url_for('static', filename='css/bootstrap.min.css')" in source
    assert "url_for('static', filename='css/bootstrap-icons.min.css')" in source
    assert "url_for('static', filename='images/custom_logo.png')" in source
    assert "url_for('static', filename='images/logo-lightmode.png')" in source
    assert "url_for('static', filename='images/logo.png')" not in source
    assert "data:image" not in source
    assert "https://" not in source
    assert "http://" not in source
    assert "terms.message | markdown(" in source
    assert "safe_mode='escape'" in source
    assert 'name="return_url"' not in source
    assert "|safe" not in source
    assert "innerHTML" not in source
    assert "display:none" not in source


@pytest.fixture(scope="module")
def terms_browser(playwright):
    endpoint = os.getenv("AZURE_PLAYWRIGHT_WS_ENDPOINT")
    if not endpoint:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()
        return
    with DefaultAzureCredential() as credential:
        with PlaywrightMgmtClient(credential, os.environ["AZURE_SUBSCRIPTION_ID"]) as client:
            workspace = client.playwright_workspaces.get(
                os.environ["AZURE_PLAYWRIGHT_RESOURCE_GROUP"],
                os.environ["AZURE_PLAYWRIGHT_WORKSPACE"],
            )
            if not workspace.id:
                raise RuntimeError("Azure Playwright workspace could not be verified.")
            token = credential.get_token(os.environ["AZURE_PLAYWRIGHT_TOKEN_SCOPE"])
            browser = playwright.chromium.connect(
                endpoint,
                headers={"Authorization": f"Bearer {token.token}"},
                expose_network="<loopback>",
            )
            try:
                yield browser
            finally:
                browser.close()


@pytest.mark.ui
def test_admin_current_terms_version_is_read_only_and_visible_when_disabled(terms_browser):
    environment = Environment(loader=FileSystemLoader(TERMS_TEMPLATE.parent), autoescape=select_autoescape(["html"]))
    markup = environment.get_template("admin/_panes/notices.html").render(
        settings={"enable_terms_of_use": False, "terms_of_use_version_label": "v2"},
        admin_landing_tab="notices",
    )
    context = terms_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(markup)
        expect(page.locator("#terms-of-use-version")).to_have_text("v2")
        expect(page.locator("#enable_terms_of_use")).not_to_be_checked()
        assert page.locator("#terms-of-use-version").get_attribute("name") is None
        expect(page.locator("#terms_of_use_message")).to_be_editable()
    finally:
        context.close()


@pytest.fixture(scope="module")
def terms_environment():
    tree = ast.parse(_read(APP_ROOT / "app.py"))
    renderer = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "markdown_filter"
    )
    namespace = {"markdown2": markdown2, "bleach": bleach, "re": re, "Markup": Markup}
    exec(compile(ast.Module(body=[renderer], type_ignores=[]), "app.py", "exec"), namespace)
    environment = Environment(
        loader=FileSystemLoader(TERMS_TEMPLATE.parent),
        autoescape=select_autoescape(),
    )
    environment.filters["markdown"] = namespace["markdown_filter"]
    environment.globals["url_for"] = lambda endpoint, **values: (
        f"/static/{values['filename']}" if endpoint == "static" else {
            "frontend_terms_of_use.accept_terms_of_use": "/terms-of-use/accept",
            "frontend_terms_of_use.decline_terms_of_use": "/terms-of-use/decline",
        }[endpoint]
    )
    return environment


@pytest.fixture
def terms_page(terms_browser, terms_environment):
    contexts = []
    errors = []
    external = []
    submissions = []

    def open_terms(message, *, width=1440, authenticated=False, javascript=True, **overrides):
        context = terms_browser.new_context(
            viewport={"width": width, "height": 900},
            java_script_enabled=javascript,
        )
        contexts.append(context)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        terms = {
            "title": "Terms of Use", "message": message,
            "accept_button_text": "Accept and continue", "decline_button_text": "Cancel",
            **overrides,
        }
        html = terms_environment.get_template("terms_of_use.html").render(
            terms=terms,
            app_settings={"show_logo": False, "app_title": "SimpleChat"},
            is_authenticated=authenticated,
        )

        def route_request(route):
            url = urlsplit(route.request.url)
            if f"{url.scheme}://{url.netloc}" != ORIGIN:
                external.append(route.request.url)
                route.abort()
            elif url.path.startswith("/static/"):
                asset = (APP_ROOT / unquote(url.path.lstrip("/"))).resolve()
                if not asset.is_relative_to(APP_ROOT) or not asset.is_file():
                    route.fulfill(status=404, body="")
                    return
                route.fulfill(
                    body=asset.read_bytes(),
                    content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream",
                )
            elif url.path in {"/terms-of-use/accept", "/terms-of-use/decline"}:
                submissions.append((route.request.method, url.path))
                route.fulfill(body="Decision received", content_type="text/plain")
            elif url.path == "/terms-of-use":
                route.fulfill(body=html, content_type="text/html")
            else:
                route.fulfill(status=404, body="")

        page.route("**/*", route_request)
        page.goto(f"{ORIGIN}/terms-of-use", wait_until="networkidle")
        return page

    yield open_terms, submissions
    for context in contexts:
        context.close()
    assert not errors
    assert not external


@pytest.mark.ui
@pytest.mark.parametrize("width,authenticated", [(1440, False), (390, True)])
def test_markdown_terms_render_without_javascript(terms_page, width, authenticated):
    open_terms, _ = terms_page
    page = open_terms(
        "## Usage rules\n\n**Required** and *important*.\n\n"
        "- Protect data\n- Report issues\n\n1. Read\n2. Accept\n\n"
        "> Review before accepting.\n\n[Policy](https://example.com/policy)\n\n"
        "`inline code`\n\n```text\n<example>\n```\n\n"
        "| Rule | Detail |\n| --- | --- |\n| Privacy | Protect data |\n\n---",
        width=width, authenticated=authenticated, javascript=False,
    )
    content = page.get_by_role("region", name="Terms of Use")
    expect(content.get_by_role("heading", name="Usage rules")).to_be_visible()
    expect(content.locator("strong")).to_have_text("Required")
    expect(content.locator("em")).to_have_text("important")
    expect(content.locator("ul > li")).to_have_text(["Protect data", "Report issues"])
    expect(content.locator("ol > li")).to_have_text(["Read", "Accept"])
    expect(content.locator("blockquote")).to_contain_text("Review before accepting.")
    expect(content.get_by_role("link", name="Policy")).to_have_attribute("href", "https://example.com/policy")
    expect(content.get_by_role("link", name="Policy")).to_have_attribute("rel", "noopener noreferrer")
    expect(content.locator("pre code")).to_have_text("<example>\n")
    expect(content.get_by_role("columnheader")).to_have_text(["Rule", "Detail"])
    expect(content.get_by_role("cell")).to_have_text(["Privacy", "Protect data"])
    expect(content.locator("hr")).to_have_count(1)
    expect(page.get_by_role("button", name="Accept and continue")).to_be_visible()
    expect(page.get_by_role("button", name="Cancel", exact=True)).to_be_visible()


@pytest.mark.ui
def test_plain_text_line_breaks_and_mobile_overflow(terms_page):
    open_terms, _ = terms_page
    page = open_terms(
        "First line\nSecond line\n\nNext paragraph\n\n"
        + "A" * 500 + "\n\n```text\n" + "B" * 500 + "\n```",
        width=390,
    )
    content = page.get_by_role("region", name="Terms of Use")
    expect(content.locator("p").first).to_have_text("First line\nSecond line")
    expect(content.locator("p").first.locator("br")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    content.focus()
    expect(content).to_be_focused()
    before = content.evaluate("element => element.scrollTop")
    page.keyboard.press("End")
    expect(content.locator("pre")).to_be_in_viewport()
    assert content.evaluate("element => element.scrollTop") > before
    code = content.locator("pre")
    assert code.evaluate("element => element.scrollWidth > element.clientWidth")


@pytest.mark.ui
def test_markdown_and_html_cannot_inject_active_content(terms_page):
    open_terms, _ = terms_page
    page = open_terms(
        '<script>window.termsInjected = true</script>\n\n'
        '<img src="https://invalid.example/track" onerror="window.termsInjected = true">\n\n'
        '<form action="/terms-of-use/accept"><button>Injected</button></form>\n\n'
        '[Unsafe](javascript:alert(1))\n\n'
        '[Encoded](jav&#x61;script:alert(1))\n\n'
        '[Data](data:text/html;base64,PHNjcmlwdD4=)\n\n'
        '![Tracking](https://invalid.example/image)\n\n'
        '[Relative](/policy)\n\n[Email](mailto:policy@example.com)',
        title='**Title** <img src="invalid">',
        accept_button_text='<b>Accept</b>',
    )
    content = page.locator(".terms-message")
    expect(content.locator("script, img, form, button, iframe, svg, style, input")).to_have_count(0)
    expect(content.locator("a[href^='javascript:'], a[href^='data:']")).to_have_count(0)
    expect(content.get_by_role("link", name="Relative")).to_have_attribute("href", "/policy")
    expect(content.get_by_role("link", name="Email")).to_have_attribute("href", "mailto:policy@example.com")
    expect(page.locator("#terms-of-use-title")).to_have_text('**Title** <img src="invalid">')
    expect(page.locator("#terms-of-use-title img")).to_have_count(0)
    expect(page.get_by_role("button", name="<b>Accept</b>")).to_be_visible()
    assert page.evaluate("window.termsInjected === undefined")


@pytest.mark.ui
@pytest.mark.parametrize("button,path", [("Accept and continue", "/terms-of-use/accept"), ("Cancel", "/terms-of-use/decline")])
def test_markdown_terms_preserve_decision_forms(terms_page, button, path):
    open_terms, submissions = terms_page
    page = open_terms("## Review\n\nPlease **read** these terms.", javascript=False)
    page.get_by_role("button", name=button, exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}{path}")
    assert submissions == [("POST", path)]


def test_shared_markdown_filter_keeps_default_line_break_behavior(terms_environment):
    render = terms_environment.filters["markdown"]
    assert str(render("First\nSecond")) == "<p>First\nSecond</p>\n"
    assert str(render(None)) == "<p></p>\n"
