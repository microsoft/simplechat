# test_v2_conversation_mode_persistence.py
"""
Real-Composer browser regressions for explicit per-conversation mode choices.
Version: 0.261.341
Implemented in: 0.261.341

Use the existing local/Azure Playwright connection, production CSS, real stores,
router and Composer. Only HTTP is replaced; no models, tools or deliveries run.
Run: python -m pytest -q ui_tests/test_v2_conversation_mode_persistence.py
"""

import copy
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ui_tests" / "fixtures"))
sys.path.insert(0, str(REPO_ROOT / "ui_tests" / "fixtures" / "orchestration"))

import harness_build as hb  # noqa: E402
from composer_helpers import open_composer_tools  # noqa: E402
from playwright_connection import connect_options  # noqa: E402, F401
from test_v2_orchestration_approval_persistence import (  # noqa: E402
    ApprovalApi,
    CHAT_PATH,
    HARNESS_PATH,
    ORIGIN,
    approval_assets,
    approval_browser,
    message_box,
    send_button,
)


pytestmark = pytest.mark.ui
MODE_PREFIX = "simplechat:v2:conversation-mode:"


class ModeApi(ApprovalApi):
    def __init__(self, assets):
        super().__init__(assets)
        self.bootstrap["user"] = {"id": "mode-user", "display_name": "Mode User"}
        self.creations = []
        self.pending_creations = []
        self.hold_creation = False

    def finish_creation(self, route, conversation_id):
        self.respond(route, {"conversation_id": conversation_id, "title": "Mode test"})

    def handle(self, route):
        path = urlsplit(route.request.url).path
        if path == "/api/create_conversation" and route.request.method == "POST":
            conversation_id = f"mode-created-{len(self.creations) + 1}"
            self.creations.append(copy.deepcopy(route.request.post_data_json))
            if self.hold_creation:
                self.pending_creations.append((route, conversation_id))
            else:
                self.finish_creation(route, conversation_id)
        elif path.startswith("/api/chat/stream/status/"):
            self.respond(route, {"active": False, "pending": False, "reattachable": False})
        elif path.startswith("/api/conversations/") and path.endswith("/metadata"):
            self.respond(route, {})
        elif path.startswith("/api/conversations/") and route.request.method == "DELETE":
            self.respond(route, {"success": True})
        elif path == "/logout":
            route.fulfill(status=204)
        else:
            super().handle(route)


@pytest.fixture
def mode_ui(approval_browser, approval_assets):
    api = ModeApi(approval_assets)
    context = approval_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.route("**/*", api.handle)
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, f"Unexpected requests: {api.unexpected}"
        assert not errors, f"Unexpected browser errors: {errors}"


