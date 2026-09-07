# test_v2_orchestration_approval_persistence.py
"""
Browser regressions for account-level orchestration approval persistence.
Version: 0.261.101
Implemented in: 0.261.101

Drive the real Composer, router and settings store. Only HTTP is replaced: the
settings fixture persists across reloads and fresh browser contexts. Planning
requests are captured and receive a manual pending fixture plan, without running
tools or calling a model. Reuse local/Azure Playwright with DefaultAzureCredential.

Run: python -m pytest ui_tests/test_v2_orchestration_approval_persistence.py -q
"""

import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

# The repository's shared UI fixtures live outside the Python application package.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ui_tests" / "fixtures"))
sys.path.insert(0, str(REPO_ROOT / "ui_tests" / "fixtures" / "orchestration"))

import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402, F401


pytestmark = pytest.mark.ui
ORIGIN = "https://simplechat.test"
HARNESS_PATH = f"/{hb.HARNESS_HTML_REL}"
SETTINGS_PATH = "/api/user/settings"
PLAN_PATH = "/api/v2/orchestration/plan"
CHAT_PATH = "/api/chat/stream"
SETTING = "orchestrationApprovalMode"
LABELS = {"manual": "Review", "timed": "After 8s", "auto": "Auto"}


class ApprovalApi:
    def __init__(self, assets):
        self.assets = assets
        self.settings = {"darkModeEnabled": True}
        self.writes = []
        self.plans = []
        self.chats = []
        self.read_count = 0
        self.read_status = 200
        self.write_status = 200
        self.hold_reads = False
        self.hold_writes = False
        self.pending_reads = []
        self.pending_writes = []
        self.unexpected = []
        self.expected_http_errors = set()
        self.bootstrap = {
            "features": {"enable_chat_orchestration": True},
            "orchestration": {
                "enabled": True,
                "show_manual_controls": True,
                "default_approval_mode": "manual",
                "allow_user_approval_override": True,
                "timed_approval_seconds": 8,
            },
            "branding": {"app_title": "SimpleChat"},
            "catalogs": {"prompts": [], "models": [], "agents": []},
            "settings": {},
            "scope": {"groups": [], "public_workspaces": []},
            "user": {"id": "approval-user", "display_name": "Approval User"},
        }

    def respond(self, route, body, status=200):
        if status >= 400:
            self.expected_http_errors.add((urlsplit(route.request.url).path, status))
        route.fulfill(status=status, json=body)

    def read(self, route):
        self.respond(
            route,
            {"settings": copy.deepcopy(self.settings)}
            if self.read_status == 200 else {"error": "Preferences unavailable"},
            self.read_status,
        )

    def write(self, route, status=None):
        status = self.write_status if status is None else status
        if status == 200:
            self.settings.update(copy.deepcopy(route.request.post_data_json["settings"]))
        self.respond(
            route,
            {"message": "Saved"} if status == 200 else {"error": "Could not save preference"},
            status,
        )

    def release_reads(self):
        pending, self.pending_reads = self.pending_reads, []
        for route in pending:
            self.read(route)

    def release_write(self, status=200):
        self.write(self.pending_writes.pop(0), status)

    def handle(self, route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
        elif path == "/favicon.ico":
            route.fulfill(status=204)
        elif path == SETTINGS_PATH and request.method == "GET":
            self.read_count += 1
            if self.hold_reads:
                self.pending_reads.append(route)
            else:
                self.read(route)
        elif path == SETTINGS_PATH and request.method == "POST":
            self.writes.append(copy.deepcopy(request.post_data_json))
            if self.hold_writes:
                self.pending_writes.append(route)
            else:
                self.write(route)
        elif path == "/api/v2/bootstrap" and request.method == "GET":
            self.respond(route, self.bootstrap)
        elif path == PLAN_PATH and request.method == "POST":
            body = request.post_data_json
            self.plans.append(copy.deepcopy(body))
            event = {
                "type": "orchestration_plan",
                "plan": {
                    "plan_id": "fixture-plan", "run_id": "fixture-run", "turn_id": body["turn_id"],
                    "intent": {"summary": "Approval fixture", "complexity": "simple"},
                    "steps": [{
                        "step_id": "answer", "capability_id": "respond", "title": "Answer",
                        "arguments": {}, "estimated_cost": "low",
                    }],
                    "approval": {"mode": "manual", "timeout_seconds": 0, "state": "pending"},
                    "status": "awaiting_approval",
                },
            }
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")
        elif path == CHAT_PATH and request.method == "POST":
            self.chats.append(copy.deepcopy(request.post_data_json))
            route.fulfill(
                content_type="text/event-stream",
                body='data: {"response":"Fixture answer"}\n\ndata: {"done":true}\n\n',
            )
        elif path == "/api/get_messages" and request.method == "GET":
            self.respond(route, {"messages": []})
        elif path == "/api/conversations/feed" and request.method == "GET":
            self.respond(route, {"conversations": [], "has_more": False})
        else:
            self.unexpected.append(f"{request.method} {path}")
            self.respond(route, {"error": "Unexpected approval fixture request"}, 404)


@pytest.fixture(scope="module")
def approval_assets():
    static_root = REPO_ROOT / "application" / "single_app" / "static"
    index = static_root / "v2" / "index.html"
    assert index.is_file(), "Run the existing v2 npm build before browser coverage."
    assets = {
        HARNESS_PATH: hb.HERE / "harness.html",
        "/ui_tests/fixtures/orchestration/harness.bundle.js": hb.ensure_bundle(),
    }
    styles = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text(encoding="utf-8"))
    assert styles, "The production build must reference its local stylesheet."
    for url in styles:
        parsed = urlsplit(url)
        assert not parsed.netloc and parsed.path.startswith("/static/")
        asset = (static_root / parsed.path.removeprefix("/static/")).resolve()
        assert asset.is_relative_to(static_root.resolve()) and asset.is_file()
        assets[parsed.path] = asset
    return assets


