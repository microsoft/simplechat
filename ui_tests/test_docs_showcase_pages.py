# test_docs_showcase_pages.py
"""
UI test for docs showcase pages.
Version: 0.241.009
Implemented in: 0.241.009

This test ensures that the redesigned docs landing pages, reference guides,
how-to guides, tutorials, and troubleshooting pages render the shared
latest-release-style hero and page-specific content blocks at desktop and
mobile viewport sizes.
"""

import os

import pytest
from playwright.sync_api import expect


DOCS_BASE_URL = os.getenv("SIMPLECHAT_DOCS_BASE_URL", "").rstrip("/")

VIEWPORTS = [
    pytest.param({"width": 1440, "height": 960}, id="desktop"),
    pytest.param({"width": 390, "height": 844}, id="mobile"),
]

PAGES = [
    pytest.param("/", "Simple Chat Documentation", ".latest-release-note-panel", id="home"),
    pytest.param("/setup_instructions/", "Getting Started", "nav.page-navigation", id="getting-started"),
    pytest.param("/features/", "Features", ".latest-release-card-image img", id="features"),
    pytest.param("/faqs/", "FAQ", ".latest-release-archive-panel", id="faq"),
    pytest.param("/about/", "About Simple Chat", "h2:has-text('Built as an open repo')", id="about"),
    pytest.param("/admin_configuration/", "Admin Configuration", "img[src*='admin_settings_page.png']", id="admin-config"),
    pytest.param("/application_scaling/", "Application Scaling", "img[src*='scale-cosmos.png']", id="scaling"),
    pytest.param("/application_workflows/", "Application Workflows", "img[src*='workflow-content_safety.png']", id="workflows"),
    pytest.param("/demos/", "Solution Demonstrations", "img[src*='UploadDocumentDemo.gif']", id="demos"),
    pytest.param("/external_apps_overview/", "External Applications Overview", ".latest-release-note-panel", id="external-apps"),
    pytest.param("/setup_instructions_manual/", "Manual Setup", "h2:has-text('Provision Azure Resources')", id="manual-setup"),
    pytest.param("/setup_instructions_special/", "Special Setup Scenarios", "img[src*='architecture-private-endpoints.png']", id="special-setup"),
    pytest.param("/tutorials/", "Tutorials", "a[href$='/tutorials/classifying_documents/']", id="tutorials-index"),
    pytest.param("/tutorials/getting_started/", "Getting Started with Simple Chat", "h2:has-text('Step 1: Deploy Simple Chat')", id="tutorial-getting-started"),
    pytest.param("/tutorials/first_agent/", "Create Your First Agent", "h2:has-text('What Are Agents?')", id="tutorial-first-agent"),
    pytest.param("/tutorials/uploading_documents/", "Uploading and Managing Documents", "h2:has-text('Understanding Workspaces')", id="tutorial-uploading"),
    pytest.param("/tutorials/classifying_documents/", "Document Classification Tutorial", "h2:has-text('What Is Document Classification?')", id="tutorial-classifying"),
    pytest.param("/troubleshooting/", "Troubleshooting", "text=DISABLE_FLASK_INSTRUMENTATION", id="troubleshooting"),
    pytest.param("/reference/admin_configuration/", "Admin Configuration Reference", "h2:has-text('Read the settings in dependency order')", id="reference-admin-config"),
    pytest.param("/reference/api_reference/", "API Reference", "h2:has-text('Documentation endpoints')", id="reference-api"),
    pytest.param("/reference/features/", "Features Reference", "h2:has-text('Feature map by operating area')", id="reference-features"),
    pytest.param("/reference/deploy/", "Deployment Reference", "h2:has-text('Recommended order')", id="reference-deploy"),
    pytest.param("/reference/deploy/azd-cli_deploy/", "Azure Developer CLI Deployment", "h2:has-text('Startup command rule for this path')", id="reference-azd"),
    pytest.param("/reference/deploy/azurecli_powershell_deploy/", "Azure CLI with PowerShell Deployment", "h2:has-text('When to choose this path')", id="reference-azurecli"),
    pytest.param("/reference/deploy/bicep_deploy/", "Bicep Deployment", "h2:has-text('Recommended workflow')", id="reference-bicep"),
    pytest.param("/reference/deploy/manual_deploy/", "Manual Deployment Notes", "h2:has-text('Native Python App Service Startup Command')", id="reference-manual"),
    pytest.param("/reference/deploy/terraform_deploy/", "Terraform Deployment", "h2:has-text('Current behavior')", id="reference-terraform"),
    pytest.param("/how-to/", "How-To Guides", "a[href$='/how-to/agents/ServiceNow/']", id="howto-index"),
    pytest.param("/how-to/add_documents/", "Add Documents", "h2:has-text('Recommended upload flow')", id="howto-add-documents"),
    pytest.param("/how-to/create_agents/", "Create Agents", "h2:has-text('Minimum viable agent setup')", id="howto-create-agents"),
    pytest.param("/how-to/docker_customization/", "Docker Customization", "h2:has-text('Custom Certificate Authorities')", id="howto-docker"),
    pytest.param("/how-to/enterprise_networking/", "Enterprise Networking", "img[src*='architecture-private-endpoints-commercial.png']", id="howto-enterprise-networking"),
    pytest.param("/how-to/scaling_on_azure/", "Scale Simple Chat on Azure", "h2:has-text('When to Scale')", id="howto-scaling"),
    pytest.param("/how-to/upgrade_paths/", "Upgrade Paths", "h2:has-text('Choose the Right Upgrade Path')", id="howto-upgrade-paths"),
    pytest.param("/how-to/use_managed_identity/", "Use Managed Identity", "h2:has-text('What is Managed Identity?')", id="howto-managed-identity"),
    pytest.param("/how-to/azure_speech_managed_identity_manul_setup/", "Azure Speech Managed Identity Setup", "h2:has-text('Authentication Methods')", id="howto-speech-managed-identity"),
    pytest.param("/how-to/agents/ServiceNow/", "ServiceNow Agent Guides", "a[href$='/how-to/agents/ServiceNow/servicenow_oauth_setup/']", id="howto-servicenow-index"),
    pytest.param("/how-to/agents/ServiceNow/servicenow_integration/", "ServiceNow Integration", "h2:has-text('Integration Architecture')", id="howto-servicenow-integration"),
    pytest.param("/how-to/agents/ServiceNow/servicenow_oauth_setup/", "ServiceNow OAuth 2.0 Setup", "h2:has-text('Part 1: Configure OAuth in ServiceNow')", id="howto-servicenow-oauth"),
    pytest.param("/how-to/agents/ServiceNow/two_agent_setup/", "ServiceNow Two-Agent Setup", "h2:has-text('Agent 1: ServiceNow Support Agent')", id="howto-servicenow-two-agent"),
    pytest.param("/how-to/agents/ServiceNow/servicenow_asset_management_setup/", "ServiceNow Asset Management Setup", "h2:has-text('Step 1: Create ServiceNow Actions')", id="howto-servicenow-asset"),
    pytest.param("/explanation/", "Explanation", "h2:has-text('Continue into deeper references')", id="explanation-index"),
    pytest.param("/explanation/architecture/", "Architecture", "h2:has-text('System Overview')", id="explanation-architecture"),
    pytest.param("/explanation/design_principles/", "Design Principles", "h2:has-text('Core Philosophy')", id="explanation-design-principles"),
    pytest.param("/explanation/feature_guidance/", "Feature Guidance", "h2:has-text('Rollout groups')", id="explanation-feature-guidance"),
    pytest.param("/explanation/running_simplechat_locally/", "Running Simple Chat Locally", "h2:has-text('VS Code Python 3.12 Setup')", id="explanation-running-locally"),
    pytest.param("/explanation/running_simplechat_azure_production/", "Running Simple Chat in Azure Production", "h2:has-text('Default Azure Production Model in This Repo')", id="explanation-running-azure"),
]


def _require_docs_base_url():
    if not DOCS_BASE_URL:
        pytest.skip("Set SIMPLECHAT_DOCS_BASE_URL to run this docs UI test.")


@pytest.mark.ui
@pytest.mark.parametrize("viewport", VIEWPORTS)
@pytest.mark.parametrize("path, heading, specific_selector", PAGES)
def test_docs_showcase_pages(playwright, viewport, path, heading, specific_selector):
    """Validate the redesigned docs pages at desktop and mobile breakpoints."""
    _require_docs_base_url()

    browser = playwright.chromium.launch()
    context = browser.new_context(viewport=viewport)

    try:
        page = context.new_page()
        response = page.goto(
            f"{DOCS_BASE_URL}{path}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        assert response is not None, f"Expected a navigation response when loading {path}."
        assert response.ok, f"Expected {path} to load successfully, got HTTP {response.status}."

        expect(page.locator(".latest-release-hero")).to_be_visible()
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        expect(page.locator(".latest-release-hero-actions .btn").first).to_be_visible()
        expect(page.locator(".latest-release-card-grid").first).to_be_visible()
        expect(page.locator(specific_selector).first).to_be_visible()
    finally:
        context.close()
        browser.close()