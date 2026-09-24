// actionWorkbench.ts
// Scope-aware action reads, writes and connection tests for the actions collection and editor.
//
// The actions surface shipped personal-only: ActionsSection and ActionEditorPage called the
// /api/user/plugins functions in workspaceAuthoringApi.ts and workspaceActionServices.ts directly.
// This module is the seam that lets the same components serve a group workspace without forking
// them, the way documentOperations.ts and promptWorkbench.ts became scope-aware before it. An
// ActionScope selects which URLs are used, which draft-cache partition drafts live in, which
// identities may be bound, whether a connection test carries the group payload, and which
// per-operation gates apply. The personal adapter is a thin pass-through so its behaviour stays
// byte-identical in effect: same URLs, same identities, same flows -- it holds no /api/user/plugins
// URL of its own and delegates entirely to the unchanged authoring functions.
//
// The group path never falls back to personal behaviour. An absent or unrecognised
// action_management hint yields an empty operation set, which leaves every write gate refusing --
// a missing server hint must not become a silent authorization bypass on the client. Editing,
// deleting and testing a specific action additionally require the action to belong to this group
// and to carry the operation in its own action_actions, exactly as the group prompt gate does.

import { ApiError, api } from './apiClient';
import {
    buildEditorWrite, isRecord,
    type ActionConfiguration, type ActionTypeDefinition, type AuthoringResource,
} from './workspaceAuthoring';
import {
    deleteAuthoringAction, fetchActionEditor, fetchActionTypes, fetchAuthoringActions,
    saveActionConfiguration,
} from './workspaceAuthoringApi';
import {
    fetchActionEditorHints, fetchActionIdentities, testWorkspaceAction, type ActionEditorHints,
} from './workspaceActionServices';
import type { ActionIdentity, ActionTestGroupScope } from './workspaceActionTypes';
import type { EditorWorkspaceScope } from './workspaceEditorDrafts';
import { requireWorkspaceId, workspaceBasePath } from './workspaceContext';

export type ActionScope =
    | { kind: 'personal' }
    | { kind: 'group'; id: string; name: string };

export const ACTION_OPERATIONS = ['create', 'edit', 'delete', 'test'] as const;
export type ActionOperation = typeof ACTION_OPERATIONS[number];

/**
 * Thrown when the current scope forbids listing identities at all -- a group member gets a 403 (or
 * a 404 for a workspace with no identity route), as opposed to an empty-but-readable list. The
 * action editor catches this to keep neutral "kept as is" copy instead of implying no identities
 * are configured, and it never falls back to reading personal identities.
 */
export class IdentitiesNotPermittedError extends Error {
    constructor(message = 'Reusable identities are not available in this workspace.') {
        super(message);
        this.name = 'IdentitiesNotPermittedError';
    }
}

export interface ActionWorkbenchAdapter {
    scope: ActionScope;
    /** The SPA route the collection and editor live under, e.g. '/workspace/actions'. */
    basePath: string;
    /** Draft-cache partition, so a group A draft never restores into group B or personal. */
    draftScope: EditorWorkspaceScope;
    /** Group test scope threaded into connection tests; undefined for personal. */
    testScope?: ActionTestGroupScope;
    supported: ReadonlySet<ActionOperation>;
    allows: (operation: ActionOperation, action?: ActionConfiguration) => boolean;
    listActions: (signal?: AbortSignal) => Promise<ActionConfiguration[]>;
    fetchTypes: (signal?: AbortSignal) => Promise<ActionTypeDefinition[]>;
    fetchEditorHints: (signal?: AbortSignal) => Promise<ActionEditorHints>;
    fetchEditor: (id: string, providedScope: string, signal?: AbortSignal) => Promise<AuthoringResource<ActionConfiguration>>;
    save: (draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null) => Promise<AuthoringResource<ActionConfiguration>>;
    deleteAction: (action: ActionConfiguration) => Promise<void>;
    listIdentities: (signal?: AbortSignal) => Promise<ActionIdentity[]>;
    test: (
        draft: ActionConfiguration, original: AuthoringResource<ActionConfiguration> | null,
        definition: ActionTypeDefinition, signal?: AbortSignal,
    ) => Promise<unknown>;
}

