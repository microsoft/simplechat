# test_v2_admin_agents_visual_hierarchy.py
"""
Browser coverage for the scoped V2 Agents settings presentation.
Version: 0.261.093
Implemented in: 0.261.093

Exercise the built application and real field schema with intercepted APIs. Check
visual hierarchy, contrast, keyboard disclosure, responsiveness, dependency
visibility, and draft/save behavior without modifying live settings.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

# Fixtures stay under ui_tests; the import also registers Azure connect_options.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AGENT_SECTION_IDS, AdminSettingsFixture, connect_options


pytestmark = pytest.mark.ui


@pytest.fixture
def agents_ui(page):
    fixture = AdminSettingsFixture(page)
    yield fixture
    fixture.assert_clean()


def _checkbox(page, label):
    return page.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))


def _set_checkbox(page, label, checked):
    checkbox = _checkbox(page, label)
    if checkbox.is_checked() != checked:
        page.get_by_text(label, exact=True).click()
    expect(checkbox).to_be_checked(checked=checked)


def _catalog_group(page, label):
    return page.get_by_role("region", name="Agents Page", exact=True).get_by_role(
        "button", name=re.compile(f"^{re.escape(label)}")
    )


# Resolve alpha against actual ancestor surfaces. Only used inside the opaque
# catalog groups, so the ambient page gradients cannot invalidate the result.
_CONTRAST = """
(element, property) => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    const rgba = (color) => {
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        const pixel = context.getImageData(0, 0, 1, 1).data;
        return [pixel[0], pixel[1], pixel[2], pixel[3] / 255];
    };
    const over = (top, bottom) => {
        const alpha = top[3] + bottom[3] * (1 - top[3]);
        return [0, 1, 2].map((index) =>
            (top[index] * top[3] + bottom[index] * bottom[3] * (1 - top[3])) / alpha
        ).concat(alpha);
    };
    let background = [0, 0, 0, 0];
    for (let parent = element; parent; parent = parent.parentElement) {
        const color = rgba(getComputedStyle(parent).backgroundColor);
        if (color[3]) {
            background = over(background, color);
        }
        if (background[3] === 1) break;
    }
    if (background[3] !== 1) throw new Error('Contrast requires an opaque ancestor');
    const foreground = over(rgba(getComputedStyle(element)[property]), background);
    const luminance = (color) => color.slice(0, 3).reduce((sum, value, index) => {
        const channel = value / 255;
        const linear = channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
        return sum + linear * [0.2126, 0.7152, 0.0722][index];
    }, 0);
    const light = Math.max(luminance(background), luminance(foreground));
    const dark = Math.min(luminance(background), luminance(foreground));
    return (light + 0.05) / (dark + 0.05);
}
"""


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_agent_sections_have_distinct_headers_and_readable_controls(agents_ui, theme):
    agents_ui.open(theme=theme)
    page = agents_ui.page
    expect(page.locator(".admin-settings-distinct")).to_have_count(4)
    field_size = page.get_by_text("Enable Agents", exact=True).evaluate(
        "element => parseFloat(getComputedStyle(element).fontSize)"
    )
    for section_id in AGENT_SECTION_IDS:
        section = page.locator(f"#{section_id}")
        expect(section).to_have_attribute("role", "region")
        heading = section.get_by_role("heading", level=2)
        assert heading.evaluate("element => parseFloat(getComputedStyle(element).fontSize)") > field_size
        expect(section.locator(":scope > div").first.locator('[aria-hidden="true"] svg')).to_have_count(1)

    other = page.locator("#core-plugin-toggles")
    expect(other).not_to_have_class(re.compile("admin-settings-distinct"))
    assert other.get_by_role("heading", level=2).evaluate(
        "element => parseFloat(getComputedStyle(element).fontSize)"
    ) == field_size

    runtime = page.get_by_role("region", name="Agent Runtime", exact=True)
    expect(runtime.locator('[data-setting-emphasis="primary"]')).to_contain_text("Enable Agents")
    expect(runtime.locator('[data-setting-emphasis="dependent"]')).to_have_count(2)
    expect(runtime.get_by_text("Configured", exact=True)).to_have_count(0)
    agents_ui.capture(f"overview-{theme}")

    _catalog_group(page, "Hero").click()
    title = page.get_by_label("Hero Title", exact=True)
    help_text = page.get_by_text("Headline at the top of the Agents catalog page.", exact=True)
    assert title.evaluate(_CONTRAST, "color") >= 4.5
    assert help_text.evaluate(_CONTRAST, "color") >= 4.5
    assert title.evaluate(_CONTRAST, "borderTopColor") >= 3
    border_before = title.evaluate("element => getComputedStyle(element).borderTopColor")
    title.focus()
    assert title.evaluate("element => getComputedStyle(element).borderTopColor") != border_before
    assert title.evaluate(_CONTRAST, "borderTopColor") >= 3
    agents_ui.capture(f"headers-{theme}")


def test_disclosure_keyboard_and_search_keep_the_current_workflow(agents_ui):
    agents_ui.open()
    page = agents_ui.page
    hero = _catalog_group(page, "Hero")
    guidance = _catalog_group(page, "Guidance")
    promoted = _catalog_group(page, "Promoted agents")
    for group in (hero, guidance, promoted):
        expect(group).to_have_attribute("aria-expanded", "false")
    expect(hero).to_contain_text("settings")

    hero.focus()
    page.keyboard.press("Space")
    expect(hero).to_have_attribute("aria-expanded", "true")
    assert hero.evaluate("element => getComputedStyle(element).outlineStyle") == "solid"
    assert hero.evaluate("element => parseFloat(getComputedStyle(element).outlineWidth)") >= 2
    expect(page.get_by_label("Hero Title", exact=True)).to_be_visible()
    expect(guidance).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("Space")
    expect(hero).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_label("Hero Title", exact=True)).to_have_count(0)

    page.get_by_role("searchbox", name="Search settings").fill("Promoted Tag Label")
    expect(_catalog_group(page, "Promoted agents")).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_label("Promoted Tag Label", exact=True)).to_be_visible()
    page.get_by_role("searchbox", name="Search settings").fill("")
    expect(page.get_by_role("region", name="Agent Runtime", exact=True)).to_be_visible()


def test_permissions_visibility_and_save_discard_remain_schema_driven(agents_ui):
    agents_ui.open()
    page = agents_ui.page
    permissions = page.get_by_role("region", name="Workspace Agent Permissions", exact=True)
    expect(permissions.locator('[aria-hidden="true"] svg.lucide-user-round')).to_have_count(2)
    # Two group field icons and the section header icon.
    expect(permissions.locator('[aria-hidden="true"] svg.lucide-users-round')).to_have_count(3)
    expect(_checkbox(page, "Allow Personal Agents")).to_be_checked()
    expect(_checkbox(page, "Allow Group Agents")).not_to_be_checked()
    expect(page.get_by_text(
        re.compile("This lets model traffic leave the endpoints you administer")
    )).to_be_visible()

    _set_checkbox(page, "Enable Agents", False)
    expect(_checkbox(page, "Workspace Mode")).to_have_count(0)
    expect(page.get_by_role("region", name="Agents Page", exact=True)).to_have_count(0)
    _set_checkbox(page, "Enable Agents", True)
    _set_checkbox(page, "Workspace Mode", False)
    expect(permissions).to_have_count(0)
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(permissions).to_be_visible()
    expect(_checkbox(page, "Workspace Mode")).to_be_checked()
    assert agents_ui.patches == []

    _set_checkbox(page, "Enable Agent Template Gallery", False)
    expect(page.get_by_role("region", name="Agent Template Approvals", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(page.get_by_role("region", name="Agent Template Approvals", exact=True)).to_be_visible()

    _set_checkbox(page, "Allow Group Agents", True)
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert agents_ui.patches == [{"allow_group_agents": True}]
    assert agents_ui.settings["allow_group_agents"] is True
    page.reload(wait_until="networkidle")
    expect(_checkbox(page, "Allow Group Agents")).to_be_checked()


def test_promoted_agent_controls_still_save_the_catalog_entry_and_window(agents_ui):
    agents_ui.settings["agents_page_promoted_popular_agents"] = [agents_ui.catalog_agents[0]]
    agents_ui.open()
    page = agents_ui.page
    _catalog_group(page, "Promoted agents").click()
    page.get_by_role("combobox", name="Agent to promote", exact=True).select_option("global:roadmap")
    page.get_by_role("button", name="Promote", exact=True).click()
    window = page.get_by_role("combobox", name="Popular window for Roadmap Advisor", exact=True)
    expect(window).to_have_value("both")
    window.select_option("30_days")
    remove = page.get_by_role("button", name="Stop promoting Quarterly Research Assistant", exact=True)
    remove.click()
    expect(remove).to_have_count(0)
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert agents_ui.patches == [{
        "agents_page_promoted_popular_agents": [
            {**agents_ui.catalog_agents[1], "window": "30_days"}
        ]
    }]


def test_rejected_save_keeps_the_draft_and_error_visible(agents_ui):
    agents_ui.open()
    page = agents_ui.page
    _catalog_group(page, "Hero").click()
    title = page.get_by_label("Hero Title", exact=True)
    original = title.input_value()
    title.fill("Updated catalog")
    agents_ui.reject_next_save = True
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(title).to_have_value("Updated catalog")
    expect(page.get_by_role("alert").filter(has_text="Fixture validation error.")).to_be_visible()
    assert agents_ui.settings["agents_page_title"] == original
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(title).to_have_value(original)
    # The intercepted 400 is expected; all other console errors remain failures.
    agents_ui.errors = [error for error in agents_ui.errors if "400 (Bad Request)" not in error]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,font_size", [(390, "m"), (1440, "xl"), (390, "xl")])
def test_agent_cards_wrap_at_narrow_widths_and_large_text(agents_ui, theme, width, font_size):
    agents_ui.settings["agents_page_promoted_popular_agents"] = [agents_ui.catalog_agents[0]]
    agents_ui.open(theme=theme, width=width, font_size=font_size)
    page = agents_ui.page
    for label in ("Hero", "Guidance", "Promoted agents"):
        _catalog_group(page, label).click()
    agents_ui.capture(f"responsive-{theme}-{width}-{font_size}")
    for section_id in AGENT_SECTION_IDS:
        section = page.locator(f"#{section_id}")
        overflow = section.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"{section_id} overflows by {overflow}px at {width}px/{font_size}"
