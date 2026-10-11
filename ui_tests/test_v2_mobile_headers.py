# test_v2_mobile_headers.py
"""
Real-component and production-SPA regressions for single-row V2 mobile headers.
Version: 0.261.325
Implemented in: 0.261.325

Only closed synthetic HTTP is replaced. Test direct actions, permitted directory
controls, tour lifetime, category refresh, status/loading, bounded overflow and
keyboard dismissal with production CSS, including the 767/768 breakpoint.
"""

from pathlib import Path
import sys

import pytest
from playwright.sync_api import expect

from test_v2_sidebar_conversation_scroll import mount
from test_v2_approvals_dashboard import ApprovalsDashboardFixture
from ui_tests.fixtures.workspace_authoring import WorkspaceAuthoringFixture

# Older shared fixtures use top-level imports for their connection helpers.
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

pytest_plugins = (
    "test_v2_sidebar_conversation_scroll",
    "ui_tests.fixtures.group_directory",
    "ui_tests.fixtures.public_directory",
    "ui_tests.fixtures.workspace_authoring",
)

pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).parent / "artifacts" / "single-row-headers"
WIDTHS = (320, 360, 393, 430, 767, 768, 1280)


def assert_single_band(page, width, selector=".page-header"):
    header = page.locator(selector)
    expect(header).to_be_visible()
    geometry = header.evaluate("""element => {
        const box = element.getBoundingClientRect();
        const controls = [...element.querySelectorAll('button')].filter(item => item.getClientRects().length);
        return {
            height: box.height, left: box.left, right: box.right,
            controls: controls.map(item => {
                const rect = item.getBoundingClientRect();
                return {left: rect.left, right: rect.right, height: rect.height, width: rect.width,
                    center: (rect.top + rect.bottom) / 2 - (box.top + box.bottom) / 2};
            }),
            texts: [...element.querySelectorAll('h1, h1 + p')].map(item => ({
                overflow: getComputedStyle(item).textOverflow,
                whiteSpace: getComputedStyle(item).whiteSpace,
                clipped: item.scrollWidth > item.clientWidth,
            })),
        };
    }""")
    assert geometry["right"] <= width + 1
    if width < 768:
        assert geometry["height"] <= 76, geometry
    assert all(geometry["left"] <= control["left"] and control["right"] <= width + 1
               for control in geometry["controls"]), geometry
    assert all(text["overflow"] == "ellipsis" and text["whiteSpace"] == "nowrap"
               for text in geometry["texts"]), geometry
    if width < 768:
        assert all(abs(control["center"]) <= 1 for control in geometry["controls"]), geometry
        assert all(control["height"] >= 44 and control["width"] >= 44
                   for control in geometry["controls"]), geometry
    return geometry


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("theme", ("light", "dark"))
@pytest.mark.parametrize("count", (2, 3))
def test_explicit_actions_stay_on_one_band_with_bounded_overflow(open_page, width, theme, count):
    page, api = open_page({"width": width, "height": 852})
    mount(page, api, experience="HeaderExperience", rows=0, props={"count": count})
    page.evaluate("""theme => {
        document.documentElement.classList.toggle('dark', theme === 'dark');
        document.documentElement.dataset.fontSize = 'xl';
    }""", theme)
    geometry = assert_single_band(page, width)
    if width < 768:
        assert all(text["clipped"] for text in geometry["texts"]), geometry
    first = page.get_by_role("button", name="Action 1", exact=True)
    second = page.get_by_role("button", name="Action 2", exact=True)
    more = page.get_by_role("button", name="More actions", exact=True)
    if width < 768 and count > 2:
        expect(more).to_be_visible()
        expect(second).to_have_count(0)
        height_before = page.locator(".page-header").bounding_box()["height"]
        more.click()
        panel = page.get_by_role("group", name="More actions", exact=True)
        expect(second).to_be_focused()
        bounds = panel.bounding_box()
        assert bounds and bounds["x"] >= 8 and bounds["x"] + bounds["width"] <= width - 8 + 1
        assert bounds["y"] + bounds["height"] <= 852 - 8 + 1
        assert page.locator(".page-header").bounding_box()["height"] == height_before
        page.keyboard.press("ArrowDown")
        expect(page.get_by_role("button", name="Action 3", exact=True)).to_be_focused()
        page.keyboard.press("Escape")
        expect(more).to_be_focused()
        expect(panel).to_have_count(0)
        more.click()
        second.click()
        expect(page.locator(".page-header").get_by_role("status")).to_have_count(0)
        expect(page.get_by_label("Activated action")).to_have_text("Action 2")
        expect(more).to_be_focused()
        more.click()
        page.get_by_role("button", name="Outside control").click()
        expect(panel).to_have_count(0)
        more.click()
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        expect(panel).to_have_count(0)
    else:
        expect(more).to_have_count(0)
        expect(second).to_be_visible()
        label_visible = second.locator(".header-action-label").is_visible()
        assert label_visible == (width >= 768)
        second.click()
        expect(page.get_by_label("Activated action")).to_have_text("Action 2")
    first.click()
    expect(page.get_by_label("Activated action")).to_have_text("Action 1")
    if (width, theme, count) in ((320, "light", 2), (393, "dark", 3), (1280, "light", 3)):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        if width < 768 and count > 2:
            more.click()
        page.screenshot(path=str(ARTIFACTS / f"header-{width}-{theme}-{count}.png"))


