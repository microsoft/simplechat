# test_v2_chat_upload_status.py
"""
Browser regressions for filename-independent chat upload status.
Version: 0.261.354
Implemented in: 0.261.354

Run the real Composer and polling with intercepted upload/document APIs, using
the existing local/Azure Playwright connection. No live uploads are performed.
"""

import pytest
from playwright.sync_api import expect

from test_v2_chat_context_selection import (  # noqa: F401
    CONVERSATION_ID, connect_options, context_page, mount_workflow,
)


pytestmark = pytest.mark.ui


def prepare_upload(page, scope, filename):
    mount_workflow(page)
    page.evaluate(
        """() => {
            const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
            store.setState(state => ({data: {...state.data,
                features: {...state.data.features, enable_chat_file_uploads: true}
            }}));
        }"""
    )
    page.get_by_role("textbox", name="Message", exact=True).fill("Review the uploaded policy.")
    counts = {"uploads": 0, "polls": 0}
    state = {"status": f"Processing file {filename}, type: .md", "progress": 0}

    def upload(route):
        counts["uploads"] += 1
        route.fulfill(json={
            "conversation_id": CONVERSATION_ID,
            "file_message_id": "upload-message",
            "workspace_document_id": "upload-document",
            "workspace_scope": scope,
            "workspace_document": {
                "document_id": "upload-document", "scope": scope,
                "group_id": "group-1" if scope == "group" else None,
                "file_name": filename, "status": "Queued for processing", "percentage_complete": 0,
            },
        })

    def status(route):
        counts["polls"] += 1
        route.fulfill(json={
            "id": "upload-document", "file_name": filename, "status": state["status"],
            "percentage_complete": state["progress"],
        })

    page.route("**/upload", upload)
    page.route("**/api/get_messages?*", lambda route: route.fulfill(json={"messages": []}))
    endpoint = "group_documents" if scope == "group" else "documents"
    page.route(f"**/api/{endpoint}/upload-document", status)
    page.locator('[data-composer-editor="composer-input"] input[type="file"]').set_input_files({
        "name": filename, "mimeType": "text/markdown", "buffer": b"# Policy\nLimit: 125000.",
    })
    item = page.get_by_role("list", name="Attached files", exact=True).get_by_role("listitem")
    expect(item.get_by_text("Processing 0%", exact=True)).to_be_visible()
    return item, counts, state


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("filename", [
    "FED-failed-harness-followup-20261019-a-FED-17-policy-v1.md",
    "error-budget.md",
    "processing complete.md",
    "incomplete-policy.md",
])
def test_processing_keeps_polling_until_real_completion(context_page, scope, filename):
    page, _ = context_page
    item, counts, state = prepare_upload(page, scope, filename)
    endpoint = "group_documents" if scope == "group" else "documents"
    with page.expect_request(f"**/api/{endpoint}/upload-document"):
        expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
    expect(item.get_by_role("alert")).to_have_count(0)
    expect(item.get_by_text("Ready", exact=True)).to_have_count(0)
    state.update(status="Retrying Markdown processing after a transient parser concurrency error (1/3)...", progress=20)
    expect(item.get_by_text("Processing 20%", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
    state.update(status="Processing complete - final metadata extracted", progress=100)
    expect(item.get_by_text("Ready", exact=True)).to_be_visible(timeout=15000)
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_enabled()
    assert counts["uploads"] == 1
    assert counts["polls"] >= 4


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_real_failure_stays_visible_and_retry_only_rechecks_status(context_page, scope):
    page, _ = context_page
    filename = "error-budget.md"
    item, counts, state = prepare_upload(page, scope, filename)
    state.update(status="Error: Unable to process document.", progress=100)
    expect(item.get_by_text("Failed", exact=True)).to_be_visible(timeout=10000)
    expect(item.get_by_role("alert")).to_contain_text("File processing failed.")
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
    before = counts["polls"]
    state.update(status="Processing complete", progress=100)
    page.get_by_role("button", name=f"Retry {filename}", exact=True).click()
    expect(item.get_by_text("Ready", exact=True)).to_be_visible()
    assert counts["uploads"] == 1
    assert counts["polls"] > before


def test_removing_processing_upload_cancels_tracking(context_page):
    page, _ = context_page
    page.clock.install()
    filename = "failed-checklist.md"
    item, counts, state = prepare_upload(page, "personal", filename)
    page.get_by_role("button", name=f"Remove {filename}", exact=True).click()
    expect(item).to_have_count(0)
    before = counts["polls"]
    state.update(status="Processing complete", progress=100)
    # Rendering another draft change must not resurrect a removed upload.
    page.get_by_role("textbox", name="Message", exact=True).fill("No attachment.")
    page.clock.run_for(6000)
    expect(page.get_by_role("list", name="Attached files", exact=True)).to_have_count(0)
    assert counts["polls"] == before
