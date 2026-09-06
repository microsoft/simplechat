// workspaceAgentCommands.ts

import { api } from './apiClient';
import type { WorkspaceModelEndpoint } from './types';
import type { ActionConfiguration, AgentConfiguration, WorkspaceAgentType } from './workspaceAuthoring';
import { agentSelectedActionsContext } from './workspaceAgentActions';
import { agentText, foundryEndpointMatches, type FoundryDiscoveryRecord } from './workspaceAgentAuthoring';
import { agentKnowledgeReference, type AgentKnowledgeCatalog } from './workspaceAgentKnowledge';

export function agentInstructionRequest(
    draft: AgentConfiguration, actions: ActionConfiguration[], catalog: AgentKnowledgeCatalog | null,
) {
    return {
        agent_scope: 'user',
        display_name: draft.display_name,
        description: draft.description,
        brief: agentText(draft._editor_instruction_brief),
        existing_instructions: draft.instructions,
        selected_actions: agentSelectedActionsContext(draft, actions),
        assigned_knowledge: agentKnowledgeReference(draft, catalog),
    };
}

export async function draftAgentInstructions(
    draft: AgentConfiguration, actions: ActionConfiguration[], catalog: AgentKnowledgeCatalog | null, signal?: AbortSignal,
): Promise<string> {
    if (draft.agent_type !== 'local') throw new Error('Foundry manages its own instructions.');
    const result = await api.post<{ success: boolean; instructions: string }>(
        '/api/agents/draft-instructions', agentInstructionRequest(draft, actions, catalog), signal,
    );
    if (!result.success || typeof result.instructions !== 'string' || !result.instructions.trim()) {
        throw new Error('Instruction drafting returned no instructions.');
    }
    return result.instructions;
}

export function withAgentInstructionProposal(current: AgentConfiguration, instructions: string, baseline: string): AgentConfiguration {
    return { ...current, _editor_instruction_proposal: instructions, _editor_instruction_baseline: baseline };
}

export async function discoverAgentFoundryResources(
    endpoint: WorkspaceModelEndpoint, type: WorkspaceAgentType, signal?: AbortSignal,
) {
    if (type === 'local' || !foundryEndpointMatches(type, endpoint)) throw new Error('Select an available Foundry connection for this agent type.');
    const result = await api.post<{ agents: FoundryDiscoveryRecord[]; responses_api_version?: string }>(
        '/api/models/foundry/agents', {
            endpoint_id: endpoint.id,
            scope: agentText(endpoint.scope) || 'global',
            resource_type: type === 'foundry_workflow' ? 'workflow' : '',
        }, signal,
    );
    if (!Array.isArray(result.agents)) throw new Error('Foundry discovery returned an invalid resource list.');
    return result;
}
