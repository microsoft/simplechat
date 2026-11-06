# test_v2_chat_attachment_isolation.py
"""
Browser regressions for conversation-owned V2 chat attachments.
Version: 0.261.414
Implemented in: 0.261.414

The real sidebar, composer, stores, and request builders run against synthetic
APIs through the existing local/Azure Playwright connection. Navigation must
not transfer selections, and restored documents must retain readable names.
"""

import base64
from copy import deepcopy
from email import policy
from email.parser import BytesParser
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_new_chat_reset import (  # noqa: F401
    NewChatApi,
    click_new_chat,
    connect_options,
    draft,
    editor_assets,
    editor_browser,
    mount,
    open_from_rail,
)


pytestmark = pytest.mark.ui
ORIGIN_CHAT = "attachment-origin"
OTHER_CHAT = "attachment-destination"
ORIGIN_TITLE = "Original attachment chat"
OTHER_TITLE = "Unrelated destination chat"
DOCUMENT_ID = "11111111-2222-4333-8444-555555555555"
FILENAME = "original-diagram.png"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def saved_selection(document_id=DOCUMENT_ID):
    return {
        "version": 1,
        "mode": "selected",
        "sources": [{"kind": "document", "id": document_id, "scope": {"kind": "personal"}}],
    }


def attachment_message(filename=FILENAME, document_id=DOCUMENT_ID, conversation=ORIGIN_CHAT):
    return {
        "id": f"{conversation}_file_original",
        "conversation_id": conversation,
        "role": "file",
        "content": "",
        "filename": filename,
        "workspace_document_id": document_id,
        "metadata": {
            "is_user_upload": True,
            "workspace_attachment": {
                "document_id": document_id,
                "file_name": filename,
                "scope": "personal",
                "status": "ready",
                "percentage_complete": 100,
            },
        },
    }


