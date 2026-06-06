# test_chat_search_panel_mobile_drawer.py
"""
UI test for the mobile grounded-search drawer.
Version: 0.242.017
Implemented in: 0.242.017

This test ensures the grounded search panel stays behind the toolbar on mobile,
opens as an end-side drawer, closes cleanly through its mobile close button,
and keeps scope, tag, and document dropdown menus usable on desktop and mobile.
On desktop, the document dropdown opens upward from the composer; on mobile, it
opens downward inside the grounded-search drawer.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
MOBILE_VIEWPORT = {"width": 430, "height": 932}
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _open_grounded_search(page):
    search_button = page.locator("#search-documents-btn")
    search_panel = page.locator("#search-documents-container")

    if search_button.count() == 0 or search_panel.count() == 0:
        pytest.skip("Grounded search is not enabled for this environment.")

    expect(search_button).to_be_visible()
    search_button.click()
    expect(search_panel).to_be_visible()


def _seed_dropdown_items(page):
    page.evaluate(
        """
        () => {
            const tagsButton = document.getElementById('tags-dropdown-button');
            const tagsItems = document.getElementById('tags-dropdown-items');
            const documentItems = document.getElementById('document-dropdown-items');

            if (tagsButton) {
                tagsButton.disabled = false;
                tagsButton.removeAttribute('disabled');
                tagsButton.setAttribute('aria-disabled', 'false');
            }

            if (tagsItems && tagsItems.children.length === 0) {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'dropdown-item d-flex align-items-center';
                item.setAttribute('data-search-role', 'item');
                item.dataset.searchLabel = 'very long procurement readiness classification tag';

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'form-check-input me-2 tag-checkbox';
                checkbox.style.pointerEvents = 'none';

                const label = document.createElement('span');
                label.textContent = 'very long procurement readiness classification tag (12)';

                item.appendChild(checkbox);
                item.appendChild(label);
                tagsItems.appendChild(item);
            }

            if (documentItems && documentItems.children.length === 0) {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'dropdown-item d-flex align-items-center';
                item.setAttribute('data-document-id', 'synthetic-long-document');
                item.setAttribute('data-search-role', 'item');

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'form-check-input me-2 doc-checkbox';
                checkbox.style.pointerEvents = 'none';

                const label = document.createElement('span');
                label.textContent = 'Very Long Workspace Document Title For Procurement Readiness And Compliance Review.pdf';

                item.appendChild(checkbox);
                item.appendChild(label);
                documentItems.appendChild(item);
            }
        }
        """
    )


def _assert_dropdown_bounds(page, button_selector, menu_selector, viewport_width, *, should_expand, expected_direction=None):
    page.keyboard.press("Escape")
    button = page.locator(button_selector)
    menu = page.locator(menu_selector)

    expect(button).to_be_visible()
    button_box = button.bounding_box()
    assert button_box is not None, f"Expected {button_selector} to have a bounding box."

    button.click()
    expect(menu).to_be_visible()
    menu_box = menu.bounding_box()
    assert menu_box is not None, f"Expected {menu_selector} to have a bounding box."

    assert menu_box["x"] >= -1, f"Expected {menu_selector} to stay within the left viewport edge."
    assert menu_box["x"] + menu_box["width"] <= viewport_width + 1, f"Expected {menu_selector} to stay within the right viewport edge."
    assert menu_box["width"] >= button_box["width"] - 2, f"Expected {menu_selector} to be at least as wide as its trigger."

    if should_expand:
        assert menu_box["width"] >= button_box["width"] + 40, f"Expected {menu_selector} to expand beyond the narrow trigger width."

    if expected_direction == "up":
        assert menu_box["y"] + menu_box["height"] <= button_box["y"] + 1, f"Expected {menu_selector} to open above its trigger."
    elif expected_direction == "down":
        assert menu_box["y"] >= button_box["y"] + button_box["height"] - 1, f"Expected {menu_selector} to open below its trigger."

    page.keyboard.press("Escape")


@pytest.mark.ui
def test_chat_search_panel_uses_mobile_drawer(playwright):
    """Validate that grounded search opens in an end-side mobile drawer."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=MOBILE_VIEWPORT,
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        search_button = page.locator("#search-documents-btn")
        search_panel = page.locator("#search-documents-container")

        if search_button.count() == 0 or search_panel.count() == 0:
            pytest.skip("Grounded search is not enabled for this environment.")

        expect(search_button).to_be_visible()
        expect(search_panel).to_be_hidden()

        search_button.click()
        expect(page.locator("#search-documents-container.show")).to_be_visible()
        expect(page.locator("#search-documents-container .chat-search-panel-mobile-header")).to_be_visible()
        expect(page.locator("#searchDocumentsDrawerLabel")).to_contain_text("Grounded Search")

        close_button = page.locator("#search-documents-container .chat-search-panel-mobile-header .btn-close")
        expect(close_button).to_be_visible()
        close_button.click()
        expect(page.locator("#search-documents-container.show")).to_have_count(0)
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
@pytest.mark.parametrize(
    ("viewport", "should_expand"),
    [
        (DESKTOP_VIEWPORT, True),
        (MOBILE_VIEWPORT, False),
    ],
)
def test_chat_search_filter_dropdowns_are_responsive(playwright, viewport, should_expand):
    """Validate grounded-search dropdown menus are not capped to narrow trigger widths."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=viewport,
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        _open_grounded_search(page)
        _seed_dropdown_items(page)

        viewport_width = viewport["width"]
        _assert_dropdown_bounds(page, "#scope-dropdown-button", "#scope-dropdown-menu", viewport_width, should_expand=should_expand)
        _assert_dropdown_bounds(page, "#tags-dropdown-button", "#tags-dropdown-menu", viewport_width, should_expand=should_expand)
        _assert_dropdown_bounds(
            page,
            "#document-dropdown-button",
            "#document-dropdown-menu",
            viewport_width,
            should_expand=False,
            expected_direction="down" if viewport == MOBILE_VIEWPORT else "up",
        )
    finally:
        context.close()
        browser.close()