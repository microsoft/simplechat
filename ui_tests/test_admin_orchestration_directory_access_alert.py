# test_admin_orchestration_directory_access_alert.py
"""
UI coverage for the Chat Orchestration directory access warnings in classic Admin Settings.
Version: 0.261.204
Implemented in: 0.261.204

Before a plan uses web search or another external source, Chat Orchestration rereads the user's
app roles from Microsoft Graph with the application's own identity, which needs the Microsoft
Graph Directory.Read.All application permission. Admin Settings asks the server to run the same
read and, when it fails, warns on the Chat Orchestration tab and on the Web Search card. The two
panes are rendered from their real templates, the real ES modules run against an intercepted
check endpoint, and no SimpleChat server, credential or tenant is used.
"""

import json
import re
import sys
import time
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

HERE = Path(__file__).resolve().parent
# The shared static server lives in the orchestration fixtures folder, which is not a package, so
# its module can only be imported once that folder is on sys.path.
sys.path.insert(0, str(HERE / "fixtures" / "orchestration"))

import harness_build as hb  # noqa: E402

pytestmark = pytest.mark.ui
APP_ROOT = HERE.parent / "application" / "single_app"
STATIC = "/application/single_app/static"
MODULE = f"{STATIC}/js/admin/admin_orchestration_directory_access.js"
CARD_LINK_MODULES = (f"{STATIC}/js/admin/admin_sidebar_nav.js", f"{STATIC}/js/admin/admin_card_links.js")
CHECK_ROUTE = "**/api/admin/settings/orchestration/directory-access-check"
ALERT = "#chat-orchestration-directory-access-alert"
WEB_SEARCH_ALERT = "#web-search-directory-access-alert"
STATES = ("permission_missing", "sign_in_failed", "unverified")
BOTH_TABS = ("chat-orchestration", "web-research")
HIDDEN = re.compile(r"\bd-none\b")
ACTIVE = re.compile(r"\bactive\b")

# A made-up application id; the page must never need a real tenant value.
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
PERMISSION_ID = "7ab1d382-f21e-4acd-a863-ba3e13f7da61"
# The server sends datetime.isoformat(), which carries microseconds.
CHECKED_AT = "2026-01-15T12:00:00.123456+00:00"
CHECKED = re.compile(r"^Checked \S.*\.$")
LABELS = {
    "web_search": "Web search",
    "url_fetch": "Read linked pages",
    "deep_research": "Deep research",
    "agent_invoke": "Invoke an agent",
    "action_invoke": "Run an action",
}
REASONS = {
    "permission_missing": "external_identity_directory_permission_missing",
    "sign_in_failed": "external_identity_directory_sign_in_failed",
}
PERMISSION_SUMMARY = (
    "Chat Orchestration can't verify that users may use web search, because this app registration "
    "doesn't have the Microsoft Graph Directory.Read.All permission."
)
SIGN_IN_SUMMARY = (
    "Chat Orchestration can't verify that users may use web search, because Microsoft Entra ID "
    "refused SimpleChat's application sign-in."
)
RETRY_TEXT = "The check could not be completed. Try again."
PANE_CONTEXT = {
    "chat-orchestration": {
        "settings": {"enable_chat_orchestration": True},
        "orchestration_capabilities": (),
        "orchestration_selected_capabilities": (),
    },
    "web-research": {
        "settings": {"enable_web_search": True, "web_search_agent": {"other_settings": {}}},
        "js_runtime": {"js_rendering_available": False, "message": ""},
    },
}
ENVIRONMENT = Environment(
    loader=FileSystemLoader(APP_ROOT / "templates"), autoescape=select_autoescape(["html"]),
)


def commands(client_id=CLIENT_ID):
    return (
        f"az ad app permission add --id {client_id} --api {GRAPH_APP_ID} "
        f"--api-permissions {PERMISSION_ID}=Role\n"
        f"az ad app permission admin-consent --id {client_id}"
    )


def report(status, *, sources=("web_search",), **overrides):
    """A check result shaped like check_orchestration_directory_access() returns it."""
    result = {
        "success": True,
        "status": status,
        "required": bool(sources),
        "reason": REASONS.get(status),
        "capabilities": [{"id": source, "label": LABELS[source]} for source in sources],
        "web_search_enabled": "web_search" in sources,
        "application_client_id": CLIENT_ID,
        "graph_permission": "Directory.Read.All",
        "graph_permission_id": PERMISSION_ID,
        "graph_resource_app_id": GRAPH_APP_ID,
        "checked_at": None if status == "not_required" else CHECKED_AT,
    }
    result.update(overrides)
    return result


def ok(result):
    return 200, result


# Placed in a response script to keep a request open until the test releases it.
HOLD = object()


