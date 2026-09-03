// collaboration.ts
// Typed wrappers around the /api/collaboration/* endpoints the V2 UI uses for shared
// conversations.
//
// Kept apart from `endpoints.ts` because these are not variants of the personal routes but
// a parallel API over a different pair of Cosmos containers. Paths and payload shapes were
// verified against route_backend_collaboration.py, functions_collaboration.py and
// collaboration_models.py.
//
// Two conventions in this API differ from the personal one and are easy to get wrong:
//
//   - Most responses wrap the conversation as `{conversation: ...}`, but the rename route
//     returns the serialized conversation *bare*. Both spellings are normalised here so
//     callers never have to know which route they came from.
//   - Sharing an existing conversation does not modify it. It creates a *new* collaboration
//     conversation with its own id and leaves the original in place as the hidden source
//     the AI actually runs in, so callers must follow the returned id.

import { api, apiUrl } from './apiClient';
import type { MessageVisualStyles } from './endpoints';
import type {
    CollaborationConversation,
    CollaborationMessage,
    CollaborationParticipant,
    CollaboratorSuggestion,
    Json,
    MembershipRole,
} from './types';
import type { MaskAction, MaskedRange, MaskSelection } from './masking';
import type {
    BlockRevisionAssistResponse,
    BlockRevisionResponse,
    ImageRevisionRequest,
    ImageRevisionResponse,
} from './endpoints';

/* -------------------------------------------------------------------------- */
/* Paths                                                                       */
/* -------------------------------------------------------------------------- */

const base = (conversationId: string) =>
    `/api/collaboration/conversations/${encodeURIComponent(conversationId)}`;

/* -------------------------------------------------------------------------- */
/* Conversations                                                               */
/* -------------------------------------------------------------------------- */

/**
 * List the caller's shared conversations.
 *
 * The conversation feed already merges these into the rail, so this is not how the list is
 * built. It exists for the one thing the feed cannot answer: which invitations are still
 * pending, which `include_pending` controls and which the feed omits entirely.
 */
export const fetchCollaborationConversations = (
    options: { includePending?: boolean; scope?: 'all' | 'personal' | 'group' } = {},
    signal?: AbortSignal,
) => {
    const params = new URLSearchParams();
    params.set('include_pending', options.includePending === false ? 'false' : 'true');
    if (options.scope) {
        params.set('scope', options.scope);
    }
    return api.get<{ conversations: CollaborationConversation[] }>(
        `/api/collaboration/conversations?${params.toString()}`,
        signal,
    );
};

/**
 * Load one shared conversation, with its members and the caller's capability flags.
 *
 * This is also the existence check for a shared conversation: it answers 404 when the
 * conversation is gone and 403 when the caller may not see it, where the messages endpoint
 * would simply return an empty list.
 */
export const fetchCollaborationConversation = (conversationId: string, signal?: AbortSignal) =>
    api.get<{ conversation: CollaborationConversation }>(base(conversationId), signal);

/** Rename. Unlike its siblings this route returns the conversation unwrapped. */
export const renameCollaborationConversation = (conversationId: string, title: string) =>
    api.put<CollaborationConversation>(base(conversationId), { title });

/** Toggle pinned. Server-side toggle with no request body, like the personal route. */
export const toggleCollaborationPinned = (conversationId: string) =>
    api.post<{ success: boolean; is_pinned: boolean }>(`${base(conversationId)}/pin`);

/** Toggle hidden. Also a server-side toggle with no request body. */
export const toggleCollaborationHidden = (conversationId: string) =>
    api.post<{ success: boolean; is_hidden: boolean }>(`${base(conversationId)}/hide`);

export const markCollaborationConversationRead = (conversationId: string) =>
    api.post<Json>(`${base(conversationId)}/mark-read`);

/**
 * Remove the caller from a shared conversation, or destroy it for everybody.
 *
 * The two are one endpoint because they are the same decision made from different
 * positions: an owner leaving must hand ownership on, which is what `newOwnerUserId` is
 * for. Which of the two the caller may do is reported by `can_delete_conversation` and
 * `can_leave_conversation` on the conversation.
 */
export const collaborationDeleteAction = (
    conversationId: string,
    action: 'delete' | 'leave',
    newOwnerUserId?: string,
) =>
    api.post<{
        success: boolean;
        action: string;
        conversation?: CollaborationConversation;
        removed_participant?: CollaborationParticipant;
        promoted_participant?: CollaborationParticipant | null;
    }>(`${base(conversationId)}/delete-action`, {
        action,
        ...(newOwnerUserId ? { new_owner_user_id: newOwnerUserId } : {}),
    });

