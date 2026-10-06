# test_v2_admin_enhanced_extraction_section.py
"""
Browser coverage for the V2 Admin Settings Enhanced Extraction section.
Version: 0.261.265
Implemented in: 0.261.265

Exercise the built application with the real field schema and intercepted APIs.
Check that Enhanced extraction is the switch that leads its own card rather than a
control inside a collapsed Document Intelligence group, that nothing it governs --
Content Understanding included -- can be edited while it is off, that turning it on
moves the mode to Auto and opens the Content Understanding connection, that the card
names the engine in force as the connection is filled in, and that a cloud without
Content Understanding shows the Layout fallback instead. No live settings are written.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

# Fixtures stay under ui_tests; the import also registers Azure connect_options.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

SECTIONS = {"knowledge": ("document-intelligence-section", "enhanced-extraction-section")}
REGION = "Enhanced Extraction"
SWITCH = "Enable Enhanced extraction"
MODE = "document_intelligence_pdf_image_extraction_mode"
ARTIFACTS = "v2_admin_enhanced_extraction"


@pytest.fixture
def extraction_ui(page):
    fixture = AdminSettingsFixture(page, sections=SECTIONS, validate_updates=True)
    fixture.payload["runtime_flags"] = {"content_understanding_supported": True}
    yield fixture
    fixture.assert_clean()


def _region(page):
    return page.get_by_role("region", name=REGION, exact=True)


def _switch(scope):
    return scope.get_by_role("checkbox", name=re.compile(f"^{re.escape(SWITCH)}"))


def _set_switch(page, checked):
    switch = _switch(_region(page))
    if switch.is_checked() != checked:
        _region(page).get_by_text(SWITCH, exact=True).click()
    expect(switch).to_be_checked(checked=checked)


def _group(page, label):
    return _region(page).get_by_role("button", name=re.compile(f"^{re.escape(label)}"))


def _engine(page):
    return _region(page).get_by_test_id("enhanced-extraction-engine")


def _save(fixture):
    fixture.page.get_by_role("button", name="Save changes", exact=True).click()
    expect(fixture.page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)


def test_with_enhanced_off_the_card_is_only_its_switch(extraction_ui):
    """Content Understanding cannot be filled in while Enhanced extraction is off."""
    extraction_ui.open(ready_region=REGION)
    page = extraction_ui.page
    region = _region(page)

    expect(_switch(region)).not_to_be_checked()
    expect(region.get_by_text("Off", exact=True)).to_be_visible()
    expect(region.get_by_role("combobox")).to_have_count(0)
    expect(region.get_by_role("textbox")).to_have_count(0)
    expect(_group(page, "Content Understanding connection")).to_have_count(0)
    # The switch now leads its own card instead of hiding in a Document
    # Intelligence group that had to be opened to find it.
    intelligence = page.get_by_role("region", name="Document Intelligence", exact=True)
    expect(_switch(intelligence)).to_have_count(0)
    extraction_ui.capture("off", folder=ARTIFACTS)


def test_turning_enhanced_on_brings_auto_and_the_connection(extraction_ui):
    """The next steps appear with the switch, and the engine follows the connection."""
    extraction_ui.open(ready_region=REGION)
    page = extraction_ui.page
    region = _region(page)

    _set_switch(page, True)

    expect(region.get_by_role("combobox", name="PDF and Image Extraction Mode")).to_have_value("auto")
    expect(_group(page, "Content Understanding connection")).to_have_attribute("aria-expanded", "true")
    expect(_group(page, "Content Understanding analyzers")).to_have_attribute("aria-expanded", "false")
    engine = _engine(page)
    expect(engine).to_have_attribute("data-engine", "document_intelligence")
    expect(engine).to_contain_text("Add a Foundry endpoint")
    expect(engine).to_contain_text("Takes effect when you save.")

    region.get_by_role("textbox", name="Foundry Endpoint").fill("https://contoso.services.ai.azure.com")
    expect(engine).to_contain_text("an endpoint but no key")

    region.get_by_role("combobox", name="Authentication Type").select_option("managed_identity")
    expect(engine).to_have_attribute("data-engine", "content_understanding")
    expect(engine).to_contain_text("Azure AI Content Understanding")
    extraction_ui.capture("on-connected-unsaved", folder=ARTIFACTS)

    _save(extraction_ui)
    assert extraction_ui.patches == [{
        "enable_enhanced_extraction": True,
        MODE: "auto",
        "azure_content_understanding_endpoint": "https://contoso.services.ai.azure.com",
        "azure_content_understanding_authentication_type": "managed_identity",
    }], extraction_ui.patches
    expect(engine).not_to_contain_text("Takes effect when you save.")
    expect(region.get_by_text("Configured", exact=True)).to_be_visible()


def test_turning_enhanced_back_off_before_saving_takes_the_mode_back(extraction_ui):
    """The draft only carries what the administrator chose."""
    extraction_ui.open(ready_region=REGION)
    page = extraction_ui.page

    _set_switch(page, True)
    expect(_region(page).get_by_role("combobox", name="PDF and Image Extraction Mode")).to_have_value("auto")
    _set_switch(page, False)
    expect(_region(page).get_by_role("combobox")).to_have_count(0)

    _save(extraction_ui)
    assert extraction_ui.patches == [{"enable_enhanced_extraction": False}], extraction_ui.patches


def test_a_connected_content_understanding_reads_as_a_summary(extraction_ui):
    """A working connection folds away, and the card says what it gives."""
    extraction_ui.settings.update({
        "enable_enhanced_extraction": True,
        MODE: "auto",
        "azure_content_understanding_endpoint": "https://contoso.services.ai.azure.com",
        "azure_content_understanding_authentication_type": "managed_identity",
    })
    extraction_ui.open(ready_region=REGION)
    page = extraction_ui.page

    engine = _engine(page)
    expect(engine).to_have_attribute("data-engine", "content_understanding")
    expect(engine).to_contain_text("descriptions of figures and charts")
    expect(engine).not_to_contain_text("Takes effect when you save.")
    expect(_group(page, "Content Understanding connection")).to_have_attribute("aria-expanded", "false")

    _group(page, "Content Understanding connection").click()
    expect(_region(page).get_by_role("textbox", name="Foundry Endpoint")).to_have_value(
        "https://contoso.services.ai.azure.com"
    )


def test_a_cloud_without_content_understanding_shows_the_layout_fallback(extraction_ui):
    """Azure Government and custom clouds have nothing to configure beyond the switch."""
    extraction_ui.payload["runtime_flags"] = {"content_understanding_supported": False}
    extraction_ui.settings.update({"enable_enhanced_extraction": True, MODE: "auto"})
    extraction_ui.open(ready_region=REGION)
    page = extraction_ui.page

    engine = _engine(page)
    expect(engine).to_have_attribute("data-engine", "document_intelligence")
    expect(engine).to_contain_text("not offered in this Azure cloud")
    expect(engine).to_contain_text("nothing more to configure")
    expect(_group(page, "Content Understanding connection")).to_have_count(0)
    expect(_group(page, "Content Understanding analyzers")).to_have_count(0)
    expect(_region(page).get_by_role("combobox", name="PDF and Image Extraction Mode")).to_be_visible()


@pytest.mark.parametrize("width", [390, 1440])
def test_the_card_fits_phone_and_desktop_widths(extraction_ui, width):
    """The switch leads its settings, and nothing runs past the card at either width."""
    extraction_ui.settings.update({"enable_enhanced_extraction": True, MODE: "auto"})
    extraction_ui.open(width=width, ready_region=REGION)
    page = extraction_ui.page

    region = _region(page)
    expect(region.locator('[data-setting-emphasis="primary"]')).to_contain_text(SWITCH)
    # Mode, Auto's sample pages and formulas sit beneath the switch they depend on.
    expect(region.locator('[data-setting-emphasis="dependent"]')).to_have_count(3)
    expect(_engine(page)).to_be_visible()
    expect(_group(page, "Content Understanding connection")).to_have_attribute("aria-expanded", "true")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    overflow = region.evaluate("element => element.scrollWidth - element.clientWidth")
    assert overflow <= 1, f"The card overflows by {overflow}px at {width}px"
    extraction_ui.capture(f"on-unconnected-{width}", folder=ARTIFACTS)
