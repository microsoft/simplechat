# test_v2_admin_model_catalog_workbench.py
"""
Browser coverage for the native V2 Model Catalog workbench.
Version: 0.261.256
Implemented in: 0.261.256

Exercise the built application with the real catalog profiles, field schema, and
intercepted APIs. Check that each profile reads as one line -- name, vendor, and
connected-model count -- that the detail tabs follow the keyboard, and that a
connected model opens its own AI Connection with that model outlined, even when a
search had hidden the AI Connections section. No live settings are written.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

CATALOG_SECTIONS = {"ai-models": ("model-catalog-section", "multi-endpoint-configuration")}
ARTIFACTS = "v2_admin_model_catalog"


@pytest.fixture
def catalog_ui(page):
    fixture = AdminSettingsFixture(page, sections=CATALOG_SECTIONS)
    profiles = fixture.catalog_module.get_effective_model_profiles({})
    fixture.linked = sorted(
        (profile for profile in profiles if profile["publisher"] == "openai"),
        key=lambda profile: profile["displayName"],
    )[:2]
    fixture.unlinked = next(
        profile for profile in sorted(profiles, key=lambda profile: profile["displayName"])
        if profile["id"] not in {linked["id"] for linked in fixture.linked}
    )
    fixture.endpoints = [{
        "id": "endpoint-primary",
        "name": "Primary connection",
        "provider": "aoai",
        "enabled": True,
        "connection": {"endpoint": "https://contoso.openai.azure.com", "openai_api_version": "2024-05-01-preview"},
        "auth": {"type": "managed_identity", "managed_identity_type": "system_assigned"},
        "models": [
            {
                "id": f"model-{index}",
                "deploymentName": f"prod-{profile['id']}",
                "modelName": profile["id"],
                "enabled": True,
                "catalogProfileId": profile["id"],
            }
            for index, profile in enumerate(fixture.linked)
        ],
    }]
    fixture.settings["enable_multi_model_endpoints"] = True
    page.emulate_media(reduced_motion="reduce")
    yield fixture
    fixture.assert_clean()


def _row(page, profile):
    return page.get_by_role("list", name="Catalog profiles").get_by_role(
        "button", name=profile["displayName"], exact=True
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_each_profile_reads_as_name_vendor_and_connected_count(catalog_ui, theme):
    catalog_ui.open(theme=theme, width=1920, height=1080, ready_region="Model Catalog")
    page = catalog_ui.page
    linked, unlinked = catalog_ui.linked[0], catalog_ui.unlinked

    row = _row(page, linked)
    expect(row).to_contain_text(linked["displayName"])
    expect(row).to_contain_text("OpenAI")
    expect(row.locator("[data-catalog-connections]")).to_have_text("1")
    expect(_row(page, unlinked).locator("[data-catalog-connections]")).to_have_text("0")
    box = row.bounding_box()
    assert box and box["height"] < 56, "A profile should read as a single line"
    if linked["summary"]:
        expect(page.get_by_role("list", name="Catalog profiles").get_by_text(linked["summary"])).to_have_count(0)

    row.click()
    expect(page.get_by_role("heading", name=linked["displayName"], level=3)).to_be_visible()
    expect(page.get_by_role("tab", name="Overview")).to_have_attribute("aria-selected", "true")
    catalog_ui.capture(f"catalog-{theme}", ARTIFACTS)


def test_detail_tabs_follow_the_keyboard(catalog_ui):
    catalog_ui.open(width=1920, height=1080, ready_region="Model Catalog")
    page = catalog_ui.page
    _row(page, catalog_ui.linked[0]).click()

    overview = page.get_by_role("tab", name="Overview")
    overview.focus()
    page.keyboard.press("ArrowRight")
    capabilities = page.get_by_role("tab", name="Capabilities")
    expect(capabilities).to_be_focused()
    expect(capabilities).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel")).to_contain_text("Inputs")
    page.keyboard.press("End")
    expect(page.get_by_role("tab", name="Evidence")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel")).to_contain_text("Sources")
    page.keyboard.press("Home")
    expect(overview).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel")).to_contain_text("Task suitability")


def test_a_connected_model_opens_its_own_connection(catalog_ui):
    catalog_ui.open(width=1920, height=1080, ready_region="Model Catalog")
    page = catalog_ui.page
    profile = catalog_ui.linked[1]
    deployment = f"prod-{profile['id']}"

    # The count on the row goes straight to the profile's connections.
    _row(page, profile).locator("[data-catalog-connections]").click()
    expect(page.get_by_role("tab", name=re.compile("^Connections"))).to_have_attribute("aria-selected", "true")
    expect(page.get_by_test_id("catalog-linked-model")).to_contain_text("Primary connection")

    page.get_by_role("button", name=f"Open in AI Connections: {deployment}").click()
    dialog = page.get_by_role("dialog", name="Edit Primary connection")
    expect(dialog).to_be_visible()
    linked_model = dialog.get_by_test_id("connection-model-linked")
    expect(linked_model).to_have_count(1)
    expect(linked_model.get_by_label("Catalog profile")).to_have_value(profile["id"])
    expect(linked_model).to_be_in_viewport()
    catalog_ui.capture("open-connection", ARTIFACTS)

    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(page.locator("#multi-endpoint-configuration")).to_be_in_viewport()


def test_opening_a_connection_clears_a_search_that_hid_it(catalog_ui):
    catalog_ui.open(width=1920, height=1080, ready_region="Model Catalog")
    page = catalog_ui.page
    page.get_by_role("searchbox", name="Search settings").fill("model catalog")
    expect(page.locator("#multi-endpoint-configuration")).to_have_count(0)

    profile = catalog_ui.linked[0]
    _row(page, profile).locator("[data-catalog-connections]").click()
    page.get_by_role("button", name=f"Open in AI Connections: prod-{profile['id']}").click()

    expect(page.get_by_role("searchbox", name="Search settings")).to_have_value("")
    expect(page.get_by_role("dialog", name="Edit Primary connection")).to_be_visible()
    expect(page.locator("#multi-endpoint-configuration")).to_have_count(1)


@pytest.mark.parametrize("width,font_size", [(390, "m"), (1920, "xl")])
def test_the_workbench_never_overflows(catalog_ui, width, font_size):
    catalog_ui.open(width=width, font_size=font_size, ready_region="Model Catalog")
    page = catalog_ui.page
    _row(page, catalog_ui.linked[0]).click()
    for tab in ("Overview", "Capabilities", "Connections", "Evidence"):
        page.get_by_role("tab", name=re.compile(f"^{tab}")).click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        catalog = page.get_by_test_id("model-catalog-manager")
        overflow = catalog.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"The catalog overflows by {overflow}px on {tab} at {width}px/{font_size}"
    catalog_ui.capture(f"responsive-{width}-{font_size}", ARTIFACTS)
