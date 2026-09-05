// harness_entry.tsx
// Version: 0.261.093. Real SSE reader, chat store and error notice; only HTTP is mocked.

import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { MessageList } from '../../../application/v2_ui/src/components/chat/MessageList';
import { useChatStore, type ComposerOptions } from '../../../application/v2_ui/src/stores/chatStore';
import { useBootstrapStore } from '../../../application/v2_ui/src/stores/bootstrapStore';
import type { BootstrapPayload } from '../../../application/v2_ui/src/lib/types';

const options: ComposerOptions = {
    documentSearch: false,
    webSearch: false,
    imageGeneration: false,
    deepResearch: false,
    urlAccess: false,
    contextItems: [],
};

declare global {
    interface Window {
        FoundryConsentHarness: {
            send: () => Promise<void>;
            retry: () => Promise<void>;
            reset: () => void;
            switchChat: () => Promise<void>;
            state: () => { error: string | null; authUrl: string | null; streaming: boolean };
        };
    }
}

useBootstrapStore.setState({
    data: {
        user: { id: 'user-1', display_name: 'Test user', is_admin: false, roles: [] },
        features: {},
        catalogs: { agents: [], models: [], prompts: [], initial_model_selection: null },
    } as BootstrapPayload,
    loading: false,
});
useChatStore.setState({
    activeConversationId: 'chat-1',
    activeConversationKind: 'personal',
    messagesLoading: false,
});
window.FoundryConsentHarness = {
    send: () => useChatStore.getState().sendMessage('Delegate a review.', options),
    retry: () => useChatStore.getState().retryMessage('user-message', options),
    reset: () => useChatStore.getState().startNewConversation(),
    switchChat: () => useChatStore.getState().selectConversation('other-chat', { kind: 'personal' }),
    state: () => {
        const state = useChatStore.getState();
        return { error: state.streamError, authUrl: state.streamAuthUrl, streaming: state.streaming };
    },
};

const root = document.getElementById('root');
if (!root) {
    throw new Error('Missing harness root');
}
createRoot(root).render(<MemoryRouter><MessageList /></MemoryRouter>);