/**
 * The operations an `action_management` hint offers.
 *
 * Mirrors `advertisedPromptOperations`: an unrecognised block (missing, wrong schema, or a
 * non-string entry) yields the empty set rather than a guess, so a malformed hint disables
 * writing rather than enabling it.
 */
export function advertisedActionOperations(value: unknown): ReadonlySet<ActionOperation> {
    if (!isRecord(value) || value.schema_version !== 1 || !Array.isArray(value.operations)
        || !value.operations.every((operation) => typeof operation === 'string')) {
        return new Set();
    }
    const offered = value.operations;
    return new Set(ACTION_OPERATIONS.filter((operation) => offered.includes(operation)));
}

/**
 * Whether an operation is allowed in a scope.
 *
 * Personal scope allows everything, exactly as the section did before it was scoped. Group scope
 * requires the workspace-level `action_management` hint to offer the operation, and edit, delete
 * and test additionally require the specific action to belong to this group and to carry the
 * operation in its own `action_actions`. Create is workspace-level with no per-action subject.
 * There is deliberately no fallback that enables an action when the hint is empty or absent.
 */
export function actionOperationAllowed(
    scope: ActionScope,
    supported: ReadonlySet<ActionOperation>,
    operation: ActionOperation,
    action?: ActionConfiguration,
): boolean {
    if (scope.kind === 'personal') {
        return true;
    }
    if (!supported.has(operation)) {
        return false;
    }
    if (operation === 'create') {
        return true;
    }
    if (!action || action.group_id !== scope.id) {
        return false;
    }
    return Array.isArray(action.action_actions) && action.action_actions.includes(operation);
}

export const PERSONAL_ACTION_WORKBENCH: ActionWorkbenchAdapter = {
    scope: { kind: 'personal' },
    basePath: '/workspace/actions',
    draftScope: { kind: 'personal' },
    supported: new Set(ACTION_OPERATIONS),
    allows: () => true,
    listActions: (signal) => fetchAuthoringActions(signal),
    fetchTypes: (signal) => fetchActionTypes(signal),
    fetchEditorHints: (signal) => fetchActionEditorHints(signal),
    fetchEditor: (id, providedScope, signal) => fetchActionEditor(id, providedScope, signal),
    save: (draft, original) => saveActionConfiguration(draft, original),
    deleteAction: async (action) => {
        await deleteAuthoringAction(action.id);
    },
    listIdentities: (signal) => fetchActionIdentities(signal),
    test: (draft, original, definition, signal) => testWorkspaceAction(draft, original, definition, signal),
};

function groupActionsUrl(groupId: string, actionId?: string): string {
    const base = `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/actions`;
    return actionId ? `${base}/${encodeURIComponent(requireWorkspaceId(actionId))}` : base;
}

function groupIdentitiesUrl(groupId: string): string {
    return `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/identities`;
}

/**
 * Prove a returned action belongs to the requested group, as the group prompt reader does. A
 * provided global action merged in read-only is accepted; anything scoped to another group or to
 * a person is refused rather than rendered.
 */
function assertGroupActionScope(action: ActionConfiguration, groupId: string, id?: string): void {
    if (!action || typeof action.id !== 'string' || !action.id
        || (id !== undefined && action.id !== id)
        || !(action.is_global === true || action.group_id === groupId)) {
        throw new Error('The action response does not match this group. Refresh and try again.');
    }
}

