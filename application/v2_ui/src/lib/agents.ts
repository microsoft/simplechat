// agents.ts
// Identifying a selected agent, and shaping it the way the chat endpoint expects.
//
// The chat route reads the selection as an OBJECT under the key `agent_info`:
//
//     request_agent_info = data.get('agent_info') if isinstance(data.get('agent_info'), dict) else {}
//     (route_backend_chats.py)
//
// A string, or any other key name, is silently discarded — the request succeeds and the
// agent is simply never applied, which is indistinguishable from the picker not working.

import type { Json } from './types';

/** The seven fields the classic client sends, and the server resolves against. */
export interface AgentInfo {
    id: string | null;
    name: string;
    display_name: string;
    is_global: boolean;
    is_group: boolean;
    group_id: string | null;
    group_name: string | null;
}

type AgentRecord = Record<string, unknown>;

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * Stable key identifying an agent within the picker.
 *
 * Agent catalog records carry `id`; `name` is the fallback for a record without one, and is
 * what the server matches on when no id is supplied.
 */
export function agentSelectionKey(agent: AgentRecord | undefined): string {
    if (!agent) {
        return '';
    }
    return text(agent.id) || text(agent.name);
}

/** Find the catalog record a picker selection refers to. */
export function findAgent(
    agents: AgentRecord[] | undefined,
    selection: string | undefined,
): AgentRecord | undefined {
    if (!selection || !agents?.length) {
        return undefined;
    }
    return agents.find((agent) => agentSelectionKey(agent) === selection);
}

/**
 * Build the `agent_info` payload from a catalog record.
 *
 * Returns null when the record cannot identify an agent, so the caller omits the key
 * entirely rather than sending an empty object the server would treat as a selection.
 */
export function buildAgentInfo(agent: AgentRecord | undefined): AgentInfo | null {
    if (!agent) {
        return null;
    }

    const id = text(agent.id);
    const name = text(agent.name);
    if (!id && !name) {
        return null;
    }

    return {
        id: id || null,
        name,
        display_name: text(agent.display_name) || name,
        is_global: agent.is_global === true,
        is_group: agent.is_group === true,
        group_id: text(agent.group_id) || null,
        group_name: text(agent.group_name) || null,
    };
}

/** Convenience for request construction: selection key straight to a payload value. */
export function agentInfoForSelection(
    agents: AgentRecord[] | undefined,
    selection: string | undefined,
): Json | null {
    const info = buildAgentInfo(findAgent(agents, selection));
    return info ? (info as unknown as Json) : null;
}
