// m365PendingActions.ts
// Pure rules for the Microsoft 365 outgoing-action cards (no React, no network).
//
// A card is a saved email or calendar invitation that is waiting for the owner to send or
// cancel it. These helpers decide which server snapshot to trust, where a card belongs in the
// conversation and what a stream frame or history message is carrying. They mirror the classic
// m365-pending-actions.js behavior so both interfaces treat the same saved action the same way.

import {
    ACTIONABLE_PENDING_STATUSES,
    isPendingAction,
    pendingActionNeedsFullReview,
    type PendingAction,
} from './approvalsApi';
import { normalizePendingActionId } from './conversationUrl';

export type PendingActionTone = 'info' | 'warn' | 'danger' | 'ok';

export interface PendingActionNotice {
    text: string;
    tone: PendingActionTone;
}

/** Where in the conversation a card was seen. Every field is a trimmed string, '' when unknown. */
export interface PendingActionReference {
    messageId: string;
    userMessageId: string;
    fallbackMessageId: string;
    requestId: string;
}

export const EMPTY_PENDING_ACTION_REFERENCE: PendingActionReference = Object.freeze({
    messageId: '',
    userMessageId: '',
    fallbackMessageId: '',
    requestId: '',
});

/** The slot that renders cards for the reply that is still streaming. */
export const STREAMING_ANCHOR = '@streaming';

/** The conversation-level section for cards that have no visible originating message. */
export const ORPHAN_ANCHOR = '';

/** How long a card waits before it asks the server about a due or in-progress action again. */
export const PENDING_ACTION_POLL_MS = 15_000;

export const PENDING_ACTIONS_UNAVAILABLE_MESSAGE =
    'Microsoft 365 actions were saved, but their cards could not be loaded. Reload the conversation to recover them. Do not repeat the request.';

/* Links ---------------------------------------------------------------------- */

/** An https link without credentials, or '' so the card shows no link at all. */
export function safeWebLinkUrl(value: unknown): string {
    if (typeof value !== 'string' || !value) return '';
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
    } catch {
        return '';
    }
}

/** The in-app route for a saved sharing decision, falling back to the Approvals list. */
export function safeApprovalDecisionHref(value: unknown): string {
    return typeof value === 'string' && value ? `/approvals/m365/${encodeURIComponent(value)}` : '/approvals/m365';
}

/* Display -------------------------------------------------------------------- */

export function countdownText(action: PendingAction, now: number = Date.now()): string {
    const due = Date.parse(action.auto_send_at_utc ?? '');
    if (!Number.isFinite(due)) return 'The scheduled time is unavailable. Refresh status to check it.';
    const seconds = Math.max(0, Math.ceil((due - now) / 1000));
    return seconds
        ? `Scheduled in ${Math.floor(seconds / 60)}m ${seconds % 60}s.`
        : 'Scheduled time reached. Waiting for the server delivery status.';
}

export function actionSubject(action: PendingAction): string {
    return action.subject || action.summary?.subject || '(No subject)';
}

/* Identity ------------------------------------------------------------------- */

// The id rule lives with the chat URL vocabulary so a link and a card agree on what is safe.
export { normalizePendingActionId };

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : typeof value === 'number' ? String(value) : '';
}

/** Merge references, letting any field the newer one knows replace what the older one had. */
export function mergeReference(
    current: PendingActionReference,
    next: Partial<PendingActionReference> | null | undefined,
): PendingActionReference {
    if (!next) return current;
    const merged: PendingActionReference = {
        messageId: text(next.messageId) || current.messageId,
        userMessageId: text(next.userMessageId) || current.userMessageId,
        fallbackMessageId: text(next.fallbackMessageId) || current.fallbackMessageId,
        requestId: text(next.requestId) || current.requestId,
    };
    return merged.messageId === current.messageId &&
        merged.userMessageId === current.userMessageId &&
        merged.fallbackMessageId === current.fallbackMessageId &&
        merged.requestId === current.requestId
        ? current
        : merged;
}

/* Which snapshot to trust ---------------------------------------------------- */

export function isActionableStatus(status: string | undefined): boolean {
    return ACTIONABLE_PENDING_STATUSES.has(status ?? '');
}

/**
 * Whether a snapshot must be ignored because the card already holds something newer.
 *
 * A late list page or stream frame must never move a finished action back to a sendable state,
 * and a version the card has already moved past must not come back.
 */