@pytest.fixture(scope="module")
def approval_browser(connect_options):
    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.connect(**connect_options)
            if connect_options else playwright.chromium.launch()
        )
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def approval_ui(approval_browser, approval_assets):
    api = ApprovalApi(approval_assets)
    contexts = []
    errors = []

    def console_error(message):
        if message.type == "error":
            path = urlsplit(message.location.get("url", "")).path
            if not any(
                path == expected_path and f"status of {status}" in message.text
                for expected_path, status in api.expected_http_errors
            ):
                errors.append(message.text)

    def open_page(width=1440):
        context = approval_browser.new_context(viewport={"width": width, "height": 900})
        contexts.append(context)
        page = context.new_page()
        page.route("**/*", api.handle)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", console_error)
        return page

    try:
        yield open_page, api
    finally:
        for context in contexts:
            context.close()
        assert not api.unexpected, f"Unexpected requests: {api.unexpected}"
        assert not errors, f"Unexpected browser errors: {errors}"


def mount(page, api):
    response = page.goto(f"{ORIGIN}{HARNESS_PATH}", wait_until="domcontentloaded")
    assert response and response.ok
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for path in api.assets:
        if path.endswith(".css"):
            page.add_style_tag(url=f"{ORIGIN}{path}")
    page.evaluate(
        """(bootstrap) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: bootstrap });
            H.stores.chat.useChatStore.setState({
                activeConversationId: 'approval-chat',
                activeConversationKind: 'personal',
                conversations: [{ id: 'approval-chat', title: 'Approval preferences' }],
                streaming: false,
                messagesLoading: false,
            });
            void H.stores.userSettings.useUserSettingsStore.getState().load();
            H.mount('mount-a', 'ApprovalPreferenceWorkflow', {}, { initialEntries: ['/chat'] });
        }""",
        api.bootstrap,
    )
    expect(message_box(page)).to_be_visible()


def message_box(page):
    return page.get_by_role("textbox", name="Message", exact=True)


def approval_picker(page):
    return page.get_by_title("Approval mode", exact=True)


def send_button(page):
    return page.get_by_role("button", name="Send message", exact=True)


def settings_response(response):
    return urlsplit(response.url).path == SETTINGS_PATH and response.request.method == "POST"


def choose(page, mode, wait=True):
    def click_option():
        approval_picker(page).click()
        page.get_by_role("option", name=re.compile(f"^{re.escape(LABELS[mode])}")).click()

    if wait:
        with page.expect_response(settings_response):
            click_option()
    else:
        click_option()


def refresh_policy(page, api, **changes):
    api.bootstrap["orchestration"].update(changes)
    page.evaluate("() => window.OrchHarness.stores.bootstrap.useBootstrapStore.getState().refresh()")


