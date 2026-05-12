# test_workspace_active_hero_shortcuts.py
"""
UI test for active workspace hero shortcuts.
Version: 0.241.152
Implemented in: 0.241.125

This test ensures the group and public workspace pages render the active hero
card branding at the top of the page and expose the manage shortcut for the
selected workspace. Updated in 0.241.151 to validate public workspace dropdown
search and implicit public User role display. Updated in 0.241.152 to validate
public workspace search remains visible for smaller public workspace lists.
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


def _is_before(page, first_selector, second_selector):
    return page.evaluate(
        """
        ([firstSelector, secondSelector]) => {
            const first = document.querySelector(firstSelector);
            const second = document.querySelector(secondSelector);
            return Boolean(first && second && (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING));
        }
        """,
        [first_selector, second_selector],
    )


def _selector_row_contains_group_controls(page):
    return page.evaluate(
        """
        () => {
            const row = document.querySelector('#group-selector-row');
            return Boolean(
                row
                && row.querySelector('#group-dropdown')
                && row.querySelector('#user-role-display')
                && row.querySelector('#manage-active-group-btn')
                && row.querySelector('#btn-my-groups')
            );
        }
        """
    )


def _selector_row_contains_public_controls(page):
    return page.evaluate(
        """
        () => {
            const row = document.querySelector('#public-selector-row');
            return Boolean(
                row
                && row.querySelector('#public-dropdown')
                && row.querySelector('#user-public-role-display')
                && row.querySelector('#manage-active-public-btn')
                && row.querySelector('#btn-my-publics')
            );
        }
        """
    )


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
        expect(page.locator("#user-role-display")).to_be_visible()
        expect(page.locator("#user-role-display .group-role-pill")).to_be_visible()
        expect(page.locator("#user-role")).to_have_text("Owner")
        role_summary_text = page.locator("#user-role-display").inner_text()
        assert "Alpha Team" not in role_summary_text, "Expected role summary to avoid repeating the group name."
        expect(page.locator("#active-group-hero-logo")).to_be_visible()
        expect(page.locator("#active-group-hero-initial")).to_be_hidden()
        assert _selector_row_contains_group_controls(page), (
            "Expected the group selector, role summary, manage button, and My Groups button in one row."
        )
        expect(page.locator("#btn-change-group")).to_have_count(0)
        assert _is_before(page, "#active-group-hero", "#group-dropdown"), (
            "Expected the active group hero to render above the group selector."
        )
        assert page.locator("h2", has_text="Group Workspace").count() == 0, (
            "Expected the redundant Group Workspace heading to be removed."
        )

        hero_color = page.locator("#active-group-hero").evaluate(
            "el => el.style.getPropertyValue('--workspace-hero-color').trim()"
        )
        assert hero_color == "#d83b01", f"Expected branded group workspace hero color, saw {hero_color!r}."
        assert page_errors == [], f"Expected no page errors while loading /group_workspaces. Saw: {page_errors}"
    finally:
        context.close()
        browser.close()



@pytest.mark.ui
def test_group_workspace_dropdown_click_sets_active_group(playwright):
    """Validate selecting a group menu item immediately changes the active group."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    active_group_id = "group-alpha"
    set_active_calls = []

    def build_groups_payload():
        return {
            "groups": [
                {
                    "id": "group-alpha",
                    "name": "Alpha Team",
                    "description": "Alpha workspace.",
                    "owner": {"displayName": "Alpha Owner", "email": "alpha@example.com"},
                    "isActive": active_group_id == "group-alpha",
                    "userRole": "Owner",
                    "status": "active",
                    "heroColor": "#d83b01",
                    "hasLogo": False,
                    "logoVersion": 1,
                },
                {
                    "id": "group-beta",
                    "name": "Beta Team",
                    "description": "Beta workspace.",
                    "owner": {"displayName": "Beta Owner", "email": "beta@example.com"},
                    "isActive": active_group_id == "group-beta",
                    "userRole": "Admin",
                    "status": "active",
                    "heroColor": "#0078d4",
                    "hasLogo": False,
                    "logoVersion": 1,
                },
            ]
        }

    def handle_set_active_group(route):
        nonlocal active_group_id
        payload = json.loads(route.request.post_data or "{}")
        active_group_id = payload.get("groupId")
        set_active_calls.append(active_group_id)
        _fulfill_json(route, {"success": True})

    try:
        page.route("**/api/groups?page_size=1000", lambda route: _fulfill_json(route, build_groups_payload()))
        page.route("**/api/groups/setActive", handle_set_active_group)
        page.route(
            "**/api/group_documents?*",
            lambda route: _fulfill_json(route, {"documents": [], "page": 1, "page_size": 10, "total_count": 0}),
        )
        page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/group_workspaces returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."
        expect(page.locator("#active-group-hero-name")).to_have_text("Alpha Team")

        page.locator("#group-dropdown-button").click()
        page.locator("#group-dropdown-items .dropdown-item", has_text="Beta Team").click()

        expect(page.locator("#active-group-hero-name")).to_have_text("Beta Team")
        expect(page.locator("#active-group-hero-owner")).to_have_text("Beta Owner")
        expect(page.locator("#user-role-display .group-role-pill")).to_be_visible()
        expect(page.locator("#user-role")).to_have_text("Admin")
        role_summary_text = page.locator("#user-role-display").inner_text()
        assert "Beta Team" not in role_summary_text, "Expected role summary to avoid repeating the group name."
        expect(page.locator("#manage-active-group-btn")).to_have_attribute("href", "/groups/group-beta")
        expect(page.locator(".selected-group-text")).to_have_text("Beta Team")
        assert set_active_calls == ["group-beta"], (
            f"Expected selecting Beta Team to set it active once. Observed: {set_active_calls}"
        )
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_group_workspace_empty_group_membership_message(playwright):
    """Validate users with no groups see a useful empty-state selector message."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.route("**/api/groups?page_size=1000", lambda route: _fulfill_json(route, {"groups": []}))

        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/group_workspaces returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        expect(page.locator(".selected-group-text")).to_have_text("No groups yet")
        page.locator("#group-dropdown-button").click()
        expect(
            page.get_by_text("You are not a member of any group. Select My Groups to find or create a group.")
        ).to_be_visible()
        expect(page.locator("#user-role-display")).to_be_hidden()
        manage_button_class = page.locator("#manage-active-group-btn").get_attribute("class") or ""
        assert "d-none" in manage_button_class, "Expected Manage Group to stay hidden without an active group."
        expect(page.locator("#btn-my-groups")).to_be_visible()
        expect(page.locator("#btn-change-group")).to_have_count(0)
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
                {
                    "workspaces": [
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
                    ]
                },
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
        expect(page.locator("#user-public-role-display")).to_be_visible()
        expect(page.locator("#user-public-role-display .public-role-pill")).to_be_visible()
        expect(page.locator("#user-public-role")).to_have_text("Owner")
        role_summary_text = page.locator("#user-public-role-display").inner_text()
        assert "Public Hub" not in role_summary_text, "Expected public role summary to avoid repeating the workspace name."
        expect(page.locator("#active-public-hero-logo")).to_be_visible()
        expect(page.locator("#active-public-hero-initial")).to_be_hidden()
        assert _selector_row_contains_public_controls(page), (
            "Expected the public selector, role summary, manage button, and My Workspaces button in one row."
        )
        expect(page.locator("#btn-change-public")).to_have_count(0)
        assert _is_before(page, "#active-public-hero", "#public-dropdown"), (
            "Expected the active public hero to render above the public workspace selector."
        )
        assert page.locator("h2", has_text="Public Workspace").count() == 0, (
            "Expected the redundant Public Workspace heading to be removed."
        )

        hero_color = page.locator("#active-public-hero").evaluate(
            "el => el.style.getPropertyValue('--workspace-hero-color').trim()"
        )
        assert hero_color == "#0099bc", f"Expected branded public workspace hero color, saw {hero_color!r}."
        assert page_errors == [], f"Expected no page errors while loading /public_workspaces. Saw: {page_errors}"
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_public_workspace_dropdown_click_sets_active_workspace(playwright):
    """Validate selecting a public workspace menu item immediately changes the active workspace."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    active_workspace_id = "public-1"
    set_active_calls = []

    def build_public_payload():
        workspaces = [
            {
                "id": "public-1",
                "name": "Public Hub",
                "description": "Primary public workspace.",
                "owner": {"displayName": "Workspace Owner", "email": "owner@example.com"},
                "isActive": active_workspace_id == "public-1",
                "userRole": "Owner",
                "isMember": True,
                "status": "active",
                "heroColor": "#0099bc",
                "hasLogo": False,
                "logoVersion": 1,
            },
            {
                "id": "public-2",
                "name": "Research Library",
                "description": "Secondary public workspace.",
                "owner": {"displayName": "Research Owner", "email": "research@example.com"},
                "isActive": active_workspace_id == "public-2",
                "userRole": "User",
                "isMember": True,
                "status": "active",
                "heroColor": "#107c10",
                "hasLogo": False,
                "logoVersion": 1,
            },
        ]
        return {"workspaces": workspaces}

    def handle_set_active_public(route):
        nonlocal active_workspace_id
        payload = json.loads(route.request.post_data or "{}")
        active_workspace_id = payload.get("workspaceId")
        set_active_calls.append(active_workspace_id)
        _fulfill_json(route, {"success": True})

    try:
        page.route("**/api/public_workspaces?*", lambda route: _fulfill_json(route, build_public_payload()))
        page.route("**/api/public_workspaces/setActive", handle_set_active_public)
        page.route(
            "**/api/public_documents?*",
            lambda route: _fulfill_json(route, {"documents": [], "page": 1, "page_size": 10, "total_count": 0}),
        )
        page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

        response = page.goto(f"{BASE_URL}/public_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /public_workspaces."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/public_workspaces returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /public_workspaces to load successfully, got HTTP {response.status}."
        expect(page.locator("#active-public-hero-name")).to_have_text("Public Hub")

        page.locator("#public-dropdown-button").click()
        expect(page.locator("#public-search-input")).to_be_visible()
        page.locator("#public-search-input").fill("Research")
        expect(page.locator("#public-dropdown-items .dropdown-item", has_text="Public Hub")).to_be_hidden()
        expect(page.locator("#public-dropdown-items .dropdown-item", has_text="Research Library")).to_be_visible()
        page.locator("#public-dropdown-items .dropdown-item", has_text="Research Library").click()

        expect(page.locator("#active-public-hero-name")).to_have_text("Research Library")
        expect(page.locator("#active-public-hero-owner")).to_have_text("Research Owner")
        expect(page.locator("#user-public-role-display .public-role-pill")).to_be_visible()
        expect(page.locator("#user-public-role")).to_have_text("User")
        role_summary_text = page.locator("#user-public-role-display").inner_text()
        assert "Research Library" not in role_summary_text, "Expected public role summary to avoid repeating the workspace name."
        expect(page.locator("#manage-active-public-btn")).to_have_attribute(
            "href", "/public_workspaces/public-2"
        )
        expect(page.locator(".selected-public-text")).to_have_text("Research Library")
        assert set_active_calls == ["public-2"], (
            f"Expected selecting Research Library to set it active once. Observed: {set_active_calls}"
        )
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_public_workspace_empty_availability_message(playwright):
    """Validate users with no public workspaces see a useful empty-state selector message."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.route("**/api/public_workspaces?*", lambda route: _fulfill_json(route, {"workspaces": []}))

        response = page.goto(f"{BASE_URL}/public_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /public_workspaces."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/public_workspaces returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /public_workspaces to load successfully, got HTTP {response.status}."

        expect(page.locator(".selected-public-text")).to_have_text("No workspaces yet")
        page.locator("#public-dropdown-button").click()
        expect(
            page.get_by_text("No public workspaces are available. Select My Workspaces to create one.")
        ).to_be_visible()
        expect(
            page.locator("#public-documents-table").get_by_text(
                "No public workspaces are available. Select My Workspaces to create one."
            )
        ).to_be_visible()
        expect(page.locator("#user-public-role-display")).to_be_hidden()
        manage_button_class = page.locator("#manage-active-public-btn").get_attribute("class") or ""
        assert "d-none" in manage_button_class, "Expected Manage Public Workspace to stay hidden without an active workspace."
        expect(page.locator("#btn-my-publics")).to_be_visible()
        expect(page.locator("#btn-change-public")).to_have_count(0)
    finally:
        context.close()
        browser.close()
