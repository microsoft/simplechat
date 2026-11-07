# test_v2_m365_transport_settings.py
"""
Native Microsoft 365 settings controls using the production schema and validator.
Version: 0.261.122
Implemented in: 0.261.122

Uses the shared Azure Playwright/local browser fixture and local built assets.
All API traffic is isolated; no account, settings store, or cloud is modified.
"""

import sys
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

# The repository keeps reusable UI fixtures separate from functional-test imports.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options


pytestmark = pytest.mark.ui


@pytest.fixture
def transport_ui(page):
    fixture = AdminSettingsFixture(page, validate_updates=True)
    yield fixture
    fixture.assert_clean()


def open_transport_settings(fixture, width=1440):
    fixture.open(width=width)
    fixture.page.get_by_role("button", name=re.compile(r"^Microsoft 365 retrieval")).click()


@pytest.mark.parametrize("width", [390, 1440])
def test_native_transport_settings_save_normalize_and_clear_without_truncation(transport_ui, width):
    open_transport_settings(transport_ui, width)
    page = transport_ui.page
    provider = page.get_by_label("Retrieval provider", exact=True)
    hosts = page.get_by_label("Additional trusted file-download hosts", exact=True)
    expect(provider).to_have_value("auto")
    expect(hosts).to_have_value("")
    provider.select_option("graph")
    long_host = "a" * 60 + "." + "b" * 60 + ".example"
    hosts.fill(f"*.FILES.EXAMPLE.\n{long_host}")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert transport_ui.settings["m365_retrieval_provider"] == "graph"
    assert transport_ui.settings["m365_trusted_download_hosts"] == ["files.example", long_host]
    expect(hosts).to_have_value(f"files.example,{long_host}")
    hosts.fill("")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert transport_ui.settings["m365_trusted_download_hosts"] == []
    assert transport_ui.settings["m365_retrieval_provider"] == "graph"
    assert set(transport_ui.patches[-1]) == {"m365_trusted_download_hosts"}


def test_invalid_download_host_stays_a_visible_unsaved_draft(transport_ui):
    open_transport_settings(transport_ui)
    page = transport_ui.page
    hosts = page.get_by_label("Additional trusted file-download hosts", exact=True)
    hosts.fill("https://unapproved.example/file")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("alert").filter(
        has_text="Configure valid trusted Microsoft 365 download hosts.",
    )).to_be_visible()
    expect(hosts).to_have_value("https://unapproved.example/file")
    assert transport_ui.settings["m365_trusted_download_hosts"] == []
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(hosts).to_have_value("")
    transport_ui.errors = [error for error in transport_ui.errors if "400 (Bad Request)" not in error]