class AttachmentApi(NewChatApi):
    """Keep uploaded messages and document metadata in their original conversation."""

    def __init__(self, assets):
        super().__init__(assets)
        self.conversations = [
            {"id": ORIGIN_CHAT, "title": ORIGIN_TITLE},
            {"id": OTHER_CHAT, "title": OTHER_TITLE},
        ]
        self.messages = {
            ORIGIN_CHAT: [
                attachment_message(),
                {
                    "id": "original-question",
                    "conversation_id": ORIGIN_CHAT,
                    "role": "user",
                    "content": "Describe this diagram.",
                    "metadata": {"workspace_search": {"document_source_selection": saved_selection()}},
                },
                {
                    "id": "original-answer",
                    "conversation_id": ORIGIN_CHAT,
                    "role": "assistant",
                    "content": "The original diagram is attached here.",
                },
            ],
            OTHER_CHAT: [
                {
                    "id": "unrelated-question",
                    "conversation_id": OTHER_CHAT,
                    "role": "user",
                    "content": "A question with no attached files.",
                },
            ],
        }
        self.documents = {
            DOCUMENT_ID: {
                "id": DOCUMENT_ID, "file_name": FILENAME,
                "status": "ready", "percentage_complete": 100,
            },
        }
        self.metadata_documents = {
            ORIGIN_CHAT: [{
                "document_id": DOCUMENT_ID, "file_name": FILENAME,
                "scope": {"type": "personal"},
            }],
            OTHER_CHAT: [],
        }
        self.uploads = []
        self.defer_uploads = False
        self.defer_details = False
        self.defer_messages = {}
        self.defer_metadata = {}
        self.held = []
        self.processing = False
        self.workspace_uploads = True

    def release_kind(self, kind):
        matching = [entry for entry in self.held if entry[0] == kind]
        self.held = [entry for entry in self.held if entry[0] != kind]
        for _, route, payload in matching:
            route.fulfill(json=payload)

    def release(self):
        super().release()
        held, self.held = self.held, []
        for _, route, payload in held:
            route.fulfill(json=payload)

    def upload(self, route):
        request = route.request
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
            + request.post_data_buffer
        )
        fields = {
            part.get_param("name", header="content-disposition"): part
            for part in message.iter_parts()
        }
        filename = fields["file"].get_filename()
        requested = fields["conversation_id"].get_content().strip() if "conversation_id" in fields else ""
        number = len(self.uploads) + 1
        conversation = requested or f"upload-created-chat-{number}"
        identifier = f"upload-document-{number}"
        self.uploads.append({"filename": filename, "conversation": requested, "created": conversation})
        document = {
            "id": identifier, "document_id": identifier, "file_name": filename, "scope": "personal",
            "status": "Queued for processing" if self.processing else "ready",
            "percentage_complete": 0 if self.processing else 100,
        }
        self.documents[identifier] = document
        message = attachment_message(filename, identifier, conversation)
        message["id"] = f"{conversation}_file_{number}"
        self.messages.setdefault(conversation, []).append(message)
        self.metadata_documents.setdefault(conversation, []).append({
            "document_id": identifier, "file_name": filename, "scope": {"type": "personal"},
        })
        if not any(item["id"] == conversation for item in self.conversations):
            self.conversations.append({"id": conversation, "title": f"Uploaded {filename}"})
        payload = {
            "success": True, "conversation_id": conversation, "file_message_id": message["id"],
            "workspace_document_id": identifier, "workspace_scope": "personal", "workspace_document": document,
        }
        if not self.workspace_uploads:
            message.pop("workspace_document_id")
            message["metadata"] = {"is_user_upload": True}
            self.metadata_documents[conversation].pop()
            self.documents.pop(identifier)
            payload = {
                "success": True, "conversation_id": conversation, "file_message_id": message["id"],
            }
        if self.defer_uploads:
            self.held.append(("upload", route, deepcopy(payload)))
        else:
            route.fulfill(json=payload)

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if request.method == "POST" and path == "/upload":
            self.requests.append((request.method, path))
            self.upload(route)
            return
        if request.method == "GET" and path.startswith("/api/image/"):
            route.fulfill(body=PNG, content_type="image/png")
            return
        if request.method == "GET" and path.startswith("/api/documents/") and path.rsplit("/", 1)[-1] in self.documents:
            self.requests.append((request.method, path))
            payload = deepcopy(self.documents[path.rsplit("/", 1)[-1]])
            if self.defer_details:
                self.held.append(("details", route, payload))
            else:
                route.fulfill(json=payload)
            return
        if request.method == "GET" and path == "/api/get_messages":
            conversation = parse_qs(parsed.query).get("conversation_id", [""])[0]
            if self.defer_messages.get(conversation, 0):
                self.requests.append((request.method, path))
                self.defer_messages[conversation] -= 1
                self.held.append(("messages", route, {"messages": deepcopy(self.messages.get(conversation, []))}))
                return
        if request.method == "GET" and re.fullmatch(r"/api/conversations/[^/]+/metadata", path):
            self.requests.append((request.method, path))
            conversation = unquote(path.split("/")[3])
            payload = {
                "conversation_id": conversation,
                "title": next((item["title"] for item in self.conversations if item["id"] == conversation), "New chat"),
                "linked_workspace_documents": deepcopy(self.metadata_documents.get(conversation, [])),
            }
            if self.defer_metadata.get(conversation, 0):
                self.defer_metadata[conversation] -= 1
                self.held.append(("metadata", route, payload))
            else:
                route.fulfill(json=payload)
            return
        super().handle(route)


@pytest.fixture
def attachment_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    api = AttachmentApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", lambda message: api.errors.append(message.text) if message.type == "error" else None)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def remove_buttons(page):
    return page.locator('[data-composer-editor="composer-input"]').get_by_role(
        "button", name=re.compile(r"^Remove "),
    )


def test_saved_attachment_selection_does_not_follow_navigation(attachment_ui):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    expect(remove_buttons(page)).to_have_count(1)
    before = len(api.requests)

    open_from_rail(page, OTHER_TITLE)

    expect(remove_buttons(page)).to_have_count(0)
    expect(page.get_by_text(FILENAME, exact=True)).to_have_count(0)
    assert not [
        entry for entry in api.requests[before:]
        if entry[0] == "POST" and entry[1] in {"/upload", "/api/chat/stream", "/api/v2/orchestration/plan"}
    ]


def test_restored_attachment_uses_its_filename_not_its_document_guid(attachment_ui):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)

    expect(remove_buttons(page)).to_have_count(1)
    expect(remove_buttons(page)).to_have_attribute("aria-label", f"Remove {FILENAME}")
    expect(remove_buttons(page).locator("..")).not_to_contain_text(DOCUMENT_ID)


