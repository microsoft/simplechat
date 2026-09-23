// agentWorkbench.ts
// Scope-aware agent reads, writes and side resources for the agents collection and editor.
//
// The agents surface shipped personal-only: AgentsSection and AgentEditorPage called the
// /api/user/agents functions in workspaceAuthoringApi.ts and the personal knowledge, options,
// drafting and delegation helpers directly. This module is the seam that lets the same components
// serve a group workspace without forking them, exactly as actionWorkbench.ts did for actions. An
// AgentWorkbenchScope selects which URLs are used, which draft-cache partition drafts live in,
// which knowledge scopes may be assigned, which delegation targets are offered, whether drafting
// speaks for the group, and which per-operation gates apply. The personal adapter is a thin
// pass-through so its behaviour stays byte-identical in effect: same URLs, same catalogues, same
// flows -- it holds no /api/user URL of its own and delegates entirely to the unchanged functions.
//
// The group path never falls back to personal behaviour, and never reads a personal route. An
// absent or unrecognised agent_management hint yields an empty operation set, which leaves every
// write gate refusing -- a missing server hint must not become a silent authorization bypass on
// the client. Editing and deleting a specific agent additionally require the agent to belong to
// this group and to carry the operation in its own agent_actions, exactly as the group action gate
// does. Every side resource -- options, assigned knowledge, delegation targets, instruction
// drafting, action candidates -- resolves to a group-scoped route so a group agent page issues no
// personal-scope read.

import { api } from './apiClient';
import { generateAgentId } from './workspaceApi';
import {
    buildEditorWrite, isRecord,
    type ActionConfiguration, type AgentConfiguration, type AgentEditorOptions, type AuthoringResource,
} from './workspaceAuthoring';
import {
    deleteAuthoringAgent, fetchAgentEditor, fetchAgentEditorOptions, fetchAuthoringActions,
    fetchAuthoringAgents, saveAgentConfiguration,
} from './workspaceAuthoringApi';
import {
    fetchAgentKnowledgeCatalog, fetchGroupAgentKnowledgeCatalog, type AgentKnowledgeCatalog,
} from './workspaceAgentKnowledge';
import {
    draftAgentInstructions, PERSONAL_INSTRUCTION_SCOPE, type InstructionDraftScope,
} from './workspaceAgentCommands';
import {
    fetchAgentTargets, PERSONAL_DELEGATION_SCOPE, type AgentTargetCatalog, type DelegationScope,
} from './agentDelegation';
import type { AgentLinkScope } from './conversationUrl';
import type { EditorWorkspaceScope } from './workspaceEditorDrafts';
import type { ActionWorkbenchAdapter } from './actionWorkbench';
import { requireWorkspaceId, workspaceBasePath } from './workspaceContext';

export type AgentWorkbenchScope =
    | { kind: 'personal' }
    | { kind: 'group'; id: string; name: string };

export const AGENT_OPERATIONS = ['create', 'edit', 'delete'] as const;
export type AgentOperation = typeof AGENT_OPERATIONS[number];

