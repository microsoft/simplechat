# test_m365_connection_result_page.py
"""
UI test for the Microsoft 365 sign-in result page.
Version: 0.261.302
Implemented in: 0.261.302

The sign-in callbacks used to answer a failed sign-in with raw JSON, which the V2 popup showed
as {"error":"m365_auth_state_invalid",...}. They now render templates/m365_connection_result.html.
In a popup the page reports the outcome to the same-origin window that opened it and closes; on a
full page it continues to the fixed settings page after success, and shows the error, as text,
with a link back after a failure.

The page is rendered by the real route helper, route_backend_m365._connection_result_page, with
the real template, Bootstrap and the page's local script, in local Chromium with same-origin
fixtures. No server, Microsoft sign-in or network is used.
Run: python -m pytest .\\ui_tests\\test_m365_connection_result_page.py -q
"""

import functools
import importlib.util
import mimetypes
import sys
import types
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import pytest
from flask import Flask
from playwright.sync_api import expect


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ORIGIN = "https://simplechat.test"
CLASSIC_CHAT_CONNECTION_URL = "/profile?tab=settings#m365-chat-connection"
CLASSIC_WORKFLOW_CONNECTED_URL = "/profile?tab=settings&m365_connection=connected#m365-connection-status"
UNSAFE_MESSAGE = 'Consent was not completed. <img src=x onerror="window.injected=true">'

pytestmark = pytest.mark.ui


def _module_stub(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


@functools.lru_cache(maxsize=1)
def _routes_module():
    """The real route module, with its authentication and logging seams stubbed."""
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    spec = importlib.util.spec_from_file_location("m365_result_page_routes", APP_ROOT / "route_backend_m365.py")
    module = importlib.util.module_from_spec(spec)
    stubs = {
        "functions_appinsights": _module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_authentication": _module_stub(
            "functions_authentication", login_required=lambda function: function,
            user_required=lambda function: function, user_required_blueprint=lambda: (lambda: None),
        ),
        "swagger_wrapper": _module_stub(
            "swagger_wrapper", swagger_route=lambda **kwargs: (lambda function: function),
            get_auth_security=lambda: [],
        ),
    }
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


def render_result_page(**options):
    """The callback's result page exactly as route_backend_m365 renders it."""
    app = Flask(__name__, template_folder=str(APP_ROOT / "templates"), static_folder=str(APP_ROOT / "static"))
    with app.test_request_context("/getAToken"):
        response = _routes_module()._connection_result_page(**options)
        return response.status_code, response.get_data(as_text=True)


def serve_static(route, path):
    """Serve a file from the application's static folder, refusing anything outside it."""
    root = (APP_ROOT / "static").resolve()
    asset = (root / unquote(path[len("/static/"):])).resolve()
    if not asset.is_relative_to(root) or not asset.is_file():
        route.fulfill(status=404, body="")
        return
    route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")


