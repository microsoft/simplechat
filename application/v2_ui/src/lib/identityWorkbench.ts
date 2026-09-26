// identityWorkbench.ts
// Scope-aware identity reads and writes for the workspace identities section.
//
// The identities section shipped personal-only: it called the /api/workspace-identities/personal
// functions in workspaceApi.ts directly. This module is the seam that lets the section serve a
// group workspace natively, the way promptWorkbench.ts and actionWorkbench.ts became scope-aware,
// and from M10B a public workspace too. An IdentityScope selects which URLs are used and which
// per-operation gates apply. The personal adapter is a thin pass-through so its behaviour stays
// byte-identical in effect: same list URL, same delete URL, same classic hand-off for creating one.
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

import { ApiError, api, requestWithStatus } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import {
    deleteIdentity as deletePersonalIdentity,
    fetchIdentities as fetchPersonalIdentities,
} from './workspaceApi';
import type { WorkspaceIdentity } from './types';

export type IdentityScope =
    | { kind: 'personal' }
    | { kind: 'group'; id: string; name: string }
    | { kind: 'public'; id: string; name: string };

export const IDENTITY_OPERATIONS = ['create', 'edit', 'delete'] as const;
export type IdentityOperation = typeof IDENTITY_OPERATIONS[number];

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
    allows: (operation: IdentityOperation, identity?: WorkspaceIdentity) => boolean;
    list: (signal?: AbortSignal) => Promise<WorkspaceIdentity[]>;
    create: (write: IdentityWrite) => Promise<WorkspaceIdentity>;
    update: (identity: WorkspaceIdentity, write: IdentityWrite) => Promise<WorkspaceIdentity>;
    remove: (identity: WorkspaceIdentity) => Promise<void>;
    /** Where "adding one is still done in the classic workspace" points, for personal scope. */
    classicPath: string;
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
 * Personal scope allows everything the personal section can do, which is delete; there is no
 * personal create or edit in this surface. A group or public scope requires the workspace-level
 * `identity_management` hint to offer the operation, and edit/delete additionally require the
 * specific identity to belong to this workspace (its `group_id` for a group, its
 * `public_workspace_id` for a public workspace) and to carry the operation in its own
 * `identity_actions`. There is deliberately no fallback that enables an action when the hint is
 * empty or absent, and no scope ever falls back to personal behaviour.
 */
export function identityOperationAllowed(
    scope: IdentityScope,
    supported: ReadonlySet<IdentityOperation>,
    operation: IdentityOperation,
    identity?: WorkspaceIdentity,
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
    if (!identity) {
        return false;
    }
    const ownerId = scope.kind === 'public' ? identity.public_workspace_id : identity.group_id;
    if (ownerId !== scope.id) {
        return false;
    }
    return Array.isArray(identity.identity_actions) && identity.identity_actions.includes(operation);
}

export const PERSONAL_IDENTITY_WORKBENCH: IdentityWorkbenchAdapter = {
    scope: { kind: 'personal' },
    manageable: false,
    supported: new Set(),
    allows: () => true,
    list: (signal) => fetchPersonalIdentities(signal),
    create: () => {
        throw new Error('Creating identities is done in the classic workspace.');
    },
    update: () => {
        throw new Error('Editing identities is done in the classic workspace.');
    },
    remove: async (identity) => {
        await deletePersonalIdentity(identity.id);
    },
    classicPath: '/workspace',
};

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
    return [];
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
function groupWriteBody(write: IdentityWrite): Record<string, unknown> {
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

async function conditionalGroupWrite(
    method: 'PATCH' | 'DELETE', url: string, body: Record<string, unknown>,
): Promise<unknown> {
    try {
        const response = await requestWithStatus<unknown>(url, { method, body });
        return response.data;
    } catch (cause) {
        if (cause instanceof ApiError && cause.status === 409) {
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
            const response = await api.post<unknown>(groupIdentitiesUrl(groupId), groupWriteBody(write));
            const created = identityFromResponse(response);
            assertGroupIdentityScope(created, groupId);
            return created;
        },
        update: async (identity, write) => {
            if (!allows('edit', identity)) {
                throw new Error('Editing this identity is not available.');
            }
            const updated = await conditionalGroupWrite('PATCH', groupIdentitiesUrl(groupId, identity.id), {
                ...groupWriteBody(write), expected_etag: requiredEtag(identity),
            });
            const record = identityFromResponse(updated);
            assertGroupIdentityScope(record, groupId, identity.id);
            return record;
        },
        remove: async (identity) => {
            if (!allows('delete', identity)) {
                throw new Error('Deleting this identity is not available.');
            }
            await conditionalGroupWrite('DELETE', groupIdentitiesUrl(groupId, identity.id), {
                expected_etag: requiredEtag(identity),
            });
        },
        classicPath: '/group_workspaces',
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
            const response = await api.post<unknown>(publicIdentitiesUrl(workspaceId), groupWriteBody(write));
            const created = identityFromResponse(response);
            assertPublicIdentityScope(created, workspaceId);
            return created;
        },
        update: async (identity, write) => {
            if (!allows('edit', identity)) {
                throw new Error('Editing this identity is not available.');
            }
            const updated = await conditionalGroupWrite('PATCH', publicIdentitiesUrl(workspaceId, identity.id), {
                ...groupWriteBody(write), expected_etag: requiredEtag(identity),
            });
            const record = identityFromResponse(updated);
            assertPublicIdentityScope(record, workspaceId, identity.id);
            return record;
        },
        remove: async (identity) => {
            if (!allows('delete', identity)) {
                throw new Error('Deleting this identity is not available.');
            }
            await conditionalGroupWrite('DELETE', publicIdentitiesUrl(workspaceId, identity.id), {
                expected_etag: requiredEtag(identity),
            });
        },
        classicPath: '/public_workspaces',
    };
}