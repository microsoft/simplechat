// replyEvents.ts
// A small in-page channel for "a reply just finished".
//
// The chat store and the orchestration controller each know when a reply lands; the desktop
// notifier needs to hear about both, and neither of them should need to know it exists.
// So they announce here and the notifier subscribes. The module imports nothing, which is
// what lets both stores reach it without an import cycle through the notification code.
//
// Workflow runs (Phase 6b) announce their delivered results through the same call with
// `source: 'workflow'`; that is the whole integration a new source of replies needs.

export type CompletedReplySource = 'chat' | 'orchestration' | 'workflow';

export interface CompletedReply {
    conversationId: string;
    /** The finished assistant message. The desktop notifier deduplicates on it. */
    messageId: string | null;
    /** An orchestration or workflow run, when the reply belongs to one. */
    runId?: string | null;
    conversationTitle: string | null;
    /** A reply the safety filter replaced. Classic never raises a notification for one. */
    blocked: boolean;
    source: CompletedReplySource;
}

type CompletedReplyListener = (reply: CompletedReply) => void;

const listeners = new Set<CompletedReplyListener>();

/** Tell every subscriber that a reply finished. A failing subscriber cannot stop the others. */
export function announceCompletedReply(reply: CompletedReply): void {
    if (!reply.conversationId) {
        return;
    }
    for (const listener of [...listeners]) {
        try {
            listener(reply);
        } catch (error) {
            console.warn('A completed-reply listener failed.', error);
        }
    }
}

/** Listen for finished replies. Returns the function that stops listening. */
export function subscribeCompletedReplies(listener: CompletedReplyListener): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}
