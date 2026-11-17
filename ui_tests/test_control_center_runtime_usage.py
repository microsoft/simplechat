# test_control_center_runtime_usage.py
"""
Classic and V2 metadata-only usage interaction coverage.
Version: 0.261.447
Implemented in: 0.261.447
"""

import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from test_v2_control_center_activity_logs import ActivityFixture
from test_v2_control_center_users import ORIGIN


pytestmark = pytest.mark.ui


def report_payload():
    total = {
        "invocations": 42, "unique_users": 3, "outcomes": {"succeeded": 40, "failed": 2},
        "duration_count": 40, "measured_duration_ms": 400, "average_duration_ms": 10,
        "legacy_records": 2,
    }
    return {
        "totals": {kind: total for kind in ("agent", "action", "workflow")},
        "entities": [{
            **total, "kind": "action", "entity_id": "action-1", "name": "<img src=x onerror=alert(1)>",
            "scope_type": "global", "scope_id": "global", "entity_type": "openapi",
            "endpoint_host": "api.example.test", "auth_type": "managed_identity", "operation": "get_items",
        }],
        "complete": True, "recorded_at": "2026-11-16T12:00:00Z", "cache_seconds": 90,
    }


class UsageFixture(ActivityFixture):
    def __init__(self, page, classic=False):
        self.classic = classic
        self.usage_queries = []
        self.usage_fail = False
        self.usage_empty = False
        super().__init__(page)

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        if parsed.path.endswith("/activity-logs/usage"):
            query = parse_qs(parsed.query)
            self.usage_queries.append(query)
            if self.usage_fail:
                route.fulfill(status=422, json={"complete": False, "error": "Narrow the date range."})
            elif query.get("format") == ["csv"]:
                route.fulfill(body="kind,invocations\naction,42\n", content_type="text/csv",
                              headers={"Content-Disposition": 'attachment; filename="runtime_usage.csv"'})
            else:
                payload = report_payload()
                if self.usage_empty:
                    payload["entities"] = []
                route.fulfill(json=payload)
        elif self.classic and parsed.path == "/classic-usage":
            route.fulfill(content_type="text/html", body=(
                '<html lang="en"><head><title>Usage test</title>'
                '<link rel="stylesheet" href="/static/css/bootstrap.min.css" />'
                '<link rel="stylesheet" href="/static/css/control-center-usage.css" /></head><body>'
                '<div id="runtimeUsagePanel"></div><table id="activityLogsTable"></table>'
                '<script type="module" src="/static/js/control-center-usage.js"></script></body></html>'
            ))
        else:
            super()._route(route)


@pytest.mark.parametrize("classic", [False, True], ids=["v2", "classic"])
@pytest.mark.parametrize("viewport", [{"width": 1365, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "mobile"])
def test_usage_filters_safe_names_drill_export_and_failure(page, classic, viewport):
    """Use actual locally built interfaces and server-intercepted metadata."""
    page.set_viewport_size(viewport)
    fixture = UsageFixture(page, classic)
    if classic:
        page.goto(ORIGIN + "/classic-usage")
        page.locator("summary").click()
    else:
        fixture.open(mobile=viewport["width"] < 500)
        page.get_by_role("button", name="Show usage", exact=True).click()
    panel = page.locator("#runtimeUsagePanel") if classic else page.get_by_role("region", name="Agent, action & workflow usage")
    expect(panel.get_by_text("42 · 3 distinct users", exact=True)).to_have_count(3)
    expect(panel.get_by_text("api.example.test / managed_identity" if classic else "api.example.test", exact=classic)).to_be_visible()
    expect(panel.get_by_text("<img src=x onerror=alert(1)>", exact=False)).to_be_visible()
    assert panel.locator("img").count() == 0
    artifacts = Path(__file__).resolve().parent / "artifacts"
    artifacts.mkdir(exist_ok=True)
    page.screenshot(path=str(artifacts / f"runtime-usage-{'classic' if classic else 'v2'}-{viewport['width']}.png"), full_page=True)
    panel.get_by_label("Entity kind", exact=True).select_option("action")
    panel.get_by_label("Configured host", exact=True).fill("api.example.test")
    panel.get_by_role("button", name="Apply usage filters", exact=True).click()
    expect(panel.get_by_role("button", name="View events", exact=True)).to_be_visible()
    with page.expect_download() as downloaded:
        panel.get_by_role("link", name="Export usage CSV", exact=True).click()
    assert downloaded.value.suggested_filename
    if classic:
        page.evaluate("document.addEventListener('runtime-usage-filter', e => { window.usageDrill = e.detail; });")
        panel.get_by_role("button", name="View events", exact=True).click()
        drill = page.evaluate("window.usageDrill")
        assert drill["usage_entity_id"] == "action-1"
        assert drill["usage_host"] == "api.example.test"
    else:
        panel.get_by_role("button", name="View events", exact=True).click()
        expect(page).to_have_url(re.compile("usage_entity_id=action-1"))
    fixture.usage_fail = True
    panel.get_by_role("button", name="Reload usage", exact=True).click()
    expect(panel.get_by_text("Narrow the date range.", exact=False)).to_be_visible()
    fixture.usage_fail = False
    fixture.usage_empty = True
    panel.get_by_role("button", name="Reload usage", exact=True).click()
    expect(panel.get_by_text("No recorded usage matches these filters.", exact=True)).to_be_visible()
    assert not fixture.console_errors
    assert any(query.get("usage_host") == ["api.example.test"] for query in fixture.usage_queries)
