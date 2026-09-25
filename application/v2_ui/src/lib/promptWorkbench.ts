// promptWorkbench.ts
// Scope-aware prompt reads and writes for the workbench.
//
// The workbench shipped personal-only: it called the /api/prompts functions in workspaceApi.ts
// directly. This module is the seam that lets the same component serve a group or public workspace
// without forking it, the way documentOperations.ts became scope-aware in M9B. A PromptScope
// selects which URLs are used, whether favourites exist, and which per-operation gates apply. The
// personal adapter is a thin pass-through so its behaviour stays byte-identical in effect: same
// URLs, same favourites, same flows.
//
// The group and public paths never fall back to personal behaviour. An absent or unrecognised
// prompt_management hint yields an empty operation set, which leaves every write gate refusing --
// a missing server hint must not become a silent authorization bypass on the client. Both shared
// scopes carry a conditional write: PATCH and DELETE send expected_etag in the JSON body
// (the transport this programme's collaboration DELETEs already use), and a 409 becomes a
// PromptConflictError the workbench turns into "your draft is kept, refresh and retry". The public
// scope differs only in its immutable-target URL family and its per-prompt scope proof (public_id).

import { ApiError, api, requestWithStatus } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import {
    createPrompt as createPersonalPrompt,
    deletePrompt as deletePersonalPrompt,
    fetchPrompts as fetchPersonalPrompts,
    updatePrompt as updatePersonalPrompt,
    type PromptWrite,
} from './workspaceApi';
import type { WorkspacePrompt } from './types';

export type PromptScope =
    | { kind: 'personal' }
    | { kind: 'group'; id: string; name: string }
    | { kind: 'public'; id: string; name: string };

export const PROMPT_OPERATIONS = ['create', 'edit', 'delete'] as const;
export type PromptOperation = typeof PROMPT_OPERATIONS[number];

/**
 * A conditional-write conflict (409 `prompt_changed`). The workbench catches this specifically:
 * a stale etag must keep the editor and its draft open and offer a refresh, not discard the edit.
 */
export class PromptConflictError extends Error {
    constructor(
        message = 'This prompt changed since you opened it. Your draft is kept — refresh to load the latest, then save again.',
    ) {
        super(message);
        this.name = 'PromptConflictError';
    }
}

export interface PromptWorkbenchAdapter {
    scope: PromptScope;
    /** Group prompts are shared documents, so a per-user star would change them for everyone. */
    favoritesEnabled: boolean;
    supported: ReadonlySet<PromptOperation>;
    allows: (operation: PromptOperation, prompt?: WorkspacePrompt) => boolean;
    list: (signal?: AbortSignal) => Promise<WorkspacePrompt[]>;
    create: (name: string, content: string, extra?: PromptWrite) => Promise<WorkspacePrompt>;
    update: (prompt: WorkspacePrompt, updates: PromptWrite) => Promise<WorkspacePrompt>;
    remove: (prompt: WorkspacePrompt) => Promise<void>;
}

/**
 * The operations a `prompt_management` hint offers.
 *
 * Mirrors `advertisedDocumentOperations`: an unrecognised block (missing, wrong schema, or a
 * non-string entry) yields the empty set rather than a guess, so a malformed hint disables
 * writing rather than enabling it.
 */
export function advertisedPromptOperations(value: unknown): ReadonlySet<PromptOperation> {
    if (!isRecord(value) || value.schema_version !== 1 || !Array.isArray(value.operations)
        || !value.operations.every((operation) => typeof operation === 'string')) {
        return new Set();
    }
    const offered = value.operations;
    return new Set(PROMPT_OPERATIONS.filter((operation) => offered.includes(operation)));
}

/**
 * Whether an operation is allowed in a scope.
 *
 * Personal scope allows everything, exactly as the section did before it was scoped. Group and
 * public scope require the workspace-level `prompt_management` hint to offer the operation, and
 * edit/delete additionally require the specific prompt to belong to this workspace (by `group_id`
 * for group scope, `public_id` for public scope) and to carry the operation in its own
 * `prompt_actions`. Create is workspace-level with no per-prompt subject; duplicate creates too,
 * so it is gated on create. There is deliberately no fallback that enables an action when the hint
 * is empty or absent.
 */
