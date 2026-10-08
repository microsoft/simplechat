# test_v2_settings_workspace_open.py
"""
Production-SPA coverage for opening a workspace from V2 User Settings.
Version: 0.261.296
Implemented in: 0.261.296

The Groups and Public workspaces tabs in User Settings list the workspaces a user can use. Each row
offers Open beside Set active (or the Active badge). Open goes to the workspace's V2 page by its
immutable id and, like the directories' Open, never activates anything from the settings tab: a
group page activates the group it shows, and a public workspace page leaves the active public
workspace alone.

The real built SPA runs against the closed group and public directory fixtures, so a row that
activated before navigating, opened the wrong id, or pushed Open out of the row at a phone width
fails the run.

Run: build application/v2_ui, then python -m pytest .\\ui_tests\\test_v2_settings_workspace_open.py -q
with PLAYWRIGHT_SERVICE_URL='' and PYTHONPATH including ui_tests\\fixtures.
"""

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_workspace import connect_options, group_ui  # noqa: F401
from ui_tests.fixtures.public_directory import (  # noqa: F401
    LONG_WORKSPACE_NAME, MEMBER_WORKSPACE, MEMBER_WORKSPACE_NAME, public_directory_ui,
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

GROUP_SET_ACTIVE = "/api/groups/setActive"
PUBLIC_SET_ACTIVE = "/api/public_workspaces/setActive"


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def search_public(ui, term):
    ui.page.get_by_role("textbox", name="Search public workspaces", exact=True).fill(term)


def requests_to(ui, path):
    return [entry for entry in ui.requests if entry.path == path]


def assert_within(container, element):
    """The element is drawn wholly inside its container, so nothing clips or pushes it out."""
    outer, inner = container.bounding_box(), element.bounding_box()
    assert outer and inner, "Both the row and its Open button must be rendered."
    assert outer["x"] - 0.5 <= inner["x"], "Open starts outside its row."
    assert inner["x"] + inner["width"] <= outer["x"] + outer["width"] + 0.5, (
        "Open is pushed past the edge of its row."
    )


def assert_single_line(locator, what):
    """A short label keeps its one line rather than being squeezed into a column of letters."""
    single = locator.evaluate(
        """element => {
            const style = getComputedStyle(element);
            const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.6;
            return element.getBoundingClientRect().height < 2 * line;
        }"""
    )
    assert single, f"{what} wraps onto more than one line."


def assert_not_truncated(locator, what):
    fits = locator.evaluate("element => element.scrollWidth <= element.clientWidth")
    assert fits, f"{what} is cut short to make room for the row's actions."


# --------------------------------------------------------------------------
# Groups.
# --------------------------------------------------------------------------

def test_open_goes_to_a_group_and_the_group_page_activates_it(group_ui):
    """Open on a group that isn't active lands on its page, which then makes it the active group."""
    ui = group_ui
    ui.active_group = "group-b"
    ui.open("/settings?tab=groups")
    research = row(ui, "Research group")
    expect(research.get_by_role("button", name="Set active", exact=True)).to_be_visible()
    research.get_by_role("button", name="Open Research group", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a")
    expect(ui.page.get_by_text("Research group owner · owner@example.test", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Role: Owner", exact=True)).to_be_visible()
    activations = [entry.body for entry in requests_to(ui, GROUP_SET_ACTIVE)]
    assert activations == [{"groupId": "group-a"}], (
        "Opening a group should activate it exactly once, through the group page."
    )
    assert ui.active_group == "group-a"


def test_open_on_the_active_group_makes_no_activation_request(group_ui):
    """The active row offers Open too, and opening from settings never asks to activate anything."""
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/settings?tab=groups")
    research = row(ui, "Research group")
    expect(research.get_by_text("Active", exact=True)).to_be_visible()
    research.get_by_role("button", name="Open Research group", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a")
    expect(ui.page.get_by_text("Research group owner · owner@example.test", exact=True)).to_be_visible()
    assert not requests_to(ui, GROUP_SET_ACTIVE), "Open must not activate a group from the settings tab."


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_group_rows_fit_open_beside_set_active_and_active(group_ui, theme, width, height):
    """Open sits inside every row, next to the Active badge or Set active, at both widths and themes.

    On a phone the actions wrap below the name, so the name and role badge keep their room instead
    of being squeezed to a few letters.
    """
    ui = group_ui
    ui.active_group = "group-a"
    ui.open("/settings?tab=groups", theme=theme, width=width, height=height)
    active, inactive = row(ui, "Research group"), row(ui, "Read-only group")
    expect(active.get_by_text("Active", exact=True)).to_be_visible()
    expect(inactive.get_by_role("button", name="Set active", exact=True)).to_be_visible()
    for item, name, role in ((active, "Research group", "Owner"), (inactive, "Read-only group", "User")):
        button = item.get_by_role("button", name=f"Open {name}", exact=True)
        expect(button).to_be_visible()
        expect(button).to_be_enabled()
        assert_within(item, button)
        assert_single_line(item.get_by_text(role, exact=True), f"The {role} badge")
        assert_not_truncated(item.get_by_text(name, exact=True), f"The name {name!r}")
    ui.assert_no_overflow()


# --------------------------------------------------------------------------
# Public workspaces.
# --------------------------------------------------------------------------

def test_open_goes_to_a_public_workspace_without_activating_it(public_directory_ui):
    """Open lands on the public workspace page by id and leaves the active public workspace alone."""
    ui = public_directory_ui
    ui.open("/settings?tab=public")
    search_public(ui, MEMBER_WORKSPACE_NAME)
    library = row(ui, MEMBER_WORKSPACE_NAME)
    expect(library.get_by_role("button", name="Set active", exact=True)).to_be_visible()
    library.get_by_role("button", name=f"Open {MEMBER_WORKSPACE_NAME}", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/{MEMBER_WORKSPACE}")
    expect(ui.page.get_by_text("About this workspace", exact=True)).to_be_visible()
    assert not requests_to(ui, PUBLIC_SET_ACTIVE), (
        "Opening a public workspace from settings must not change the active public workspace."
    )
    assert ui.active_workspace is None


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_a_long_public_workspace_name_leaves_room_for_open(public_directory_ui, theme, width, height):
    """An 80-character name truncates rather than pushing Open or Set active out of the row."""
    ui = public_directory_ui
    ui.open("/settings?tab=public", theme=theme, width=width, height=height)
    search_public(ui, "Long content workspace")
    long_row = row(ui, "Long content workspace")
    button = long_row.get_by_role("button", name=f"Open {LONG_WORKSPACE_NAME}", exact=True)
    expect(button).to_be_visible()
    assert_within(long_row, button)
    assert_within(long_row, long_row.get_by_role("button", name="Set active", exact=True))
    ui.assert_no_overflow()
