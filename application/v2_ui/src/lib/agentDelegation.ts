// agentDelegation.ts
// Scoped Call agent resources; binding writes never replace an agent configuration.

import { api, ApiError } from './apiClient';
import type { WorkspaceAction, WorkspaceAgent } from './types';

export type AgentScopeType = 'personal' | 'group' | 'global';
export type DelegationScope =
    | { type: 'personal' }
    | { type: 'group'; groupId: string }
    | { type: 'global' };

export interface AgentReference {
    id: string;
    scope_type: AgentScopeType;
    scope_id: string;
}

export interface AgentTarget extends AgentReference {
    name: string;
    display_name?: string;
    description?: string;
    agent_type: string;
}

export interface AgentTargetCatalog {
    targets: AgentTarget[];
    can_manage: boolean;
    scope_type: AgentScopeType;
    scope_id: string;
}

export interface CallAgentWrite {
    id?: string;
    name: string;
    displayName: string;
    description: string;
    type: 'agent';
    endpoint: 'internal://agent';
    auth: { type: 'user' };
    metadata: Record<string, unknown>;
    is_enabled: boolean;
    additionalFields: { target_agent: AgentReference };
}

export const PERSONAL_DELEGATION_SCOPE: DelegationScope = { type: 'personal' };
export const GLOBAL_DELEGATION_SCOPE: DelegationScope = { type: 'global' };

export function referenceKey(reference: AgentReference): string {
    return JSON.stringify([reference.scope_type, reference.scope_id, reference.id]);
}

export function actionTarget(action: WorkspaceAction): AgentReference | null {
    const fields = action.additionalFields;
    if (!fields || typeof fields !== 'object' || !('target_agent' in fields)) {
        return null;
    }
    const value = fields.target_agent;
    if (!value || typeof value !== 'object' ||
        !('id' in value) || typeof value.id !== 'string' ||
        !('scope_id' in value) || typeof value.scope_id !== 'string' ||
        !('scope_type' in value) ||
        !['personal', 'group', 'global'].includes(String(value.scope_type))) {
        return null;
    }
    return {
        id: value.id,
        scope_id: value.scope_id,
        scope_type: value.scope_type as AgentScopeType,
    };
}

export function isOwnedResource(
    resource: WorkspaceAgent | WorkspaceAction,
    scope: DelegationScope,
): boolean {
    if (scope.type === 'global') {
        return !resource.is_group;
    }
    if (resource.is_global) {
        return false;
    }
    return scope.type === 'group'
        ? !resource.group_id || resource.group_id === scope.groupId
        : !resource.is_group && !resource.group_id;
}

export function delegationResourceUrl(
    scope: DelegationScope,
    resource: 'agents' | 'plugins',
    suffix = '',
): string {
    const owner = scope.type === 'personal' ? 'user' : scope.type === 'global' ? 'admin' : 'group';
    const query = scope.type === 'group'
        ? `?${new URLSearchParams({ group_id: scope.groupId })}`
        : '';
    return `/api/${owner}/${resource}${suffix}${query}`;
}

export async function fetchAgentTargets(scope: DelegationScope, signal?: AbortSignal) {
    const query = new URLSearchParams({ scope: scope.type });
    if (scope.type === 'group') {
        query.set('group_id', scope.groupId);
    }
    return api.get<AgentTargetCatalog>(`/api/plugins/agent-targets?${query}`, signal);
}

export async function fetchDelegationActions(scope: DelegationScope, signal?: AbortSignal) {
    const response = await api.get<WorkspaceAction[] | { actions: WorkspaceAction[] }>(
        delegationResourceUrl(scope, 'plugins'), signal,
    );
    const actions = Array.isArray(response) ? response : response.actions;
    return actions.filter((action) => action.type === 'agent');
}

export async function fetchDelegationAgents(scope: DelegationScope, signal?: AbortSignal) {
    const response = await api.get<WorkspaceAgent[] | { agents: WorkspaceAgent[] }>(
        delegationResourceUrl(scope, 'agents'), signal,
    );
    return Array.isArray(response) ? response : response.agents;
}

export function saveCallAgentAction(
    scope: DelegationScope,
    payload: CallAgentWrite,
    original?: WorkspaceAction,
) {
    if (!original) {
        return api.post(delegationResourceUrl(scope, 'plugins'), payload);
    }
    if (!original.id || (scope.type === 'global' && !original.name)) {
        throw new Error('This action has no stable identifier. Reload before editing.');
    }
    const identifier = scope.type === 'global' ? original.name! : original.id;
    const url = delegationResourceUrl(scope, 'plugins', `/${encodeURIComponent(identifier)}`);
    const update = { ...payload, id: original.id };
    return scope.type === 'global' ? api.put(url, update) : api.patch(url, update);
}

export function saveAgentActionBindings(
    scope: DelegationScope,
    agent: WorkspaceAgent,
    actionIds: string[],
) {
    return api.patch(
        delegationResourceUrl(scope, 'agents', `/${encodeURIComponent(agent.id)}/agent-actions`),
        {
            action_ids: actionIds,
            expected_actions_to_load: agent.actions_to_load ?? [],
        },
    );
}

export function deleteCallAgentAction(scope: DelegationScope, action: WorkspaceAction) {
    const identifier = scope.type === 'global' ? action.name : action.id;
    if (!identifier || action.type !== 'agent' || !isOwnedResource(action, scope)) {
        throw new Error('This Call agent action cannot be deleted from this workspace.');
    }
    return api.delete(delegationResourceUrl(scope, 'plugins', `/${encodeURIComponent(identifier)}`));
}

export function delegationError(error: unknown): string {
    if (error instanceof ApiError) {
        if (error.status === 409) {
            return 'This configuration changed in another session. Reload and review the latest bindings before saving again.';
        }
        if (error.status === 401 || error.status === 403) {
            return 'Access denied. Your permissions or this workspace’s available features may have changed.';
        }
    }
    return error instanceof Error ? error.message : 'Unable to load or save Call agent configuration.';
}