export function isStaleSnapshot(
    previous: PendingAction,
    seenVersions: ReadonlySet<string>,
    next: PendingAction,
    authoritative: boolean,
): boolean {
    const older = Date.parse(next.updated_at ?? '') < Date.parse(previous.updated_at ?? '');
    const terminalRegression =
        !authoritative && !isActionableStatus(previous.status) && isActionableStatus(next.status);
    const revisited = next.version !== previous.version && seenVersions.has(next.version ?? '');
    return older || terminalRegression || revisited;
}

/** The permissions the owner still has to grant, or null when nothing is needed or it was acknowledged. */
export function hydratedAuth(
    action: PendingAction,
    authoritative: boolean,
    acknowledgedVersion: string,
    current: Record<string, unknown> | null,
): { auth: Record<string, unknown> | null; acknowledgedVersion: string } {
    if (action.viewer_is_owner === false) return { auth: null, acknowledgedVersion: '' };
    if (action.auth_required === true) {
        if (action.version && acknowledgedVersion === action.version) {
            return { auth: null, acknowledgedVersion };
        }
        return {
            auth: {
                auth_required: true,
                sources: Array.isArray(action.sources)
                    ? action.sources
                    : [action.graph_resource_type === 'calendar' ? 'calendar' : 'email'],
                scopes: Array.isArray(action.scopes) ? action.scopes : [],
            },
            acknowledgedVersion,
        };
    }
    if (authoritative && action.auth_required === false) return { auth: null, acknowledgedVersion };
    return { auth: current, acknowledgedVersion };
}

/** Whether the complete saved content was already loaded for this exact version. */
export function hasLoadedFullDetails(action: PendingAction, authoritative: boolean): boolean {
    return (
        authoritative &&
        action.review_details_required === false &&
        !pendingActionNeedsFullReview(action) &&
        typeof action.summary?.body_preview === 'string'
    );
}

/* Polling -------------------------------------------------------------------- */

/** A scheduled action that will be sent by the server, with a usable time. */
export function isScheduled(action: PendingAction): boolean {
    return (
        action.will_auto_send === true &&
        isActionableStatus(action.status) &&
        Number.isFinite(Date.parse(action.auto_send_at_utc ?? ''))
    );
}

/** Whether the card should tick once a second (to show the countdown or watch a send finish). */
export function needsTicking(action: PendingAction): boolean {
    return (action.will_auto_send === true && isActionableStatus(action.status)) || action.status === 'sending';
}

/** Whether a tick should ask the server again: the send time passed, or a send is in progress. */
export function isPollDue(action: PendingAction, busy: boolean, nextRefreshAt: number, now: number = Date.now()): boolean {
    if (busy || now < nextRefreshAt) return false;
    const due = Date.parse(action.auto_send_at_utc ?? '');
    return (isScheduled(action) && due <= now) || action.status === 'sending';
}

/* Reading what the server sent ----------------------------------------------- */

/** Every saved action an event, frame or message carries, ignoring anything that is not one. */
export function pendingActionsFromPayload(payload: unknown): PendingAction[] {
    if (!payload || typeof payload !== 'object') return [];
    const record = payload as { pending_action?: unknown; m365_pending_actions?: unknown };
    const found: PendingAction[] = [];
    if (isPendingAction(record.pending_action)) found.push(record.pending_action);
    if (Array.isArray(record.m365_pending_actions)) {
        for (const item of record.m365_pending_actions) {
            if (isPendingAction(item)) found.push(item);
        }
    }
    return found;
}

/** The error message when the server saved actions but could not build their cards. */
export function pendingActionsErrorFromPayload(payload: unknown): string {
    if (!payload || typeof payload !== 'object') return '';
    const failure = (payload as { m365_pending_actions_error?: unknown }).m365_pending_actions_error;
    if (!failure) return '';
    const message = typeof failure === 'object' ? text((failure as { message?: unknown }).message) : text(failure);
    return message || PENDING_ACTIONS_UNAVAILABLE_MESSAGE;
}

/** Ids a message says belong to it, whether or not their cards were loaded with it. */
export function referencedActionIds(message: unknown): string[] {
    const ids = (message as { metadata?: { m365_pending_action_ids?: unknown } } | null)?.metadata
        ?.m365_pending_action_ids;
    if (!Array.isArray(ids)) return [];
    const unique = new Set<string>();
    for (const value of ids) {
        const id = normalizePendingActionId(value);
        if (id) unique.add(id);
    }
    return [...unique];
}