def respond(route, status, payload):
    if isinstance(payload, str):
        route.fulfill(status=status, content_type="text/html; charset=utf-8", body=payload)
    else:
        route.fulfill(status=status, json=payload)


class DirectoryCheck:
    """Answers the directory access check endpoint from a script of responses."""

    def __init__(self, page, *responses):
        self.responses = list(responses)
        self.bodies = []
        self.held = []
        page.route(CHECK_ROUTE, self._handle)

    def _handle(self, route):
        self.bodies.append(json.loads(route.request.post_data or "null"))
        if not self.responses:
            route.fulfill(status=500, json={"success": False, "error": "Unexpected directory access check."})
            return
        response = self.responses.pop(0)
        if response is HOLD:
            self.held.append(route)
            return
        respond(route, *response)

    def wait_for_held(self, page, timeout=5.0):
        # Route handlers run while Playwright waits, so short waits let the request arrive.
        deadline = time.monotonic() + timeout
        while not self.held:
            if time.monotonic() > deadline:
                raise AssertionError("The check request never reached the endpoint.")
            page.wait_for_timeout(25)

    def release(self, response):
        respond(self.held.pop(0), *response)


def render_pane(tab_id, *, active):
    template = ENVIRONMENT.get_template(f"admin/_panes/{tab_id}.html")
    return template.render(admin_landing_tab=tab_id if active else "", **PANE_CONTEXT[tab_id])


def admin_page(active_tabs, *, card_links):
    panes = "\n".join(render_pane(tab_id, active=tab_id in active_tabs) for tab_id in PANE_CONTEXT)
    modules = [*CARD_LINK_MODULES, MODULE] if card_links else [MODULE]
    scripts = "\n".join(f'<script type="module" src="{source}"></script>' for source in modules)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin Settings</title>
<link rel="stylesheet" href="{STATIC}/css/bootstrap.min.css">
</head>
<body>
<main class="container-fluid py-3">
<form method="post" id="admin-settings-form" novalidate>
<div class="tab-content mt-3" id="adminSettingsTabContent">
{panes}
</div>
</form>
</main>
{scripts}
</body>
</html>"""


@pytest.fixture(scope="module")
def static_origin():
    with hb.start_static_server() as url:
        yield url


def open_admin_settings(page, origin, *, active_tabs=BOTH_TABS, card_links=False):
    """Serve the panes as the Admin Settings page and wait for the first check to settle.

    Returns the list that collects uncaught page errors and console errors.
    """
    problems = []

    def on_console(message):
        if message.type == "error":
            problems.append(f"console: {message.text}")

    page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
    page.on("console", on_console)
    html = admin_page(active_tabs, card_links=card_links)
    page.route(
        f"{origin}/admin/settings",
        lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html),
    )
    with page.expect_response(CHECK_ROUTE):
        page.goto(f"{origin}/admin/settings", wait_until="load")
    # The module disables Check again for the length of a check, so an enabled button after the
    # response means the result has been applied to the page.
    expect(page.locator(f"{ALERT} [data-directory-access-recheck]")).to_be_enabled()
    return problems


def unexpected(problems):
    """Everything except the browser's own log line for a deliberately failed response."""
    return [problem for problem in problems if "the server responded with a status of 5" not in problem]


def expect_state(alert, state):
    """Only the guidance for ``state`` is shown; every other block stays hidden."""
    for name in STATES:
        block = alert.locator(f'[data-directory-access-state="{name}"]')
        if name == state:
            expect(block).to_be_visible()
            expect(block).not_to_have_class(HIDDEN)
        else:
            expect(block).to_have_class(HIDDEN)


def sources_phrase(alert, state):
    return alert.locator(f'[data-directory-access-state="{state}"] [data-directory-access-capabilities]')


def assert_fits(locator):
    """The warning sits inside the viewport and nothing in it scrolls sideways out of its box."""
    layout = locator.evaluate(
        """(element) => {
            const rect = element.getBoundingClientRect();
            return {
                left: rect.left, right: rect.right, viewport: document.documentElement.clientWidth,
                scrollWidth: element.scrollWidth, clientWidth: element.clientWidth,
            };
        }"""
    )
    assert layout["left"] >= 0 and layout["right"] <= layout["viewport"] + 1, layout
    assert layout["scrollWidth"] <= layout["clientWidth"] + 1, layout


