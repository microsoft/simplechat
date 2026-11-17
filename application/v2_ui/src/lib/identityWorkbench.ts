// identityWorkbench.ts
// Scope-aware identity reads and writes for the workspace identities section.
//
// Personal authoring uses the strict /api/user/identities family. No operation falls back to a
// classic or unversioned route. Personal, group and public scopes use conditional edits and
// deletes.
//
// The group and public paths never fall back to personal behaviour. An absent or unrecognised
// identity_management hint yields an empty operation set, which leaves every write gate refusing --
// a missing server hint must not become a silent authorization bypass on the client. Editing and
// deleting a specific identity additionally require it to belong to this workspace (its group_id
// for a group, its public_workspace_id for a public workspace) and to carry the operation in its
// own identity_actions, exactly as the group prompt gate does.
//
// Group scope carries a conditional write: PATCH and DELETE send expected_etag in the JSON body
// (missing is 400, stale is 409). A stale-etag 409 becomes an IdentityConflictError the section
// turns into "your draft is kept, refresh and retry". A delete refused because the identity is
// still referenced returns a 409 with error_code "identity_in_use"; that becomes an
// IdentityInUseError carrying the references, so the section can name what still uses it.
//
// Global scope is the administrator's deployment-wide identities, edited on the administrator-only
// Admin Settings page through /api/admin/workspace-identities/global/identities. Those routes are
// the older family: the record carries no etag and no identity_actions, so the administrator-only
// surface is the gate (the server's admin check is the authority) and an edit is last-write-wins,
// as it is in the classic editor. The adapter still honours what a record does advertise: it
// follows identity_actions when present, sends expected_etag when the record has an etag, and
// reads a 409 or 412 as a conflict, so a server that starts versioning these records needs no
// change here. A delete refused because actions still use the identity answers the same 409
// "identity_in_use" as the strict routes.

import { ApiError, api, requestWithStatus } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import type { WorkspaceIdentity } from './types';

export type IdentityScope =
    | { kind: 'personal'; id?: string }
    | { kind: 'group'; id: string; name: string }
    | { kind: 'public'; id: string; name: string }
    | { kind: 'global' };

export const IDENTITY_OPERATIONS = ['create', 'edit', 'delete'] as const;
export type IdentityOperation = typeof IDENTITY_OPERATIONS[number];

/** The scope id every global identity carries, as its `global_id` and its `scope_type`. */
export const GLOBAL_IDENTITY_SCOPE_ID = 'global';

export interface IdentityWrite {
    name?: string;
    description?: string;
    provider?: string;
    source_type?: string;
    usage_contexts?: string[];
    supported_source_types?: string[];
    metadata?: Record<string, unknown>;
    credentials?: Record<string, unknown>;
}

/** A resource that still references an identity, blocking its deletion. */
export interface IdentityReference {
    kind: string;
    id: string;
    name: string;
}

/**
 * A conditional-write conflict (409 without an identity_in_use code). The section catches this
 * specifically: a stale etag must keep the editor and its draft open and offer a refresh, not
 * discard the edit.
 */
export class IdentityConflictError extends Error {
    constructor(
        message = 'This workspace identity was modified. Reload and try again.',
    ) {
        super(message);
        this.name = 'IdentityConflictError';
    }
}

/** A delete refused because the identity is still referenced (409 identity_in_use). */
export class IdentityInUseError extends Error {
    readonly references: IdentityReference[];
    constructor(
        references: IdentityReference[],
        message = 'This workspace identity is still in use.',
    ) {
        super(message);
        this.name = 'IdentityInUseError';
        this.references = references;
    }
}

export interface IdentityWorkbenchAdapter {
    scope: IdentityScope;
    /** Whether the workspace advertises identity creation, so the section shows a New control. */
    manageable: boolean;
    supported: ReadonlySet<IdentityOperation>;
    /**
     * The credential methods this scope's editor offers, when that is narrower than what the chosen
     * capabilities allow. Absent means every method the capabilities allow.
     */
    authTypes?: readonly string[];
    allows: (operation: IdentityOperation, identity?: WorkspaceIdentity) => boolean;
    list: (signal?: AbortSignal) => Promise<WorkspaceIdentity[]>;
    create: (write: IdentityWrite) => Promise<WorkspaceIdentity>;
    update: (identity: WorkspaceIdentity, write: IdentityWrite) => Promise<WorkspaceIdentity>;
    remove: (identity: WorkspaceIdentity) => Promise<void>;
}