export interface AgentWorkbenchAdapter {
    scope: AgentWorkbenchScope;
    /** The SPA route the collection and editor live under, e.g. '/workspace/agents'. */
    basePath: string;
    /** Draft-cache partition, so a group A draft never restores into group B or personal. */
    draftScope: EditorWorkspaceScope;
    /** Knowledge scopes a source picker may assign in this workspace; never includes 'personal' in a group. */
    knowledgeScopes: readonly string[];
    /** Whom instruction drafting speaks for; a group scope drafts against the group's own resources. */
    instructionScope: InstructionDraftScope;
    /** The delegation catalogue scope; group pages never read the personal target catalogue. */
    delegationScope: DelegationScope;
    /** Where the agent editor's "New action" hands off; the matching action editor family. */
    actionsBasePath: string;
    /** Whether "New action" is offered. Personal reads this from bootstrap; group precomputes it here. */
    canCreateActions: boolean;
    supported: ReadonlySet<AgentOperation>;
    allows: (operation: AgentOperation, agent?: AgentConfiguration) => boolean;
    /** Whether this agent may be launched into chat: a per-agent server hint in group scope. */
    canUseInChat: (agent: AgentConfiguration) => boolean;
    /** The scope a use-in-chat link names, so a group agent opens in its own group. */
    chatScope: (agent: AgentConfiguration) => AgentLinkScope;
    /** Whether custom model endpoints may be configured, from this scope's own settings flag. */
    allowsCustomEndpoints: (settings: Record<string, unknown>) => boolean;
    /**
     * Whether the caller may submit an agent template in this scope. Personal reads the classic
     * per-user submission flag; group reads the server-computed `agent_template_submission_allowed`,
     * always present on group options, so a mislabelled button never renders and always 403s.
     */
    allowsTemplateSubmission: (settings: Record<string, unknown>) => boolean;
    listAgents: (signal?: AbortSignal) => Promise<AgentConfiguration[]>;
    fetchOptions: (signal?: AbortSignal) => Promise<AgentEditorOptions>;
    fetchEditor: (id: string, providedScope: string, signal?: AbortSignal) => Promise<AuthoringResource<AgentConfiguration>>;
    save: (draft: AgentConfiguration, original: AuthoringResource<AgentConfiguration> | null) => Promise<AuthoringResource<AgentConfiguration>>;
    deleteAgent: (agent: AgentConfiguration) => Promise<void>;
    /** The actions offered for actions_to_load. Group scope offers the group's merged action list. */
    fetchActions: (signal?: AbortSignal) => Promise<ActionConfiguration[]>;
    fetchTargets: (signal?: AbortSignal) => Promise<AgentTargetCatalog>;
    fetchKnowledge: (signal?: AbortSignal) => Promise<AgentKnowledgeCatalog>;
    draftInstructions: (
        draft: AgentConfiguration, actions: ActionConfiguration[], catalog: AgentKnowledgeCatalog | null, signal?: AbortSignal,
    ) => Promise<string>;
}

/**
 * The operations an `agent_management` hint offers.
 *
 * Mirrors `advertisedActionOperations`: an unrecognised block (missing, wrong schema, or a
 * non-string entry) yields the empty set rather than a guess, so a malformed hint disables writing
 * rather than enabling it.
 */
export function advertisedAgentOperations(value: unknown): ReadonlySet<AgentOperation> {
    if (!isRecord(value) || value.schema_version !== 1 || !Array.isArray(value.operations)
        || !value.operations.every((operation) => typeof operation === 'string')) {
        return new Set();
    }
    const offered = value.operations;
    return new Set(AGENT_OPERATIONS.filter((operation) => offered.includes(operation)));
}

/**
 * Whether an operation is allowed in a scope.
 *
 * Personal scope allows everything, exactly as the section did before it was scoped. Group scope
 * requires the workspace-level `agent_management` hint to offer the operation, and edit and delete
 * additionally require the specific agent to belong to this group and to carry the operation in its
 * own `agent_actions`. Create is workspace-level with no per-agent subject. There is deliberately no
 * fallback that enables an agent when the hint is empty or absent.
 */
export function agentOperationAllowed(
    scope: AgentWorkbenchScope,
    supported: ReadonlySet<AgentOperation>,
    operation: AgentOperation,
    agent?: AgentConfiguration,
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
    if (!agent || agent.group_id !== scope.id) {
        return false;
    }
    return Array.isArray(agent.agent_actions) && agent.agent_actions.includes(operation);
}

