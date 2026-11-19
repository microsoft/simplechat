# test_v2_sidebar_color_mode_cycle.py
"""
Browser regressions for returning to a saved custom color mode from the V2 sidebar.
Version: 0.261.459
Implemented in: 0.261.459

The production Sidebar, ColorModeCard, color runtime and preference stores run with
production CSS. Only HTTP is stubbed. Shared connection fixtures support local or
Azure Playwright. No live user preferences are changed.
"""

from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).resolve().parent / "artifacts" / "sidebar-color-mode"
CUSTOM = {
    "name": "Harbor",
    "base": "dark",
    "colors": {
        "accent": "#2DD4BF",
        "onAccent": "#06201C",
        "backdrop": "#0B1A24",
        "panel": "#12283A",
        "border": "#21415A",
        "text1": "#E6F4F1",
        "text2": "#9CC3C0",
        "ok": "#34D399",
        "warn": "#FBBF24",
        "danger": "#F87171",
        "info": "#22D3EE",
    },
}


class ColorModeApi:
    """Keep the saved settings across reloads while refusing unexpected requests."""

    def __init__(self, assets, settings):
        self.assets = assets
        self.settings = deepcopy(settings)
        self.writes = []
        self.unexpected = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
        elif path == "/favicon.ico":
            route.fulfill(status=204)
        elif path == "/api/user/settings" and request.method == "GET":
            route.fulfill(json={"settings": self.settings})
        elif path == "/api/user/settings" and request.method == "POST":
            update = request.post_data_json["settings"]
            self.writes.append(update)
            self.settings.update(update)
            route.fulfill(json={"message": "User settings updated successfully"})
        else:
            self.unexpected.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected test request."})


@pytest.fixture
def color_page(editor_browser, editor_assets):
    opened = []

    def make(*, custom=CUSTOM, allowed=True, mode="light", collapsed=False, mobile=False, os_dark=False):
        context = editor_browser.new_context(
            viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
            color_scheme="dark" if os_dark else "light",
        )
        page = context.new_page()
        settings = {
            "darkModeEnabled": mode == "dark",
            "v2ColorMode": mode,
            "v2CustomColorMode": custom,
            "v2RailCollapsed": collapsed,
        }
        api = ColorModeApi(editor_assets, settings)
        errors = []
        page.route("**/*", api.handle)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        opened.append((context, api, errors))
        mount(page, api, allowed=allowed)
        if mobile:
            page.get_by_role("button", name="Open navigation", exact=True).click()
        return page, api

    yield make
    for context, api, errors in opened:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not errors, f"Unexpected browser errors: {errors}"


def mount(page, api, *, allowed=True):
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(
        """async (allowed) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                features: {}, settings: {allow_user_custom_color_modes: allowed},
                user: {id: 'color-tester', display_name: 'Color tester'},
                branding: {app_title: 'SimpleChat'},
                catalogs: {models: [], agents: [], prompts: []},
                scope: {groups: [], public_workspaces: []},
                orchestration: {enabled: false, capabilities: []},
            }});
            await H.stores.userSettings.useUserSettingsStore.getState().load();
            H.stores.ui.hydrateUiPreferences(H.stores.userSettings.useUserSettingsStore.getState().settings);
            H.mount('mount-a', 'ColorModeExperience', {}, {initialEntries: ['/settings']});
        }""",
        allowed,
    )
    expect(page.get_by_text("Color mode", exact=True)).to_be_visible()


def next_button(page, mode):
    return page.get_by_role("navigation", name="Primary").get_by_role(
        "button", name=f"Switch to {mode} theme", exact=True,
    )


def choose_next(page, mode, *, keyboard=False):
    button = next_button(page, mode)
    expect(button).to_be_visible()
    if keyboard:
        button.focus()
        button.press("Enter")
    else:
        button.click()
    page.wait_for_function(
        "(mode) => localStorage.getItem('simplechat.v2.color-mode') === mode",
        arg=mode,
    )
    page.evaluate("() => window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().flush()")


