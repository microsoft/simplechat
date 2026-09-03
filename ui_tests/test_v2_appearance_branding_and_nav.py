# test_v2_appearance_branding_and_nav.py
"""
UI test for V2 Appearance branding, the classification banner, the home page and the
administrator-configured navigation groups.

Version: 0.261.050
Implemented in: 0.261.047

Six Appearance settings had no visible effect in the V2 interface:

  - the custom light and dark logos and the favicon never appeared, because the
    bootstrap payload the branding comes from was fetched once at startup and never
    refreshed, and because the compiled SPA shell hard-coded the shipped favicon;
  - the classification banner did not render for the same stale-payload reason;
  - the landing copy, its alignment and the home page logo size configured a page V2
    did not have;
  - Custom Pages and External Links were absent from the rail entirely.

Extended in 0.261.050, when the brand mark became the rail's home link and the separate
Home nav item was removed: the brand coverage now also states that there is one control
for the destination rather than two, that the link names itself for the collapsed rail,
and that the letter square is not drawn beside the title it stands in for.

Each assertion here is driven by what /api/v2/bootstrap actually reports for the
deployment under test, so the test states the same contract on any tenant rather than
depending on one particular configuration. Sections that a deployment has not turned on
are reported and skipped instead of silently passing.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "") or os.getenv(
    "SIMPLECHAT_UI_ADMIN_STORAGE_STATE",
    "",
)


def _require_environment():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a "
            "valid authenticated Playwright storage state file."
        )


@pytest.fixture
def v2_context(playwright):
    """An authenticated browser context pointed at the V2 interface."""
    _require_environment()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    try:
        yield context
    finally:
        context.close()
        browser.close()


def _open_v2(context, path="/v2"):
    """Load a V2 route and return ``(page, bootstrap_payload)``."""
    page = context.new_page()
    response = page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")

    assert response is not None, f"Expected a navigation response for {path}."
    if response.status in {401, 403}:
        pytest.skip("The configured session is not authorised for the V2 interface.")
    if response.status == 503:
        pytest.skip("The V2 bundle is not built in the environment under test.")
    assert response.ok, f"Expected {path} to load, got HTTP {response.status}."

    bootstrap = page.request.get(f"{BASE_URL}/api/v2/bootstrap")
    assert bootstrap.ok, f"Expected bootstrap to load, got HTTP {bootstrap.status}."

    # The rail only exists once bootstrap has resolved in the browser too.
    expect(page.get_by_role("navigation", name="Primary")).to_be_visible()

    return page, bootstrap.json()


@pytest.mark.ui
def test_rail_shows_the_configured_brand_mark(v2_context):
    """A custom logo must reach the rail, at its own aspect ratio."""
    page, bootstrap = _open_v2(v2_context)
    branding = bootstrap["branding"]
    title = branding.get("app_title") or "SimpleChat"

    rail = page.get_by_role("navigation", name="Primary")
    brand = rail.locator('a[href="/v2"], a[href="/v2/"]')
    logo = rail.locator("img").first

    if not branding.get("hide_app_title"):
        # The letter square is a stand-in for a mark, so in the expanded rail it must not
        # be drawn beside the title it stands in for -- that showed the same word twice.
        # The logo contributes no text, so this holds whether or not one is configured.
        expect(brand).to_have_text(title)

    if not branding.get("show_logo") or not branding.get("logo_url"):
        # The letter avatar is the deliberate V2 fallback, not a missing logo.
        expect(rail.locator("header img, > div img")).to_have_count(0)
        pytest.skip("No custom logo is configured; the letter avatar is expected.")

    expect(logo).to_be_visible()

    box = logo.bounding_box()
    assert box is not None, "The rail logo should have a layout box."
    assert box["height"] <= 40, (
        f"The rail logo should stay within the 32px brand slot, got {box['height']}px."
    )
    # A squashed logo is the symptom of a fixed square box; the rail sizes by height.
    assert box["width"] > box["height"] * 0.5, (
        f"The rail logo looks squashed at {box['width']}x{box['height']}."
    )


@pytest.mark.ui
def test_classification_banner_renders_when_configured(v2_context):
    """The banner spans the full width above the rail, as it does in the classic UI."""
    page, bootstrap = _open_v2(v2_context)
    banner_config = bootstrap["branding"].get("classification_banner")

    banner = page.locator("#classification-banner")

    if not banner_config:
        expect(banner).to_have_count(0)
        pytest.skip("No classification banner is configured.")

    expect(banner).to_be_visible()
    expect(banner).to_have_text(banner_config["text"])
    expect(banner).to_have_attribute("role", "note")

    banner_box = banner.bounding_box()
    rail_box = page.get_by_role("navigation", name="Primary").bounding_box()
    assert banner_box is not None and rail_box is not None
    assert banner_box["y"] < rail_box["y"], (
        "The classification banner should sit above the navigation rail."
    )


@pytest.mark.ui
def test_home_page_renders_landing_content_and_reaches_chat(v2_context):
    """/v2 is the home page, and its call to action opens chat."""
    page, bootstrap = _open_v2(v2_context)
    branding = bootstrap["branding"]

    start = page.get_by_role("link", name="Start chatting")
    expect(start).to_be_visible()

    if branding.get("show_logo") and branding.get("logo_url"):
        # The home page logo is sized by "Main Page Logo Size", which the classic home
        # page applies as a pixel height.
        hero = page.locator("main img").first
        expect(hero).to_be_visible()
        expected = branding["landing_page_logo_scale_percent"]
        box = hero.bounding_box()
        assert box is not None
        assert abs(box["height"] - expected) <= 2, (
            f"The home page logo should be {expected}px tall, got {box['height']}px."
        )

    start.click()
    page.wait_for_url("**/v2/chat")
    expect(page.get_by_role("navigation", name="Primary")).to_be_visible()


@pytest.mark.ui
def test_home_is_reachable_from_the_rail(v2_context):
    """Home has to be navigable, since /v2 is where a deep link now lands."""
    page, bootstrap = _open_v2(v2_context, "/v2/chat")
    title = bootstrap["branding"].get("app_title") or "SimpleChat"

    rail = page.get_by_role("navigation", name="Primary")

    # The brand mark carries the destination; the separate Home nav item that used to sit
    # beneath it is gone, so there must be exactly one control leading to /v2 rather than
    # two stacked on each other. Matching on the href keeps this independent of how the
    # link chooses to name itself.
    home = rail.locator('a[href="/v2"], a[href="/v2/"]')
    expect(home).to_have_count(1)
    expect(home).to_be_visible()

    # Collapsed, the link holds only a logo or a letter, both of which are decorative, so
    # it has to name itself or it reaches a screen reader as an unlabelled link.
    assert (home.get_attribute("aria-label") or "").strip() == f"{title} home", (
        "The brand link should be named for the application and its destination, got "
        f"{home.get_attribute('aria-label')!r}."
    )

    home.click()
    page.wait_for_url(f"{BASE_URL}/v2")
    expect(page.get_by_role("link", name="Start chatting")).to_be_visible()


@pytest.mark.ui
def test_new_chat_is_not_offered_on_the_home_page(v2_context):
    """New chat acts on chat state, so it is only offered where that is on screen."""
    page, _bootstrap = _open_v2(v2_context)

    rail = page.get_by_role("navigation", name="Primary")
    expect(rail.get_by_role("button", name="New chat")).to_have_count(0)

    # Chats is what reaches a fresh chat from here.
    rail.get_by_role("link", name="Chats").click()
    page.wait_for_url("**/v2/chat")
    expect(rail.get_by_role("button", name="New chat")).to_be_visible()


@pytest.mark.ui
def test_navigation_groups_appear_in_the_rail(v2_context):
    """Custom pages and external links are configured centrally and must be shown."""
    page, bootstrap = _open_v2(v2_context)
    navigation = bootstrap["navigation"]

    rail = page.get_by_role("navigation", name="Primary")
    checked = 0

    for group_key in ("custom_pages", "external_links"):
        group = navigation[group_key]
        if not group["enabled"] or not group["items"]:
            continue

        checked += 1
        expect(rail.get_by_text(group["menu_name"], exact=True)).to_be_visible()

        # Three or more entries collapse behind the menu name, matching the classic rail.
        if group["force_menu"] or len(group["items"]) > 2:
            toggle = rail.get_by_role("button", name=group["menu_name"])
            expect(toggle).to_have_attribute("aria-expanded", "true")

        for item in group["items"]:
            entry = rail.get_by_role("link", name=item["label"], exact=True).first
            expect(entry).to_be_visible()

            expected_path = urlparse(item["url"]).path or item["url"]
            assert expected_path in (entry.get_attribute("href") or ""), (
                f"{item['label']} should link to {item['url']}."
            )

            # External destinations leave the application, so they must not replace an
            # in-progress conversation.
            if group_key == "external_links":
                expect(entry).to_have_attribute("target", "_blank")
                assert "noopener" in (entry.get_attribute("rel") or ""), (
                    f"{item['label']} must open with rel=noopener."
                )

    if not checked:
        pytest.skip("Neither Custom Pages nor External Links is configured.")


@pytest.mark.ui
def test_shell_serves_the_configured_favicon(v2_context):
    """The shell is a build artefact, so the server has to rewrite its icon link."""
    page, bootstrap = _open_v2(v2_context)
    expected = bootstrap["branding"]["favicon_url"]

    href = page.locator('link[rel="icon"]').first.get_attribute("href")
    assert href == expected, (
        f"The shell should serve the configured favicon {expected!r}, got {href!r}."
    )

    icon = page.request.get(f"{BASE_URL}{expected}")
    assert icon.ok, f"The favicon at {expected} should be served, got HTTP {icon.status}."
