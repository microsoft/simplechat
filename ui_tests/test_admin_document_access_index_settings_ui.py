# test_admin_document_access_index_settings_ui.py
"""
UI test for Admin Settings document access index operations.

Version: 0.250.011
Implemented in: 0.250.011

This test ensures the Scale tab exposes the Wave 4A1 operational
dashboard, safe settings, manual batch button, and reset modal without
exposing future read-path controls as editable form fields.
"""

import re
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"


def _extract_document_access_index_markup(template):
    start = template.index('<div class="card p-3 mb-3" id="document-access-index-section"')
    end = template.index('<div class="card p-3 mb-3" id="cosmos-throughput-section"', start)
    markup = template[start:end]
    markup = re.sub(r"\{\%[^%]*\%\}", "", markup)
    return re.sub(r"\{\{[^}]*\}\}", "", markup)


@pytest.mark.ui
def test_admin_document_access_index_dashboard_renders_safe_controls():
    """Validate the document access index dashboard markup and accessible controls."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    card_html = _extract_document_access_index_markup(template)

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    try:
        page.set_content(f"<main>{card_html}</main>")
        section = page.locator("#document-access-index-section")
        expect(section).to_be_visible()
        expect(section.get_by_text("Cosmos Document Access Index")).to_be_visible()
        expect(page.get_by_role("button", name="Refresh Status")).to_be_visible()
        expect(page.get_by_role("button", name="Run One Backfill Batch")).to_be_visible()
        expect(page.get_by_role("button", name="Reset Checkpoint")).to_be_visible()
        expect(page.get_by_label("Enable write-through projection")).to_be_visible()
        expect(page.get_by_label("Enable scheduled backfill")).to_be_visible()
        expect(page.get_by_label("Backfill Batch Size")).to_be_visible()
        expect(page.get_by_label("Repair Batch Size")).to_be_visible()
        expect(page.locator("#enable_document_access_index_reads_preview")).to_be_disabled()
        expect(page.locator("#enable_document_access_index_shadow_validation_preview")).to_be_disabled()
        expect(section.get_by_text("Wave 5")).to_be_visible()
        expect(section.get_by_text("Wave 4B")).to_be_visible()
        expect(page.locator("#documentAccessIndexResetModal")).to_be_attached()
        expect(page.get_by_role("button", name="Reset and Run Batch")).to_be_visible()
    finally:
        browser.close()
        playwright_context.stop()


def test_admin_document_access_index_dashboard_wiring_contract():
    """Validate static ids, endpoint wiring, and future-wave field protection."""
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    source = ADMIN_JS.read_text(encoding="utf-8")

    required_ids = [
        "document-access-index-section",
        "document-access-index-refresh-btn",
        "document-access-index-run-batch-btn",
        "document-access-index-reset-btn",
        "documentAccessIndexResetModal",
        "document-access-index-reset-confirm-btn",
        "document-access-index-backfill-status",
        "document-access-index-repair-count",
        "document-access-index-total-processed",
        "document-access-index-last-error",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert 'name="enable_document_access_index_write_through"' in template
    assert 'name="enable_startup_document_access_index_backfill"' in template
    assert 'name="document_access_index_backfill_batch_size"' in template
    assert 'name="document_access_index_repair_batch_size"' in template
    assert 'name="enable_document_access_index_reads"' not in template
    assert 'name="enable_document_access_index_shadow_validation"' not in template
    assert "setupDocumentAccessIndexControls();" in source
    assert "loadDocumentAccessIndexStatus(null, { showLoading: false });" in source
    assert "'/api/admin/settings/app-maintenance/status'" in source
    assert "'/api/admin/settings/app-maintenance/run'" in source
    assert "apply_cosmos_indexing_policies: false" in source
    assert "getNormalizedDocumentAccessIndexStatus(status) === 'running'" in source
    assert "function isDocumentAccessIndexBackfillInProgress" in source
    assert "function isDocumentAccessIndexBackfillActive" not in source
    assert "return ['running', 'in_progress'].includes" not in source
