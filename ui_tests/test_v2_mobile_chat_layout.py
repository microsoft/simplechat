# test_v2_mobile_chat_layout.py
"""
Real-component regressions for V2 mobile composer and conversation actions.
Version: 0.261.325
Implemented in: 0.261.323

Only HTTP is stubbed; the production ChatExperience, stores, composer and CSS run
through the existing harness. Actual iOS keyboard behavior needs a real device.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_v2_sidebar_conversation_scroll import mount

pytest_plugins = ("test_v2_sidebar_conversation_scroll",)


pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).parent / "artifacts" / "mobile-layout"


@pytest.mark.parametrize("width,height,theme", [
    (320, 740, "light"), (360, 740, "dark"), (393, 852, "light"),
    (430, 932, "dark"), (768, 1024, "light"), (852, 393, "dark"),
    (1280, 800, "light"),
])
def test_composer_actions_and_tools_remain_reachable(open_page, width, height, theme):
    page, api = open_page({"width": width, "height": height})
    mount(page, api, rows=0)
    page.evaluate("""theme => {
        document.documentElement.classList.toggle('dark', theme === 'dark');
        const H = window.OrchHarness;
        H.stores.bootstrap.useBootstrapStore.setState(state => ({data: {
            ...state.data, features: {
                ...state.data.features, enable_speech_to_text_input: true,
                enable_chat_orchestration: true,
            }, orchestration: {enabled: true, capabilities: [], default_approval_mode: 'manual'},
        }}));
    }""", theme)
    send = page.get_by_role("button", name="Send message", exact=True)
    attach = page.get_by_role("button", name="Attach a file", exact=True)
    voice = page.get_by_role("button", name="Voice input", exact=True)
    expect(send).to_be_visible()
    if width < 768:
        tools = page.get_by_role("button", name="Chat tools", exact=True)
        expect(tools).to_be_visible()
        boxes = [control.bounding_box() for control in (tools, voice, attach, send)]
        assert all(boxes)
        assert len({round(box["y"]) for box in boxes}) == 1, boxes
        assert all(box["height"] >= 44 for box in boxes)
        assert boxes[-1]["x"] + boxes[-1]["width"] <= width
        expect(page.get_by_role("button", name="Orchestrate", exact=True)).not_to_be_visible()
        tools.click()
        orchestration = page.get_by_role("button", name="Orchestrate", exact=True)
        expect(orchestration).to_have_attribute("aria-pressed", "true")
        expect(tools).to_contain_text("manual")
        orchestration.click()
        expect(orchestration).to_have_attribute("aria-pressed", "false")
        orchestration.click()
        expect(tools).to_contain_text("manual")
        tools.click()
        expect(send).to_be_visible()
        expect(page.get_by_role("button", name="Orchestrate", exact=True)).not_to_be_visible()
    else:
        expect(page.get_by_role("button", name="Chat tools", exact=True)).not_to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / f"chat-{width}-{theme}.png"))


def test_mobile_conversation_actions_and_new_chat_keep_existing_semantics(open_page):
    page, api = open_page({"width": 393, "height": 852})
    mount(page, api, rows=0)
    page.evaluate("""() => {
        window.OrchHarness.stores.chat.useChatStore.setState({
            activeConversationId: 'conv-01',
            conversations: [{id: 'conv-01', title: 'Long conversation title '.repeat(10)}],
        });
    }""")
    expect(page.get_by_role("button", name="Open used documents", exact=True)).not_to_be_visible()
    trigger = page.get_by_role("button", name="Conversation actions", exact=True)
    height_before = page.locator(".chat-header").bounding_box()["height"]
    trigger.click()
    panel = page.get_by_role("group", name="Conversation actions", exact=True)
    expect(panel).to_be_visible()
    expect(page.get_by_role("button", name="View conversation details", exact=True)).to_be_focused()
    bounds = panel.bounding_box()
    assert bounds and bounds["x"] >= 8 and bounds["x"] + bounds["width"] <= 393 - 8 + 1
    assert page.locator(".chat-header").bounding_box()["height"] == height_before
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    expect(panel).to_have_count(0)
    trigger.click()
    page.get_by_role("button", name="Open used documents", exact=True).click()
    expect(panel).to_have_count(0)
    expect(page.get_by_role("complementary", name="Conversation details")).to_be_visible()
    page.get_by_role("button", name="Close panel", exact=True).click()
    page.evaluate("""() => {
        window.OrchHarness.stores.userSettings.useUserSettingsStore.setState({
            settings: {showTutorialButtons: true},
        });
    }""")
    trigger.click()
    page.get_by_role("button", name="Take the chat tour", exact=True).click()
    expect(panel).to_have_count(0)
    expect(page.get_by_role("dialog")).to_have_count(1)
    expect(page.get_by_role("dialog")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(trigger).to_be_focused()
    page.get_by_role("button", name="Start a new chat", exact=True).click()
    expect(page.get_by_role("heading", name="New chat", exact=True)).to_be_visible()
    assert page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId") is None


def test_large_text_and_classification_banner_keep_mobile_actions_in_bounds(open_page):
    page, api = open_page({"width": 393, "height": 852})
    mount(page, api, rows=0)
    page.evaluate("""() => {
        document.documentElement.dataset.fontSize = 'xl';
        const H = window.OrchHarness;
        H.stores.bootstrap.useBootstrapStore.setState(state => ({data: {
            ...state.data, branding: {...state.data.branding, classification_banner: {
                enabled: true, text: 'Internal information - handle according to your organization policy',
                color: '#123456', text_color: '#ffffff',
            }},
            features: {...state.data.features, enable_speech_to_text_input: true},
        }}));
    }""")
    expect(page.locator("#classification-banner")).to_be_visible()
    for label in ("Open navigation", "Chat tools", "Voice input", "Attach a file", "Send message"):
        control = page.get_by_role("button", name=label, exact=True)
        expect(control).to_be_in_viewport()
        bounds = control.bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 393
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