def test_missing_historical_names_are_loaded_for_only_the_selected_document(attachment_ui):
    page, api = attachment_ui
    api.messages[ORIGIN_CHAT] = [api.messages[ORIGIN_CHAT][1]]
    api.metadata_documents[ORIGIN_CHAT] = []
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    expect(remove_buttons(page)).to_have_attribute("aria-label", f"Remove {FILENAME}")
    detail_reads = [path for method, path in api.requests if method == "GET" and path.startswith("/api/documents/")]
    assert detail_reads == [f"/api/documents/{DOCUMENT_ID}"]


def test_restored_markup_like_filename_is_inert_text(attachment_ui):
    page, api = attachment_ui
    filename = '<img src=x onerror="window.attachmentInjected = true"> ' + "long-name-" * 25 + ".txt"
    api.messages[ORIGIN_CHAT][0]["filename"] = filename
    api.messages[ORIGIN_CHAT][0]["metadata"]["workspace_attachment"]["file_name"] = filename
    api.metadata_documents[ORIGIN_CHAT][0]["file_name"] = filename
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)

    expect(remove_buttons(page)).to_have_attribute("aria-label", f"Remove {filename}")
    expect(page.locator('[data-composer-editor="composer-input"] img[src="x"]')).to_have_count(0)
    injected = page.evaluate("() => window.attachmentInjected")
    assert injected is None


def enable_uploads(page):
    page.evaluate("""() => {
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        store.setState(state => ({data: {...state.data, features: {
            ...state.data.features, enable_chat_file_uploads: true, enable_user_workspace: true
        }}}));
    }""")


def attach_file(page, filename):
    page.locator('[data-composer-editor="composer-input"] input[type="file"]').set_input_files({
        "name": filename,
        "mimeType": "image/png" if filename.endswith(".png") else "text/plain",
        "buffer": PNG if filename.endswith(".png") else b"Only the original chat owns this document.",
    })


def settle_browser(page):
    page.evaluate("async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }")


@pytest.mark.parametrize("filename", [FILENAME, "original-notes.txt"])
@pytest.mark.parametrize("workspace_backed", [False, True])
def test_unsent_upload_returns_only_to_its_original_conversation(attachment_ui, filename, workspace_backed):
    page, api = attachment_ui
    api.messages[ORIGIN_CHAT] = []
    api.metadata_documents[ORIGIN_CHAT] = []
    api.workspace_uploads = workspace_backed
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    enable_uploads(page)
    attach_file(page, filename)
    attached = page.get_by_role("list", name="Attached files", exact=True)
    expect(attached).to_contain_text("Ready")

    open_from_rail(page, OTHER_TITLE)
    expect(remove_buttons(page)).to_have_count(0)
    expect(attached).to_have_count(0)
    open_from_rail(page, ORIGIN_TITLE)

    expect(attached).to_contain_text(filename)
    expect(attached).to_contain_text("Ready")
    assert api.uploads == [{"filename": filename, "conversation": ORIGIN_CHAT, "created": ORIGIN_CHAT}]


def test_processing_upload_resumes_only_in_its_original_conversation(attachment_ui):
    page, api = attachment_ui
    api.messages[ORIGIN_CHAT] = []
    api.metadata_documents[ORIGIN_CHAT] = []
    api.processing = True
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    enable_uploads(page)
    attach_file(page, "processing-notes.txt")
    attached = page.get_by_role("list", name="Attached files", exact=True)
    expect(attached).to_contain_text("Processing")
    open_from_rail(page, OTHER_TITLE)
    expect(attached).to_have_count(0)
    api.documents["upload-document-1"].update(status="Processing complete", percentage_complete=100)
    open_from_rail(page, ORIGIN_TITLE)

    expect(attached).to_contain_text("processing-notes.txt")
    expect(attached).to_contain_text("Ready")
    assert len(api.uploads) == 1


