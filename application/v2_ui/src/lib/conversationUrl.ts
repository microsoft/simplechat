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
 */
export function syncedConversationParams(
    params: URLSearchParams,
    conversationId: string | null,
): URLSearchParams | null {
    const current = params.get(CONVERSATION_PARAM);
    const hasLegacy = params.has(LEGACY_CONVERSATION_PARAM);

    if (!hasLegacy && (current ?? null) === conversationId) {
        return null;
    }

    const next = new URLSearchParams(params);
    next.delete(LEGACY_CONVERSATION_PARAM);
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