def mount(page, api, conversation_id="mode-a", fresh=True, bootstrap=True, component="ApprovalPreferenceWorkflow"):
    response = page.goto(f"{ORIGIN}{HARNESS_PATH}", wait_until="domcontentloaded")
    assert response and response.ok
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for path in api.assets:
        if path.endswith(".css"):
            page.add_style_tag(url=f"{ORIGIN}{path}")
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            if (spec.fresh) H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: spec.bootstrap });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversationId,
                activeConversationKind: 'personal',
                conversations: ['mode-a', 'mode-b'].map(id => ({ id, title: id })),
                streaming: false, messagesLoading: false,
            });
            H.stores.userSettings.useUserSettingsStore.setState({
                settings: {}, loading: false, error: null,
            });
            H.mount('mount-a', spec.component, {}, { initialEntries: ['/chat'] });
        }""",
        {"fresh": fresh, "bootstrap": api.bootstrap if bootstrap else None,
         "conversationId": conversation_id, "component": component},
    )
    expect(message_box(page)).to_be_visible()
    open_composer_tools(page)


def toggle(page):
    open_composer_tools(page)
    return page.get_by_role("button", name="Orchestrate", exact=True)


def assert_mode(page, enabled):
    expect(toggle(page)).to_have_attribute("aria-pressed", str(enabled).lower())


def select_conversation(page, conversation_id):
    page.evaluate(
        "(id) => window.OrchHarness.stores.chat.useChatStore.getState().selectConversation(id, { kind: 'personal' })",
        conversation_id,
    )
    expect(message_box(page)).to_be_visible()
    open_composer_tools(page)


def start_new(page):
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    open_composer_tools(page)


def stored_choices(page):
    return page.evaluate(
        "(prefix) => Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith(prefix)))",
        MODE_PREFIX,
    )


def send_direct(page, text="Keep this question in direct chat."):
    message_box(page).fill(text)
    with page.expect_response(lambda response: urlsplit(response.url).path == CHAT_PATH):
        message_box(page).press("Enter")
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    expect(page.get_by_role("button", name="Stop generating", exact=True)).to_have_count(0)


@pytest.mark.parametrize("width", [1440, 390])
def test_off_survives_navigation_reload_and_keyboard_submission(mode_ui, width):
    page, api = mode_ui
    page.set_viewport_size({"width": width, "height": 900})
    mount(page, api)
    assert_mode(page, True)
    assert stored_choices(page) == {}, "the deployment default is not a saved user choice"
    control = toggle(page)
    control.focus()
    control.press("Space")
    assert_mode(page, False)
    expect(control).to_be_focused()
    send_direct(page)
    assert len(api.chats) == 1 and not api.plans

    page.get_by_role("link", name="Leave chat", exact=True).click()
    expect(message_box(page)).to_have_count(0)
    page.get_by_role("link", name="Return to chat", exact=True).click()
    assert_mode(page, False)
    assert len(api.chats) == 1 and not api.plans, "remounting never replays a submission"
    send_direct(page, "Direct after navigating back.")
    page.reload(wait_until="domcontentloaded")
    mount(page, api, fresh=False)
    assert_mode(page, False)
    assert len(api.chats) == 2 and not api.plans, "reload never replays a submission"
    send_direct(page, "Direct after reloading.")
    assert len(api.chats) == 3 and not api.plans
    assert all(request["conversation_id"] == "mode-a" for request in api.chats)


def test_separate_conversations_and_accounts_never_share_a_choice(mode_ui):
    page, api = mode_ui
    mount(page, api)
    toggle(page).click()
    assert_mode(page, False)
    select_conversation(page, "mode-b")
    assert_mode(page, True)
    assert len(stored_choices(page)) == 1
    toggle(page).click()
    toggle(page).click()
    assert_mode(page, True)
    select_conversation(page, "mode-a")
    assert_mode(page, False)
    select_conversation(page, "mode-b")
    assert_mode(page, True)

    bob = copy.deepcopy(api.bootstrap)
    bob["user"]["id"] = "other-account"
    page.evaluate("(data) => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({ data })", bob)
    assert_mode(page, True)
    toggle(page).click()
    assert_mode(page, False)
    page.evaluate("(data) => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({ data })", api.bootstrap)
    assert_mode(page, True)
    select_conversation(page, "mode-a")
    assert_mode(page, False)
    start_new(page)
    assert_mode(page, True)
    assert not api.chats and not api.plans


def test_late_bootstrap_and_thread_switch_resolve_the_current_identity_only(mode_ui):
    page, api = mode_ui
    mount(page, api, bootstrap=False)
    expect(page.get_by_role("button", name="Orchestrate", exact=True)).to_have_count(0)
    page.evaluate(
        """(prefix) => {
            localStorage.setItem(prefix + 'mode-user:mode-a', 'on');
            localStorage.setItem(prefix + 'mode-user:mode-b', 'off');
            window.OrchHarness.stores.chat.useChatStore.setState({ activeConversationId: 'mode-b' });
        }""",
        MODE_PREFIX,
    )
    page.evaluate("(data) => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({ data })", api.bootstrap)
    assert_mode(page, False)
    send_direct(page)
    assert api.chats[0]["conversation_id"] == "mode-b"
    select_conversation(page, "mode-a")
    assert_mode(page, True)
    assert len(api.chats) == 1 and not api.plans


def test_explicit_draft_choices_migrate_for_direct_and_orchestration_creation(mode_ui):
    page, api = mode_ui
    mount(page, api, conversation_id=None)
    toggle(page).click()
    assert_mode(page, False)
    page.get_by_role("link", name="Leave chat", exact=True).click()
    page.get_by_role("link", name="Return to chat", exact=True).click()
    assert_mode(page, False)
    send_direct(page)
    assert_mode(page, False)
    assert api.chats[0]["conversation_id"] == "mode-created-1"
    assert stored_choices(page) == {f"{MODE_PREFIX}mode-user:mode-created-1": "off"}

    start_new(page)
    assert_mode(page, True)
    toggle(page).click()
    toggle(page).click()
    message_box(page).fill("Prepare a plan, but do not run it.")
    with page.expect_response(lambda response: urlsplit(response.url).path == "/api/v2/orchestration/plan"):
        send_button(page).click()
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    assert api.plans[0]["conversation_id"] == "mode-created-2"
    assert_mode(page, True)
    assert stored_choices(page)[f"{MODE_PREFIX}mode-user:mode-created-2"] == "on"
    start_new(page)
    assert_mode(page, True)
    select_conversation(page, "mode-created-1")
    assert_mode(page, False)
    assert len(api.chats) == 1 and len(api.plans) == 1


def test_late_creation_cannot_consume_another_new_chats_choice(mode_ui):
    page, api = mode_ui
    mount(page, api, conversation_id=None)
    toggle(page).click()
    api.hold_creation = True
    message_box(page).fill("Direct from the first draft.")
    with page.expect_request(lambda request: urlsplit(request.url).path == "/api/create_conversation"):
        send_button(page).click()
    expect(message_box(page)).to_have_value("")
    assert len(api.pending_creations) == 1
    start_new(page)
    assert_mode(page, True)
    toggle(page).click()
    toggle(page).click()
    route, conversation_id = api.pending_creations.pop()
    with page.expect_response(lambda response: urlsplit(response.url).path == CHAT_PATH):
        api.finish_creation(route, conversation_id)
    assert_mode(page, True)
    current = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId")
    assert current is None
    select_conversation(page, conversation_id)
    assert_mode(page, False)
    assert len(api.chats) == 1 and not api.plans


def test_forced_modes_do_not_overwrite_the_saved_choice(mode_ui):
    page, api = mode_ui
    api.bootstrap["catalogs"]["agents"] = [{"id": "selected-agent", "name": "Selected agent"}]
    mount(page, api)
    toggle(page).click()
    toggle(page).click()
    original = stored_choices(page)
    disabled = copy.deepcopy(api.bootstrap)
    disabled["features"]["enable_chat_orchestration"] = False
    page.evaluate("(data) => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({ data })", disabled)
    expect(page.get_by_role("button", name="Orchestrate", exact=True)).to_have_count(0)
    expect(page.get_by_title("Documents", exact=True)).to_be_visible()
    send_direct(page, "Capability policy requires direct chat without changing my saved choice.")
    page.evaluate("(data) => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({ data })", api.bootstrap)
    assert_mode(page, True)

    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.mount('mount-a', 'Composer', { initialAgentSelection: 'selected-agent' });
        }"""
    )
    assert_mode(page, False)
    assert stored_choices(page) == original
    send_direct(page, "Ask the selected agent directly.")
    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.mount('mount-a', 'Composer');
        }"""
    )
    assert_mode(page, True)
    page.evaluate(
        """() => window.OrchHarness.stores.chat.useChatStore.setState({
            analysisResultContext: {
                conversation_id: 'mode-a', analysis_id: 'saved-analysis',
                title: 'Saved analysis', status: 'completed',
            },
        })"""
    )
    assert_mode(page, False)
    assert stored_choices(page) == original
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().clearAnalysisResultContext()")
    assert_mode(page, True)
    page.evaluate(
        """() => window.OrchHarness.stores.chat.useChatStore.setState({
            workflowResultContext: { conversation_id: 'mode-a', descriptor: { title: 'Stored workflow result' } },
        })"""
    )
    assert_mode(page, False)
    assert stored_choices(page) == original
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().clearWorkflowResultContext()")
    assert_mode(page, True)
    assert len(api.chats) == 2 and not api.plans


def test_storage_failure_is_visible_and_keeps_the_current_choice_usable(mode_ui):
    page, api = mode_ui
    mount(page, api)
    page.evaluate(
        """() => {
            window.restoreModeStorage = Storage.prototype.setItem;
            Storage.prototype.setItem = () => { throw new DOMException('Blocked', 'QuotaExceededError'); };
            window.OrchHarness.mount('mount-b', 'Toaster');
        }"""
    )
    message_box(page).fill("Preserve this draft when saving fails.")
    toggle(page).click()
    assert_mode(page, False)
    expect(page.get_by_role("alert").filter(has_text="mode choice could not be saved")).to_be_visible()
    expect(message_box(page)).to_have_value("Preserve this draft when saving fails.")
    page.get_by_role("link", name="Leave chat", exact=True).click()
    page.get_by_role("link", name="Return to chat", exact=True).click()
    assert_mode(page, False)
    send_direct(page)
    page.evaluate("() => { Storage.prototype.setItem = window.restoreModeStorage; }")
    assert not stored_choices(page)
    assert len(api.chats) == 1 and not api.plans


def test_successful_deletion_prunes_only_that_conversations_preference(mode_ui):
    page, api = mode_ui
    mount(page, api)
    toggle(page).click()
    select_conversation(page, "mode-b")
    toggle(page).click()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().removeConversation('mode-a')")
    assert stored_choices(page) == {f"{MODE_PREFIX}mode-user:mode-b": "off"}
    assert_mode(page, False)


def test_storage_read_failure_is_announced_and_does_not_block_an_explicit_choice(mode_ui):
    page, api = mode_ui
    mount(page, api)
    page.evaluate(
        """() => {
            window.restoreModeRead = Storage.prototype.getItem;
            Storage.prototype.getItem = () => { throw new DOMException('Blocked', 'SecurityError'); };
            window.OrchHarness.mount('mount-b', 'Toaster');
        }"""
    )
    select_conversation(page, "unread-mode")
    assert_mode(page, True)
    expect(page.get_by_role("alert").filter(has_text="mode choice could not be read")).to_be_visible()
    toggle(page).click()
    assert_mode(page, False)
    send_direct(page)
    page.evaluate("() => { Storage.prototype.getItem = window.restoreModeRead; }")
    assert stored_choices(page) == {f"{MODE_PREFIX}mode-user:unread-mode": "off"}
    assert len(api.chats) == 1 and not api.plans


def test_sign_out_clears_this_accounts_modes_and_invalidates_the_runtime(mode_ui):
    page, api = mode_ui
    mount(page, api)
    toggle(page).click()
    page.evaluate(
        """(prefix) => {
            localStorage.setItem(prefix + 'other-account:mode-a', 'off');
            window.OrchHarness.mount('mount-b', 'Sidebar');
        }""",
        MODE_PREFIX,
    )
    page.locator('#mount-b [data-tour="user-menu"]').click()
    with page.expect_request(lambda request: urlsplit(request.url).path == "/logout"):
        page.get_by_role("link", name="Sign out", exact=True).click()
    assert stored_choices(page) == {f"{MODE_PREFIX}other-account:mode-a": "off"}
    assert_mode(page, True)
    assert not api.chats and not api.plans
