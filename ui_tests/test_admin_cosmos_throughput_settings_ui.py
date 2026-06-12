# test_admin_cosmos_throughput_settings_ui.py
"""
UI test for Admin Settings Cosmos throughput controls.

Version: 0.241.199
Implemented in: 0.241.147

This test ensures the Scale tab exposes Cosmos throughput monitoring and
separate scale-up/scale-down automation controls with min and max guardrails.
It also validates the container-targeted metric clarity, setup guide UI, and
cached status first render. Container policy enforcement coverage was added in
version 0.241.153. Aggregate-only metric warning coverage was added in
version 0.241.154 and clarified in version 0.241.155. Version 0.241.156
keeps coverage aligned with the REST metadata metrics path. Version 0.241.157
adds Metrics Window cadence copy coverage. Version 0.241.159 adds native
Cosmos manual-to-autoscale conversion coverage. Version 0.241.161 adds
grouped scale-up/scale-down policy UI and save-blocking validation coverage.
Version 0.241.162 adds Validate Access setup testing coverage.
Version 0.241.180 adds container table sorting and filtering coverage.
Version 0.241.181 adds container table refresh button coverage.
Version 0.241.183 adds explicit setup guidance and detailed Validate Access diagnostics coverage.
Version 0.241.184 adds neutral informational copy for normal container-targeted throughput mode.
Version 0.241.199 adds SimpleChat's 10,000 RU/s scale support ceiling, monitor-only indicators, and container policy modal filtering coverage.
"""

import re
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"


