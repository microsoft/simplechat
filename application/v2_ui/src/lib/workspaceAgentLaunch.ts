// workspaceAgentLaunch.ts
// Reading a "Use in chat" link and resolving it to exactly one agent in the chat catalogue.
//
// Agent ids are unique only within their scope, and one user can belong to several groups, so a
// launch always resolves by id *and* scope, and a group launch also by the group it names
// (`agent_scope_id`). The chat catalogue already lists agents from every group the user belongs to
// and the chat request carries the agent's own `group_id`, so resolving the right catalogue record
// here is what keeps a group agent from running in whichever group the account last selected.

import {
    AGENT_SCOPE_ID_PARAM, AGENT_SCOPE_PARAM, NEW_CHAT_PARAM, readConversationParam, WORKSPACE_AGENT_PARAM,
} from './conversationUrl';
import type { AgentOption, WorkspaceRef } from './types';

export type WorkspaceAgentLaunch =
    | { id: string; scope: 'personal' | 'global' }
    | { id: string; scope: 'group'; groupId: string };

const UNSAFE_IDENTIFIER = /[/\\\u0000-\u001f\u007f]/;

function launchIdentifier(value: string | null): string {
    const text = value?.trim() ?? '';
    return text && !UNSAFE_IDENTIFIER.test(text) ? text : '';
}

export function readWorkspaceAgentLaunch(params: URLSearchParams): WorkspaceAgentLaunch | null {
    if (readConversationParam(params) || params.get(NEW_CHAT_PARAM) !== '1') return null;
    const id = launchIdentifier(params.get(WORKSPACE_AGENT_PARAM));
    const scope = params.get(AGENT_SCOPE_PARAM) ?? 'personal';
    if (!id) return null;
    if (scope === 'group') {
        const groupId = launchIdentifier(params.get(AGENT_SCOPE_ID_PARAM));
        return groupId ? { id, scope: 'group', groupId } : null;
    }
    // A group id on a personal or provided link names nothing it could apply to, so the link is
    // ambiguous rather than something to guess at.
    if (params.has(AGENT_SCOPE_ID_PARAM) || !['personal', 'global'].includes(scope)) return null;
    return { id, scope: scope === 'global' ? 'global' : 'personal' };
}

function agentGroupId(agent: AgentOption): string {
    const value = agent.group_id ?? agent.scope_id;
    return typeof value === 'string' ? value : '';
}

/** The URL is a request, not authorization and never a reason to match an agent by name. */
export function workspaceAgentForLaunch(
    agents: AgentOption[] | undefined,
    launch: WorkspaceAgentLaunch,
): AgentOption | undefined {
    return agents?.find((agent) => {
        const scope = agent.scope_type || (agent.is_group ? 'group' : agent.is_global ? 'global' : 'personal');
        if (agent.id !== launch.id || scope !== launch.scope || agent.is_enabled === false) return false;
        return launch.scope !== 'group' || agentGroupId(agent) === launch.groupId;
    });
}

/**
 * Why a launch found no agent.
 *
 * A group link names its group, as a stale group prompt link does, so a member who lost access
 * or a deleted agent reads as "not in Research" rather than "some agent, somewhere, is gone".
 */
export function workspaceAgentLaunchUnavailableMessage(
    launch: WorkspaceAgentLaunch,
    groups: WorkspaceRef[] | undefined,
    agents: AgentOption[] | undefined,
): string {
    if (launch.scope !== 'group') return 'That agent is no longer available in this workspace.';
    const listed = groups?.find((group) => group.id === launch.groupId)?.name;
    const catalogued = agents?.find((agent) => agentGroupId(agent) === launch.groupId
        && typeof agent.group_name === 'string' && agent.group_name)?.group_name;
    const name = listed || (typeof catalogued === 'string' ? catalogued : '');
    return `That agent is no longer available in ${name || 'that group'}.`;
}
