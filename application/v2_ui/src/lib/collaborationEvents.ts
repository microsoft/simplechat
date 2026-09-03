// collaborationEvents.ts
// Subscribing to a shared conversation's server-sent event stream.
//
// The stream is what makes a shared conversation shared: another participant's message,
// a member being added or removed, a mask being applied and somebody typing all arrive
// here rather than being polled for.
//
// Two properties of the endpoint shape this module, and neither is optional to handle:
//
//   - **It replays.** `iter_events` starts from `start_index=0`, so attaching delivers the
//     conversation's entire event history before any live event. Treating those as new
//     would append the whole thread again on every reconnect. They are recognised by
//     `occurred_at` predating the subscription and dropped.
//   - **`EventSource` reconnects by itself,** and reattaches from the beginning, so the
//     replay above happens again after every network blip. De-duplication is therefore by
//     event identity and has to survive reconnects, not just the first attach.
//
// The frames are JSON envelopes on the default `message` event, unlike the chat stream,
// which puts its discriminator inside the data. `event_type` is the discriminator here.

import { collaborationEventsUrl } from './collaboration';
import { API_BASE } from './apiClient';
import type {
    CollaborationConversation,
    CollaborationEvent,
    CollaborationMessage,
    CollaborationParticipant,
} from './types';

/**
 * How far before the subscription an event may have occurred and still count as live.
 *
 * Clock skew between the browser and the server is real, and an event published in the
 * same instant the subscription opened is a genuine one. A second of tolerance matches the
 * classic client and is far shorter than the gap to any actually-replayed history.
 */
const REPLAY_TOLERANCE_MS = 1000;

/**
 * How many event keys to remember.
 *
 * Bounded because a long-lived conversation would otherwise grow this set without limit.
 * It only has to cover one replay window, and a replay is bounded by the conversation's
 * own event history.
 */
const MAX_REMEMBERED_EVENTS = 2000;

/**
 * Fields of a serialized conversation that describe the *viewer* rather than the conversation.
 *
 * This distinction is why `conversationFactsOnly` exists.
 * `serialize_collaboration_conversation` computes all of these from the `current_user_id`
 * it is called with — and every route that publishes an event calls it with the user who
 * *caused* the event, then broadcasts that one dict to every subscriber. So the copy
 * arriving here carries somebody else's permissions, pin state and membership status.
 *
 * Taking them at face value is harmful in both directions: a participant leaving publishes
 * a conversation serialized for themselves, in which `can_post_messages` is now false,
 * which would disable everyone else's composer; and an owner acting publishes one in which
 * `can_delete_conversation` is true, which would offer every member a "Delete for everyone"
 * button the server then refuses.
 */
const VIEWER_SCOPED_FIELDS = [
    'can_manage_members',
    'can_manage_roles',
    'can_accept_invite',
    'can_post_messages',
    'can_delete_conversation',
    'can_leave_conversation',
    'current_user_role',
    'membership_status',
    'is_pinned',
    'is_hidden',
    'has_unread_assistant_response',
    'last_unread_assistant_message_id',
    'last_unread_assistant_at',
] as const;

/**
 * Strip the fields of a broadcast conversation that belong to whoever triggered the event.
 *
 * What remains — title, participants, counts, timestamps, scope, classification — means the
 * same thing to every reader and is safe to apply directly. The viewer-scoped fields have to
 * be re-read for the reader instead, which is what makes a membership change a reason to
 * fetch rather than a payload to trust.
 */
export function conversationFactsOnly(
    conversation: CollaborationConversation,
): Partial<CollaborationConversation> {
    const facts: Record<string, unknown> = { ...conversation };
    for (const field of VIEWER_SCOPED_FIELDS) {
        delete facts[field];
    }
    return facts as Partial<CollaborationConversation>;
}

export interface CollaborationEventHandlers {
    onMessageCreated?: (
        message: CollaborationMessage,
        conversation: CollaborationConversation | undefined,
    ) => void;
    onMessageDeleted?: (
        messageId: string,
        deletedByUserId: string | undefined,
        conversation: CollaborationConversation | undefined,
    ) => void;
    onMessageMasked?: (
        message: CollaborationMessage,
        updatedByUserId: string | undefined,
    ) => void;
    onConversationUpdated?: (conversation: CollaborationConversation) => void;
    onConversationDeleted?: (conversationId: string) => void;
    onMembersInvited?: (
        participants: CollaborationParticipant[],
        conversation: CollaborationConversation | undefined,
    ) => void;
    onMemberRemoved?: (
        participant: CollaborationParticipant | undefined,
        conversation: CollaborationConversation | undefined,
    ) => void;
    onMemberRoleUpdated?: (
        participant: CollaborationParticipant | undefined,
        conversation: CollaborationConversation | undefined,
    ) => void;
    onInviteAnswered?: (
        participant: CollaborationParticipant | undefined,
        accepted: boolean,
        conversation: CollaborationConversation | undefined,
    ) => void;
    onTyping?: (
        user: CollaborationParticipant | undefined,
        isTyping: boolean,
        expiresAt: string | undefined,
    ) => void;
}

/**
 * Identity of one event, for de-duplication.
 *
 * The envelope carries no id of its own, so identity is assembled from what distinguishes
 * one event from another: the conversation, the kind, the subject it concerns, and when it
 * happened. Two genuinely distinct events cannot collide on all four.
 */
