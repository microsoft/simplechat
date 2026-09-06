// workspaceAgentLaunch.ts

import {
    AGENT_SCOPE_PARAM, NEW_CHAT_PARAM, readConversationParam, WORKSPACE_AGENT_PARAM,
} from './conversationUrl';
import type { AgentOption } from './types';

export interface WorkspaceAgentLaunch {
    id: string;
    scope: 'personal' | 'global';
}

export function readWorkspaceAgentLaunch(params: URLSearchParams): WorkspaceAgentLaunch | null {
    if (readConversationParam(params) || params.get(NEW_CHAT_PARAM) !== '1') return null;
    const id = params.get(WORKSPACE_AGENT_PARAM)?.trim() ?? '';
    const scope = params.get(AGENT_SCOPE_PARAM) ?? 'personal';
    if (!id || /[/\\\u0000-\u001f\u007f]/.test(id) || !['personal', 'global'].includes(scope)) return null;
    return { id, scope: scope === 'global' ? 'global' : 'personal' };
}

/** The URL is a request, not authorization and never a reason to match an agent by name. */
export function workspaceAgentForLaunch(
    agents: AgentOption[] | undefined,
    launch: WorkspaceAgentLaunch,
): AgentOption | undefined {
    return agents?.find((agent) => {
        const scope = agent.scope_type || (agent.is_group ? 'group' : agent.is_global ? 'global' : 'personal');
        return agent.id === launch.id && scope === launch.scope && agent.is_enabled !== false;
    });
}