def send(page, path=PLAN_PATH):
    message_box(page).fill("Use my selected approval mode.")
    with page.expect_response(lambda response: urlsplit(response.url).path == path):
        send_button(page).click()


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("mode", ["auto", "timed", "manual"])
def test_choice_is_saved_without_sending_and_survives_navigation(approval_ui, width, mode):
    open_page, api = approval_ui
    api.bootstrap["orchestration"]["default_approval_mode"] = "manual" if mode == "auto" else "auto"
    page = open_page(width)
    mount(page, api)
    expect(approval_picker(page)).to_be_enabled()
    choose(page, mode)
    expect(approval_picker(page)).to_contain_text(LABELS[mode])
    assert api.writes == [{"settings": {SETTING: mode}}]
    assert not api.plans
    page.get_by_role("link", name="Leave chat", exact=True).click()
    expect(page.get_by_text("Away from chat", exact=True)).to_be_visible()
    page.get_by_role("link", name="Return to chat", exact=True).click()
    expect(approval_picker(page)).to_contain_text(LABELS[mode])
    page.evaluate(
        "() => window.OrchHarness.stores.chat.useChatStore.setState({ activeConversationId: 'other-chat' })"
    )
    send(page)
    assert api.plans[-1]["approval_mode"] == mode
    assert api.plans[-1]["conversation_id"] == "other-chat"
    assert api.settings["darkModeEnabled"] is True


@pytest.mark.parametrize("mode", ["auto", "timed", "manual"])
def test_reload_and_fresh_context_restore_from_account_settings(approval_ui, mode):
    open_page, api = approval_ui
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_be_enabled()
    choose(page, mode)
    for current_page in (page, open_page()):
        mount(current_page, api)
        expect(approval_picker(current_page)).to_contain_text(LABELS[mode])
        assert api.settings[SETTING] == mode
    assert api.read_count == 3
    assert api.writes == [{"settings": {SETTING: mode}}]


def test_leaving_chat_does_not_cancel_an_unacknowledged_save(approval_ui):
    open_page, api = approval_ui
    api.hold_writes = True
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_be_enabled()
    with page.expect_request(lambda request: urlsplit(request.url).path == SETTINGS_PATH):
        choose(page, "auto", wait=False)
    page.get_by_role("link", name="Leave chat", exact=True).click()
    expect(page.get_by_text("Away from chat", exact=True)).to_be_visible()
    with page.expect_response(settings_response):
        api.release_write()
    page.get_by_role("link", name="Return to chat", exact=True).click()
    expect(approval_picker(page)).to_contain_text("Auto")
    mount(page, api)
    expect(approval_picker(page)).to_contain_text("Auto")
    assert api.settings[SETTING] == "auto"


def test_admin_refresh_and_lockout_do_not_erase_saved_choice(approval_ui):
    open_page, api = approval_ui
    api.settings[SETTING] = "timed"
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_contain_text(LABELS["timed"])
    refresh_policy(page, api, default_approval_mode="auto")
    expect(approval_picker(page)).to_contain_text(LABELS["timed"])
    refresh_policy(page, api, allow_user_approval_override=False)
    expect(approval_picker(page)).to_have_count(0)
    send(page)
    assert api.plans[-1]["approval_mode"] == "auto"
    refresh_policy(page, api, allow_user_approval_override=True, default_approval_mode="manual")
    expect(approval_picker(page)).to_contain_text(LABELS["timed"])
    assert api.settings[SETTING] == "timed"
    assert not api.writes


@pytest.mark.parametrize("mode", ["auto", "timed", "manual"])
def test_default_is_used_without_creating_a_user_choice(approval_ui, mode):
    open_page, api = approval_ui
    api.bootstrap["orchestration"]["default_approval_mode"] = mode
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_contain_text(LABELS[mode])
    send(page)
    assert api.plans[-1]["approval_mode"] == mode
    assert SETTING not in api.settings
    assert not api.writes


def test_slow_settings_load_blocks_mouse_and_keyboard_submission(approval_ui):
    open_page, api = approval_ui
    api.settings[SETTING] = "manual"
    api.bootstrap["orchestration"]["default_approval_mode"] = "auto"
    api.hold_reads = True
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_be_disabled()
    message_box(page).fill("Do not run before my preference arrives.")
    expect(send_button(page)).to_be_disabled()
    message_box(page).press("Enter")
    expect(page.get_by_role("status").filter(has_text="Loading your approval preference")).to_be_visible()
    assert not api.plans
    assert len(api.pending_reads) == 1
    api.release_reads()
    expect(approval_picker(page)).to_contain_text("Review")
    expect(send_button(page)).to_be_enabled()
    expect(message_box(page)).to_have_value("Do not run before my preference arrives.")
    send(page)
    assert api.plans[-1]["approval_mode"] == "manual"


