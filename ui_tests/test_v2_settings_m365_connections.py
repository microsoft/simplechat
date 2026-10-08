# test_v2_settings_m365_connections.py
"""
Real-component browser tests for the Microsoft 365 connection cards in V2 Settings.
Version: 0.261.302
Implemented in: 0.261.302

The production M365Cards, Toaster and connect flow run in Chromium with the production CSS;
only HTTP responses are deterministic. The sign-in window ends on the real callback result
page, rendered by route_backend_m365 with its local script. These tests pin what the user saw
go wrong:

- the chat card said "Sources saved for this session: none" while chat was reading mail; it
  now names the sources the session can use;
- Connect for workflows failed with a Key Vault error no user can act on; the card now
  explains that an administrator has to turn on Key Vault storage and keeps Connect disabled;
- workflow connect navigated the whole page away and came back to classic Profile; it now
  signs in through a popup that reports back, so the user stays in V2, and a failure reported
  by the result page is shown;
- Open Approvals opened the classic Approvals page; it is now the V2 route.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_settings_m365_connections.py -q
"""

import copy
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_m365_connection_result_page import render_result_page, serve_static
from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
CSRF_TOKEN = "m365-settings-test-csrf-token-000000000001"
SIGN_IN_URL = f"{ORIGIN}/getAToken?code=ui-settings-code&state=m365-workflow-ui-settings-state"
CLASSIC_WORKFLOW_CONNECTED_URL = "/profile?tab=settings&m365_connection=connected#m365-connection-status"
NOT_READY = (
    "Workflow connections are not set up on this deployment yet: they need Key Vault secret storage. "
    "An administrator can turn it on in Admin Settings > Security > Secrets > Key Vault."
)
KEY_FORBIDDEN = (
    "SimpleChat could not create the workflow encryption key because its identity cannot write "
    "Key Vault secrets. An administrator must grant it Key Vault Secrets Officer on the vault."
)
PREFERENCES = {
    "sources": {"calendar": "ask", "email": "ask", "onedrive": "ask", "spo": "ask"},
    "extended_analysis": {"onedrive": "ask", "spo": "ask"},
}
CONNECTED = {
    "id": "m365-connection-ui", "status": "connected", "tenant_id": "tenant-ui", "cloud": "public",
    "account_username": "tester@contoso.test", "sources": ["email"], "authorized_scopes": ["Mail.Read"],
    "connected_at": "2026-10-08T15:00:00+00:00",
}


class SettingsApi:
    """The Microsoft 365 routes the cards call, plus the sign-in window's last page."""

    def __init__(self, assets):
        self.assets = assets
        self.chat_connection = {"status": "available", "sources": ["email", "onedrive", "spo"]}
        self.workflow_connection = None
        self.readiness = {"available": True, "reason": None, "message": ""}
        self.sign_in_fails = False
        self.connects = []
        self.unexpected = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path.startswith("/static/"):
            serve_static(route, path)
            return
        if request.method == "GET" and path == "/api/m365/preferences":
            route.fulfill(json={"success": True, "preferences": PREFERENCES, "csrf_token": CSRF_TOKEN})
        elif request.method == "GET" and path == "/api/m365/chat/connection":
            route.fulfill(json={"success": True, "connection": self.chat_connection, "csrf_token": CSRF_TOKEN})
        elif request.method == "GET" and path == "/api/m365/connections":
            route.fulfill(json={
                "success": True, "connection": copy.deepcopy(self.workflow_connection),
                "workflow_connections": self.readiness, "csrf_token": CSRF_TOKEN,
            })
        elif request.method == "GET" and path == "/api/m365/bindings":
            route.fulfill(json={"items": [], "continuation_token": None})
        elif request.method == "POST" and path == "/api/m365/connections/connect":
            self.connects.append({"body": request.post_data_json, "csrf": request.headers.get("x-m365-csrf-token")})
            route.fulfill(json={"success": True, "authorization_url": SIGN_IN_URL})
        elif request.method == "GET" and path == "/getAToken":
            self.finish_sign_in(route)
        else:
            self.unexpected.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unmocked request"})

    def finish_sign_in(self, route):
        if self.sign_in_fails:
            status, html = render_result_page(
                kind="workflow", outcome="failed", completion="popup", status=503,
                code="m365_key_provision_forbidden", message=KEY_FORBIDDEN,
                continue_url="/profile?tab=settings#m365-connection-status",
            )
        else:
            self.workflow_connection = copy.deepcopy(CONNECTED)
            status, html = render_result_page(
                kind="workflow", outcome="connected", completion="popup", continue_url=CLASSIC_WORKFLOW_CONNECTED_URL,
            )
        route.fulfill(status=status, content_type="text/html", body=html)


