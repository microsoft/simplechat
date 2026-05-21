# test_chat_visio_citation_modal.py
"""
UI test for chat Visio citation previews.

Version: 0.241.078
Implemented in: 0.241.074

This test ensures a `.vsdx` enhanced citation opens the Visio preview modal,
loads the page preview image, and keeps the original file download available.
"""

import base64
import json
import os
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_visio_citation_modal_preview():
    """Validate that a Visio enhanced citation opens the visual preview modal."""
    _require_ui_env()
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    console_errors = []

    def handle_document_metadata(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "id": "doc-visio-1",
                "document_id": "doc-visio-1",
                "file_name": "architecture.vsdx",
                "enhanced_citations": True,
            }),
        )

    def handle_visio_preview(route):
        request_url = route.request.url
        if "download=true" in request_url:
            route.fulfill(
                status=200,
                content_type="application/vnd.ms-visio.drawing.main+xml",
                headers={"Content-Disposition": 'attachment; filename="architecture.vsdx"'},
                body=b"vsdx",
            )
            return

        route.fulfill(status=200, content_type="image/png", body=PNG_BYTES)

    page.route("**/api/enhanced_citations/document_metadata**", handle_document_metadata)
    page.route("**/api/enhanced_citations/visio**", handle_visio_preview)
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        page.evaluate(
            """
            async () => {
                const module = await import('/static/js/chat/chat-enhanced-citations.js');
                await module.showEnhancedCitationModal('doc-visio-1', 1, 'citation-visio-1');
            }
            """
        )

        expect(page.locator("#enhanced-visio-modal")).to_be_visible()
        expect(page.locator("#enhanced-visio-modal .modal-title")).to_have_text("Visio: architecture.vsdx")
        expect(page.locator("#enhanced-visio-page-info")).to_have_text("Page 1")
        expect(page.locator("#enhanced-visio-image")).to_be_visible()
        expect(page.locator("#enhanced-visio-download")).to_be_visible()
        assert console_errors == []
    finally:
        context.close()
        browser.close()
        playwright_context.stop()