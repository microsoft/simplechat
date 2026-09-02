// notices.ts
// Browser-session state for the two administrator-configured chat notices.
//
// The keys are deliberately the ones the classic interface already writes
// (`chat-input-actions.js` and `chat-ai-notice.js`). A dismissal is a statement about the
// person, not about which interface they happened to be looking at, so namespacing these
// the way `v2RailCollapsed` is namespaced would make a notice the user had just dismissed
// reappear when they switched interfaces in the same tab. The V2-prefixed preferences
// describe V2's own chrome; these describe the user.
//
// sessionStorage throws in some privacy modes rather than returning null, and a notice is
// not worth taking the page down for. Reads therefore fail closed -- the notice stays
// visible -- and writes report failure so the caller can say the dismissal did not stick
// instead of hiding a notice that will be back on the next page load.

/** Set for the session once the web search notice has been dismissed. */
export const WEB_SEARCH_NOTICE_SESSION_KEY = 'webSearchNoticeDismissed';

/** Prefix for the per-message-version AI notice dismissal. */
export const AI_NOTICE_SESSION_KEY_PREFIX = 'simplechat.aiNoticeDismissal';

/**
 * The session key for one version of the AI notice.
 *
 * Keyed by hash so that editing the notice text re-shows it, matching how the stored
 * server-side dismissals are invalidated.
 */
export function aiNoticeSessionKey(noticeHash: string): string {
    return `${AI_NOTICE_SESSION_KEY_PREFIX}.${noticeHash}`;
}

/** Whether the flag is set. False when session storage cannot be read. */
export function isNoticeDismissedForSession(key: string): boolean {
    try {
        return sessionStorage.getItem(key) === 'true';
    } catch (error) {
        if (!(error instanceof DOMException)) {
            throw error;
        }
        console.warn('Session storage is unavailable; the notice will remain visible.', error);
        return false;
    }
}

/** Set the flag. Returns false when session storage refused the write. */
export function dismissNoticeForSession(key: string): boolean {
    try {
        sessionStorage.setItem(key, 'true');
        return true;
    } catch (error) {
        if (!(error instanceof DOMException)) {
            throw error;
        }
        console.warn('Session storage is unavailable; the dismissal was not saved.', error);
        return false;
    }
}
