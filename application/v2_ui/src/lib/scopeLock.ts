// scopeLock.ts
// Changing which workspaces a conversation is locked to.
//
// The lock is a fact about the conversation, written by the server. The first reply grounded in
// workspace documents locks the conversation to the workspaces that produced them
// (`collect_conversation_metadata`, "Scope Lock Logic"), and from then on the document picker
// only offers those workspaces (`source_catalog` narrows its catalog to `locked_contexts`). V2
// drew that state in the chat header and gave no way to change it, so a conversation locked to
// the wrong workspace had to be abandoned. This is the logic behind the control that changes it.
//
// The rules are the classic scope lock modal's (`chat-documents.js`) and the route that enforces
// them (`patch_conversation_scope_lock`):
//
//   - There are three states, not two. `null` means no workspace document has been used yet,
//     so there is nothing to lock or unlock and no control is drawn. `true` is locked; `false`
//     is unlocked by choice.
//   - Locking is always allowed. Unlocking is refused while the administrator enforces the lock
//     (`enforce_workspace_scope_lock`, which defaults to on), and the server rejects it with a
//     403 whatever this file believes about that setting.
//   - A personal conversation is changed by its owner; a shared one by anyone who can post in
//     it (`assert_user_can_participate_in_collaboration_conversation`).
//   - Unlocking keeps `locked_contexts`, so locking again returns to the same workspaces.
//
// Everything here is pure. The store that holds the dialog and the in-flight change lives in
// `stores/scopeLockStore.ts`, and the split is what lets the optimistic write and its rollback be
// tested without a DOM or a server.

import { scopeLockState, type ScopeLockState } from './conversationBadges';
import { readContexts } from './conversationDetails';
import { isCollaborative, type ConversationMetadata, type WorkspaceRef } from './types';

export type ScopeLockWorkspaceKind = 'personal' | 'group' | 'public';

/** One workspace a conversation is locked to, or would be locked to. */
export interface ScopeLockWorkspace {
    kind: ScopeLockWorkspaceKind;
    /** Empty for the personal workspace, which is always the reader's own. */
    id: string;
    name: string;
}

/** The workspaces the reader belongs to, which name an id the conversation itself does not. */
export interface WorkspaceDirectory {
    groups: readonly WorkspaceRef[];
    publicWorkspaces: readonly WorkspaceRef[];
}

export type ScopeLockAction = 'lock' | 'unlock';

/** Why the reader can look at the lock but not change it. */
export type ScopeLockLimit =
    | 'enforced'
    | 'shared_participant'
    | 'owner_only'
    | 'nothing_recorded';

export interface ScopeLockView {
    state: ScopeLockState;
    workspaces: ScopeLockWorkspace[];
    /** What confirming would do. Null when the reader can only look. */
    action: ScopeLockAction | null;
    /** Why `action` is null while the lock is visible; null when an action is possible. */
    limit: ScopeLockLimit | null;
}

/** The two fields a change writes, which are also what a rollback restores. */
export interface ScopeLockFields {
    scope_locked: boolean | null;
    locked_contexts?: unknown[];
}

type Bag = Record<string, unknown>;

