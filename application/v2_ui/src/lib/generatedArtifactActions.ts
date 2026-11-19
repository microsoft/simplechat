// generatedArtifactActions.ts
// What can be done with a generated file besides downloading it: add it to a workspace and, when
// it is Markdown, build a PowerPoint deck from it.
//
// Both are the classic artifact card's buttons -- "Add to Workspace" and "Create PowerPoint" --
// whose decisions are made inline in `chat-messages.js` and `chat-message-export.js`. V2 had
// neither: `V2_TABULAR_ANALYSIS.md` recorded them as "better rebuilt with V2's own export
// machinery than ported", and that is what this is. The rules below are classic's, written as
// pure functions so each one can be checked without a DOM:
//
//   - Both apply only to a finished file that lives on its own message in the conversation and
//     is not withheld for approval. A background run has nothing to act on yet, and a file waiting
//     for the conversation owner's release is refused by the server whoever asks.
//   - "Add to Workspace" posts to `/api/chat_artifacts/promote` with an explicit destination. The
//     destination is the workspace the conversation belongs to: a group conversation offers its
//     group, a public one its workspace, anything else the reader's personal workspace.
//   - "Create PowerPoint" posts the file's own message id as `artifact_message_id` beside the
//     reply that carries it, and the server builds the deck from the stored file rather than from
//     the reply text. It is offered for Markdown files only.
//
// Neither action decides who may do it. The server checks the reader's role in the destination
// workspace and its approval policy; these rules only avoid offering a button whose destination
// the deployment does not have.

import { primaryContext, resolveChatType } from './conversationBadges';
import {
    approvalBlocksDownload,
    isCompletedTabularArtifact,
    isMarkdownArtifact,
    type GeneratedArtifact,
} from './generatedArtifacts';
import type { ConversationMetadata, WorkspaceRef } from './types';

type Bag = Record<string, unknown>;

