# test_streaming_thought_progression.py
"""
UI test for streaming thought progression.
Version: 0.250.064
Implemented in: 0.250.064

This test ensures the live streaming placeholder keeps advancing to the latest
thought and ordered orchestration step for the active assistant message, remains
accessible, and does not inherit stale state when a new message starts.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
@pytest.mark.parametrize('viewport', [
    {'width': 1440, 'height': 900},
    {'width': 390, 'height': 844},
])
def test_streaming_thought_progression_and_session_isolation(playwright, viewport):
    """Validate live thought progression and stale-session isolation in the browser."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=viewport,
        ignore_https_errors=True,
    )
    page = context.new_page()

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        if page.locator('link[href="/static/css/chats.css"]').count() == 0:
            page.add_style_tag(url='/static/css/chats.css')
        if page.evaluate("typeof window.DOMPurify === 'undefined'"):
            page.add_script_tag(url='/static/js/chat/purify.min.js')

        result = page.evaluate(
            """
            async () => {
                const thoughtsModule = await import('/static/js/chat/chat-thoughts.js');
                const {
                    beginStreamingThoughtSession,
                    clearStreamingThoughtSession,
                    createThoughtsToggleHtml,
                    handleStreamingThought,
                    markStreamingThoughtContentStarted,
                } = thoughtsModule;

                function createPlaceholder(messageId, initialText = 'Streaming...') {
                        let harness = document.getElementById('phase7-thought-harness');
                        if (!harness) {
                            harness = document.createElement('main');
                            harness.id = 'phase7-thought-harness';
                            harness.className = 'container py-3';
                            document.body.replaceChildren(harness);
                        }
                    const wrapper = document.createElement('div');
                    wrapper.setAttribute('data-message-id', messageId);
                    wrapper.innerHTML = `<div class="message-text">${initialText}</div>`;
                        harness.appendChild(wrapper);
                    return wrapper;
                }

                const oldPlaceholder = createPlaceholder('temp-old');
                beginStreamingThoughtSession('temp-old');
                handleStreamingThought({
                    message_id: 'assistant-old',
                    step_index: 0,
                    step_type: 'generation',
                    content: 'Old thought'
                }, 'temp-old');

                clearStreamingThoughtSession('temp-old');

                const newPlaceholder = createPlaceholder('temp-new');
                beginStreamingThoughtSession('temp-new');
                const beforeThought = newPlaceholder.querySelector('.message-text').textContent;

                handleStreamingThought({
                    message_id: 'assistant-new',
                    step_index: 0,
                    step_type: 'search',
                    content: 'Searching for current reply'
                }, 'temp-new');
                const afterFirstThought = newPlaceholder.querySelector('.message-text').textContent;

                handleStreamingThought({
                    message_id: 'assistant-new',
                    step_index: 1,
                    step_type: 'generation',
                    content: 'Preparing final answer'
                }, 'temp-new');
                const afterSecondThought = newPlaceholder.querySelector('.message-text').textContent;

                markStreamingThoughtContentStarted('temp-new');
                handleStreamingThought({
                    message_id: 'assistant-new',
                    step_index: 2,
                    step_type: 'generation',
                    content: 'Late thought should be ignored'
                }, 'temp-new');
                const afterContentStarted = newPlaceholder.querySelector('.message-text').textContent;
                const serverMessageId = newPlaceholder.dataset.streamingServerMessageId || null;
                const thoughtIndexAfterContent = newPlaceholder.dataset.streamingThoughtIndex || null;

                clearStreamingThoughtSession('temp-new');
                const orchestrationPlaceholder = createPlaceholder('temp-orchestration');
                beginStreamingThoughtSession('temp-orchestration');
                const capabilities = [
                    ['evidence_discovery', 'plan-evidence', 'Planning evidence workflow'],
                    ['selected_images', 'selected-images', 'Reviewing selected image'],
                    ['workspace_search', 'workspace-search', 'Searching workspace documents'],
                    ['web_search', 'web-search', 'Searching public web'],
                    ['selected_agent', 'selected-agent', 'Calling selected agent'],
                    ['source_review', 'source-review', 'Reviewing sources'],
                    ['image_proposal', 'image-proposal', 'Building image proposal'],
                ];
                let stepIndex = 0;
                const orchestrationPercents = [];
                capabilities.forEach(([capability, nodeId, content], nodeIndex) => {
                    ['running', 'succeeded'].forEach(status => {
                        handleStreamingThought({
                            message_id: 'assistant-orchestration',
                            step_index: stepIndex,
                            step_type: 'orchestration_progress',
                            content,
                            activity: {
                                kind: 'orchestration_node',
                                run_id: 'run-orchestration',
                                node_id: nodeId,
                                node_index: nodeIndex,
                                node_count: 8,
                                node_type: capability === 'image_proposal' ? 'finalize' : 'collect',
                                capability,
                                status,
                                required: true,
                            },
                        }, 'temp-orchestration');
                        orchestrationPercents.push(Number(
                            orchestrationPlaceholder.querySelector('.orchestration-progress-card').dataset.orchestrationProgressPercent
                        ));
                        stepIndex += 1;
                    });
                });
                handleStreamingThought({
                    message_id: 'assistant-orchestration',
                    step_index: stepIndex,
                    step_type: 'approval_required',
                    content: 'Awaiting image proposal approval',
                    activity: {
                        kind: 'orchestration_node',
                        run_id: 'run-orchestration',
                        node_id: 'image-proposal:approval',
                        node_index: 7,
                        node_count: 8,
                        node_type: 'approval',
                        capability: 'approval_required',
                        status: 'running',
                        required: true,
                    },
                }, 'temp-orchestration');

                const orchestrationCard = orchestrationPlaceholder.querySelector('.orchestration-progress-card');
                const orchestrationLabels = Array.from(
                    orchestrationCard.querySelectorAll('.orchestration-progress-step .fw-semibold')
                ).map(element => element.textContent.trim());
                const orchestrationStatuses = Array.from(
                    orchestrationCard.querySelectorAll('.orchestration-progress-step')
                ).map(element => element.dataset.orchestrationNodeStatus);

                clearStreamingThoughtSession('temp-orchestration');
                const isolatedPlaceholder = createPlaceholder('temp-orchestration-isolated');
                beginStreamingThoughtSession('temp-orchestration-isolated');
                handleStreamingThought({
                    message_id: 'assistant-orchestration-isolated',
                    step_index: 0,
                    step_type: 'orchestration_progress',
                    content: 'Searching public web',
                    activity: {
                        kind: 'orchestration_node',
                        run_id: 'run-isolated',
                        node_id: 'web-search',
                        node_type: 'collect',
                        capability: 'web_search',
                        status: 'running',
                        required: true,
                    },
                }, 'temp-orchestration-isolated');
                const isolatedLabels = Array.from(
                    isolatedPlaceholder.querySelectorAll('.orchestration-progress-step .fw-semibold')
                ).map(element => element.textContent.trim());
                window.appSettings = {
                    ...(window.appSettings || {}),
                    enable_thoughts: true,
                };
                const thoughtsMarkup = createThoughtsToggleHtml('assistant-complete');

                return {
                    beforeThought,
                    afterFirstThought,
                    afterSecondThought,
                    afterContentStarted,
                    oldPlaceholderText: oldPlaceholder.querySelector('.message-text').textContent,
                    serverMessageId,
                    thoughtIndexAfterContent,
                    orchestrationLabels,
                    orchestrationStatuses,
                    orchestrationPercents,
                    orchestrationState: orchestrationCard.dataset.orchestrationProgressState,
                    orchestrationPercent: orchestrationCard.dataset.orchestrationProgressPercent,
                    ariaLive: orchestrationCard.getAttribute('aria-live'),
                    ariaRole: orchestrationCard.getAttribute('role'),
                    currentOrchestrationStep: orchestrationCard.querySelector('.orchestration-progress-current').textContent.trim(),
                    orchestrationOverflows: orchestrationCard.scrollWidth > orchestrationCard.clientWidth,
                    orchestrationRight: orchestrationCard.getBoundingClientRect().right,
                    viewportWidth: window.innerWidth,
                    isolatedLabels,
                    completedThoughtsCollapsed: thoughtsMarkup.containerHtml.includes('d-none'),
                };
            }
            """
        )

        assert result['beforeThought'] == 'Streaming...'
        assert 'Searching for current reply' in result['afterFirstThought']
        assert 'Old thought' not in result['afterFirstThought']
        assert 'Preparing final answer' in result['afterSecondThought']
        assert 'Searching for current reply' not in result['afterSecondThought']
        assert result['afterContentStarted'] == result['afterSecondThought']
        assert result['oldPlaceholderText'] != result['afterFirstThought']
        assert result['serverMessageId'] == 'assistant-new'
        assert result['thoughtIndexAfterContent'] is None
        assert result['orchestrationLabels'] == [
            'Planning evidence workflow',
            'Reviewing selected image',
            'Searching workspace documents',
            'Searching public web',
            'Calling selected agent',
            'Reviewing sources',
            'Building image proposal',
            'Awaiting approval',
        ]
        assert result['orchestrationStatuses'] == (['succeeded'] * 7) + ['running']
        assert result['orchestrationPercents'] == sorted(result['orchestrationPercents'])
        assert result['orchestrationPercents'][-1] < 100
        assert result['orchestrationState'] == 'awaiting_approval'
        assert result['orchestrationPercent'] == '95'
        assert result['ariaLive'] == 'polite'
        assert result['ariaRole'] == 'status'
        assert result['currentOrchestrationStep'] == 'Awaiting approval'
        assert result['orchestrationOverflows'] is False
        assert result['orchestrationRight'] <= result['viewportWidth'] + 1
        assert result['isolatedLabels'] == ['Searching public web']
        assert result['completedThoughtsCollapsed'] is True
    finally:
        context.close()
        browser.close()