/* -------------------------------------------------------------------------- */
/* Membership                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Response of every route that adds people, whether or not it had to create the shared
 * conversation first.
 *
 * `created` and `source_conversation_id` are only sent by the two conversion routes. They
 * are what tells the caller the returned conversation is a *different* one from the
 * conversation it just shared, and so must be selected in place of it.
 */
export interface InviteResult {
    conversation: CollaborationConversation;
    invited_participants?: CollaborationParticipant[];
    created?: boolean;
    source_conversation_id?: string;
}

/** Invite people into a conversation that is already shared. */
export const inviteCollaborationMembers = (
    conversationId: string,
    participants: CollaborationParticipant[],
) => api.post<InviteResult>(`${base(conversationId)}/members`, { participants });

/**
 * Share a personal conversation.
 *
 * Creates a new shared conversation seeded from this one and returns it. The original is
 * kept as the hidden source conversation the AI runs in, so it is not renamed, moved or
 * deleted — but it is no longer the id the reader should have open.
 */
export const sharePersonalConversation = (
    conversationId: string,
    participants: CollaborationParticipant[],
) =>
    api.post<InviteResult>(
        `/api/collaboration/conversations/from-personal/${encodeURIComponent(conversationId)}/members`,
        { participants },
    );

/** Share a group conversation. Same contract as the personal conversion. */
export const shareGroupConversation = (
    conversationId: string,
    participants: CollaborationParticipant[],
) =>
    api.post<InviteResult>(
        `/api/collaboration/conversations/from-group/${encodeURIComponent(conversationId)}/members`,
        { participants },
    );

export const removeCollaborationMember = (conversationId: string, memberUserId: string) =>
    api.delete<{
        conversation: CollaborationConversation;
        removed_participant?: CollaborationParticipant;
    }>(`${base(conversationId)}/members/${encodeURIComponent(memberUserId)}`);

/**
 * Change a member's role.
 *
 * Only an owner may do this (`can_manage_roles`), and only `admin` and `member` are
 * assignable — ownership moves by handing it on when leaving, not by assignment.
 */
export const updateCollaborationMemberRole = (
    conversationId: string,
    memberUserId: string,
    role: MembershipRole,
) =>
    api.put<{ conversation: CollaborationConversation; participant?: CollaborationParticipant }>(
        `${base(conversationId)}/members/${encodeURIComponent(memberUserId)}/role`,
        { role },
    );

export const respondToCollaborationInvite = (
    conversationId: string,
    action: 'accept' | 'decline',
) => api.post<{ conversation: CollaborationConversation }>(
    `${base(conversationId)}/invite-response`,
    { action },
);

/* -------------------------------------------------------------------------- */
/* Messages                                                                    */
/* -------------------------------------------------------------------------- */

export const fetchCollaborationMessages = (conversationId: string, signal?: AbortSignal) =>
    api.get<{ messages: CollaborationMessage[] }>(`${base(conversationId)}/messages`, signal);

/**
 * Post a message to the other participants without asking the AI to answer.
 *
 * This is the ordinary case in a shared conversation and has no equivalent in a personal
 * one, where every message is a prompt. The AI path is `streamCollaborationUrl` below.
 */
export const postCollaborationMessage = (
    conversationId: string,
    body: {
        content: string;
        reply_to_message_id?: string | null;
        mentioned_participants?: CollaborationParticipant[];
    },
) =>
    api.post<{ conversation: CollaborationConversation; message: CollaborationMessage }>(
        `${base(conversationId)}/messages`,
        body,
    );

/**
 * URL of the AI streaming endpoint for a shared conversation.
 *
 * A URL rather than a wrapper because the response is an SSE body, which `lib/sse.ts`
 * consumes with its own reader. The frames are the ones `/api/chat/stream` emits: the route
 * bridges to that view internally and rewrites the terminal frame, so the existing parser
 * needs no changes.
 *
 * There is deliberately no reattach counterpart. `/api/chat/stream/reattach` addresses the
 * hidden source conversation, which the browser is never told the id of, so a dropped
 * collaboration stream cannot be resumed and must not be retried as though it could.
 */
export const streamCollaborationUrl = (conversationId: string) =>
    apiUrl(`${base(conversationId)}/stream`);

export const cancelCollaborationStreamUrl = (conversationId: string) =>
    apiUrl(`${base(conversationId)}/stream/cancel`);

export const deleteCollaborationMessage = (conversationId: string, messageId: string) =>
    api.delete<{
        success: boolean;
        deleted_message_ids: string[];
        conversation: CollaborationConversation;
    }>(`${base(conversationId)}/messages/${encodeURIComponent(messageId)}`);

