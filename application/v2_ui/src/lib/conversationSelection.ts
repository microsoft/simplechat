// conversationSelection.ts
// The rules a bulk action needs to read off a multi-selection of conversations, kept free
// of React so they can be tested directly.
//
// All of this exists because a conversation rail selection is not homogeneous. Two things
// vary row by row and both change which request is correct:
//
//   1. Storage. Personal conversations have bulk routes -- delete_multiple_conversations,
//      bulk-pin, bulk-hide -- that take a list of ids in one request. Shared
//      (collaborative) conversations live in a different container and those routes match
//      on `user_id`, so a shared id posted to them is silently reported in `failed_ids`
//      and nothing happens to it. Shared rows have to go one at a time through
//      /api/collaboration/*.
//
//   2. Authority. Removing a shared conversation is a *delete* for an owner and a *leave*
//      for everybody else, and the server refuses the wrong one. `can_delete_conversation`
//      says which applies, per row.
//
// Pin adds a third wrinkle: the personal bulk route takes an explicit 'pin' | 'unpin'
// rather than toggling, so a mixed selection needs a decision about what the button means
// before it is pressed.

import { isCollaborative } from './types';
import type { Conversation } from './types';

/* -------------------------------------------------------------------------- */
/* Partitioning                                                                */
/* -------------------------------------------------------------------------- */

/** One shared conversation and how it must be removed for this user. */
export interface CollaborativeRemoval {
    id: string;
    /** 'delete' destroys it for everybody; 'leave' only removes this user. */
    action: 'delete' | 'leave';
}

export interface ConversationPartition {
    /** Ids that can go to the personal bulk routes in one request. */
    personalIds: string[];
    /** Ids that must be driven one at a time through the collaboration routes. */
    collaborativeIds: string[];
}

/**
 * Resolve selected ids against the loaded rows, in list order.
 *
 * Ids with no matching row are dropped rather than passed through: they name a
 * conversation that has left the feed, and a bulk action must never act on a row the user
 * cannot see.
 */
export function selectedConversations(
    conversations: readonly Conversation[],
    selectedIds: readonly string[],
): Conversation[] {
    const wanted = new Set(selectedIds);
    return conversations.filter((conversation) => wanted.has(conversation.id));
}

/** Split a selection by which family of endpoints can act on it. */
export function partitionBySpecies(
    conversations: readonly Conversation[],
): ConversationPartition {
    const personalIds: string[] = [];
    const collaborativeIds: string[] = [];

    for (const conversation of conversations) {
        if (isCollaborative(conversation)) {
            collaborativeIds.push(conversation.id);
        } else {
            personalIds.push(conversation.id);
        }
    }

    return { personalIds, collaborativeIds };
}

/**
 * How this conversation will actually be removed for this user.
 *
 * The single source of truth for the question, so the sentence shown in the confirmation
 * and the request sent after it cannot disagree. Personal conversations are always a
 * deletion. For a shared one, only an owner may destroy it for everybody; anybody else
 * leaves it and the thread carries on without them.
 *
 * Defaults to 'leave' when the flag is absent. That is the safe direction: leaving when a
 * delete was permitted loses nothing but the row, whereas deleting when only a leave was
 * permitted is refused by the server anyway — and would be destructive for other people if
 * it were not.
 */
export function removalActionFor(conversation: Conversation): 'delete' | 'leave' {
    if (!isCollaborative(conversation)) {
        return 'delete';
    }
    return conversation.can_delete_conversation === true ? 'delete' : 'leave';
}

/** Decide delete-vs-leave for each shared conversation in a selection. */
export function collaborativeRemovals(
    conversations: readonly Conversation[],
): CollaborativeRemoval[] {
    return conversations
        .filter((conversation) => isCollaborative(conversation))
        .map((conversation) => ({
            id: conversation.id,
            action: removalActionFor(conversation),
        }));
}

/* -------------------------------------------------------------------------- */
/* Pinning                                                                     */
/* -------------------------------------------------------------------------- */

export type PinAction = 'pin' | 'unpin';

/**
 * What a pin button should do to this selection.
 *
 * Unpin only when *every* selected conversation is already pinned. Any other mix means the
 * user is most likely trying to pin the ones that are not, and pinning something already
 * pinned is a no-op -- whereas unpinning a mixed selection silently loses pins the user
 * never asked to give up.
 *
 * An empty selection reports 'pin' so the control has a stable label while disabled.
 */
export function pinActionFor(conversations: readonly Conversation[]): PinAction {
    if (conversations.length === 0) {
        return 'pin';
    }
    return conversations.every((conversation) => conversation.is_pinned === true)
        ? 'unpin'
        : 'pin';
}

