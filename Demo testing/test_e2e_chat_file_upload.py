# test_e2e_chat_file_upload.py
"""
End-to-end test for local personal workspace upload and chat response.
Version: 0.250.018
Implemented in: 0.250.003; presenter waits refined in 0.250.011; hidden upload input marker fixed in 0.250.013; upload agreement handled in 0.250.014; model mode enforced in 0.250.015; workspace Chat button click added in 0.250.016; chat picker file selection verified in 0.250.017; document select id fixed in 0.250.018

This test opens a local headed browser, allows the presenter to sign in, uploads
a file to the personal workspace, launches chat with that workspace document,
sends a prompt about the file, waits for an assistant response, and cleans up.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from demo_helpers import (
    ensure_artifact_dir,
    env_flag,
    get_demo_base_url,
    get_int_env,
    new_demo_context,
    pause_for_presenter,
    wait_for_authenticated_selector,
    wait_for_new_completed_assistant_response,
)


UPLOAD_FILE = Path(__file__).resolve().parent / "fixtures" / "simplechat_demo_upload.txt"
UPLOAD_TIMEOUT_MS = 180000
RESPONSE_TIMEOUT_MS = 240000


def accept_upload_agreement_if_present(page):
    """Accept the upload agreement modal when the environment requires it."""
    modal = page.locator("#userAgreementUploadModal")
    try:
        modal.wait_for(state="visible", timeout=3000)
    except Exception:
        return False

    page.locator("#userAgreementUploadAcceptBtn").click()
    return True


def force_model_chat_mode(context, base_url):
    """Persist model chat mode so a previously selected agent cannot handle this demo."""
    response = context.request.post(
        f"{base_url}/api/user/settings",
        data={"settings": {"enable_agents": False}},
        timeout=30000,
    )
    assert response.ok, f"Expected model-mode settings update to succeed, got HTTP {response.status}."


def click_uploaded_document_chat_button(page, document_id, artifact_dir):
    """Click the uploaded document's visible Chat button from Personal Workspace."""
    page.evaluate("() => window.fetchUserDocuments?.()")
    chat_button = page.locator(
        f"button[onclick*=\"redirectToChat('{document_id}')\"]"
    ).filter(has_text="Chat").first
    chat_button.wait_for(state="visible", timeout=30000)
    chat_button.scroll_into_view_if_needed(timeout=10000)
    page.screenshot(path=artifact_dir / "demo_workspace_uploaded_file_chat_button.png", full_page=True)
    chat_button.click()


def ensure_uploaded_document_selected_in_chat(page, document_id, artifact_dir):
    """Open the chat workspace picker and ensure the uploaded document is visibly selected."""
    page.locator("#search-documents-btn").wait_for(state="visible", timeout=30000)
    page.locator("#document-dropdown-button").wait_for(state="visible", timeout=30000)
    page.wait_for_function(
        """
        ({ documentId }) => {
            const select = document.querySelector('#document-select');
            const item = document.querySelector(`#document-dropdown-items .dropdown-item[data-document-id="${documentId}"]`);
            return Boolean(select && item && Array.from(select.options).some((option) => option.value === documentId));
        }
        """,
        arg={"documentId": document_id},
        timeout=30000,
    )

    page.locator("#document-dropdown-button").click()
    page.locator("#document-dropdown-menu").wait_for(state="visible", timeout=10000)
    document_item = page.locator(
        f"#document-dropdown-items .dropdown-item[data-document-id=\"{document_id}\"]"
    ).first
    document_item.scroll_into_view_if_needed(timeout=10000)

    is_selected = page.evaluate(
        """
        ({ documentId }) => {
            const select = document.querySelector('#document-select');
            const option = select ? Array.from(select.options).find((item) => item.value === documentId) : null;
            const item = document.querySelector(`#document-dropdown-items .dropdown-item[data-document-id="${documentId}"]`);
            const checkbox = item ? item.querySelector('.doc-checkbox') : null;
            return Boolean((option && option.selected) || (checkbox && checkbox.checked));
        }
        """,
        arg={"documentId": document_id},
    )
    if not is_selected:
        document_item.click()

    page.wait_for_function(
        """
        ({ documentId }) => {
            const select = document.querySelector('#document-select');
            const option = select ? Array.from(select.options).find((item) => item.value === documentId) : null;
            const item = document.querySelector(`#document-dropdown-items .dropdown-item[data-document-id="${documentId}"]`);
            const checkbox = item ? item.querySelector('.doc-checkbox') : null;
            return Boolean(option && option.selected && checkbox && checkbox.checked);
        }
        """,
        arg={"documentId": document_id},
        timeout=10000,
    )
    page.screenshot(path=artifact_dir / "demo_chat_uploaded_file_selected.png", full_page=True)
    page.keyboard.press("Escape")