OPENER_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8" /><title>Opener</title></head>
<body><button type="button" id="open">Sign in</button>
<script>
window.received = [];
window.addEventListener('message', (event) => window.received.push({ origin: event.origin, data: event.data }));
document.getElementById('open').addEventListener('click', () => {
    window.open('/getAToken?code=ui&state=fixture', 'simplechat-m365-workflow-connect', 'popup,width=600,height=600');
});
</script></body></html>"""


class ResultFixture:
    def __init__(self):
        self.result_html = ""
        self.unexpected = []

    def handle(self, route):
        parsed = urlsplit(route.request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(route.request.url)
            route.abort()
            return
        if path == "/opener":
            route.fulfill(content_type="text/html", body=OPENER_HTML)
        elif path == "/getAToken":
            route.fulfill(content_type="text/html", body=self.result_html)
        elif path == "/profile":
            route.fulfill(content_type="text/html", body="<!doctype html><title>Profile</title><h1>Profile fixture</h1>")
        elif path.startswith("/static/"):
            serve_static(route, path)
        else:
            self.unexpected.append(route.request.url)
            route.fulfill(status=404, body="")


@pytest.fixture
def result_ui(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    fixture = ResultFixture()
    errors = []
    context.route("**/*", fixture.handle)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield page, fixture
    finally:
        context.close()
        browser.close()
        assert not fixture.unexpected, fixture.unexpected
        assert not errors, errors


def open_result_popup(page):
    page.goto(f"{ORIGIN}/opener")
    with page.expect_popup() as opened:
        page.locator("#open").click()
    popup = opened.value
    if not popup.is_closed():
        popup.wait_for_event("close")
    return page.evaluate("window.received")


def test_popup_reports_a_workflow_connection_to_its_opener_and_closes(result_ui):
    page, fixture = result_ui
    status, fixture.result_html = render_result_page(
        kind="workflow", outcome="connected", completion="popup", continue_url=CLASSIC_WORKFLOW_CONNECTED_URL,
    )
    assert status == 200
    received = open_result_popup(page)
    assert received == [{
        "origin": ORIGIN,
        "data": {"type": "m365-workflow-connected", "kind": "workflow", "outcome": "connected"},
    }]


def test_popup_reports_a_failure_with_its_code_and_message_as_text(result_ui):
    page, fixture = result_ui
    status, fixture.result_html = render_result_page(
        kind="chat", outcome="failed", completion="popup", status=400,
        code="m365_consent_required", message=UNSAFE_MESSAGE, continue_url=CLASSIC_CHAT_CONNECTION_URL,
    )
    assert status == 400
    received = open_result_popup(page)
    assert received == [{
        "origin": ORIGIN,
        "data": {
            "type": "m365-connect-failed", "kind": "chat", "outcome": "failed",
            "code": "m365_consent_required", "message": UNSAFE_MESSAGE,
        },
    }]
    assert page.evaluate("window.injected === undefined")


@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}])
def test_failure_without_an_opener_stays_readable_with_a_link_back(result_ui, viewport):
    page, fixture = result_ui
    page.set_viewport_size(viewport)
    _status, fixture.result_html = render_result_page(
        kind="chat", outcome="failed", completion="auto", status=400,
        code="m365_auth_state_invalid", message=UNSAFE_MESSAGE, continue_url=CLASSIC_CHAT_CONNECTION_URL,
    )
    page.goto(f"{ORIGIN}/getAToken?code=ui&state=fixture")
    expect(page.get_by_role("heading", name="Microsoft 365 was not connected")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text(UNSAFE_MESSAGE)
    expect(page.locator("#m365-connection-result img")).to_have_count(0)
    link = page.get_by_role("link", name="Return to settings")
    expect(link).to_have_attribute("href", CLASSIC_CHAT_CONNECTION_URL)
    expect(page.get_by_role("button", name="Close window")).to_be_hidden()
    assert urlsplit(page.url).path == "/getAToken"
    layout = page.evaluate("""() => ({
        content: document.documentElement.scrollWidth, viewport: window.innerWidth,
    })""")
    assert layout["content"] <= layout["viewport"]
    assert page.evaluate("window.injected === undefined")


def test_full_page_success_continues_to_the_fixed_settings_page(result_ui):
    page, fixture = result_ui
    _status, fixture.result_html = render_result_page(
        kind="workflow", outcome="connected", completion="auto", continue_url=CLASSIC_WORKFLOW_CONNECTED_URL,
    )
    page.goto(f"{ORIGIN}/getAToken?code=ui&state=fixture")
    expect(page.get_by_role("heading", name="Profile fixture")).to_be_visible()
    returned = urlsplit(page.url)
    assert (returned.path, returned.query, returned.fragment) == (
        "/profile", "tab=settings&m365_connection=connected", "m365-connection-status",
    )


def test_popup_that_lost_its_opener_offers_to_close_instead_of_navigating(result_ui):
    page, fixture = result_ui
    _status, fixture.result_html = render_result_page(
        kind="chat", outcome="connected", completion="popup", continue_url=CLASSIC_CHAT_CONNECTION_URL,
    )
    page.goto(f"{ORIGIN}/getAToken?code=ui&state=fixture")
    expect(page.get_by_role("heading", name="Microsoft 365 is connected")).to_be_visible()
    expect(page.get_by_role("button", name="Close window")).to_be_visible()
    expect(page.locator("#m365-connection-result-closing")).to_be_hidden()
    assert urlsplit(page.url).path == "/getAToken"
