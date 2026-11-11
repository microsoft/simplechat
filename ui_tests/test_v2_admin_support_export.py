# test_v2_admin_support_export.py
"""
Built V2 support-export browser coverage with the real support backend.
Version: 0.261.426
Implemented in: 0.261.426
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from support_export_backend import API_PATTERN, SupportBackend
from v2_admin_settings import AdminSettingsFixture


pytestmark = pytest.mark.ui


@pytest.fixture
def support_ui(page):
    backend = SupportBackend()
    fixture = AdminSettingsFixture(page, sections={"operations": ("support-log-export-section",)})
    page.route(API_PATTERN, backend.handle)
    yield fixture, backend
    fixture.assert_clean()


@pytest.mark.parametrize("width,theme", [(1440, "light"), (390, "dark")])
def test_v2_complete_diagnostic_zip_workflow(support_ui, tmp_path, width, theme):
    fixture, backend = support_ui
    fixture.open(width=width, theme=theme, ready_region="Support Log Export")
    page = fixture.page
    panel = page.get_by_test_id("support-export-panel")
    panel.get_by_label("Selected user", exact=True).select_option("owner")
    panel.get_by_label("Application Insights telemetry", exact=False).uncheck()
    panel.get_by_role("button", name="Review export scope", exact=True).click()
    expect(panel.get_by_role("heading", name="Review the exact collection scope")).to_be_visible()
    generate = panel.get_by_role("button", name="Generate support ZIP", exact=True)
    expect(generate).to_be_disabled()
    panel.get_by_label("I reviewed the scope", exact=False).check()
    generate.click()
    expect(panel.get_by_role("button", name="Refresh export status")).to_be_visible()
    panel.get_by_role("button", name="Refresh export status").click()
    expect(panel.get_by_role("button", name="Review redacted preview")).to_be_visible()
    panel.get_by_role("button", name="Review redacted preview").click()
    expect(panel.get_by_test_id("support-export-preview")).to_contain_text("Preview only")
    download = panel.get_by_role("button", name="Download support ZIP", exact=True)
    expect(download).to_be_disabled()
    panel.get_by_label("I reviewed the scrubbed preview", exact=False).check()
    with page.expect_download() as downloaded:
        download.click()
    path = tmp_path / "support.zip"
    downloaded.value.save_as(path)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["sources"]["activity"]["records"] == 1
        text = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"owner@example.test" not in text and b"fake-password" not in text
    assert not fixture.patches
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert overflow is False
    fixture.capture(f"support-export-{width}-{theme}", "support_exports")


def test_v2_user_change_clears_conversations_and_owner_consent_selection(support_ui):
    fixture, _ = support_ui
    fixture.open(ready_region="Support Log Export")
    panel = fixture.page.get_by_test_id("support-export-panel")
    panel.get_by_label("Selected user", exact=True).select_option("owner")
    conversation = panel.get_by_label("conversation-1 (personal;", exact=False)
    conversation.check()
    panel.get_by_label("Request whole personal-conversation", exact=False).check()
    panel.get_by_label("All users (explicitly", exact=False).check()
    expect(panel.get_by_label("Request whole personal-conversation", exact=False)).not_to_be_checked()
    expect(panel.get_by_label("Request whole personal-conversation", exact=False)).to_be_disabled()
    expect(panel.get_by_label("Collection mode", exact=True)).to_have_value("time")


def test_v2_missing_user_is_visible_without_submitting(support_ui):
    fixture, backend = support_ui
    fixture.open(ready_region="Support Log Export")
    fixture.page.get_by_role("button", name="Review export scope", exact=True).click()
    expect(fixture.page.get_by_role("alert")).to_contain_text("Select one SimpleChat user")
    assert not backend.posts
