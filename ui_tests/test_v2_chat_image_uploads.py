# test_v2_chat_image_uploads.py
"""
UI coverage for v2 inline chat upload image previews.
Version: 0.261.210
Implemented in: 0.261.192; 0.261.210

This test ensures workspace-backed uploaded image messages render as inline image cards,
fall back safely when previews are unavailable, and keep non-image uploads as file chips.
Since 0.261.210 it also ensures the card is sized to the image like a generated image, its
actions are revealed on hover, Show sources and the file preview show what ingestion
extracted, and a cited image shows its extracted passage.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_chat_image_uploads.py -q
"""

import base64
import json
import re
import struct
import zlib
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
CONVERSATION = "image-upload-chat"


def solid_png(width, height, rgb=(96, 96, 96)):
    """A real PNG of a known size, so layout can be measured against the image itself."""
    row = b"\x00" + bytes(rgb) * width

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b"")
    )


SIZED_PNG = solid_png(320, 200)
VISION_DESCRIPTION = "A grayscale image of a large indoor lab with a mostly empty tiled floor."
WORKSPACE_EXTRACTION = {
    "file_content": (
        "=== AI Vision Analysis ===\nModel: gpt-5.4\n\n"
        f"Description: {VISION_DESCRIPTION}"
    ),
    "filename": "lab.png",
    "is_table": False,
    "file_content_source": "workspace",
    "indexed_text_available": True,
    "workspace_document": {
        "document_id": "doc-lab",
        "title": "AI Vision Analysis of Indoor Environment",
        "abstract": "",
        "keywords": [],
        "status": "Processing complete - final metadata extracted",
        "percentage_complete": 100,
        "number_of_pages": 1,
        "extraction_engine": "document_intelligence",
        "extraction_engine_reason": (
            "Content Understanding returned no content, so Document Intelligence Layout was used"
        ),
        "indexed_chunk_count": 1,
        "vision_analysis": {
            "model": "gpt-5.4",
            "description": VISION_DESCRIPTION,
            "objects": ["checkerboard calibration panels", "equipment rack"],
            "text": "",
            "analysis": "Likely a robotics or computer vision test space.",
        },
    },
}


def file_message(message_id, filename, document_id, **overrides):
    return {
        "id": message_id,
        "conversation_id": CONVERSATION,
        "role": "file",
        "content": "",
        "filename": filename,
        "workspace_document_id": document_id,
        "sender": {"user_id": "ui-user", "display_name": "Upload Tester"},
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
        **overrides,
    }


