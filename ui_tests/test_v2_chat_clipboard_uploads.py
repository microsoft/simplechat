# test_v2_chat_clipboard_uploads.py
"""
Browser regressions for React V2 clipboard and dropped chat attachments.
Version: 0.261.483
Implemented in: 0.261.368

The real composer, controlled editor, upload queue, and production styles run in
Chromium. Only HTTP boundaries are mocked. The shared connection fixtures support
Azure Playwright with DefaultAzureCredential or local Chromium. Clipboard fixtures
contain fake data, not the user's clipboard or production documents.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_chat_clipboard_uploads.py -q
"""

import base64
import re
from email import policy
from email.parser import BytesParser
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_chat_image_uploads import SIZED_PNG
from test_v2_image_reference_generation import ImageReferenceApi
from test_v2_orchestration_plan_editor import (
    HARNESS,
    ORIGIN,
    connect_options,  # noqa: F401
    editor_assets,  # noqa: F401
    editor_browser,  # noqa: F401
)


pytestmark = pytest.mark.ui
CONVERSATION = "clipboard-chat"
NEW_CONVERSATION = "clipboard-created-chat"


class ClipboardApi(ImageReferenceApi):
    """Retain actual multipart file bytes, identity, and request ordering."""

    def __init__(self, assets):
        super().__init__(assets)
        self.uploads = []
        self.fail_next = False
        self.defer_uploads = False
        self.pending = []
        self.metadata_failures = 0

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        if (
            f"{parsed.scheme}://{parsed.netloc}" == ORIGIN
            and request.method == "GET"
            and parsed.path.startswith("/api/conversations/")
            and parsed.path.endswith("/metadata")
        ):
            conversation = parsed.path.split("/")[3]
            self.requests.append({"method": request.method, "path": parsed.path})
            if self.metadata_failures:
                self.metadata_failures -= 1
                route.fulfill(status=503, json={"error": "Conversation unavailable"})
            else:
                route.fulfill(json={
                    "conversation_id": conversation,
                    "title": "Clipboard chat",
                    "chat_type": "personal_single_user",
                })
            return
        if (
            f"{parsed.scheme}://{parsed.netloc}" != ORIGIN
            or request.method != "POST"
            or parsed.path != "/upload"
        ):
            super().handle(route)
            return

        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
            + request.post_data_buffer
        )
        fields = {
            part.get_param("name", header="content-disposition"): part
            for part in message.iter_parts()
        }
        file = fields["file"]
        conversation = (
            fields["conversation_id"].get_content().strip()
            if "conversation_id" in fields else ""
        )
        self.uploads.append({
            "name": file.get_filename(),
            "mime": file.get_content_type(),
            "body": file.get_payload(decode=True),
            "conversation": conversation,
            "group_ids": [
                part.get_content().strip()
                for part in message.iter_parts()
                if part.get_param("name", header="content-disposition") == "upload_scope_group_ids"
            ],
        })
        if self.defer_uploads:
            self.pending.append(route)
            return
        if self.fail_next:
            self.fail_next = False
            route.fulfill(status=503, json={"error": "Upload failed. Please retry."})
            return
        number = len(self.uploads)
        route.fulfill(json={
            "success": True,
            "conversation_id": conversation or NEW_CONVERSATION,
            "file_message_id": f"clipboard-message-{number}",
            "workspace_scope": "personal",
            "workspace_document_id": f"clipboard-document-{number}",
            "workspace_document": {
                "document_id": f"clipboard-document-{number}",
                "file_name": file.get_filename(),
                "scope": "personal",
                "status": "ready",
                "percentage_complete": 100,
            },
        })