/** The editor contract, validated the same way workspaceAuthoringApi validates the personal one. */
function assertGroupEditorResource(
    response: AuthoringResource<ActionConfiguration>, groupId: string, id?: string,
): AuthoringResource<ActionConfiguration> {
    if (!isRecord(response) || !isRecord(response.record)
        || typeof response.read_only !== 'boolean'
        || (response.revision != null && typeof response.revision !== 'string')
        || (!response.read_only && (!response.revision || typeof response.record.id !== 'string' || !response.record.id))
        || !Array.isArray(response.secret_paths)
        || !response.secret_paths.every((path) => typeof path === 'string' && path.startsWith('/'))) {
        throw new Error('The workspace returned an invalid editor resource. Reload before trying again.');
    }
    assertGroupActionScope(response.record, groupId, id);
    return { ...response, revision: response.revision ?? '' };
}

function actionsFromResponse(value: unknown): ActionConfiguration[] {
    if (!isRecord(value) || !Array.isArray(value.actions) || !value.actions.every(isRecord)) {
        throw new Error('The workspace returned an invalid action list. Reload before trying again.');
    }
    return value.actions as ActionConfiguration[];
}

/**
 * `action_actions` is a read-only projection the server never accepts back: the plugin schema is
 * `additionalProperties: false` and does not list it, and it is not a managed field. Echoing it in
 * `updates` or `removed_paths` is a 400. A fresh read carries it, so a restored draft whose value
 * differs from the original would otherwise emit it. Strip it from both sides of the diff so
 * buildEditorWrite emits neither an update nor a removed path for it.
 */
function withoutActionProjectionFields<T extends ActionConfiguration>(record: T): T {
    if (!isRecord(record) || !('action_actions' in record)) {
        return record;
    }
    const clone = { ...(record as Record<string, unknown>) };
    delete clone.action_actions;
    return clone as T;
}

/**
 * Map the group `action-options` envelope onto ActionEditorHints. The group editor needs only the
 * five tenant-level Key Vault reminder defaults; unlike the personal `/api/user/agent/settings`
 * read it carries no personal flags and no personal model endpoints. The envelope is validated
 * strictly, so a drifted shape throws rather than silently rendering blank defaults, and `canAuthor`
 * comes from the adapter gate, never from a server flag on this response.
 */
function groupEditorHints(value: unknown, canAuthor: boolean): ActionEditorHints {
    if (!isRecord(value) || !isRecord(value.secret_reminders)) {
        throw new Error('The workspace returned invalid action options. Reload before trying again.');
    }
    const reminders = value.secret_reminders;
    if (typeof reminders.storage_enabled !== 'boolean' || typeof reminders.reminders_enabled !== 'boolean'
        || typeof reminders.require_expiration !== 'boolean' || typeof reminders.lead_days !== 'number'
        || typeof reminders.contact_email !== 'string') {
        throw new Error('The workspace returned invalid action options. Reload before trying again.');
    }
    const days = reminders.lead_days;
    return {
        canAuthor,
        storageEnabled: reminders.storage_enabled,
        remindersEnabled: reminders.reminders_enabled,
        requireExpiration: reminders.require_expiration,
        reminderLeadDays: Number.isInteger(days) && days >= 1 && days <= 3650 ? days : 30,
        reminderEmail: reminders.contact_email,
    };
}

