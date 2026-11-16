// aiActivity.ts
// Which AI requests are running in the open shared conversation, for the activity line.
//
// The collaboration stream route publishes `collaboration.ai.started` when a request begins,
// `collaboration.ai.progress` with its latest step, and `collaboration.ai.finished` however it
// ends (route_backend_collaboration.CollaborationAiActivity). Every participant receives them,
// so everybody sees the same "Agent is working" line rather than only the person who asked.
//
// Several requests can run at once, for different people or agents, so the state is a list
// keyed by run id. Everything here is pure so the bookkeeping can be tested without a browser.

import { messageSenderId } from './sharedMessage';
import type { ChatMessage } from './types';

/** An AI request that has started and not yet finished. */
export interface AiActivityRun {
    run_id: string;
    display_name: string;
    target_type: 'agent' | 'model' | 'image';
    requested_by: { user_id: string; display_name: string };
    /** The person's message that asked, which the answer replies to. */
    request_message_id: string;
    /** Epoch milliseconds, on this browser's clock. */
    startedAt: number;
    /** The latest progress step, or empty before the first one. */
    step: string;
}

/** One activity event, decoded from the event stream. */
export interface AiActivityEvent {
    kind: 'started' | 'progress' | 'finished';
    run: Record<string, unknown>;
    /** When the server published it, in epoch milliseconds, or NaN when unknown. */
    occurredAt: number;
    /** Delivered as history when the subscription attached, rather than live. */
    replayed: boolean;
}

/**
 * How long a run is shown without hearing that it finished.
 *
 * A request ends with a `finished` event even when it fails or the requester disconnects, so
 * this only matters when the server itself went away mid-run. Long enough for the slowest
 * delegated agent runs, short enough that a lost run does not claim to be working all day.
 */
export const AI_ACTIVITY_MAX_AGE_MS = 15 * 60 * 1000;

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * When a run started, on this browser's clock.
 *
 * A live event is stamped with the moment it arrived, so a server clock that differs from the
 * browser's cannot make the timer start at minus ten seconds. A replayed one, from a run that
 * was already going when the reader opened the conversation, has to use the server's time,
 * capped at now for the same reason.
 */
function startedAtFor(event: AiActivityEvent, now: number): number {
    if (!event.replayed) {
        return now;
    }
    const occurred = Number.isFinite(event.occurredAt) ? event.occurredAt : now;
    return Math.min(occurred, now);
}

/** Apply one activity event to the running list. */
export function applyAiActivityEvent(
    runs: readonly AiActivityRun[],
    event: AiActivityEvent,
    now: number,
): AiActivityRun[] {
    const runId = text(event.run.run_id);
    if (!runId) {
        return [...runs];
    }

    if (event.kind === 'finished') {
        return runs.filter((run) => run.run_id !== runId);
    }

    if (event.kind === 'progress') {
        const step = text(event.run.step);
        return runs.map((run) => (run.run_id === runId && step ? { ...run, step } : run));
    }

    const startedAt = startedAtFor(event, now);
    if (now - startedAt > AI_ACTIVITY_MAX_AGE_MS) {
        return runs.filter((run) => run.run_id !== runId);
    }
    const requestedBy = (event.run.requested_by && typeof event.run.requested_by === 'object'
        ? event.run.requested_by
        : {}) as Record<string, unknown>;
    const type = text(event.run.target_type).toLowerCase();
    const run: AiActivityRun = {
        run_id: runId,
        display_name: text(event.run.display_name) || 'Assistant',
        target_type: type === 'agent' || type === 'image' ? type : 'model',
        requested_by: {
            user_id: text(requestedBy.user_id),
            display_name: text(requestedBy.display_name),
        },
        request_message_id: text(event.run.request_message_id),
        startedAt,
        step: '',
    };
    return [...runs.filter((entry) => entry.run_id !== runId), run];
}

