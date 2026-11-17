#!/usr/bin/env python3
# test_v2_admin_section_links.py
"""
Browser coverage for the Admin Settings links that used to leave V2.
Version: 0.261.445
Implemented in: 0.261.445

A link to a section stays inside V2 whenever V2 draws the section, and opens the classic tab that
holds it, in a new tab, only for a section V2 never draws. The classic page reads the address
fragment as a tab id, so a link there names the tab and not the section, and it carries the classic
escape pair (`ui=classic`) so it still opens the classic page once the redirect to V2 is switched
on. Exercise the built application with the real navigation and schema: a related-section link and
a prerequisite notice move within the page for a section V2 draws and open the classic tab for one
it does not, the chat mode notice points at the connections section and at the classic endpoint's
tab, and the global identities section no longer hands off to the classic page at all (it edits in
place; see test_v2_admin_global_identities.py).
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

# Fixtures stay under ui_tests; the import also registers Azure connect_options.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401
from test_support.nav import ADMIN_NAV  # noqa: E402


pytestmark = pytest.mark.ui

ARTIFACTS = "v2_admin_section_links"
WIDTHS = [1440, 390]


def classic_only_group():
    """Chat > Citation > Standard citations, the one card V2 has nothing to draw."""
    group = copy.deepcopy(next(
        group for group in ADMIN_NAV if any(tab["id"] == "citation" for tab in group["tabs"])
    ))
    group["tabs"] = [tab for tab in group["tabs"] if tab["id"] == "citation"]
    group["tabs"][0]["sections"] = [
        section for section in group["tabs"][0]["sections"] if section["id"] == "standard-citations-section"
    ]
    return group


def field_of(ui, section_id, key):
    return next(field for field in ui.payload["field_schema"][section_id] if field.get("key") == key)


def region(page, name):
    return page.get_by_role("region", name=name, exact=True)


@pytest.fixture
def operations_links_ui(page):
    fixture = AdminSettingsFixture(
        page, sections={"operations": ("debug-logging-section", "health-check-section")},
    )
    fixture.settings.pop("enable_semantic_kernel", None)
    fixture.payload["admin_nav"].append(classic_only_group())
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def file_sync_links_ui(page):
    fixture = AdminSettingsFixture(
        page, sections={"knowledge": ("file-sync-section",), "operations": ("health-check-section",)},
    )
    fixture.settings.pop("enable_semantic_kernel", None)
    fixture.settings.update({"enable_file_sync": True, "enable_redis_cache": False})
    fixture.payload["admin_nav"].append(classic_only_group())
    yield fixture
    fixture.assert_clean()


def open_diagnostics(ui, width):
    ui.open(width=width, ready_region="Debug Logging")
    debug = region(ui.page, "Debug Logging")
    debug.get_by_role("button", name=re.compile("^Feature diagnostics")).click()
    return debug


def fits_the_screen(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "The page scrolls sideways"
    )


@pytest.mark.parametrize("width", WIDTHS)
def test_a_related_section_v2_draws_is_reached_within_the_page(operations_links_ui, width):
    ui = operations_links_ui
    field_of(ui, "debug-logging-section", "enable_dai_debug")["related_section"] = {
        "section_id": "health-check-section", "label": "Health Check",
    }
    debug = open_diagnostics(ui, width)
    page = ui.page

    link = debug.get_by_role("button", name="Go to Health Check")
    expect(link).to_be_visible()
    expect(debug.get_by_role("link", name=re.compile("classic admin page"))).to_have_count(0)
    fits_the_screen(page)
    link.click()
    expect(region(page, "Health Check")).to_be_in_viewport()
    expect(page).to_have_url(re.compile(r"/v2/admin$"))


@pytest.mark.parametrize("width", WIDTHS)
def test_a_related_section_v2_never_draws_opens_the_classic_tab_in_a_new_tab(operations_links_ui, width):
    ui = operations_links_ui
    field_of(ui, "debug-logging-section", "enable_dai_debug")["related_section"] = {
        "section_id": "standard-citations-section", "label": "Standard citations",
    }
    debug = open_diagnostics(ui, width)

    link = debug.get_by_role("link", name=re.compile("^Open Standard citations on the classic admin page"))
    expect(link).to_be_visible()
    # The classic page reads the fragment as a tab id, so the link names the tab, not the section.
    # The escape pair keeps it a classic page when the redirect to V2 is on.
    expect(link).to_have_attribute("href", "/admin/settings?ui=classic#citation")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", re.compile("noopener"))
    expect(debug.get_by_role("button", name=re.compile("^Go to "))).to_have_count(0)
    fits_the_screen(ui.page)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_prerequisite_for_a_section_v2_draws_is_reached_within_the_page(file_sync_links_ui, width):
    ui = file_sync_links_ui
    field_of(ui, "file-sync-section", "enable_file_sync")["requires"]["target_section"] = "health-check-section"
    ui.open(width=width, ready_region="File Sync")
    page = ui.page
    card = region(page, "File Sync")

    expect(card.get_by_text("Redis Cache", exact=False).first).to_be_visible()
    link = card.get_by_role("button", name="Configure Redis Cache", exact=True)
    expect(link).to_be_visible()
    expect(card.get_by_role("link", name=re.compile("classic admin page"))).to_have_count(0)
    fits_the_screen(page)
    link.click()
    expect(region(page, "Health Check")).to_be_in_viewport()
    expect(page).to_have_url(re.compile(r"/v2/admin$"))


@pytest.mark.parametrize("width", WIDTHS)
def test_a_prerequisite_for_a_section_v2_never_draws_opens_the_classic_tab(file_sync_links_ui, width):
    ui = file_sync_links_ui
    field_of(ui, "file-sync-section", "enable_file_sync")["requires"]["target_section"] = "standard-citations-section"
    ui.open(width=width, ready_region="File Sync")
    card = region(ui.page, "File Sync")

    link = card.get_by_role("link", name=re.compile("^Configure Redis Cache on the classic admin page"))
    expect(link).to_be_visible()
    expect(link).to_have_attribute("href", "/admin/settings?ui=classic#citation")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", re.compile("noopener"))
    expect(card.get_by_role("button", name="Configure Redis Cache")).to_have_count(0)
    fits_the_screen(ui.page)


def test_a_prerequisite_whose_section_the_navigation_does_not_name_links_nowhere(file_sync_links_ui):
    ui = file_sync_links_ui
    field_of(ui, "file-sync-section", "enable_file_sync")["requires"]["target_section"] = "no-such-section"
    ui.open(width=1440, ready_region="File Sync")
    card = region(ui.page, "File Sync")

    # The notice still says what is missing; it just has nowhere to send the reader.
    expect(card.get_by_text("Redis Cache", exact=False).first).to_be_visible()
    expect(card.get_by_role("button", name="Configure Redis Cache")).to_have_count(0)
    expect(card.get_by_role("link", name=re.compile("^Configure Redis Cache"))).to_have_count(0)


@pytest.mark.parametrize("width", WIDTHS)
def test_the_chat_mode_notice_points_at_the_connections_and_at_the_classic_endpoint_tab(page, width):
    ui = AdminSettingsFixture(page, sections={"ai-models": ("gpt-config", "multi-endpoint-configuration")})
    ui.settings.pop("enable_semantic_kernel", None)
    ui.settings["enable_multi_model_endpoints"] = False
    # The Chat card's default-model picker reads its choices; the notice does not depend on them.
    ui.extra_routes[("GET", "/api/v2/admin/capability-models/chat")] = lambda route: route.fulfill(json={
        "capability": "chat", "enabled": True, "multi_endpoint_enabled": False, "choices": [],
        "selection": {"endpoint_id": "", "model_id": "", "provider": ""}, "reason": None,
    })
    try:
        ui.open(width=width, ready_region="Chat")
        notice = ui.page.get_by_role("note").filter(has_text="Chat is using the classic single endpoint.")
        expect(notice).to_be_visible()

        classic = notice.get_by_role("link", name=re.compile("^classic admin page"))
        expect(classic).to_have_attribute("href", "/admin/settings?ui=classic#model-endpoints")
        expect(classic).to_have_attribute("target", "_blank")
        # The switch it tells the administrator to turn on is named as the page labels it.
        expect(notice.get_by_text("Use AI Connections for chat", exact=True)).to_be_visible()
        fits_the_screen(ui.page)

        notice.get_by_role("button", name="Go to AI Connections").click()
        expect(ui.page.get_by_role("region", name="AI Connections", exact=True)).to_be_in_viewport()
        expect(ui.page).to_have_url(re.compile(r"/v2/admin$"))
    finally:
        ui.assert_clean()


@pytest.mark.parametrize("width", WIDTHS)
def test_the_global_identities_section_no_longer_hands_off_to_the_classic_page(page, width):
    ui = AdminSettingsFixture(page, sections={"security": ("workspace-identities-section",)})
    ui.settings.pop("enable_semantic_kernel", None)
    ui.extra_routes[("GET", "/api/admin/workspace-identities/global/identities")] = (
        lambda route: route.fulfill(json={"identities": []})
    )
    try:
        ui.open(width=width, ready_region="Global Identities")
        card = region(ui.page, "Global Identities")
        # V2 creates, edits and deletes global identities in place, so nothing here leaves V2.
        expect(card.get_by_role("button", name="New identity", exact=True)).to_be_visible()
        expect(card.get_by_role("link")).to_have_count(0)
        expect(card.get_by_text(re.compile("classic", re.IGNORECASE))).to_have_count(0)
        fits_the_screen(ui.page)
    finally:
        ui.assert_clean()