/**
 * The operations an `identity_management` hint offers.
 *
 * Mirrors `advertisedPromptOperations`: an unrecognised block (missing, wrong schema, or a
 * non-string entry) yields the empty set rather than a guess, so a malformed hint disables
 * writing rather than enabling it.
 */
export function advertisedIdentityOperations(value: unknown): ReadonlySet<IdentityOperation> {
    if (!isRecord(value) || value.schema_version !== 1 || !Array.isArray(value.operations)
        || !value.operations.every((operation) => typeof operation === 'string')) {
        return new Set();
    }
    const offered = value.operations;
    return new Set(IDENTITY_OPERATIONS.filter((operation) => offered.includes(operation)));
}

/**
 * Whether an operation is allowed in a scope.
 *
 * Personal operations use the strict session-owned API. A group or public scope requires the workspace-level
 * `identity_management` hint to offer the operation, and edit/delete additionally require the
 * specific identity to belong to this workspace (its `group_id` for a group, its
 * `public_workspace_id` for a public workspace) and to carry the operation in its own
 * `identity_actions`. There is deliberately no fallback that enables an action when the hint is
 * empty or absent, and no scope ever falls back to personal behaviour.
 *
 * The global scope is the exception that proves the rule: its surface is administrator-only and
 * its records carry no `identity_actions`, so an identity that belongs to the global scope is
 * editable and deletable. A record that does carry `identity_actions` is held to them like any
 * other, and a malformed value refuses rather than allows.
 */
export function identityOperationAllowed(
    scope: IdentityScope,
    supported: ReadonlySet<IdentityOperation>,
    operation: IdentityOperation,
    identity?: WorkspaceIdentity,
): boolean {
    if (!supported.has(operation)) {
        return false;
    }
    if (operation === 'create') {
        return true;
    }
    if (!identity) {
        return false;
    }
    if (scope.kind === 'global') {
        if (identity.scope_type !== 'global' || identity.global_id !== GLOBAL_IDENTITY_SCOPE_ID) {
            return false;
        }
        const advertised = identity.identity_actions;
        return advertised === undefined || (Array.isArray(advertised) && advertised.includes(operation));
    }
    const ownerId = scope.kind === 'personal' ? identity.user_id
        : scope.kind === 'public' ? identity.public_workspace_id : identity.group_id;
    if (scope.kind === 'personal' && identity.scope_type !== 'personal') {
        return false;
    }
    if (scope.id !== undefined && ownerId !== scope.id) {
        return false;
    }
    return Array.isArray(identity.identity_actions) && identity.identity_actions.includes(operation);
}

function personalIdentitiesUrl(identityId?: string): string {
    const base = '/api/user/identities';
    return identityId ? `${base}/${encodeURIComponent(requireWorkspaceId(identityId))}` : base;
}

function assertPersonalIdentityScope(identity: WorkspaceIdentity, ownerId?: string, id?: string): void {
    if (!isRecord(identity) || typeof identity.id !== 'string' || !identity.id
        || identity.scope_type !== 'personal' || typeof identity.user_id !== 'string' || !identity.user_id
        || (ownerId !== undefined && identity.user_id !== ownerId)
        || (id !== undefined && identity.id !== id)) {
        throw new Error('The identity response does not match your workspace. Refresh and try again.');
    }
    requiredEtag(identity);
}

export function createPersonalIdentityWorkbench(ownerId?: string): IdentityWorkbenchAdapter {
    const scope: IdentityScope = { kind: 'personal', id: ownerId };
    const supported = new Set<IdentityOperation>(IDENTITY_OPERATIONS);
    const allows = (operation: IdentityOperation, identity?: WorkspaceIdentity) =>
        identityOperationAllowed(scope, supported, operation, identity);
    return {
        scope, supported, manageable: true, allows,
        list: async (signal) => {
            const response = await api.get<unknown>(personalIdentitiesUrl(), signal);
            const identities = identitiesFromResponse(response);
            identities.forEach((identity) => assertPersonalIdentityScope(identity, ownerId));
            return identities;
        },
        create: async (write) => {
            const response = await api.post<unknown>(personalIdentitiesUrl(), identityWriteBody(write));
            const created = identityFromResponse(response);
            assertPersonalIdentityScope(created, ownerId);
            return created;
        },
        update: async (identity, write) => {
            if (!allows('edit', identity)) {
                throw new Error('Editing this identity is not available.');
            }
            const response = await conditionalIdentityWrite('PATCH', personalIdentitiesUrl(identity.id), {
                ...identityWriteBody(write), expected_etag: requiredEtag(identity),
            });
            const updated = identityFromResponse(response);
            assertPersonalIdentityScope(updated, ownerId, identity.id);
            return updated;
        },
        remove: async (identity) => {
            if (!allows('delete', identity)) {
                throw new Error('Deleting this identity is not available.');
            }
            await conditionalIdentityWrite('DELETE', personalIdentitiesUrl(identity.id), {
                expected_etag: requiredEtag(identity),
            });
        },
    };
}

