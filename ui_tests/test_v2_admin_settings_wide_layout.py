# test_v2_admin_settings_wide_layout.py
"""
Browser coverage for the wide V2 Admin Settings layout.
Version: 0.261.253
Implemented in: 0.261.253

Exercise the built application with the real field schema and intercepted APIs.
Check that settings fill the width beside the "On this page" index, that a wide
card puts each label beside its control while a narrow one stacks them, that
independent switches pair up, and that the index reports the same status as the
cards and jumps to them -- in light and dark, at desktop and phone widths, and at
large text sizes, without writing to live settings.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

LAYOUT_SECTIONS = {
    "appearance": ("classification-banner-section", "ai-notice-section"),
    "agents-actions": ("agents-config", "core-plugin-toggles"),
    "knowledge": ("web-search-section",),
}
ARTIFACTS = "v2_admin_layout"


@pytest.fixture
def layout_ui(page):
    fixture = AdminSettingsFixture(page, sections=LAYOUT_SECTIONS)
    fixture.settings.update({
        "classification_banner_enabled": True,
        "classification_banner_text": "UNCLASSIFIED",
        # On, with its Foundry endpoint still empty: the section needs configuration.
        "enable_web_search": True,
        "web_search_foundry_endpoint": "",
    })
    yield fixture
    fixture.assert_clean()


def _box(locator):
    box = locator.bounding_box()
    assert box, "Element is not rendered"
    return box


def _index(page):
    return page.get_by_role("navigation", name="On this page")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_settings_fill_the_width_beside_the_index(layout_ui, theme):
    layout_ui.open(theme=theme, width=1920, height=1080, ready_region="Classification Banner")
    page = layout_ui.page

    content = _box(page.get_by_test_id("admin-settings-content"))
    assert content["width"] > 1000, f"Settings are still a narrow column ({content['width']}px)"

    index = _index(page)
    expect(index).to_be_visible()
    for label in ("Classification Banner", "Chat AI Notice", "Agent Runtime", "Built-in Actions", "Web Search"):
        expect(index.get_by_role("link", name=label)).to_have_count(1)
    assert _box(index)["x"] > content["x"] + content["width"], "The index belongs beside the cards"

    # One status for each section, read the same way by the card and the index.
    web_search = page.get_by_role("region", name="Web Search", exact=True)
    expect(web_search.get_by_text("Needs configuration", exact=True)).to_be_visible()
    expect(index.get_by_role("link", name="Web Search")).to_contain_text("Needs configuration")
    expect(index).to_contain_text("1 needs attention")
    layout_ui.capture(f"wide-{theme}", ARTIFACTS)


def test_the_index_jumps_to_a_section_and_marks_it_current(layout_ui):
    layout_ui.page.emulate_media(reduced_motion="reduce")
    layout_ui.open(width=1920, height=1080, ready_region="Classification Banner")
    page = layout_ui.page
    scroll_area = page.get_by_test_id("admin-settings-scroll")
    assert scroll_area.evaluate("element => element.scrollTop") == 0
    link = _index(page).get_by_role("link", name="Web Search")
    link.click()

    heading = page.get_by_role("heading", name="Web Search", level=2)
    expect(heading).to_be_focused()
    expect(link).to_have_attribute("aria-current", "location")
    # Reduced motion makes the jump immediate, and the section lands in the upper pane.
    assert scroll_area.evaluate("element => element.scrollTop") > 0
    scroll = _box(scroll_area)
    section = _box(page.get_by_role("region", name="Web Search", exact=True))
    assert scroll["y"] - 1 <= section["y"] < scroll["y"] + scroll["height"] / 2


def test_the_index_steps_aside_when_there_is_no_room(layout_ui):
    layout_ui.open(width=1280, ready_region="Classification Banner")
    expect(_index(layout_ui.page)).to_be_hidden()


@pytest.mark.parametrize("width,expect_split", [(1920, True), (390, False)])
def test_wide_cards_put_each_label_beside_its_control(layout_ui, width, expect_split):
    layout_ui.open(width=width, ready_region="Classification Banner")
    page = layout_ui.page
    label = _box(page.get_by_text("Banner Text", exact=True))
    control = _box(page.get_by_label("Banner Text", exact=True))
    if expect_split:
        assert control["x"] >= label["x"] + label["width"] + 16, "The control belongs right of its label"
        assert abs(control["y"] - label["y"]) < 24, "Label and control should share a row"
    else:
        assert control["y"] > label["y"] + label["height"] - 1, "A narrow card stacks the control below"
        assert abs(control["x"] - label["x"]) < 4


@pytest.mark.parametrize("width,columns", [(1920, 2), (390, 1)])
def test_independent_switches_pair_up_on_wide_cards(layout_ui, width, columns):
    layout_ui.open(width=width, ready_region="Built-in Actions")
    section = layout_ui.page.locator("#core-plugin-toggles")
    # The always-on built-in actions start collapsed.
    section.get_by_role("button", name=re.compile("^Built-in actions")).click()
    grid = section.get_by_test_id("admin-switch-grid").first
    expect(grid).to_be_visible()
    tracks = grid.evaluate("element => getComputedStyle(element).gridTemplateColumns.split(' ').length")
    assert tracks == columns
    cells = grid.locator(":scope > *")
    first, second = _box(cells.nth(0)), _box(cells.nth(1))
    if columns == 2:
        assert abs(first["y"] - second["y"]) < 2 and second["x"] > first["x"]
    else:
        assert second["y"] > first["y"]


def test_the_lead_switch_and_its_settings_read_as_one_cluster(layout_ui):
    layout_ui.open(width=1920, ready_region="Classification Banner")
    banner = layout_ui.page.get_by_role("region", name="Classification Banner", exact=True)
    expect(banner.locator('[data-setting-emphasis="primary"]')).to_contain_text("Enable Classification Banner")
    expect(banner.locator('[data-setting-emphasis="dependent"]')).to_have_count(3)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,font_size", [(390, "m"), (1920, "xl"), (390, "xl")])
def test_cards_never_overflow(layout_ui, theme, width, font_size):
    layout_ui.open(theme=theme, width=width, font_size=font_size, ready_region="Classification Banner")
    page = layout_ui.page
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for region in page.locator(".admin-settings-distinct").all():
        overflow = region.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"A card overflows by {overflow}px at {width}px/{font_size}"
    layout_ui.capture(f"responsive-{theme}-{width}-{font_size}", ARTIFACTS)
