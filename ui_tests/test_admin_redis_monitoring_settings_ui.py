# test_admin_redis_monitoring_settings_ui.py
"""
UI test for Admin Settings Redis monitoring.

Version: 0.250.026
Implemented in: 0.250.026

This test ensures the Scale tab exposes Redis health, capacity, hit-rate,
eviction, and runtime monitoring before Redis-backed DAI caching is enabled.
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
        expect(section.get_by_text("Configuration")).to_be_visible()
        expect(section.get_by_text("Health")).to_be_visible()
        expect(section.get_by_text("App Cache Runtime")).to_be_visible()
        expect(section.get_by_text("Session Runtime")).to_be_visible()
        expect(section.get_by_text("Memory Usage")).to_be_visible()
        expect(section.get_by_text("Keyspace Hit Rate")).to_be_visible()
        expect(section.get_by_text("Expired / Evicted Keys")).to_be_visible()
        expect(section.get_by_text("Rejected Connections")).to_be_visible()
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
        "redis-monitoring-expired-keys",
        "redis-monitoring-evicted-keys",
        "redis-monitoring-fragmentation",
        "redis-monitoring-errors",
        "redis-monitoring-rejected-connections",
        "redis-monitoring-version",
        "redis-monitoring-checked-at",
        "redis-monitoring-last-error",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    redis_markup = _extract_redis_markup(template)
    assert 'style="display: none;"' not in redis_markup
    assert "setupRedisMonitoringControls();" in source
    assert "function renderRedisMonitoringStatus" in source
    assert "function loadRedisMonitoringStatus" in source
    assert "'/api/admin/settings/redis-monitoring/status'" in source
    assert "setRedisTestResult(resultDiv, data.message || 'Redis connection successful.', 'success');" in source
    assert "redisSettingsDiv.style.display" not in source