@pytest.mark.parametrize("width", [1280, 390])
def test_missing_permission_warns_both_tabs_until_check_again_passes(page, static_origin, width):
    page.set_viewport_size({"width": width, "height": 900})
    check = DirectoryCheck(
        page, ok(report("permission_missing", sources=("web_search", "url_fetch", "agent_invoke"))), HOLD,
    )
    problems = open_admin_settings(page, static_origin)

    alert = page.locator(ALERT)
    expect(alert).to_be_visible()
    expect(alert).to_have_attribute("role", "status")
    expect(alert).to_have_attribute("aria-live", "polite")
    expect_state(alert, "permission_missing")
    expect(alert).to_contain_text("SimpleChat can't read Microsoft Entra ID")
    expect(sources_phrase(alert, "permission_missing")).to_have_text("web search, linked pages or agents")
    assert alert.locator("[data-directory-access-commands]").text_content() == commands()
    detail = alert.locator("[data-directory-access-detail]")
    expect(detail).to_have_text(CHECKED)

    web_alert = page.locator(WEB_SEARCH_ALERT)
    expect(web_alert).to_be_visible()
    expect(web_alert.locator("[data-directory-access-summary]")).to_have_text(PERMISSION_SUMMARY)
    link = web_alert.get_by_role("link", name="See how to fix it")
    expect(link).to_have_attribute("href", ALERT)
    expect(link).to_have_attribute("data-admin-link", ALERT.lstrip("#"))
    assert_fits(alert)
    assert_fits(web_alert)

    button = alert.get_by_role("button", name="Check again")
    # The warning sits inside the settings form, so its button must never be the form's submit.
    assert button.evaluate("(element) => element.type") == "button"
    button.click()
    check.wait_for_held(page)
    expect(button).to_be_disabled()
    expect(detail).to_have_text("Checking...")

    check.release(ok(report("ready", sources=("web_search", "url_fetch", "agent_invoke"))))
    expect(alert).to_be_hidden()
    # Hidden elements leave the accessibility tree, so the button is found by its hook from here.
    expect(alert.locator("[data-directory-access-recheck]")).to_be_enabled()
    expect(alert).to_have_class(HIDDEN)
    expect(web_alert).to_be_hidden()
    expect_state(alert, None)
    expect(detail).to_have_text("")
    # Opening the page may reuse the server's cached result; Check again always asks for a new one.
    assert check.bodies == [{"refresh": False}, {"refresh": True}]
    assert problems == []


@pytest.mark.parametrize("width", [1280, 390])
def test_refused_sign_in_points_at_the_client_secret(page, static_origin, width):
    page.set_viewport_size({"width": width, "height": 900})
    DirectoryCheck(page, ok(report("sign_in_failed")))
    problems = open_admin_settings(page, static_origin)

    alert = page.locator(ALERT)
    expect(alert).to_be_visible()
    expect_state(alert, "sign_in_failed")
    expect(alert).to_contain_text("SimpleChat can't sign in to Microsoft Entra ID")
    expect(alert).to_contain_text("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET")
    expect(sources_phrase(alert, "sign_in_failed")).to_have_text("web search")
    # The reason is only spelled out when the cause is unknown.
    expect(alert.locator("[data-directory-access-detail]")).to_have_text(CHECKED)

    web_alert = page.locator(WEB_SEARCH_ALERT)
    expect(web_alert).to_be_visible()
    expect(web_alert.locator("[data-directory-access-summary]")).to_have_text(SIGN_IN_SUMMARY)
    assert_fits(alert)
    assert_fits(web_alert)
    assert problems == []


def test_unconfirmed_access_names_the_reason_and_leaves_the_web_search_card_alone(page, static_origin):
    DirectoryCheck(page, ok(report("unverified", sources=("web_search", "deep_research"), reason="directory_check_failed")))
    problems = open_admin_settings(page, static_origin)

    alert = page.locator(ALERT)
    expect(alert).to_be_visible()
    expect_state(alert, "unverified")
    expect(alert).to_contain_text("Microsoft Entra ID access could not be confirmed")
    expect(sources_phrase(alert, "unverified")).to_have_text("web search or deep research")
    expect(alert.locator("[data-directory-access-detail]")).to_have_text(
        re.compile(r"^Reason: directory_check_failed\. Checked \S.*\.$"),
    )
    # The cause is unknown, so the Web Search card does not claim a missing permission.
    expect(page.locator(WEB_SEARCH_ALERT)).to_be_hidden()
    assert problems == []


@pytest.mark.parametrize(
    "result",
    [
        report("not_required", sources=()),
        report("ready"),
        report("hasOwnProperty"),
    ],
    ids=["not-required", "ready", "unknown-status"],
)
def test_no_warning_when_access_is_fine_or_the_result_is_unrecognized(page, static_origin, result):
    check = DirectoryCheck(page, ok(result))
    problems = open_admin_settings(page, static_origin)

    alert = page.locator(ALERT)
    expect(alert).to_be_hidden()
    expect(alert).to_have_class(HIDDEN)
    expect_state(alert, None)
    expect(page.locator(WEB_SEARCH_ALERT)).to_be_hidden()
    assert check.bodies == [{"refresh": False}]
    assert problems == []


