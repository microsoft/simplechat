# test_semantic_search_health_warning.py
"""
UI test for Semantic Ranker quota health warning rendering.
Version: 0.241.086
Implemented in: 0.241.086

This test ensures the workspace/admin service-health warning renders visibly and
escapes settings-backed warning text before it reaches the browser.
"""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "application" / "single_app" / "templates"


@pytest.mark.ui
def test_semantic_search_health_warning_partial_renders_safely():
    """Render the warning partial in a browser and verify visible, escaped output."""
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError:
        pytest.skip("Install Playwright to run this UI test.")

    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = environment.get_template("_semantic_search_health_warning.html")
    rendered_html = template.render(
        settings={
            "service_health": {
                "semantic_search": {
                    "status": "quota_exceeded",
                    "user_message": "Azure AI Search Semantic Ranker free query usage has been exceeded for the month. <script>alert('x')</script>",
                    "admin_resolution": "Upgrade Semantic Ranker to Standard.",
                    "last_seen_at": "2026-05-21T12:00:00+00:00",
                }
            }
        }
    )

    playwright_context = sync_playwright().start()
    browser = None
    try:
        try:
            browser = playwright_context.chromium.launch()
        except Exception as ex:
            pytest.skip(f"Playwright Chromium is not available: {ex}")

        page = browser.new_page()
        page.set_content(f"<!doctype html><html><body>{rendered_html}</body></html>")

        warning = page.get_by_test_id("semantic-search-health-warning")
        expect(warning).to_be_visible()
        expect(warning).to_contain_text("Workspace search warning")
        expect(warning).to_contain_text("Semantic Ranker free query usage has been exceeded")
        expect(warning).to_contain_text("Upgrade Semantic Ranker to Standard")
        expect(page.locator("script")).to_have_count(0)
    finally:
        if browser is not None:
            browser.close()
        playwright_context.stop()