class ChatImageApi:
    def __init__(self, assets):
        self.assets = assets
        self.requests = []
        self.unexpected = []
        self.errors = []
        self.preview_hits = {}
        # file_id -> (status, payload) for /api/get_file_content.
        self.file_content = {}
        self.file_content_requests = []
        self.cited_text = ""

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        self.requests.append({"path": path, "query": parsed.query, "method": request.method})
        if request.method == "POST" and path == "/api/get_file_content":
            body = json.loads(request.post_data or "{}")
            self.file_content_requests.append((body.get("conversation_id"), body.get("file_id")))
            status, payload = self.file_content.get(
                body.get("file_id"), (404, {"error": "File content not found"}),
            )
            route.fulfill(status=status, json=payload)
            return
        if request.method == "GET" and re.fullmatch(r"/api/message/[^/]+/metadata", path):
            route.fulfill(json={"message_details": {"message_id": path.split("/")[3]}})
            return
        if request.method == "GET" and path == "/api/enhanced_citations/document_metadata":
            route.fulfill(json={"document_id": "doc-lab", "file_name": "lab.png", "enhanced_citations": True})
            return
        if request.method == "GET" and path == "/api/enhanced_citations/image":
            route.fulfill(status=200, body=SIZED_PNG, content_type="image/png")
            return
        if request.method == "POST" and path == "/api/get_citation":
            route.fulfill(json={"cited_text": self.cited_text, "file_name": "lab.png", "page_number": 1})
            return
        if request.method == "POST" and path == "/upload":
            route.fulfill(json={
                "success": True,
                "conversation_id": CONVERSATION,
                "file_message_id": "local-preview-message",
                "workspace_scope": "personal",
                "workspace_document_id": "doc-local-preview",
                "workspace_document": {
                    "document_id": "doc-local-preview",
                    "file_name": "composer.png",
                    "scope": "personal",
                    "status": "ready",
                    "percentage_complete": 100,
                },
            })
            return
        if request.method == "GET" and path in {"/api/get_messages", "/api/v2/chat/messages"}:
            route.fulfill(json={"messages": []})
            return
        if path.startswith("/api/image/"):
            message_id = unquote(path.rsplit("/", 1)[-1])
            query = parse_qs(parsed.query)
            variant = query.get("variant", [""])[0]
            self.preview_hits[(message_id, variant)] = self.preview_hits.get((message_id, variant), 0) + 1
            if message_id == "processing-image" and variant == "thumbnail" and self.preview_hits[(message_id, variant)] == 1:
                route.fulfill(status=409, json={"error": "Under review", "error_code": "document_under_review"})
                return
            if message_id == "unsupported-image":
                route.fulfill(status=415, json={"error": "Not an image", "error_code": "not_an_image"})
                return
            if message_id in {"heic-image", "legacy-upload"}:
                route.fulfill(status=200, body=b"not-an-image", content_type="image/heic")
                return
            if message_id == "sized-image":
                route.fulfill(status=200, body=SIZED_PNG, content_type="image/png")
                return
            route.fulfill(status=200, body=PNG, content_type="image/png")
            return
        if path == "/api/documents/doc-processing":
            route.fulfill(json={"document_id": "doc-processing", "status": "ready", "percentage_complete": 100})
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})

    def calls(self, message_id, variant):
        return self.preview_hits.get((message_id, variant), 0)


@pytest.fixture
def image_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 820})
    page = context.new_page()
    api = ChatImageApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not api.errors, api.errors


def mount_messages(page, api, messages, features=None):
    if page.url != ORIGIN + HARNESS:
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
                version: '0.261.192',
                settings: {},
                branding: { app_title: 'SimpleChat' },
                features: spec.features,
                user: { id: 'ui-user', display_name: 'Upload Tester' },
                scope: { groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation,
                activeConversationKind: 'personal',
                messagesLoading: false,
                messagesError: null,
                streaming: false,
                streamingContent: '',
                streamError: null,
                thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Image upload chat' }],
                messages: spec.messages,
            });
            H.mount('test-root', 'MessageList');
        }""",
        {
            "conversation": CONVERSATION,
            "messages": messages,
            "features": features or {"enable_user_workspace": True, "enable_image_generation": True},
        },
    )


def mount_composer(page, api):
    if page.url != ORIGIN + HARNESS:
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
                version: '0.261.192',
                settings: { max_file_size_mb: 25 },
                branding: { app_title: 'SimpleChat' },
                features: { enable_user_workspace: true, enable_chat_file_uploads: true },
                user: { id: 'ui-user', display_name: 'Upload Tester' },
                scope: { groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation,
                activeConversationKind: 'personal',
                messagesLoading: false,
                messagesError: null,
                streaming: false,
                streamingContent: '',
                streamError: null,
                thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Image upload chat' }],
                messages: [],
            });
            H.mount('test-root', 'PromptExperience');
        }""",
        {"conversation": CONVERSATION},
    )


def test_workspace_image_upload_renders_card_and_lightbox(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("inline-image", "house.png", "doc-house")])

    card = page.get_by_role("button", name="View the full-size image: house.png")
    expect(card).to_be_visible()
    expect(card.locator("img[alt='house.png']")).to_be_visible()
    card.click()

    expect(page.get_by_role("dialog", name="Image")).to_be_visible()
    expect(page.get_by_role("heading", name="house.png")).to_be_visible()
    expect(page.get_by_role("dialog", name="Image").locator("img[alt='house.png']")).to_be_visible()
    assert api.calls("inline-image", "display") > 0


def test_processing_workspace_image_retries_until_preview_is_ready(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("processing-image", "queued.jpg", "doc-processing")])

    expect(page.get_by_role("button", name="View the full-size image: queued.jpg")).to_be_visible()
    expect(page.locator("img[alt='queued.jpg']")).to_be_visible()
    assert api.calls("processing-image", "thumbnail") >= 2