def test_interrupted_transfer_returns_as_an_actionable_original_selection(attachment_ui):
    page, api = attachment_ui
    api.messages[ORIGIN_CHAT] = []
    api.metadata_documents[ORIGIN_CHAT] = []
    api.defer_uploads = True
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    enable_uploads(page)
    with page.expect_request(lambda request: urlsplit(request.url).path == "/upload"):
        attach_file(page, "interrupted.txt")
    with page.expect_event("requestfailed", predicate=lambda request: urlsplit(request.url).path == "/upload"):
        open_from_rail(page, OTHER_TITLE)
    expect(remove_buttons(page)).to_have_count(0)
    open_from_rail(page, ORIGIN_TITLE)
    attached = page.get_by_role("list", name="Attached files", exact=True)

    expect(attached).to_contain_text("interrupted.txt")
    expect(attached).to_contain_text("Failed")
    expect(attached.get_by_role("button", name="Retry interrupted.txt", exact=True)).to_be_visible()
    assert len(api.uploads) == 1


def test_removed_selection_stays_removed_when_old_message_metadata_returns(attachment_ui):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    page.get_by_role("button", name=f"Remove {FILENAME}", exact=True).click()
    open_from_rail(page, OTHER_TITLE)
    open_from_rail(page, ORIGIN_TITLE)

    expect(remove_buttons(page)).to_have_count(0)
    assert api.messages[ORIGIN_CHAT][1]["metadata"]["workspace_search"]["document_source_selection"] == saved_selection()


def test_each_conversation_keeps_its_own_saved_selection(attachment_ui):
    page, api = attachment_ui
    other_id = "destination-document"
    api.messages[OTHER_CHAT] = [
        attachment_message("destination-notes.txt", other_id, OTHER_CHAT),
        {
            "id": "destination-question", "conversation_id": OTHER_CHAT, "role": "user",
            "content": "Use the destination notes.",
            "metadata": {"workspace_search": {"document_source_selection": saved_selection(other_id)}},
        },
    ]
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    expect(remove_buttons(page)).to_have_attribute("aria-label", f"Remove {FILENAME}")
    open_from_rail(page, OTHER_TITLE)
    expect(remove_buttons(page)).to_have_attribute("aria-label", "Remove destination-notes.txt")
    open_from_rail(page, ORIGIN_TITLE)
    expect(remove_buttons(page)).to_have_attribute("aria-label", f"Remove {FILENAME}")


def test_search_all_does_not_follow_navigation(attachment_ui):
    page, api = attachment_ui
    api.messages[ORIGIN_CHAT][1]["metadata"]["workspace_search"]["document_source_selection"] = {
        "version": 1, "mode": "all", "sources": [],
    }
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    enable_uploads(page)
    documents = page.get_by_title("Documents", exact=True)
    expect(documents).to_have_attribute("aria-pressed", "true")
    open_from_rail(page, OTHER_TITLE)
    expect(documents).to_have_attribute("aria-pressed", "false")
    open_from_rail(page, ORIGIN_TITLE)
    expect(documents).to_have_attribute("aria-pressed", "true")


def test_account_change_cannot_restore_the_previous_accounts_sources(attachment_ui):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    expect(remove_buttons(page)).to_have_count(1)
    page.evaluate("""() => {
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        store.setState(state => ({data: {...state.data, user: {id: 'different-tester'}}}));
    }""")
    expect(remove_buttons(page)).to_have_count(0)
    open_from_rail(page, OTHER_TITLE)
    open_from_rail(page, ORIGIN_TITLE)
    expect(remove_buttons(page)).to_have_count(0)


def test_old_message_load_cannot_overwrite_a_reopened_conversation(attachment_ui):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    open_from_rail(page, OTHER_TITLE)
    api.defer_messages[ORIGIN_CHAT] = 1
    with page.expect_request(lambda request: "/api/get_messages?" in request.url and ORIGIN_CHAT in request.url):
        open_from_rail(page, ORIGIN_TITLE)
    page.wait_for_function("() => window.OrchHarness.stores.chat.useChatStore.getState().messagesLoading")
    open_from_rail(page, OTHER_TITLE)
    api.messages[ORIGIN_CHAT] = [{
        "id": "fresh-current-answer", "conversation_id": ORIGIN_CHAT,
        "role": "assistant", "content": "The latest version of the original conversation.",
    }]
    open_from_rail(page, ORIGIN_TITLE)
    current_answer = page.get_by_text("The latest version of the original conversation.", exact=True)
    expect(current_answer).to_be_visible()
    api.release_kind("messages")
    settle_browser(page)

    expect(current_answer).to_be_visible()
    first_message = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().messages[0].id")
    assert first_message == "fresh-current-answer"


