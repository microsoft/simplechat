// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_artifact_actions.py.
//
// Mounts the real generated-artifact card -- the one MessageList draws under a reply -- with the
// toaster beside it as the app shell draws it. Nothing in application/v2_ui/src is replaced: the
// card, its actions, the promotion dialog, the stores and the export machinery all run as they do
// in the application. The test answers HTTP and seeds the stores that tell the card which
// conversation it is in.

import { StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as actionStore from '../../../application/v2_ui/src/stores/generatedArtifactActionStore';
import * as toastStore from '../../../application/v2_ui/src/stores/toastStore';
import { GeneratedArtifactCard } from '../../../application/v2_ui/src/components/chat/GeneratedArtifactCard';
import { Toaster } from '../../../application/v2_ui/src/components/ui/Toaster';
import type { GeneratedArtifact } from '../../../application/v2_ui/src/lib/generatedArtifacts';

interface CardProps {
    artifact: GeneratedArtifact;
    conversationId?: string;
    messageId?: string;
    embedded?: boolean;
}

function Frame({ cards }: { cards: CardProps[] }) {
    return (
        <div className="min-h-screen p-4">
            <main className="mx-auto max-w-2xl space-y-3">
                {cards.map((card, index) => (
                    <GeneratedArtifactCard key={`${card.artifact.artifact_message_id}-${index}`} {...card} />
                ))}
            </main>
            <Toaster />
        </div>
    );
}

let root: Root | null = null;

function unmount(): void {
    root?.unmount();
    root = null;
}

function mount(cards: CardProps[]): void {
    unmount();
    const container = document.getElementById('root');
    if (!container) {
        throw new Error('Root container #root was not found in the harness page.');
    }
    root = createRoot(container);
    root.render(
        <StrictMode>
            <Frame cards={cards} />
        </StrictMode>,
    );
}

declare global {
    interface Window {
        ArtifactHarness: unknown;
    }
}

window.ArtifactHarness = {
    mount,
    unmount,
    stores: {
        bootstrap: bootstrapStore,
        chat: chatStore,
        actions: actionStore,
        toast: toastStore,
    },
};
