# test_admin_support_export.py
"""
Classic support-export interaction, download, and layout coverage.
Version: 0.261.426
Implemented in: 0.261.426
"""

import sys
import zipfile
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from support_export_backend import ClassicSupportPage, SupportBackend


pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width,theme", [(1440, "light"), (390, "dark")])
def test_classic_support_zip_is_reviewed_and_downloaded(page, tmp_path, width, theme):
    backend = SupportBackend()
    fixture = ClassicSupportPage(page, backend)
    fixture.open(width=width, theme=theme)
    page.get_by_label("Selected user", exact=True).select_option("owner")
    page.get_by_label("Application Insights telemetry", exact=False).uncheck()
    page.get_by_role("button", name="Review export scope", exact=True).click()
    expect(page.get_by_role("heading", name="Review the exact collection scope")).to_be_visible()
    expect(page.get_by_role("button", name="Generate support ZIP", exact=True)).to_be_disabled()
    page.get_by_label("I reviewed the scope", exact=False).check()
    page.get_by_role("button", name="Generate support ZIP", exact=True).click()
    page.get_by_role("button", name="Refresh export status").click()
    expect(page.get_by_role("button", name="Review redacted preview")).to_be_visible()
    page.get_by_role("button", name="Review redacted preview").click()
    expect(page.locator("#support-export-preview")).to_contain_text("Preview only")
    page.get_by_label("I reviewed the scrubbed preview", exact=False).check()
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Download support ZIP", exact=True).click()
    path = tmp_path / "support.zip"
    downloaded.value.save_as(path)
    with zipfile.ZipFile(path) as archive:
        contents = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"owner@example.test" not in contents and b"fake-password" not in contents
        assert b"unrelated event" not in contents
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert overflow is False
    fixture.assert_clean()


def test_classic_scope_edit_does_not_submit_unrelated_settings(page):
    backend = SupportBackend()
    fixture = ClassicSupportPage(page, backend)
    fixture.open()
    page.get_by_label("Selected user", exact=True).select_option("owner")
    page.get_by_label("Find conversation ID", exact=True).fill("conversation-1")
    page.get_by_role("button", name="Find conversations", exact=True).click()
    page.get_by_label("conversation-1 (personal;", exact=False).check()
    page.get_by_label("Request whole personal-conversation", exact=False).check()
    page.get_by_label("All users (explicitly", exact=False).check()
    expect(page.get_by_label("Request whole personal-conversation", exact=False)).not_to_be_checked()
    expect(page.get_by_label("Collection mode", exact=True)).to_have_value("time")
    assert not backend.posts
    fixture.assert_clean()