export function promptOperationAllowed(
    scope: PromptScope,
    supported: ReadonlySet<PromptOperation>,
    operation: PromptOperation,
    prompt?: WorkspacePrompt,
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
    if (!prompt) {
        return false;
    }
    const owningId = scope.kind === 'public' ? prompt.public_id : prompt.group_id;
    if (owningId !== scope.id) {
        return false;
    }
    return Array.isArray(prompt.prompt_actions) && prompt.prompt_actions.includes(operation);
}

export const PERSONAL_PROMPT_WORKBENCH: PromptWorkbenchAdapter = {
    scope: { kind: 'personal' },
    favoritesEnabled: true,
    supported: new Set(PROMPT_OPERATIONS),
    allows: () => true,
    list: (signal) => fetchPersonalPrompts({}, signal),
    create: (name, content, extra) => createPersonalPrompt(name, content, extra),
    update: (prompt, updates) => updatePersonalPrompt(prompt.id, updates),
    remove: async (prompt) => {
        await deletePersonalPrompt(prompt.id);
    },
};

function groupPromptsUrl(groupId: string, promptId?: string, params?: URLSearchParams): string {
    const base = `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/prompts`;
    const path = promptId ? `${base}/${encodeURIComponent(requireWorkspaceId(promptId))}` : base;
    const query = params?.toString();
    return query ? `${path}?${query}` : path;
}

/** Prove a returned prompt belongs to the requested group, as the group document reader does. */
function assertGroupPromptScope(prompt: WorkspacePrompt, groupId: string, id?: string): void {
    if (!prompt || typeof prompt.id !== 'string' || !prompt.id
        || (id !== undefined && prompt.id !== id)
        || prompt.group_id !== groupId) {
        throw new Error('The prompt response does not match this group. Refresh and try again.');
    }
}

/** The new routes wrap the collection under `prompts`; tolerate a bare array defensively. */
function promptsFromResponse(value: unknown): WorkspacePrompt[] {
    if (Array.isArray(value)) {
        return value as WorkspacePrompt[];
    }
    if (isRecord(value) && Array.isArray(value.prompts)) {
        return value.prompts as WorkspacePrompt[];
    }
    return [];
}

function requiredEtag(prompt: WorkspacePrompt): string {
    const etag = typeof prompt.etag === 'string' ? prompt.etag.trim() : '';
    if (!etag) {
        throw new Error('This prompt is missing its version marker. Refresh and try again.');
    }
    return etag;
}

/** Strip is_favorite: it is rejected by the group routes and has no meaning in shared scope. */
function groupWriteBody(updates: PromptWrite): PromptWrite {
    const body: PromptWrite = {};
    if (updates.name !== undefined) {
        body.name = updates.name;
    }
    if (updates.content !== undefined) {
        body.content = updates.content;
    }
    if (updates.description !== undefined) {
        body.description = updates.description;
    }
    return body;
}

async function conditionalGroupWrite(
    method: 'PATCH' | 'DELETE', url: string, body: Record<string, unknown>,
): Promise<WorkspacePrompt | undefined> {
    try {
        const response = await requestWithStatus<WorkspacePrompt>(url, { method, body });
        return response.data;
    } catch (cause) {
        if (cause instanceof ApiError && cause.status === 409) {
            throw new PromptConflictError();
        }
        throw cause;
    }
}

