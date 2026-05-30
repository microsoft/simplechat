# test_admin_governance_tab.py
"""
UI test for admin governance tab rendering and API wiring.

Version: 0.241.025
Implemented in: 0.241.009; 0.241.025

This test ensures the Governance tab is present in admin settings, the
sidebar navigation exposes the same destination, feature policy fetch/save
calls are wired, and delegated item policy calls are sent to governance API
endpoints.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_admin_governance_tab_and_api_wiring():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    playwright_sync_api = pytest.importorskip("playwright.sync_api")

    feature_get_requests = []
    feature_put_requests = []
    item_get_requests = []
    item_review_get_requests = []
    item_put_requests = []
    agent_lookup_requests = []
    action_lookup_requests = []

    feature_payload = {
        "features": [
            {
                "feature_key": "governance_user_agents",
                "allow_all": True,
                "allowed_users": [],
                "allowed_groups": [],
            },
            {
                "feature_key": "governance_global_actions_usage",
                "allow_all": False,
                "allowed_users": ["entra-user-123"],
                "allowed_groups": ["workspace-group-abc"],
            },
        ],
        "feature_keys": [
            "governance_user_agents",
            "governance_global_actions_usage",
        ],
    }

    def fulfill_feature_get(route):
        feature_get_requests.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(feature_payload))

    def fulfill_feature_put(route):
        feature_put_requests.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"policy": {"ok": true}}')

    def fulfill_item_get(route):
        item_get_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "item_policies": [
                    {
                        "entity_type": "global_agent",
                        "item_id": "global-agent-1",
                        "allow_all": False,
                        "allowed_users": ["entra-user-123"],
                        "allowed_groups": ["workspace-group-abc"],
                    }
                ]
            }),
        )

    def fulfill_item_review_get(route):
        item_review_get_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "item_policies": [
                    {
                        "entity_type": "endpoint",
                        "item_id": "endpoint-1",
                        "allow_all": False,
                        "allowed_users": ["entra-user-123"],
                        "allowed_groups": ["workspace-group-abc"],
                    }
                ],
                "pagination": {
                    "page": 1,
                    "per_page": 25,
                    "total_items": 1,
                    "total_pages": 1,
                    "has_prev": False,
                    "has_next": False,
                },
                "search": "",
                "entity_type": None,
            }),
        )

    def fulfill_item_put(route):
        item_put_requests.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"policy": {"ok": true}}')

    def fulfill_admin_agents_lookup(route):
        agent_lookup_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {
                    "id": "global-agent-1",
                    "name": "Global Agent One",
                    "display_name": "Global Agent One",
                },
                {
                    "id": "global-agent-2",
                    "name": "Global Agent Two",
                    "display_name": "Global Agent Two",
                },
            ]),
        )

    def fulfill_admin_plugins_lookup(route):
        action_lookup_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {
                    "id": "global-action-1",
                    "name": "Global Action One",
                    "type": "api",
                }
            ]),
        )

    with playwright_sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1365, "height": 900},
        )
        page = context.new_page()

        try:
            page.route("**/api/admin/governance/policies", fulfill_feature_get)
            page.route("**/api/admin/governance/policies/*", fulfill_feature_put)
            page.route("**/api/admin/governance/item-policies", fulfill_item_get)
            page.route("**/api/admin/governance/item-policies/review**", fulfill_item_review_get)
            page.route("**/api/admin/governance/item-policies/*/*", fulfill_item_put)
            page.route("**/api/admin/agents", fulfill_admin_agents_lookup)
            page.route("**/api/admin/plugins", fulfill_admin_plugins_lookup)

            page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")

            page.get_by_role("link", name="Governance").click()
            page.wait_for_selector("#governance-feature-policies-table")

            page.get_by_role("tab", name="Governance").click()
            page.wait_for_selector("#governance-feature-policies-table")

            page.get_by_role("button", name="Review Configured List").click()
            page.wait_for_selector("#governance-item-policies-review-modal.show")
            page.wait_for_selector("#governance-item-policies-review-body tr")

            page.get_by_role("button", name="Save Feature Policies").click()
            page.wait_for_timeout(300)

            page.locator("#governance-item-id").select_option("global-agent-2")
            page.get_by_role("button", name="Edit List").click()
            page.wait_for_selector("#governanceAllowListEditorModal.show")

            page.locator("#governance-allowlist-csv-target").select_option("users")
            page.locator("#governance-allowlist-csv-mode").select_option("merge")
            page.locator("#governance-allowlist-csv-input").fill("entra-user-123")
            page.get_by_role("button", name="Apply CSV").click()

            page.locator("#governance-allowlist-csv-target").select_option("groups")
            page.locator("#governance-allowlist-csv-input").fill("workspace-group-abc")
            page.get_by_role("button", name="Apply CSV").click()

            page.get_by_role("button", name="Apply to Policy").click()
            page.wait_for_selector("#governanceAllowListEditorModal.show", state="hidden")

            page.get_by_role("button", name="Save Item Policy").click()
            page.wait_for_timeout(300)

            assert feature_get_requests, "Expected governance feature policies GET request"
            assert item_get_requests, "Expected governance item policies GET request"
            assert item_review_get_requests, "Expected governance item policy review GET request"
            assert feature_put_requests, "Expected governance feature policies PUT request"
            assert item_put_requests, "Expected governance item policy PUT request"
            assert agent_lookup_requests, "Expected global agent lookup GET request"
        finally:
            context.close()
            browser.close()
