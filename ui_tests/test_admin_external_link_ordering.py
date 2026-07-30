# test_admin_external_link_ordering.py
"""
UI test for admin external-link ordering.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures admins can move saved external links up and down while the
visible row order and submitted JSON remain synchronized.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "") or os.getenv(
    "SIMPLECHAT_UI_STORAGE_STATE",
    "",
)


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state():
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE "
            "to a valid authenticated Playwright storage state file."
        )


def _external_link_labels(page):
    return [
        label.strip()
        for label in page.locator("#external-links-tbody .external-link-label").all_text_contents()
    ]


@pytest.mark.ui
def test_admin_can_reorder_saved_external_links(playwright):
    """Validate external-link ordering controls and save-payload synchronization."""
    _require_base_url()
    _require_storage_state()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        response = page.goto(
            f"{BASE_URL}/admin/settings#general",
            wait_until="domcontentloaded",
        )
        assert response is not None, (
            "Expected a navigation response when loading /admin/settings."
        )
        if response.status in {401, 403, 404}:
            pytest.skip(
                "Admin settings page was not available for the configured admin session."
            )

        assert response.ok, (
            f"Expected /admin/settings to load successfully, got HTTP {response.status}."
        )

        general_nav = page.locator(
            '[data-bs-target="#general"], [data-tab="general"]'
        ).first
        if general_nav.count() > 0:
            general_nav.click()

        enable_toggle = page.locator("#enable_external_links")
        expect(enable_toggle).to_have_count(1)
        if not enable_toggle.is_checked():
            enable_toggle.check(force=True)

        rows = page.locator("#external-links-tbody tr")
        expect(rows.first).to_be_visible()
        if rows.count() < 2:
            pytest.skip(
                "Configure at least two saved external links to exercise ordering."
            )

        original_labels = _external_link_labels(page)
        original_payload = json.loads(
            page.locator("#external_links_json").input_value()
        )
        assert [link["label"] for link in original_payload] == original_labels

        first_row = rows.nth(0)
        last_row = rows.nth(rows.count() - 1)
        expect(first_row.locator(".external-link-move-up-btn")).to_be_disabled()
        expect(first_row.locator(".external-link-move-down-btn")).to_be_enabled()
        expect(last_row.locator(".external-link-move-down-btn")).to_be_disabled()

        first_row.locator(".external-link-move-down-btn i").click()

        expected_labels = original_labels.copy()
        expected_labels[0], expected_labels[1] = (
            expected_labels[1],
            expected_labels[0],
        )
        assert _external_link_labels(page) == expected_labels

        reordered_payload = json.loads(
            page.locator("#external_links_json").input_value()
        )
        assert [link["label"] for link in reordered_payload] == expected_labels

        rows.nth(1).locator(".external-link-move-up-btn i").click()
        assert _external_link_labels(page) == original_labels

        restored_payload = json.loads(
            page.locator("#external_links_json").input_value()
        )
        assert [link["label"] for link in restored_payload] == original_labels

        original_row_count = rows.count()
        page.locator("#add-external-link-btn").click()
        new_row = rows.nth(original_row_count)
        new_row.locator(".external-link-label-input").fill(
            "External Link Ordering Test"
        )
        new_row.locator(".external-link-url-input").fill(
            "https://example.com/external-link-ordering-test"
        )
        new_row.locator(".external-link-save-btn").click()

        expect(rows).to_have_count(original_row_count + 1)
        expect(
            rows.nth(original_row_count - 1).locator(
                ".external-link-move-down-btn"
            )
        ).to_be_enabled()
        expect(
            rows.nth(original_row_count).locator(
                ".external-link-move-down-btn"
            )
        ).to_be_disabled()
    finally:
        context.close()
        browser.close()