/** Response of the collaboration mask route. Carries the whole message, unlike the personal one. */
export interface CollaborationMaskResponse {
    success: boolean;
    message_id: string;
    conversation_id: string;
    masked: boolean;
    masked_ranges: MaskedRange[];
    message?: CollaborationMessage;
}

export const maskCollaborationMessage = (
    conversationId: string,
    messageId: string,
    body: { action: MaskAction; selection?: MaskSelection },
) =>
    api.post<CollaborationMaskResponse>(
        `${base(conversationId)}/messages/${encodeURIComponent(messageId)}/mask`,
        body,
    );

/** Response of the collaboration visual style route. */
export interface CollaborationVisualStyleResponse {
    success: boolean;
    message_id: string;
    conversation_id: string;
    visual_styles: MessageVisualStyles;
    message?: CollaborationMessage;
}

/**
 * Save, or clear, the colours and size of one diagram or chart in a shared message.
 *
 * The shared counterpart of `setMessageVisualStyle` in `endpoints.ts`. The personal route
 * resolves the conversation through the personal container, which a shared conversation is
 * not in, so sending a shared message there answers 404 rather than saving anything.
 *
 * The conversation travels in the path rather than the body, which is how every other
 * collaboration message route addresses its conversation. The remaining fields match the
 * personal route exactly, including `height` being absent to keep the stored size and null to
 * clear it, because both routes hand the payload to the same validator on the server.
 *
 * The stored choice belongs to the message, so it applies for every participant and the
 * server broadcasts it to them. Changing it therefore needs the same write access as posting.
 */
export const setCollaborationMessageVisualStyle = (
    conversationId: string,
    messageId: string,
    body: {
        block_kind: string;
        block_index: number;
        source_hash: string;
        style: { palette: string; background: string; colors: Record<string, string> } | null;
        height?: number | null;
    },
) =>
    api.post<CollaborationVisualStyleResponse>(
        `${base(conversationId)}/messages/${encodeURIComponent(messageId)}/visual-style`,
        body,
    );

/* -------------------------------------------------------------------------- */
/* Block revisions                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Editing a diagram in a shared conversation.
 *
 * The same three operations as the personal routes in `endpoints.ts`, against the
 * collaboration containers. They cannot be one route because a shared conversation's messages
 * live somewhere else entirely, but the request and response shapes are deliberately identical
 * so `chatStore` can pick an endpoint and pass the same body either way.
 *
 * The conversation id is in the path here rather than the body, matching every other
 * collaboration route.
 */
export const addCollaborationBlockRevision = (
    conversationId: string,
    messageId: string,
    body: {
        block_kind: string;
        block_index: number;
        source_hash: string;
        source: string;
        original_source: string;
        origin?: 'manual' | 'control';
        note?: string;
        expected_revision_count?: number;
    },
) =>
    api.post<BlockRevisionResponse>(
        `${base(conversationId)}/messages/${encodeURIComponent(messageId)}/block-revision`,
        body,
    );

export const setCollaborationBlockRevision = (
    conversationId: string,
    messageId: string,
    body: {
        block_kind: string;
        block_index: number;
        source_hash: string;
        revision_id: string;
    },
) =>
    api.post<BlockRevisionResponse>(
        `${base(conversationId)}/messages/${encodeURIComponent(messageId)}/block-revision/current`,
        body,
    );

export const assistCollaborationBlockRevision = (
    conversationId: string,
    messageId: string,
    body: {
        block_kind: string;
        block_index: number;
        source_hash: string;
        instruction: string;
        original_source: string;
        expected_revision_count?: number;
    },
) =>
    api.post<BlockRevisionAssistResponse>(
        `${base(conversationId)}/messages/${encodeURIComponent(messageId)}/block-revision/assist`,
        body,
    );

/* -------------------------------------------------------------------------- */
/* Image revisions                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Produce a new version of a shared generated image.
 *
 * The body is deliberately identical to the personal route's, so the store picks an endpoint
 * from the conversation's kind and sends the same request either way.
 *
 * There is no `assist` counterpart to the diagram trio: a browser cannot author an image, so
 * every version already comes from the model and this one call covers it.
 */
export const addCollaborationImageRevision = (
    conversationId: string,
    messageId: string,
    body: ImageRevisionRequest,
) =>
    api.post<ImageRevisionResponse>(
        `${base(conversationId)}/messages/${encodeURIComponent(messageId)}/image-revision`,
        body,
    );

