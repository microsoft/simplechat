# test_admin_redis_monitoring_settings_ui.py
"""
UI test for Admin Settings Redis monitoring.

Version: 0.250.043
Implemented in: 0.250.026
Redis Explorer implemented in: 0.250.040
Redis Explorer DAI resolution implemented in: 0.250.043

This test ensures the Scale tab exposes Redis health, capacity, hit-rate,
eviction, DAI hygiene, runtime monitoring, and read-only Redis Explorer
controls before Redis-backed DAI caching is enabled.
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


def _extract_redis_markup(template):
    start = template.index('<div class="card p-3 mb-3" id="redis-cache-section"')
    end = template.index('<div class="card p-3 mb-3" id="document-access-index-section"', start)
    markup = template[start:end]
    markup = re.sub(r"\{\%[^%]*\%\}", "", markup)
    return re.sub(r"\{\{[^}]*\}\}", "", markup)


@pytest.mark.ui
def test_admin_redis_monitoring_dashboard_renders_safe_controls():
    """Validate the Redis monitoring markup and accessible refresh control."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    card_html = _extract_redis_markup(template)

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    try:
        page.set_content(f"<main>{card_html}</main>")
        section = page.locator("#redis-monitoring-section")
        expect(section).to_be_visible()
        expect(section.get_by_text("Redis Monitoring")).to_be_visible()
        expect(page.get_by_role("button", name="Refresh Redis Status")).to_be_visible()
        expect(page.get_by_role("button", name="Redis Explorer")).to_be_visible()
        expect(section.get_by_text("Configuration")).to_be_visible()
        expect(section.get_by_text("Health")).to_be_visible()
        expect(section.get_by_text("App Cache Runtime")).to_be_visible()
        expect(section.get_by_text("Session Runtime")).to_be_visible()
        expect(section.get_by_text("Memory Usage")).to_be_visible()
        expect(section.get_by_text("Keyspace Hit Rate")).to_be_visible()
        expect(section.get_by_text("DAI Version Markers")).to_be_visible()
        expect(section.get_by_text("DAI Cache Payloads")).to_be_visible()
        expect(section.get_by_text("Expired / Evicted Keys")).to_be_visible()
        expect(section.get_by_text("Rejected Connections")).to_be_visible()
        expect(page.locator("#redisExplorerModal")).to_be_attached()
        expect(page.get_by_label("Key Filter")).to_be_attached()
        expect(page.get_by_text("Filters are case sensitive.")).to_be_attached()
        expect(page.get_by_label("Page Size")).to_be_attached()
        expect(page.get_by_role("button", name="Browse All")).to_be_attached()
        expect(page.get_by_role("button", name="Apply Filter")).to_be_attached()
        expect(page.get_by_role("button", name="Previous Page")).to_be_attached()
        expect(page.get_by_role("button", name="Next Page")).to_be_attached()
        expect(page.get_by_text("SimpleChat Resolution")).to_be_attached()
    finally:
        browser.close()
        playwright_context.stop()


def test_admin_redis_monitoring_dashboard_wiring_contract():
    """Validate static ids, endpoint wiring, and safe Redis rendering helpers."""
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    source = ADMIN_JS.read_text(encoding="utf-8")

    required_ids = [
        "redis-monitoring-section",
        "redis-monitoring-refresh-btn",
        "redis-monitoring-message",
        "redis-monitoring-config-status",
        "redis-monitoring-health-status",
        "redis-monitoring-app-cache-status",
        "redis-monitoring-session-status",
        "redis-monitoring-source",
        "redis-monitoring-ping-latency",
        "redis-monitoring-memory-usage",
        "redis-monitoring-memory-policy",
        "redis-monitoring-connected-clients",
        "redis-monitoring-ops-per-sec",
        "redis-monitoring-hit-rate",
        "redis-monitoring-key-count",
        "redis-monitoring-dai-version-markers",
        "redis-monitoring-dai-version-marker-expiry",
        "redis-monitoring-dai-payload-keys",
        "redis-monitoring-dai-version-ttl-policy",
        "redis-monitoring-expired-keys",
        "redis-monitoring-evicted-keys",
        "redis-monitoring-fragmentation",
        "redis-monitoring-errors",
        "redis-monitoring-rejected-connections",
        "redis-monitoring-version",
        "redis-monitoring-checked-at",
        "redis-monitoring-last-error",
        "redis-explorer-open-btn",
        "redisExplorerModal",
        "redis-explorer-filter",
        "redis-explorer-page-size",
        "redis-explorer-browse-all-btn",
        "redis-explorer-search-btn",
        "redis-explorer-refresh-btn",
        "redis-explorer-prev-btn",
        "redis-explorer-next-btn",
        "redis-explorer-key-list",
        "redis-explorer-key-count",
        "redis-explorer-message",
        "redis-explorer-preview-empty",
        "redis-explorer-preview-panel",
        "redis-explorer-preview-key",
        "redis-explorer-preview-type",
        "redis-explorer-preview-ttl",
        "redis-explorer-preview-memory",
        "redis-explorer-preview-redacted",
        "redis-explorer-resolution-card",
        "redis-explorer-resolution-kind",
        "redis-explorer-resolution-entity",
        "redis-explorer-resolution-scope",
        "redis-explorer-resolution-note",
        "redis-explorer-preview-content",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    redis_markup = _extract_redis_markup(template)
    assert 'style="display: none;"' not in redis_markup
    assert 'style="max-height:' not in redis_markup
    assert "Leave the filter blank" in redis_markup
    assert "Filters are case sensitive." in redis_markup
    assert "APP_SETTINGS_CACHE" in redis_markup
    assert "SimpleChat Resolution" in redis_markup
    assert "modal-dialog-scrollable redis-explorer-dialog" in redis_markup
    assert ".redis-explorer-body" in template
    assert "overflow-y: auto;" in template
    assert ".redis-explorer-key-list" in template
    assert "height: clamp(16rem, 36vh, 24rem);" in template
    assert "overscroll-behavior: contain;" in template
    assert "redis-explorer-key-list\" style=" not in redis_markup
    assert "setupRedisMonitoringControls();" in source
    assert "setupRedisExplorerControls();" in source
    assert "function renderRedisMonitoringStatus" in source
    assert "function loadRedisMonitoringStatus" in source
    assert "function loadRedisExplorerKeys" in source
    assert "function loadRedisExplorerValue" in source
    assert "function getRedisExplorerScopeLabel" in source
    assert "function renderRedisExplorerResolution" in source
    assert "statusPayload?.dai_cache" in source
    assert "redis-explorer-browse-all-btn" in source
    assert "'/api/admin/settings/redis-monitoring/status'" in source
    assert "'/api/admin/settings/redis-explorer/value'" in source
    assert "/api/admin/settings/redis-explorer/keys" in source
    assert "setRedisTestResult(resultDiv, data.message || 'Redis connection successful.', 'success');" in source
    assert "redisSettingsDiv.style.display" not in source
    assert "innerHTML" not in source[source.index("function renderRedisExplorerKeys"):source.index("function getRedisExplorerRequestState")]