function eventKey(event: CollaborationEvent): string {
    const payload = event.payload ?? {};
    const subject =
        payload.message?.id ??
        payload.message_id ??
        payload.participant?.user_id ??
        payload.user?.user_id ??
        payload.deleted_by_user_id ??
        '';
    return [
        event.conversation_id ?? payload.conversation?.id ?? '',
        event.event_type ?? '',
        subject,
        event.occurred_at ?? '',
    ].join('|');
}

/**
 * Parse a server timestamp to epoch milliseconds.
 *
 * `utc_now_iso` does not always emit a zone designator, and `Date.parse` reads a bare
 * timestamp as *local* time. On a browser west of UTC that makes every replayed event look
 * like it happened in the future, so nothing is ever recognised as a replay. Appending `Z`
 * when no offset is present is what stops that.
 */
export function parseEventTimestamp(timestamp: string | undefined): number {
    const value = String(timestamp ?? '').trim();
    if (!value) {
        return Number.NaN;
    }
    if (/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) {
        return Date.parse(value);
    }
    const asUtc = Date.parse(`${value}Z`);
    return Number.isNaN(asUtc) ? Date.parse(value) : asUtc;
}

/** Whether this event predates the subscription and is therefore replayed history. */
export function isReplayedEvent(event: CollaborationEvent, subscribedAt: number): boolean {
    const occurredAt = parseEventTimestamp(event.occurred_at);
    if (Number.isNaN(occurredAt)) {
        // An unparseable timestamp cannot be shown to be history, and dropping a live event
        // is worse than replaying one: de-duplication catches the repeat either way.
        return false;
    }
    return occurredAt < subscribedAt - REPLAY_TOLERANCE_MS;
}

/**
 * Route one decoded envelope to the matching handler.
 *
 * Exported so the dispatch can be tested without an `EventSource`.
 */
export function dispatchCollaborationEvent(
    event: CollaborationEvent,
    handlers: CollaborationEventHandlers,
): void {
    const payload = event.payload ?? {};
    const conversation = payload.conversation;

    switch (event.event_type) {
        case 'collaboration.message.created':
            if (payload.message) {
                handlers.onMessageCreated?.(payload.message, conversation);
            }
            return;

        case 'collaboration.message.deleted':
            if (payload.message_id) {
                handlers.onMessageDeleted?.(
                    String(payload.message_id),
                    payload.deleted_by_user_id,
                    conversation,
                );
            }
            return;

        case 'collaboration.message.masked':
            if (payload.message) {
                handlers.onMessageMasked?.(payload.message, payload.updated_by_user_id);
            }
            return;

        case 'collaboration.typing.updated':
            handlers.onTyping?.(payload.user, payload.is_typing !== false, payload.expires_at);
            return;

        case 'collaboration.member.invited':
            handlers.onMembersInvited?.(payload.participants ?? [], conversation);
            break;

        case 'collaboration.member.removed':
            handlers.onMemberRemoved?.(payload.participant, conversation);
            break;

        case 'collaboration.member.role_updated':
            handlers.onMemberRoleUpdated?.(payload.participant, conversation);
            break;

        case 'collaboration.invite.accepted':
            handlers.onInviteAnswered?.(payload.participant, true, conversation);
            break;

        case 'collaboration.invite.declined':
            handlers.onInviteAnswered?.(payload.participant, false, conversation);
            break;

        case 'collaboration.deleted':
            handlers.onConversationDeleted?.(
                String(event.conversation_id ?? conversation?.id ?? ''),
            );
            return;

        case 'collaboration.created':
        case 'collaboration.updated':
            break;

        default:
            return;
    }

    // Every event above that falls through here carries the conversation in its payload, and
    // it is the freshest membership the client will see — the routes serialize it *after*
    // applying the change. Handled once here rather than in each branch.
    if (conversation) {
        handlers.onConversationUpdated?.(conversation);
    }
}

/**
 * Attach to a shared conversation's event stream.
 *
 * Returns a function that detaches. Calling it is required when leaving the conversation:
 * `EventSource` reconnects on its own, so an abandoned subscription keeps a connection
 * open and keeps feeding another conversation's messages into the handlers.
 */
export function subscribeToCollaborationEvents(
    conversationId: string,
    handlers: CollaborationEventHandlers,
): () => void {
    if (typeof EventSource === 'undefined' || !conversationId) {
        return () => {};
    }

    const subscribedAt = Date.now();
    const seen = new Set<string>();

    const source = new EventSource(collaborationEventsUrl(conversationId), {
        // Only meaningful cross-origin, where the session cookie would otherwise be
        // withheld. Same-origin deployments send it regardless.
        withCredentials: Boolean(API_BASE),
    });

    source.onmessage = (frame: MessageEvent<string>) => {
        if (!frame?.data) {
            return;
        }

        let event: CollaborationEvent;
        try {
            event = JSON.parse(frame.data) as CollaborationEvent;
        } catch {
            // A malformed frame is not worth tearing the subscription down for.
            return;
        }

        const key = eventKey(event);
        if (key) {
            if (seen.has(key)) {
                return;
            }
            if (seen.size >= MAX_REMEMBERED_EVENTS) {
                seen.clear();
            }
            seen.add(key);
        }

        if (isReplayedEvent(event, subscribedAt)) {
            return;
        }

        dispatchCollaborationEvent(event, handlers);
    };

    source.onerror = () => {
        // Left to reconnect on its own. Surfacing this would flag every routine
        // reconnection as a failure, and the thread stays readable throughout.
    };

    return () => source.close();
}
