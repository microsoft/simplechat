# test_v2_admin_file_sync_single_card.py
"""
Browser coverage for the single V2 File Sync card.
Version: 0.261.266
Implemented in: 0.261.266

Exercise the built application with the real File Sync field schema and
intercepted APIs. File Sync used to be five cards. Check that it is now one; that
turning it on reveals the Personal, Group and Public workspace switches nested
beneath it; that each enabled type's Access panel sits directly under its own
switch and opens to that type's rules; that the closed Source types panel reports
how many types are offered; and that the card never overflows on a phone or at a
large text size -- without writing to live settings.
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

SECTIONS = {"knowledge": ("file-sync-section",)}
ARTIFACTS = "v2_admin_file_sync"
WORKSPACE_TYPES = ("Personal workspaces", "Group workspaces", "Public workspaces")
RETIRED_CARDS = (
    "Visible Source Types",
    "Personal Workspace Sync",
    "Group Workspace Sync",
    "Public Workspace Sync",
)


@pytest.fixture
def file_sync_ui(page):
    fixture = AdminSettingsFixture(page, sections=SECTIONS)
    fixture.settings.update({
        "enable_file_sync": True,
        "enable_redis_cache": True,
        "enable_file_sync_personal": True,
        "enable_file_sync_group": True,
        "enable_file_sync_public": False,
        "file_sync_visible_source_types": ["smb", "azure_files", "azure_blob"],
    })
    yield fixture
    fixture.assert_clean()


def _box(locator):
    box = locator.bounding_box()
    assert box, "Element is not rendered"
    return box


def _card(page):
    return page.get_by_role("region", name="File Sync", exact=True)


def _panel(card, anchor):
    """The Access panel drawn beneath the workspace type switch ``anchor``."""
    return card.locator(f'[data-anchored-to="{anchor}"]')


def _checkbox(scope, label):
    return scope.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))


def _set_checkbox(scope, label, checked):
    checkbox = _checkbox(scope, label)
    if checkbox.is_checked() != checked:
        scope.get_by_text(label, exact=True).click()
    expect(checkbox).to_be_checked(checked=checked)


def test_file_sync_is_one_card_with_its_workspace_types_nested(file_sync_ui):
    file_sync_ui.open(width=1440, ready_region="File Sync")
    page = file_sync_ui.page
    card = _card(page)

    # Only File Sync's own cards count: the fixture serves just this section's schema,
    # so the Redis Cache switch it seeds is drawn under "Other capabilities".
    expect(page.locator('.admin-settings-distinct[id^="file-sync"]')).to_have_count(1)
    for retired in RETIRED_CARDS:
        expect(page.get_by_text(retired, exact=True)).to_have_count(0)

    expect(card.locator('[data-setting-emphasis="primary"]')).to_contain_text("Enable File Sync")
    nested = card.locator('[data-setting-emphasis="dependent"]')
    expect(nested).to_have_count(len(WORKSPACE_TYPES))
    for index, label in enumerate(WORKSPACE_TYPES):
        expect(nested.nth(index)).to_contain_text(label)

    # The panels every workspace type shares follow the types, closed.
    for label in ("Run limits", "Source types"):
        panel = card.get_by_role("button", name=re.compile(f"^{label}"))
        expect(panel).to_have_attribute("aria-expanded", "false")
    file_sync_ui.capture("card-desktop", ARTIFACTS)


def test_switching_file_sync_off_folds_the_card_to_its_switch(file_sync_ui):
    file_sync_ui.open(width=1440, ready_region="File Sync")
    card = _card(file_sync_ui.page)

    _set_checkbox(card, "Enable File Sync", False)
    expect(card.locator('[data-setting-emphasis="dependent"]')).to_have_count(0)
    expect(card.locator("[data-anchored-to]")).to_have_count(0)
    for label in ("Run limits", "Source types"):
        expect(card.get_by_role("button", name=re.compile(f"^{label}"))).to_have_count(0)

    _set_checkbox(card, "Enable File Sync", True)
    expect(card.locator('[data-setting-emphasis="dependent"]')).to_have_count(len(WORKSPACE_TYPES))
    expect(card.locator("[data-anchored-to]")).to_have_count(2)


@pytest.mark.parametrize("width,indented", [(1440, True), (390, False)])
def test_each_access_panel_sits_beneath_its_own_switch(file_sync_ui, width, indented):
    file_sync_ui.open(width=width, ready_region="File Sync")
    card = _card(file_sync_ui.page)

    # Public is off, so there are no public rules to show.
    expect(_panel(card, "enable_file_sync_public")).to_have_count(0)

    group_label = _box(card.get_by_text("Group workspaces", exact=True))
    public_label = _box(card.get_by_text("Public workspaces", exact=True))
    panel = _panel(card, "enable_file_sync_group")
    panel_box = _box(panel)
    assert group_label["y"] < panel_box["y"] < public_label["y"], (
        "The Access panel belongs between its own switch and the next workspace type"
    )
    if indented:
        assert abs(panel_box["x"] - group_label["x"]) <= 2, (
            "On a wide card the panel lines up with its switch's label"
        )
    else:
        assert panel_box["x"] < group_label["x"] - 24, (
            "On a narrow card the panel keeps the full row"
        )

    toggle = panel.get_by_role("button", name="Group workspaces: Access")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(toggle).to_contain_text("2 settings")
    toggle.focus()
    file_sync_ui.page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(panel.get_by_text("Only administrators manage sources", exact=True)).to_be_visible()

    _set_checkbox(panel, "Restrict to assigned groups", True)
    expect(panel.get_by_text("Assigned groups", exact=True)).to_be_visible()
    # One type's rules never appear under another.
    expect(_panel(card, "enable_file_sync_personal").get_by_text("Restrict to assigned groups")).to_have_count(0)


def test_the_closed_source_types_panel_reports_its_selection(file_sync_ui):
    file_sync_ui.open(width=1440, ready_region="File Sync")
    card = _card(file_sync_ui.page)
    toggle = card.get_by_role("button", name=re.compile("^Source types"))
    expect(toggle).to_contain_text("3 selected")

    toggle.click()
    expect(card.get_by_label("OneDrive")).to_be_disabled()
    card.get_by_label("Azure Blob Storage").uncheck()
    toggle.click()
    # The header reads the unsaved selection, not the stored one.
    expect(toggle).to_contain_text("2 selected")


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,font_size", [(390, "m"), (390, "xl"), (1920, "xl")])
def test_the_card_never_overflows(file_sync_ui, theme, width, font_size):
    file_sync_ui.settings.update({
        "enable_file_sync_public": True,
        "require_group_assignment_for_file_sync": True,
        "require_public_workspace_assignment_for_file_sync": True,
    })
    file_sync_ui.open(theme=theme, width=width, font_size=font_size, ready_region="File Sync")
    page = file_sync_ui.page
    card = _card(page)

    # Open every panel, so the deepest nesting -- an assignment list inside an Access
    # panel beneath a workspace type -- is measured as well.
    for toggle in card.locator(".admin-field-group > button").all():
        if toggle.get_attribute("aria-expanded") == "false":
            toggle.click()
    expect(card.get_by_text("Assigned public workspaces", exact=True)).to_be_visible()

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    overflow = card.evaluate("element => element.scrollWidth - element.clientWidth")
    assert overflow <= 1, f"The card overflows by {overflow}px at {width}px/{font_size}"
    file_sync_ui.capture(f"responsive-{theme}-{width}-{font_size}", ARTIFACTS)