export function createGroupActionWorkbench(
    scope: Extract<ActionScope, { kind: 'group' }>, management: unknown,
): ActionWorkbenchAdapter {
    if (scope.kind !== 'group') {
        throw new Error('Group actions require an explicit group scope.');
    }
    const groupId = requireWorkspaceId(scope.id);
    const supported = advertisedActionOperations(management);
    const testScope: ActionTestGroupScope = { id: groupId, name: scope.name };
    const allows = (operation: ActionOperation, action?: ActionConfiguration) =>
        actionOperationAllowed(scope, supported, operation, action);
    return {
        scope,
        basePath: `${workspaceBasePath(scope)}/actions`,
        draftScope: { kind: 'group', id: groupId },
        testScope,
        supported,
        allows,
        listActions: async (signal) => {
            const response = await api.get<unknown>(groupActionsUrl(groupId), signal);
            const actions = actionsFromResponse(response);
            actions.forEach((action) => assertGroupActionScope(action, groupId));
            return actions;
        },
        fetchTypes: async (signal) => {
            const response = await api.get<unknown>(
                `/api/groups/${encodeURIComponent(groupId)}/actions/types`, signal);
            if (!isRecord(response) || !Array.isArray(response.types) || !response.types.every(isRecord)) {
                throw new Error('The workspace returned an invalid action type list.');
            }
            return response.types as unknown as ActionTypeDefinition[];
        },
        fetchEditorHints: async (signal) => {
            const response = await api.get<unknown>(
                `/api/groups/${encodeURIComponent(groupId)}/action-options`, signal);
            return groupEditorHints(response, allows('create'));
        },
        fetchEditor: async (id, _providedScope, signal) => {
            const response = await api.get<AuthoringResource<ActionConfiguration>>(groupActionsUrl(groupId, id), signal);
            return assertGroupEditorResource(response, groupId, id);
        },
        save: async (draft, original) => {
            if (!allows(original ? 'edit' : 'create', original?.record ?? draft)) {
                throw new Error(original ? 'Editing this action is not available.' : 'Creating actions is not available in this group.');
            }
            const write = buildEditorWrite(
                withoutActionProjectionFields(draft),
                original ? { ...original, record: withoutActionProjectionFields(original.record) } : null,
            );
            if (!original) delete write.updates.id;
            const response = original
                ? await api.patch<AuthoringResource<ActionConfiguration>>(groupActionsUrl(groupId, original.record.id), write)
                : await api.post<AuthoringResource<ActionConfiguration>>(groupActionsUrl(groupId), write);
            return assertGroupEditorResource(response, groupId, original?.record.id);
        },
        deleteAction: async (action) => {
            if (!allows('delete', action)) {
                throw new Error('Deleting this action is not available.');
            }
            await api.delete<{ success: boolean }>(groupActionsUrl(groupId, action.id));
        },
        listIdentities: async (signal) => {
            // M5A: read the native group identity list and offer the ones an action may bind. The
            // route is immutable and page-group scoped, so it never resolves the account's active
            // group. A 403 (member) or 404 (no route) means "not available here": raise
            // IdentitiesNotPermittedError so the editor keeps neutral copy rather than reading
            // personal identities. Every served row must belong to this group, and only identities
            // the server marks usable for actions are offered -- with no client-side default or
            // alias, since the backend normalizes usage_contexts exactly as its save-time check does.
            let response: unknown;
            try {
                response = await api.get<unknown>(groupIdentitiesUrl(groupId), signal);
            } catch (cause) {
                if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) {
                    throw new IdentitiesNotPermittedError();
                }
                throw cause;
            }
            // A malformed envelope (no identities array) is a hard load error, not an empty
            // successful load: raise so the editor leaves resolvable false and shows the load
            // error, keeping a bound identity's neutral "kept as is" copy instead of calling it
            // "Unavailable". This mirrors identityWorkbench's strict envelope check.
            if (!isRecord(response) || !Array.isArray(response.identities)) {
                throw new Error('The identity response was malformed. Refresh and try again.');
            }
            const rows = response.identities;
            return rows.filter(isRecord).filter((identity) => {
                if (identity.group_id !== groupId) {
                    throw new Error('The identity response does not match this group. Refresh and try again.');
                }
                return Array.isArray(identity.usage_contexts) && identity.usage_contexts.includes('action');
            }).map((identity) => {
                const credentials = isRecord(identity.credentials) ? identity.credentials : {};
                return {
                    id: String(identity.id ?? ''),
                    name: String(identity.name ?? ''),
                    auth_type: String(credentials.auth_type ?? ''),
                    description: identity.description ? String(identity.description) : undefined,
                    scope_type: 'group',
                    scope_id: groupId,
                } satisfies ActionIdentity;
            });
        },
        test: (draft, original, definition, signal) => testWorkspaceAction(draft, original, definition, signal, testScope),
    };
}
