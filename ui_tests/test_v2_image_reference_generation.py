# test_v2_image_reference_generation.py
"""
UI coverage for v2 direct Image mode reference-image generation.
Version: 0.261.144
Implemented in: 0.261.144

This test ensures reference uploads, "Use as reference", sent thumbnails, and capability
gating are wired through the real v2 composer and message list.
"""

import base64
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
CONVERSATION = "image-reference-chat"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class ImageReferenceApi:
    def __init__(self, assets):
        self.assets = assets
        self.requests = []
        self.stream_bodies = []
        self.unexpected = []
        self.errors = []

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
        self.requests.append({"method": request.method, "path": path})
        if request.method == "POST" and path == "/upload":
            route.fulfill(json={
                "success": True,
                "conversation_id": CONVERSATION,
                "file_message_id": "uploaded-reference-message",
                "workspace_scope": "personal",
                "workspace_document_id": "uploaded-reference-doc",
                "workspace_document": {
                    "document_id": "uploaded-reference-doc",
                    "file_name": "house.png",
                    "scope": "personal",
                    "status": "ready",
                    "percentage_complete": 100,
                },
            })
            return
        if request.method == "POST" and path == "/api/chat/stream":
            body = request.post_data_json
            self.stream_bodies.append(body)
            frames = [
                {"type": "thought", "content": "Using 1 reference image(s)"},
                {"type": "user_message_persisted", "user_message_id": "sent-user-message"},
                {
                    "done": True,
                    "role": "image",
                    "message_id": "generated-image-message",
                    "user_message_id": "sent-user-message",
                    "content": "/api/image/generated-image-message",
                },
            ]
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
            )
            return
        if request.method == "GET" and path in {"/api/get_messages", "/api/v2/chat/messages"}:
            route.fulfill(json={"messages": []})
            return
        if path.startswith("/api/image/"):
            route.fulfill(status=200, body=PNG, content_type="image/png")
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})


@pytest.fixture
def reference_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 860})
    page = context.new_page()
    api = ImageReferenceApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, api.unexpected
        assert not api.errors, api.errors


def input_file(name, body=b"image"):
    folder = Path(__file__).resolve().parent / "artifacts" / "image-reference-inputs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(body)
    return path


def mount_prompt_experience(page, capability=None, messages=None):
    if page.url != ORIGIN + HARNESS:
        page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.144',
                settings: { max_file_size_mb: 25 },
                branding: { app_title: 'SimpleChat' },
                features: {
                    enable_user_workspace: true,
                    enable_chat_file_uploads: true,
                    enable_image_generation: true,
                },
                capabilities: { image_edit: spec.capability },
                user: { id: 'ui-user', display_name: 'Reference Tester' },
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
                conversations: [{ id: spec.conversation, title: 'Reference chat' }],
                messages: spec.messages,
            });
            H.mount('test-root', 'PromptExperience');
        }""",
        {
            "conversation": CONVERSATION,
            "messages": messages or [],
            "capability": capability or {
                "enabled": True,
                "mode": "masked",
                "model_name": "gpt-image",
                "reason": "",
                "provider_label": "OpenAI",
                "cloud_label": "Commercial",
                "availability": "documented",
                "availability_reason": "",
                "editing": True,
                "masking": True,
                "max_reference_images": 4,
                "input_fidelity": True,
                "sizes": [],
                "qualities": [],
                "backgrounds": [],
            },
        },
    )


def test_image_mode_upload_rejects_heic_and_sends_references(reference_ui):
    page, api = reference_ui
    mount_prompt_experience(page)
    page.get_by_role("button", name="Image", exact=True).click()
    expect(page.get_by_text("0 / 4 reference images")).to_be_visible()
    expect(page.get_by_role("button", name="Documents", exact=True)).to_be_enabled()

    file_input = page.locator("input[type=file]").first
    file_input.set_input_files(str(input_file("portrait.heic")))
    expect(page.get_by_text("HEIC images can't be used as reference images yet")).to_be_visible()
    # A rejected file stays as a failed chip, which blocks sending until it is removed.
    page.get_by_role("button", name="Remove portrait.heic", exact=True).click()
    expect(page.get_by_text("portrait.heic")).to_have_count(0)

    file_input.set_input_files(str(input_file("house.png", PNG)))
    expect(page.get_by_text("house.png")).to_be_visible()
    expect(page.get_by_text("1 / 4 reference images")).to_be_visible()
    page.get_by_label("Message", exact=True).fill("Make a cartoon of this house")
    page.get_by_role("button", name="Send message", exact=True).click()
    page.wait_for_function("() => document.body.innerText.includes('Reference images')")

    body = api.stream_bodies[-1]
    assert body["image_generation"] is True
    assert body["hybrid_search"] is False
    assert body["image_references"] == [{"type": "message", "message_id": "uploaded-reference-message"}]
    assert "selected_document_ids" not in body or body["selected_document_ids"] == []
    expect(page.get_by_text("Reference images", exact=True)).to_be_visible()


def test_use_as_reference_adds_chip_and_turns_image_on(reference_ui):
    page, _api = reference_ui
    mount_prompt_experience(page, messages=[{
        "id": "generated-message-1",
        "conversation_id": CONVERSATION,
        "role": "image",
        "content": "/api/image/generated-message-1",
        "prompt": "A generated cabin",
        "metadata": {},
    }])
    page.get_by_role("button", name="Use as reference", exact=True).click(force=True)
    expect(page.get_by_role("button", name="Image", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_text("Generated image", exact=True)).to_be_visible()
    expect(page.get_by_text("1 / 4 reference images")).to_be_visible()


def test_switching_conversation_drops_explicit_references(reference_ui):
    page, _api = reference_ui
    mount_prompt_experience(page, messages=[{
        "id": "generated-message-1",
        "conversation_id": CONVERSATION,
        "role": "image",
        "content": "/api/image/generated-message-1",
        "prompt": "A generated cabin",
        "metadata": {},
    }])
    page.get_by_role("button", name="Use as reference", exact=True).click(force=True)
    remove_chip = page.get_by_role("button", name="Remove reference Generated image", exact=True)
    expect(remove_chip).to_be_visible()
    # A message reference is only valid in its own conversation, so leaving it must drop it.
    page.evaluate(
        """() => window.OrchHarness.stores.chat.useChatStore.setState({
            activeConversationId: 'another-conversation',
            conversations: [{ id: 'another-conversation', title: 'Another chat' }],
            messages: [],
        })"""
    )
    expect(remove_chip).to_have_count(0)


def test_reference_affordances_hide_when_model_cannot_edit(reference_ui):
    page, _api = reference_ui
    mount_prompt_experience(page, capability={
        "enabled": True,
        "mode": "regenerate",
        "model_name": "text-to-image-only",
        "reason": "The selected image model can't use reference images.",
        "provider_label": "Provider",
        "cloud_label": "Cloud",
        "availability": "documented",
        "availability_reason": "",
        "editing": False,
        "masking": False,
        "max_reference_images": 0,
        "input_fidelity": False,
        "sizes": [],
        "qualities": [],
        "backgrounds": [],
    }, messages=[{
        "id": "generated-message-1",
        "conversation_id": CONVERSATION,
        "role": "image",
        "content": "/api/image/generated-message-1",
        "prompt": "A generated cabin",
        "metadata": {},
    }])
    page.get_by_role("button", name="Image", exact=True).click()
    expect(page.get_by_text("The selected image model can't use reference images.")).to_be_visible()
    expect(page.get_by_role("button", name="Attach a file", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Use as reference", exact=True)).to_have_count(0)