/**
 * Drop the runs a newly arrived answer belongs to.
 *
 * The `finished` event normally does this, but the answer itself is proof the run is over, so
 * a lost or late `finished` does not leave the line up under the answer.
 */
export function finishAiRunsAnsweredBy(
    runs: readonly AiActivityRun[],
    message: { role?: string; reply_to_message_id?: unknown } | undefined,
): AiActivityRun[] {
    const replyTo = text(message?.reply_to_message_id);
    if (!replyTo || message?.role === 'user') {
        return [...runs];
    }
    return runs.filter((run) => run.request_message_id !== replyTo);
}

/** Drop runs that have outlived `AI_ACTIVITY_MAX_AGE_MS`. */
export function pruneStaleAiRuns(runs: readonly AiActivityRun[], now: number): AiActivityRun[] {
    return runs.filter((run) => now - run.startedAt <= AI_ACTIVITY_MAX_AGE_MS);
}

/**
 * The lines to draw: every broadcast run, plus the reader's own request until its broadcast
 * arrives. The local one is dropped as soon as a broadcast run of the reader's exists, so the
 * same request is never listed twice.
 */
export function visibleAiRuns(
    runs: readonly AiActivityRun[],
    local: AiActivityRun | null,
    currentUserId: string | undefined,
    now: number,
): AiActivityRun[] {
    const live = pruneStaleAiRuns(runs, now);
    const ownBroadcast = Boolean(currentUserId)
        && live.some((run) => run.requested_by.user_id === currentUserId);
    return local && !ownBroadcast ? [...live, local] : live;
}

/** "0:42", "4:05", "1:02:09". */
export function formatAiActivityElapsed(milliseconds: number): string {
    const total = Math.max(0, Math.floor(milliseconds / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = String(total % 60).padStart(2, '0');
    return hours > 0
        ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}`
        : `${minutes}:${seconds}`;
}

/** The sentence for one run, from the reader's point of view. */
export function describeAiActivityRun(run: AiActivityRun, currentUserId: string | undefined): string {
    const requester = run.requested_by.user_id && run.requested_by.user_id === currentUserId
        ? 'you'
        : run.requested_by.display_name;
    return requester
        ? `${run.display_name} is working for ${requester}`
        : `${run.display_name} is working`;
}

/**
 * The reader's own request, drawn from their stream until its `started` event arrives.
 *
 * The request is sent before the event can come back, so without this the line would appear
 * a moment after the message instead of with it. It reads the target from the reader's latest
 * message (the same `ai_invocation_target` the server stores; the copy shown while sending has
 * no sender yet). It has no step: the server describes steps in plain words, and the broadcast
 * run replaces this one within a moment.
 */
export function localAiRun(input: {
    messages: readonly ChatMessage[];
    currentUserId: string | undefined;
    now: number;
}): AiActivityRun | null {
    const request = [...input.messages].reverse().find((message) => {
        const senderId = messageSenderId(message);
        return message.role === 'user' && (!senderId || senderId === input.currentUserId);
    });
    if (!request) {
        return null;
    }
    const metadata = (request.metadata && typeof request.metadata === 'object' && !Array.isArray(request.metadata)
        ? request.metadata
        : {}) as Record<string, unknown>;
    const target = (metadata.ai_invocation_target && typeof metadata.ai_invocation_target === 'object'
        ? metadata.ai_invocation_target
        : {}) as Record<string, unknown>;
    const type = text(target.target_type).toLowerCase();
    const sentAt = Date.parse(String(request.timestamp ?? ''));
    const recent = Number.isFinite(sentAt) && input.now - sentAt <= AI_ACTIVITY_MAX_AGE_MS;
    return {
        run_id: 'local',
        display_name: text(target.display_name) || 'Assistant',
        target_type: type === 'agent' || type === 'image' ? type : 'model',
        requested_by: { user_id: input.currentUserId ?? '', display_name: '' },
        request_message_id: String(request.id ?? ''),
        startedAt: recent ? Math.min(sentAt, input.now) : input.now,
        step: '',
    };
}