def test_old_metadata_does_not_settle_the_destinations_pending_load(attachment_ui):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    api.defer_metadata[ORIGIN_CHAT] = 1
    with page.expect_request(lambda request: f"/api/conversations/{ORIGIN_CHAT}/metadata" in request.url):
        page.evaluate("(id) => { void window.OrchHarness.stores.chat.useChatStore.getState().loadMetadata(id); }", ORIGIN_CHAT)
    api.defer_metadata[OTHER_CHAT] = 1
    with page.expect_request(lambda request: f"/api/conversations/{OTHER_CHAT}/metadata" in request.url):
        open_from_rail(page, OTHER_TITLE)
    original = next(entry for entry in api.held if entry[0] == "metadata" and ORIGIN_CHAT in entry[1].request.url)
    api.held.remove(original)
    original[1].fulfill(json=original[2])
    settle_browser(page)

    metadata_loading = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().metadataLoading")
    assert metadata_loading is True
    expect(remove_buttons(page)).to_have_count(0)
    api.release_kind("metadata")
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().metadataLoading")


def test_late_filename_lookup_does_not_readd_a_removed_source_or_follow_navigation(attachment_ui):
    page, api = attachment_ui
    api.messages[ORIGIN_CHAT] = [api.messages[ORIGIN_CHAT][1]]
    api.metadata_documents[ORIGIN_CHAT] = []
    api.defer_details = True
    with page.expect_request(lambda request: request.url.endswith(f"/api/documents/{DOCUMENT_ID}")):
        mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    expect(remove_buttons(page)).to_have_attribute("aria-label", "Remove Document details unavailable")
    remove_buttons(page).click()
    open_from_rail(page, OTHER_TITLE)
    api.release_kind("details")
    settle_browser(page)
    expect(remove_buttons(page)).to_have_count(0)
    open_from_rail(page, ORIGIN_TITLE)
    expect(remove_buttons(page)).to_have_count(0)


def test_successive_null_id_new_chats_do_not_reuse_an_old_upload(attachment_ui):
    page, api = attachment_ui
    mount(page, api, conversation=None, orchestration=False)
    enable_uploads(page)
    api.defer_uploads = True
    with page.expect_request(lambda request: urlsplit(request.url).path == "/upload"):
        attach_file(page, "old-draft.txt")
    with page.expect_event("requestfailed", predicate=lambda request: urlsplit(request.url).path == "/upload"):
        click_new_chat(page)
    click_new_chat(page)
    api.defer_uploads = False
    attach_file(page, "fresh-draft.txt")
    attached = page.get_by_role("list", name="Attached files", exact=True)
    expect(attached).to_contain_text("Ready")
    api.release_kind("upload")
    settle_browser(page)

    expect(remove_buttons(page)).to_have_count(1)
    expect(attached).to_contain_text("fresh-draft.txt")
    expect(attached).not_to_contain_text("old-draft.txt")
    assert [entry["conversation"] for entry in api.uploads] == ["", ""]
    active = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId")
    assert active is None


@pytest.mark.parametrize("return_before_rejection", [False, True])
def test_aborted_send_recovers_only_the_original_draft(attachment_ui, return_before_rejection):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=False)
    expect(remove_buttons(page)).to_have_attribute("aria-label", f"Remove {FILENAME}")
    draft(page).fill("Keep this question and its file in the original chat.")
    page.evaluate("""({other, original, returnBeforeRejection}) => {
        const railButton = title => [...document.querySelectorAll('nav[aria-label="Primary"] button')]
            .find(button => button.textContent.trim() === title);
        document.querySelector('button[aria-label="Send message"]').click();
        railButton(other).click();
        if (returnBeforeRejection) railButton(original).click();
    }""", {"other": OTHER_TITLE, "original": ORIGIN_TITLE, "returnBeforeRejection": return_before_rejection})
    settle_browser(page)
    if not return_before_rejection:
        expect(remove_buttons(page)).to_have_count(0)
        expect(draft(page)).to_have_value("")
        open_from_rail(page, ORIGIN_TITLE)
    expect(remove_buttons(page)).to_have_attribute("aria-label", f"Remove {FILENAME}")
    if return_before_rejection:
        expect(draft(page)).to_have_value("Keep this question and its file in the original chat.")


