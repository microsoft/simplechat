# test_agent_modal_assigned_knowledge_step.py
"""
UI test for the Assigned Knowledge step in the agent modal.
Version: 0.241.119
Implemented in: 0.241.068

This test ensures the agent wizard renders searchable Assigned Knowledge pickers,
shows active documents, and persists selected knowledge, assigned URL sources,
and user-context policy values into additional settings.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_agent_modal_assigned_knowledge_step():
    """Validate the Assigned Knowledge wizard step and settings serialization."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        page.route("**/api/user/plugins", lambda route: _fulfill_json(route, []))
        page.route(
            "**/api/agents/assigned-knowledge/catalog?*",
            lambda route: _fulfill_json(
                route,
                {
                    "success": True,
                    "agent_scope": "personal",
                    "sources": [
                        {
                            "scope": "personal",
                            "id": "personal",
                            "label": "Personal workspace",
                        },
                        {
                            "scope": "public",
                            "id": "public-1",
                            "label": "Public One",
                        },
                    ],
                    "documents": [
                        {
                            "id": "public-doc",
                            "title": "Public Guide",
                            "file_name": "Public Guide.pdf",
                            "scope": "public",
                            "source_id": "public-1",
                            "source_name": "Public One",
                            "tags": ["Finance", "Operations"],
                        },
                        {
                            "id": "finance-doc",
                            "title": "Finance Checklist",
                            "file_name": "Finance Checklist.pdf",
                            "scope": "public",
                            "source_id": "public-1",
                            "source_name": "Public One",
                            "tags": ["Finance"],
                        }
                    ],
                    "tags": [
                        {"name": "Finance", "count": 2},
                        {"name": "Operations", "count": 1},
                    ],
                },
            ),
        )

        try:
            page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            expect(page.locator("#agentModal")).to_be_attached()
            modal_dialog_class = page.locator("#agentModal .modal-dialog").get_attribute("class") or ""
            assert "modal-xl" in modal_dialog_class
            assert "agent-modal-dialog" in modal_dialog_class
            page.wait_for_function("() => window.agentModalStepper && typeof window.agentModalStepper.showModal === 'function'")

            page.evaluate(
                """
                async () => {
                    await window.agentModalStepper.showModal();
                    window.agentModalStepper.goToStep(5);
                }
                """
            )

            knowledge_toggle = page.locator("#agent-assigned-knowledge-enabled")
            expect(knowledge_toggle).to_be_visible()
            knowledge_toggle.check()

            expect(page.locator("#agent-assigned-knowledge-controls")).to_be_visible()
            page.locator("#agent-assigned-knowledge-user-context-enabled").check()
            expect(page.locator("#agent-assigned-knowledge-user-action-controls")).to_be_visible()
            page.locator("#agent-assigned-knowledge-user-action-compare").uncheck()
            page.locator("#agent-assigned-knowledge-web-source-input").fill("https://example.com/guide#section")
            page.select_option("#agent-assigned-knowledge-web-source-mode", value="deep_research")
            page.locator("#agent-assigned-knowledge-web-source-add").click()
            expect(page.locator("#agent-assigned-knowledge-web-source-list")).to_contain_text("https://example.com/guide")
            expect(page.locator("#agent-assigned-knowledge-web-source-list")).to_contain_text("Deep Research")
            expect(page.locator("#agent-assigned-knowledge-sources")).to_contain_text("Public One")
            expect(page.locator("#agent-assigned-knowledge-tags")).to_contain_text("Finance")

            page.locator(
                "#agent-assigned-knowledge-source-available "
                ".agent-assigned-knowledge-transfer-item[data-assigned-knowledge-key='public:public-1'] button"
            ).click()
            expect(page.locator("#agent-assigned-knowledge-source-selected")).to_contain_text("Public One")
            expect(page.locator("#agent-assigned-knowledge-document-available")).to_contain_text("Public Guide")
            expect(page.locator("#agent-assigned-knowledge-document-available")).to_contain_text("Finance Checklist")
            expect(page.locator("#agent-assigned-knowledge-resolved-count")).to_contain_text("2 active documents")
            expect(page.locator("#agent-assigned-knowledge-active-summary")).to_contain_text("Using all 2 active documents")

            page.locator(
                "#agent-assigned-knowledge-tag-available "
                ".agent-assigned-knowledge-transfer-item[data-assigned-knowledge-key='Finance'] button"
            ).click()
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("Public Guide")
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("Finance Checklist")

            page.locator(
                "#agent-assigned-knowledge-tag-available "
                ".agent-assigned-knowledge-transfer-item[data-assigned-knowledge-key='Operations'] button"
            ).click()
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("Public Guide")
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).not_to_contain_text("Finance Checklist")
            expect(page.locator("#agent-assigned-knowledge-active-summary")).to_contain_text("documents matching all 2 selected tag limits")

            page.locator(
                "#agent-assigned-knowledge-document-available "
                ".agent-assigned-knowledge-transfer-item[data-assigned-knowledge-key='finance-doc'] button"
            ).click()

            expect(page.locator("#agent-assigned-knowledge-tag-selected")).to_contain_text("Finance")
            expect(page.locator("#agent-assigned-knowledge-tag-selected")).to_contain_text("Operations")
            expect(page.locator("#agent-assigned-knowledge-document-selected")).to_contain_text("Finance Checklist")
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("Public Guide")
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("Finance Checklist")
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("explicit")
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("Finance")
            expect(page.locator("#agent-assigned-knowledge-resolved-documents")).to_contain_text("Operations")

            settings = page.evaluate(
                """
                () => JSON.parse(document.getElementById('agent-additional-settings').value)
                """
            )
            assigned_knowledge = settings["assigned_knowledge"]
            assert assigned_knowledge["enabled"] is True
            assert assigned_knowledge["scopes"]["personal"] is False
            assert assigned_knowledge["scopes"]["public_workspace_ids"] == ["public-1"]
            assert assigned_knowledge["document_ids"] == ["finance-doc"]
            assert assigned_knowledge["tags"] == ["Finance", "Operations"]
            assert assigned_knowledge["web_sources"] == [
                {"url": "https://example.com/guide", "mode": "deep_research"}
            ]
            assert assigned_knowledge["allow_user_workspace_context"] is True
            assert assigned_knowledge["allowed_user_workspace_actions"] == ["search", "analyze"]

            page.evaluate("() => window.agentModalStepper.goToStep(7)")
            expect(page.locator("#summary-assigned-knowledge-section")).to_be_visible()
            expect(page.locator("#summary-assigned-knowledge")).to_contain_text("1 public workspace")
            expect(page.locator("#summary-assigned-knowledge")).to_contain_text("1 specific document")
            expect(page.locator("#summary-assigned-knowledge")).to_contain_text("2 tag limits")
            expect(page.locator("#summary-assigned-knowledge")).to_contain_text("1 assigned URL")
            expect(page.locator("#summary-assigned-knowledge")).to_contain_text("1 Deep Research URL")
            expect(page.locator("#summary-assigned-knowledge")).to_contain_text("User context: Search, Analyze")
        finally:
            context.close()
            browser.close()
