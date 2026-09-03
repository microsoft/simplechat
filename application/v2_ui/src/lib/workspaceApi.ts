// workspaceApi.ts
// Every call the personal workspace sections make.
//
// The routes behind these sections grew independently and do not share a response shape:
// prompts, identities, sync sources and workflows wrap their collection in a named key,
// while agents and actions return a bare array. Rather than make each section deal with
// that, the differences are absorbed here and every function returns a plain array or a
// plain entity.
//
// Per-item writes are used throughout. Agents, actions and endpoints also accept a
// whole-collection POST, but that form requires the client to send back rows it never
// edited, so a stale tab silently reverts another one's work. Nothing here uses it.

import { api } from './apiClient';
import type {
    WorkspaceAction,
    WorkspaceAgent,
    WorkspaceIdentity,
    WorkspaceModelEndpoint,
    WorkspacePrompt,
    WorkspaceSyncRun,
    WorkspaceSyncSource,
    WorkspaceWorkflow,
    WorkspaceWorkflowRun,
} from './types';

/** Coerce a response that should be a list into one, whatever shape it arrived in. */
function asArray<T>(value: unknown, key?: string): T[] {
    if (Array.isArray(value)) {
        return value as T[];
    }
    if (key && value && typeof value === 'object') {
        const nested = (value as Record<string, unknown>)[key];
        if (Array.isArray(nested)) {
            return nested as T[];
        }
    }
    return [];
}

/* -------------------------------------------------------------------------- Prompts */

export interface PromptWrite {
    name?: string;
    content?: string;
    description?: string;
    is_favorite?: boolean;
}

/**
 * List personal prompts.
 *
 * Paging and search are server-side. The default page size is large because the section
 * renders a single scrolling list rather than paged controls.
 *
 * The search parameter is `search`, which is what `list_prompts` reads. It was `search_term`
 * here, a name the route has never looked for, so server-side search silently did nothing.
 */
export async function fetchPrompts(
    { search = '', pageSize = 500 }: { search?: string; pageSize?: number } = {},
    signal?: AbortSignal,
): Promise<WorkspacePrompt[]> {
    const params = new URLSearchParams({ page: '1', page_size: String(pageSize) });
    if (search.trim()) {
        params.set('search', search.trim());
    }
    const response = await api.get<unknown>(`/api/prompts?${params.toString()}`, signal);
    return asArray<WorkspacePrompt>(response, 'prompts');
}

export const fetchPrompt = (promptId: string, signal?: AbortSignal) =>
    api.get<WorkspacePrompt>(`/api/prompts/${encodeURIComponent(promptId)}`, signal);

export const createPrompt = (name: string, content: string, extra: PromptWrite = {}) =>
    api.post<WorkspacePrompt>('/api/prompts', { ...extra, name, content });

export const updatePrompt = (promptId: string, updates: PromptWrite) =>
    api.patch<WorkspacePrompt>(`/api/prompts/${encodeURIComponent(promptId)}`, updates);

export const deletePrompt = (promptId: string) =>
    api.delete<{ message?: string }>(`/api/prompts/${encodeURIComponent(promptId)}`);

/* ----------------------------------------------------------------------- Identities */

export async function fetchIdentities(signal?: AbortSignal): Promise<WorkspaceIdentity[]> {
    const response = await api.get<unknown>(
        '/api/workspace-identities/personal/identities',
        signal,
    );
    return asArray<WorkspaceIdentity>(response, 'identities');
}

export const deleteIdentity = (identityId: string) =>
    api.delete<{ message?: string }>(
        `/api/workspace-identities/personal/identities/${encodeURIComponent(identityId)}`,
    );

/* --------------------------------------------------------------------- File sources */

export async function fetchSyncSources(signal?: AbortSignal): Promise<WorkspaceSyncSource[]> {
    const response = await api.get<unknown>('/api/file-sync/personal/sources', signal);
    return asArray<WorkspaceSyncSource>(response, 'sources');
}

export async function fetchSyncRuns(
    sourceId: string,
    signal?: AbortSignal,
): Promise<WorkspaceSyncRun[]> {
    const response = await api.get<unknown>(
        `/api/file-sync/personal/sources/${encodeURIComponent(sourceId)}/runs`,
        signal,
    );
    return asArray<WorkspaceSyncRun>(response, 'runs');
}

/** Queue a sync. The route answers 202 with the run it created, not a finished result. */
export const startSyncRun = (sourceId: string) =>
    api.post<{ run?: WorkspaceSyncRun }>(
        `/api/file-sync/personal/sources/${encodeURIComponent(sourceId)}/sync`,
    );

/**
 * Delete a sync source.
 *
 * `delete_associated_files` is read from the body, so it is sent explicitly rather than
 * left to the server's default: whether the documents a source produced also disappear is
 * too consequential to leave implicit.
 */