@pytest.fixture
def clipboard_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(
        viewport={"width": 1280, "height": 860},
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    api = ClipboardApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, api.unexpected
        assert not api.errors, api.errors


def mount_composer(
    page, api, *, conversation=CONVERSATION, uploads_enabled=True,
    max_size_mb=25, editor=None, active_group_id=None, metadata=None,
):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.368',
                settings: { max_file_size_mb: spec.maxSizeMb },
                branding: { app_title: 'SimpleChat' },
                features: {
                    enable_user_workspace: true,
                    enable_chat_file_uploads: spec.uploadsEnabled,
                    enable_image_generation: true,
                },
                capabilities: { image_edit: {
                    enabled: true, editing: true, masking: true, mode: 'masked',
                    model_name: 'gpt-image', max_reference_images: 4, reason: '',
                } },
                user: { id: 'clipboard-user', display_name: 'Clipboard Tester' },
                scope: { active_group_id: spec.activeGroupId, groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: [], prompts: [] },
                chat_uploads: { personal: ['txt', 'pdf', 'htm', 'png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff'],
                    group: ['txt', 'pdf', 'htm', 'png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff', 'xsd'] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation,
                activeConversationKind: 'personal',
                messagesLoading: false, messagesError: null, messages: [],
                streaming: false, streamingContent: '', streamError: null, thoughts: [],
                metadata: spec.conversation ? (spec.metadata ?? {
                    conversation_id: spec.conversation, title: 'Clipboard chat',
                    chat_type: 'personal_single_user',
                }) : null,
                metadataLoading: false, metadataError: null,
                conversations: spec.conversation
                    ? [{ id: spec.conversation, title: 'Clipboard chat' }] : [],
            });
            if (spec.editor === null) {
                H.mount('test-root', 'Composer');
            } else {
                let draft = {
                    text: '', contextItems: [], attachedPrompt: null,
                    promptValues: {}, uploads: [],
                };
                const render = () => H.mount('test-root', 'ComposerEditor', {
                    id: 'clipboard-editor', label: 'Message',
                    conversationId: spec.conversation, ...spec.editor,
                    draft,
                    onChange: (update) => {
                        draft = typeof update === 'function' ? update(draft) : update;
                        render();
                    },
                });
                render();
            }
        }""",
        {
            "conversation": conversation,
            "uploadsEnabled": uploads_enabled,
            "maxSizeMb": max_size_mb,
            "editor": editor,
            "activeGroupId": active_group_id,
            "metadata": metadata,
        },
    )
    return page.get_by_role("textbox", name="Message", exact=True)


def test_new_conversation_and_metadata_invalidation_restore_uploads(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api, conversation=None)
    page.evaluate(
        """(conversation) => window.OrchHarness.stores.chat.useChatStore.setState({
            activeConversationId: conversation, activeConversationKind: 'personal',
            metadata: null, metadataLoading: false, metadataError: null,
        })""",
        NEW_CONVERSATION,
    )
    expect(page.locator('input[type="file"]')).to_be_enabled()
    transfer_files(editor, [file_spec("report.pdf", "application/pdf", b"pdf")], source="drop")
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert api.uploads[0]["conversation"] == NEW_CONVERSATION

    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({ metadata: null })")
    page.wait_for_function(
        "(id) => window.OrchHarness.stores.chat.useChatStore.getState().metadata?.conversation_id === id",
        arg=NEW_CONVERSATION,
    )
    expect(page.locator('input[type="file"]')).to_be_enabled()
    assert len([request for request in api.requests if request["path"].endswith("/metadata")]) == 2


def test_sending_files_from_a_new_chat_keeps_the_next_composer_available(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api, conversation=None)
    transfer_files(editor, [
        file_spec("page.htm", "text/html", b"<p>Example</p>"),
        file_spec("report.pdf", "application/pdf", b"pdf"),
    ], source="drop")
    expect(page.get_by_role("list", name="Attached files").get_by_text("Ready", exact=True)).to_have_count(2)
    editor.fill("Summarize these files")
    editor.press("Enter")

    expect(editor).to_have_value("")
    expect(page.locator('input[type="file"]')).to_be_enabled()
    expect(page.get_by_text("Chat upload formats are unavailable.", exact=False)).to_have_count(0)
    assert [upload["conversation"] for upload in api.uploads] == ["", NEW_CONVERSATION]
    assert any(request["path"].endswith("/metadata") for request in api.requests)


def test_failed_conversation_metadata_can_be_retried(clipboard_ui):
    page, api = clipboard_ui
    api.metadata_failures = 1
    mount_composer(page, api)
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({ metadata: null })")
    expect(page.get_by_text("Could not load conversation upload options.")).to_be_visible()
    expect(page.locator('input[type="file"]')).to_be_disabled()
    page.get_by_role("button", name="Try again").click()
    expect(page.locator('input[type="file"]')).to_be_enabled()


def file_spec(name="screenshot.png", mime="image/png", body=SIZED_PNG):
    return {
        "name": name,
        "type": mime,
        "body": base64.b64encode(body).decode("ascii"),
    }


def transfer_files(editor, files, *, source="paste", exposure="both", text=""):
    return editor.evaluate(
        """async (element, spec) => {
            const transfer = new DataTransfer();
            if (spec.text) {
                transfer.setData('text/plain', spec.text);
            }
            for (const file of spec.files) {
                transfer.items.add(new File([
                    Uint8Array.from(atob(file.body), (byte) => byte.charCodeAt(0)),
                ], file.name, { type: file.type, lastModified: 1234 }));
            }
            const event = new Event(spec.source, { bubbles: true, cancelable: true });
            const payload = {
                items: spec.exposure === 'files' ? [] : Array.from(transfer.items),
                files: spec.exposure === 'items' ? [] : Array.from(transfer.files),
                types: Array.from(transfer.types),
                getData: (format) => transfer.getData(format),
            };
            Object.defineProperty(event,
                spec.source === 'paste' ? 'clipboardData' : 'dataTransfer',
                { value: payload });
            element.dispatchEvent(event);
            await new Promise(requestAnimationFrame);
            return event.defaultPrevented;
        }""",
        {"files": files, "source": source, "exposure": exposure, "text": text},
    )


def test_actual_browser_clipboard_image_attaches_without_image_mode(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    expect(page.get_by_role("button", name="Image", exact=True)).to_have_attribute(
        "aria-pressed", "false",
    )
    page.evaluate(
        """async (image) => {
            const bytes = Uint8Array.from(atob(image), (byte) => byte.charCodeAt(0));
            await navigator.clipboard.write([
                new ClipboardItem({ 'image/png': new Blob([bytes], { type: 'image/png' }) }),
            ]);
        }""",
        base64.b64encode(SIZED_PNG).decode("ascii"),
    )
    editor.focus()
    editor.press("Control+V")

    attached = page.get_by_role("list", name="Attached files")
    expect(attached).to_contain_text("Ready")
    expect(attached.locator("img")).to_be_visible()
    assert len(api.uploads) == 1
    assert api.uploads[0]["mime"] == "image/png"
    assert api.uploads[0]["name"].endswith(".png")
    assert api.uploads[0]["conversation"] == CONVERSATION
    expect(editor).to_have_value("")


@pytest.mark.parametrize("exposure", ["items", "files", "both"])
def test_named_document_paste_uses_browser_files_once(clipboard_ui, exposure):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    prevented = transfer_files(
        editor, [file_spec("report.pdf", "application/pdf", b"fake PDF")],
        exposure=exposure,
    )
    assert prevented
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert len(api.uploads) == 1
    assert api.uploads[0]["name"] == "report.pdf"
    assert api.uploads[0]["body"] == b"fake PDF"


def test_nameless_screenshot_gets_a_supported_filename(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    transfer_files(editor, [file_spec("")])

    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert len(api.uploads) == 1
    assert api.uploads[0]["name"].startswith("pasted_file_")
    assert api.uploads[0]["name"].endswith(".png")
    assert api.uploads[0]["mime"] == "image/png"
    assert api.uploads[0]["body"] == SIZED_PNG


def test_multiple_new_chat_files_reuse_first_upload_conversation(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api, conversation=None)
    transfer_files(editor, [
        file_spec("first.txt", "text/plain", b"first"),
        file_spec("second.txt", "text/plain", b"second"),
    ])

    attached = page.get_by_role("list", name="Attached files")
    expect(attached.get_by_text("Ready", exact=True)).to_have_count(2)
    assert [upload["name"] for upload in api.uploads] == ["first.txt", "second.txt"]
    assert [upload["conversation"] for upload in api.uploads] == ["", NEW_CONVERSATION]


@pytest.mark.parametrize("source", ["picker", "drop"])
def test_new_chat_upload_ignores_active_group(clipboard_ui, source):
    page, api = clipboard_ui
    editor = mount_composer(page, api, conversation=None, active_group_id="active-group")
    file_input = page.locator('input[type="file"]')
    expect(file_input).not_to_have_attribute("accept", re.compile(r"\.xsd"))
    if source == "picker":
        file_input.set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"notes"})
    else:
        transfer_files(editor, [file_spec("notes.txt", "text/plain", b"notes")], source="drop")
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert api.uploads[0]["conversation"] == ""
    assert api.uploads[0]["group_ids"] == []


def test_group_locked_chat_uses_group_formats_without_active_group(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(
        page, api, active_group_id="different-group",
        metadata={
            "conversation_id": CONVERSATION,
            "title": "Group chat",
            "chat_type": "group-single-user",
            "scope_locked": True,
            "locked_contexts": [{"scope": "group", "id": "locked-group"}],
        },
    )
    expect(page.locator('input[type="file"]')).to_have_attribute("accept", re.compile(r"\.xsd"))
    transfer_files(editor, [file_spec("notes.txt", "text/plain", b"notes")], source="drop")
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert api.uploads[0]["conversation"] == CONVERSATION
    assert api.uploads[0]["group_ids"] == []


def test_retry_new_chat_upload_ignores_active_group(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api, conversation=None, active_group_id="active-group")
    api.fail_next = True
    transfer_files(editor, [file_spec("notes.txt", "text/plain", b"notes")])
    expect(page.get_by_role("alert")).to_contain_text("Upload failed. Please retry.")
    page.get_by_role("button", name="Retry notes.txt", exact=True).click()
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert [upload["group_ids"] for upload in api.uploads] == [[], []]


def test_real_text_paste_preserves_selection_before_and_after_an_image(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    editor.fill("alpha beta omega")
    editor.evaluate("(element) => element.setSelectionRange(6, 10)")
    page.evaluate("() => navigator.clipboard.writeText('first')")
    editor.press("Control+V")
    expect(editor).to_have_value("alpha first omega")
    assert not api.uploads

    transfer_files(editor, [file_spec()])
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    editor.focus()
    editor.evaluate("(element) => element.setSelectionRange(6, 11)")
    page.evaluate("() => navigator.clipboard.writeText('second')")
    editor.press("Control+V")

    expect(editor).to_have_value("alpha second omega")
    caret = editor.evaluate("(element) => [element.selectionStart, element.selectionEnd]")
    assert caret == [12, 12]
    assert len(api.uploads) == 1


def test_text_with_an_unnamed_auxiliary_image_keeps_native_paste(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    editor.fill("Keep this draft")
    prevented = transfer_files(editor, [file_spec("")], text="ordinary clipboard text")
    assert not prevented
    expect(editor).to_have_value("Keep this draft")
    expect(page.get_by_role("list", name="Attached files")).to_have_count(0)
    assert not api.uploads


def test_file_drop_attaches_but_text_drop_keeps_native_behavior(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    editor.fill("Explain this")
    accepted = transfer_files(editor, [file_spec()], source="dragover")
    assert accepted
    prevented = transfer_files(
        editor, [file_spec("notes.txt", "text/plain", b"notes")], source="drop",
    )
    assert prevented
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert len(api.uploads) == 1
    prevented = transfer_files(editor, [], source="drop", text="dropped text")
    assert not prevented
    expect(editor).to_have_value("Explain this")
    assert len(api.uploads) == 1
    page.evaluate(
        """() => {
            const source = document.createElement('div');
            source.id = 'clipboard-text-source';
            source.draggable = true;
            source.textContent = 'Drag this text';
            Object.assign(source.style, {
                position: 'fixed', top: '8px', right: '8px', zIndex: '1000',
            });
            source.addEventListener('dragstart', (event) => {
                event.dataTransfer.setData('text/plain', 'dropped text');
            });
            document.body.append(source);
        }"""
    )
    page.locator("#clipboard-text-source").drag_to(editor)
    expect(editor).to_have_value(re.compile("dropped text"))
    expect(editor).to_have_value(re.compile("Explain this"))
    assert len(api.uploads) == 1


@pytest.mark.parametrize("editor_options,enabled", [
    ({}, False),
    ({"uploadsDisabled": True}, True),
    ({"restricted": True}, True),
    ({"disabled": True}, True),
])
def test_transfer_cannot_bypass_upload_eligibility(clipboard_ui, editor_options, enabled):
    page, api = clipboard_ui
    editor = mount_composer(page, api, editor=editor_options, uploads_enabled=enabled)
    for source in ("paste", "dragover", "drop"):
        transfer_files(editor, [file_spec()], source=source)
    expect(page.get_by_role("list", name="Attached files")).to_have_count(0)
    assert not api.uploads


@pytest.mark.parametrize("name,mime,limit,error", [
    ("program.exe", "image/png", 25, "This file type is not supported"),
    ("large.pdf", "application/pdf", 0.00001, "MB upload limit"),
])
def test_invalid_pasted_file_has_a_visible_error_without_uploading(
    clipboard_ui, name, mime, limit, error,
):
    page, api = clipboard_ui
    editor = mount_composer(page, api, max_size_mb=limit)
    transfer_files(editor, [file_spec(name, mime)])
    expect(page.get_by_role("alert")).to_contain_text(error)
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Failed")
    assert not api.uploads


def test_single_file_inline_editor_keeps_its_limit(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api, editor={"multipleFiles": False})
    transfer_files(editor, [
        file_spec("first.txt", "text/plain", b"first"),
        file_spec("second.txt", "text/plain", b"second"),
    ])
    attached = page.get_by_role("list", name="Attached files")
    expect(attached).to_contain_text("Ready")
    expect(attached.locator("li")).to_have_count(1)
    assert [upload["name"] for upload in api.uploads] == ["first.txt"]


@pytest.mark.parametrize("source", ["paste", "drop"])
def test_image_mode_retains_reference_format_restrictions(clipboard_ui, source):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    page.get_by_role("button", name="Image", exact=True).click()
    transfer_files(editor, [file_spec("report.pdf", "application/pdf", b"PDF")], source=source)
    expect(page.get_by_role("alert")).to_contain_text("Image mode can only use")
    assert not api.uploads
    page.get_by_role("button", name="Remove report.pdf", exact=True).click()
    transfer_files(editor, [file_spec("portrait.heic", "image/heic")], source=source)
    expect(page.get_by_role("alert")).to_contain_text("HEIC images can't be used")
    assert not api.uploads
    page.get_by_role("button", name="Remove portrait.heic", exact=True).click()
    transfer_files(editor, [file_spec()], source=source)
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    expect(page.get_by_text("1 / 4 reference images")).to_be_visible()
    assert len(api.uploads) == 1


def test_failed_paste_can_be_retried_and_removed_without_losing_text(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    editor.fill("Keep my question")
    api.fail_next = True
    transfer_files(editor, [file_spec("notes.txt", "text/plain", b"notes")])
    expect(page.get_by_role("alert")).to_contain_text("Upload failed. Please retry.")
    page.get_by_role("button", name="Retry notes.txt", exact=True).click()
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Ready")
    assert len(api.uploads) == 2
    page.get_by_role("button", name="Remove notes.txt", exact=True).click()
    expect(page.get_by_role("list", name="Attached files")).to_have_count(0)
    expect(editor).to_have_value("Keep my question")


def test_switching_conversations_cancels_the_original_paste(clipboard_ui):
    page, api = clipboard_ui
    editor = mount_composer(page, api)
    api.defer_uploads = True
    with page.expect_request(lambda request: urlsplit(request.url).path == "/upload"):
        transfer_files(editor, [file_spec("old.txt", "text/plain", b"old")])
    expect(page.get_by_role("list", name="Attached files")).to_contain_text("Uploading")
    with page.expect_event(
        "requestfailed", predicate=lambda request: urlsplit(request.url).path == "/upload",
    ):
        page.evaluate(
            """() => window.OrchHarness.stores.chat.useChatStore.setState({
                activeConversationId: 'other-clipboard-chat',
                conversations: [{ id: 'other-clipboard-chat', title: 'Other chat' }],
                messages: [],
            })"""
        )
    expect(page.get_by_role("list", name="Attached files")).to_have_count(0)
    api.defer_uploads = False
    transfer_files(editor, [file_spec("new.txt", "text/plain", b"new")])
    attached = page.get_by_role("list", name="Attached files")
    expect(attached).to_contain_text("Ready")
    expect(attached).not_to_contain_text("old.txt")
    assert [upload["conversation"] for upload in api.uploads] == [
        CONVERSATION, "other-clipboard-chat",
    ]
