// workspaceAuthoringApi.ts

import { api } from './apiClient';
import { generateAgentId } from './workspaceApi';
import {
    buildEditorWrite,
    isRecord,
    type ActionConfiguration,
    type ActionTypeDefinition,
    type AgentConfiguration,
    type AgentEditorOptions,
    type AuthoringResource,
} from './workspaceAuthoring';

const agentRoot = '/api/user/agents';
const actionRoot = '/api/user/plugins';

function editorUrl(root: string, id?: string, scope = 'personal'): string {
    const query = new URLSearchParams({ view: 'editor' });
    if (scope === 'global') query.set('scope', 'global');
    return `${root}${id ? `/${encodeURIComponent(id)}` : ''}?${query}`;
}

async function collection<T>(path: string, signal?: AbortSignal): Promise<T[]> {
    const response = await api.get<T[]>(path, signal);
    if (!Array.isArray(response) || !response.every(isRecord)) throw new Error('The workspace returned an invalid resource list.');
    return response;
}

async function editorResource<T extends AgentConfiguration | ActionConfiguration>(
    request: Promise<AuthoringResource<T>>,
): Promise<AuthoringResource<T>> {
    const response = await request;
    if (!isRecord(response) || !isRecord(response.record) ||
        typeof response.read_only !== 'boolean' ||
        (response.revision != null && typeof response.revision !== 'string') ||
        (!response.read_only && (!response.revision || typeof response.record.id !== 'string' || !response.record.id)) ||
        !Array.isArray(response.secret_paths) ||
        !response.secret_paths.every((path) => typeof path === 'string' && path.startsWith('/'))) {
        throw new Error('The workspace returned an invalid editor resource. Reload before trying again.');
    }
    return { ...response, revision: response.revision ?? '' };
}

export const fetchAuthoringAgents = (signal?: AbortSignal) =>
    collection<AgentConfiguration>(editorUrl(agentRoot), signal);

export const fetchAuthoringActions = (signal?: AbortSignal) =>
    collection<ActionConfiguration>(editorUrl(actionRoot), signal);

export const fetchAgentEditor = (id: string, scope = 'personal', signal?: AbortSignal) =>
    editorResource(api.get<AuthoringResource<AgentConfiguration>>(editorUrl(agentRoot, id, scope), signal));

export const fetchActionEditor = (id: string, scope = 'personal', signal?: AbortSignal) =>
    editorResource(api.get<AuthoringResource<ActionConfiguration>>(editorUrl(actionRoot, id, scope), signal));

export const fetchAgentEditorOptions = (signal?: AbortSignal) =>
    api.get<AgentEditorOptions>('/api/user/agent/settings?view=editor', signal);

export const fetchActionTypes = (signal?: AbortSignal) =>
    collection<ActionTypeDefinition>('/api/user/plugins/types?view=editor', signal);

export async function saveAgentConfiguration(
    draft: AgentConfiguration,
    original: AuthoringResource<AgentConfiguration> | null,
): Promise<AuthoringResource<AgentConfiguration>> {
    if (original?.read_only) throw new Error('Provided agents are read-only.');
    const record = original ? draft : { ...draft, id: await generateAgentId() };
    if (!record.id) throw new Error('Could not allocate an agent identifier. Try again.');
    const write = buildEditorWrite(record, original);
    return editorResource(original
        ? api.patch<AuthoringResource<AgentConfiguration>>(editorUrl(agentRoot, original.record.id), write)
        : api.post<AuthoringResource<AgentConfiguration>>(editorUrl(agentRoot), write));
}

export function saveActionConfiguration(
    draft: ActionConfiguration,
    original: AuthoringResource<ActionConfiguration> | null,
): Promise<AuthoringResource<ActionConfiguration>> {
    if (original?.read_only) throw new Error('Provided actions are read-only.');
    const write = buildEditorWrite(draft, original);
    if (!original) delete write.updates.id;
    return editorResource(original
        ? api.patch<AuthoringResource<ActionConfiguration>>(editorUrl(actionRoot, original.record.id), write)
        : api.post<AuthoringResource<ActionConfiguration>>(editorUrl(actionRoot), write));
}

export const deleteAuthoringAgent = (id: string) => api.delete<{ success: boolean }>(editorUrl(agentRoot, id));
export const deleteAuthoringAction = (id: string) => api.delete<{ success: boolean }>(editorUrl(actionRoot, id));
