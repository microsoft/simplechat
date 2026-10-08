// reviewAssistApi.ts
// The Review center's side of POST /api/admin/review/<section>/assist: one request, with the
// browser's own deadline and the caller's cancel, read strictly.
//
// The server reads every record itself by id, so a request names records and nothing more. Its
// answer is checked against what was asked (lib/reviewSuggestions.ts) before anything shows it.

import { apiUrl, CREDENTIALS_MODE } from './apiClient';
import type { ReviewSectionId } from './reviewAccess';
import {
    describeReviewAssistFailure,
    parseReviewAssistResponse,
    type ReviewAssistMode,
    type TriagePostResult,
} from './reviewSuggestions';

export const REVIEW_ASSIST_PATHS: Readonly<Record<ReviewSectionId, string>> = {
    feedback: '/api/admin/review/feedback/assist',
    safety: '/api/admin/review/safety/assist',
};

/** The server stops at about 150 seconds; the browser waits a little longer for its answer. */
export const REVIEW_ASSIST_DEADLINE_MS = 170_000;

const UNREADABLE_MESSAGE = "The assistant's answer couldn't be read. Nothing was suggested.";

/**
 * Ask for suggestions about `ids`. A cancel through `signal` is `aborted`; the browser deadline
 * and a lost connection are failures the reader can retry.
 */
export async function postReviewAssist(
    section: ReviewSectionId,
    mode: ReviewAssistMode,
    ids: readonly string[],
    signal: AbortSignal,
    deadlineMs = REVIEW_ASSIST_DEADLINE_MS,
): Promise<TriagePostResult> {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, deadlineMs);
    const stop = () => controller.abort();
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', stop, { once: true });
    try {
        // A raw fetch rather than apiClient: ApiError drops the headers, and a throttled 429
        // carries its wait in Retry-After.
        const response = await fetch(apiUrl(REVIEW_ASSIST_PATHS[section]), {
            method: 'POST',
            credentials: CREDENTIALS_MODE,
            signal: controller.signal,
            headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, ids }),
        });
        const text = await response.text();
        let payload: unknown = null;
        try {
            payload = text ? JSON.parse(text) : null;
        } catch {
            payload = null;
        }
        if (signal.aborted) return { ok: false, aborted: true };
        if (!response.ok) {
            return { ok: false, failure: describeReviewAssistFailure(response.status, payload, response.headers.get('Retry-After')) };
        }
        const results = parseReviewAssistResponse(section, mode, payload, ids);
        return results ? { ok: true, results } : {
            ok: false,
            failure: { status: 502, code: 'unreadable', message: UNREADABLE_MESSAGE, retryAfterSeconds: null },
        };
    } catch {
        if (signal.aborted) return { ok: false, aborted: true };
        return {
            ok: false,
            failure: timedOut ? {
                status: 0, code: 'browser_timeout', retryAfterSeconds: null,
                message: 'The assistant took too long to answer. Nothing was suggested. Try again.',
            } : {
                status: 0, code: 'network_error', retryAfterSeconds: null,
                message: "Couldn't reach the assistant. Nothing was suggested. Check your connection and try again.",
            },
        };
    } finally {
        clearTimeout(timer);
        signal.removeEventListener('abort', stop);
    }
}
