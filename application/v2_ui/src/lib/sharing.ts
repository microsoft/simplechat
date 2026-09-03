// sharing.ts
// Deciding how a conversation can be shared, and therefore which endpoint an invite uses.
//
// There are three cases and they are not interchangeable. A conversation that is already
// shared takes new members directly. A group conversation is converted through the group
// route, which additionally restricts the invitees to that group's members. Anything else
// is converted through the personal route. Sending an invite to the wrong one of these
// either fails or, worse, creates a second shared conversation alongside the first.
//
// Mirrors `addParticipantToConversation` and `canUseParticipantFlow` in
// chat-collaboration.js.

import { isCollaborative } from './types';
import type { Conversation, ConversationMetadata } from './types';
import type { ParticipantsPanelTarget } from '../stores/collaborationStore';

/**
 * Chat types that can be shared.
 *
 * Public-workspace conversations are absent deliberately: they have no conversion route,
 * so offering to share one would present an action with nothing behind it.
 */
const SHAREABLE_CHAT_TYPES = new Set([
    '',
    'personal_single_user',
    'personal_multi_user',
    'group-single-user',
    'group_multi_user',
]);

function chatTypeOf(conversation: Conversation | ConversationMetadata | null | undefined): string {
    return String(conversation?.chat_type ?? '')
        .trim()
        .toLowerCase();
}

/** Whether a Share action should be offered for this conversation at all. */
export function canShareConversation(
    conversation: Conversation | ConversationMetadata | null | undefined,
): boolean {
    if (!conversation) {
        return false;
    }
    return SHAREABLE_CHAT_TYPES.has(chatTypeOf(conversation));
}

/**
 * Describe a conversation for the participants panel.
 *
 * `kind` here is not the storage kind but the *invite* kind — which of the three routes
 * applies — which is why a group conversation that is already shared reports
 * `collaborative` rather than `group`: it takes members directly and must not be converted
 * a second time.
 */
export function panelTargetForConversation(
    conversationId: string,
    conversation: Conversation | ConversationMetadata | null | undefined,
): ParticipantsPanelTarget {
    const chatType = chatTypeOf(conversation);
    const groupId =
        (conversation?.group_id as string | undefined) ??
        (conversation?.scope as { group_id?: string } | undefined)?.group_id ??
        null;

    if (isCollaborative(conversation)) {
        return {
            conversationId,
            kind: 'collaborative',
            title: conversation?.title as string | undefined,
            groupId,
        };
    }

    return {
        conversationId,
        kind: chatType.startsWith('group') ? 'group' : 'personal',
        title: conversation?.title as string | undefined,
        groupId,
    };
}