function isRecord(value: unknown): value is Bag {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * The conversation the file is stored under, which both routes address it by.
 *
 * The artifact names its own conversation. That matters in a shared conversation, where the file
 * is written under the hidden source conversation rather than the shared id the thread is
 * opened by; downloads resolve it the same way.
 */
export function artifactConversationId(artifact: GeneratedArtifact, fallback = ''): string {
    return text(artifact.conversation_id) || text(artifact.source_conversation_id) || text(fallback);
}

/**
 * Whether the file is in a state either action can be taken on.
 *
 * A background export has no file yet, and a staged or declined one is withheld from everyone,
 * so offering an action on either would end in a refusal with no explanation.
 */
export function isActionableArtifact(artifact: GeneratedArtifact, conversationId: string): boolean {
    return Boolean(
        !artifact.background_export
            && !approvalBlocksDownload(artifact)
            && text(artifact.artifact_message_id)
            && conversationId,
    );
}

/* -------------------------------------------------------------------------- */
/* Add to workspace                                                            */
/* -------------------------------------------------------------------------- */

export type PromotionScope = 'personal' | 'group' | 'public';

/** One workspace a file can be added to. */
export interface PromotionTarget {
    /** `personal`, `group:<id>` or `public:<id>`: stable, and what a chooser keys on. */
    id: string;
    scope: PromotionScope;
    groupId?: string;
    publicWorkspaceId?: string;
    name: string;
    /** What happens to the file there, in the words classic uses. */
    detail: string;
    /** The confirm button when this is the only destination. */
    confirmLabel: string;
}

/** Which workspace kinds the deployment has switched on. */
export interface WorkspaceAvailability {
    personal: boolean;
    group: boolean;
    public: boolean;
}

export interface PromotionContext {
    /** The open conversation, which decides the destination. Null until it has loaded. */
    metadata: ConversationMetadata | null | undefined;
    groups: readonly WorkspaceRef[];
    publicWorkspaces: readonly WorkspaceRef[];
    available: WorkspaceAvailability;
}

export const PERSONAL_TARGET: PromotionTarget = {
    id: 'personal',
    scope: 'personal',
    name: 'Personal workspace',
    detail: 'Private to you',
    confirmLabel: 'Add to Personal',
};

function groupTarget(id: string, name: string): PromotionTarget {
    return {
        id: `group:${id}`,
        scope: 'group',
        groupId: id,
        name: name || 'Group workspace',
        detail: 'Group workspace approval request',
        confirmLabel: 'Submit to Group',
    };
}

function publicTarget(id: string, name: string): PromotionTarget {
    return {
        id: `public:${id}`,
        scope: 'public',
        publicWorkspaceId: id,
        name: name || 'Public workspace',
        detail: 'Public workspace approval request',
        confirmLabel: 'Submit to Public',
    };
}

function listedName(list: readonly WorkspaceRef[], id: string): string {
    return text(list.find((item) => item.id === id)?.name);
}

/**
 * Where the open conversation's files can go.
 *
 * Classic reads the destination off the active conversation: a group conversation offers its
 * group, a public one its public workspace, and any other kind the personal workspace. When a
 * group or public conversation does not name its workspace -- a conversation that predates the
 * field -- classic falls back to whatever the scope selector holds, which V2 has no equivalent
 * of; the reader's own workspaces are offered instead so they can say where it belongs. The
 * server still decides who may publish where.
 *
 * Empty when the conversation has not loaded: guessing "personal" for a conversation that is
 * really a group's would offer to put its files in the wrong place.
 */
export function resolvePromotionTargets(context: PromotionContext): PromotionTarget[] {
    const { metadata, groups, publicWorkspaces, available } = context;
    if (!metadata) {
        return [];
    }

    const chatType = resolveChatType(metadata);
    let targets: PromotionTarget[];

    if (chatType.startsWith('group')) {
        const primary = primaryContext(metadata, 'group');
        const id = text(primary?.id) || text(metadata.group_id);
        targets = id
            ? [groupTarget(id, text(primary?.name) || text(metadata.group_name) || listedName(groups, id))]
            : [];
    } else if (chatType.startsWith('public')) {
        const primary = primaryContext(metadata, 'public');
        const id = text(primary?.id);
        targets = id ? [publicTarget(id, text(primary?.name) || listedName(publicWorkspaces, id))] : [];
    } else {
        targets = [PERSONAL_TARGET];
    }

    if (targets.length === 0) {
        targets = [
            PERSONAL_TARGET,
            ...groups.map((group) => groupTarget(group.id, group.name)),
            ...publicWorkspaces.map((workspace) => publicTarget(workspace.id, workspace.name)),
        ];
    }

    return targets.filter((target) => available[target.scope]);
}

/** Whether "Add to workspace" is worth showing: an actionable file and somewhere to put it. */
export function canAddToWorkspace(
    artifact: GeneratedArtifact,
    conversationId: string,
    targets: readonly PromotionTarget[],
): boolean {
    return targets.length > 0 && isActionableArtifact(artifact, conversationId);
}

/** What POST /api/chat_artifacts/promote takes. `workspace_scope` is required by the route. */
export interface PromotionRequestBody {
    conversation_id: string;
    message_id: string;
    workspace_scope: PromotionScope;
    group_id?: string;
    public_workspace_id?: string;
}

export function promotionRequestBody(
    conversationId: string,
    artifactMessageId: string,
    target: PromotionTarget,
): PromotionRequestBody {
    return {
        conversation_id: conversationId,
        message_id: artifactMessageId,
        workspace_scope: target.scope,
        ...(target.groupId ? { group_id: target.groupId } : {}),
        ...(target.publicWorkspaceId ? { public_workspace_id: target.publicWorkspaceId } : {}),
    };
}

/**
 * How far the file got.
 *
 * `added` is in the workspace already (a personal destination, or an approval that was granted).
 * `pending_approval` waits on the workspace's approvers. `unconfirmed` is the server saying it
 * could not tell whether the publication finished: it created no second copy and the same request
 * can be sent again to reconcile.
 */
export type PromotionStatus = 'added' | 'pending_approval' | 'unconfirmed';

export interface PromotionOutcome {
    status: PromotionStatus;
    message: string;
}

const UNCONFIRMED_MESSAGE =
    'Publication could not be fully confirmed. Check the existing destination; no second copy was created.';

/** A successful reply (200 for a personal destination, 202 when approval is needed). */
export function promotionOutcome(data: unknown, target: PromotionTarget): PromotionOutcome {
    const body = isRecord(data) ? data : {};
    const publication = isRecord(body.publication) ? body.publication : {};
    const state = text(publication.state);
    const serverMessage = text(body.message);

    if (state === 'uncertain' || state === 'approval_failed') {
        return { status: 'unconfirmed', message: serverMessage || UNCONFIRMED_MESSAGE };
    }
    if (state === 'approved') {
        return { status: 'added', message: serverMessage || `Already added to ${target.name}.` };
    }
    if (body.approval_required === true || target.scope !== 'personal') {
        return { status: 'pending_approval', message: `Submitted to ${target.name} for approval.` };
    }
    return { status: 'added', message: 'Added to your personal workspace.' };
}
/**
 * A 409 from the route, which is not an error body.
 *
 * The route answers 409 when the publication is `uncertain` or `approval_failed` and still sends
 * the usual result, with its sentence under `message`. Reading that as a failure would tell the
 * reader nothing happened, when a copy may well exist.
 */
export function promotionConflict(error: unknown): PromotionOutcome | null {
    if (!isRecord(error) || error.status !== 409 || !isRecord(error.payload)) {
        return null;
    }
    const payload = error.payload;
    if (!isRecord(payload.publication)) {
        return null;
    }
    return { status: 'unconfirmed', message: text(payload.message) || UNCONFIRMED_MESSAGE };
}

export function promotionErrorMessage(error: unknown): string {
    return error instanceof Error && error.message.trim()
        ? error.message
        : 'Failed to add the generated artifact to a workspace.';
}

/* -------------------------------------------------------------------------- */
/* Create PowerPoint                                                           */
/* -------------------------------------------------------------------------- */

export const POWERPOINT_PENDING_MESSAGE =
    'Building your PowerPoint… planning the slides can take a minute.';
export const POWERPOINT_SUCCESS_MESSAGE = 'Markdown artifact exported as PowerPoint.';

/**
 * Whether "Create PowerPoint" applies.
 *
 * Classic offers it on a finished Markdown file that is not a row-level export, beside the reply
 * that carries it. The export route reads the reply from the personal conversation container and
 * requires the caller to own it, so a shared conversation can never succeed and is left out
 * rather than offered and refused.
 */
export function canCreatePowerPoint(
    artifact: GeneratedArtifact,
    conversationId: string,
    options: { shared: boolean; messageId: string },
): boolean {
    return Boolean(
        !options.shared
            && text(options.messageId)
            && isActionableArtifact(artifact, conversationId)
            && isMarkdownArtifact(artifact)
            && !isCompletedTabularArtifact(artifact),
    );
}

/** What POST /api/message/export-powerpoint takes to build a deck from a stored file. */
export interface PowerPointArtifactBody {
    /** The reply carrying the file. The route loads it before it loads the file. */
    message_id: string;
    conversation_id: string;
    artifact_message_id: string;
    visual_assets?: { kind: string; source: string; data_uri: string }[];
}

export function powerPointArtifactBody(
    artifact: GeneratedArtifact,
    conversationId: string,
    messageId: string,
    visualAssets: PowerPointArtifactBody['visual_assets'] = [],
): PowerPointArtifactBody {
    return {
        message_id: messageId,
        conversation_id: conversationId,
        artifact_message_id: text(artifact.artifact_message_id),
        // The diagrams drawn in the reply are sent, as classic does. The server matches them to
        // the file's own diagrams by their text and draws any it was not sent a picture of.
        ...(visualAssets.length > 0 ? { visual_assets: visualAssets } : {}),
    };
}
