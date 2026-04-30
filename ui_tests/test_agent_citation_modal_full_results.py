# test_agent_citation_modal_full_results.py
"""
UI test for agent citation full-result modal rendering.

Version: 0.240.048
Implemented in: 0.240.048

This test ensures that opening an agent tool citation lazy-loads the raw
artifact payload, starts with a short preview, expands to 25 rows, and can
show all returned rows for tabular results.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _build_raw_citation_payload():
    rows = [
        {
            "Location": f"Row {index:02d} - https://contoso.sharepoint.com/sites/Site{index:02d}",
            "Site": f"Site {index:02d}",
        }
        for index in range(1, 31)
    ]
    return {
        "tool_name": "TabularProcessingPlugin.search_rows [Legal]",
        "function_name": "search_rows",
        "plugin_name": "TabularProcessingPlugin",
        "function_arguments": json.dumps(
            {
                "filename": "CCO-Legal File Plan 2025_Final Approved.xlsx",
                "sheet_name": "Legal",
                "search_value": "SharePoint",
                "search_columns": "Location",
                "max_rows": "25",
            }
        ),
        "function_result": json.dumps(
            {
                "filename": "CCO-Legal File Plan 2025_Final Approved.xlsx",
                "selected_sheet": "Legal",
                "search_value": "SharePoint",
                "searched_columns": ["Location"],
                "total_matches": 30,
                "returned_rows": 30,
                "data": rows,
            }
        ),
        "artifact_id": "assistant-msg-1_artifact_1",
    }


@pytest.mark.ui
def test_agent_citation_modal_can_expand_from_preview_to_all_rows(playwright):
    """Validate the agent citation modal can expand raw tabular results on demand."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    compact_citation = {
        "tool_name": "TabularProcessingPlugin.search_rows [Legal]",
        "function_arguments": {
            "filename": "CCO-Legal File Plan 2025_Final Approved.xlsx",
            "sheet_name": "Legal",
            "search_value": "SharePoint",
            "search_columns": "Location",
            "max_rows": "25",
        },
        "function_result": {
            "filename": "CCO-Legal File Plan 2025_Final Approved.xlsx",
            "selected_sheet": "Legal",
            "total_matches": 30,
            "returned_rows": 30,
            "sample_rows": [
                {"Location": "Row 01 - https://contoso.sharepoint.com/sites/Site01 ... [truncated 120 chars]"},
            ],
            "sample_rows_limited": True,
        },
        "artifact_id": "assistant-msg-1_artifact_1",
        "raw_payload_externalized": True,
    }

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))
    page.route(
        "**/api/conversation/test-convo/agent-citation/assistant-msg-1_artifact_1",
        lambda route: _fulfill_json(route, {"citation": _build_raw_citation_payload()}),
    )

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        page.wait_for_selector("#chatbox")

        page.evaluate(
            """
            async (payload) => {
                currentConversationId = 'test-convo';
                window.currentConversationId = 'test-convo';
                const messagesModule = await import('/static/js/chat/chat-messages.js');
                messagesModule.appendMessage(
                    'AI',
                    'Citation answer',
                    null,
                    'assistant-msg-1',
                    false,
                    [],
                    [],
                    [payload],
                    null,
                    null,
                    {
                        id: 'assistant-msg-1',
                        role: 'assistant',
                        content: 'Citation answer',
                        agent_citations: [payload],
                    },
                    true
                );
            }
            """,
            compact_citation,
        )

        citation_button = page.locator("a.agent-citation-link").first
        expect(citation_button).to_be_visible()

        with page.expect_response("**/api/conversation/test-convo/agent-citation/assistant-msg-1_artifact_1"):
            citation_button.click()

        expect(page.locator("#agent-citation-modal")).to_be_visible()
        expect(page.locator("#agent-tool-result-summary")).to_contain_text("total_matches: 30")
        expect(page.locator("#agent-tool-result-summary")).to_contain_text("returned_rows: 30")
        expect(page.locator("#agent-tool-result-summary")).to_contain_text("showing 3 rows")

        result_panel = page.locator("#agent-tool-result")
        expect(result_panel).to_contain_text("Row 01")
        expect(result_panel).to_contain_text("Row 03")
        expect(result_panel).not_to_contain_text("Row 04")

        page.get_by_role("button", name="Show 25 rows").click()
        expect(page.locator("#agent-tool-result-summary")).to_contain_text("showing 25 rows")
        expect(result_panel).to_contain_text("Row 25")
        expect(result_panel).not_to_contain_text("Row 26")

        page.get_by_role("button", name="Show all rows").click()
        expect(page.locator("#agent-tool-result-summary")).to_contain_text("showing 30 rows")
        expect(result_panel).to_contain_text("Row 30")

        page.get_by_role("button", name="Show preview").click()
        expect(page.locator("#agent-tool-result-summary")).to_contain_text("showing 3 rows")
        expect(result_panel).not_to_contain_text("Row 04")
    finally:
        context.close()
        browser.close()