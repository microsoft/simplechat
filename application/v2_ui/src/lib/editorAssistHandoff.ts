// editorAssistHandoff.ts
// An explicit agent-to-action detour keeps its originating editor session in tab memory.

import { holdAssistThread, useAssistThreadStore } from '../stores/assistThreadStore';
import { useEditorAssistStore } from '../stores/editorAssistStore';
import { agentEditorReturnPath, GLOBAL_AGENT_RETURN_SCOPE, isActionEditorNewPath } from './workspaceAuthoring';
import type { ActionConfiguration } from './workspaceAuthoring';
import type { EditorWorkspaceScope } from './workspaceEditorDrafts';

export interface AgentAssistSession {
    visit: string;
    open: boolean;
    stash: Map<string, ActionConfiguration>;
    scrollTop: number;
    focusReference: string | null;
}

interface Handoff {
    owner: string;
    path: string;
    scope: EditorWorkspaceScope;
    session: AgentAssistSession;
    threadKey: string | null;
    release: (() => void) | null;
}

const handoffs = new Map<string, Handoff>();
export const MAX_AGENT_ASSIST_HANDOFFS = 8;

function key(owner: string, path: string, scope: EditorWorkspaceScope): string {
    return JSON.stringify([owner, scope.kind, scope.kind === 'group' ? scope.id : '', path]);
}

function validPath(path: string, scope: EditorWorkspaceScope): string | null {
    return agentEditorReturnPath(path, scope.kind === 'group' ? scope.id
        : scope.kind === 'global' ? GLOBAL_AGENT_RETURN_SCOPE : undefined);
}

function releaseHandoff(item: Handoff, forget: boolean): void {
    item.release?.();
    if (forget && item.threadKey) {
        useAssistThreadStore.getState().forgetThread(item.threadKey);
        useEditorAssistStore.getState().forgetThread(item.threadKey);
    }
}

export function suspendAgentAssist(
    owner: string, path: string, scope: EditorWorkspaceScope, session: AgentAssistSession, threadKey: string | null,
): void {
    if (!validPath(path, scope)) throw new Error('Invalid agent editor return path.');
    const id = key(owner, path, scope);
    const previous = handoffs.get(id);
    if (previous) releaseHandoff(previous, previous.threadKey !== threadKey);
    handoffs.delete(id);
    handoffs.set(id, { owner, path, scope, session, threadKey, release: threadKey ? holdAssistThread(threadKey) : null });
    while (handoffs.size > MAX_AGENT_ASSIST_HANDOFFS) {
        const oldest = handoffs.entries().next().value;
        if (!oldest) break;
        releaseHandoff(oldest[1], true);
        handoffs.delete(oldest[0]);
    }
}

/** Peek during render; consume in an effect so React's repeated initializers are safe. */
export function readAgentAssist(owner: string, path: string, scope: EditorWorkspaceScope): AgentAssistSession | null {
    return handoffs.get(key(owner, path, scope))?.session ?? null;
}

export function resumeAgentAssist(owner: string, path: string, scope: EditorWorkspaceScope, session: AgentAssistSession): void {
    const id = key(owner, path, scope);
    const item = handoffs.get(id);
    if (item?.session !== session) return;
    releaseHandoff(item, false);
    handoffs.delete(id);
}

/** Called by the app router: abandoning the detour releases its transcript and Undo records. */
export function pruneAgentAssistHandoffs(owner: string, pathname: string, search: string): void {
    for (const [id, item] of handoffs) {
        const returning = pathname === item.path;
        const editingAction = isActionEditorNewPath(pathname)
            && pathname === `${item.path.slice(0, item.path.lastIndexOf('/agents/'))}/actions/new`
            && validPath(new URLSearchParams(search).get('returnTo') ?? '', item.scope) === item.path;
        if (item.owner === owner && (returning || editingAction)) continue;
        releaseHandoff(item, true);
        handoffs.delete(id);
    }
}

export function clearAgentAssistHandoffs(): void {
    for (const item of handoffs.values()) releaseHandoff(item, true);
    handoffs.clear();
}
