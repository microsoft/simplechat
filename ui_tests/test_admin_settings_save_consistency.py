# test_admin_settings_save_consistency.py
"""
Admin form concurrency contract and optional authenticated browser regression.
Version: 0.261.025
Implemented in: 0.261.025

The live test submits only an invalid revision, so it cannot change any settings.
"""

import os
from pathlib import Path
import re

from jinja2 import Environment
import pytest
from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[1]


def test_admin_form_carries_escaped_revision():
    source = (ROOT / "application" / "single_app" / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    field = re.search(r'<input[^>]+name="admin_settings_etag"[^>]+>', source)
    assert field is not None
    rendered = Environment(autoescape=True).from_string(field.group()).render(settings={"_etag": '"revision"'})
    assert "&#34;revision&#34;" in rendered


@pytest.mark.ui
def test_stale_admin_form_is_rejected_before_settings_are_parsed(playwright):
    base_url = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
    storage_state = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE")
    if not base_url or not storage_state or not Path(storage_state).is_file():
        pytest.skip("An authenticated admin UI test environment is required.")
    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=storage_state)
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/admin/settings", wait_until="domcontentloaded")
        assert response and response.ok
        field = page.locator('input[name="admin_settings_etag"]')
        expect(field).to_have_count(1)
        assert field.input_value()
        page.evaluate("""() => {
            const form = document.getElementById('admin-settings-form');
            for (const element of form.elements) element.disabled = true;
            const revision = document.createElement('input');
            revision.type = 'hidden';
            revision.name = 'admin_settings_etag';
            revision.value = 'deliberately-stale-test-revision';
            form.appendChild(revision);
            form.submit();
        }""")
        expect(page.get_by_text(
            "Settings changed since this page was loaded. Review the latest settings and try again.",
            exact=True,
        )).to_be_visible()
    finally:
        context.close()
        browser.close()
