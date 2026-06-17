# test_manage_group_page_branding.py
"""
UI test for group manage page branding.
Version: 0.242.057
Implemented in: 0.241.125

This test ensures the manage group page renders the branded hero metadata and
logo without client-side errors when the group branding payload is present.
Updated in 0.241.176 to validate the custom hero color swatch updates the
preview and saved color payload. Updated in 0.242.057 to verify local file
download settings stay hidden until administrators enable group downloads.
"""

import base64
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+JqkAAAAASUVORK5CYII="
)


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_manage_group_page_renders_branding_without_page_errors(playwright):
    """Validate branded hero rendering on the manage group page."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []

    def handle_page_error(error):
        page_errors.append(str(error))

    try:
        page.on("pageerror", handle_page_error)
        page.route(
            "**/api/groups/group-alpha",
            lambda route: _fulfill_json(
                route,
                {
                    "id": "group-alpha",
                    "name": "Brand Ops",
                    "description": "Regression coverage for group hero branding.",
                    "status": "active",
                    "heroColor": "#107c10",
                    "hasLogo": True,
                    "logoVersion": 3,
                    "owner": {
                        "id": "owner-1",
                        "displayName": "Owner User",
                        "email": "owner@example.com",
                    },
                    "admins": [],
                    "documentManagers": [],
                    "userIds": ["owner-1"],
                    "file_downloads_admin_enabled": False,
                },
            ),
        )
        page.route(
            "**/api/groups/group-alpha/members*",
            lambda route: _fulfill_json(route, []),
        )
        page.route(
            "**/api/groups/group-alpha/logo*",
            lambda route: route.fulfill(status=200, content_type="image/png", body=PNG_BYTES),
        )

        response = page.goto(f"{BASE_URL}/groups/group-alpha", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /groups/group-alpha."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/groups/group-alpha returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /groups/group-alpha to load successfully, got HTTP {response.status}."

        expect(page.locator("#groupHeroName")).to_have_text("Brand Ops")
        expect(page.locator("#groupOwnerName")).to_have_text("Owner User")
        expect(page.locator("#groupHeroDescription")).to_have_text(
            "Regression coverage for group hero branding."
        )
        expect(page.locator("#groupLogoImage")).to_be_visible()
        expect(page.locator("#groupInitial")).to_be_hidden()

        hero_color = page.locator("#groupHero").evaluate(
            "el => el.style.getPropertyValue('--hero-color').trim()"
        )
        assert hero_color == "#107c10", f"Expected branded group hero color, saw {hero_color!r}."

        page.locator("#customHeroColor").evaluate(
            """(element) => {
                element.value = '#8844cc';
                element.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        expect(page.locator("#selectedColor")).to_have_value("#8844cc")
        expect(page.locator("#customHeroColor")).to_have_class("custom-color-option selected")

        custom_hero_color = page.locator("#groupHero").evaluate(
            "el => el.style.getPropertyValue('--hero-color').trim()"
        )
        assert custom_hero_color == "#8844cc", (
            f"Expected custom group hero color, saw {custom_hero_color!r}."
        )
        expect(page.locator("#group-file-download-settings-section")).to_have_class(
            re.compile(r"\bd-none\b")
        )
        assert page_errors == [], f"Expected no page errors while loading the manage group page. Saw: {page_errors}"
    finally:
        context.close()
        browser.close()