// sharedMessage.ts
// Reading the extra facts a message carries in a shared conversation.
//
// A personal conversation has exactly one human, so a user message needs no attribution
// and both interfaces label them "You" without asking. A shared conversation has several,
// and a thread that does not say who wrote what is unreadable — so these fields are only
// ever populated there, and every consumer has to tolerate their absence.

import { messageToPlainText } from './messageText';
import type { ChatMessage, CollaborationMessage, CollaborationReplyContext } from './types';

/** How much of a message to quote when it is being replied to. */
const REPLY_PREVIEW_LENGTH = 140;

function asShared(message: ChatMessage | undefined): CollaborationMessage | undefined {
    return message as CollaborationMessage | undefined;
}

/**
 * The user id of whoever wrote a message, when it is known.
 *
 * Read from `sender`, which `serialize_collaboration_message` copies out of the message's
 * metadata. Assistant messages have no sender, and neither does anything in a personal
 * conversation.
 */
export function messageSenderId(message: ChatMessage | undefined): string {
    const shared = asShared(message);
    return String(
        shared?.sender?.user_id ??
            (shared?.metadata as { sender?: { user_id?: string } } | undefined)?.sender?.user_id ??
            '',
    ).trim();
}

/** Whether the reader wrote this message. */
export function isOwnMessage(
    message: ChatMessage | undefined,
    currentUserId: string | undefined,
): boolean {
    const senderId = messageSenderId(message);
    return Boolean(currentUserId && senderId && senderId === currentUserId);
}

/**
 * Who to credit a message to on screen.
 *
 * Returns an empty string when there is nobody to name — a personal conversation, or an
 * assistant reply — so the caller renders no attribution line rather than a placeholder.
 * The reader's own messages are labelled "You", which is both shorter and how every other
 * chat interface reads.
 */
export function messageAuthorName(
    message: ChatMessage | undefined,
    currentUserId: string | undefined,
): string {
    const shared = asShared(message);
    const sender =
        shared?.sender ??
        (shared?.metadata as { sender?: { display_name?: string; email?: string } } | undefined)
            ?.sender;
    if (!sender) {
        return '';
    }
    if (isOwnMessage(message, currentUserId)) {
        return 'You';
    }
    return String(sender.display_name ?? '').trim() || String(sender.email ?? '').trim();
}

/**
 * What a message is replying to, resolved against the messages on screen.
 *
 * The server stores only `reply_to_message_id`; the author and the quoted text have to be
 * looked up, which is why this takes the whole list. Returns null when the reply target is
 * not loaded — it may have been deleted, or be above the part of the thread in memory — so
 * the message renders normally rather than showing an empty quote.
 */
export function resolveReplyContext(
    message: ChatMessage | undefined,
    messages: ChatMessage[],
    currentUserId: string | undefined,
): CollaborationReplyContext | null {
    const replyToId = String(asShared(message)?.reply_to_message_id ?? '').trim();
    if (!replyToId) {
        return null;
    }

    const target = messages.find((candidate) => candidate.id === replyToId);
    if (!target) {
        return null;
    }

    return {
        message_id: replyToId,
        display_name:
            messageAuthorName(target, currentUserId) ||
            (target.role === 'assistant' ? 'Assistant' : ''),
        preview: buildReplyPreview(target),
    };
}

/** A short, plain-text quotation of a message, for a reply banner or preview. */
export function buildReplyPreview(message: ChatMessage): string {
    const text = messageToPlainText(message).replace(/\s+/g, ' ').trim();
    return text.length > REPLY_PREVIEW_LENGTH
        ? `${text.slice(0, REPLY_PREVIEW_LENGTH - 1)}\u2026`
        : text;
}

/**
 * Whether this message asked the AI to answer rather than only addressing the participants.
 *
 * Both are `role: 'user'`, so the role cannot tell them apart; `message_kind` can. Used to
 * label the request in the thread, so a reader can see why an answer appeared after one
 * message and not another.
 */
export function isAiRequest(message: ChatMessage | undefined): boolean {
    return asShared(message)?.message_kind === 'ai_request';
}
