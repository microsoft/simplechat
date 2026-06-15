# test_chat_workspace_upload_progress_polling.py
"""
UI test for chat workspace upload progress polling.
Version: 0.241.203
Implemented in: 0.241.203

This test ensures workspace-backed chat upload cards keep the progress bar
visible while status details stay collapsed behind a toggle, and that the
workspace-backed upload watcher immediately enables user workspace context and
registers completed uploads as conversation task documents.
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_MESSAGES_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


@pytest.mark.ui
def test_chat_workspace_upload_progress_polling_recovers_from_transient_error():
    """Validate workspace upload progress polling updates the visible chat card."""
    playwright_sync_api = pytest.importorskip("playwright.sync_api")
    expect = playwright_sync_api.expect
    sync_playwright = playwright_sync_api.sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Playwright browser unavailable: {exc}")

        page = browser.new_page()
        try:
            run_chat_workspace_upload_progress_polling_scenario(page, expect)
        finally:
            browser.close()


def run_chat_workspace_upload_progress_polling_scenario(page, expect):
    """Run the browser assertions once a Playwright page is available."""
    chat_source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")
    snippet_start = chat_source.index("function getChatWorkspaceProgressValue")
    snippet_end = chat_source.index("function getDocumentActionCapability")
    progress_source = chat_source[snippet_start:snippet_end].replace(
        "export function watchChatWorkspaceUploadDocument",
        "function watchChatWorkspaceUploadDocument",
    )

    page.set_content(
        """
        <main>
            <div id="progress-root"></div>
        </main>
        """
    )
    page.add_script_tag(
        content=f"""
        const chatWorkspaceUploadPolls = new Map();
        const chatWorkspaceUploadCompletionWatchers = new Map();
        const currentConversationId = 'conversation-task-doc-test';
        window.currentConversationId = currentConversationId;
        window.__activationCount = 0;
        window.__selectedWorkspaceDocument = null;
        window.__registeredTaskDocuments = [];
        const activateUserWorkspaceContextForChatUpload = () => {{
            window.__activationCount += 1;
            return true;
        }};
        const selectWorkspaceDocumentForChatUpload = (workspaceDocumentId, options = {{}}) => {{
            window.__selectedWorkspaceDocument = {{ workspaceDocumentId, ...options }};
            return Promise.resolve(true);
        }};
        const registerConversationTaskDocument = (documentInfo) => {{
            window.__registeredTaskDocuments.push(documentInfo);
            return true;
        }};
        const escapeHtml = (value) => String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\"/g, '&quot;')
            .replace(/'/g, '&#39;');
        window.__intervalCallbacks = [];
        window.__clearedIntervalIds = [];
        window.setInterval = (callback) => {{
            window.__intervalCallbacks.push(callback);
            return window.__intervalCallbacks.length;
        }};
        window.clearInterval = (intervalId) => {{
            window.__clearedIntervalIds.push(intervalId);
        }};
        {progress_source}
        window.__chatWorkspaceProgressTest = {{
            buildChatWorkspaceAttachmentHtml,
            watchChatWorkspaceUploadDocument,
            startChatWorkspaceAttachmentPolling,
            hydrateChatWorkspaceAttachmentProgress,
        }};
        """
    )
    page.evaluate(
        """
        () => {
            window.__progressFetchCount = 0;
            window.__watchFetchCount = 0;
            window.__watchFetchUrls = [];
            window.fetch = async (url) => {
                const requestUrl = String(url || '');
                if (requestUrl.includes('group-upload-doc')) {
                    window.__watchFetchCount += 1;
                    window.__watchFetchUrls.push(requestUrl);
                    return {
                        ok: true,
                        status: 200,
                        json: async () => ({
                            document: {
                                id: 'group-upload-doc',
                                status: 'Processing Complete',
                                percentage_complete: 100,
                            },
                        }),
                    };
                }

                window.__progressFetchCount += 1;
                if (window.__progressFetchCount === 1) {
                    return {
                        ok: false,
                        status: 500,
                        json: async () => ({ error: 'Temporary status lookup failure' }),
                    };
                }
                return {
                    ok: true,
                    status: 200,
                    json: async () => ({
                        document: {
                            id: 'workspace-doc-ui-test',
                            status: 'Processing Complete',
                            percentage_complete: 100,
                        },
                    }),
                };
            };

            const root = document.getElementById('progress-root');
            root.innerHTML = window.__chatWorkspaceProgressTest.buildChatWorkspaceAttachmentHtml({
                document_id: 'workspace-doc-ui-test',
                status: 'Queued for processing',
                percentage_complete: 0,
            });
            const container = root.querySelector('.chat-workspace-upload-progress');
            window.__chatWorkspaceProgressTest.hydrateChatWorkspaceAttachmentProgress(root);
        }
        """
    )

    status = page.locator(".chat-workspace-upload-status-text")
    progress_bar = page.locator(".progress-bar")
    details = page.locator(".chat-workspace-upload-progress-details")

    expect(status).to_have_text("Temporary status lookup failure")
    assert "d-none" in (details.get_attribute("class") or "")
    assert "text-warning" in (status.get_attribute("class") or "")
    assert "bg-warning" in (progress_bar.get_attribute("class") or "")

    page.evaluate(
        """
        () => {
            window.__chatWorkspaceProgressTest.watchChatWorkspaceUploadDocument('group-upload-doc', {
                autoSelect: true,
                workspaceScope: 'group',
                groupId: 'group-1',
            });
        }
        """
    )

    assert page.evaluate("window.__activationCount") == 1
    page.wait_for_function("window.__selectedWorkspaceDocument !== null")
    assert page.evaluate("window.__selectedWorkspaceDocument.workspaceDocumentId") == "group-upload-doc"
    assert page.evaluate("window.__selectedWorkspaceDocument.workspaceScope") == "group"
    assert page.evaluate("window.__selectedWorkspaceDocument.groupId") == "group-1"
    assert page.evaluate("window.__registeredTaskDocuments.length") == 1
    assert page.evaluate("window.__registeredTaskDocuments[0].id") == "group-upload-doc"
    assert page.evaluate("window.__registeredTaskDocuments[0].scope") == "group"
    assert page.evaluate("window.__registeredTaskDocuments[0].group_id") == "group-1"
    assert page.evaluate("window.__registeredTaskDocuments[0].ready") is True
    assert page.evaluate("window.__watchFetchCount") == 1
    assert page.evaluate("window.__watchFetchUrls[0]").endswith("/api/group_documents/group-upload-doc")

    page.locator(".chat-workspace-progress-toggle").click()

    expect(details).to_be_visible()
    assert "d-none" not in (details.get_attribute("class") or "")

    page.evaluate("window.__intervalCallbacks[0]()")

    expect(page.locator(".chat-workspace-progress-toggle")).to_be_visible()
    expect(status).to_have_text("Processing Complete (100%)")
    assert "d-none" in (details.get_attribute("class") or "")
    expect(page.locator(".progress-bar")).to_have_count(0)

    page.locator(".chat-workspace-progress-toggle").click()

    expect(details).to_be_visible()
    assert "d-none" not in (details.get_attribute("class") or "")
    assert page.evaluate("window.__progressFetchCount") == 2