function isRecord(value: unknown): value is Bag {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * Whether the administrator keeps users from unlocking.
 *
 * `enforce_workspace_scope_lock` reaches the browser inside the sanitized `settings` block of
 * the bootstrap payload (it is not an `enable_*` key, so it is not in `features`). The server
 * treats an absent value as enforced, because that is the stored default, so only an explicit
 * `false` lifts it here too.
 */
export function scopeLockEnforced(settings: unknown): boolean {
    return !(isRecord(settings) && settings.enforce_workspace_scope_lock === false);
}

function workspaceName(
    kind: ScopeLockWorkspaceKind,
    id: string,
    named: ReadonlyMap<string, string>,
    directory: WorkspaceDirectory,
): string {
    if (kind === 'personal') {
        return 'Personal workspace';
    }
    const fromConversation = named.get(`${kind}:${id}`);
    if (fromConversation) {
        return fromConversation;
    }
    const listed = (kind === 'group' ? directory.groups : directory.publicWorkspaces).find(
        (item) => item.id === id,
    );
    return text(listed?.name) || id;
}

/**
 * The workspaces the lock applies to.
 *
 * `locked_contexts` when the conversation has it, otherwise its recorded contexts -- the same
 * fallback the server enforces with (`locked_contexts or context`), so what is listed is what
 * the picker is actually limited to. Entries for anything but a personal, group or public
 * workspace are ignored, and a workspace is listed once.
 */
export function readScopeLockWorkspaces(
    metadata: ConversationMetadata | null | undefined,
    directory: WorkspaceDirectory = { groups: [], publicWorkspaces: [] },
): ScopeLockWorkspace[] {
    const contexts = readContexts(metadata);
    const named = new Map(
        contexts
            .filter((entry) => entry.name)
            .map((entry) => [`${entry.scope}:${entry.id}`, entry.name] as const),
    );
    const locked = Array.isArray(metadata?.locked_contexts)
        ? (metadata.locked_contexts as unknown[]).filter(isRecord)
        : [];
    const entries: { scope: string; id: string }[] = locked.length
        ? locked.map((entry) => ({ scope: text(entry.scope), id: text(entry.id) }))
        : contexts.map((entry) => ({ scope: entry.scope, id: entry.id }));

    const seen = new Set<string>();
    const workspaces: ScopeLockWorkspace[] = [];
    for (const entry of entries) {
        if (entry.scope !== 'personal' && entry.scope !== 'group' && entry.scope !== 'public') {
            continue;
        }
        const kind: ScopeLockWorkspaceKind = entry.scope;
        const id = kind === 'personal' ? '' : entry.id;
        if (kind !== 'personal' && !id) {
            continue;
        }
        const key = `${kind}:${id}`;
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        workspaces.push({ kind, id, name: workspaceName(kind, id, named, directory) });
    }
    return workspaces;
}

/**
 * Whether this reader may change the lock, and what to say when they may not.
 *
 * A shared conversation reports `can_post_messages`, which folds membership, role and group
 * visibility together and is what the server's participation check amounts to. It is deny by
 * default: a membership that has not loaded is not permission. A personal conversation carries
 * its owner, and an absent owner is left for the server to judge.
 */
function mayChange(
    metadata: ConversationMetadata,
    viewerId: string | null | undefined,
): ScopeLockLimit | null {
    if (isCollaborative(metadata)) {
        return metadata.can_post_messages === true ? null : 'shared_participant';
    }
    const owner = text(metadata.user_id);
    return !owner || !viewerId || owner === viewerId ? null : 'owner_only';
}

export function resolveScopeLockView(
    metadata: ConversationMetadata | null | undefined,
    options: {
        enforced: boolean;
        viewerId?: string | null;
        directory?: WorkspaceDirectory;
    },
): ScopeLockView {
    const state = scopeLockState(metadata);
    if (!metadata || state === 'hidden') {
        return { state: 'hidden', workspaces: [], action: null, limit: null };
    }

    const workspaces = readScopeLockWorkspaces(metadata, options.directory);
    const blocked = mayChange(metadata, options.viewerId);
    if (blocked) {
        return { state, workspaces, action: null, limit: blocked };
    }
    if (state === 'locked') {
        return options.enforced
            ? { state, workspaces, action: null, limit: 'enforced' }
            : { state, workspaces, action: 'unlock', limit: null };
    }
    // Locking to nothing would leave the picker with no workspace at all, so it is not offered
    // until the conversation has recorded one.
    return workspaces.length === 0
        ? { state, workspaces, action: null, limit: 'nothing_recorded' }
        : { state, workspaces, action: 'lock', limit: null };
}

/* -------------------------------------------------------------------------- */
/* Wording                                                                     */
/* -------------------------------------------------------------------------- */

export interface ScopeLockCopy {
    title: string;
    description: string;
    /** Introduces the workspace list; empty when there is nothing to list. */
    listLabel: string;
    notice: string;
    noticeTone: 'info' | 'warn';
    /** Empty when the dialog can only be read. */
    confirmLabel: string;
}

const LIMIT_NOTICE: Record<ScopeLockLimit, string> = {
    enforced: 'Workspace scope lock is enforced by your administrator. The scope cannot be unlocked.',
    shared_participant: 'Only people who can post in this conversation can change its workspace scope.',
    owner_only: 'Only the owner of this conversation can change its workspace scope.',
    nothing_recorded:
        'No workspaces are recorded for this conversation yet, so there is nothing to lock it to.',
};

/**
 * The dialog's wording, for one intent.
 *
 * The intent is the action the dialog was opened for and is fixed for its life. Deriving it
 * from the live view instead would flip a dialog from "Unlock" to "Lock" the moment the
 * optimistic write lands, while the reader is still looking at it.
 */
export function scopeLockCopy(view: ScopeLockView, intent: ScopeLockAction | null): ScopeLockCopy {
    const hasWorkspaces = view.workspaces.length > 0;
    if (intent === 'unlock') {
        return {
            title: 'Unlock workspace scope',
            description:
                "This conversation's scope is locked to prevent accidental cross-contamination with other data sources.",
            listLabel: hasWorkspaces ? 'Currently locked to:' : '',
            notice:
                'Unlocking lets you choose any workspace for this conversation. You can lock it again later.',
            noticeTone: 'warn',
            confirmLabel: 'Unlock scope',
        };
    }
    if (intent === 'lock') {
        return {
            title: 'Lock workspace scope',
            description:
                'Lock the scope to keep this conversation to the workspaces that produced its search results.',
            listLabel: hasWorkspaces ? 'Will lock to:' : '',
            notice:
                'Locking limits the Documents picker to the workspaces listed above. Sources you already added from other workspaces must be removed before you send.',
            noticeTone: 'info',
            confirmLabel: 'Lock scope',
        };
    }
    const notice = view.limit ? LIMIT_NOTICE[view.limit] : '';
    return view.state === 'locked'
        ? {
              title: 'Workspace scope is locked',
              description:
                "This conversation's scope is locked to prevent accidental cross-contamination with other data sources.",
              listLabel: hasWorkspaces ? 'Currently locked to:' : '',
              notice,
              noticeTone: 'info',
              confirmLabel: '',
          }
        : {
              title: 'Workspace scope is unlocked',
              description: 'This conversation is not restricted to particular workspaces.',
              listLabel: hasWorkspaces ? 'Last locked to:' : '',
              notice,
              noticeTone: 'info',
              confirmLabel: '',
          };
}

/** The sentence a control announces and shows as its tooltip. */
export function scopeLockControlLabel(view: ScopeLockView): string {
    if (view.state === 'hidden') {
        return '';
    }
    const state = view.state === 'locked' ? 'Workspace scope is locked' : 'Workspace scope is unlocked';
    if (!view.action) {
        return `${state}. View details.`;
    }
    return `${state}. ${view.action === 'unlock' ? 'Review or unlock it.' : 'Review or lock it.'}`;
}

/* -------------------------------------------------------------------------- */
/* Changing the lock                                                           */
/* -------------------------------------------------------------------------- */

/** What PATCH /api/conversations/<id>/scope_lock sends. The route accepts only real booleans. */
export function scopeLockRequestBody(locked: boolean): { scope_locked: boolean } {
    return { scope_locked: locked === true };
}

/**
 * The server's answer, reduced to the two fields a change writes.
 *
 * The route echoes `scope_locked` and returns the conversation's `locked_contexts`, which it
 * preserves across an unlock. Either may be missing from an unexpected body, so each falls back
 * to what was asked for and what was already held rather than being invented.
 */
export function confirmedScopeLock(
    response: unknown,
    requested: boolean,
    held: unknown[] | undefined,
): ScopeLockFields {
    const body = isRecord(response) ? response : {};
    return {
        scope_locked: typeof body.scope_locked === 'boolean' ? body.scope_locked : requested,
        locked_contexts: Array.isArray(body.locked_contexts) ? body.locked_contexts : held,
    };
}

export function scopeLockErrorMessage(error: unknown, requested: boolean): string {
    if (error instanceof Error && error.message.trim()) {
        return error.message;
    }
    return requested
        ? 'The workspace scope could not be locked. Try again.'
        : 'The workspace scope could not be unlocked. Try again.';
}

/** Lock fields written onto metadata, leaving the rest of it untouched. */
export function withScopeLockFields(
    metadata: ConversationMetadata,
    fields: ScopeLockFields,
): ConversationMetadata {
    return { ...metadata, scope_locked: fields.scope_locked, locked_contexts: fields.locked_contexts };
}

/** Everything a change needs from the outside, so the sequence can be run without either. */
export interface ScopeLockEffects {
    /** The open conversation's lock fields, or null when its metadata is not loaded. */
    read: () => ScopeLockFields | null;
    /** Write lock fields onto the loaded metadata. A no-op when another conversation is open. */
    write: (fields: ScopeLockFields) => void;
    send: (locked: boolean) => Promise<unknown>;
    /** Read the conversation again, so every surface agrees with the server. */
    refresh: () => void;
}

export type ScopeLockChangeResult = { ok: true } | { ok: false; message: string };

/**
 * Lock or unlock, showing the result at once and putting it back if the server refuses.
 *
 * The write is optimistic because the control that was just pressed should answer the press;
 * waiting for the round trip makes the header lag behind the reader. A refusal restores what was
 * held, but only while the lock still reads as the optimistic value -- a metadata read that
 * landed in between carries the server's own answer, and overwriting it with an older snapshot
 * would reintroduce exactly the disagreement this is meant to prevent.
 */
export async function changeScopeLock(
    locked: boolean,
    effects: ScopeLockEffects,
): Promise<ScopeLockChangeResult> {
    const before = effects.read();
    if (!before) {
        return { ok: false, message: 'This conversation is not loaded yet. Try again in a moment.' };
    }

    effects.write({ ...before, scope_locked: locked });
    try {
        const response = await effects.send(locked);
        effects.write(confirmedScopeLock(response, locked, before.locked_contexts));
        effects.refresh();
        return { ok: true };
    } catch (error) {
        if (effects.read()?.scope_locked === locked) {
            effects.write(before);
        }
        return { ok: false, message: scopeLockErrorMessage(error, locked) };
    }
}
