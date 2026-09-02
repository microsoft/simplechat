// conversationBadges.ts
// The badges shown beside a conversation title.
//
// This reproduces `addChatTypeBadges` and `renderConversationHeaderBadges`
// (static/js/chat/chat-conversations.js) so the two interfaces agree about what a
// conversation is bound to.
//
// Everything here is derived from the conversation's own metadata. An earlier version read
// the user's globally active group instead, which is why every conversation showed the same
// badge no matter which one was open.

import type { Conversation, ConversationMetadata } from './types';

export type WorkspaceBadgeTone = 'group' | 'public' | 'shared';

export interface WorkspaceBadge {
    tone: WorkspaceBadgeTone;
    label: string;
}

/**
 * Anything carrying the two fields a badge is derived from.
 *
 * Both the metadata endpoint and the conversation feed supply `chat_type` and `context`,
 * because the feed returns the whole conversation document — `_strip_internal_feed_fields`
 * removes only `_feed_source`. That is what lets the conversation list badge every row
 * without fetching metadata per row.
 */
export type BadgeSource = ConversationMetadata | Conversation;

interface ContextEntry {
    type?: string;
    scope?: string;
    name?: string;
    id?: string;
}

function contexts(metadata: BadgeSource | null | undefined): ContextEntry[] {
    const value = metadata?.context;
    return Array.isArray(value) ? (value as ContextEntry[]) : [];
}

/** The context a conversation is primarily bound to, for a given scope. */
function primaryContext(
    metadata: BadgeSource | null | undefined,
    scope: 'group' | 'public',
): ContextEntry | undefined {
    return contexts(metadata).find(
        (entry) => entry?.type === 'primary' && entry?.scope === scope,
    );
}

/**
 * Resolve the conversation's chat type.
 *
 * `chat_type` is authoritative when present. When it is absent the classic client infers the
 * type from the primary context's scope, and conversations predating the field rely on that
 * fallback, so it is reproduced here rather than defaulting everything to personal.
 */
export function resolveChatType(metadata: BadgeSource | null | undefined): string {
    const declared = String(metadata?.chat_type ?? '').trim();
    if (declared) {
        return declared === 'personal' ? 'personal_single_user' : declared;
    }

    const primary = contexts(metadata).find((entry) => entry?.type === 'primary');
    switch (primary?.scope) {
        case 'group':
            return 'group-single-user';
        case 'public':
            return 'public';
        default:
            return 'personal_single_user';
    }
}

/**
 * The single workspace badge for a conversation, or null when it needs none.
 *
 * Personal conversations deliberately get no badge: it would be on almost every
 * conversation and would say nothing.
 */
export function workspaceBadge(
    metadata: BadgeSource | null | undefined,
): WorkspaceBadge | null {
    const chatType = resolveChatType(metadata);

    if (chatType === 'personal_multi_user') {
        return { tone: 'shared', label: 'shared' };
    }

    if (chatType.startsWith('group')) {
        const name = (primaryContext(metadata, 'group')?.name ?? '').trim();
        return { tone: 'group', label: name || 'group' };
    }

    if (chatType.startsWith('public')) {
        const name = (primaryContext(metadata, 'public')?.name ?? '').trim();
        return { tone: 'public', label: name ? `public - ${name}` : 'public' };
    }

    return null;
}

/** Classification labels, which the route may return as an array or a single string. */
export function classificationLabels(
    metadata: ConversationMetadata | null | undefined,
): string[] {
    const value = metadata?.classification;
    if (Array.isArray(value)) {
        return value.map((entry) => String(entry ?? '').trim()).filter(Boolean);
    }
    if (typeof value === 'string' && value.trim()) {
        return [value.trim()];
    }
    return [];
}

export interface ClassificationCategory {
    label?: string;
    color?: string;
}

/** Colour configured for a classification label, if the deployment defines one. */
export function classificationColor(
    label: string,
    categories: ClassificationCategory[] | undefined,
): string | undefined {
    const match = (categories ?? []).find((category) => category?.label === label);
    return match?.color;
}

/**
 * Whether a background colour needs dark text on top of it.
 *
 * Classification colours are configured per deployment and can be anything, so the contrast
 * has to be computed rather than assumed. Uses the standard luminance weighting.
 */
export function isLightColor(color: string | undefined): boolean {
    if (!color) {
        return false;
    }

    let hex = color.trim().replace('#', '');
    if (hex.length === 3) {
        hex = hex
            .split('')
            .map((character) => character + character)
            .join('');
    }
    if (hex.length !== 6 || !/^[0-9a-f]{6}$/i.test(hex)) {
        return false;
    }

    const red = parseInt(hex.slice(0, 2), 16);
    const green = parseInt(hex.slice(2, 4), 16);
    const blue = parseInt(hex.slice(4, 6), 16);
    return (red * 299 + green * 587 + blue * 114) / 1000 > 155;
}

export type ScopeLockState = 'hidden' | 'locked' | 'unlocked';

/**
 * Scope lock indicator state.
 *
 * Null or undefined means no workspace data has been used yet, which is different from being
 * unlocked, so it shows nothing at all rather than an open padlock.
 */
export function scopeLockState(
    metadata: ConversationMetadata | null | undefined,
): ScopeLockState {
    const locked = metadata?.scope_locked;
    if (locked === null || locked === undefined) {
        return 'hidden';
    }
    return locked ? 'locked' : 'unlocked';
}
