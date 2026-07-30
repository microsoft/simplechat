# test_shared_toast_notifications.py
"""
UI test for shared non-blocking toast notifications.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures dynamic toast messages render as literal text, use accessible
Bootstrap variants, remain dismissible, and never open a native browser dialog.
"""

from pathlib import Path
import re

import pytest
from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[1]
STATIC_JS_ROOT = ROOT / "application" / "single_app" / "static" / "js"


@pytest.mark.ui
def test_shared_toast_renders_safe_non_blocking_notifications(playwright):
    """Validate the global toast API without relying on a feature-specific workflow."""
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    dialogs = []

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)

    try:
        page.route(
            "https://simplechat.test/",
            lambda route: route.fulfill(
                content_type="text/html",
                body="""
                <!doctype html>
                <html lang="en">
                    <body>
                        <div id="toast-container" aria-label="Notifications"></div>
                    </body>
                </html>
                """,
            ),
        )
        page.goto("https://simplechat.test/")
        page.add_script_tag(path=str(STATIC_JS_ROOT / "chat" / "bootstrap.bundle.min.js"))
        page.add_script_tag(path=str(STATIC_JS_ROOT / "toast.js"))
        page.wait_for_function("() => typeof window.showToast === 'function'")

        payload = '<img src="invalid" onerror="window.__toastXss = true">Toast test'
        page.evaluate(
            """
            message => {
                window.__toastXss = false;
                window.showToast(message, 'warning');
            }
            """,
            payload,
        )

        toast = page.locator("#toast-container .toast").last
        expect(toast).to_be_visible()
        expect(toast).to_have_class(re.compile(r"\btext-bg-warning\b"))
        expect(toast.locator(".toast-body")).to_have_text(payload)
        expect(toast.locator("img")).to_have_count(0)
        assert page.evaluate("() => window.__toastXss") is False
        assert dialogs == []

        toast.get_by_role("button", name="Close").click()
        expect(toast).to_have_count(0)

        page.evaluate(
            """
            () => {
                window.showToast('Saved successfully.', 'success');
                window.showToast('Unable to save.', 'danger');
                window.showToast('Legacy error variant.', 'error');
            }
            """
        )
        expect(page.locator("#toast-container .toast")).to_have_count(3)
        expect(page.locator("#toast-container .toast").last).to_have_class(
            re.compile(r"\btext-bg-danger\b")
        )
        assert dialogs == []

        page.evaluate(
            "() => window.showToast('Available after navigation.', 'success', { persist: true })"
        )
        pending_toast = page.evaluate(
            "() => JSON.parse(window.sessionStorage.getItem('simplechat.pendingToast'))"
        )
        assert pending_toast == {
            "message": "Available after navigation.",
            "variant": "success",
        }

        page.reload()
        page.add_script_tag(path=str(STATIC_JS_ROOT / "chat" / "bootstrap.bundle.min.js"))
        page.add_script_tag(path=str(STATIC_JS_ROOT / "toast.js"))
        restored_toast = page.locator("#toast-container .toast").last
        expect(restored_toast).to_be_visible()
        expect(restored_toast).to_have_class(re.compile(r"\btext-bg-success\b"))
        expect(restored_toast.locator(".toast-body")).to_have_text("Available after navigation.")
        assert page.evaluate(
            "() => window.sessionStorage.getItem('simplechat.pendingToast')"
        ) is None
    finally:
        browser.close()
