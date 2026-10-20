# test_chat_action_recovery.py
"""
Explicit action recovery in both production chat transports and UI surfaces.
Version: 0.261.356
Implemented in: 0.261.347

Uses the shared Azure Playwright/DefaultAzureCredential connection or local
browser fallback. All requests are intercepted; nothing reaches Graph or a model.
"""

from pathlib import Path
import sys

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from action_recovery import RecoveryFixture, REQUEST
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.fixture(params=["classic", "v2"])
def recovery(page, request):
    fixture = RecoveryFixture(page, request.param)
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize("width", [390, 1440])
def test_unavailable_actions_require_consent_and_do_not_replay(recovery, width):
    page = recovery.page
    page.set_viewport_size({"width": width, "height": 900})
    recovery.open()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    dialog = page.get_by_role("dialog", name="This agent has unavailable actions")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("All assigned actions are unavailable.", exact=False)).to_be_visible()
    expect(dialog.get_by_role("link", name="Open action in a new tab")).to_have_attribute(
        "href", "/v2/workspace/actions/action-1")
    assert recovery.sends == []
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if recovery.flavour == "classic":
        expect(dialog.get_by_role("button", name="Cancel / choose another agent", exact=True)).to_be_focused()
    # Inspect a screenshot only once for each desktop/mobile surface.
    artifact = Path(__file__).resolve().parent / "artifacts" / "action_recovery"
    artifact.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifact / f"{recovery.flavour}-{width}.png"))
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page.locator("#fixture-send")).to_be_focused()
    assert recovery.sends == []
    expect(page.get_by_role("region", name="Unavailable actions")).to_be_visible()
    storage = page.evaluate("JSON.stringify({...sessionStorage})")
    assert "Private unsent fixture message" not in storage
    page.get_by_role("button", name="Recheck and send preserved request").click()
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Continue without these actions", exact=True).click()
    recovery.wait_complete()
    assert len(recovery.sends) == 1
    sent = recovery.sends[0]
    assert sent["body"]["action_recovery"] == {"id": "incident-1", "decision": "continue"}
    assert sent["headers"]["x-csrftoken"] == "fixture-csrf"


def test_reports_are_user_triggered_and_delivery_uncertainty_is_visible(recovery):
    page = recovery.page
    recovery.open()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    dialog = page.get_by_role("dialog", name="This agent has unavailable actions")
    expect(dialog).to_be_visible()
    assert not any(item["path"].endswith("/report") for item in recovery.requests)
    recovery.report_status = 503
    dialog.get_by_role("button", name="Notify owner/admin").click()
    expect(dialog.get_by_text("Delivery uncertain. Retry safely.")).to_be_visible()
    assert "PRIVATE-provider" not in page.locator("body").inner_text()
    recovery.report_status = 200
    dialog.get_by_role("button", name="Notify owner/admin").click()
    expect(dialog.get_by_role("button", name="Reported", exact=True)).to_be_disabled()
    reports = [item for item in recovery.requests if item["path"].endswith("/report")]
    assert len(reports) == 2
    assert reports[0]["body"] == reports[1]["body"] == {"action_key": "a" * 64}
    assert recovery.sends == []


def test_editor_links_are_constrained_and_strings_are_never_html(recovery):
    recovery.incident["actions"][0]["name"] = '<img src=x onerror="window.__injected=true">'
    recovery.incident["actions"][0]["edit_url"] = "https://untrusted.invalid/"
    recovery.incident["actions"][0]["can_report"] = False
    recovery.open()
    recovery.page.get_by_role("button", name="Send fixture", exact=True).click()
    dialog = recovery.page.get_by_role("dialog", name="This agent has unavailable actions")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("link")).to_have_count(0)
    expect(dialog.get_by_role("button", name="Notify owner/admin")).to_have_count(0)
    assert dialog.locator("img").count() == 0
    assert recovery.page.evaluate("window.__injected === undefined")


def test_restored_healthy_request_stays_unsent_until_explicitly_rechecked(recovery):
    page = recovery.page
    recovery.open()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    dialog = page.get_by_role("dialog", name="This agent has unavailable actions")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel / choose another agent", exact=True).click()
    expect(dialog).to_be_hidden()
    recovery.health = "ready"
    recovery.open()
    notice = page.get_by_role("region", name="Unavailable actions")
    expect(notice).to_be_visible()
    expect(notice.get_by_text("Actions are available again.", exact=False)).to_be_visible()
    assert recovery.sends == []
    notice.get_by_role("button", name="Recheck and send preserved request").click()
    recovery.wait_complete()
    assert len(recovery.sends) == 1
    assert "action_recovery" not in recovery.sends[0]["body"]