/** The reference a history or live message gives to the cards it carries. */
export function referenceForMessage(message: unknown): PendingActionReference {
    const record = (message ?? {}) as {
        id?: unknown;
        message_id?: unknown;
        request_id?: unknown;
        metadata?: { m365_request_id?: unknown };
    };
    return {
        ...EMPTY_PENDING_ACTION_REFERENCE,
        messageId: text(record.id) || text(record.message_id),
        requestId: text(record.metadata?.m365_request_id) || text(record.request_id),
    };
}

/**
 * The reference for cards that arrive on a chat stream frame.
 *
 * A creation frame (`m365_pending_action`) has no reply yet, so its message id is never used;
 * the card is placed under the user turn that caused it until the reply is saved.
 */
export function referenceForStreamFrame(
    frame: unknown,
    options: { messageId?: string; userMessageId?: string; requestId?: string } = {},
): PendingActionReference {
    const record = (frame ?? {}) as {
        type?: unknown;
        message_id?: unknown;
        user_message_id?: unknown;
        request_id?: unknown;
        metadata?: { m365_request_id?: unknown };
    };
    const fromFrame = record.type === 'm365_pending_action' ? '' : text(record.message_id);
    return {
        messageId: text(options.messageId) || fromFrame,
        userMessageId: text(record.user_message_id) || text(options.userMessageId),
        fallbackMessageId: text(options.userMessageId),
        requestId: text(record.request_id) || text(record.metadata?.m365_request_id) || text(options.requestId),
    };
}

/** A signature that changes only when a message brings new or different cards. */
export function messageTrackKey(message: unknown): string {
    const record = (message ?? {}) as { id?: unknown; message_id?: unknown; m365_pending_actions?: unknown };
    const messageId = text(record.id) || text(record.message_id);
    if (!messageId) return '';
    const cards = Array.isArray(record.m365_pending_actions)
        ? record.m365_pending_actions
              .filter(isPendingAction)
              .map((action) => `${action.id}@${action.version ?? ''}@${action.updated_at ?? ''}@${action.status}`)
        : [];
    const ids = referencedActionIds(message);
    if (!cards.length && !ids.length) return '';
    return [messageId, referenceForMessage(message).requestId, cards.join(','), ids.join(',')].join('|');
}

/* Placement ------------------------------------------------------------------ */

export interface AnchorContext {
    /** Ids of the messages the thread is showing. */
    visibleMessageIds: ReadonlySet<string>;
    /** For each request id, the last visible message that belongs to it. */
    lastMessageByRequestId: ReadonlyMap<string, string>;
    /** The user message whose reply is still streaming, or '' when nothing is streaming. */
    streamingUserMessageId: string;
}

/**
 * Where a card is drawn: the id of a visible message, the streaming slot, or the
 * conversation-level section when nothing visible claims it.
 */
export function resolveAnchor(
    reference: PendingActionReference,
    action: Pick<PendingAction, 'request_id'>,
    context: AnchorContext,
): string {
    const visible = (id: string) => Boolean(id) && context.visibleMessageIds.has(id);
    if (visible(reference.messageId)) return reference.messageId;
    const streaming = context.streamingUserMessageId;
    if (streaming && (reference.userMessageId === streaming || reference.fallbackMessageId === streaming)) {
        return STREAMING_ANCHOR;
    }
    if (visible(reference.userMessageId)) return reference.userMessageId;
    if (visible(reference.fallbackMessageId)) return reference.fallbackMessageId;
    const requestId = reference.requestId || text(action.request_id);
    const byRequest = requestId ? context.lastMessageByRequestId.get(requestId) : undefined;
    return byRequest && context.visibleMessageIds.has(byRequest) ? byRequest : ORPHAN_ANCHOR;
}

/** Index the visible messages by request id so anchors do not scan the thread per card. */
export function lastMessageByRequestId(
    messages: ReadonlyArray<{ id?: unknown; metadata?: { m365_request_id?: unknown } }>,
): Map<string, string> {
    const byRequest = new Map<string, string>();
    for (const message of messages) {
        const id = text(message.id);
        const requestId = text(message.metadata?.m365_request_id);
        if (id && requestId) byRequest.set(requestId, id);
    }
    return byRequest;
}

/** The newest user message in a thread: the turn a reply that is still streaming answers. */
export function latestUserMessageId(messages: ReadonlyArray<{ id?: unknown; role?: unknown }>): string {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (message.role === 'user' && text(message.id)) return text(message.id);
    }
    return '';
}
