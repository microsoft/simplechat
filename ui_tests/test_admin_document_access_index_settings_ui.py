# test_admin_document_access_index_settings_ui.py
"""
UI test for Admin Settings document access index operations.

Version: 0.250.031
Implemented in: 0.250.011
Default read enablement updated in: 0.250.027
Redis DAI cache dashboard updated in: 0.250.029
DAI debug UI cleanup updated in: 0.250.031

This test ensures the Scale tab exposes the DAI operations dashboard,
automatic maintenance status, production read metrics, default-hidden debug
controls, optional shadow validation, and Wave 6 Redis DAI cache metrics.
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
SIDEBAR_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "_sidebar_nav.html"
ADMIN_SIDEBAR_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_sidebar_nav.js"


def _extract_document_access_index_markup(template):
    start = template.index('<div class="card p-3 mb-3" id="document-access-index-section"')
    end = template.index('<div class="card p-3 mb-3" id="cosmos-throughput-section"', start)
    return template[start:end]


def _render_dai_debug_blocks(markup, enable_dai_debug):
    tokens = re.split(r"(\{\%[^%]*\%\})", markup)
    rendered = []
    stack = []
    skip_depth = 0
    for token in tokens:
        stripped = token.strip()
        if stripped.startswith("{% if "):
            condition = stripped[6:-2].strip()
            is_dai_debug_condition = condition == "enable_dai_debug"
            if is_dai_debug_condition:
                should_skip = not enable_dai_debug
                stack.append((True, should_skip))
                if should_skip:
                    skip_depth += 1
                continue
            stack.append((False, False))
            if skip_depth == 0:
                rendered.append(token)
            continue

        if stripped == "{% endif %}":
            if stack:
                is_dai_debug_condition, was_skipped = stack.pop()
                if is_dai_debug_condition:
                    if was_skipped:
                        skip_depth -= 1
                    continue
            if skip_depth == 0:
                rendered.append(token)
            continue

        if skip_depth == 0:
            rendered.append(token)

    return "".join(rendered)


def _render_document_access_index_markup(template, enable_dai_debug=False):
    markup = _render_dai_debug_blocks(
        _extract_document_access_index_markup(template),
        enable_dai_debug=enable_dai_debug,
    )
    replacements = {
        "{% if settings.enable_document_access_index_shadow_validation %}checked{% endif %}": "",
        "{% if settings.enable_document_access_index_cache %}checked{% endif %}": "checked",
        "{{ settings.document_access_index_backfill_batch_size or 200 }}": "200",
        "{{ settings.document_access_index_repair_batch_size or 100 }}": "100",
        "{{ settings.document_access_index_cache_ttl_seconds or 900 }}": "900",
    }
    for old_value, new_value in replacements.items():
        markup = markup.replace(old_value, new_value)
    markup = re.sub(r"\{\%[^%]*\%\}", "", markup)
    return re.sub(r"\{\{[^}]*\}\}", "", markup)


@pytest.mark.ui
def test_admin_document_access_index_dashboard_renders_safe_controls():
    """Validate the document access index dashboard markup and accessible controls."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    card_html = _render_document_access_index_markup(template, enable_dai_debug=False)

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    try:
        page.set_content(f"<main>{card_html}</main>")
        section = page.locator("#document-access-index-section")
        expect(section).to_be_visible()
        expect(section.get_by_text("Cosmos Document Access Index")).to_be_visible()
        expect(page.get_by_role("button", name="Refresh Status")).to_be_visible()
        expect(page.get_by_role("button", name="Run One Backfill Batch")).to_have_count(0)
        expect(page.get_by_role("button", name="Reset Checkpoint")).to_have_count(0)
        expect(page.get_by_label("Write-through projection")).to_have_count(0)
        expect(page.get_by_label("Automatic repair/backfill")).to_have_count(0)
        expect(page.get_by_label("Enable shadow validation")).to_have_count(0)
        expect(page.get_by_label("Backfill Batch Size")).to_have_count(0)
        expect(page.get_by_label("Repair Batch Size")).to_have_count(0)
        expect(section.get_by_text("Auto Maintenance")).to_be_visible()
        expect(section.get_by_text("Next Maintenance Action")).to_be_visible()
        expect(section.get_by_text("Redis List Cache")).to_be_visible()
        expect(section.get_by_text("15m DAI Read Attempts")).to_be_visible()
        expect(section.get_by_text("15m Redis Cache Hit Rate")).to_be_visible()
        expect(section.get_by_text("15m Cache Hits / Misses")).to_be_visible()
        expect(section.get_by_text("15m Cache Bypasses / Errors")).to_be_visible()
        expect(section.get_by_text("15m Cache Invalidations")).to_be_visible()
        expect(section.get_by_text("15m Source Fallbacks")).to_be_visible()
        expect(section.get_by_text("15m Fallback Rate")).to_be_visible()
        expect(section.get_by_text("Last Fallback Reason")).to_be_visible()
        expect(section.get_by_text("Validation Index RU")).to_have_count(0)
        expect(section.get_by_text("Candidate Read RU")).to_have_count(0)
        expect(section.get_by_text("Estimated Wave 5 Savings")).to_have_count(0)
        expect(section.get_by_text("Estimated Wave 5 Latency")).to_have_count(0)
        expect(section.get_by_text("5m Source / Candidate RU")).to_have_count(0)
        expect(section.get_by_text("15m Source / Candidate RU")).to_have_count(0)
        expect(section.get_by_text("15m Shadow Samples")).to_have_count(0)
        expect(page.locator("#enable_document_access_index_reads")).to_have_count(0)
        expect(page.locator("#enable_document_access_index_shadow_validation")).to_have_count(0)
        expect(page.get_by_label("Redis document list cache")).to_have_count(0)
        expect(page.get_by_label("Cache TTL Seconds")).to_have_count(0)
        expect(page.locator("#documentAccessIndexResetModal")).to_have_count(0)
    finally:
        browser.close()
        playwright_context.stop()


