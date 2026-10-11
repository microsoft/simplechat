# test_v2_mobile_navigation.py
"""
Real-component regression tests for the space-saving V2 mobile navigation.
Version: 0.261.323
Implemented in: 0.261.323

Reuses production components/CSS and the closed HTTP rail harness. Local Chromium
and the shared Azure Playwright connection fixture are supported.
"""

import pytest
from playwright.sync_api import expect

from test_v2_sidebar_conversation_scroll import (
    editor_assets, editor_browser, connect_options, mount, open_page,  # noqa: F401
)


pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width,height", [
    (320, 740), (360, 740), (393, 852), (430, 932), (767, 852),
])
def test_closed_navigation_reserves_no_phone_width_and_drawer_returns_focus(open_page, width, height):
    page, api = open_page({"width": width, "height": height})
    mount(page, api, rows=0)
    opener = page.get_by_role("button", name="Open navigation", exact=True)
    expect(opener).to_be_visible()
    expect(page.get_by_role("navigation", name="Primary", exact=True)).to_have_count(0)
    main = page.locator(".app-shell main")
    bounds = main.bounding_box()
    assert bounds and bounds["x"] == 0 and bounds["width"] == width
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    expect(page.locator("[data-notification-bell]")).to_have_count(1)
    opener.click()
    close = page.get_by_role("navigation", name="Primary").get_by_role("button", name="Close navigation")
    expect(close).to_be_focused()
    assert main.evaluate("element => element.inert")
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.getElementById('primary-navigation').contains(document.activeElement)")
    page.keyboard.press("Escape")
    expect(opener).to_be_focused()
    assert not main.evaluate("element => element.inert")
    opener.click()
    page.get_by_role("navigation", name="Primary").get_by_role("button", name="New chat", exact=True).click()
    expect(opener).to_be_visible()
    expect(page.get_by_role("navigation", name="Primary")).to_have_count(0)


def test_resize_keeps_desktop_preference_and_active_conversation(open_page):
    page, api = open_page()
    mount(page, api)
    page.get_by_role("button", name="Collapse navigation", exact=True).click()
    page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.setState({
        activeConversationId: 'conv-01',
    })""")
    page.set_viewport_size({"width": 393, "height": 852})
    page.get_by_role("button", name="Open navigation", exact=True).click()
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1280, "height": 800})
    expect(page.get_by_role("button", name="Expand navigation", exact=True)).to_be_visible()
    bounds = page.get_by_role("navigation", name="Primary").bounding_box()
    assert bounds and bounds["width"] == 68
    assert page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId") == "conv-01"


def test_home_uses_one_fallback_header_and_mobile_drawer_scrolls(open_page):
    page, api = open_page({"width": 393, "height": 393})
    mount(page, api, experience="HomeExperience", entry="/", rows=0)
    expect(page.get_by_role("button", name="Open navigation", exact=True)).to_have_count(1)
    page.get_by_role("button", name="Open navigation", exact=True).click()
    nav = page.get_by_role("navigation", name="Primary")
    expect(nav).to_be_visible()
    region = nav.locator("[data-rail-scroll-region]")
    assert region.evaluate("element => getComputedStyle(element).overflowY") == "auto"
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Open navigation", exact=True)).to_be_focused()