def test_unsupported_preview_falls_back_to_file_chip(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("unsupported-image", "scan.jpg", "doc-scan")])

    expect(page.get_by_role("button", name=re.compile("View the full-size image"))).to_have_count(0)
    expect(page.get_by_role("button", name="scan.jpg")).to_be_visible()
    expect(page.get_by_text("Preview is unavailable.")).to_be_visible()


def test_heic_decode_failure_shows_browser_hint(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("heic-image", "portrait.heic", "doc-heic")])

    expect(page.get_by_text("Preview isn't available in this browser. Convert to JPG or PNG to preview it.")).to_be_visible()
    expect(page.get_by_role("button", name="portrait.heic")).to_be_visible()


def test_non_image_upload_stays_as_file_chip(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("pdf-file", "report.pdf", "doc-pdf")])

    expect(page.get_by_role("button", name="report.pdf")).to_be_visible()
    expect(page.locator("img[alt='report.pdf']")).to_have_count(0)
    assert api.calls("pdf-file", "thumbnail") == 0


def test_composer_upload_chip_shows_local_browser_image_preview(image_ui):
    page, api = image_ui
    mount_composer(page, api)

    page.locator("input[type='file']").set_input_files({
        "name": "composer.png",
        "mimeType": "image/png",
        "buffer": PNG,
    })

    attached = page.get_by_role("list", name="Attached files")
    expect(attached).to_be_visible()
    expect(attached.locator("img[alt='']")).to_be_visible()
    expect(attached).to_contain_text("composer.png")
    expect(attached).to_contain_text("Ready")


def test_own_uploaded_image_message_is_right_aligned(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("own-image", "mine.png", "doc-mine")])

    expect(page.locator("[id='message-own-image']")).to_have_class(re.compile("items-end"))
    expect(page.get_by_role("button", name="View the full-size image: mine.png")).to_be_visible()


def test_legacy_user_upload_image_error_uses_file_style_fallback(image_ui):
    page, api = image_ui
    mount_messages(page, api, [{
        "id": "legacy-upload",
        "conversation_id": CONVERSATION,
        "role": "image",
        "content": "/api/image/legacy-upload",
        "filename": "legacy.heif",
        "prompt": "",
        "sender": {"user_id": "ui-user", "display_name": "Upload Tester"},
        "metadata": {"is_user_upload": True},
    }])

    expect(page.get_by_text("Preview isn't available in this browser. Convert to JPG or PNG to preview it.")).to_be_visible()
    expect(page.locator("[id='message-legacy-upload']")).to_have_class(re.compile("items-end"))
    expect(page.get_by_text("legacy.heif")).to_be_visible()


def action_row(page):
    """The hover-revealed row under the upload, found through a control it always holds."""
    return page.get_by_role("button", name="Show sources", exact=True).locator(
        "xpath=ancestor::div[contains(@class, 'transition-opacity')][1]"
    )


def test_uploaded_image_card_is_sized_to_the_image_like_generated_images(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("sized-image", "lab.png", "doc-lab")])

    card = page.get_by_role("button", name="View the full-size image: lab.png")
    expect(card.locator("img[alt='lab.png']")).to_be_visible()
    page.wait_for_function(
        "() => document.querySelector(\"img[alt='lab.png']\")?.naturalWidth === 320"
    )
    box = card.bounding_box()
    # Sized to the 320px image, as a generated image is, not stretched across the column.
    assert box and box["width"] <= 330, box
    frame = card.locator("xpath=ancestor::div[contains(@class, 'glass-flat')][1]").bounding_box()
    assert frame and frame["width"] <= 345, frame


def test_uploaded_image_actions_are_revealed_on_hover(image_ui):
    page, api = image_ui
    mount_messages(page, api, [file_message("sized-image", "lab.png", "doc-lab")])

    card = page.get_by_role("button", name="View the full-size image: lab.png")
    expect(card.locator("img[alt='lab.png']")).to_be_visible()
    page.mouse.move(1, 1)
    expect(action_row(page)).to_have_css("opacity", "0")

    card.hover()
    expect(action_row(page)).to_have_css("opacity", "1")
    for name in ("Show sources", "Message details", "Open file preview for lab.png"):
        expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()