@pytest.mark.ui
def test_admin_document_access_index_debug_mode_renders_hidden_controls():
    """Validate the Cosmos-edited DAI debug flag reveals support-only controls."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    card_html = _render_document_access_index_markup(template, enable_dai_debug=True)

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    try:
        page.set_content(f"<main>{card_html}</main>")
        section = page.locator("#document-access-index-section")
        expect(section).to_be_visible()
        expect(page.get_by_role("button", name="Run One Backfill Batch")).to_be_visible()
        expect(page.get_by_role("button", name="Reset Checkpoint")).to_be_visible()
        expect(page.get_by_label("Write-through projection")).to_be_visible()
        expect(page.get_by_label("Automatic repair/backfill")).to_be_visible()
        expect(page.get_by_label("Enable shadow validation")).to_be_visible()
        expect(page.locator("#enable_document_access_index_reads")).to_be_disabled()
        expect(page.get_by_label("Redis document list cache")).to_be_visible()
        expect(page.get_by_label("Cache TTL Seconds")).to_have_value("900")
        expect(section.get_by_text("Validation Index RU")).to_be_visible()
        expect(section.get_by_text("15m Shadow Samples")).to_be_visible()
        expect(page.locator("#documentAccessIndexResetModal")).to_be_attached()
        expect(page.get_by_role("button", name="Reset and Run Batch")).to_be_visible()
    finally:
        browser.close()
        playwright_context.stop()


def test_admin_document_access_index_dashboard_wiring_contract():
    """Validate static ids, endpoint wiring, and Wave 5B field exposure."""
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
        "document-access-index-maintenance-mode",
        "document-access-index-maintenance-next-action",
        "document-access-index-maintenance-more-work",
        "document-access-index-maintenance-active-interval",
        "document-access-index-cache-status",
        "document-access-index-read-15m-attempts",
        "document-access-index-cache-15m-hit-rate",
        "document-access-index-cache-15m-hits-misses",
        "document-access-index-cache-15m-bypasses-errors",
        "document-access-index-cache-15m-invalidations",
        "document-access-index-read-15m-served",
        "document-access-index-read-15m-fallbacks",
        "document-access-index-read-15m-fallback-rate",
        "document-access-index-read-15m-ru",
        "document-access-index-read-15m-latency",
        "document-access-index-read-last-fallback",
        "document-access-index-read-last-sample",
        "document-access-index-cache-last-event",
        "document-access-index-shadow-last-status",
        "document-access-index-shadow-mismatches",
        "document-access-index-shadow-ru-comparison",
        "document-access-index-shadow-validation-ru",
        "document-access-index-shadow-candidate-ru",
        "document-access-index-shadow-wave5-ru-savings",
        "document-access-index-shadow-ms-comparison",
        "document-access-index-shadow-ms-savings",
        "document-access-index-rolling-5m-ru-comparison",
        "document-access-index-rolling-5m-wave5-ru-savings",
        "document-access-index-rolling-15m-ru-comparison",
        "document-access-index-rolling-15m-wave5-ru-savings",
        "document-access-index-rolling-15m-validation-overhead",
        "document-access-index-rolling-15m-samples",
        "document-access-index-total-processed",
        "document-access-index-last-error",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    rendered_default = _render_document_access_index_markup(template, enable_dai_debug=False)
    assert 'id="document-access-index-run-batch-btn"' not in rendered_default
    assert 'id="enable_document_access_index_shadow_validation"' not in rendered_default
    assert 'id="documentAccessIndexResetModal"' not in rendered_default
    assert 'Validation Index RU' not in rendered_default
    assert '15m Shadow Samples' not in rendered_default
    rendered_debug = _render_document_access_index_markup(template, enable_dai_debug=True)
    assert 'id="document-access-index-run-batch-btn"' in rendered_debug
    assert 'id="enable_document_access_index_shadow_validation"' in rendered_debug
    assert 'id="documentAccessIndexResetModal"' in rendered_debug
    assert 'value="900"' in rendered_debug
    assert "Default 900 seconds" in rendered_debug
    assert "enable_dai_debug" in template
    assert 'name="enable_dai_debug"' not in template
    assert 'name="enable_document_access_index_write_through"' in template
    assert 'name="enable_startup_document_access_index_backfill"' in template
    assert 'name="enable_document_access_index_shadow_validation"' in template
    assert 'name="document_access_index_backfill_batch_size"' in template
    assert 'name="document_access_index_repair_batch_size"' in template
    assert 'name="enable_document_access_index_reads"' in template
    assert 'name="enable_document_access_index_cache"' in template
    assert 'name="document_access_index_cache_ttl_seconds"' in template
    assert "Wave 5B default" in template
    assert "Wave 6" in template
    assert "enable_document_access_index_shadow_validation_preview" not in template
    assert "setupDocumentAccessIndexControls();" in source
    assert "loadDocumentAccessIndexStatus(null, { showLoading: false });" in source
    assert "function getDocumentAccessIndexReadWindow" in source
    assert "function getDocumentAccessIndexCacheWindow" in source
    assert "formatDocumentAccessIndexCacheEvent" in source
    assert "formatDocumentAccessIndexLatencyWindow" in source
    assert "'/api/admin/settings/app-maintenance/status'" in source
    assert "'/api/admin/settings/app-maintenance/run'" in source
    assert "apply_cosmos_indexing_policies: false" in source
    assert "getNormalizedDocumentAccessIndexStatus(status) === 'running'" in source
    assert "function isDocumentAccessIndexBackfillInProgress" in source
    assert "function isDocumentAccessIndexBackfillActive" not in source
    assert "return ['running', 'in_progress'].includes" not in source


def test_admin_scale_sidebar_metric_links_are_wired():
    """Validate left-nav metric shortcuts for DAI, Cosmos, and Redis sections."""
    sidebar_template = SIDEBAR_TEMPLATE.read_text(encoding="utf-8")
    sidebar_source = ADMIN_SIDEBAR_JS.read_text(encoding="utf-8")

    expected_links = [
        ("DAI Metrics", "document-access-index-section"),
        ("Cosmos Metrics", "cosmos-throughput-section"),
        ("Redis Metrics", "redis-monitoring-section"),
    ]
    for label, section_id in expected_links:
        assert label in sidebar_template
        assert f'data-section="{section_id}"' in sidebar_template
        assert f"'{section_id}': '{section_id}'" in sidebar_source
