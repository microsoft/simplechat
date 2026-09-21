# test_admin_settings_save_consistency.py
"""
Admin form concurrency contract and optional authenticated browser regression.
Version: 0.261.125
Implemented in: 0.261.025
Index diagnostic revision and queued-submit regressions: 0.261.125

The live test submits only an invalid revision, so it cannot change any settings.
"""

import os
from pathlib import Path
import re
import sys

from jinja2 import Environment
import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from admin_diagnostics import ClassicAdminDiagnosticsFixture
from playwright_connection import connect_options  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_admin_form_carries_escaped_revision():
    source = (ROOT / "application" / "single_app" / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    field = re.search(r'<input[^>]+name="admin_settings_etag"[^>]+>', source)
    assert field is not None
    rendered = Environment(autoescape=True).from_string(field.group()).render(settings={"_etag": '"revision"'})
    assert "&#34;revision&#34;" in rendered


@pytest.fixture
def diagnostics_ui(page):
    fixture = ClassicAdminDiagnosticsFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.mark.ui
@pytest.mark.parametrize("record_metadata", [False, True])
def test_save_after_index_checks_uses_only_its_own_revision(diagnostics_ui, record_metadata):
    fixture = diagnostics_ui
    fixture.record_metadata = record_metadata
    fixture.open()
    page = fixture.page
    page.locator("#key_vault_name").fill("unsaved-vault")
    save = page.locator("#floating-save-btn")
    expect(save).to_be_enabled()
    assert [request["indexType"] for request in fixture.index_requests] == ["user", "group", "public"]
    expected_revisions = [f'"revision-{number}"' for number in (1, 2, 3)] if record_metadata else ['"revision-1"'] * 3
    assert [request["settings_etag"] for request in fixture.index_requests] == expected_revisions
    expect(page.locator('input[name="admin_settings_etag"]')).to_have_value(fixture.etag)
    save.click()
    expect(page.get_by_text("Saved fixture settings.", exact=True)).to_be_visible()
    assert fixture.submissions[0]["admin_settings_etag"] == [fixture.etag]
    assert fixture.submissions[0]["key_vault_name"] == ["unsaved-vault"]


@pytest.mark.ui
def test_submission_waits_for_initial_metadata_checks(diagnostics_ui):
    fixture = diagnostics_ui
    fixture.hold_indexes = True
    fixture.record_metadata = True
    fixture.open()
    page = fixture.page
    page.locator("#key_vault_name").fill("unsaved-vault")
    expect(page.locator("#floating-save-btn")).to_be_disabled()
    page.evaluate("document.getElementById('admin-settings-form').requestSubmit()")
    assert fixture.submissions == []
    assert len(fixture.index_requests) == 1
    fixture.release_indexes()
    expect(page.get_by_text("Saved fixture settings.", exact=True)).to_be_visible()
    assert fixture.submissions[0]["admin_settings_etag"] == ['"revision-4"']


@pytest.mark.ui
def test_queued_submission_rechecks_browser_validation(diagnostics_ui):
    fixture = diagnostics_ui
    fixture.hold_indexes = True
    fixture.open()
    page = fixture.page
    page.locator("#key_vault_name").fill("unsaved-vault")
    page.evaluate("document.getElementById('admin-settings-form').requestSubmit()")
    page.locator("#key_vault_name").fill("")
    fixture.release_indexes()
    expect(page.locator("#floating-save-btn")).to_be_enabled()
    assert fixture.submissions == []
    missing_value = page.locator("#key_vault_name").evaluate("(input) => input.validity.valueMissing")
    assert missing_value is True


@pytest.mark.ui
def test_concurrent_settings_edit_does_not_fast_forward_or_discard_draft(diagnostics_ui):
    fixture = diagnostics_ui
    fixture.hold_indexes = True
    fixture.open()
    page = fixture.page
    page.locator("#key_vault_name").fill("unsaved-vault")
    page.evaluate("document.getElementById('admin-settings-form').requestSubmit()")
    fixture.revision = 10
    fixture.release_indexes()
    expect(page.locator("#index-warning-user")).to_contain_text("Settings changed since this page was loaded")
    expect(page.locator("#fixture-toasts")).to_contain_text("Copy them before reloading")
    expect(page.locator("#floating-save-btn")).to_be_disabled()
    expect(page.locator('input[name="admin_settings_etag"]')).to_have_value('"revision-1"')
    expect(page.locator("#key_vault_name")).to_have_value("unsaved-vault")
    assert fixture.submissions == []
    assert len(fixture.index_requests) == 1


@pytest.mark.ui
@pytest.mark.parametrize("status,payload,action_visible", [
    (500, {"error": "Unable to inspect Azure AI Search.", "code": "index_check_failed"}, False),
    (404, {"error": "The user index does not exist yet.", "needsCreation": True}, True),
])
def test_index_failures_are_visible_without_claiming_success(diagnostics_ui, status, payload, action_visible):
    fixture = diagnostics_ui
    fixture.index_errors["user"] = (status, payload)
    fixture.open()
    page = fixture.page
    expect(page.locator("#index-warning-user")).to_be_visible()
    expect(page.locator("#missing-fields-user")).to_have_text(payload["error"])
    button = page.locator("#fix-user-index-btn")
    if action_visible:
        expect(button).to_be_visible()
        expect(button).to_have_text("Create user Index")
    else:
        expect(button).not_to_be_visible()
        expect(page.locator("#fixture-toasts")).to_contain_text("An AI Search index check failed")


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