export const PERSONAL_IDENTITY_WORKBENCH = createPersonalIdentityWorkbench();

function groupIdentitiesUrl(groupId: string, identityId?: string): string {
    const base = `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/identities`;
    return identityId ? `${base}/${encodeURIComponent(requireWorkspaceId(identityId))}` : base;
}

/** The list route wraps the collection under `identities`; tolerate a bare array defensively. */
function identitiesFromResponse(value: unknown): WorkspaceIdentity[] {
    if (Array.isArray(value)) {
        return value as WorkspaceIdentity[];
    }
    if (isRecord(value) && Array.isArray(value.identities)) {
        return value.identities as WorkspaceIdentity[];
    }
    throw new Error('The workspace returned an invalid identity list. Refresh and try again.');
}

/** The read, create and update routes wrap the record under `identity`. */
function identityFromResponse(value: unknown): WorkspaceIdentity {
    if (isRecord(value) && isRecord(value.identity)) {
        return value.identity as WorkspaceIdentity;
    }
    throw new Error('The identity response was malformed. Refresh and try again.');
}

/** Prove a returned identity belongs to the requested group, as the group document reader does. */
function assertGroupIdentityScope(identity: WorkspaceIdentity, groupId: string, id?: string): void {
    if (!identity || typeof identity.id !== 'string' || !identity.id
        || (id !== undefined && identity.id !== id)
        || identity.group_id !== groupId) {
        throw new Error('The identity response does not match this group. Refresh and try again.');
    }
}

function requiredEtag(identity: WorkspaceIdentity): string {
    const etag = typeof identity.etag === 'string' ? identity.etag.trim() : '';
    if (!etag) {
        throw new Error('This identity is missing its version marker. Refresh and try again.');
    }
    return etag;
}

/** Strip anything the strict native routes reject; send only the documented write fields. */
function identityWriteBody(write: IdentityWrite): Record<string, unknown> {
    const body: Record<string, unknown> = {};
    if (write.name !== undefined) body.name = write.name;
    if (write.description !== undefined) body.description = write.description;
    if (write.provider !== undefined) body.provider = write.provider;
    if (write.source_type !== undefined) body.source_type = write.source_type;
    if (write.usage_contexts !== undefined) body.usage_contexts = write.usage_contexts;
    if (write.supported_source_types !== undefined) body.supported_source_types = write.supported_source_types;
    if (write.metadata !== undefined) body.metadata = write.metadata;
    if (write.credentials !== undefined) body.credentials = write.credentials;
    return body;
}

function identityReferences(value: unknown): IdentityReference[] {
    if (!Array.isArray(value)) {
        return [];
    }
    return value.filter(isRecord).map((entry) => ({
        kind: String(entry.kind ?? ''),
        id: String(entry.id ?? ''),
        name: String(entry.name ?? ''),
    }));
}

/**
 * PATCH or DELETE an identity and read what a refusal means.
 *
 * `conflictStatuses` are the statuses that mean "the record changed" or "the record is still in
 * use". Every strict scope answers those with 409 alone. The global scope also accepts 412, the
 * status HTTP gives a failed precondition, because its routes are the older family and nothing
 * pins which of the two a versioned version of them would choose.
 */
async function conditionalIdentityWrite(
    method: 'PATCH' | 'DELETE', url: string, body?: Record<string, unknown>,
    conflictStatuses: readonly number[] = [409],
): Promise<unknown> {
    try {
        const response = await requestWithStatus<unknown>(url, { method, body });
        return response.data;
    } catch (cause) {
        if (cause instanceof ApiError && conflictStatuses.includes(cause.status)) {
            const payload = cause.payload;
            if (isRecord(payload) && payload.error_code === 'identity_in_use') {
                const inUseMessage = typeof payload.error === 'string' ? payload.error : undefined;
                throw new IdentityInUseError(identityReferences(payload.references), inUseMessage);
            }
            const serverMessage = isRecord(payload) && typeof payload.error === 'string'
                ? payload.error
                : undefined;
            throw new IdentityConflictError(serverMessage);
        }
        throw cause;
    }
}