def test_uploaded_image_sources_show_what_ingestion_extracted(image_ui):
    page, api = image_ui
    api.file_content["sized-image"] = (200, WORKSPACE_EXTRACTION)
    mount_messages(page, api, [file_message("sized-image", "lab.png", "doc-lab")])

    page.get_by_role("button", name="View the full-size image: lab.png").hover()
    page.get_by_role("button", name="Show sources", exact=True).click()

    expect(page.get_by_role("button", name="Sources", exact=True)).to_have_attribute("aria-pressed", "true")
    vision = page.get_by_role("region", name="AI vision analysis")
    expect(vision).to_be_visible()
    expect(vision).to_contain_text(VISION_DESCRIPTION)
    expect(vision).to_contain_text("checkerboard calibration panels")
    expect(vision).to_contain_text("gpt-5.4")
    expect(page.get_by_text("Azure AI Document Intelligence")).to_be_visible()
    expect(page.get_by_text("Indexed text")).to_be_visible()
    # The panel stays up while the pointer leaves, so it does not vanish mid-read.
    page.mouse.move(1, 1)
    expect(action_row(page)).to_have_css("opacity", "1")
    assert api.file_content_requests == [(CONVERSATION, "sized-image")]

    page.get_by_role("button", name="Details", exact=True).click()
    expect(page.get_by_role("button", name="Details", exact=True)).to_have_attribute("aria-pressed", "true")


def test_uploaded_image_preview_shows_extraction_instead_of_not_found(image_ui):
    page, api = image_ui
    api.file_content["sized-image"] = (200, WORKSPACE_EXTRACTION)
    mount_messages(page, api, [file_message("sized-image", "lab.png", "doc-lab")])

    page.get_by_role("button", name="View the full-size image: lab.png").hover()
    page.get_by_role("button", name="Open file preview for lab.png", exact=True).click()

    dialog = page.get_by_role("dialog", name="Uploaded file: lab.png")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("region", name="AI vision analysis")).to_contain_text(VISION_DESCRIPTION)
    expect(dialog.get_by_text("Likely a robotics or computer vision test space.")).to_be_visible()
    expect(dialog.get_by_text("File content not found")).to_have_count(0)


def test_uploaded_image_preview_explains_a_file_that_is_still_processing(image_ui):
    page, api = image_ui
    api.file_content["sized-image"] = (
        404,
        {"error": "This file is still being processed. Try again when it finishes."},
    )
    mount_messages(page, api, [file_message("sized-image", "lab.png", "doc-lab")])

    page.get_by_role("button", name="View the full-size image: lab.png").hover()
    page.get_by_role("button", name="Open file preview for lab.png", exact=True).click()

    dialog = page.get_by_role("dialog", name="Uploaded file: lab.png")
    expect(dialog.get_by_text("This file is still being processed. Try again when it finishes.")).to_be_visible()


def test_image_citation_viewer_shows_what_was_extracted(image_ui):
    page, api = image_ui
    api.cited_text = f"=== AI Vision Analysis ===\nModel: gpt-5.4\n\nDescription: {VISION_DESCRIPTION}"
    mount_messages(
        page,
        api,
        [{
            "id": "answer-1",
            "conversation_id": CONVERSATION,
            "role": "assistant",
            "content": "It is an empty lab floor. (Source: lab.png, Page: 1) [#doc-lab_1]",
            "metadata": {},
        }],
        features={"enable_user_workspace": True, "enable_enhanced_citations": True},
    )

    page.get_by_role("button", name=re.compile(r"^lab\.png")).click()

    viewer = page.get_by_role("dialog", name="Cited source")
    expect(viewer).to_be_visible()
    expect(viewer.locator("img[alt='lab.png']")).to_be_visible()
    expect(viewer.get_by_text("What was extracted from this image")).to_be_visible()
    expect(viewer).to_contain_text(VISION_DESCRIPTION)
