// threads.ts
// Reading a message's retry-thread bookkeeping.
//
// A retry creates a new *attempt* within a thread. The server records this under
// `metadata.thread_info`, and `thread_attempt` is ONE-BASED: every creation site in the
// application writes `'thread_attempt': 1` for a first attempt.
//
// `/api/get_messages` filters the list to the active attempt
// (route_backend_conversations.py), so the number of attempts can never be counted from the
// messages on screen. Only the switch-attempt endpoint reports the full set.

import type { ChatMessage } from './types';

export interface ThreadInfo {
    thread_id?: string;
    thread_attempt?: number;
    active_thread?: boolean;
    previous_thread_id?: string;
}

export function threadInfo(message: ChatMessage | undefined): ThreadInfo {
    const metadata = message?.metadata as Record<string, unknown> | undefined;
    const info = metadata?.thread_info;
    return (info && typeof info === 'object' ? info : {}) as ThreadInfo;
}

export function messageThreadId(message: ChatMessage | undefined): string | undefined {
    const id = threadInfo(message).thread_id;
    return typeof id === 'string' && id ? id : undefined;
}

/** Which attempt this message belongs to. One-based, defaulting to the first. */
export function currentAttempt(message: ChatMessage | undefined): number {
    const attempt = threadInfo(message).thread_attempt;
    return typeof attempt === 'number' && attempt > 0 ? attempt : 1;
}

export interface AttemptState {
    /** Whether attempt navigation should be offered at all. */
    show: boolean;
    current: number;
    /** Total attempts, when it is actually known. Null means "at least `current`". */
    total: number | null;
}

/**
 * Decide what the attempt control should say.
 *
 * Showing "1 of 1" on every message is noise, and showing a total that was guessed from the
 * visible messages is wrong — that list only ever holds one attempt. So the control appears
 * only once more than one attempt is known to exist, which is true when either:
 *
 *   - this message is attempt 2 or later, which proves earlier attempts exist, or
 *   - the switch-attempt endpoint has already reported the set for this thread.
 *
 * Until an exact set is known, the total is null and the caller shows the attempt number
 * alone rather than inventing a denominator.
 */
export function attemptState(
    message: ChatMessage | undefined,
    attemptsByThread: Record<string, number[]>,
): AttemptState {
    const current = currentAttempt(message);
    const threadId = messageThreadId(message);
    const known = threadId ? attemptsByThread[threadId] : undefined;

    if (Array.isArray(known) && known.length > 1) {
        return { show: true, current, total: known.length };
    }

    if (current > 1) {
        return { show: true, current, total: null };
    }

    return { show: false, current, total: null };
}