/**
 * Which shared conversations actually need a request to reach the desired pin state.
 *
 * The collaboration route toggles rather than setting, so anything already in the target
 * state must be left alone -- posting to it would flip it the wrong way.
 */
export function collaborativeIdsNeedingPin(
    conversations: readonly Conversation[],
    action: PinAction,
): string[] {
    const desired = action === 'pin';
    return conversations
        .filter(
            (conversation) =>
                isCollaborative(conversation) &&
                (conversation.is_pinned === true) !== desired,
        )
        .map((conversation) => conversation.id);
}

/* -------------------------------------------------------------------------- */
/* Confirmation                                                                */
/* -------------------------------------------------------------------------- */

export interface RemovalSummary {
    /** Conversations that will be destroyed. */
    deleteCount: number;
    /** Shared conversations this user will only leave, which survive for the others. */
    leaveCount: number;
    /** Title to show when a single conversation is being removed. */
    onlyTitle: string | null;
    total: number;
}

/**
 * Describe what a removal is about to do, for the confirmation dialog.
 *
 * The two counts are reported separately because they are not the same promise. "Delete 5
 * conversations" is a lie if two of them are shared threads the user is merely stepping
 * out of, and a user who believes they have destroyed something they have not is worse off
 * than one who was told plainly.
 */
export function summarizeRemoval(conversations: readonly Conversation[]): RemovalSummary {
    let deleteCount = 0;
    let leaveCount = 0;

    for (const conversation of conversations) {
        // Read through the same helper the request uses, so the count promised here and the
        // action performed afterwards cannot be decided differently.
        if (removalActionFor(conversation) === 'leave') {
            leaveCount += 1;
        } else {
            deleteCount += 1;
        }
    }

    const onlyTitle =
        conversations.length === 1
            ? (conversations[0].title || 'Untitled conversation')
            : null;

    return { deleteCount, leaveCount, onlyTitle, total: conversations.length };
}

/**
 * One line describing a removal, used as the confirm dialog's title.
 *
 * Named for what will happen rather than for the button that was pressed, so a user who
 * only has permission to leave is never shown the word "delete".
 */
export function removalTitle(summary: RemovalSummary): string {
    if (summary.total === 0) {
        return 'Remove conversations';
    }
    if (summary.deleteCount === 0) {
        return summary.total === 1 ? 'Leave conversation' : 'Leave conversations';
    }
    if (summary.leaveCount === 0) {
        return summary.total === 1 ? 'Delete conversation' : 'Delete conversations';
    }
    return 'Delete and leave conversations';
}

/** The sentence under the title, spelling out the split when there is one. */
export function removalDescription(summary: RemovalSummary): string {
    if (summary.total === 0) {
        return 'Nothing is selected.';
    }

    if (summary.onlyTitle) {
        return summary.deleteCount === 1
            ? `“${summary.onlyTitle}” and its messages will be permanently deleted.`
            : `You will be removed from “${summary.onlyTitle}”. It stays available to everyone else.`;
    }

    if (summary.leaveCount === 0) {
        return `${summary.deleteCount} conversations and their messages will be permanently deleted.`;
    }
    if (summary.deleteCount === 0) {
        return `You will be removed from ${summary.leaveCount} shared conversations. They stay available to everyone else.`;
    }
    return (
        `${summary.deleteCount} ${summary.deleteCount === 1 ? 'conversation' : 'conversations'} will be permanently deleted. ` +
        `You will be removed from the other ${summary.leaveCount}, which stay available to everyone else.`
    );
}

/** The confirm button's label, matching the title's promise. */
export function removalConfirmLabel(summary: RemovalSummary): string {
    return summary.deleteCount === 0 ? 'Leave' : 'Delete';
}

/* -------------------------------------------------------------------------- */
/* Reporting                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Turn a partially successful bulk action into something worth showing.
 *
 * The bulk routes answer with `failed_ids` rather than failing whole, so reporting plain
 * success would leave rows visibly unchanged with no explanation. Returns null when
 * everything landed, so the caller can stay quiet in the ordinary case.
 *
 * Both tenses are passed in rather than derived: "hide" does not become "hided", and a
 * message that has to apologise for a failure should not also be ungrammatical.
 */
export function partialFailureMessage(
    attempted: number,
    failed: number,
    verb: string,
    pastTense: string,
): string | null {
    if (failed <= 0) {
        return null;
    }
    if (failed >= attempted) {
        return `Could not ${verb} ${attempted === 1 ? 'that conversation' : 'those conversations'}.`;
    }
    return `${attempted - failed} of ${attempted} conversations ${pastTense}. ${failed} could not be changed.`;
}
