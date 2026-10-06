// sharedMessage.ts
// Reading the extra facts a message carries in a shared conversation.
//
// A personal conversation has exactly one human, so a user message needs no attribution
// and both interfaces label them "You" without asking. A shared conversation has several,
// and a thread that does not say who wrote what is unreadable — so these fields are only
// ever populated there, and every consumer has to tolerate their absence.

import { stripMentionText } from './mentions';
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

/**
 * Markdown markers taken out of a quotation, keeping the words.
 *
 * A quotation is one line of plain text, so an answer that opens with "## Answer" and bold
 * figures would otherwise quote its markers. Single underscores are left alone because
 * identifiers such as `case_id` use them.
 */
function flattenMarkdown(text: string): string {
    return text
        .replace(/^[ \t]*(`{3,}|~{3,}).*$/gm, '')
        .replace(/^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$/gm, '')
        .replace(/^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$/gm, '')
        .replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm, '')
        .replace(/^[ \t]*>[ \t]?/gm, '')
        .replace(/^[ \t]*[-*+][ \t]+/gm, '')
        .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, '$2')
        .replace(/(^|[^\w*])\*(?=\S)([^*\n]*?\S)\*(?!\w)/g, '$1$2')
        .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '$1')
        .replace(/`([^`\n]+)`/g, '$1')
        .replace(/[ \t]*\|[ \t]*/g, ' ');
}

/**
 * A short, plain-text quotation of a message, for a reply banner or preview.
 *
 * It reads like the message it quotes: the `@Name` text of the people and agent shown as
 * pills is left out, and an answer's markdown markers are dropped. A person's own text is
 * plain, so only answers and agent-posted messages are flattened.
 */
export function buildReplyPreview(message: ChatMessage): string {
    let text = messageToPlainText(message);
    if (message.role === 'assistant' || isAgentPostedMessage(message)) {
        text = flattenMarkdown(text);
    }
    const mentionNames = readMessageMentionPills(message, undefined).map((pill) => pill.label);
    if (mentionNames.length > 0) {
        // A message that was only mentions keeps them, so its quote is not empty.
        text = stripMentionText(text, mentionNames) || text;
    }
    text = text.replace(/\s+/g, ' ').trim();
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

/**
 * Whether an agent wrote this message through an action, on its sender's behalf.
 *
 * `add_conversation_message_for_current_user` (functions_simplechat_operations.py) stores such
 * messages as the user's own, since they are sent with the user's permissions, and marks them
 * with `posted_via: 'agent_action'` and `content_format: 'markdown'`. They are rendered as
 * markdown, like the agent's replies; messages people type stay plain text.
 */
export function isAgentPostedMessage(message: ChatMessage | undefined): boolean {
    const metadata = message?.metadata as { posted_via?: unknown; content_format?: unknown } | undefined;
    return (
        message?.role === 'user' &&
        metadata?.posted_via === 'agent_action' &&
        metadata?.content_format === 'markdown'
    );
}

/**
 * Whether a workflow run's mirrored reply has replaced this message in the thread.
 *
 * A run that creates a conversation and posts its own message there later mirrors its full
 * reply into the same conversation, with the maps and sources its tools returned. The server
 * then marks the run's post with `superseded_by_workflow_reply`
 * (`_hide_run_posts_superseded_by_reply` in functions_workflow_runner.py). It stays stored, and
 * in the AI's history, but showing it would repeat the reply in a form that reads as though the
 * person had written it.
 */
export function isSupersededByWorkflowReply(message: ChatMessage | undefined): boolean {
    const metadata = message?.metadata as { superseded_by_workflow_reply?: unknown } | undefined;
    return Boolean(metadata?.superseded_by_workflow_reply);
}

/** A person or the AI target a message was addressed to, drawn as a pill above its text. */
export interface MessageMentionPill {
    key: string;
    kind: 'person' | 'ai';
    label: string;
    target_type?: 'model' | 'agent' | 'image';
    /** Whether the pill names the reader. */
    self?: boolean;
}

function textValue(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * Who a message was addressed to, read from what the server stored with it.
 *
 * `metadata.ai_invocation_target` is the model or agent that was asked, and
 * `metadata.mentioned_participants` the people the server accepted as mentioned (only
 * participants who have joined). The AI target comes first, as in the classic client. Both are
 * only ever stored on a person's message in a shared conversation, so anything else has none.
 */
export function readMessageMentionPills(
    message: ChatMessage | undefined,
    currentUserId: string | undefined,
): MessageMentionPill[] {
    const metadata = message?.metadata;
    if (message?.role !== 'user' || !metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
        return [];
    }
    const record = metadata as Record<string, unknown>;
    const pills: MessageMentionPill[] = [];

    const target = record.ai_invocation_target;
    if (target && typeof target === 'object' && !Array.isArray(target)) {
        const raw = target as Record<string, unknown>;
        const label = textValue(raw.display_name) || textValue(raw.label);
        const type = textValue(raw.target_type).toLowerCase();
        if (label) {
            pills.push({
                key: 'ai',
                kind: 'ai',
                label,
                target_type: type === 'agent' || type === 'image' ? type : 'model',
            });
        }
    }

    const seen = new Set<string>();
    const mentioned = Array.isArray(record.mentioned_participants) ? record.mentioned_participants : [];
    for (const entry of mentioned) {
        const raw = (entry && typeof entry === 'object' ? entry : {}) as Record<string, unknown>;
        const userId = textValue(raw.user_id);
        const label = textValue(raw.display_name) || textValue(raw.name) || textValue(raw.email);
        if (!userId || !label || seen.has(userId)) {
            continue;
        }
        seen.add(userId);
        pills.push({
            key: `person:${userId}`,
            kind: 'person',
            label,
            self: Boolean(currentUserId) && userId === currentUserId,
        });
    }
    return pills;
}
