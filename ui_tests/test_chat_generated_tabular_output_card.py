# test_chat_generated_tabular_output_card.py
"""
UI test for chat generated tabular output cards.
Version: 0.241.096
Implemented in: 0.241.033
Updated in: 0.241.096

This test ensures assistant replies with generic generated analysis artifact
metadata render a reusable export card, preserve untrusted values as text,
keep long JSON preview lines wrapped inside the chat card, and trigger the chat
artifact download endpoint plus the workspace-promotion action when the user
clicks the card buttons without introducing page-level JavaScript errors. It
also validates Markdown artifact previews render as sanitized Markdown instead
of raw source text and that generated Markdown files can be viewed in a rendered
modal from the artifact card. It also ensures generated Markdown artifact cards
offer direct PowerPoint export and that workspace promotion opens a confirmation
or target-selection modal before submitting.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _wait_for_chatbox_or_skip(page):
    try:
        page.wait_for_selector("#chatbox", timeout=10000)
    except PlaywrightTimeoutError:
        if "login" in page.url.lower():
            pytest.skip("Generated artifact card UI tests require an authenticated chat session.")
        raise


@pytest.mark.ui
def test_chat_generated_tabular_output_card(playwright):
    """Validate generated tabular output cards render preview data and trigger downloads."""
    _require_ui_env()

    download_requests = []
    promote_requests = []
    page_errors = []

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
        accept_downloads=True,
        ignore_https_errors=True,
    )
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))

    def handle_generated_download(route):
        download_requests.append(route.request.url)
        route.fulfill(
            status=200,
            headers={
                "Content-Type": "application/json",
                "Content-Disposition": 'attachment; filename="comments.json"',
            },
            body=b"[]",
        )

    page.route(
        "**/api/chat_artifacts/download?conversation_id=generated-tabular-output-test&message_id=generated-export-123",
        handle_generated_download,
    )

    def handle_promote(route):
        promote_requests.append(json.loads(route.request.post_data or "{}"))
        _fulfill_json(
            route,
            {
                "approval_required": False,
                "workspace_scope": "personal",
                "document": {
                    "id": "workspace-doc-123",
                    "file_name": "comments.json",
                },
            },
        )

    page.route("**/api/chat_artifacts/promote", handle_promote)

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        _wait_for_chatbox_or_skip(page)
        page.wait_for_function("() => window.chatMessages && typeof window.chatMessages.appendMessage === 'function'")

        page.evaluate(
            """
            async () => {
                const conversationId = 'generated-tabular-output-test';
                currentConversationId = conversationId;
                window.currentConversationId = conversationId;

                const documentsModule = await import('/static/js/chat/chat-documents.js');
                await documentsModule.setEffectiveScopes(
                    { personal: true, groupIds: [], publicWorkspaceIds: [] },
                    { reload: false, force: true }
                );

                const messagesModule = await import('/static/js/chat/chat-messages.js');

                messagesModule.appendMessage(
                    'AI',
                    'I prepared a reusable export for every comment row.',
                    null,
                    'assistant-generated-output',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'assistant-generated-output',
                        role: 'assistant',
                        content: 'I prepared a reusable export for every comment row.',
                        metadata: {
                            generated_analysis_artifacts: [
                                {
                                    capability: 'tabular',
                                    artifact_message_id: 'generated-export-123',
                                    conversation_id: 'generated-tabular-output-test',
                                    storage_scope: 'chat',
                                    file_name: 'comments<script>alert(1)</script>.json',
                                    output_format: 'json',
                                    row_count: 124,
                                    source_file_name: 'feedback_comments.xlsx',
                                    selected_sheet: 'Comments',
                                    summary: 'The full export is saved separately so the reply can stay concise. <analysis>',
                                    preview_rows: [
                                        {
                                            comment_id: '001',
                                            author: 'Alicia <Admin>',
                                            comment: 'First <tag> comment',
                                        },
                                        {
                                            comment_id: '002',
                                            author: 'Ben',
                                            comment: 'Second comment',
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                    true
                );
            }
            """
        )

        card = page.locator('.generated-tabular-output-card')
        expect(card).to_be_visible()
        expect(card).to_contain_text('Generated JSON export')
        expect(card).to_contain_text('Saved to this chat for download in this conversation.')
        expect(card).to_contain_text('124 rows')
        expect(card).to_contain_text('Source: feedback_comments.xlsx | Sheet: Comments')
        expect(card).to_contain_text('comments<script>alert(1)</script>.json')
        expect(card).to_contain_text('The full export is saved separately so the reply can stay concise. <analysis>')
        expect(card).to_contain_text('Alicia <Admin>')
        expect(card).to_contain_text('First <tag> comment')

        assert page.locator('.generated-tabular-output-card script').count() == 0

        with page.expect_download() as download_info:
            page.get_by_role('button', name='Download JSON').click()
        download = download_info.value

        assert download.suggested_filename == 'comments.json'
        assert download_requests == [
            f'{BASE_URL}/api/chat_artifacts/download?conversation_id=generated-tabular-output-test&message_id=generated-export-123'
        ]

        page.get_by_role('button', name='Add to Workspace').click()
        promotion_modal = page.locator('#generated-artifact-workspace-modal')
        expect(promotion_modal).to_be_visible()
        expect(promotion_modal).to_contain_text('Add to Personal workspace?')
        expect(promotion_modal).to_contain_text('comments<script>alert(1)</script>.json will be saved to Personal workspace.')
        page.get_by_role('button', name='Add to Personal').click()
        expect(page.get_by_role('button', name='Added to Workspace')).to_be_visible()

        assert len(promote_requests) == 1
        assert promote_requests[0]["conversation_id"] == "generated-tabular-output-test"
        assert promote_requests[0]["message_id"] == "generated-export-123"
        assert promote_requests[0]["workspace_scope"] == "personal"
        assert page_errors == []
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_generated_artifact_workspace_promotion_modal_target_selection(playwright):
    """Validate ambiguous workspace promotion opens a chooser and submits the selected target."""
    _require_ui_env()

    promote_requests = []
    page_errors = []

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))

    def handle_promote(route):
        promote_requests.append(json.loads(route.request.post_data or "{}"))
        _fulfill_json(
            route,
            {
                "approval_required": True,
                "workspace_scope": "group",
                "group_id": "research-team",
                "document": {
                    "id": "workspace-doc-456",
                    "file_name": "research-ledger.md",
                },
            },
            status=202,
        )

    page.route("**/api/chat_artifacts/promote", handle_promote)

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        _wait_for_chatbox_or_skip(page)
        page.wait_for_function("() => window.chatMessages && typeof window.chatMessages.appendMessage === 'function'")

        page.evaluate(
            """
            async () => {
                const conversationId = 'generated-artifact-target-selection-test';
                currentConversationId = conversationId;
                window.currentConversationId = conversationId;
                window.userGroups = [{ id: 'research-team', name: 'Research Team' }];
                window.userVisiblePublicWorkspaces = [];

                const documentsModule = await import('/static/js/chat/chat-documents.js');
                await documentsModule.setEffectiveScopes(
                    { personal: true, groupIds: ['research-team'], publicWorkspaceIds: [] },
                    { reload: false, force: true }
                );

                const messagesModule = await import('/static/js/chat/chat-messages.js');
                messagesModule.appendMessage(
                    'AI',
                    'I saved the research ledger as a Markdown artifact.',
                    null,
                    'assistant-generated-md-output',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'assistant-generated-md-output',
                        role: 'assistant',
                        content: 'I saved the research ledger as a Markdown artifact.',
                        metadata: {
                            generated_analysis_artifacts: [
                                {
                                    capability: 'deep_research',
                                    artifact_message_id: 'generated-md-export-456',
                                    conversation_id: 'generated-artifact-target-selection-test',
                                    storage_scope: 'chat',
                                    file_name: 'research-ledger.md',
                                    output_format: 'md',
                                    summary: 'Deep Research ledger.',
                                },
                            ],
                        },
                    },
                    true
                );
            }
            """
        )

        page.get_by_role('button', name='Add to Workspace').click()
        promotion_modal = page.locator('#generated-artifact-workspace-modal')
        expect(promotion_modal).to_be_visible()
        expect(promotion_modal).to_contain_text('Choose Workspace')
        expect(promotion_modal).to_contain_text('Personal workspace')
        expect(promotion_modal).to_contain_text('Research Team')

        page.locator('input[name="generated-artifact-workspace-target"][value="group:research-team"]').check()
        page.get_by_role('button', name='Add to Selected Workspace').click()
        expect(page.get_by_role('button', name='Pending Approval')).to_be_visible()

        assert len(promote_requests) == 1
        assert promote_requests[0]["conversation_id"] == "generated-artifact-target-selection-test"
        assert promote_requests[0]["message_id"] == "generated-md-export-456"
        assert promote_requests[0]["workspace_scope"] == "group"
        assert promote_requests[0]["group_id"] == "research-team"
        assert page_errors == []
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_generated_analysis_json_preview_wraps_long_lines(playwright):
    """Validate generated JSON preview blocks wrap long lines instead of overflowing the card."""
    _require_ui_env()

    long_reason_token = "analysis" * 160
    artifact_payload = {
        "capability": "analyze",
        "artifact_message_id": "generated-wrap-123",
        "conversation_id": "generated-json-wrap-test",
        "storage_scope": "chat",
        "file_name": "analysis.json",
        "output_format": "json",
        "summary": "Saved the full analysis as a JSON artifact for follow-up.",
        "preview_items": [
            {
                "comment_id": "115562TroyHammer.pdf",
                "classification": "substantive",
                "reason": long_reason_token,
            }
        ],
    }

    page_errors = []

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 900, "height": 900},
        ignore_https_errors=True,
    )
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        _wait_for_chatbox_or_skip(page)
        page.wait_for_function("() => window.chatMessages && typeof window.chatMessages.appendMessage === 'function'")

        page.evaluate(
            """
            async (artifactPayload) => {
                const conversationId = 'generated-json-wrap-test';
                currentConversationId = conversationId;
                window.currentConversationId = conversationId;

                const messagesModule = await import('/static/js/chat/chat-messages.js');

                messagesModule.appendMessage(
                    'AI',
                    'Saved the analysis JSON artifact.',
                    null,
                    'assistant-generated-wrap',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'assistant-generated-wrap',
                        role: 'assistant',
                        content: 'Saved the analysis JSON artifact.',
                        metadata: {
                            generated_analysis_artifacts: [artifactPayload],
                        },
                    },
                    true
                );
            }
            """,
            artifact_payload,
        )

        card = page.locator('.generated-tabular-output-card')
        expect(card).to_be_visible()
        expect(card).to_contain_text('Analyze JSON artifact')

        preview_block = card.locator('.generated-analysis-preview-block')
        expect(preview_block).to_be_visible()
        expect(preview_block).to_contain_text(long_reason_token[:120])

        layout_metrics = preview_block.evaluate(
            """
            (node) => {
                const computedStyle = window.getComputedStyle(node);
                return {
                    whiteSpace: computedStyle.whiteSpace,
                    overflowWrap: computedStyle.overflowWrap,
                    scrollWidth: node.scrollWidth,
                    clientWidth: node.clientWidth,
                };
            }
            """
        )

        assert layout_metrics["whiteSpace"] == "pre-wrap"
        assert layout_metrics["overflowWrap"] == "anywhere"
        assert layout_metrics["scrollWidth"] <= layout_metrics["clientWidth"] + 4, (
            "Expected generated JSON preview lines to wrap within the preview block instead of "
            "overflowing horizontally."
        )
        assert page_errors == []
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_generated_analysis_markdown_preview_renders_markdown(playwright):
    """Validate generated Markdown artifact previews and modal view render sanitized Markdown."""
    _require_ui_env()

    full_markdown_body = "\n".join(
        [
            "# Full Circular A-4 Analysis",
            "",
            "**Document-level summary:** Circular A-4 provides government-wide guidance.",
            "",
            "## Core framework and analytical orientation",
            "",
            "The Circular makes **benefit-cost analysis (BCA)** the primary analytic tool.",
            "",
            '<img src=x onerror="window.__markdownViewXss = true">',
        ]
    )
    artifact_payload = {
        "capability": "analyze",
        "artifact_message_id": "generated-markdown-123",
        "conversation_id": "generated-markdown-preview-test",
        "storage_scope": "chat",
        "file_name": "circular-a-4-analysis.md",
        "output_format": "md",
        "summary": "Saved the full analysis as a Markdown artifact for follow-up.",
        "preview_lines": [
            "**Document-level summary: Circular A-4 (OMB), consolidated from pages 1-93**",
            "OMB Circular A-4 provides government-wide guidance on regulatory analyses.",
            "## Core framework and analytical orientation",
            "The Circular makes **benefit-cost analysis (BCA)** the primary analytic tool.",
            "<img src=x onerror=\"window.__markdownPreviewXss = true\">",
        ],
    }
    page_errors = []
    view_requests = []

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))
    page.route(
        "**/api/chat_artifacts/download?conversation_id=generated-markdown-preview-test&message_id=generated-markdown-123",
        lambda route: (
            view_requests.append(route.request.url),
            route.fulfill(
                status=200,
                headers={
                    "Content-Type": "text/markdown; charset=utf-8",
                    "Content-Disposition": 'attachment; filename="circular-a-4-analysis.md"',
                },
                body=full_markdown_body,
            ),
        ),
    )

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        _wait_for_chatbox_or_skip(page)

        page.evaluate(
            """
            async (artifactPayload) => {
                const conversationId = 'generated-markdown-preview-test';
                currentConversationId = conversationId;
                window.currentConversationId = conversationId;
                window.__markdownPreviewXss = false;
                window.__markdownViewXss = false;

                const messagesModule = await import('/static/js/chat/chat-messages.js');

                messagesModule.appendMessage(
                    'AI',
                    'Saved the Markdown analysis artifact.',
                    null,
                    'assistant-generated-markdown',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'assistant-generated-markdown',
                        role: 'assistant',
                        content: 'Saved the Markdown analysis artifact.',
                        metadata: {
                            generated_analysis_artifacts: [artifactPayload],
                        },
                    },
                    true
                );
            }
            """,
            artifact_payload,
        )

        card = page.locator('.generated-tabular-output-card')
        expect(card).to_be_visible()
        expect(card).to_contain_text('Analyze MD artifact')

        preview_block = card.locator('.generated-analysis-markdown-preview')
        expect(preview_block).to_be_visible()
        expect(preview_block.locator('strong').filter(has_text='Document-level summary')).to_be_visible()
        expect(preview_block.locator('h2').filter(has_text='Core framework')).to_be_visible()
        expect(preview_block.locator('strong').filter(has_text='benefit-cost analysis')).to_be_visible()
        expect(preview_block).not_to_contain_text('**Document-level summary')
        expect(preview_block).not_to_contain_text('## Core framework')
        expect(preview_block.locator('script')).to_have_count(0)
        expect(preview_block.locator('[onerror]')).to_have_count(0)

        view_button = card.get_by_role('button', name='View MD')
        expect(view_button).to_be_visible()
        expect(card.get_by_role('button', name='Create PowerPoint')).to_be_visible()

        with page.expect_response(
            "**/api/chat_artifacts/download?conversation_id=generated-markdown-preview-test&message_id=generated-markdown-123"
        ):
            view_button.click()

        citation_modal = page.locator('#citation-modal')
        expect(citation_modal).to_be_visible()
        expect(citation_modal.locator('.modal-title')).to_have_text(
            'Markdown artifact: circular-a-4-analysis.md'
        )

        modal_content = citation_modal.locator('#cited-text-content')
        expect(modal_content.locator('h1')).to_have_text('Full Circular A-4 Analysis')
        expect(modal_content.locator('h2')).to_have_text('Core framework and analytical orientation')
        expect(modal_content.locator('strong').filter(has_text='benefit-cost analysis')).to_be_visible()
        expect(modal_content).not_to_contain_text('# Full Circular A-4 Analysis')
        expect(modal_content).not_to_contain_text('## Core framework')
        expect(modal_content.locator('[onerror]')).to_have_count(0)

        assert view_requests == [
            f'{BASE_URL}/api/chat_artifacts/download?conversation_id=generated-markdown-preview-test&message_id=generated-markdown-123'
        ]
        assert page.evaluate("() => window.__markdownPreviewXss") is False
        assert page.evaluate("() => window.__markdownViewXss") is False
        assert page_errors == []
    finally:
        context.close()
        browser.close()