export function createGroupIdentityWorkbench(
    scope: Extract<IdentityScope, { kind: 'group' }>, management: unknown,
): IdentityWorkbenchAdapter {
    if (scope.kind !== 'group') {
        throw new Error('Group identities require an explicit group scope.');
    }
    const groupId = requireWorkspaceId(scope.id);
    const supported = advertisedIdentityOperations(management);
    const allows = (operation: IdentityOperation, identity?: WorkspaceIdentity) =>
        identityOperationAllowed(scope, supported, operation, identity);
    return {
        scope,
        manageable: supported.has('create'),
        supported,
        allows,
        list: async (signal) => {
            const response = await api.get<unknown>(groupIdentitiesUrl(groupId), signal);
            const identities = identitiesFromResponse(response);
            identities.forEach((identity) => assertGroupIdentityScope(identity, groupId));
            return identities;
        },
        create: async (write) => {
            if (!allows('create')) {
                throw new Error('Creating identities is not available in this group.');
            }
            const response = await api.post<unknown>(groupIdentitiesUrl(groupId), identityWriteBody(write));
            const created = identityFromResponse(response);
            assertGroupIdentityScope(created, groupId);
            return created;
        },
        update: async (identity, write) => {
            if (!allows('edit', identity)) {
                throw new Error('Editing this identity is not available.');
            }
            const updated = await conditionalIdentityWrite('PATCH', groupIdentitiesUrl(groupId, identity.id), {
                ...identityWriteBody(write), expected_etag: requiredEtag(identity),
            });
            const record = identityFromResponse(updated);
            assertGroupIdentityScope(record, groupId, identity.id);
            return record;
        },
        remove: async (identity) => {
            if (!allows('delete', identity)) {
                throw new Error('Deleting this identity is not available.');
            }
            await conditionalIdentityWrite('DELETE', groupIdentitiesUrl(groupId, identity.id), {
                expected_etag: requiredEtag(identity),
            });
        },
    };
}

function publicIdentitiesUrl(workspaceId: string, identityId?: string): string {
    const base = `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(workspaceId))}/identities`;
    return identityId ? `${base}/${encodeURIComponent(requireWorkspaceId(identityId))}` : base;
}

/** Prove a returned identity belongs to the requested public workspace, as the public document reader does. */
function assertPublicIdentityScope(identity: WorkspaceIdentity, workspaceId: string, id?: string): void {
    if (!identity || typeof identity.id !== 'string' || !identity.id
        || (id !== undefined && identity.id !== id)
        || identity.public_workspace_id !== workspaceId) {
        throw new Error('The identity response does not match this workspace. Refresh and try again.');
    }
}

export function createPublicIdentityWorkbench(
    scope: Extract<IdentityScope, { kind: 'public' }>, management: unknown,
): IdentityWorkbenchAdapter {
    if (scope.kind !== 'public') {
        throw new Error('Public identities require an explicit public scope.');
    }
    const workspaceId = requireWorkspaceId(scope.id);
    const supported = advertisedIdentityOperations(management);
    const allows = (operation: IdentityOperation, identity?: WorkspaceIdentity) =>
        identityOperationAllowed(scope, supported, operation, identity);
    return {
        scope,
        manageable: supported.has('create'),
        supported,
        allows,
        list: async (signal) => {
            const response = await api.get<unknown>(publicIdentitiesUrl(workspaceId), signal);
            const identities = identitiesFromResponse(response);
            identities.forEach((identity) => assertPublicIdentityScope(identity, workspaceId));
            return identities;
        },
        create: async (write) => {
            if (!allows('create')) {
                throw new Error('Creating identities is not available in this workspace.');
            }
            const response = await api.post<unknown>(publicIdentitiesUrl(workspaceId), identityWriteBody(write));
            const created = identityFromResponse(response);
            assertPublicIdentityScope(created, workspaceId);
            return created;
        },
        update: async (identity, write) => {
            if (!allows('edit', identity)) {
                throw new Error('Editing this identity is not available.');
            }
            const updated = await conditionalIdentityWrite('PATCH', publicIdentitiesUrl(workspaceId, identity.id), {
                ...identityWriteBody(write), expected_etag: requiredEtag(identity),
            });
            const record = identityFromResponse(updated);
            assertPublicIdentityScope(record, workspaceId, identity.id);
            return record;
        },
        remove: async (identity) => {
            if (!allows('delete', identity)) {
                throw new Error('Deleting this identity is not available.');
            }
            await conditionalIdentityWrite('DELETE', publicIdentitiesUrl(workspaceId, identity.id), {
                expected_etag: requiredEtag(identity),
            });
        },
    };
}