@pytest.mark.parametrize("base", ["light", "dark"])
@pytest.mark.parametrize("layout", ["expanded", "collapsed", "mobile"])
def test_sidebar_cycles_back_to_saved_custom_colors(color_page, base, layout):
    custom = {**CUSTOM, "base": base}
    page, api = color_page(custom=custom, collapsed=layout == "collapsed", mobile=layout == "mobile")

    choose_next(page, "dark")
    custom_action = next_button(page, "custom")
    expect(custom_action.locator("svg.lucide-palette")).to_have_count(1)
    if layout == "collapsed":
        expect(custom_action).to_have_attribute("title", "Switch to custom theme")
        expect(custom_action).to_have_text("")
    else:
        expect(custom_action).to_have_text("Custom mode")
    if layout in {"expanded", "mobile"} and base == "dark":
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / f"{layout}-custom.png"))
    if layout != "mobile":
        settings_icon = page.get_by_role("radio", name="Custom", exact=True).locator("svg.lucide-palette")
        expect(settings_icon).to_have_count(1)
        sidebar_paths = custom_action.locator("svg path").evaluate_all(
            "(paths) => paths.map((path) => path.getAttribute('d'))",
        )
        settings_paths = settings_icon.locator("path").evaluate_all(
            "(paths) => paths.map((path) => path.getAttribute('d'))",
        )
        assert sidebar_paths == settings_paths
    choose_next(page, "custom", keyboard=True)
    expect(next_button(page, "light")).to_be_visible()
    expect(page.locator("html")).to_have_class("dark" if base == "dark" else "")
    page.wait_for_function(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() === '#2DD4BF'",
    )
    assert api.settings["v2ColorMode"] == "custom"
    assert api.settings["darkModeEnabled"] == (base == "dark")
    assert api.settings["v2CustomColorMode"] == custom
    choose_next(page, "light")
    page.wait_for_function("() => !document.getElementById('sc-color-scheme')")
    assert api.settings["v2CustomColorMode"] == custom
    choose_next(page, "dark")
    choose_next(page, "custom")
    page.wait_for_function(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() === '#2DD4BF'",
    )
    assert [write["v2ColorMode"] for write in api.writes] == ["dark", "custom", "light", "dark", "custom"]

    mount(page, api)
    if layout == "mobile":
        page.get_by_role("button", name="Open navigation", exact=True).click()
    expect(next_button(page, "light")).to_be_visible()
    page.wait_for_function(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() === '#2DD4BF'",
    )


@pytest.mark.parametrize(
    "custom, allowed, mode",
    [
        (None, True, "light"),
        ({**CUSTOM, "colors": {}}, True, "light"),
        (CUSTOM, False, "light"),
        (CUSTOM, False, "custom"),
    ],
    ids=["not-saved", "invalid-saved-palette", "admin-disabled", "disabled-while-custom"],
)
def test_unavailable_custom_keeps_two_mode_cycle(color_page, custom, allowed, mode):
    page, api = color_page(custom=custom, allowed=allowed, mode=mode)
    choose_next(page, "dark")
    expect(next_button(page, "custom")).to_have_count(0)
    expect(next_button(page, "light").locator("svg.lucide-sun")).to_have_count(1)
    choose_next(page, "light")
    expect(next_button(page, "dark")).to_be_visible()
    assert api.settings["v2CustomColorMode"] == custom
    assert [write["v2ColorMode"] for write in api.writes] == ["dark", "light"]


@pytest.mark.parametrize("os_dark, next_mode", [(False, "dark"), (True, "custom")])
def test_system_mode_enters_cycle_from_resolved_appearance(color_page, os_dark, next_mode):
    page, api = color_page(mode="system", os_dark=os_dark)
    choose_next(page, next_mode)
    assert api.settings["v2ColorMode"] == next_mode
