# test_admin_governance_tab.py
"""
UI test for admin governance tab rendering and API wiring.

Version: 0.261.002
Implemented in: 0.241.009; 0.241.025; 0.242.012; 0.242.013; 0.242.014; 0.242.018; 0.242.019; 0.250.204; 0.250.205; 0.250.206; 0.250.207; 0.250.208; 0.261.002

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
    item_review_get_requests = []
    item_put_requests = []
    user_info_requests = []
    agent_lookup_requests = []
    action_lookup_requests = []

    feature_payload = {
        "features": [
            {
                "feature_key": "governance_user_agents",
                "allow_all": True,
                "allowed_users": [],
                "allowed_groups": [],
                "denied_users": [],
                "denied_groups": ["blocked-high-quota-group"],
            },
            {
                "feature_key": "governance_global_actions_usage",
                "allow_all": False,
                "allowed_users": ["entra-user-123"],
                "allowed_groups": ["workspace-group-abc"],
                "denied_users": ["blocked-user-789"],
                "denied_groups": [],
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
        feature_put_requests.append(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body='{"policy": {"ok": true}}')

    def fulfill_item_review_get(route):
        item_review_get_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "item_policies": [
                    {
                        "entity_type": "global_endpoint",
                        "item_id": "endpoint-1",
                        "policy_id": "policy-1",
                        "policy_name": "Endpoint Pilot Users",
                        "resource_label": "Endpoint One",
                        "allow_all": False,
                        "allowed_users": ["entra-user-123"],
                        "allowed_groups": ["workspace-group-abc"],
                        "denied_users": ["blocked-user-789"],
                        "denied_groups": ["blocked-group-xyz"],
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
        item_put_requests.append({
            "url": route.request.url,
            "method": route.request.method,
            "body": route.request.post_data_json,
        })
        route.fulfill(status=200, content_type="application/json", body='{"policy": {"ok": true}}')

    def fulfill_empty_user_search(route):
        route.fulfill(status=200, content_type="application/json", body="[]")

    def fulfill_user_info(route):
        user_info_requests.append(route.request.url)
        user_id = route.request.url.rstrip("/").rsplit("/", 1)[-1]
        is_known_user = user_id == "entra-user-123"
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "id": user_id,
                "user_id": user_id,
                "displayName": "Paul Lizer" if is_known_user else user_id,
                "display_name": "Paul Lizer" if is_known_user else user_id,
                "email": "paullizer@swiftiesandbox1.onmicrosoft.us" if is_known_user else f"{user_id}@example.invalid",
                "userPrincipalName": "paullizer@swiftiesandbox1.onmicrosoft.us" if is_known_user else f"{user_id}@example.invalid",
            }),
        )

    def fulfill_empty_group_discovery(route):
        route.fulfill(status=200, content_type="application/json", body="[]")

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
            page.route("**/api/admin/governance/item-policies/review**", fulfill_item_review_get)
            page.route("**/api/admin/governance/item-policies", fulfill_item_put)
            page.route("**/api/userSearch**", fulfill_empty_user_search)
            page.route("**/api/user/info/*", fulfill_user_info)
            page.route("**/api/groups/discover**", fulfill_empty_group_discovery)
            page.route("**/api/admin/agents", fulfill_admin_agents_lookup)
            page.route("**/api/admin/plugins", fulfill_admin_plugins_lookup)

            page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")

            page.get_by_role("link", name="Governance").click()
            page.locator("#feature-governance-tab").click()
            page.wait_for_selector("#governance-info-guide-btn")
            page.locator("#governance-policies-tab").click()
            page.wait_for_selector("#governance-feature-policies-table")

            page.locator("#governance-info-guide-btn").click()
            page.wait_for_selector("#governanceInfoModal.show")
            assert "SimpleChat application-level features are governed by identity and app roles" in page.locator("#governanceInfoModal").inner_text()
            assert "Using Workspaces as Governance Cohorts" in page.locator("#governanceInfoModal").inner_text()
            page.locator("#governanceInfoModal .btn-close").click()
            page.wait_for_selector("#governanceInfoModal.show", state="hidden")

            page.wait_for_selector("#governance-item-policies-review-body tr")
            item_policy_header = page.locator("#governance-item-policies-table thead").inner_text()
            assert "Allowed Users" not in item_policy_header
            assert "Allowed Groups" not in item_policy_header
            assert "Blocked Users" not in item_policy_header
            assert "Blocked Groups" not in item_policy_header

            page.locator(".governance-show-item-policy-users-btn").first.click()
            page.wait_for_selector("#governance-item-policy-users-modal.show")
            principal_modal_text = page.locator("#governance-item-policy-users-modal").inner_text()
            assert "Allow Users" in principal_modal_text
            assert "Allow Groups" in principal_modal_text
            assert "Block Users" in principal_modal_text
            assert "Block Groups" in principal_modal_text
            page.get_by_text("Paul Lizer (paullizer@swiftiesandbox1.onmicrosoft.us)").wait_for()
            page.locator("#governance-item-policy-users-modal .btn-close").click()
            page.wait_for_selector("#governance-item-policy-users-modal.show", state="hidden")

            page.locator(".governance-duplicate-item-policy-btn").first.click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show")
            assert page.locator("#governance-item-policy-name").input_value() == "Endpoint Pilot Users (duplicate)"
            assert page.locator("#governance-item-policy-id").input_value() == ""
            assert page.locator("#governance-item-users").input_value() == "entra-user-123"
            assert page.locator("#governance-item-groups").input_value() == "workspace-group-abc"
            assert page.locator("#governance-item-denied-users").input_value() == "blocked-user-789"
            assert page.locator("#governance-item-denied-groups").input_value() == "blocked-group-xyz"
            assert "A new policy ID will be assigned" in page.locator("#governance-item-editor-status").inner_text()
            page.locator("#governance-item-policy-editor-modal .btn-close").click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show", state="hidden")

            page.locator(".governance-inverse-item-policy-btn").first.click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show")
            assert page.locator("#governance-item-policy-name").input_value() == "Endpoint Pilot Users (inverse)"
            assert page.locator("#governance-item-policy-id").input_value() == ""
            assert page.locator("#governance-item-users").input_value() == "blocked-user-789"
            assert page.locator("#governance-item-groups").input_value() == "blocked-group-xyz"
            assert page.locator("#governance-item-denied-users").input_value() == "entra-user-123"
            assert page.locator("#governance-item-denied-groups").input_value() == "workspace-group-abc"
            assert not page.locator("#governance-item-allow-all").is_checked()
            assert "Allowed and blocked users/groups were swapped" in page.locator("#governance-item-editor-status").inner_text()
            page.locator("#governance-item-policy-editor-modal .btn-close").click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show", state="hidden")

            page.get_by_role("button", name="Save Feature Policies").click()
            page.wait_for_timeout(300)

            page.locator(".governance-edit-item-policy-btn").first.click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show")
            assert not page.locator("#governance-item-entity-type").is_disabled(), (
                "Existing item policy edits should allow intentional retargeting"
            )
            assert not page.locator("#governance-item-id").is_disabled(), (
                "Existing item policy edits should allow selecting a new delegated item"
            )
            assert "Changing the target will move this policy" in page.locator("#governance-item-id-status").inner_text()
            page.locator("#governance-item-entity-type").select_option("global_agent")
            page.wait_for_selector("#governance-item-id option[value='global-agent-2']")
            page.locator("#governance-item-id").select_option("global-agent-2")
            page.get_by_role("button", name="Save Item Policy").click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show", state="hidden")
            page.wait_for_timeout(300)

            page.get_by_role("button", name="New Policy").click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show")
            page.wait_for_selector("#governance-item-id option[value='global-agent-2']")
            page.locator("#governance-item-id").select_option("global-agent-2")
            page.locator("#governance-item-allow-all").uncheck()

            page.locator("#governance-item-csv-target").select_option("users")
            page.locator("#governance-item-csv-mode").select_option("merge")
            page.locator("#governance-item-csv-input").fill("entra-user-123")
            page.locator("#governance-item-csv-apply-btn").click()
            page.locator("#governance-item-selected-user-search").fill("entra-user")
            assert "entra-user-123" in page.locator("#governance-item-selected-users").inner_text()

            page.locator("#governance-item-csv-target").select_option("groups")
            page.locator("#governance-item-csv-input").fill("workspace-group-abc")
            page.locator("#governance-item-csv-apply-btn").click()
            page.locator("#governance-item-selected-group-search").fill("workspace-group")
            assert "workspace-group-abc" in page.locator("#governance-item-selected-groups").inner_text()

            page.locator("#governance-item-edit-blocklist-btn").click()
            page.wait_for_selector("#governanceAllowListEditorModal.show")
            page.wait_for_selector("#governance-item-policy-editor-modal.show", state="hidden")
            page.locator("#governance-allowlist-csv-target").select_option("groups")
            page.locator("#governance-allowlist-csv-mode").select_option("merge")
            page.locator("#governance-allowlist-csv-input").fill("blocked-group-xyz")
            page.locator("#governance-allowlist-csv-apply-btn").click()
            page.get_by_role("button", name="Apply to Policy").click()
            page.wait_for_selector("#governanceAllowListEditorModal.show", state="hidden")
            page.wait_for_selector("#governance-item-policy-editor-modal.show")
            assert "1 group blocked" in page.locator("#governance-item-blocklist-summary").input_value()

            page.get_by_role("button", name="Save Item Policy").click()
            page.wait_for_selector("#governance-item-policy-editor-modal.show", state="hidden")
            page.wait_for_timeout(300)

            assert feature_get_requests, "Expected governance feature policies GET request"
            assert item_review_get_requests, "Expected governance item policy review GET request"
            assert user_info_requests, "Expected selected user hydration through user info fallback"
            assert feature_put_requests, "Expected governance feature policies PUT request"
            assert item_put_requests, "Expected governance item policy PUT request"
            assert agent_lookup_requests, "Expected global agent lookup GET request"
            assert any("denied_groups" in request for request in feature_put_requests), (
                "Expected feature policy save payloads to include denied groups"
            )
            edited_policy_request = next(
                request for request in item_put_requests
                if request["body"].get("policy_id") == "policy-1"
            )
            assert edited_policy_request["body"].get("original_entity_type") == "global_endpoint", (
                "Expected existing policy edits to retain the original entity type"
            )
            assert edited_policy_request["body"].get("original_item_id") == "endpoint-1", (
                "Expected existing policy edits to retain the original item target"
            )
            assert edited_policy_request["body"].get("entity_type") == "global_agent", (
                "Expected existing policy edits to allow intentional entity retargeting"
            )
            assert edited_policy_request["body"].get("item_id") == "global-agent-2", (
                "Expected existing policy edits to send the selected retarget item"
            )
            assert item_put_requests[-1]["body"].get("denied_groups") == ["blocked-group-xyz"], (
                "Expected item policy save payload to include block-list groups"
            )
        finally:
            context.close()
            browser.close()
