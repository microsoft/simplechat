# test_chat_reasoning_runtime_notices.py
"""
Classic chat reasoning-recovery notices through real stream and history rendering.
Version: 0.261.104
Implemented in: 0.261.104

Loads local application modules and vendored Markdown/sanitizer assets. Only API
responses are mocked; the existing browser fixture supports local/Azure Playwright.
"""

import pytest
from playwright.sync_api import expect

from test_chat_streaming_thinking_placeholder import HARNESS_PATH, _start_static_test_server
from test_v2_orchestration_approval_persistence import approval_browser, connect_options  # noqa: F401

pytestmark = pytest.mark.ui


@pytest.fixture
def classic_reasoning_page(approval_browser):
    with _start_static_test_server() as origin:
        context = approval_browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(f"{origin}/{HARNESS_PATH}")
            for asset in ("marked.min.js", "purify.min.js"):
                page.add_script_tag(url=f"{origin}/application/single_app/static/js/chat/{asset}")
            page.evaluate("""async () => {
                window.appSettings = {enable_thoughts: true, enable_text_to_speech: false, documentActionCapabilities: {}};
                window.enable_document_classification = false;
                window.currentConversationId = 'classic-reasoning';
                window.scrollChatToBottom = () => {};
                window.reasoningInjected = false;
                window.savedReasoningMessages = [];
                document.getElementById('test-root').innerHTML = `
                    <div id="chatbox"></div><textarea id="user-input"></textarea>
                    <button id="send-btn" type="button"></button><select id="prompt-select"></select>
                    <div id="prompt-selection-container"></div>
                    <select id="model-select"><option value="gpt-4o">gpt-4o</option></select>`;
                window.fetch = (url) => {
                    const path = String(url);
                    if (path === '/api/chat/stream') {
                        const body = new ReadableStream({
                            start(controller) {
                                window.emitClassicReasoningEvent = (event) => {
                                    controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\\n\\n`));
                                    if (event.done) controller.close();
                                };
                            },
                        });
                        return Promise.resolve(new Response(body, {headers: {'Content-Type': 'text/event-stream'}}));
                    }
                    const result = path.startsWith('/conversation/classic-reasoning/messages')
                        ? {messages: window.savedReasoningMessages}
                        : {success: true, messages: [], documents: [], thoughts: []};
                    return Promise.resolve(new Response(JSON.stringify(result), {headers: {'Content-Type': 'application/json'}}));
                };
                window.classicMessages = await import('/application/single_app/static/js/chat/chat-messages.js');
                window.classicStreaming = await import('/application/single_app/static/js/chat/chat-streaming.js');
                window.currentConversationId = 'classic-reasoning';
            }""")
            yield page
            assert errors == []
        finally:
            context.close()