def test_authoritative_recovery_frame_does_not_trigger_transport_retry(recovery):
    recovery.health = "ready"
    recovery.stream_outcome = "recovery"
    recovery.open()
    recovery.page.get_by_role("button", name="Send fixture", exact=True).click()
    expect(recovery.page.get_by_role("region", name="Unavailable actions")).to_be_visible()
    assert len(recovery.sends) == 1
    assert not any("stream/status" in item["path"] for item in recovery.requests)


def test_agent_change_invalidates_an_open_decision(recovery):
    page = recovery.page
    recovery.open()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    dialog = page.get_by_role("dialog", name="This agent has unavailable actions")
    expect(dialog).to_be_visible()
    recovery.change_agent()
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("region", name="Unavailable actions")).to_have_count(0)
    assert recovery.sends == []


def test_late_availability_response_cannot_attach_to_a_new_agent(recovery):
    recovery.defer_health = True
    page = recovery.page
    recovery.open()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    page.wait_for_function("window.__healthHeld === true")
    recovery.change_agent()
    # Wait for React's effect cleanup, not just its scheduled render.
    if recovery.flavour == "v2":
        page.wait_for_function("window.OrchHarness.actionRecovery.getActionRecovery() === null")
    route = recovery.pending_health.pop()
    recovery._json(route, recovery.incident)
    page.wait_for_function("window.__settled === true")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("region", name="Unavailable actions")).to_have_count(0)
    assert recovery.sends == []


@pytest.mark.parametrize("change", ["agent", "conversation"])
def test_late_authoritative_recovery_does_not_restore_an_old_context(recovery, change):
    recovery.health = "ready"
    recovery.defer_stream = True
    recovery.open()
    page = recovery.page
    page.get_by_role("button", name="Send fixture", exact=True).click()
    page.wait_for_function("window.__streamHeld === true")
    if change == "agent":
        recovery.change_agent()
    else:
        recovery.change_conversation()
    recovery.release_stream()
    expect(page.get_by_role("region", name="Unavailable actions")).to_have_count(0)
    assert len(recovery.sends) == 1
    assert not any("stream/status" in item["path"] for item in recovery.requests)