@pytest.mark.ui
def test_admin_cosmos_throughput_controls_render_from_template():
    """Validate that the Cosmos throughput Scale-tab controls are present and usable."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    required_ids = [
        "cosmos-throughput-section",
        "cosmos_throughput_autoscale_enabled",
        "cosmos_throughput_auto_scale_up_enabled",
        "cosmos_throughput_auto_scale_down_enabled",
        "cosmos_throughput_scale_up_threshold_percent",
        "cosmos_throughput_scale_down_threshold_percent",
        "cosmos_throughput_scale_up_cooldown_minutes",
        "cosmos_throughput_scale_down_cooldown_minutes",
        "cosmos_throughput_min_ru",
        "cosmos_throughput_max_ru",
        "cosmos_throughput_ignore_min_limit",
        "cosmos_throughput_ignore_max_limit",
        "cosmos-throughput-scale-up-policy",
        "cosmos-throughput-scale-down-policy",
        "cosmos-throughput-validation-message",
        "cosmos_throughput_convert_manual_to_autoscale_enabled",
        "cosmos_throughput_enforce_container_defaults",
        "cosmos-throughput-setup-guide-btn",
        "cosmosThroughputSetupModal",
        "cosmos-throughput-run-setup-test-btn",
        "cosmos-throughput-refresh-btn",
        "cosmos-throughput-validate-access-btn",
        "cosmos-throughput-container-policies-btn",
        "cosmos-throughput-convert-autoscale-btn",
        "cosmos-throughput-scale-up-btn",
        "cosmos-throughput-scale-down-btn",
        "cosmos-throughput-container-filter",
        "cosmos-throughput-container-filter-count",
        "cosmos-throughput-container-policy-filter",
        "cosmos-throughput-container-policy-filter-count",
        "cosmos-throughput-refresh-table-btn",
        "cosmos_throughput_container_policies_json",
        "cosmos-throughput-container-policies-body",
        "cosmos-throughput-apply-global-policy-btn",
        "cosmos-throughput-save-container-policies-btn",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert '<th scope="col">Database</th>' not in template
    assert 'Total request units consumed during the selected metrics window' in template
    assert 'Highest normalized RU percentage Azure Monitor reported' in template
    assert 'Automation checks Cosmos throughput on the Metrics Window cadence' in template
    assert 'SimpleChat can scale throughput up or down at 10,000 RU/s or lower' in template
    assert 'Above 10,000 RU/s, SimpleChat monitors utilization only' in template
    assert 'capacity changes, which can take 4 to 6 hours' in template
    assert 'Native Cosmos autoscale conversion is separate from SimpleChat scale-up and scale-down automation' in template
    assert 'SimpleChat-managed scaling stops at 10,000 RU/s' in template
    assert 'Containers above 10,000 RU/s are monitor-only in SimpleChat' in template
    assert 'Filter Container Policies' in template
    assert 'window.cosmosThroughputCachedStatus' in template
    assert "admin_settings.js') }}?v={{ config['VERSION'] }}" in template
    assert 'Enforce global policy for all containers' in template
    assert 'Convert manual throughput to Cosmos autoscale' in template
    assert 'Scale Up Policy' in template
    assert 'Scale Down Policy' in template
    assert 'Validate Access runs the same read checks automation depends on using the current form values' in template
    assert 'Assign roles to the Azure App Service managed identity service principal' in template
    assert 'Object (principal) ID' in template
    assert 'SimpleChat Cosmos Throughput Operator' in template
    assert 'Microsoft.Insights/metrics' in template
    assert 'data-sort-field="container_name"' in template
    assert 'data-sort-field="current_ru"' in template
    assert 'data-sort-field="ru_utilization"' in template
    assert 'data-sort-field="request_units"' in template
    assert 'data-sort-field="policy"' in template
    assert 'Apply Global Policy' in template

    card_match = re.search(
        r'<div class="card p-3 mb-3" id="cosmos-throughput-section"[\s\S]*?</table>\s*</div>\s*</div>',
        template,
    )
    assert card_match, "Expected to find the Cosmos throughput settings card."
    card_html = card_match.group(0)
    assert card_html.index('id="cosmos-throughput-setup-guide-btn"') < card_html.index('id="cosmos-throughput-refresh-btn"')
    card_html = re.sub(r"\{\%[^%]*\%\}", "", card_html)
    card_html = re.sub(r"\{\{[^}]*\}\}", "", card_html)
    modal_match = re.search(
        r'<div class="modal fade" id="cosmosThroughputContainerModal"[\s\S]*?</div>\s*</div>\s*</div>\s*</div>',
        template,
    )
    assert modal_match, "Expected to find the Cosmos throughput container policy modal."
    modal_html = modal_match.group(0)
    modal_html = re.sub(r"\{\%[^%]*\%\}", "", modal_html)
    modal_html = re.sub(r"\{\{[^}]*\}\}", "", modal_html)
    setup_modal_match = re.search(
        r'<div class="modal fade" id="cosmosThroughputSetupModal"[\s\S]*?</div>\s*</div>\s*</div>\s*</div>',
        template,
    )
    assert setup_modal_match, "Expected to find the Cosmos throughput setup guide modal."
    setup_modal_html = setup_modal_match.group(0)
    setup_modal_html = re.sub(r"\{\%[^%]*\%\}", "", setup_modal_html)
    setup_modal_html = re.sub(r"\{\{[^}]*\}\}", "", setup_modal_html)

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    try:
        page.set_content(f"<main>{card_html}{setup_modal_html}{modal_html}</main>")
        section = page.locator("#cosmos-throughput-section")
        expect(section).to_be_visible()
        expect(section.get_by_text("Cosmos DB Throughput")).to_be_visible()
        expect(page.get_by_label("Enable Cosmos throughput automation")).to_be_visible()
        expect(page.get_by_label("Auto scale up")).to_be_visible()
        expect(page.get_by_label("Auto scale down")).to_be_visible()
        expect(page.get_by_text("Scale Up Policy")).to_be_visible()
        expect(page.get_by_text("Scale Down Policy")).to_be_visible()
        expect(page.get_by_label("Scale Up At")).to_be_visible()
        expect(page.get_by_label("Scale Down At")).to_be_visible()
        expect(page.get_by_label("Minimum RU/s")).to_be_visible()
        expect(page.get_by_label("Maximum RU/s")).to_be_visible()
        expect(page.get_by_label("Ignore minimum guardrail")).to_be_visible()
        expect(page.get_by_label("Ignore maximum guardrail")).to_be_visible()
        expect(page.get_by_label("Convert manual throughput to Cosmos autoscale")).to_be_visible()
        expect(page.get_by_label("Enforce global policy for all containers")).to_be_visible()
        expect(page.get_by_role("button", name="Setup Guide")).to_be_visible()
        expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Validate Access")).to_be_visible()
        expect(page.get_by_role("button", name="Containers", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Convert")).to_be_visible()
        expect(page.get_by_role("button", name="Scale Up")).to_be_visible()
        expect(page.get_by_role("button", name="Scale Down")).to_be_visible()
        expect(page.get_by_label("Filter Containers")).to_be_visible()
        expect(page.get_by_role("button", name="Refresh Table")).to_be_visible()
        expect(page.get_by_label("Filter Container Policies")).to_be_attached()
        expect(page.get_by_role("button", name="Sort containers by container name")).to_be_visible()
        expect(page.get_by_role("button", name="Sort containers by current RU/s")).to_be_visible()
        expect(page.get_by_role("button", name="Sort containers by RU utilization")).to_be_visible()
        expect(page.get_by_role("button", name="Sort containers by request units")).to_be_visible()
        expect(page.get_by_role("button", name="Sort containers by policy")).to_be_visible()
        expect(page.locator("#cosmos-throughput-run-setup-test-btn")).to_be_attached()
        expect(page.locator("#cosmos-throughput-apply-global-policy-btn")).to_be_attached()
        expect(page.locator("#cosmosThroughputSetupModal")).to_be_attached()
        expect(page.locator("#cosmosThroughputContainerModal")).to_be_attached()
    finally:
        browser.close()
        playwright_context.stop()


def test_container_metrics_table_uses_clarity_renderer():
    """Container metric rows should stay compact and avoid misleading RU output."""
    source = ADMIN_JS.read_text(encoding="utf-8")

    assert "createIconButton('bi bi-gear'" in source
    assert "configureButton.textContent = 'Configure'" not in source
    assert "setCosmosContainerPolicyFilter(containerName);" in source
    assert "renderCosmosContainerPolicyModal(currentCosmosContainers);" in source
    assert "container.database_name || ''" not in source
    assert "cell.colSpan = 7;" in source
    assert "cell.colSpan = 8;" in source
    assert "getContainerRuUtilization(container)" in source
    assert "formatRequestUnits(container.request_units)" in source
    assert "createCosmosAutoscaleConversionButton" in source
    assert "/api/admin/settings/cosmos-throughput/convert-autoscale" in source


def test_container_metrics_table_supports_sorting_and_filtering():
    """Container metric rows should support client-side sort and container-name filtering."""
    source = ADMIN_JS.read_text(encoding="utf-8")

    assert "currentCosmosContainerSort" in source
    assert "COSMOS_CONTAINER_SORT_FIELDS" in source
    assert "function getFilteredCosmosContainers" in source
    assert "function getSortedCosmosContainers" in source
    assert "function updateCosmosContainerTableControls" in source
    assert "cosmos-throughput-container-filter" in source
    assert "cosmos-throughput-container-filter-count" in source
    assert "function getFilteredCosmosPolicyContainers" in source
    assert "function updateCosmosContainerPolicyFilterControls" in source
    assert "cosmos-throughput-container-policy-filter" in source
    assert "cosmos-throughput-container-policy-filter-count" in source
    assert "No container policies match the current filter." in source
    assert "cosmos-throughput-refresh-table-btn" in source
    assert "No containers match the current filter." in source
    assert "data-sort-field" in ADMIN_TEMPLATE.read_text(encoding="utf-8")


def test_cached_cosmos_status_renders_before_refresh():
    """The page should render the saved Cosmos status without a manual refresh."""
    source = ADMIN_JS.read_text(encoding="utf-8")

    assert "window.cosmosThroughputCachedStatus" in source
    assert "function initializeCosmosThroughputStatusView()" in source
    assert "updateCosmosThroughputStatusPanel(cachedStatus);" in source
    assert "Showing last saved Cosmos throughput status." in source
    assert "No saved Cosmos throughput status is available yet. Loading the first status check now" in source
    assert "Background automation refreshes this saved view on the Metrics Window cadence" in source
    assert "Azure Monitor returned aggregate RU utilization, but not per-container metric dimensions" in source
    assert "Container autoscale waits for per-container utilization before scaling individual containers" in source


def test_container_policy_staging_marks_admin_form_modified():
    """Container policy staging should enable the main Save Settings button."""
    source = ADMIN_JS.read_text(encoding="utf-8")
    write_function_match = re.search(
        r"function writeCosmosContainerPolicies\(policies\) \{[\s\S]*?\n\}",
        source,
    )

    assert write_function_match, "Expected writeCosmosContainerPolicies to exist."
    assert "markFormAsModified();" in write_function_match.group(0)
    assert "formModified = true;" not in write_function_match.group(0)


def test_global_container_policy_enforcement_ui_logic():
    """The frontend should expose global policy enforcement for all containers."""
    source = ADMIN_JS.read_text(encoding="utf-8")

    assert "function isCosmosContainerPolicyEnforced()" in source
    assert "function buildGlobalCosmosContainerPolicy" in source
    assert "global policy enforced" in source
    assert "Apply Global Policy" not in source
    assert "applyGlobalCosmosContainerPolicyToCurrentContainers" in source
    assert "cosmos_throughput_enforce_container_defaults" in source
    assert "convert_manual_to_autoscale_enabled" in source
    assert "cosmos_throughput_convert_manual_to_autoscale_enabled" in source


def test_cosmos_throughput_portal_managed_limit_ui_logic():
    """The frontend should mark high-throughput targets as monitor-only in SimpleChat."""
    source = ADMIN_JS.read_text(encoding="utf-8")
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")

    assert "COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU = 10000" in source
    assert "Throughput above 10,000 RU/s is monitored only in SimpleChat" in source
    assert "capacity changes above this level can take 4 to 6 hours" in source
    assert "function isCosmosThroughputPortalManaged" in source
    assert "function isCosmosScaleUpBlockedBySimpleChatLimit" in source
    assert "function createCosmosPortalManagedBadge" in source
    assert "portal_managed_scaling_required" in source
    assert "Monitor only" in source
    assert "Use Azure portal for capacity changes." in source
    assert "One or more Cosmos throughput targets are above 10,000 RU/s" in source
    assert "max=\"10000\"" in template
    assert "SimpleChat-managed scaling stops at 10,000 RU/s" in template
    assert "plan for a 4 to 6 hour provisioning window" in template


def test_cosmos_throughput_policy_validation_blocks_invalid_saves():
    """The frontend should block invalid Cosmos throughput policy saves."""
    source = ADMIN_JS.read_text(encoding="utf-8")

    assert "function validateCosmosThroughputSettings" in source
    assert "cosmos-throughput-validation-message" in source
    assert "Scale Up At must be higher than Scale Down At" in source
    assert "Scale Up Interval must be greater than or equal to the Metrics Window" in source
    assert "Scale Down Interval must be greater than or equal to the Metrics Window" in source
    assert "e.preventDefault();" in source
    assert "e.stopImmediatePropagation();" in source
    assert "if (event.defaultPrevented)" in source


def test_cosmos_throughput_validate_access_uses_current_form_values():
    """Validate Access should test unsaved Cosmos throughput form values separately from Refresh."""
    source = ADMIN_JS.read_text(encoding="utf-8")

    assert "function buildCosmosThroughputAccessPayload" in source
    assert "function validateCosmosThroughputAccess" in source
    assert "/api/admin/settings/cosmos-throughput/validate-access" in source
    assert "cosmos_throughput_subscription_id: getFieldValue('cosmos_throughput_subscription_id')" in source
    assert "cosmos_throughput_resource_group: getFieldValue('cosmos_throughput_resource_group')" in source
    assert "cosmos_throughput_account_name: getFieldValue('cosmos_throughput_account_name')" in source
    assert "cosmos_throughput_database_name: getFieldValue('cosmos_throughput_database_name')" in source
    assert "document.getElementById('cosmos-throughput-validate-access-btn')" in source
    assert "document.getElementById('cosmos-throughput-run-setup-test-btn')" in source
    assert "function setCosmosThroughputValidationResult" in source
    assert "Passed" in source
    assert "Failed" in source
    assert "Database throughput read access" in (REPO_ROOT / "application" / "single_app" / "functions_cosmos_throughput.py").read_text(encoding="utf-8")
    assert "Cosmos database throughput could not be read." in source
    assert "Container-targeted throughput is active." in source
    assert "Database-level throughput was not found. Container-targeted throughput controls" not in source
