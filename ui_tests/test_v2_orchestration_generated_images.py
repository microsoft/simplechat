# test_v2_orchestration_generated_images.py
"""
Real-component browser coverage for images an orchestrated answer generated as planned steps.
Version: 0.261.138
Implemented in: 0.261.138

The production controller, SSE reader, stores, message list and image cards execute in the
existing local/Azure Playwright harness. Only API responses are deterministic. The answer
lists its saved image messages in metadata.orchestration.generated_images, exactly as
functions_orchestration_execution._finalize publishes them, and its image cards use the
server's simpleimage projection (functions_orchestration_deliverables.generated_image_block).

Covers:
- the live chat loading the saved image messages after the run's terminal frame;
- a planned image card never offering Approve or Approve all, even before its image loads;
- a retry's answer showing an image an earlier attempt generated, while the earlier
  answer keeps showing it too.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_generated_images.py -q
"""

import base64
import io
import json

import pytest
from PIL import Image
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
import test_v2_orchestration_recovery as recovery_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
PRESIDENTS = (("washington", "George Washington"), ("adams", "John Adams"), ("jefferson", "Thomas Jefferson"))


def _pixel():
    """A tiny PNG inlined as a data URI, so the harness makes no image request."""
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "navy").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


PIXEL = _pixel()


def image_block(visual_id, title):
    """The block the server projects for a generated image."""
    payload = {
        "version": 1, "visualId": visual_id, "title": title,
        "description": "AI-generated illustration", "prompt": f"An illustrated portrait of {title}.",
        "visualType": "illustration", "context": "AI-generated illustration",
    }
    return "```simpleimage\n" + json.dumps(payload) + "\n```"


def image_message(visual_id, title, source_answer_id):
    return {
        "id": f"image-{visual_id}", "conversation_id": recovery_tests.CONVERSATION, "role": "image",
        "content": PIXEL, "prompt": f"An illustrated portrait of {title}.", "model_deployment_name": "gpt-image-1",
        "metadata": {"image_proposal": {
            "version": 1, "visualId": visual_id, "title": title, "prompt": f"An illustrated portrait of {title}.",
            "source_assistant_message_id": source_answer_id,
        }},
    }


def answer_content():
    sections = [
        f"## {title}\n\n{image_block(visual_id, title)}\n\n*AI-generated illustration: {title}*"
        for visual_id, title in PRESIDENTS
    ]
    return "# The first three presidents\n\n" + "\n\n".join(sections)


class GeneratedImagesApi(recovery_tests.RecoveryApi):
    """A completed run whose answer shows images saved as separate conversation messages."""

    def finish(self, run_id, status="failed"):
        event = super().finish(run_id, "completed")
        answer_id = self.records[run_id]["assistant_message_id"]
        images = [
            {"visual_id": visual_id, "message_id": f"image-{visual_id}"} for visual_id, _title in PRESIDENTS
        ]
        content = answer_content()
        for message in self.messages:
            if message["id"] == answer_id:
                message["content"] = content
                message["metadata"]["orchestration"]["generated_images"] = images
        # The image messages exist only on the server until the chat reads the thread again.
        self.messages = [message for message in self.messages if message["role"] != "image"] + [
            image_message(visual_id, title, answer_id) for visual_id, title in PRESIDENTS
        ]
        event.update(full_content=content, generated_images=images)
        event["metadata"]["orchestration"]["generated_images"] = images
        return event


@pytest.fixture
def images_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = GeneratedImagesApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def test_the_live_chat_loads_the_images_its_answer_generated(images_ui):
    page, api = images_ui
    recovery_tests.mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()

    for _visual_id, title in PRESIDENTS:
        expect(page.get_by_role("button", name=f"View the full-size image: {title}")).to_be_visible()
    expect(page.get_by_role("button", name="Approve", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Approve all 3 images")).to_have_count(0)
    # Each image appears once, in its card, not again as a loose image in the thread.
    expect(page.locator("img[alt='George Washington']")).to_have_count(1)
    # The images arrived because the chat read the thread again after the terminal frame.
    run_index = next(index for index, call in enumerate(api.requests) if call["path"] == editor_tests.RUN)
    assert any(
        call["path"] in ("/api/get_messages", "/api/v2/chat/messages") for call in api.requests[run_index + 1:]
    )
    assert not api.calls("/image-proposals/generate")


def test_a_planned_image_card_never_offers_approval_while_its_image_loads(images_ui):
    page, api = images_ui
    answer_id = "assistant-earlier"
    api.messages.append({
        "id": answer_id, "conversation_id": recovery_tests.CONVERSATION, "role": "assistant",
        "content": answer_content(),
        "metadata": {"orchestration": {"run_id": api.plan["run_id"], "generated_images": [
            {"visual_id": visual_id, "message_id": f"image-{visual_id}"} for visual_id, _title in PRESIDENTS
        ]}},
    })
    # Only Washington's image message has loaded so far.
    api.messages.append(image_message("washington", "George Washington", answer_id))
    recovery_tests.mount_recovery(page, api, saved=True, resume_saved=False)

    expect(page.get_by_role("button", name="View the full-size image: George Washington")).to_be_visible()
    loading = page.get_by_text("This image was generated with the answer. It appears here once it has loaded.")
    expect(loading).to_have_count(2)
    expect(page.get_by_role("button", name="Approve", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Approve all 3 images")).to_have_count(0)

    page.evaluate("""(images) => {
        const chat = window.OrchHarness.stores.chat.useChatStore;
        chat.setState({ messages: [...chat.getState().messages, ...images] });
    }""", [image_message(visual_id, title, answer_id) for visual_id, title in PRESIDENTS[1:]])
    expect(loading).to_have_count(0)
    for _visual_id, title in PRESIDENTS:
        expect(page.get_by_role("button", name=f"View the full-size image: {title}")).to_be_visible()
    assert not api.calls("/image-proposals/generate")


def test_a_retry_answer_and_the_earlier_answer_both_show_a_reused_image(images_ui):
    page, api = images_ui
    listed = [{"visual_id": "washington", "message_id": "image-washington"}]
    for answer_id in ("assistant-earlier", "assistant-retry"):
        api.messages.append({
            "id": answer_id, "conversation_id": recovery_tests.CONVERSATION, "role": "assistant",
            "content": f"## George Washington\n\n{image_block('washington', 'George Washington')}",
            "metadata": {"orchestration": {"run_id": answer_id, "generated_images": listed}},
        })
    # The image stays linked to the earlier answer that generated it; the retry lists it too.
    api.messages.append(image_message("washington", "George Washington", "assistant-earlier"))
    recovery_tests.mount_recovery(page, api, saved=True, resume_saved=False)

    expect(page.get_by_role("button", name="View the full-size image: George Washington")).to_have_count(2)
    expect(page.get_by_role("button", name="Approve", exact=True)).to_have_count(0)
    # The shared image is shown only inside the two cards, never as a loose thread image.
    expect(page.locator("img[alt='George Washington']")).to_have_count(2)
