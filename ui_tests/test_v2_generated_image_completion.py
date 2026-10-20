# test_v2_generated_image_completion.py
"""
Real-store and real-component coverage for generated image completion messages.
Version: 0.261.358
Implemented in: 0.261.356

Only HTTP is mocked. Live image_url completions, legacy image frames, saved-message
reload, viewer downloads, retry/edit, reattachment, collaboration, safety and
conversation ownership all pass through the production chat store and SSE reader.
"""

import base64
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_image_reference_generation import (
    CONVERSATION, PNG, ImageReferenceApi, mount_prompt_experience,
)
from test_v2_orchestration_plan_editor import (  # noqa: F401
    ORIGIN, connect_options, editor_assets, editor_browser,
)


pytestmark = pytest.mark.ui
PROMPT = "A cabin beside a quiet lake"
MESSAGE_ID = "generated-image-message"
SOURCE = f"/api/image/{MESSAGE_ID}"


class CompletionApi(ImageReferenceApi):
    def __init__(self, assets):
        super().__init__(assets)
        self.completion = {
            "reply": "Image loading...", "image_url": SOURCE,
            "model_deployment_name": "image-model", "metadata": {"is_user_upload": False},
        }
        self.messages = []
        self.waiting = []
        self.defer_stream = False
        self.defer_messages = False
        self.resume = False
        self.on_stream_held = None
        self.on_messages_held = None

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/api/chat/stream" or path.endswith(f"/{CONVERSATION}/stream") or "/stream/reattach/" in path:
            self.stream_bodies.append(request.post_data_json if request.post_data else {})
            frames = [
                {"type": "thought", "content": "Creating the image"},
                {"type": "user_message_persisted", "user_message_id": "sent-user-message"},
                {"done": True, "message_id": MESSAGE_ID, "user_message_id": "sent-user-message", **self.completion},
            ]

            def finish():
                route.fulfill(content_type="text/event-stream",
                              body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames))

            if self.defer_stream:
                self.waiting.append(finish)
                self.on_stream_held()
            else:
                finish()
            return
        if "/stream/status/" in path:
            route.fulfill(json={"pending": self.resume, "active": self.resume, "user_message_id": "sent-user-message"})
            return
        if path.endswith("/metadata"):
            route.fulfill(json={})
            return
        if path == "/api/action-credentials/pending":
            route.fulfill(json={"requests": []})
            return
        if path in ("/api/get_messages", "/api/v2/chat/messages"):
            if self.defer_messages:
                self.waiting.append(lambda: route.fulfill(json={"messages": self.messages}))
                self.on_messages_held()
            else:
                route.fulfill(json={"messages": self.messages})
            return
        if path.startswith("/api/message/") and path.endswith(("/edit", "/retry")):
            prompt = (request.post_data_json or {}).get("content", PROMPT)
            question = {
                "id": "sent-user-message", "conversation_id": CONVERSATION, "role": "user", "content": prompt,
                "metadata": {"thread_info": {"thread_id": "image-thread", "thread_attempt": 2, "active_thread": True}},
            }
            route.fulfill(json={
                "user_message_id": question["id"], "user_message": question,
                "thread_id": "image-thread", "new_attempt": 2, "available_attempts": [1, 2],
                "chat_request": {"conversation_id": CONVERSATION, "message": prompt, "image_generation": True},
            })
            return
        if path.startswith(f"/api/collaboration/conversations/{CONVERSATION}/images/") or request.url.startswith("https://images.test/"):
            route.fulfill(body=PNG, content_type="image/png")
            return
        super().handle(route)

    def release(self):
        waiting, self.waiting = self.waiting, []
        for finish in waiting:
            finish()


@pytest.fixture
def completion_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 860}, accept_downloads=True)
    page = context.new_page()
    api = CompletionApi(editor_assets)
    api.on_stream_held = lambda: page.evaluate("window.imageStreamHeld = true")
    api.on_messages_held = lambda: page.evaluate("window.imageMessagesHeld = true")
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    mount_prompt_experience(page)
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.unexpected, api.unexpected
        assert not api.errors, api.errors