def test_failed_load_retries_without_losing_the_draft(approval_ui):
    open_page, api = approval_ui
    api.settings[SETTING] = "timed"
    api.read_status = 500
    page = open_page()
    mount(page, api)
    retry = page.get_by_role("button", name="Retry loading approval preference", exact=True)
    expect(retry).to_be_visible()
    message_box(page).fill("Keep this draft.")
    message_box(page).press("Enter")
    expect(send_button(page)).to_be_disabled()
    assert not api.plans
    api.read_status = 200
    retry.click()
    expect(approval_picker(page)).to_contain_text(LABELS["timed"])
    expect(send_button(page)).to_be_enabled()
    expect(message_box(page)).to_have_value("Keep this draft.")
    expect(retry).to_have_count(0)


@pytest.mark.parametrize("invalid", ["future-mode", None])
def test_invalid_stored_mode_requires_a_valid_replacement(approval_ui, invalid):
    open_page, api = approval_ui
    api.settings[SETTING] = invalid
    api.bootstrap["orchestration"]["default_approval_mode"] = "auto"
    page = open_page()
    mount(page, api)
    warning = page.get_by_role("alert").filter(has_text="saved approval preference is invalid")
    expect(warning).to_be_visible()
    message_box(page).fill("Wait for a deliberate approval choice.")
    expect(send_button(page)).to_be_disabled()
    expect(approval_picker(page)).to_be_enabled()
    choose(page, "manual")
    expect(warning).to_have_count(0)
    expect(send_button(page)).to_be_enabled()
    assert api.settings[SETTING] == "manual"


def test_failed_save_is_visible_and_restores_confirmed_choice(approval_ui):
    open_page, api = approval_ui
    api.settings[SETTING] = "manual"
    api.write_status = 500
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_be_enabled()
    choose(page, "auto")
    expect(page.get_by_role("alert").filter(has_text="Could not save preference")).to_be_visible()
    expect(approval_picker(page)).to_contain_text("Review")
    assert api.settings[SETTING] == "manual"
    api.write_status = 200
    choose(page, "auto")
    expect(page.get_by_role("alert")).to_have_count(0)
    mount(page, api)
    expect(approval_picker(page)).to_contain_text("Auto")


def test_older_failed_save_cannot_overwrite_a_newer_selection(approval_ui):
    open_page, api = approval_ui
    api.settings[SETTING] = "manual"
    api.hold_writes = True
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_be_enabled()
    with page.expect_request(lambda request: urlsplit(request.url).path == SETTINGS_PATH):
        choose(page, "auto", wait=False)
    choose(page, "timed", wait=False)
    expect(approval_picker(page)).to_contain_text(LABELS["timed"])
    assert len(api.writes) == 1
    with page.expect_request(lambda request: urlsplit(request.url).path == SETTINGS_PATH):
        api.release_write(500)
    expect(approval_picker(page)).to_contain_text(LABELS["timed"])
    with page.expect_response(settings_response):
        api.release_write()
    expect(page.get_by_role("alert")).to_have_count(0)
    assert api.settings[SETTING] == "timed"
    mount(page, api)
    expect(approval_picker(page)).to_contain_text(LABELS["timed"])


def test_admin_enforced_mode_does_not_wait_for_unused_preference(approval_ui):
    open_page, api = approval_ui
    api.settings[SETTING] = "auto"
    api.read_status = 500
    api.bootstrap["orchestration"].update({
        "allow_user_approval_override": False, "default_approval_mode": "timed",
    })
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_have_count(0)
    send(page)
    assert api.plans[-1]["approval_mode"] == "timed"
    assert api.settings[SETTING] == "auto"


def test_ordinary_chat_stays_available_when_preferences_fail(approval_ui):
    open_page, api = approval_ui
    api.read_status = 500
    page = open_page()
    mount(page, api)
    expect(page.get_by_role("button", name="Retry loading approval preference")).to_be_visible()
    page.get_by_role("button", name="Orchestrate", exact=True).click()
    send(page, CHAT_PATH)
    assert len(api.chats) == 1
    assert not api.plans


def test_changing_preference_leaves_existing_plan_approval_unchanged(approval_ui):
    open_page, api = approval_ui
    page = open_page()
    mount(page, api)
    expect(approval_picker(page)).to_be_enabled()
    existing = {"plan_id": "existing", "approval": {"mode": "manual", "state": "pending"}}
    page.evaluate(
        "(plan) => window.OrchHarness.stores.orchestration.useOrchestrationStore.setState({ plans: { existing: plan } })",
        existing,
    )
    choose(page, "auto")
    assert page.evaluate(
        "() => window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().plans.existing"
    ) == existing
