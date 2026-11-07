# test_v2_admin_search_result_cache.py
"""
UI test for the search result cache settings in V2 Admin Settings.

Version: 0.261.263
Implemented in: 0.261.263

Serve the built V2 SPA with the real field schema for the Web Search and Azure AI
Search sections, through the schema-backed fixture, so no application server,
signed-in account or live settings write is needed. Check that the cache is
explained inside Azure AI Search instead of being drawn as a bare key-named switch
under Web Search, that its lifetime is only offered while caching is on, and that
both save through the production field normalizer.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

SECTIONS = {"knowledge": ("web-search-section", "azure-ai-search-section")}
SWITCH_KEY = "enable_search_result_caching"
LIFETIME_KEY = "search_cache_ttl_seconds"
SWITCH_LABEL = "Cache workspace search results"
LIFETIME_LABEL = "Cache lifetime (seconds)"
ARTIFACTS = "v2_admin_search_result_cache"


@pytest.fixture
def cache_ui(page):
    fixture = AdminSettingsFixture(page, validate_updates=True, sections=SECTIONS)
    yield fixture
    fixture.assert_clean()


def _search_region(page):
    return page.get_by_role("region", name="Azure AI Search", exact=True)


def _expand_cache_group(page):
    toggle = _search_region(page).get_by_role("button", name=re.compile("^Search result cache"))
    if toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")


def _switch(page):
    name = re.compile(f"^{re.escape(SWITCH_LABEL)}")
    return _search_region(page).get_by_role("checkbox", name=name)


def _lifetime(page):
    return _search_region(page).get_by_label(LIFETIME_LABEL, exact=True)


def _save(page):
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)


def test_the_cache_is_explained_under_azure_ai_search(cache_ui):
    cache_ui.open(width=1440, ready_region="Azure AI Search")
    page = cache_ui.page
    _expand_cache_group(page)

    region = _search_region(page)
    expect(region.get_by_text("not to web search", exact=False)).to_be_visible()
    access_check = "re-checked against the requesting user's access"
    expect(region.get_by_text(access_check, exact=False)).to_be_visible()
    expect(_switch(page)).to_be_checked()
    lifetime = _lifetime(page)
    expect(lifetime).to_have_value("300")
    expect(lifetime).to_have_attribute("min", "60")
    expect(lifetime).to_have_attribute("max", "3600")

    # The fallback scan drew the bare key under Web Search; nothing of it may remain.
    web_search = page.get_by_role("region", name="Web Search", exact=True)
    expect(web_search.get_by_text(SWITCH_LABEL, exact=False)).to_have_count(0)
    expect(page.get_by_text(SWITCH_KEY, exact=True)).to_have_count(0)
    expect(page.get_by_text("Search result caching", exact=True)).to_have_count(0)
    cache_ui.capture("explained", ARTIFACTS)


def test_turning_the_cache_off_hides_its_lifetime_and_saves_a_boolean(cache_ui):
    cache_ui.open(width=1440, ready_region="Azure AI Search")
    page = cache_ui.page
    _expand_cache_group(page)

    _search_region(page).get_by_text(SWITCH_LABEL, exact=True).click()
    expect(_switch(page)).not_to_be_checked()
    expect(_lifetime(page)).to_have_count(0)

    _save(page)
    assert cache_ui.patches == [{SWITCH_KEY: False}]
    assert cache_ui.settings[SWITCH_KEY] is False
    assert cache_ui.settings[LIFETIME_KEY] == 300

    page.reload(wait_until="networkidle")
    _expand_cache_group(page)
    expect(_switch(page)).not_to_be_checked()
    expect(_lifetime(page)).to_have_count(0)


def test_the_lifetime_saves_within_its_bounds(cache_ui):
    cache_ui.open(width=390, ready_region="Azure AI Search")
    page = cache_ui.page
    _expand_cache_group(page)

    _lifetime(page).fill("5")
    _save(page)
    assert cache_ui.patches == [{LIFETIME_KEY: 5}]
    assert cache_ui.settings[LIFETIME_KEY] == 60
    expect(_lifetime(page)).to_have_value("60")

    _lifetime(page).fill("900")
    _save(page)
    assert cache_ui.patches[-1] == {LIFETIME_KEY: 900}
    assert cache_ui.settings[LIFETIME_KEY] == 900
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
