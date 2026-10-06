# test_v2_admin_settings_rail_collapse.py
"""
Browser coverage for the collapsible V2 Admin Settings categories rail.
Version: 0.261.266
Implemented in: 0.261.266

Exercise the built application with the real field schema and intercepted APIs. Check
that the categories rail collapses to icons that keep their names, hands its width to the
settings, saves the choice under its own preference and restores it on the next visit,
still switches categories while collapsed, works from the keyboard, fits at large text
sizes, and steps aside for the category select on narrow screens -- in light and dark,
without writing to live settings.
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

RAIL_SECTIONS = {
    "appearance": ("classification-banner-section",),
    "agents-actions": ("agents-config",),
    "knowledge": ("web-search-section",),
}
CATEGORIES = ("All settings", "Appearance", "Agents & Actions", "Knowledge")
PREFERENCE_KEY = "v2AdminRailCollapsed"
READY_REGION = "Classification Banner"
ARTIFACTS = "v2_admin_rail"


@pytest.fixture
def rail_ui(page):
    fixture = AdminSettingsFixture(page, sections=RAIL_SECTIONS)
    yield fixture
    fixture.assert_clean()


def _box(locator):
    box = locator.bounding_box()
    assert box, "Element is not rendered"
    return box


def _rail(page):
    return page.get_by_role("complementary", name="Settings categories")


def _category(rail, label):
    return rail.get_by_role("button", name=label, exact=True)


def _saves_rail_preference(response, value=None):
    """A settings save carrying the rail preference, optionally with a specific value."""
    request = response.request
    if request.method != "POST" or not request.url.endswith("/api/user/settings"):
        return False
    saved = (request.post_data_json or {}).get("settings", {})
    return PREFERENCE_KEY in saved and (value is None or saved[PREFERENCE_KEY] is value)


def _click_and_capture_save(page, button):
    """Click, then return the preferences the debounced save sent once it is answered."""
    with page.expect_response(_saves_rail_preference) as save:
        button.click()
    return save.value.request.post_data_json["settings"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_collapsing_gives_the_rail_width_to_the_settings(rail_ui, theme):
    rail_ui.open(theme=theme, width=1440, ready_region=READY_REGION)
    page = rail_ui.page
    rail = _rail(page)
    content = page.get_by_test_id("admin-settings-content")

    collapse = rail.get_by_role("button", name="Collapse settings categories")
    expect(collapse).to_have_attribute("aria-expanded", "true")
    expect(collapse).to_have_attribute("aria-controls", "admin-settings-category-list")
    expect(rail).to_have_css("width", "224px")
    for label in CATEGORIES:
        assert _box(_category(rail, label).locator("span"))["width"] > 1, f"{label} should be readable"
    expanded_content = _box(content)["width"]
    rail_ui.capture(f"expanded-{theme}", ARTIFACTS)

    saved = _click_and_capture_save(page, collapse)
    assert saved[PREFERENCE_KEY] is True
    assert "v2WorkspaceRailCollapsed" not in saved and "v2RailCollapsed" not in saved, (
        "Collapsing the admin rail must not collapse the workspace or shell rails"
    )

    expect(rail.get_by_role("button", name="Expand settings categories")).to_have_attribute(
        "aria-expanded", "false"
    )
    expect(rail).to_have_css("width", "64px")
    assert _box(content)["width"] >= expanded_content + 150, "The settings should take the freed width"

    rail_box = _box(rail)
    for label in CATEGORIES:
        button = _category(rail, label)
        expect(button).to_have_attribute("title", label)
        assert _box(button.locator("span"))["width"] <= 1, f"{label} should only be screen-reader text"
        box = _box(button)
        assert rail_box["x"] <= box["x"] and box["x"] + box["width"] <= rail_box["x"] + rail_box["width"] + 0.5
    expect(_category(rail, "All settings")).to_have_attribute("aria-pressed", "true")
    assert rail.evaluate("element => element.scrollWidth - element.clientWidth") <= 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    rail_ui.capture(f"collapsed-{theme}", ARTIFACTS)


def test_the_choice_is_remembered_and_can_be_undone(rail_ui):
    rail_ui.open(width=1440, ready_region=READY_REGION)
    page = rail_ui.page

    _click_and_capture_save(page, _rail(page).get_by_role("button", name="Collapse settings categories"))
    assert rail_ui.preferences[PREFERENCE_KEY] is True

    page.reload(wait_until="networkidle")
    expect(page.get_by_role("region", name=READY_REGION, exact=True)).to_be_visible()
    expand = _rail(page).get_by_role("button", name="Expand settings categories")
    expect(expand).to_be_visible()
    expect(_rail(page)).to_have_css("width", "64px")

    saved = _click_and_capture_save(page, expand)
    assert saved[PREFERENCE_KEY] is False

    page.reload(wait_until="networkidle")
    expect(page.get_by_role("region", name=READY_REGION, exact=True)).to_be_visible()
    expect(_rail(page).get_by_role("button", name="Collapse settings categories")).to_be_visible()
    expect(_rail(page)).to_have_css("width", "224px")


def test_collapsed_icons_still_switch_categories(rail_ui):
    rail_ui.open(width=1440, ready_region=READY_REGION, preferences={PREFERENCE_KEY: True})
    page = rail_ui.page
    rail = _rail(page)
    expect(rail.get_by_role("button", name="Expand settings categories")).to_be_visible()

    knowledge = _category(rail, "Knowledge")
    knowledge.click()
    expect(knowledge).to_have_attribute("aria-pressed", "true")
    expect(_category(rail, "All settings")).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_role("region", name="Web Search", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name=READY_REGION, exact=True)).to_have_count(0)

    _category(rail, "All settings").click()
    expect(page.get_by_role("region", name=READY_REGION, exact=True)).to_be_visible()
    expect(rail.get_by_role("button", name="Expand settings categories")).to_be_visible()


def test_the_rail_can_be_collapsed_from_the_keyboard(rail_ui):
    rail_ui.open(width=1440, ready_region=READY_REGION)
    page = rail_ui.page
    rail = _rail(page)

    rail.get_by_role("button", name="Collapse settings categories").focus()
    page.keyboard.press("Enter")
    expand = rail.get_by_role("button", name="Expand settings categories")
    expect(expand).to_be_focused()
    expect(rail).to_have_css("width", "64px")

    # Both presses may land in one debounced save, so wait for the one that expands.
    with page.expect_response(lambda response: _saves_rail_preference(response, False)):
        page.keyboard.press("Space")
    expect(rail.get_by_role("button", name="Collapse settings categories")).to_be_focused()
    expect(rail).to_have_css("width", "224px")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_collapsed_rail_fits_at_large_text_sizes(rail_ui, theme):
    rail_ui.open(theme=theme, width=1920, font_size="xl", ready_region=READY_REGION,
                 preferences={PREFERENCE_KEY: True})
    page = rail_ui.page
    rail = _rail(page)
    expect(rail.get_by_role("button", name="Expand settings categories")).to_be_visible()

    rail_box = _box(rail)
    for label in CATEGORIES:
        box = _box(_category(rail, label))
        assert box["x"] + box["width"] <= rail_box["x"] + rail_box["width"] + 0.5, f"{label} spills out"
    assert rail.evaluate("element => element.scrollWidth - element.clientWidth") <= 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    rail_ui.capture(f"collapsed-xl-{theme}", ARTIFACTS)


def test_the_category_select_replaces_the_rail_on_narrow_screens(rail_ui):
    rail_ui.open(width=900, ready_region=READY_REGION, preferences={PREFERENCE_KEY: True})
    page = rail_ui.page

    rail = page.get_by_role("complementary", name="Settings categories", include_hidden=True)
    expect(rail).to_have_count(1)
    expect(rail).to_be_hidden()

    select = page.get_by_role("combobox", name="Settings category", exact=True)
    expect(select).to_be_visible()
    select.select_option(label="Knowledge")
    expect(page.get_by_role("region", name="Web Search", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name=READY_REGION, exact=True)).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