@pytest.mark.parametrize("terminal_source", ["metadata", "top_level", "thought_only", "cancelled"])
def test_classic_runtime_adjustment_is_live_nonrepeating_safe_and_reloaded(classic_reasoning_page, terminal_source):
    page = classic_reasoning_page
    page.evaluate("""() => {
        window.classicStreaming.sendMessageWithStreaming(
            {message: 'Answer this request.', conversation_id: 'classic-reasoning', reasoning_effort: 'minimal'},
            'pending-classic-user', 'classic-reasoning', {allowRecovery: false},
        );
    }""")
    page.wait_for_function("() => Boolean(window.emitClassicReasoningEvent)")
    model_name = (
        '<img src=x onerror="window.reasoningInjected=true">'
        if terminal_source == "top_level" else "gpt-5.6-luna"
    )
    first = {
        "requested_effort": "minimal", "effective_effort": "low", "mode": "explicit",
        "adjustment_reason": "reasoning_effort_unsupported", "stage": "answer", "model_name": model_name,
    }
    thought = {
        "type": "thought", "step_type": "generation", "content": "Adjusting reasoning.",
        "reasoning_adjustments": [first],
    }
    page.evaluate("(event) => window.emitClassicReasoningEvent(event)", thought)
    notice = page.locator("#chatbox .reasoning-adjustment-notices")
    expect(notice).to_have_count(1)
    expect(notice).to_contain_text("using Low.")
    expect(notice).to_have_attribute("role", "status")
    expect(notice).to_have_attribute("aria-live", "polite")
    page.evaluate("() => { window.initialReasoningNotice = document.querySelector('.reasoning-adjustment-notices'); }")
    page.evaluate("(event) => window.emitClassicReasoningEvent(event)", thought)
    expect(notice).to_have_count(1)
    assert page.evaluate("() => window.initialReasoningNotice === document.querySelector('.reasoning-adjustment-notices')")
    latest = {
        **first, "effective_effort": None, "mode": "model_default",
        "adjustment_reason": (
            "<script>window.reasoningInjected=true</script>"
            if terminal_source == "top_level" else "reasoning_parameter_rejected"
        ),
    }
    page.evaluate("(event) => window.emitClassicReasoningEvent(event)", {
        "type": "thought", "step_type": "generation", "content": "Using the model default.",
        "reasoning_adjustments": [latest],
    })
    expected = f"Answer: Minimal could not be used for {model_name}; using Model default."
    expect(notice).to_have_text(expected)
    expect(notice.locator("img, script")).to_have_count(0)
    page.evaluate("(event) => window.emitClassicReasoningEvent(event)", {"content": "A useful answer."})
    expect(notice).to_have_text(expected)
    terminal = {
        "done": True, "message_id": "classic-answer", "conversation_id": "classic-reasoning",
        "full_content": "A useful answer.", "metadata": {"fixture_marker": "preserved"},
    }
    if terminal_source in ("metadata", "cancelled"):
        terminal["metadata"]["reasoning_adjustments"] = [latest]
    elif terminal_source == "top_level":
        terminal["reasoning_adjustments"] = [latest]
    if terminal_source == "cancelled":
        terminal.update(cancelled=True, message_persisted=True)
    page.evaluate("(event) => window.emitClassicReasoningEvent(event)", terminal)
    expect(page.locator('[data-message-id="classic-answer"] .reasoning-adjustment-notices')).to_have_text(expected)
    expect(notice).to_have_count(1)
    page.evaluate("""async (adjustment) => {
        window.savedReasoningMessages = [
            {id: 'classic-user', role: 'user', content: 'Answer this request.',
                metadata: {reasoning_adjustments: [adjustment]}},
            {id: 'classic-answer', conversation_id: 'classic-reasoning', role: 'assistant',
                content: 'A useful answer.', metadata: {reasoning_adjustments: [adjustment]}},
        ];
        await window.classicMessages.loadMessages('classic-reasoning');
    }""", latest)
    expect(notice).to_have_count(1)
    expect(notice).to_have_text(expected)
    expect(notice.locator("img, script")).to_have_count(0)
    assert page.evaluate("() => window.reasoningInjected") is False


def test_classic_notice_distinguishes_explicit_none_and_removes_a_superseded_correction(classic_reasoning_page):
    page = classic_reasoning_page
    page.evaluate("""async () => {
        window.classicReasoning = await import('/application/single_app/static/js/chat/chat-reasoning.js');
        window.reasoningPayload = {reasoning_adjustments: [
            {requested_effort: 'high', effective_effort: 'none', mode: 'explicit',
                adjustment_reason: 'reasoning_effort_unsupported', stage: 'answer', model_name: 'Model'},
            {requested_effort: 'minimal', effective_effort: 'low', mode: 'explicit',
                adjustment_reason: 'reasoning_effort_unsupported', stage: 'planner', model_name: 'Model'},
            null, {mode: 'invalid'},
        ]};
        window.originalReasoningPayload = JSON.stringify(window.reasoningPayload);
        window.classicAdjustments = window.classicReasoning.getMessageReasoningAdjustments(window.reasoningPayload);
        window.classicMessages.appendMessage('AI', 'A saved answer.', null, 'saved-reasoning',
            false, [], [], [], null, null, {metadata: {reasoning_adjustments: window.classicAdjustments}});
    }""")
    notice = page.locator("#chatbox .reasoning-adjustment-notices")
    expect(notice.locator("p")).to_have_count(2)
    expect(notice).to_contain_text("Answer: High could not be used for Model; using None.")
    expect(notice).to_contain_text("Planner: Minimal could not be used for Model; using Low.")
    page.evaluate("""() => {
        const latest = window.classicReasoning.getMessageReasoningAdjustments({reasoning_adjustments: [
            {requested_effort: 'high', effective_effort: 'high', mode: 'explicit',
                adjustment_reason: null, stage: 'answer', model_name: 'Model'},
        ]}, window.classicAdjustments);
        window.classicReasoning.renderMessageReasoningAdjustments(
            document.querySelector('[data-message-id="saved-reasoning"]'), latest);
    }""")
    expect(notice.locator("p")).to_have_count(1)
    expect(notice).to_have_text("Planner: Minimal could not be used for Model; using Low.")
    assert page.evaluate("() => JSON.stringify(window.reasoningPayload) === window.originalReasoningPayload")
