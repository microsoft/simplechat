# test_workspace_active_hero_shortcuts.py
"""
UI test for active workspace hero shortcuts.
Version: 0.241.125
Implemented in: 0.241.125

This test ensures the group and public workspace pages render the active hero
card branding and expose the manage shortcut for the selected workspace.
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
def test_group_workspace_active_hero_and_manage_link(playwright):
    """Validate the active group hero card and manage shortcut."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []

    try:
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route(
            "**/api/groups?page_size=1000",
            lambda route: _fulfill_json(
                route,
                {
                    "groups": [
                        {
                            "id": "group-alpha",
                            "name": "Alpha Team",
                            "description": "Hero regression coverage for groups.",
                            "owner": {
                                "displayName": "Group Owner",
                                "email": "owner@example.com",
                            },
                            "isActive": True,
                            "userRole": "Owner",
                            "status": "active",
                            "heroColor": "#d83b01",
                            "hasLogo": True,
                            "logoVersion": 5,
                        }
                    ]
                },
            ),
        )
        page.route(
            "**/api/group_documents?*",
            lambda route: _fulfill_json(
                route,
                {
                    "documents": [],
                    "page": 1,
                    "page_size": 10,
                    "total_count": 0,
                },
            ),
        )
        page.route(
            "**/api/group_documents/tags?*",
            lambda route: _fulfill_json(route, {"tags": []}),
        )
        page.route(
            "**/api/groups/group-alpha/logo*",
            lambda route: route.fulfill(status=200, content_type="image/png", body=PNG_BYTES),
        )

        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/group_workspaces returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        expect(page.locator("#active-group-hero")).to_be_visible()
        expect(page.locator("#active-group-hero-name")).to_have_text("Alpha Team")
        expect(page.locator("#active-group-hero-owner")).to_have_text("Group Owner")
        expect(page.locator("#active-group-hero-description")).to_have_text(
            "Hero regression coverage for groups."
        )
        expect(page.locator("#manage-active-group-btn")).to_have_attribute("href", "/groups/group-alpha")
        expect(page.locator("#active-group-hero-logo")).to_be_visible()
        expect(page.locator("#active-group-hero-initial")).to_be_hidden()

        hero_color = page.locator("#active-group-hero").evaluate(
            "el => el.style.getPropertyValue('--workspace-hero-color').trim()"
        )
        assert hero_color == "#d83b01", f"Expected branded group workspace hero color, saw {hero_color!r}."
        assert page_errors == [], f"Expected no page errors while loading /group_workspaces. Saw: {page_errors}"
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_public_workspace_active_hero_and_manage_link(playwright):
    """Validate the active public workspace hero card and manage shortcut."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []

    try:
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route(
            "**/api/public_workspaces?*",
            lambda route: _fulfill_json(
                route,
                [
                    {
                        "id": "public-1",
                        "name": "Public Hub",
                        "description": "Hero regression coverage for public workspaces.",
                        "owner": {
                            "displayName": "Workspace Owner",
                            "email": "owner@example.com",
                        },
                        "isActive": True,
                        "userRole": "Owner",
                        "isMember": True,
                        "status": "active",
                        "heroColor": "#0099bc",
                        "hasLogo": True,
                        "logoVersion": 8,
                    }
                ],
            ),
        )
        page.route(
            "**/api/public_workspaces/public-1",
            lambda route: _fulfill_json(
                route,
                {
                    "id": "public-1",
                    "name": "Public Hub",
                    "description": "Hero regression coverage for public workspaces.",
                    "owner": {
                        "displayName": "Workspace Owner",
                        "email": "owner@example.com",
                    },
                    "status": "active",
                    "heroColor": "#0099bc",
                    "hasLogo": True,
                    "logoVersion": 8,
                    "userRole": "Owner",
                    "isMember": True,
                },
            ),
        )
        page.route(
            "**/api/public_documents?*",
            lambda route: _fulfill_json(
                route,
                {
                    "documents": [],
                    "page": 1,
                    "page_size": 10,
                    "total_count": 0,
                },
            ),
        )
        page.route(
            "**/api/public_workspace_documents/tags?*",
            lambda route: _fulfill_json(route, {"tags": []}),
        )
        page.route(
            "**/api/public_workspaces/public-1/logo*",
            lambda route: route.fulfill(status=200, content_type="image/png", body=PNG_BYTES),
        )

        response = page.goto(f"{BASE_URL}/public_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /public_workspaces."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/public_workspaces returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /public_workspaces to load successfully, got HTTP {response.status}."

        expect(page.locator("#active-public-hero")).to_be_visible()
        expect(page.locator("#active-public-hero-name")).to_have_text("Public Hub")
        expect(page.locator("#active-public-hero-owner")).to_have_text("Workspace Owner")
        expect(page.locator("#active-public-hero-description")).to_have_text(
            "Hero regression coverage for public workspaces."
        )
        expect(page.locator("#manage-active-public-btn")).to_have_attribute(
            "href", "/public_workspaces/public-1"
        )
        expect(page.locator("#active-public-hero-logo")).to_be_visible()
        expect(page.locator("#active-public-hero-initial")).to_be_hidden()

        hero_color = page.locator("#active-public-hero").evaluate(
            "el => el.style.getPropertyValue('--workspace-hero-color').trim()"
        )
        assert hero_color == "#0099bc", f"Expected branded public workspace hero color, saw {hero_color!r}."
        assert page_errors == [], f"Expected no page errors while loading /public_workspaces. Saw: {page_errors}"
    finally:
        context.close()
        browser.close()