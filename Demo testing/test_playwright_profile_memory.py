# test_playwright_profile_memory.py
"""
Playwright test for creating a profile fact memory.
Version: 0.250.022
Implemented in: 0.250.003; presenter waits refined in 0.250.011; settings tab activation fixed in 0.250.019; settings pane selector fixed in 0.250.020; manager search added in 0.250.021; manager textarea assertion fixed in 0.250.022

This test demonstrates a focused Playwright UI workflow: navigate to Profile,
create a memory, verify the browser/API result, and clean up the created memory.
"""

import time

import pytest
from playwright.sync_api import expect

from demo_helpers import (
    ensure_artifact_dir,
    get_demo_base_url,
    new_demo_context,
    pause_for_presenter,
    wait_for_authenticated_selector,
)


def open_profile_settings_tab(page):
    """Open the profile Settings tab and scroll Fact Memory controls into view."""
    settings_tab = page.locator('#profileTabs [data-profile-tab="settings"]')
    settings_tab.wait_for(state="visible", timeout=30000)
    settings_tab.click()
    page.locator("#profile-settings-pane").wait_for(state="visible", timeout=30000)
    page.locator("#fact-memory-settings").scroll_into_view_if_needed(timeout=10000)
    page.locator("#fact-memory-new-value").wait_for(state="visible", timeout=30000)


@pytest.mark.ui
def test_local_profile_create_fact_memory(playwright):
    """Demonstrate Playwright control over a focused profile memory workflow."""
    base_url = get_demo_base_url()
    artifact_dir = ensure_artifact_dir()
    browser, context = new_demo_context(playwright)
    page = context.new_page()
    fact_id = None
    trace_path = artifact_dir / "demo_profile_memory_trace.zip"
    screenshot_path = artifact_dir / "demo_profile_memory_failure.png"
    context.tracing.start(screenshots=True, snapshots=True, sources=True)

    try:
        page.goto(f"{base_url}/profile", wait_until="domcontentloaded", timeout=60000)
        wait_for_authenticated_selector(page, "#profileTabs", "the profile memory demo")
        open_profile_settings_tab(page)

        memory_value = f"Demo memory created by Playwright at {int(time.time())}."
        page.locator("#fact-memory-new-value").fill(memory_value)
        page.locator("#fact-memory-new-type").select_option("fact")

        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith("/api/profile/fact-memory"),
            timeout=30000,
        ) as create_response_info:
            page.locator("#fact-memory-add-btn").click()

        create_response = create_response_info.value
        assert create_response.ok, f"Expected fact memory creation to succeed, got HTTP {create_response.status}."
        payload = create_response.json()
        fact_id = (payload.get("fact") or {}).get("id")
        assert fact_id, "Expected fact memory API response to include the created memory id."

        expect(page.locator("#fact-memory-status")).to_contain_text("Fact memory saved", timeout=15000)
        expect(page.locator("#fact-memory-count")).not_to_have_text("0", timeout=15000)
        page.screenshot(path=artifact_dir / "demo_profile_memory_saved.png", full_page=True)

        page.locator("#open-fact-memory-modal-btn").click()
        page.locator("#factMemoryManagerModal").wait_for(state="visible", timeout=15000)
        page.locator("#fact-memory-search-input").fill(memory_value)
        memory_textarea = page.locator(f"#fact-memory-value-{fact_id}")
        memory_textarea.wait_for(state="visible", timeout=15000)
        expect(memory_textarea).to_have_value(memory_value, timeout=15000)
        page.screenshot(path=artifact_dir / "demo_profile_memory_manager.png", full_page=True)

        pause_for_presenter(
            page,
            "SIMPLECHAT_DEMO_PROFILE_MEMORY_PAUSE_MS",
            10000,
            "Profile memory is visible in the manager.",
        )
    except Exception:
        page.screenshot(path=screenshot_path, full_page=True)
        raise
    finally:
        if fact_id:
            try:
                context.request.delete(f"{base_url}/api/profile/fact-memory/{fact_id}", timeout=30000)
            except Exception:
                pass
        context.tracing.stop(path=trace_path)
        context.close()
        browser.close()