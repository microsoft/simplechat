// sharedWorkspaceCounts.ts

import { createGroupDocumentReader, createPublicDocumentReader, type DocumentReadAdapter } from './documentReadAdapter';
import { createGroupActionWorkbench } from './actionWorkbench';
import { createGroupAgentWorkbench } from './agentWorkbench';
import { fetchDelegationActionCount } from './agentDelegation';
import { createGroupFileSourceWorkbench, createPublicFileSourceWorkbench } from './fileSourceWorkbench';
import { createGroupIdentityWorkbench, createPublicIdentityWorkbench } from './identityWorkbench';
import { createGroupMembershipClient, createPublicMembershipClient } from './groupMembership';
import { createGroupModelConnectionsAdapter } from './modelConnections';
import { fetchSharedPromptCount } from './promptWorkbench';
import { fetchScopedWorkflowCount } from './workflowEditor';
import type { GroupWorkspaceContext, PublicWorkspaceContext } from './workspaceContext';

export type SharedWorkspaceContext = GroupWorkspaceContext | PublicWorkspaceContext;
export type WorkspaceCountLoader = (signal: AbortSignal) => Promise<number>;
export type WorkspaceCountLoaders = Partial<Record<string, WorkspaceCountLoader>>;
export type WorkspaceCountResult = { count: number; failed: false } | { failed: true };

export function validWorkspaceCount(value: unknown): number {
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
        throw new Error('The workspace returned an invalid count.');
    }
    return value;
}

function documentCountLoaders(reader: DocumentReadAdapter): WorkspaceCountLoaders {
    return {
        documents: async (signal) => reader.queries.facets
            ? validWorkspaceCount((await reader.facets(signal)).total)
            : validWorkspaceCount((await reader.list({ page: 1, pageSize: 1 }, signal)).total_count),
        tags: async (signal) => (await reader.tags(signal)).tags?.length ?? 0,
    };
}

function isGroupContext(context: SharedWorkspaceContext): context is GroupWorkspaceContext {
    return context.scope.kind === 'group';
}

export function createSharedWorkspaceCountLoaders(context: SharedWorkspaceContext): WorkspaceCountLoaders {
    const { id } = context.scope;
    const name = context.workspace.name;
    const membersQuery = { page: 1, pageSize: 1, search: '', role: null };
    if (!isGroupContext(context)) {
        const scope = { kind: 'public' as const, id, name };
        return {
            ...documentCountLoaders(createPublicDocumentReader(id, name, context.document_queries)),
            prompts: (signal) => fetchSharedPromptCount(scope, signal),
            sync: async (signal) => (await createPublicFileSourceWorkbench(scope, context.file_source_management).list(signal)).length,
            identities: async (signal) => (await createPublicIdentityWorkbench(scope, context.identity_management).list(signal)).length,
            members: context.role === 'User' ? undefined
                : async (signal) => (await createPublicMembershipClient(id).list(membersQuery, signal)).totalCount,
        };
    }
    const scope = { kind: 'group' as const, id, name };
    return {
        ...documentCountLoaders(createGroupDocumentReader(id, name, context.document_queries)),
        prompts: (signal) => fetchSharedPromptCount(scope, signal),
        sync: async (signal) => (await createGroupFileSourceWorkbench(scope, context.file_source_management).list(signal)).length,
        identities: async (signal) => (await createGroupIdentityWorkbench(scope, context.identity_management).list(signal)).length,
        agents: async (signal) => (await createGroupAgentWorkbench(scope, context.agent_management, null).listAgents(signal)).length,
        actions: context.sections.actions.enabled
            ? async (signal) => (await createGroupActionWorkbench(scope, context.action_management).listActions(signal)).length
            : (signal) => fetchDelegationActionCount({ type: 'group', groupId: id }, signal),
        workflows: (signal) => fetchScopedWorkflowCount({ type: 'group', groupId: id }, signal),
        endpoints: async (signal) => (await createGroupModelConnectionsAdapter(scope, context.endpoint_management).list(signal)).endpoints.length,
        members: async (signal) => (await createGroupMembershipClient(id).list(membersQuery, signal)).totalCount,
    };
}

/** Independent results are published as they arrive; one failed service never hides the others. */
export async function loadWorkspaceCounts(
    loaders: WorkspaceCountLoaders,
    sectionIds: readonly string[],
    signal: AbortSignal,
    onResult: (id: string, result: WorkspaceCountResult) => void,
): Promise<void> {
    await Promise.all(sectionIds.map(async (id) => {
        const load = loaders[id];
        if (!load || signal.aborted) return;
        let result: WorkspaceCountResult;
        try {
            result = { count: validWorkspaceCount(await load(signal)), failed: false };
        } catch {
            result = { failed: true };
        }
        if (!signal.aborted) onResult(id, result);
    }));
}
