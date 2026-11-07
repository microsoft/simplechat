// composerDraftHandoff.ts
// A one-shot hand-off that opens a new chat with text ready in the composer.
//
// Another page passes it through router state, never the URL. A link cannot carry router
// state, so nothing outside the application can put words in someone's composer; the person
// still reads, edits and sends the text themselves. The Control Center's "Chat with this
// dashboard" uses it to start an orchestrated conversation with a prompt describing the
// dashboard on screen.

/** The longest text a hand-off may carry; anything beyond is cut, never rejected. */
export const COMPOSER_DRAFT_HANDOFF_LIMIT = 4000;

export interface ComposerDraftHandoff {
    text: string;
    /** Start a new conversation rather than adding to the one last open. */
    newConversation: boolean;
    /** Turn orchestration on for this draft, where the deployment offers it. */
    orchestrate: boolean;
}

export interface ComposerDraftHandoffState {
    composerDraft: ComposerDraftHandoff;
}

/** The hand-off a navigation's router state carries, or null when it carries none. */
export function readComposerDraftHandoff(state: unknown): ComposerDraftHandoff | null {
    if (!state || typeof state !== 'object') {
        return null;
    }
    const candidate = (state as Partial<ComposerDraftHandoffState>).composerDraft;
    if (!candidate || typeof candidate !== 'object') {
        return null;
    }
    const text = typeof candidate.text === 'string'
        ? candidate.text.slice(0, COMPOSER_DRAFT_HANDOFF_LIMIT)
        : '';
    if (!text.trim()) {
        return null;
    }
    return {
        text,
        newConversation: candidate.newConversation === true,
        orchestrate: candidate.orchestrate === true,
    };
}

/** Router state that opens a new chat with `text` ready to send. */
export function composerDraftHandoffState(
    text: string,
    options: { orchestrate?: boolean } = {},
): ComposerDraftHandoffState {
    return {
        composerDraft: {
            text: text.slice(0, COMPOSER_DRAFT_HANDOFF_LIMIT),
            newConversation: true,
            orchestrate: options.orchestrate === true,
        },
    };
}
