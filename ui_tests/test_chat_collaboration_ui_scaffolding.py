# test_chat_collaboration_ui_scaffolding.py
"""
UI test for chat collaboration scaffolding.
Version: 0.241.020
Implemented in: 0.241.020

This test ensures the authenticated chats page loads the collaboration UI
containers needed for participant management and @-mention suggestions without
introducing browser-side collaboration boot errors, including the collaboration
deactivation path used when switching away from a shared conversation and the
add-participants picker entry point used from existing chat actions. It also
validates the shared conversation details footer actions and the new delete or
leave modal flow for both legacy and collaborative chats.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


@pytest.mark.ui
def test_chat_collaboration_ui_scaffolding(playwright):
    """Validate that collaboration UI containers render on the chats page."""
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 900},
    )
    page = context.new_page()
    page_errors = []
    console_errors = []

    def track_page_error(error):
        page_errors.append(str(error))

    def track_console(message):
        if message.type == 'error':
            console_errors.append(message.text)

    page.on('pageerror', track_page_error)
    page.on('console', track_console)

    try:
        response = page.goto(f'{BASE_URL}/chats', wait_until='domcontentloaded')

        assert response is not None, 'Expected a navigation response when loading /chats.'
        assert response.ok, f'Expected /chats to load successfully, got HTTP {response.status}.'

        expect(page.locator('#chatbox')).to_be_visible()
        expect(page.locator('#user-input')).to_be_visible()
        expect(page.locator('#collaboration-reply-preview')).to_have_count(1)
        expect(page.locator('#collaboration-mention-menu')).to_have_count(1)
        expect(page.locator('#collaboration-mention-menu')).to_have_class('list-group collaboration-mention-menu d-none')
        expect(page.locator('#collaboration-participant-modal')).to_have_count(1)
        expect(page.locator('#collaboration-confirm-modal')).to_have_count(1)
        expect(page.locator('#conversation-details-actions')).to_have_count(1)
        expect(page.locator('#delete-conversation-modal')).to_have_count(1)
        expect(page.get_by_label('Participant suggestions')).to_have_count(1)
        expect(page.get_by_label('Search recent collaborators or local users')).to_have_count(1)
        expect(page.locator('#collaboration-confirm-add-btn')).to_have_text('Add participant')
        expect(page.locator('#confirm-delete-conversation-btn')).to_have_text('Delete Conversation')

        page.evaluate("""
            () => {
                const mockConversationId = 'mock-collaboration-conversation';
                const mockConversationItem = document.createElement('div');
                mockConversationItem.className = 'conversation-item';
                mockConversationItem.dataset.conversationId = mockConversationId;
                mockConversationItem.dataset.conversationKind = 'collaborative';
                mockConversationItem.dataset.canPostMessages = 'false';
                document.body.appendChild(mockConversationItem);

                const originalGetCurrentConversationId = window.chatConversations.getCurrentConversationId;
                window.chatConversations.getCurrentConversationId = () => mockConversationId;

                try {
                    window.chatCollaboration.deactivateConversation();
                } finally {
                    window.chatConversations.getCurrentConversationId = originalGetCurrentConversationId;
                    mockConversationItem.remove();
                }
            }
        """)

        page.evaluate("""
            () => {
                const mockConversationId = 'mock-personal-conversation';
                const mockConversationItem = document.createElement('div');
                mockConversationItem.className = 'conversation-item';
                mockConversationItem.dataset.conversationId = mockConversationId;
                mockConversationItem.dataset.chatType = 'personal_single_user';
                document.body.appendChild(mockConversationItem);

                const participantModal = document.getElementById('collaboration-participant-modal');
                const modalInstance = bootstrap.Modal.getOrCreateInstance(participantModal);

                try {
                    window.chatCollaboration.openParticipantPicker({ conversationId: mockConversationId });
                    if (!participantModal.classList.contains('show')) {
                        throw new Error('Participant picker did not open for an eligible personal conversation.');
                    }
                } finally {
                    modalInstance.hide();
                    mockConversationItem.remove();
                }
            }
        """)

        page.evaluate("""
            () => {
                const replyPreview = document.getElementById('collaboration-reply-preview');
                window.chatCollaboration.replyToMessage({
                    id: 'mock-reply-message',
                    content: 'Please look at the updated shared reply workflow.',
                    sender: {
                        user_id: 'member-user-002',
                        display_name: 'Member User'
                    }
                });

                if (!replyPreview || replyPreview.classList.contains('d-none')) {
                    throw new Error('Reply preview did not become visible after selecting Reply.');
                }
            }
        """)
        expect(page.locator('#collaboration-reply-preview')).not_to_have_class('collaboration-reply-preview d-none')
        expect(page.locator('#collaboration-reply-preview-label')).to_contain_text('Replying to Member User')
        expect(page.locator('#collaboration-reply-preview-text')).to_contain_text('updated shared reply workflow')
        page.click('#collaboration-reply-cancel-btn')
        expect(page.locator('#collaboration-reply-preview')).to_have_class('collaboration-reply-preview d-none')

        page.evaluate("""
            () => {
                const message = document.createElement('div');
                message.className = 'message collaborator-message';
                message.innerHTML = `
                    <div class="message-content">
                        <img src="/static/images/user-avatar.png" alt="Collaborator Avatar" class="avatar collaborator-avatar" />
                        <div class="message-bubble">Shared message</div>
                    </div>
                `;
                document.body.appendChild(message);

                const avatar = message.querySelector('.avatar');
                const styles = window.getComputedStyle(avatar);
                if (styles.flexShrink !== '0') {
                    throw new Error(`Expected collaborator avatar flex-shrink to be 0 but received ${styles.flexShrink}.`);
                }
                if (styles.minWidth !== '30px') {
                    throw new Error(`Expected collaborator avatar min-width to be 30px but received ${styles.minWidth}.`);
                }

                message.remove();
            }
        """)

        page.evaluate("""
            () => {
                const mentionContainer = document.createElement('div');
                mentionContainer.className = 'collaboration-mentions-block';
                mentionContainer.innerHTML = `
                    <div class="collaboration-mentions-label">Tagged</div>
                    <div class="collaboration-mentions-list">
                        <span class="collaboration-mention-chip collaboration-mention-chip-current-user">@Owner User</span>
                        <span class="collaboration-mention-chip collaboration-mention-chip-target-agent">@Default Agent</span>
                        <span class="collaboration-mention-chip collaboration-mention-chip-target-model">@gpt-5.4</span>
                    </div>
                `;
                document.body.appendChild(mentionContainer);

                const mentionChips = Array.from(mentionContainer.querySelectorAll('.collaboration-mention-chip'));
                const baseStyles = window.getComputedStyle(mentionChips[0]);
                if (baseStyles.borderRadius === '0px') {
                    throw new Error('Expected mention chips to be visibly pill-shaped.');
                }
                if (baseStyles.display !== 'inline-flex') {
                    throw new Error(`Expected mention chips to use inline-flex but received ${baseStyles.display}.`);
                }

                const currentUserStyles = window.getComputedStyle(mentionChips[0]);
                const agentStyles = window.getComputedStyle(mentionChips[1]);
                const modelStyles = window.getComputedStyle(mentionChips[2]);
                if (agentStyles.backgroundColor === currentUserStyles.backgroundColor) {
                    throw new Error('Expected agent mention chips to use a different background color than user mention chips.');
                }
                if (modelStyles.backgroundColor === agentStyles.backgroundColor) {
                    throw new Error('Expected model mention chips to use a different background color than agent mention chips.');
                }

                mentionContainer.remove();
            }
        """)

        page.evaluate("""
            async () => {
                window.chatModelOptions = [
                    {
                        display_name: 'gpt-5.4',
                        deployment_name: 'gpt-5.4',
                        model_id: 'gpt-5.4',
                        provider: 'azure-openai'
                    }
                ];
                window.chatAgentOptions = [
                    {
                        id: 'default-agent',
                        name: 'default-agent',
                        display_name: 'Default Agent',
                        is_global: true,
                        is_group: false
                    }
                ];

                const mockConversationId = 'mock-mention-suggestions';
                const originalConversationGetter = window.chatConversations.getCurrentConversationId;
                const conversation = document.createElement('div');
                conversation.className = 'conversation-item';
                conversation.dataset.conversationId = mockConversationId;
                conversation.dataset.conversationKind = 'collaborative';
                conversation.dataset.chatType = 'personal_multi_user';
                document.body.appendChild(conversation);

                window.chatConversations.getCurrentConversationId = () => mockConversationId;
                document.getElementById('user-input').value = '@gpt';
                document.getElementById('user-input').setSelectionRange(4, 4);

                try {
                    window.chatCollaboration.handleComposerInput();
                    await new Promise(resolve => window.setTimeout(resolve, 0));
                    const mentionMenu = document.getElementById('collaboration-mention-menu');
                    const mentionText = mentionMenu.textContent || '';
                    if (!mentionText.includes('gpt-5.4')) {
                        throw new Error('Expected @-mention suggestions to include model targets.');
                    }
                    if (!mentionText.includes('Model')) {
                        throw new Error('Expected model suggestions to include a Model badge.');
                    }

                    document.getElementById('user-input').value = '@Default';
                    document.getElementById('user-input').setSelectionRange(8, 8);
                    window.chatCollaboration.handleComposerInput();
                    await new Promise(resolve => window.setTimeout(resolve, 0));

                    if (!(mentionMenu.textContent || '').includes('Default Agent')) {
                        throw new Error('Expected @-mention suggestions to include agent targets.');
                    }
                } finally {
                    window.chatConversations.getCurrentConversationId = originalConversationGetter;
                    document.getElementById('user-input').value = '';
                    document.getElementById('user-input').setSelectionRange(0, 0);
                    document.getElementById('collaboration-mention-menu').classList.add('d-none');
                    document.getElementById('collaboration-mention-menu').innerHTML = '';
                    conversation.remove();
                }
            }
        """)

        page.evaluate("""
            () => {
                window.currentUser = { id: 'owner-user-001' };
                const originalGetCurrentConversationId = window.chatConversations.getCurrentConversationId;
                const originalUserInputValue = document.getElementById('user-input').value;
                const mockConversationId = 'mock-shared-ai-context';
                const mockConversationItem = document.createElement('div');
                mockConversationItem.className = 'conversation-item';
                mockConversationItem.dataset.conversationId = mockConversationId;
                mockConversationItem.dataset.conversationKind = 'collaborative';
                document.body.appendChild(mockConversationItem);
                document.getElementById('user-input').value = 'Summarize the selected workspace';
                window.chatConversations.getCurrentConversationId = () => mockConversationId;

                try {
                    const context = window.chatCollaboration.getPendingMessageContext({
                        invocationTarget: {
                            target_type: 'model',
                            display_name: 'GPT-4.1',
                            mention_text: '@GPT-4.1',
                            source_mode: 'workspace'
                        }
                    });

                    if (!context?.metadata?.ai_invocation_target) {
                        throw new Error('Expected shared pending message context to include ai_invocation_target metadata.');
                    }
                    if (context.metadata.ai_invocation_target.mention_text !== '@GPT-4.1') {
                        throw new Error('Expected shared pending message context to preserve the invocation chip text.');
                    }
                    if (context.metadata.explicit_ai_invocation !== true) {
                        throw new Error('Expected shared pending message context to mark explicit AI invocation.');
                    }
                } finally {
                    window.chatConversations.getCurrentConversationId = originalGetCurrentConversationId;
                    document.getElementById('user-input').value = originalUserInputValue;
                    mockConversationItem.remove();
                }
            }
        """)

        page.evaluate("""
            async () => {
                const mockConversationId = 'mock-shared-conversation-read-state';
                const originalFetch = window.fetch;
                const originalEventSource = window.EventSource;
                const fetchedUrls = [];

                window.fetch = async (url, options) => {
                    const requestUrl = String(url || '');
                    fetchedUrls.push(requestUrl);

                    if (requestUrl.includes(`/api/collaboration/conversations/${mockConversationId}/messages`)) {
                        return new Response(JSON.stringify({ messages: [] }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/json' }
                        });
                    }

                    if (requestUrl.includes(`/api/collaboration/conversations/${mockConversationId}/mark-read`)) {
                        return new Response(JSON.stringify({
                            success: true,
                            conversation_id: mockConversationId,
                            notifications_marked_read: 1
                        }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/json' }
                        });
                    }

                    return originalFetch(url, options);
                };

                window.EventSource = class MockEventSource {
                    constructor(url) {
                        this.url = url;
                        this.onmessage = null;
                        this.onerror = null;
                    }

                    close() {}
                };

                try {
                    await window.chatCollaboration.activateConversation(mockConversationId, {
                        id: mockConversationId,
                        title: 'Shared notification state',
                        conversation_kind: 'collaborative',
                        chat_type: 'personal_multi_user',
                        can_post_messages: true,
                        participants: []
                    });

                    if (!fetchedUrls.some(url => url.includes(`/api/collaboration/conversations/${mockConversationId}/mark-read`))) {
                        throw new Error('Expected collaboration activation to clear shared notifications via mark-read.');
                    }
                } finally {
                    window.fetch = originalFetch;
                    window.EventSource = originalEventSource;
                    window.chatCollaboration.deactivateConversation();
                }
            }
        """)

        page.evaluate("""
            async () => {
                const mockConversationId = 'mock-shared-ai-stream';
                const originalFetch = window.fetch;
                const originalGetCurrentConversationId = window.chatConversations.getCurrentConversationId;
                const fetchedUrls = [];
                const encoder = new TextEncoder();

                const mockConversationItem = document.createElement('div');
                mockConversationItem.className = 'conversation-item';
                mockConversationItem.dataset.conversationId = mockConversationId;
                mockConversationItem.dataset.conversationKind = 'collaborative';
                document.body.appendChild(mockConversationItem);

                window.chatConversations.getCurrentConversationId = () => mockConversationId;
                window.currentConversationId = mockConversationId;

                window.fetch = async (url, options) => {
                    const requestUrl = String(url || '');
                    fetchedUrls.push(requestUrl);

                    if (requestUrl.includes(`/api/collaboration/conversations/${mockConversationId}/stream`)) {
                        const payload = {
                            done: true,
                            conversation_id: mockConversationId,
                            conversation_title: 'Shared AI Stream',
                            message_id: 'assistant-shared-response',
                            user_message_id: 'shared-user-message',
                            full_content: 'Shared AI response',
                            augmented: true,
                            hybrid_citations: [],
                            web_search_citations: [],
                            agent_citations: [],
                            model_deployment_name: 'gpt-4.1',
                            image_url: null,
                            reload_messages: false
                        };
                        const stream = new ReadableStream({
                            start(controller) {
                                controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
                                controller.close();
                            }
                        });
                        return new Response(stream, {
                            status: 200,
                            headers: { 'Content-Type': 'text/event-stream' }
                        });
                    }

                    if (requestUrl.includes('/api/conversations/')) {
                        return new Response(JSON.stringify({ success: true }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/json' }
                        });
                    }

                    return originalFetch(url, options);
                };

                try {
                    await window.chatCollaboration.sendCollaborativeAiMessage(
                        'Summarize the workspace',
                        'temp_user_stream_test',
                        {
                            message: 'Summarize the workspace',
                            conversation_id: mockConversationId,
                            hybrid_search: true,
                            web_search_enabled: false,
                            image_generation: false,
                            prompt_info: null,
                            agent_info: null,
                            model_deployment: 'gpt-4.1'
                        },
                        {
                            metadata: {
                                ai_invocation_target: {
                                    target_type: 'model',
                                    display_name: 'GPT-4.1',
                                    mention_text: '@GPT-4.1',
                                    source_mode: 'workspace'
                                }
                            }
                        }
                    );

                    await new Promise(resolve => window.setTimeout(resolve, 50));

                    if (!fetchedUrls.some(url => url.includes(`/api/collaboration/conversations/${mockConversationId}/stream`))) {
                        throw new Error('Expected shared AI send to call the collaboration stream endpoint.');
                    }

                    if (!document.querySelector('[data-message-id="assistant-shared-response"]')) {
                        throw new Error('Expected shared AI streaming to render the final assistant message.');
                    }
                } finally {
                    window.fetch = originalFetch;
                    window.chatConversations.getCurrentConversationId = originalGetCurrentConversationId;
                    mockConversationItem.remove();
                    const renderedAssistant = document.querySelector('[data-message-id="assistant-shared-response"]');
                    if (renderedAssistant) {
                        renderedAssistant.remove();
                    }
                }
            }
        """)

        page.evaluate("""
            () => {
                window.currentUser = { id: 'owner-user-001' };
                const originalFetch = window.fetch;

                window.__deleteModalFetchRestore = () => {
                    window.fetch = originalFetch;
                };

                window.fetch = async (url, options) => {
                    const requestUrl = String(url || '');
                    if (requestUrl.includes('/api/conversations/mock-legacy-conversation/metadata')) {
                        return new Response(JSON.stringify({
                            id: 'mock-legacy-conversation',
                            title: 'Legacy conversation',
                            chat_type: 'personal_single_user'
                        }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/json' }
                        });
                    }

                    return originalFetch(url, options);
                };
            }
        """)

        page.evaluate("""
            async () => {
                await window.chatConversations.deleteConversation('mock-legacy-conversation');
            }
        """)
        expect(page.locator('#delete-conversation-modal')).to_be_visible()
        expect(page.locator('#delete-conversation-message')).to_contain_text('delete this conversation')
        page.evaluate("""
            () => {
                bootstrap.Modal.getOrCreateInstance(document.getElementById('delete-conversation-modal')).hide();
            }
        """)

        page.evaluate("""
            () => {
                window.chatCollaboration.fetchConversationMetadata = async () => ({
                    id: 'mock-shared-conversation',
                    title: 'Shared conversation',
                    conversation_kind: 'collaborative',
                    can_delete_conversation: true,
                    can_leave_conversation: true,
                    participants: [
                        { user_id: 'owner-user-001', display_name: 'Owner User', status: 'accepted', role: 'owner' },
                        { user_id: 'member-user-002', display_name: 'Member User', status: 'accepted', role: 'member' }
                    ]
                });
            }
        """)

        page.evaluate("""
            async () => {
                await window.chatConversations.deleteConversation('mock-shared-conversation');
            }
        """)
        expect(page.locator('#delete-conversation-modal')).to_be_visible()
        expect(page.locator('#delete-conversation-transfer-option')).not_to_have_class('form-check mb-2 d-none')

        page.click('#delete-conversation-action-leave')
        expect(page.locator('#delete-conversation-owner-select-container')).not_to_have_class('mt-3 d-none')
        expect(page.locator('#confirm-delete-conversation-btn')).to_have_text('Assign Owner & Leave')

        page.evaluate("""
            () => {
                bootstrap.Modal.getOrCreateInstance(document.getElementById('delete-conversation-modal')).hide();
                window.__deleteModalFetchRestore?.();
            }
        """)

        page.wait_for_load_state('networkidle')

        collaboration_page_errors = [message for message in page_errors if 'collaboration' in message.lower()]
        collaboration_console_errors = [message for message in console_errors if 'collaboration' in message.lower()]
        syntax_errors = [message for message in page_errors if 'SyntaxError' in message]

        assert not syntax_errors, (
            'Expected /chats to boot without JavaScript syntax errors. '
            f'Observed: {syntax_errors}'
        )
        assert not collaboration_page_errors, (
            'Expected /chats collaboration UI to load without page errors. '
            f'Observed: {collaboration_page_errors}'
        )
        assert not collaboration_console_errors, (
            'Expected /chats collaboration UI to load without collaboration console errors. '
            f'Observed: {collaboration_console_errors}'
        )
    finally:
        context.close()
        browser.close()