@pytest.mark.ui
def test_local_personal_workspace_upload_file_and_chat_with_it(playwright):
    """Demonstrate a live local browser workspace upload and chat loop."""
    base_url = get_demo_base_url()
    artifact_dir = ensure_artifact_dir()
    browser, context = new_demo_context(playwright)
    page = context.new_page()
    conversation_id = None
    document_id = None
    trace_path = artifact_dir / "demo_chat_file_upload_trace.zip"
    screenshot_path = artifact_dir / "demo_chat_file_upload_failure.png"
    context.tracing.start(screenshots=True, snapshots=True, sources=True)

    try:
        page.goto(f"{base_url}/workspace", wait_until="domcontentloaded", timeout=60000)
        wait_for_authenticated_selector(page, "#upload-area", "the personal workspace upload demo")

        expect(page.get_by_role("heading", name="Personal Workspace")).to_be_visible(timeout=30000)
        expect(page.locator("#workspace-file-input")).to_be_attached(timeout=30000)

        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith("/api/documents/upload"),
            timeout=UPLOAD_TIMEOUT_MS,
        ) as upload_response_info:
            page.locator("#workspace-file-input").set_input_files(str(UPLOAD_FILE))
            if accept_upload_agreement_if_present(page):
                print("Accepted upload agreement before workspace upload.")

        upload_response = upload_response_info.value
        assert upload_response.ok, f"Expected workspace upload to succeed, got HTTP {upload_response.status}."
        upload_payload = upload_response.json()
        document_ids = upload_payload.get("document_ids") or []
        assert document_ids, "Expected workspace upload response to include document_ids."
        document_id = document_ids[0]

        page.wait_for_function(
            """
            ({ documentId }) => Array.isArray(window.lastFetchedDocs)
                && window.lastFetchedDocs.some((doc) => String(doc.id || '') === String(documentId))
            """,
            arg={"documentId": document_id},
            timeout=UPLOAD_TIMEOUT_MS,
        )

        page.wait_for_function(
            """
            async ({ documentId }) => {
                const response = await fetch(`/api/documents/${encodeURIComponent(documentId)}`);
                if (!response.ok) {
                    return false;
                }
                const documentItem = await response.json();
                const status = String(documentItem.status || '').toLowerCase();
                const percentage = Number.parseFloat(String(documentItem.percentage_complete || '0'));
                if (status.includes('error')) {
                    throw new Error(`Uploaded document processing failed: ${documentItem.status}`);
                }
                return percentage >= 100 || status.includes('complete');
            }
            """,
            arg={"documentId": document_id},
            timeout=UPLOAD_TIMEOUT_MS,
        )

        if env_flag("SIMPLECHAT_DEMO_FILE_DISABLE_AGENTS", default=True):
            force_model_chat_mode(context, base_url)

        click_uploaded_document_chat_button(page, document_id, artifact_dir)
        page.wait_for_url("**/chats?**", timeout=60000)
        wait_for_authenticated_selector(page, "#user-input", "the chat-with-workspace-document demo")

        expect(page.locator("#search-documents-btn")).to_be_attached(timeout=30000)
        expect(page.locator("#send-btn")).to_be_attached(timeout=30000)

        ensure_uploaded_document_selected_in_chat(page, document_id, artifact_dir)

        if env_flag("SIMPLECHAT_DEMO_FILE_DISABLE_AGENTS", default=True):
            enable_agents_button = page.locator("#enable-agents-btn")
            if enable_agents_button.is_visible(timeout=10000):
                page.wait_for_function(
                    """
                    () => {
                        const button = document.querySelector('#enable-agents-btn');
                        const modelContainer = document.querySelector('#model-select-container');
                        const agentContainer = document.querySelector('#agent-select-container');
                        return Boolean(
                            button
                            && !button.classList.contains('active')
                            && modelContainer
                            && modelContainer.offsetParent !== null
                            && (!agentContainer || agentContainer.offsetParent === null)
                        );
                    }
                    """,
                    timeout=30000,
                )
                print("Verified file-upload demo is using model mode, not an agent.")

        expect(page.locator("#user-input")).to_be_visible(timeout=30000)
        expected_response_text = os.getenv(
            "SIMPLECHAT_DEMO_FILE_EXPECTED_RESPONSE_TEXT",
            "SimpleChat local Playwright testing demo",
        )
        prompt = os.getenv(
            "SIMPLECHAT_DEMO_FILE_PROMPT",
            f"Using only the selected workspace file, reply exactly: {expected_response_text}.",
        )
        previous_ai_message_count = page.locator(".ai-message .message-text").count()
        page.locator("#user-input").fill(prompt)
        page.locator("#send-btn").click()

        expect(page.locator(".user-message .message-text").filter(has_text=prompt)).to_be_visible(timeout=15000)
        assistant_text = wait_for_new_completed_assistant_response(
            page,
            previous_ai_message_count,
            RESPONSE_TIMEOUT_MS,
            expected_text=expected_response_text,
        )
        assert assistant_text, "Expected assistant response text after uploading a workspace file and asking about it."
        print("Uploaded-file response preview:", assistant_text[:500])
        page.screenshot(path=artifact_dir / "demo_chat_file_upload_response.png", full_page=True)

        conversation_id = page.evaluate(
            """
            () => window.chatConversations?.getCurrentConversationId?.()
                || window.currentConversationId
                || null
            """
        )

        pause_for_presenter(
            page,
            "SIMPLECHAT_DEMO_FILE_POST_RESPONSE_PAUSE_MS",
            get_int_env("SIMPLECHAT_DEMO_POST_RESPONSE_PAUSE_MS", 10000),
            "Uploaded-file response is complete.",
        )
        pause_for_presenter(
            page,
            "SIMPLECHAT_DEMO_FILE_BROWSER_PAUSE_MS",
            get_int_env("SIMPLECHAT_DEMO_BROWSER_PAUSE_MS", 0),
            "Final file-upload demo hold before cleanup.",
        )
    except Exception:
        page.screenshot(path=screenshot_path, full_page=True)
        raise
    finally:
        if conversation_id:
            try:
                context.request.delete(f"{base_url}/api/conversations/{conversation_id}", timeout=30000)
            except Exception:
                pass
        if document_id:
            try:
                context.request.delete(f"{base_url}/api/documents/{document_id}?delete_mode=all_versions", timeout=30000)
            except Exception:
                pass
        context.tracing.stop(path=trace_path)
        context.close()
        browser.close()