const GLOBAL_IDENTITIES_URL = '/api/admin/workspace-identities/global/identities';

/**
 * The statuses a global write reads as "the record changed or is in use": 409, which every strict
 * scope uses, and 412, the status HTTP gives a failed precondition.
 */
const GLOBAL_CONFLICT_STATUSES: readonly number[] = [409, 412];

/**
 * The credential methods the administrator's global editor offers. Mirrors `data-auth-type-options`
 * on the classic Global Identities pane (templates/admin/_panes/workspace-identities.html), which
 * leaves out anonymous.
 */
export const GLOBAL_IDENTITY_AUTH_TYPES: readonly string[] = [
    'username_password', 'api_key', 'bearer_token', 'client_secret', 'connection_string', 'managed_identity',
];

/** One identity's address. An id that is empty or could change the path is refused here, never sent. */
function globalIdentityUrl(identityId: string): string {
    return `${GLOBAL_IDENTITIES_URL}/${encodeURIComponent(requireWorkspaceId(identityId))}`;
}

/** Prove a returned identity is a global one, as the other scopes prove theirs. */
function assertGlobalIdentityScope(identity: WorkspaceIdentity, id?: string): void {
    if (!isRecord(identity) || typeof identity.id !== 'string' || !identity.id
        || (id !== undefined && identity.id !== id)
        || identity.scope_type !== 'global' || identity.global_id !== GLOBAL_IDENTITY_SCOPE_ID) {
        throw new Error('The identity response is not a global identity. Refresh and try again.');
    }
}

/** The version marker a record carries when its server versions it. The global routes send none today. */
function optionalEtag(identity: WorkspaceIdentity): string | undefined {
    const etag = typeof identity.etag === 'string' ? identity.etag.trim() : '';
    return etag || undefined;
}

/**
 * The administrator's global identities, over the admin routes that name the global scope in the
 * path. Nothing about the signed-in account or an active workspace decides which identities these
 * are, and no operation falls back to another scope's routes.
 */
export function createGlobalIdentityWorkbench(): IdentityWorkbenchAdapter {
    const scope: IdentityScope = { kind: 'global' };
    const supported = new Set<IdentityOperation>(IDENTITY_OPERATIONS);
    const allows = (operation: IdentityOperation, identity?: WorkspaceIdentity) =>
        identityOperationAllowed(scope, supported, operation, identity);
    return {
        scope, supported, manageable: true, authTypes: GLOBAL_IDENTITY_AUTH_TYPES, allows,
        list: async (signal) => {
            const identities = identitiesFromResponse(await api.get<unknown>(GLOBAL_IDENTITIES_URL, signal));
            identities.forEach((identity) => assertGlobalIdentityScope(identity));
            return identities;
        },
        create: async (write) => {
            if (!allows('create')) {
                throw new Error('Creating identities is not available.');
            }
            const response = await api.post<unknown>(GLOBAL_IDENTITIES_URL, identityWriteBody(write));
            const created = identityFromResponse(response);
            assertGlobalIdentityScope(created);
            return created;
        },
        update: async (identity, write) => {
            if (!allows('edit', identity)) {
                throw new Error('Editing this identity is not available.');
            }
            const etag = optionalEtag(identity);
            const updated = await conditionalIdentityWrite('PATCH', globalIdentityUrl(identity.id), {
                ...identityWriteBody(write), ...(etag ? { expected_etag: etag } : {}),
            }, GLOBAL_CONFLICT_STATUSES);
            const record = identityFromResponse(updated);
            assertGlobalIdentityScope(record, identity.id);
            return record;
        },
        remove: async (identity) => {
            if (!allows('delete', identity)) {
                throw new Error('Deleting this identity is not available.');
            }
            const etag = optionalEtag(identity);
            await conditionalIdentityWrite(
                'DELETE', globalIdentityUrl(identity.id), etag ? { expected_etag: etag } : undefined,
                GLOBAL_CONFLICT_STATUSES,
            );
        },
    };
}

export const GLOBAL_IDENTITY_WORKBENCH = createGlobalIdentityWorkbench();