export const setCollaborationImageRevision = (
    conversationId: string,
    messageId: string,
    body: { conversation_id: string; revision_id: string },
) =>
    api.post<ImageRevisionResponse>(
        `${base(conversationId)}/messages/${encodeURIComponent(messageId)}/image-revision/current`,
        body,
    );

/* -------------------------------------------------------------------------- */
/* Presence                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Announce that the caller is (or has stopped) typing.
 *
 * Fire-and-forget: the server broadcasts it to the other participants' event streams and
 * expires it after eight seconds, so a lost ping corrects itself and a failure is never
 * worth surfacing.
 */
export const sendCollaborationTyping = (conversationId: string, isTyping: boolean) =>
    api.post<{ success: boolean }>(`${base(conversationId)}/typing`, { is_typing: isTyping });

/** URL of the conversation's server-sent event stream. Consumed with `EventSource`. */
export const collaborationEventsUrl = (conversationId: string) =>
    apiUrl(`${base(conversationId)}/events`);

/* -------------------------------------------------------------------------- */
/* Images                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * URL for an image posted in a shared conversation.
 *
 * The server already writes this path into the message's `content` when it serializes an
 * image message, so this exists for the cases that need to rebuild it rather than read it.
 */
export const collaborationImageUrl = (conversationId: string, messageId: string) =>
    apiUrl(`${base(conversationId)}/images/${encodeURIComponent(messageId)}`);

/* -------------------------------------------------------------------------- */
/* Invitable people                                                            */
/* -------------------------------------------------------------------------- */

/**
 * People the caller could invite, drawn from recent collaborators and the directory.
 *
 * Not a collaboration route: it lives on the user API because the same list backs the
 * mention menu before a conversation has been shared at all.
 */
export const fetchCollaboratorSuggestions = (
    query: string,
    options: { limit?: number; recentOnly?: boolean } = {},
    signal?: AbortSignal,
) => {
    const params = new URLSearchParams();
    params.set('query', query);
    params.set('limit', String(options.limit ?? 8));
    if (options.recentOnly) {
        params.set('recent_only', 'true');
    }
    return api.get<{ results: CollaboratorSuggestion[] }>(
        `/api/user/collaboration-suggestions?${params.toString()}`,
        signal,
    );
};

/**
 * Members of a group, used instead of the directory for a group-scoped conversation.
 *
 * A group conversation may only be shared with people already in that group, so offering
 * directory-wide results there would suggest people the server will refuse. Returns a bare
 * array, and spells its fields in camelCase, unlike the collaboration API.
 */
export const fetchGroupMembers = (groupId: string, search: string, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    if (search) {
        params.set('search', search);
    }
    const qs = params.toString();
    return api.get<Array<Record<string, unknown>>>(
        `/api/groups/${encodeURIComponent(groupId)}/members${qs ? `?${qs}` : ''}`,
        signal,
    );
};

/* -------------------------------------------------------------------------- */
/* Generated file approvals                                                    */
/* -------------------------------------------------------------------------- */

/**
 * A file the AI generated inside a shared conversation, held back pending a decision.
 *
 * Generated files are staged rather than released because a shared thread has an audience:
 * the conversation's owner decides whether the other participants receive a file somebody
 * else asked the model to produce. Fields are those
 * `list_pending_generated_file_approvals_for_user` returns.
 */
export interface GeneratedFileApproval {
    artifact_message_id: string;
    /** The conversation the file was generated in, which the decision endpoint keys on. */
    source_conversation_id: string;
    /** The shared conversation it would be released into, when it came from one. */
    collaboration_conversation_id?: string;
    file_name?: string;
    output_format?: string;
    approval?: {
        state?: string;
        is_pending?: boolean;
        requested_by_name?: string;
        requested_at?: string;
        expires_at?: string;
        resolved_by_name?: string;
        viewer_can_approve?: boolean;
        viewer_is_requester?: boolean;
        [key: string]: unknown;
    };
    [key: string]: unknown;
}

export const fetchGeneratedFileApprovals = (signal?: AbortSignal) =>
    api.get<{ approvals: GeneratedFileApproval[] }>('/api/collaboration/file-approvals', signal);

export const resolveGeneratedFileApproval = (
    sourceConversationId: string,
    artifactMessageId: string,
    decision: 'approve' | 'deny',
) =>
    api.post<{
        artifact_message_id: string;
        approval_state: string;
        resolved_by_name?: string;
        resolved_at?: string;
    }>(
        `/api/collaboration/file-approvals/${encodeURIComponent(sourceConversationId)}` +
            `/${encodeURIComponent(artifactMessageId)}/${decision}`,
    );