export const deleteSyncSource = (sourceId: string, deleteAssociatedFiles = false) =>
    api.delete<{ message?: string }>(
        `/api/file-sync/personal/sources/${encodeURIComponent(sourceId)}`,
        { delete_associated_files: deleteAssociatedFiles },
    );

/* --------------------------------------------------------------------------- Agents */

/**
 * Reserve an agent id.
 *
 * The agent schema requires a UUID on the way in -- validation runs before storage would
 * assign one -- so a new agent needs an id before it can be saved. It is taken from the
 * server rather than generated in the browser because `crypto.randomUUID` is only present
 * in a secure context, and this has to work wherever the app is served from.
 */
export async function generateAgentId(): Promise<string> {
    const response = await api.get<{ id?: string }>('/api/agents/generate_id');
    return String(response?.id ?? '');
}

export async function fetchAgents(signal?: AbortSignal): Promise<WorkspaceAgent[]> {
    const response = await api.get<unknown>('/api/user/agents', signal);
    return asArray<WorkspaceAgent>(response, 'agents');
}

export const fetchAgent = (agentId: string, signal?: AbortSignal) =>
    api.get<WorkspaceAgent>(`/api/user/agents/${encodeURIComponent(agentId)}`, signal);

export const createAgent = (agent: Partial<WorkspaceAgent>) =>
    api.post<WorkspaceAgent>('/api/user/agents', agent);

export const updateAgent = (agentId: string, updates: Partial<WorkspaceAgent>) =>
    api.patch<WorkspaceAgent>(`/api/user/agents/${encodeURIComponent(agentId)}`, updates);

export const deleteAgent = (agentId: string) =>
    api.delete<{ success?: boolean }>(`/api/user/agents/${encodeURIComponent(agentId)}`);

/* -------------------------------------------------------------------------- Actions */

export async function fetchActions(signal?: AbortSignal): Promise<WorkspaceAction[]> {
    const response = await api.get<unknown>('/api/user/plugins', signal);
    return asArray<WorkspaceAction>(response, 'plugins');
}

export const fetchAction = (actionId: string, signal?: AbortSignal) =>
    api.get<WorkspaceAction>(`/api/user/plugins/${encodeURIComponent(actionId)}`, signal);

export const deleteAction = (actionId: string) =>
    api.delete<{ success?: boolean }>(`/api/user/plugins/${encodeURIComponent(actionId)}`);

/* ------------------------------------------------------------------------ Workflows */

export async function fetchWorkflows(signal?: AbortSignal): Promise<WorkspaceWorkflow[]> {
    const response = await api.get<unknown>('/api/user/workflows', signal);
    return asArray<WorkspaceWorkflow>(response, 'workflows');
}

export async function fetchWorkflowRuns(
    workflowId: string,
    signal?: AbortSignal,
): Promise<WorkspaceWorkflowRun[]> {
    const response = await api.get<unknown>(
        `/api/user/workflows/${encodeURIComponent(workflowId)}/runs`,
        signal,
    );
    return asArray<WorkspaceWorkflowRun>(response, 'runs');
}

export const startWorkflowRun = (workflowId: string) =>
    api.post<WorkspaceWorkflowRun>(`/api/user/workflows/${encodeURIComponent(workflowId)}/run`);

export const cancelWorkflow = (workflowId: string) =>
    api.post<unknown>(`/api/user/workflows/${encodeURIComponent(workflowId)}/cancel`);

export const deleteWorkflow = (workflowId: string) =>
    api.delete<{ success?: boolean }>(`/api/user/workflows/${encodeURIComponent(workflowId)}`);

/* ------------------------------------------------------------------------ Endpoints */

export async function fetchModelEndpoints(
    signal?: AbortSignal,
): Promise<WorkspaceModelEndpoint[]> {
    const response = await api.get<unknown>('/api/user/model-endpoints', signal);
    return asArray<WorkspaceModelEndpoint>(response, 'endpoints');
}

/**
 * Update one endpoint.
 *
 * Sent as a partial update rather than the whole endpoint, because the values that come
 * back from the server have their secrets stripped. Posting that object back would blank
 * the stored key; a PATCH carrying only what changed cannot.
 */
export async function updateModelEndpoint(
    endpointId: string,
    updates: Partial<WorkspaceModelEndpoint>,
): Promise<WorkspaceModelEndpoint | null> {
    const response = await api.patch<{ endpoint?: WorkspaceModelEndpoint }>(
        `/api/user/model-endpoints/${encodeURIComponent(endpointId)}`,
        updates,
    );
    return response?.endpoint ?? null;
}

export const deleteModelEndpoint = (endpointId: string) =>
    api.delete<{ success?: boolean }>(
        `/api/user/model-endpoints/${encodeURIComponent(endpointId)}`,
    );