def test_loading_status_and_conditional_actions_are_not_overflow_counts(open_page):
    page, api = open_page({"width": 320, "height": 740})
    mount(page, api, experience="HeaderExperience", rows=0,
          props={"count": 3, "secondary": False, "loading": True, "saving": True})
    first = page.get_by_role("button", name="Action 1", exact=True)
    expect(first).to_be_disabled()
    expect(first).to_have_attribute("aria-busy", "true")
    expect(page.locator(".page-header").get_by_role("status")).to_have_text("Saving")
    expect(page.get_by_role("button", name="More actions", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Action 2", exact=True)).to_have_count(0)
    assert_single_band(page, 320)
    page.evaluate("""() => window.OrchHarness.mount('mount-a', 'HeaderExperience',
        {count: 3, loading: true}, {initialEntries: ['/chat']})""")
    page.get_by_role("button", name="More actions", exact=True).click()
    expect(page.get_by_role("button", name="Action 3", exact=True)).to_be_disabled()
    page.keyboard.press("Escape")
    page.evaluate("""() => window.OrchHarness.mount('mount-a', 'HeaderExperience',
        {count: 3, disabled: true}, {initialEntries: ['/chat']})""")
    page.get_by_role("button", name="More actions", exact=True).click()
    panel = page.get_by_role("group", name="More actions", exact=True)
    expect(panel).to_be_focused()
    page.keyboard.press("Escape")
    expect(panel).to_have_count(0)
    page.set_viewport_size({"width": 768, "height": 740})
    expect(page.get_by_role("button", name="More actions", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Action 3", exact=True)).to_be_disabled()


@pytest.mark.parametrize("fixture_name,path,label", [
    ("group_directory_ui", "/groups", "Browse all groups"),
    ("public_directory_ui", "/public", "Public directory"),
])
@pytest.mark.parametrize("width,theme", [(320, "light"), (393, "dark"), (768, "light")])
def test_workspace_directory_actions_are_direct_and_navigate(request, fixture_name, path, label, width, theme):
    ui = request.getfixturevalue(fixture_name)
    ui.open(path, width=width, theme=theme)
    action = ui.page.get_by_role("button", name=label, exact=True)
    expect(action).to_be_visible()
    assert_single_band(ui.page, width)
    expect(ui.page.get_by_role("button", name="More actions", exact=True)).to_have_count(0)
    if width == 393:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        ui.page.screenshot(path=str(ARTIFACTS / f"{fixture_name}-393-{theme}.png"))
    action.click()
    expect(ui.page).to_have_url(f"http://simplechat.test/v2{path}/directory")
    assert_single_band(ui.page, width)


@pytest.mark.parametrize("fixture_name,path,create_label,back_label", [
    ("group_directory_ui", "/groups/directory", "Create group", "Your groups"),
    ("public_directory_ui", "/public/directory", "Create public workspace", "Public Workspaces"),
])
@pytest.mark.parametrize("width", (320, 393, 767, 768, 1280))
@pytest.mark.parametrize("theme", ("light", "dark"))
def test_directory_two_actions_and_permission_gate(request, fixture_name, path, create_label, back_label, width, theme):
    ui = request.getfixturevalue(fixture_name)
    ui.open(path, width=width, theme=theme)
    create = ui.page.get_by_role("button", name=create_label, exact=True)
    expect(create).to_be_visible()
    expect(ui.page.get_by_role("button", name=back_label, exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="More actions", exact=True)).to_have_count(0)
    assert_single_band(ui.page, width)
    create.click()
    expect(ui.page.get_by_role("dialog")).to_be_visible()
    ui.page.keyboard.press("Escape")
    ui.set_hints(can_create=False)
    ui.open(path, width=width, theme=theme)
    expect(create).to_have_count(0)
    assert_single_band(ui.page, width)
    expect(ui.page.get_by_role("button", name="More actions", exact=True)).to_have_count(0)


@pytest.mark.parametrize("width,theme", [(320, "light"), (393, "dark"), (768, "light")])
def test_my_workspace_tour_is_direct_with_one_dialog_host(page, width, theme):
    ui = WorkspaceAuthoringFixture(page)
    try:
        ui.preferences["showTutorialButtons"] = True
        ui.open("/workspace", width=width, theme=theme)
        launcher = page.get_by_role("button", name="Take the workspace tour", exact=True)
        expect(launcher).to_be_visible()
        assert_single_band(page, width)
        expect(page.get_by_role("button", name="More actions", exact=True)).to_have_count(0)
        if width == 393:
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(ARTIFACTS / "workspace-393-dark.png"))
        launcher.click()
        expect(page.get_by_role("dialog")).to_have_count(1)
        page.set_viewport_size({"width": 393 if width >= 768 else 768, "height": 900})
        expect(page.get_by_role("dialog")).to_have_count(1)
        page.keyboard.press("Escape")
        expect(launcher).to_be_focused()
        ui.preferences["showTutorialButtons"] = False
        ui.open("/workspace", width=width, theme=theme)
        expect(launcher).to_have_count(0)
        assert_single_band(page, width)
        ui.preferences["showTutorialButtons"] = True
        ui.preferences["tutorialVisibility"] = {"workspace": False}
        page.evaluate("sessionStorage.setItem('simplechat.v2.pendingTour', 'workspace')")
        ui.open("/workspace", width=width, theme=theme)
        expect(launcher).to_have_count(0)
        expect(page.get_by_role("dialog")).to_have_count(1)
        expect(page.get_by_role("dialog")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
    finally:
        ui.assert_clean()


@pytest.mark.parametrize("width,theme", [(320, "light"), (393, "dark"), (767, "light"), (768, "dark")])
def test_approvals_category_refresh_keeps_header_height_and_handler(page, width, theme):
    ui = ApprovalsDashboardFixture(page, roles=["User", "Admin"])
    ui.open("/v2/approvals/dashboard")
    page.set_viewport_size({"width": width, "height": 852})
    page.evaluate("theme => document.documentElement.classList.toggle('dark', theme === 'dark')", theme)
    refresh = page.get_by_test_id("v2-approvals-refresh")
    expect(refresh).to_have_accessible_name("Refresh")
    assert_single_band(page, width)
    if width == 393:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / "approvals-393-dark.png"))
    before = len(ui.stats_requests)
    with page.expect_request(lambda request: "/api/approvals/stats?" in request.url):
        refresh.click()
    expect(page.get_by_test_id("v2-approvals-dashboard-waiting")).to_contain_text("2")
    assert len(ui.stats_requests) == before + 1
    assert_single_band(page, width)
    ui.assert_clean()
