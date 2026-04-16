# test_chat_collaboration_ui_scaffolding.py
"""
UI test for chat collaboration scaffolding.
Version: 0.241.014
Implemented in: 0.241.014

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