// conversationUrl.ts
// Reading and writing the conversation that a URL names.
//
// The classic interface puts the open conversation in the address bar so it can be copied
// and shared, and reads it back on load. These helpers hold the same rules for the V2 SPA
// in one place, away from React, so the direction of travel stays explicit: a URL is read
// once when the chat page first renders, and written whenever the open conversation
// changes.

/** The spelling this interface writes. */
export const CONVERSATION_PARAM = 'conversationId';

/**
 * A one-shot parameter that hands a saved prompt to the composer, as `/chat?prompt=<id>`.
 *
 * Declared here rather than beside the prompt code because this module owns the vocabulary of
 * the chat URL, and because `syncedConversationParams` below has to know to strip it. Two
 * components writing the query string independently is how a parameter one of them removed
 * comes back: each `setSearchParams` replaces the *whole* query from its own render snapshot,
 * so the later writer restores whatever the earlier one deleted.
 */
export const PROMPT_PARAM = 'prompt';

/**
 * The prompt a set of query parameters names, or null when it names none.
 *
 * Read by the composer through a lazy state initialiser, which runs during the first render --
 * before the effect below strips it.
 */
export function readPromptParam(params: URLSearchParams): string | null {
    const value = params.get(PROMPT_PARAM) ?? '';
    return value.trim() || null;
}

/** A link that opens the chat page with a saved prompt ready to insert. */
export function chatHrefForPrompt(promptId: string): string {
    return `/chat?${PROMPT_PARAM}=${encodeURIComponent(promptId)}`;
}

/**
 * Also accepted when reading, never written.
 *
 * The server emits both spellings and they are already in circulation: notifications and
 * workflow runs build `/chats?conversationId=`, while chat responses and workspace document
 * rows build `/chats?conversation_id=`. The classic client accepts either, so a link that
 * works there must work here too.
 */
export const LEGACY_CONVERSATION_PARAM = 'conversation_id';

/** Where the classic interface serves the chat page. */
const CLASSIC_CHAT_PATH = '/chats';

/**
 * The conversation a set of query parameters names, or null when it names none.
 *
 * The canonical spelling wins when both are present, so normalising a legacy link cannot
 * change which conversation it opens.
 */
export function readConversationParam(params: URLSearchParams): string | null {
    const value =
        params.get(CONVERSATION_PARAM) ?? params.get(LEGACY_CONVERSATION_PARAM) ?? '';
    const trimmed = value.trim();
    return trimmed || null;
}

/**
 * The query parameters a URL should carry for `conversationId`, or null when it already
 * carries exactly that.
 *
 * The null return is doing real work: it is what keeps the effect that writes the URL from
 * re-entering itself, and it means leaving and returning to the chat page costs no
 * navigation. A legacy parameter always counts as a difference, so an incoming
 * `?conversation_id=` link is rewritten to the canonical spelling on arrival.
 *
 * `prompt` is stripped here for the same reason, and deliberately by this one writer. The
 * composer reads it during its first render and must not remove it itself: `setSearchParams`
 * replaces the entire query from the caller's render snapshot, so a parameter the composer
 * deleted would be restored by this effect's own snapshot moments later -- leaving a URL that
 * re-inserts the prompt on every reload.
 */
export function syncedConversationParams(
    params: URLSearchParams,
    conversationId: string | null,
): URLSearchParams | null {
    const current = params.get(CONVERSATION_PARAM);
    const hasLegacy = params.has(LEGACY_CONVERSATION_PARAM);
    const hasPrompt = params.has(PROMPT_PARAM);

    if (!hasLegacy && !hasPrompt && (current ?? null) === conversationId) {
        return null;
    }

    const next = new URLSearchParams(params);
    next.delete(LEGACY_CONVERSATION_PARAM);
    next.delete(PROMPT_PARAM);
    if (conversationId) {
        next.set(CONVERSATION_PARAM, conversationId);
    } else {
        next.delete(CONVERSATION_PARAM);
    }
    return next;
}

/**
 * A link to the classic chat page, carrying the open conversation when there is one.
 *
 * Crossing between the two interfaces otherwise lands on the conversation list, which
 * means finding your place again in a rail that may be paged.
 */
export function classicChatHref(conversationId: string | null): string {
    if (!conversationId) {
        return CLASSIC_CHAT_PATH;
    }
    return `${CLASSIC_CHAT_PATH}?${CONVERSATION_PARAM}=${encodeURIComponent(conversationId)}`;
}