def send(page, prompt=PROMPT):
    page.evaluate("""(prompt) => {
        window.imageSendFinished = false;
        window.OrchHarness.stores.chat.useChatStore.getState().sendMessage(prompt, {
            imageGeneration: true, modelDeployment: 'image-model',
        }).then(() => { window.imageSendFinished = true; });
    }""", prompt)


def image_messages(page):
    return page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.getState()
        .messages.filter(message => message.id === 'generated-image-message')""")


@pytest.mark.parametrize("source", [
    SOURCE, "https://images.test/generated.png", "data:image/png;base64," + base64.b64encode(PNG).decode("ascii"),
])
def test_live_image_completion_is_viewable_downloadable_and_matches_reload(completion_ui, source):
    page, api = completion_ui
    api.completion["image_url"] = source
    send(page)
    page.wait_for_function("() => window.imageSendFinished === true")
    (live,) = image_messages(page)
    assert live["role"] == "image" and live["content"] == source and live["prompt"] == PROMPT
    assert live["model_deployment_name"] == "image-model"
    assert live["metadata"] == {"is_user_upload": False}
    assert live["thoughts"][0]["content"] == "Creating the image"
    image = page.get_by_role("img", name=PROMPT, exact=True)
    expect(image).to_be_visible()
    page.get_by_role("button", name=f"View the full-size image: {PROMPT}", exact=True).click()
    dialog = page.get_by_role("dialog", name="Image", exact=True)
    expect(dialog.get_by_role("img", name=PROMPT, exact=True)).to_be_visible()
    with page.expect_download() as downloaded:
        dialog.get_by_role("button", name="Save the image", exact=True).click()
    assert downloaded.value.suggested_filename == PROMPT + ".png"
    downloaded_bytes = downloaded.value.path().read_bytes()
    assert downloaded_bytes == PNG
    dialog.get_by_role("button", name="Close the image", exact=True).click()
    api.messages = [
        {"id": "sent-user-message", "role": "user", "content": PROMPT, "conversation_id": CONVERSATION},
        {key: live[key] for key in ("id", "conversation_id", "role", "content", "prompt", "metadata", "model_deployment_name")},
    ]
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().reloadMessages()")
    expect(image).to_be_visible()
    (saved,) = image_messages(page)
    assert saved["role"] == "image" and saved["content"] == source and saved["prompt"] == PROMPT


@pytest.mark.parametrize(("completion", "role", "content"), [
    ({"role": "image", "content": SOURCE}, "image", SOURCE),
    ({"content": "Ordinary text"}, "assistant", "Ordinary text"),
    ({"content": "Text without an image", "image_url": None}, "assistant", "Text without an image"),
    ({"blocked": True, "content": "This request was blocked.", "image_url": SOURCE}, "safety", "This request was blocked."),
    ({"role": "safety", "content": "Safety explanation", "image_url": SOURCE}, "safety", "Safety explanation"),
])
def test_image_folding_preserves_legacy_text_and_safety_completions(completion_ui, completion, role, content):
    page, api = completion_ui
    api.completion = completion
    send(page)
    page.wait_for_function("() => window.imageSendFinished === true")
    (message,) = image_messages(page)
    assert message["role"] == role and message["content"] == content
    if role != "image":
        expect(page.locator(f"#message-{MESSAGE_ID} img")).to_have_count(0)


@pytest.mark.parametrize("kind", ["personal", "collaborative"])
def test_delayed_image_completion_keeps_its_bound_prompt_and_deduplicates_saved_echo(completion_ui, kind):
    page, api = completion_ui
    api.defer_stream = True
    source = SOURCE if kind == "personal" else f"/api/collaboration/conversations/{CONVERSATION}/images/{MESSAGE_ID}"
    api.completion["image_url"] = source
    page.evaluate("""(kind) => {
        const H = window.OrchHarness;
        H.stores.chat.useChatStore.setState({ activeConversationKind: kind });
        if (kind === 'collaborative') H.stores.collaboration.useCollaborationStore.setState({
            activeConversationId: 'image-reference-chat',
            conversation: { id: 'image-reference-chat', can_post_messages: true, participants: [] },
        });
    }""", kind)
    send(page)
    page.wait_for_function("() => window.imageStreamHeld === true")
    page.evaluate("""({source, prompt}) => {
        const S = window.OrchHarness.stores.chat.useChatStore;
        S.setState({ messages: [...S.getState().messages,
            { id: 'another-user', role: 'user', content: 'A different later question' },
            { id: 'generated-image-message', role: 'image', content: source, prompt },
        ] });
    }""", {"source": source, "prompt": PROMPT})
    page.wait_for_function("() => Boolean(document.querySelector('#message-generated-image-message'))")
    api.release()
    page.wait_for_function("() => window.imageSendFinished === true")
    (message,) = image_messages(page)
    assert message["role"] == "image" and message["content"] == source and message["prompt"] == PROMPT
    assert len(api.stream_bodies) == 1


def test_image_completion_from_a_departed_conversation_does_not_enter_the_new_thread(completion_ui):
    page, api = completion_ui
    api.defer_stream = True
    send(page)
    page.wait_for_function("() => window.imageStreamHeld === true")
    page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.setState({
        activeConversationId: 'another-chat', messages: [{ id: 'other', role: 'user', content: 'Other chat' }],
    })""")
    api.release()
    page.wait_for_function("() => window.imageSendFinished === true")
    assert image_messages(page) == []
    expect(page.get_by_text("Other chat", exact=True)).to_be_visible()