export function createGroupPromptWorkbench(
    scope: Extract<PromptScope, { kind: 'group' }>, management: unknown,
): PromptWorkbenchAdapter {
    if (scope.kind !== 'group') {
        throw new Error('Group prompts require an explicit group scope.');
    }
    const groupId = requireWorkspaceId(scope.id);
    const supported = advertisedPromptOperations(management);
    const allows = (operation: PromptOperation, prompt?: WorkspacePrompt) =>
        promptOperationAllowed(scope, supported, operation, prompt);
    return {
        scope,
        favoritesEnabled: false,
        supported,
        allows,
        list: async (signal) => {
            const params = new URLSearchParams({ page: '1', page_size: '500' });
            const response = await api.get<unknown>(groupPromptsUrl(groupId, undefined, params), signal);
            const prompts = promptsFromResponse(response);
            prompts.forEach((prompt) => assertGroupPromptScope(prompt, groupId));
            return prompts;
        },
        create: async (name, content, extra = {}) => {
            if (!allows('create')) {
                throw new Error('Creating prompts is not available in this group.');
            }
            const created = await api.post<WorkspacePrompt>(groupPromptsUrl(groupId), {
                name, content, description: extra.description ?? '',
            });
            assertGroupPromptScope(created, groupId);
            return created;
        },
        update: async (prompt, updates) => {
            if (!allows('edit', prompt)) {
                throw new Error('Editing this prompt is not available.');
            }
            const updated = await conditionalGroupWrite('PATCH', groupPromptsUrl(groupId, prompt.id), {
                ...groupWriteBody(updates), expected_etag: requiredEtag(prompt),
            });
            assertGroupPromptScope(updated as WorkspacePrompt, groupId, prompt.id);
            return updated as WorkspacePrompt;
        },
        remove: async (prompt) => {
            if (!allows('delete', prompt)) {
                throw new Error('Deleting this prompt is not available.');
            }
            await conditionalGroupWrite('DELETE', groupPromptsUrl(groupId, prompt.id), {
                expected_etag: requiredEtag(prompt),
            });
        },
    };
}

function publicPromptsUrl(workspaceId: string, promptId?: string, params?: URLSearchParams): string {
    const base = `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(workspaceId))}/prompts`;
    const path = promptId ? `${base}/${encodeURIComponent(requireWorkspaceId(promptId))}` : base;
    const query = params?.toString();
    return query ? `${path}?${query}` : path;
}

/** Prove a returned prompt belongs to the requested public workspace, as the public reader does. */
function assertPublicPromptScope(prompt: WorkspacePrompt, workspaceId: string, id?: string): void {
    if (!prompt || typeof prompt.id !== 'string' || !prompt.id
        || (id !== undefined && prompt.id !== id)
        || prompt.public_id !== workspaceId) {
        throw new Error('The prompt response does not match this workspace. Refresh and try again.');
    }
}

export function createPublicPromptWorkbench(
    scope: Extract<PromptScope, { kind: 'public' }>, management: unknown,
): PromptWorkbenchAdapter {
    if (scope.kind !== 'public') {
        throw new Error('Public prompts require an explicit public scope.');
    }
    const workspaceId = requireWorkspaceId(scope.id);
    const supported = advertisedPromptOperations(management);
    const allows = (operation: PromptOperation, prompt?: WorkspacePrompt) =>
        promptOperationAllowed(scope, supported, operation, prompt);
    return {
        scope,
        favoritesEnabled: false,
        supported,
        allows,
        list: async (signal) => {
            const params = new URLSearchParams({ page: '1', page_size: '500' });
            const response = await api.get<unknown>(publicPromptsUrl(workspaceId, undefined, params), signal);
            const prompts = promptsFromResponse(response);
            prompts.forEach((prompt) => assertPublicPromptScope(prompt, workspaceId));
            return prompts;
        },
        create: async (name, content, extra = {}) => {
            if (!allows('create')) {
                throw new Error('Creating prompts is not available in this workspace.');
            }
            const created = await api.post<WorkspacePrompt>(publicPromptsUrl(workspaceId), {
                name, content, description: extra.description ?? '',
            });
            assertPublicPromptScope(created, workspaceId);
            return created;
        },
        update: async (prompt, updates) => {
            if (!allows('edit', prompt)) {
                throw new Error('Editing this prompt is not available.');
            }
            const updated = await conditionalGroupWrite('PATCH', publicPromptsUrl(workspaceId, prompt.id), {
                ...groupWriteBody(updates), expected_etag: requiredEtag(prompt),
            });
            assertPublicPromptScope(updated as WorkspacePrompt, workspaceId, prompt.id);
            return updated as WorkspacePrompt;
        },
        remove: async (prompt) => {
            if (!allows('delete', prompt)) {
                throw new Error('Deleting this prompt is not available.');
            }
            await conditionalGroupWrite('DELETE', publicPromptsUrl(workspaceId, prompt.id), {
                expected_etag: requiredEtag(prompt),
            });
        },
    };
}
