// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_user_agreement_gate.py.
//
// Mounts the places a V2 user sends a file to the server, exactly as the application renders them: the
// chat composer's editor on its own (ComposerEditor, with its attach button, paste and drop handling,
// upload queue and retry), the whole chat composer (Composer, with its Send control and the conversation
// it sends into), the elicitation card (ElicitationCard, whose question fields embed the same editor and
// whose Next, Review answers and Use these answers controls move or submit the answers), and the
// workspace documents explorer (DocumentExplorer, with its command bar upload button, file input and drop
// region) in personal, group and public scope, built from the real read and operation adapters. Nothing in
// application/v2_ui/src is replaced; the test answers HTTP, including the two user agreement routes, and
// seeds the bootstrap store.

import { StrictMode, useEffect, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as orchestrationStore from '../../../application/v2_ui/src/stores/orchestrationStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import { Composer as ChatComposer } from '../../../application/v2_ui/src/components/chat/Composer';
import { ComposerEditor } from '../../../application/v2_ui/src/components/chat/ComposerEditor';
import { ElicitationCard } from '../../../application/v2_ui/src/components/chat/ElicitationCard';
import { DocumentExplorer } from '../../../application/v2_ui/src/components/documents/DocumentExplorer';
import { Toaster } from '../../../application/v2_ui/src/components/ui/Toaster';
import { createComposerDraft, type ComposerDraft } from '../../../application/v2_ui/src/lib/composerDraft';
import {
    createGroupDocumentOperations,
    createPublicDocumentOperations,
} from '../../../application/v2_ui/src/lib/documentOperations';
import {
    createGroupDocumentReader,
    createPublicDocumentReader,
} from '../../../application/v2_ui/src/lib/documentReadAdapter';
import type { Elicitation } from '../../../application/v2_ui/src/lib/orchestration';
import * as userAgreement from '../../../application/v2_ui/src/lib/userAgreement';

type ExplorerKind = 'personal' | 'group' | 'public';

const CAPABILITIES = { sort_fields: ['_ts'], facets: false, places: false } as never;
const MANAGEMENT = { schema_version: 1, operations: ['upload'] };
// The conversation and turn the open question belongs to.
const QUESTION_CONVERSATION = 'conv-questions';
const QUESTION_TURN = 'turn-questions';

let moveConversation: ((conversationId: string | null) => void) | null = null;
let removeEditor: (() => void) | null = null;

function Composer({ conversationId: initial }: { conversationId: string | null }) {
    const [draft, setDraft] = useState<ComposerDraft>(createComposerDraft());
    const [conversationId, setConversationId] = useState<string | null>(initial);
    const [editorShown, setEditorShown] = useState(true);
    // What the editor reports to its owner, which is all the owner knows of the agreement.
    const [pending, setPending] = useState(false);
    // An owner that never reads the flag: it counts what the editor submits and holds nothing itself.
    const [submitted, setSubmitted] = useState(0);
    // Lets a test move the composer to another conversation while the agreement is open, and take the
    // editor away while the owner stays.
    useEffect(() => {
        moveConversation = setConversationId;
        removeEditor = () => setEditorShown(false);
        return () => {
            moveConversation = null;
            removeEditor = null;
        };
    }, []);
    return (
        <div className="p-4">
            <output aria-label="Agreement pending">{String(pending)}</output>
            <output aria-label="Submitted">{submitted}</output>
            {editorShown ? (
                <ComposerEditor
                    id="agreement-composer"
                    label="Message"
                    draft={draft}
                    onChange={setDraft}
                    conversationId={conversationId}
                    multipleFiles
                    onSubmit={() => setSubmitted((count) => count + 1)}
                    onAgreementPendingChange={setPending}
                />
            ) : (
                <p>The editor is gone.</p>
            )}
        </div>
    );
}

/** The whole chat composer, as /chat renders it, over the stores a test seeds. */
function Chat() {
    return (
        <Routes>
            <Route path="/chat" element={<ChatComposer />} />
        </Routes>
    );
}

function explorerProps(kind: ExplorerKind) {
    if (kind === 'group') {
        const scope = { kind: 'group', id: 'group-a', name: 'Research Group' } as const;
        return {
            reader: createGroupDocumentReader(scope.id, scope.name, CAPABILITIES),
            operations: createGroupDocumentOperations(scope, MANAGEMENT),
        };
    }
    if (kind === 'public') {
        const scope = { kind: 'public', id: 'public-a', name: 'Open Library' } as const;
        return {
            reader: createPublicDocumentReader(scope.id, scope.name, CAPABILITIES),
            operations: createPublicDocumentOperations(scope, MANAGEMENT),
        };
    }
    return {};
}

function Explorer({ kind }: { kind: ExplorerKind }) {
    const [props] = useState(() => explorerProps(kind));
    return (
        <div style={{ height: '100dvh' }} className="flex min-w-0 flex-col p-2">
            <DocumentExplorer {...props} />
        </div>
    );
}

let root: Root | null = null;

function unmount(): void {
    root?.unmount();
    root = null;
}

function mountInto(element: JSX.Element, entry = '/'): void {
    unmount();
    const container = document.getElementById('root');
    if (!container) {
        throw new Error('Root container #root was not found in the harness page.');
    }
    root = createRoot(container);
    root.render(
        <StrictMode>
            <MemoryRouter initialEntries={[entry]}>
                {element}
                <Toaster />
            </MemoryRouter>
        </StrictMode>,
    );
}

declare global {
    interface Window {
        AgreementHarness: unknown;
    }
}

window.AgreementHarness = {
    mountComposer: (conversationId: string | null = 'conv-1') => mountInto(<Composer conversationId={conversationId} />),
    moveComposer: (conversationId: string | null) => moveConversation?.(conversationId),
    removeEditor: () => removeEditor?.(),
    mountChat: (conversationId: string | null = 'conv-1') => {
        chatStore.useChatStore.setState({
            activeConversationId: conversationId,
            activeConversationKind: 'personal',
            messages: [],
            conversations: [],
            streaming: false,
            streamError: null,
        });
        orchestrationStore.useOrchestrationStore.getState().setVisibleConversation(conversationId);
        mountInto(<Chat />, '/chat');
    },
    // What choosing "New chat" does: the person leaves the conversation they were in.
    newChat: () => chatStore.useChatStore.getState().startNewConversation(),
    // The real elicitation card over a question seeded into the real orchestration store.
    mountQuestions: (question: Elicitation) => {
        chatStore.useChatStore.setState({
            activeConversationId: QUESTION_CONVERSATION,
            activeConversationKind: 'personal',
            messages: [],
            conversations: [{ id: QUESTION_CONVERSATION, title: 'Questions' }],
            streaming: false,
            streamError: null,
        } as never);
        const store = orchestrationStore.useOrchestrationStore.getState();
        store.setActiveTurn(QUESTION_CONVERSATION, QUESTION_TURN);
        store.setElicitation(QUESTION_CONVERSATION, QUESTION_TURN, question);
        mountInto(<ElicitationCard conversationId={QUESTION_CONVERSATION} turnId={QUESTION_TURN} />);
    },
    // What the server does when it asks again: the same turn, a new revision of the question.
    reviseQuestions: (question: Elicitation) => orchestrationStore.useOrchestrationStore.getState()
        .setElicitation(QUESTION_CONVERSATION, QUESTION_TURN, question),
    mountExplorer: (kind: ExplorerKind) => mountInto(<Explorer kind={kind} />),
    unmount,
    stores: { bootstrap: bootstrapStore, chat: chatStore, userSettings: userSettingsStore },
    userAgreement,
};