export const PERSONAL_AGENT_WORKBENCH: AgentWorkbenchAdapter = {
    scope: { kind: 'personal' },
    basePath: '/workspace/agents',
    draftScope: { kind: 'personal' },
    knowledgeScopes: ['personal', 'public'],
    instructionScope: PERSONAL_INSTRUCTION_SCOPE,
    delegationScope: PERSONAL_DELEGATION_SCOPE,
    actionsBasePath: '/workspace/actions',
    // Personal action-creation eligibility comes from the bootstrap store in the editor; this
    // value is unused in personal scope and never gates the group editor.
    canCreateActions: false,
    supported: new Set(AGENT_OPERATIONS),
    allows: () => true,
    canUseInChat: (agent) => agent.is_enabled !== false,
    chatScope: (agent) => ({ kind: agent.is_global ? 'global' : 'personal' }),
    allowsCustomEndpoints: (settings) => settings.allow_user_custom_endpoints === true,
    allowsTemplateSubmission: (settings) => settings.agent_templates_allow_user_submission !== false,
    listAgents: (signal) => fetchAuthoringAgents(signal),
    fetchOptions: (signal) => fetchAgentEditorOptions(signal),
    fetchEditor: (id, providedScope, signal) => fetchAgentEditor(id, providedScope, signal),
    save: (draft, original) => saveAgentConfiguration(draft, original),
    deleteAgent: async (agent) => {
        await deleteAuthoringAgent(agent.id);
    },
    fetchActions: (signal) => fetchAuthoringActions(signal),
    fetchTargets: (signal) => fetchAgentTargets(PERSONAL_DELEGATION_SCOPE, signal),
    fetchKnowledge: (signal) => fetchAgentKnowledgeCatalog(signal),
    draftInstructions: (draft, actions, catalog, signal) => draftAgentInstructions(draft, actions, catalog, signal),
};

function groupAgentsUrl(groupId: string, agentId?: string): string {
    const base = `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/agents`;
    return agentId ? `${base}/${encodeURIComponent(requireWorkspaceId(agentId))}` : base;
}

/**
 * Prove a returned agent belongs to the requested group, as the group action reader does. A
 * provided global agent merged in read-only is accepted; anything scoped to another group or to a
 * person is refused rather than rendered.
 */
function assertGroupAgentScope(agent: AgentConfiguration, groupId: string, id?: string): void {
    if (!agent || typeof agent.id !== 'string' || !agent.id
        || (id !== undefined && agent.id !== id)
        || !(agent.is_global === true || agent.group_id === groupId)) {
        throw new Error('The agent response does not match this group. Refresh and try again.');
    }
}

/** The editor contract, validated the same way workspaceAuthoringApi validates the personal one. */
function assertGroupAgentEditorResource(
    response: AuthoringResource<AgentConfiguration>, groupId: string, id?: string,
): AuthoringResource<AgentConfiguration> {
    if (!isRecord(response) || !isRecord(response.record)
        || typeof response.read_only !== 'boolean'
        || (response.revision != null && typeof response.revision !== 'string')
        || (!response.read_only && (!response.revision || typeof response.record.id !== 'string' || !response.record.id))
        || !Array.isArray(response.secret_paths)
        || !response.secret_paths.every((path) => typeof path === 'string' && path.startsWith('/'))) {
        throw new Error('The workspace returned an invalid editor resource. Reload before trying again.');
    }
    assertGroupAgentScope(response.record, groupId, id);
    return { ...response, revision: response.revision ?? '' };
}

function agentsFromResponse(value: unknown): AgentConfiguration[] {
    if (!isRecord(value) || !Array.isArray(value.agents) || !value.agents.every(isRecord)) {
        throw new Error('The workspace returned an invalid agent list. Reload before trying again.');
    }
    return value.agents as AgentConfiguration[];
}

function assertGroupAgentOptions(value: unknown): AgentEditorOptions {
    if (!isRecord(value) || !Array.isArray(value.agent_types) || !Array.isArray(value.model_endpoints)
        || !Array.isArray(value.builtin_actions) || !isRecord(value.settings)) {
        throw new Error('The agent editor options returned an invalid response.');
    }
    return value as unknown as AgentEditorOptions;
}

/**
 * `agent_actions` is a read-only projection the server never accepts back: the agent schema does
 * not list it and it is not a managed field. Echoing it in `updates` or `removed_paths` is a 400. A
 * fresh read carries it, so a restored draft whose value differs from the original would otherwise
 * emit it. Strip it from both sides of the diff so buildEditorWrite emits neither an update nor a
 * removed path for it.
 */
function withoutAgentProjectionFields<T extends AgentConfiguration>(record: T): T {
    if (!isRecord(record) || !('agent_actions' in record)) {
        return record;
    }
    const clone = { ...(record as Record<string, unknown>) };
    delete clone.agent_actions;
    return clone as T;
}

