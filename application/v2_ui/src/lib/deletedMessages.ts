// deletedMessages.ts
// Messages deleted while conversation archiving is enabled.
//
// With archiving on, deleting a message keeps its stored document with `metadata.is_deleted`
// set, and masks it only as a fail-safe (route_backend_conversations.py). The server leaves
// those documents out of what it returns. The thread still drops any that arrive, because a
// deleted message must never come back as a masked one, which is what the mask alone renders.

import type { ChatMessage } from './types';

/** Whether a message was deleted while conversation archiving was enabled. */
export function isDeletedMessage(message: ChatMessage | undefined): boolean {
    return message?.metadata?.is_deleted === true;
}

/** The messages that were not deleted, in their original order. */
export function withoutDeletedMessages(messages: ChatMessage[] | null | undefined): ChatMessage[] {
    return (messages ?? []).filter((message) => !isDeletedMessage(message));
}