def capture_sends(page):
    page.evaluate("""() => {
        window.attachmentSends = [];
        const fetch = window.fetch.bind(window);
        window.fetch = (input, init = {}) => {
            const url = new URL(input instanceof Request ? input.url : String(input), location.href);
            if (['/api/chat/stream', '/api/v2/orchestration/plan'].includes(url.pathname)) {
                window.attachmentSends.push(JSON.parse(init.body));
            }
            return fetch(input, init);
        };
    }""")


@pytest.mark.parametrize("orchestration", [False, True])
def test_destination_request_does_not_include_the_original_attachment(attachment_ui, orchestration):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=orchestration)
    expect(remove_buttons(page)).to_have_count(1)
    open_from_rail(page, OTHER_TITLE)
    expect(remove_buttons(page)).to_have_count(0)
    capture_sends(page)
    draft(page).fill("Answer this unrelated question without any attached files.")
    page.get_by_role("button", name="Send message", exact=True).click()
    page.wait_for_function("() => window.attachmentSends.length === 1")
    payload = page.evaluate("() => window.attachmentSends[0]")

    assert payload["conversation_id"] == OTHER_CHAT
    assert DOCUMENT_ID not in json.dumps(payload)
    assert not payload.get("image_references")
    assert not payload.get("document_source_selection")
    assert not payload.get("selected_document_ids")


@pytest.mark.parametrize("orchestration", [False, True])
def test_navigation_and_send_in_one_event_cannot_send_a_stale_attachment(attachment_ui, orchestration):
    page, api = attachment_ui
    mount(page, api, conversation=ORIGIN_CHAT, orchestration=orchestration)
    expect(remove_buttons(page)).to_have_count(1)
    capture_sends(page)
    draft(page).fill("Send only after the new conversation owns this draft.")
    page.evaluate("""title => {
        [...document.querySelectorAll('nav[aria-label="Primary"] button')]
            .find(button => button.textContent.trim() === title).click();
        document.querySelector('button[aria-label="Send message"]').click();
    }""", OTHER_TITLE)
    settle_browser(page)
    expect(remove_buttons(page)).to_have_count(0)
    sent = page.evaluate("() => window.attachmentSends")
    if not sent:
        page.get_by_role("button", name="Send message", exact=True).click()
        page.wait_for_function("() => window.attachmentSends.length === 1")
        sent = page.evaluate("() => window.attachmentSends")

    assert len(sent) == 1
    assert sent[0]["conversation_id"] == OTHER_CHAT
    assert DOCUMENT_ID not in json.dumps(sent[0])


@pytest.mark.parametrize("orchestration", [False, True])
def test_new_upload_batch_adopts_only_its_created_conversation_and_clears_on_send(attachment_ui, orchestration):
    page, api = attachment_ui
    mount(page, api, conversation=None, orchestration=orchestration)
    enable_uploads(page)
    capture_sends(page)
    page.locator('[data-composer-editor="composer-input"] input[type="file"]').set_input_files([
        {"name": "first.txt", "mimeType": "text/plain", "buffer": b"First source"},
        {"name": "second.txt", "mimeType": "text/plain", "buffer": b"Second source"},
    ])
    attached = page.get_by_role("list", name="Attached files", exact=True)
    expect(attached.get_by_text("Ready", exact=True)).to_have_count(2)
    draft(page).fill("Compare only the two files uploaded into this chat.")
    page.get_by_role("button", name="Send message", exact=True).click()
    page.wait_for_function("() => window.attachmentSends.length === 1")
    payload = page.evaluate("() => window.attachmentSends[0]")

    assert [entry["conversation"] for entry in api.uploads] == ["", "upload-created-chat-1"]
    assert payload["conversation_id"] == "upload-created-chat-1"
    assert [item["id"] for item in payload["document_source_selection"]["sources"]] == [
        "upload-document-1", "upload-document-2",
    ]
    expect(draft(page)).to_have_value("")
    expect(attached).to_have_count(0)
    expect(remove_buttons(page)).to_have_count(0)