export function createGroupAgentWorkbench(
    scope: Extract<AgentWorkbenchScope, { kind: 'group' }>,
    management: unknown,
    actionAdapter: ActionWorkbenchAdapter | null,
): AgentWorkbenchAdapter {
    if (scope.kind !== 'group') {
        throw new Error('Group agents require an explicit group scope.');
    }
    const groupId = requireWorkspaceId(scope.id);
    const supported = advertisedAgentOperations(management);
    const instructionScope: InstructionDraftScope = { agentScope: 'group', groupId };
    const delegationScope: DelegationScope = { type: 'group', groupId };
    const allows = (operation: AgentOperation, agent?: AgentConfiguration) =>
        agentOperationAllowed(scope, supported, operation, agent);
    return {
        scope,
        basePath: `${workspaceBasePath(scope)}/agents`,
        draftScope: { kind: 'group', id: groupId },
        knowledgeScopes: ['group', 'public'],
        instructionScope,
        delegationScope,
        // A group agent's actions_to_load candidates and its "New action" handoff both use the
        // group action editor family. When group actions are unavailable the agent editor keeps the
        // candidates route dark and offers no creation, never falling back to a personal action.
        actionsBasePath: actionAdapter ? actionAdapter.basePath : `${workspaceBasePath(scope)}/actions`,
        canCreateActions: actionAdapter ? actionAdapter.allows('create') : false,
        supported,
        allows,
        canUseInChat: (agent) => Array.isArray(agent.agent_actions) && agent.agent_actions.includes('chat'),
        chatScope: () => ({ kind: 'group', id: groupId }),
        allowsCustomEndpoints: (settings) => settings.allow_group_custom_endpoints === true,
        allowsTemplateSubmission: (settings) => settings.agent_template_submission_allowed === true,
        listAgents: async (signal) => {
            const response = await api.get<unknown>(groupAgentsUrl(groupId), signal);
            const agents = agentsFromResponse(response);
            agents.forEach((agent) => assertGroupAgentScope(agent, groupId));
            return agents;
        },
        fetchOptions: async (signal) => assertGroupAgentOptions(
            await api.get<unknown>(`/api/groups/${encodeURIComponent(groupId)}/agent-options`, signal),
        ),
        fetchEditor: async (id, _providedScope, signal) => {
            const response = await api.get<AuthoringResource<AgentConfiguration>>(groupAgentsUrl(groupId, id), signal);
            return assertGroupAgentEditorResource(response, groupId, id);
        },
        save: async (draft, original) => {
            if (!allows(original ? 'edit' : 'create', original?.record ?? draft)) {
                throw new Error(original ? 'Editing this agent is not available.' : 'Creating agents is not available in this group.');
            }
            if (original?.read_only) throw new Error('Provided agents are read-only.');
            const record = original ? draft : { ...draft, id: await generateAgentId() };
            if (!record.id) throw new Error('Could not allocate an agent identifier. Try again.');
            const write = buildEditorWrite(
                withoutAgentProjectionFields(record),
                original ? { ...original, record: withoutAgentProjectionFields(original.record) } : null,
            );
            const response = original
                ? await api.patch<AuthoringResource<AgentConfiguration>>(groupAgentsUrl(groupId, original.record.id), write)
                : await api.post<AuthoringResource<AgentConfiguration>>(groupAgentsUrl(groupId), write);
            return assertGroupAgentEditorResource(response, groupId, original?.record.id);
        },
        deleteAgent: async (agent) => {
            if (!allows('delete', agent)) {
                throw new Error('Deleting this agent is not available.');
            }
            await api.delete<{ success: boolean }>(groupAgentsUrl(groupId, agent.id));
        },
        fetchActions: (signal) => (actionAdapter ? actionAdapter.listActions(signal) : Promise.resolve([])),
        fetchTargets: (signal) => fetchAgentTargets(delegationScope, signal),
        fetchKnowledge: (signal) => fetchGroupAgentKnowledgeCatalog(groupId, signal),
        draftInstructions: (draft, actions, catalog, signal) =>
            draftAgentInstructions(draft, actions, catalog, signal, instructionScope),
    };
}