@pytest.fixture
def settings_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    api = SettingsApi(editor_assets)
    errors = []
    # Context routes reach the sign-in popup as well as the page.
    context.route("**/*", api.handle)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not errors, f"Unexpected browser errors: {errors}"


def mount(page, api):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.reset();
            H.mount('mount-a', 'M365Cards', {});
            H.mount('mount-b', 'Toaster', {});
        }"""
    )
    return (
        page.get_by_role("region", name="Chat connection", exact=True),
        page.get_by_role("region", name="Workflow connection", exact=True),
    )


def test_chat_card_names_the_sources_this_session_can_use(settings_ui):
    page, api = settings_ui
    chat, _workflow = mount(page, api)
    expect(chat.get_by_role("status")).to_have_text(
        "Signed in to Microsoft 365 for this session. Chat can use: Email, OneDrive, SharePoint Online (SPO). "
        "Microsoft still checks your access each time a source runs."
    )
    expect(chat).not_to_contain_text("Sources saved for this session")
    for source, checked in (("calendar", False), ("email", True), ("onedrive", True), ("spo", True)):
        checkbox = chat.locator(f"#m365-chat-source-{source}")
        if checked:
            expect(checkbox).to_be_checked()
        else:
            expect(checkbox).not_to_be_checked()
    expect(chat.get_by_role("button", name="Reconnect Microsoft 365 for chat")).to_be_enabled()


def test_unready_deployment_is_explained_instead_of_failing_on_connect(settings_ui):
    page, api = settings_ui
    api.readiness = {"available": False, "reason": "key_vault_disabled", "message": NOT_READY}
    _chat, workflow = mount(page, api)
    expect(workflow.get_by_text(NOT_READY, exact=True)).to_be_visible()
    expect(workflow.get_by_role("button", name="Connect for workflows")).to_be_disabled()
    expect(workflow.locator("#m365-workflow-source-email")).to_be_disabled()
    expect(workflow).to_contain_text("which SimpleChat creates the first time anyone connects")
    assert not api.connects


def test_workflow_connect_signs_in_through_a_popup_and_stays_in_v2(settings_ui):
    page, api = settings_ui
    _chat, workflow = mount(page, api)
    expect(workflow.get_by_role("status").first).to_have_text("Workflow connection: disconnected.")
    workflow.locator("#m365-workflow-source-email").check()
    with page.expect_popup() as opened:
        workflow.get_by_role("button", name="Connect for workflows").click()
    popup = opened.value
    if not popup.is_closed():
        popup.wait_for_event("close")

    expect(page.get_by_text("Microsoft 365 is connected for workflows.", exact=False)).to_be_visible()
    expect(workflow.get_by_text("Workflow connection: connected.", exact=True)).to_be_visible()
    expect(workflow).to_contain_text("tester@contoso.test")
    expect(workflow.get_by_role("button", name="Reconnect for workflows")).to_be_enabled()
    assert api.connects == [{"body": {"sources": ["email"], "completion": "popup"}, "csrf": CSRF_TOKEN}]
    # The page never left V2 for the sign-in or for classic Profile.
    assert urlsplit(page.url).path == HARNESS


def test_failed_workflow_sign_in_shows_the_result_pages_message(settings_ui):
    page, api = settings_ui
    api.sign_in_fails = True
    _chat, workflow = mount(page, api)
    workflow.locator("#m365-workflow-source-email").check()
    with page.expect_popup() as opened:
        workflow.get_by_role("button", name="Connect for workflows").click()
    popup = opened.value
    if not popup.is_closed():
        popup.wait_for_event("close")

    expect(page.get_by_text(KEY_FORBIDDEN, exact=True)).to_be_visible()
    expect(workflow.get_by_role("button", name="Connect for workflows")).to_be_enabled()
    expect(workflow.get_by_text("Workflow connection: disconnected.", exact=True)).to_be_visible()
    assert len(api.connects) == 1
    assert urlsplit(page.url).path == HARNESS


def test_open_approvals_stays_in_v2(settings_ui):
    page, api = settings_ui
    mount(page, api)
    authorizations = page.get_by_role("region", name="Workflow authorizations")
    expect(authorizations.get_by_role("link", name="Open Approvals")).to_have_attribute("href", "/approvals/m365")