def test_web_search_card_stays_quiet_when_web_search_is_not_affected(page, static_origin):
    DirectoryCheck(page, ok(report("permission_missing", sources=("agent_invoke",))))
    problems = open_admin_settings(page, static_origin)

    alert = page.locator(ALERT)
    expect(alert).to_be_visible()
    expect_state(alert, "permission_missing")
    expect(sources_phrase(alert, "permission_missing")).to_have_text("agents")
    expect(page.locator(WEB_SEARCH_ALERT)).to_be_hidden()
    assert problems == []


@pytest.mark.parametrize(
    "status, payload",
    [
        (500, {"success": False, "error": "The directory access check could not be completed."}),
        (502, "<html><body><h1>502 Bad Gateway</h1></body></html>"),
    ],
    ids=["server-error", "gateway-page"],
)
def test_failed_first_check_leaves_the_page_as_it_was(page, static_origin, status, payload):
    check = DirectoryCheck(page, (status, payload))
    problems = open_admin_settings(page, static_origin)

    expect(page.locator(ALERT)).to_be_hidden()
    expect(page.locator(WEB_SEARCH_ALERT)).to_be_hidden()
    assert check.bodies == [{"refresh": False}]
    assert unexpected(problems) == []


def test_failed_check_again_keeps_the_warning_and_offers_another_try(page, static_origin):
    check = DirectoryCheck(
        page,
        ok(report("permission_missing")),
        (500, {"success": False, "error": "The directory access check could not be completed."}),
        ok(report("ready")),
    )
    problems = open_admin_settings(page, static_origin)
    alert = page.locator(ALERT)
    web_alert = page.locator(WEB_SEARCH_ALERT)
    button = alert.get_by_role("button", name="Check again")
    detail = alert.locator("[data-directory-access-detail]")

    with page.expect_response(CHECK_ROUTE):
        button.click()
    expect(detail).to_have_text(RETRY_TEXT)
    expect(button).to_be_enabled()
    expect(alert).to_be_visible()
    expect_state(alert, "permission_missing")
    expect(web_alert).to_be_visible()

    with page.expect_response(CHECK_ROUTE):
        button.click()
    expect(alert).to_be_hidden()
    expect(web_alert).to_be_hidden()
    assert check.bodies == [{"refresh": False}, {"refresh": True}, {"refresh": True}]
    assert unexpected(problems) == []


def test_values_from_the_server_are_shown_as_text(page, static_origin):
    hostile = '<img src="x" onerror="window.__directoryXss = true">'
    DirectoryCheck(page, ok(report(
        "unverified",
        reason=hostile,
        capabilities=[{"id": "constructor", "label": hostile}, {"id": "__proto__", "label": hostile}],
        application_client_id='"><img src="x" onerror="window.__directoryXss = true">',
        graph_resource_app_id=hostile,
        graph_permission_id="not-a-guid",
        checked_at="not a date",
    )))
    problems = open_admin_settings(page, static_origin)

    alert = page.locator(ALERT)
    expect(alert).to_be_visible()
    expect_state(alert, "unverified")
    expect(alert.locator("[data-directory-access-detail]")).to_have_text(f"Reason: {hostile}.")
    phrases = alert.locator("[data-directory-access-capabilities]")
    expect(phrases).to_have_count(len(STATES))
    expect(phrases).to_have_text(["web search or another external source"] * len(STATES))
    # Values that are not GUIDs never reach the command a reader might paste into a terminal.
    assert alert.locator("[data-directory-access-commands]").text_content() == commands("<application-client-id>")
    expect(page.locator(f"{ALERT} img, {WEB_SEARCH_ALERT} img")).to_have_count(0)
    assert page.evaluate("() => window.__directoryXss") is None
    assert problems == []


def test_see_how_to_fix_it_opens_the_chat_orchestration_warning(page, static_origin):
    DirectoryCheck(page, ok(report("permission_missing")))
    problems = open_admin_settings(page, static_origin, active_tabs=("web-research",), card_links=True)

    orchestration_tab = page.locator("#chat-orchestration")
    alert = page.locator(ALERT)
    expect(orchestration_tab).not_to_have_class(ACTIVE)
    expect(alert).to_be_hidden()

    web_alert = page.locator(WEB_SEARCH_ALERT)
    expect(web_alert).to_be_visible()
    web_alert.get_by_role("link", name="See how to fix it").click()

    expect(orchestration_tab).to_have_class(ACTIVE)
    expect(page.locator("#web-research")).not_to_have_class(ACTIVE)
    expect(alert).to_be_visible()
    expect(alert).to_be_in_viewport()
    expect_state(alert, "permission_missing")
    assert problems == []


def test_admin_settings_page_loads_the_module():
    page_template = (APP_ROOT / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    script = re.compile(
        r'<script type="module" src="[^"]*js/admin/admin_orchestration_directory_access\.js[^"]*"></script>'
    )
    assert script.search(page_template)