def test_availability_service_error_preserves_the_unsent_message(recovery):
    recovery.health = "error"
    recovery.open()
    page = recovery.page
    page.get_by_role("button", name="Send fixture", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Action availability could not be confirmed")).to_be_visible()
    details = page.get_by_text("Preserved unsent message", exact=True)
    if details.count():
        details.click()
    expect(page.get_by_text(REQUEST["message"], exact=True)).to_be_visible()
    assert recovery.sends == []


def test_v2_actor_change_rejects_a_late_recovery_frame(page):
    recovery = RecoveryFixture(page, "v2")
    recovery.health = "ready"
    recovery.defer_stream = True
    recovery.open()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    page.wait_for_function("window.__streamHeld === true")
    page.evaluate("""() => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({
        data: {user: {id: 'actor-2'}}
    })""")
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    recovery.release_stream()
    expect(page.get_by_role("region", name="Unavailable actions")).to_have_count(0)
    assert len(recovery.sends) == 1
    recovery.assert_clean()


@pytest.mark.parametrize("hold_context", [False, True])
def test_v2_first_send_adopts_its_conversation_without_invalidating_preflight(page, hold_context):
    recovery = RecoveryFixture(page, "v2")
    recovery.health = "ready"
    recovery.defer_context = hold_context
    recovery.open_new_chat()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    if hold_context:
        page.wait_for_function("""() => window.OrchHarness.stores.chat.useChatStore
            .getState().activeConversationId === 'conversation-1'""")
        page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        page.wait_for_function("window.__contextHeld === true")
        assert len(recovery.pending_context) == 1
        recovery._json(recovery.pending_context.pop(), {"csrf_token": "fixture-csrf"})
    page.wait_for_function("window.__settled === true")
    state = page.evaluate("""() => {
        const state = window.OrchHarness.stores.chat.useChatStore.getState();
        return {error: state.streamError, conversation: state.activeConversationId};
    }""")
    assert state == {"error": None, "conversation": "conversation-1"}
    assert len(recovery.sends) == 1
    health = [item for item in recovery.requests if item["path"] == "/api/chat/action-health"]
    assert len(health) == 1
    assert health[0]["body"]["request"]["conversation_id"] == "conversation-1"
    recovery.assert_clean()


def change_v2_context(recovery, change):
    page = recovery.page
    if change == "agent":
        recovery.change_agent()
    elif change == "actor":
        page.evaluate("""() => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({
            data: {user: {id: 'actor-2'}}
        })""")
    elif change == "conversation":
        page.evaluate("""() => { void window.OrchHarness.stores.chat.useChatStore.getState()
            .selectConversation('conversation-2', {kind: 'personal'}); }""")
    elif change == "new_chat":
        page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    elif change == "stop":
        page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().stopStreaming()")
    else:
        page.evaluate("""() => {
            window.__unsubscribeRecoveryFixture();
            window.OrchHarness.unmount('mount-a');
        }""")
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


@pytest.mark.parametrize("change", ["agent", "actor", "conversation", "new_chat", "stop", "unmount"])
def test_v2_late_creation_cannot_start_preflight_after_leaving_its_context(page, change):
    recovery = RecoveryFixture(page, "v2")
    recovery.defer_creation = True
    recovery.open_new_chat()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    page.wait_for_function("window.__sending !== undefined")
    assert len(recovery.pending_creation) == 1
    change_v2_context(recovery, change)
    recovery._json(recovery.pending_creation.pop(), {"conversation_id": "conversation-1"})
    page.wait_for_function("window.__settled === true")
    result = page.evaluate("window.__sending")
    assert result is False
    active = page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId")
    assert active == ("conversation-2" if change == "conversation" else None)
    assert not any(item["path"] in {"/api/chat/action-health", "/api/chat/stream"} for item in recovery.requests)
    recovery.assert_clean()


@pytest.mark.parametrize("change", ["agent", "actor", "conversation", "new_chat", "stop", "unmount"])
def test_v2_late_csrf_context_cannot_admit_a_stale_send(page, change):
    recovery = RecoveryFixture(page, "v2")
    recovery.health = "ready"
    recovery.defer_context = True
    recovery.open_new_chat()
    page.get_by_role("button", name="Send fixture", exact=True).click()
    page.wait_for_function("window.__contextHeld === true")
    change_v2_context(recovery, change)
    recovery._json(recovery.pending_context.pop(), {"csrf_token": "fixture-csrf"})
    page.wait_for_function("window.__settled === true")
    assert not any(item["path"] in {"/api/chat/action-health", "/api/chat/stream"} for item in recovery.requests)
    expect(page.get_by_role("dialog")).to_have_count(0)
    recovery.assert_clean()


@pytest.mark.parametrize("stage", ["creation", "csrf"])
@pytest.mark.parametrize("new_draft", [False, True])
def test_v2_composer_preserves_unsent_text_without_overwriting_a_new_draft(page, stage, new_draft):
    recovery = RecoveryFixture(page, "v2")
    recovery.defer_creation = stage == "creation"
    recovery.defer_context = stage == "csrf"
    recovery.health = "ready"
    recovery.open_new_chat()
    page.evaluate("""() => {
        window.__unsubscribeRecoveryFixture();
        const store = window.OrchHarness.stores.chat.useChatStore;
        const send = store.getState().sendMessage;
        store.setState({sendMessage: async (...args) => {
            const result = await send(...args);
            window.__composerSendSettled = true;
            return result;
        }});
        window.OrchHarness.mount('mount-a', 'Composer', {initialAgentSelection: 'agent-1'});
    }""")
    editor = page.get_by_role("textbox", name="Message")
    editor.fill(REQUEST["message"])
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(editor).to_have_text("")
    if stage == "csrf":
        page.wait_for_function("window.__contextHeld === true")
    page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    if new_draft:
        editor.fill("A newer unsent question")
    held = recovery.pending_creation if stage == "creation" else recovery.pending_context
    assert len(held) == 1
    recovery._json(held.pop(), {"conversation_id": "conversation-1"} if stage == "creation" else {"csrf_token": "fixture-csrf"})
    page.wait_for_function("window.__composerSendSettled === true")
    expect(editor).to_have_text("A newer unsent question" if new_draft else REQUEST["message"])
    assert recovery.sends == []
    recovery.assert_clean()
