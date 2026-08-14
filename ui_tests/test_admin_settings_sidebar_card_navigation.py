# test_admin_settings_sidebar_card_navigation.py
"""
UI tests for Admin Settings sidebar card navigation.
Version: 0.250.192
Implemented in: 0.250.192

These tests ensure newly linked configuration cards are searchable and open
the matching tab and section from the Admin Settings left sidebar.
"""

import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = (
    REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
)
SIDEBAR_TEMPLATE = (
    REPO_ROOT / "application" / "single_app" / "templates" / "_sidebar_nav.html"
)
SIDEBAR_SCRIPT = (
    REPO_ROOT
    / "application"
    / "single_app"
    / "static"
    / "js"
    / "admin"
    / "admin_sidebar_nav.js"
)
BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = (
    os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
    or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
)
EXPECTED_DESTINATIONS = [
    (
        "Document Action Capabilities",
        "agents",
        "document-action-capabilities-card",
    ),
    (
        "Agent Template Approvals",
        "agents",
        "agent-template-approvals-section",
    ),
    (
        "Governance Feature Toggles",
        "governance",
        "governance-feature-toggles-section",
    ),
    (
        "MCP Action Destination Governance",
        "governance",
        "governance-mcp-destination-section",
    ),
    (
        "Inbound MCP Source Governance",
        "governance",
        "governance-inbound-mcp-section",
    ),
    (
        "Feature Policies",
        "governance",
        "governance-feature-policies-section",
    ),
    (
        "Delegated Item Policies",
        "governance",
        "governance-item-policies-section",
    ),
    ("Chat AI Notice", "general", "ai-notice-section"),
    ("Terms of Use", "general", "terms-of-use-section"),
    ("Model Endpoints", "ai-models", "multi-endpoint-configuration"),
    (
        "Automatic Data Refresh",
        "control-center-config",
        "control-center-auto-refresh-section",
    ),
    (
        "Control Center Access",
        "control-center-config",
        "control-center-overview-section",
    ),
    ("Conversation Cache", "scale", "conversation-cache-section"),
    ("File Downloads", "workspaces", "file-download-settings-section"),
    ("Chat File Uploads", "workspaces", "chat-file-uploads-section"),
    (
        "Multi-Modal Vision Analysis",
        "workspaces",
        "multimodal-vision-section",
    ),
    ("Workspace Scope Lock", "workspaces", "workspace-scope-lock-section"),
    (
        "Desktop Conversation Notifications",
        "safety",
        "desktop-notifications-section",
    ),
    ("URL Access", "search-extract", "url-access-section"),
    ("Deep Research", "search-extract", "source-review-section"),
    ("Chunk Sizes", "search-extract", "chunk-size-section"),
    (
        "AI Video Intelligence",
        "search-extract",
        "video-intelligence-section",
    ),
    (
        "AI Voice Conversations",
        "search-extract",
        "ai-voice-chat-section",
    ),
]


def _require_ui_environment():
    """Skip authenticated browser coverage unless its environment is ready."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or "
            "SIMPLECHAT_UI_STORAGE_STATE to a valid admin storage state file."
        )


@pytest.mark.ui
def test_admin_sidebar_exposes_every_new_card_destination():
    """Validate the versioned HTML and JavaScript navigation contract."""
    admin_source = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    sidebar_source = SIDEBAR_TEMPLATE.read_text(encoding="utf-8")
    script_source = SIDEBAR_SCRIPT.read_text(encoding="utf-8")

    for label, tab_id, section_id in EXPECTED_DESTINATIONS:
        assert f'id="{section_id}"' in admin_source
        assert (
            f'data-tab="{tab_id}" data-section="{section_id}"'
            in sidebar_source
        )
        assert f'<span class="nav-text">{label}</span>' in sidebar_source
        assert f"'{section_id}': '{section_id}'" in script_source

    assert 'data-section="multimedia-support-section"' not in sidebar_source
    assert "noResultsDiv.innerHTML" not in script_source
    assert "message.textContent" in script_source


@pytest.mark.ui
def test_admin_sidebar_search_opens_every_new_card_destination():
    """Search for and open each new destination in an authenticated browser."""
    _require_ui_environment()

    # Keep Playwright optional so the source-contract test runs without UI deps.
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(storage_state=ADMIN_STORAGE_STATE)
        page = context.new_page()
        response = page.goto(
            f"{BASE_URL}/admin/settings",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok

        page.locator("#admin-search-btn").click()
        search_input = page.locator("#admin-search-input")
        expect(search_input).to_be_visible()

        for label, tab_id, section_id in EXPECTED_DESTINATIONS:
            search_input.fill(label)
            link = page.locator(
                ".admin-nav-section"
                f'[data-tab="{tab_id}"]'
                f'[data-section="{section_id}"]'
            )
            target = page.locator(f"#{section_id}")

            if section_id == "agent-template-approvals-section":
                if link.count() == 0:
                    expect(target).to_have_count(0)
                    continue

            expect(link).to_be_visible()
            expect(link.locator(".nav-text")).to_have_text(label)
            link.click()
            expect(target).to_be_visible()
            expect(target).to_be_in_viewport()

        search_input.fill("sidebar-card-parity-no-result")
        expect(page.locator("#admin-search-no-results")).to_have_text(
            'No settings found for "sidebar-card-parity-no-result"'
        )

        context.close()
        browser.close()