def test_image_completion_keeps_the_existing_source_safety_boundary(completion_ui):
    page, api = completion_ui
    api.completion["image_url"] = "javascript:window.imageExecuted=true"
    send(page)
    page.wait_for_function("() => window.imageSendFinished === true")
    expect(page.get_by_text("Image unavailable.", exact=True)).to_be_visible()
    expect(page.locator(f"#message-{MESSAGE_ID} img")).to_have_count(0)
    assert page.evaluate("window.imageExecuted") is None


@pytest.mark.parametrize("action", ["retry", "edit", "resume"])
def test_image_completion_uses_the_same_fold_for_retry_edit_and_reattachment(completion_ui, action):
    page, api = completion_ui
    question = {"id": "sent-user-message", "conversation_id": CONVERSATION, "role": "user", "content": PROMPT}
    api.messages = [question, {"id": "later", "role": "user", "content": "Unrelated later turn"}]
    api.defer_messages = action != "resume"
    api.resume = action == "resume"
    page.evaluate("""({action, messages, conversation}) => {
        const S = window.OrchHarness.stores.chat.useChatStore;
        S.setState({ messages, activeConversationId: action === 'resume' ? null : conversation });
        const pending = action === 'edit' ? S.getState().editMessage('sent-user-message', 'Edited cabin prompt')
            : action === 'retry' ? S.getState().retryMessage('sent-user-message')
            : S.getState().selectConversation(conversation, { kind: 'personal' });
        pending.then(() => { window.imageActionFinished = true; });
    }""", {"action": action, "messages": api.messages, "conversation": CONVERSATION})
    page.wait_for_function("() => window.OrchHarness.stores.chat.useChatStore.getState().messages.some(m => m.id === 'generated-image-message')")
    (message,) = image_messages(page)
    assert message["role"] == "image" and message["content"] == SOURCE
    assert message["prompt"] == ("Edited cabin prompt" if action == "edit" else PROMPT)
    if action != "resume":
        page.wait_for_function("() => window.imageMessagesHeld === true")
        api.messages = [question, message]
        api.release()
    page.wait_for_function("() => window.imageActionFinished === true")
