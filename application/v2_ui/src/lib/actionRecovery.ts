// actionRecovery.ts
// A pre-model decision only: never replay a request after model/tool execution.

import { apiUrl, API_BASE } from './apiClient';
import type { ChatStreamRequest } from './types';
import { useBootstrapStore } from '../stores/bootstrapStore';

export interface UnavailableAction {
    key: string;
    name: string;
    reason: string;
    scope: string;
    can_report: boolean;
    capabilities: string[];
    edit_url?: string;
}

export interface ActionRecovery {
    type: 'action_recovery_required';
    id: string;
    conversation_id: string;
    agent_name: string;
    actions: UnavailableAction[];
    all_actions_unavailable: boolean;
    ready?: boolean;
}

export interface RecoveryNotice {
    recovery: ActionRecovery;
    body: ChatStreamRequest;
    waiting: boolean;
    checking: boolean;
    error: string | null;
    actorId?: string;
}

type Decision = 'continue' | 'recheck' | 'cancel';
const credentials: RequestCredentials = API_BASE ? 'include' : 'same-origin';
const listeners = new Set<() => void>();
let notice: RecoveryNotice | null = null;
let decide: ((choice: Decision) => void) | null = null;
let csrfToken = '';
let contextRevision = 0;
const storageKey = (conversationId: string) => `simplechat.action-recovery.${conversationId}`;

export const subscribeActionRecovery = (listener: () => void) => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
};
export const getActionRecovery = () => notice;
export const getActionRecoveryRevision = () => contextRevision;
export const currentActionRecoveryHeaders = (): Record<string, string> => csrfToken ? { 'X-CSRFToken': csrfToken } : {};
function publish(value: RecoveryNotice | null) {
    notice = value ? { ...value, actorId: value.actorId ?? useBootstrapStore.getState().data?.user?.id } : null;
    listeners.forEach((listener) => listener());
}

export function clearActionRecovery(): void {
    contextRevision += 1;
    decide?.('cancel');
    csrfToken = '';
    publish(null);
}

function readRecovery(value: unknown): ActionRecovery | null {
    if (!value || typeof value !== 'object' || !('type' in value)
        || value.type !== 'action_recovery_required') return null;
    if (!('id' in value) || typeof value.id !== 'string'
        || !('conversation_id' in value) || typeof value.conversation_id !== 'string'
        || !('actions' in value) || !Array.isArray(value.actions)
        || !('agent_name' in value) || typeof value.agent_name !== 'string'
        || !('all_actions_unavailable' in value) || typeof value.all_actions_unavailable !== 'boolean') {
        throw new Error('Action availability could not be read. Recheck this agent.');
    }
    const actions: UnavailableAction[] = value.actions.map((item: unknown) => {
        if (!item || typeof item !== 'object'
            || !('key' in item) || typeof item.key !== 'string'
            || !('name' in item) || typeof item.name !== 'string'
            || !('reason' in item) || typeof item.reason !== 'string'
            || !('scope' in item) || typeof item.scope !== 'string'
            || !('can_report' in item) || typeof item.can_report !== 'boolean') {
            throw new Error('An unavailable action could not be read. Recheck this agent.');
        }
        return {
            key: item.key, name: item.name, reason: item.reason, scope: item.scope,
            can_report: item.can_report,
            capabilities: 'capabilities' in item && Array.isArray(item.capabilities)
                ? item.capabilities.filter((entry: unknown): entry is string => typeof entry === 'string')
                : ['All configured operations for this action'],
            ...('edit_url' in item && typeof item.edit_url === 'string' ? { edit_url: item.edit_url } : {}),
        };
    });
    const ready = 'ready' in value && value.ready === true;
    if (!actions.length && !ready) throw new Error('Action availability could not be confirmed.');
    return {
        type: 'action_recovery_required', id: value.id, conversation_id: value.conversation_id,
        agent_name: value.agent_name, actions, all_actions_unavailable: value.all_actions_unavailable, ready,
    };
}

async function recoveryApi(path: string, body?: unknown, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const response = await fetch(apiUrl(path), {
        method: body === undefined ? 'GET' : 'POST', credentials, signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
        throw new Error(response.status === 404 || response.status === 409 || response.status === 410
            ? 'Action recovery changed, expired, or is no longer permitted. Recheck this agent.'
            : 'Action recovery could not be confirmed. Retry safely.');
    }
    return await response.json() as Record<string, unknown>;
}

export async function actionRecoveryHeaders(signal?: AbortSignal): Promise<Record<string, string>> {
    const revision = contextRevision;
    const context = await recoveryApi('/api/action-recovery/context', undefined, signal);
    if (signal?.aborted || revision !== contextRevision) {
        throw new Error('The selected chat context changed. Recheck before sending.');
    }
    if (typeof context.csrf_token !== 'string' || !context.csrf_token) {
        throw new Error('Action recovery could not be initialized.');
    }
    csrfToken = context.csrf_token;
    return { 'X-CSRFToken': csrfToken };
}

export function chooseActionRecovery(choice: Decision): void {
    decide?.(choice);
}

function waitForDecision(signal?: AbortSignal): Promise<Decision> {
    return new Promise((resolve) => {
        const finish = (choice: Decision) => {
            signal?.removeEventListener('abort', cancel);
            if (decide === finish) decide = null;
            resolve(choice);
        };
        const cancel = () => finish('cancel');
        decide = finish;
        signal?.addEventListener('abort', cancel, { once: true });
        if (signal?.aborted) cancel();
    });
}

function publishAvailabilityError(body: ChatStreamRequest): void {
    publish({
        recovery: notice?.recovery ?? {
            type: 'action_recovery_required', id: '', conversation_id: body.conversation_id ?? '',
            agent_name: 'Selected agent', actions: [], all_actions_unavailable: false,
        },
        body, waiting: false, checking: false,
        error: 'Action availability could not be confirmed. Your message has not been sent. Recheck before sending.',
    });
}

export async function prepareActionRequest(
    original: ChatStreamRequest, signal?: AbortSignal,
): Promise<ChatStreamRequest | null> {
    if (!original.agent_info || !original.conversation_id) return original;
    const conversationId = original.conversation_id;
    const revision = contextRevision;
    const body = { ...original };
    body.action_recovery_nonce ??= crypto.randomUUID();
    try {
        await actionRecoveryHeaders(signal);
    } catch (error) {
        if (!signal?.aborted && revision === contextRevision) publishAvailabilityError(body);
        throw error;
    }
    if (signal?.aborted || revision !== contextRevision) return null;
    // A recovered, explicitly confirmed request is still checked and claimed by
    // the backend against fresh authorization and configuration fingerprints.
    if (body.action_recovery) return body;
    for (;;) {
        let value: Record<string, unknown>;
        try {
            value = await recoveryApi('/api/chat/action-health', { request: body }, signal);
        } catch (error) {
            if (!signal?.aborted && revision === contextRevision) publishAvailabilityError(body);
            throw error;
        }
        if (signal?.aborted || revision !== contextRevision) return null;
        const recovery = readRecovery(value);
        if (!recovery) {
            if (value.state !== 'ready' && value.state !== 'not_checked') {
                throw new Error('Action availability could not be confirmed.');
            }
            sessionStorage.removeItem(storageKey(conversationId));
            publish(null);
            return body;
        }
        sessionStorage.setItem(storageKey(conversationId), recovery.id);
        publish({ recovery, body, waiting: true, checking: false, error: null });
        const choice = await waitForDecision(signal);
        if (revision !== contextRevision) return null;
        if (choice === 'cancel' || signal?.aborted) {
            publish({ recovery, body: { ...body, conversation_id: recovery.conversation_id },
                waiting: false, checking: false, error: null });
            return null;
        }
        if (choice === 'continue') {
            publish(null);
            sessionStorage.removeItem(storageKey(conversationId));
            return { ...body, action_recovery: { id: recovery.id, decision: 'continue' } };
        }
        publish({ recovery, body, waiting: true, checking: true, error: null });
    }
}

export function publishActionRecoveryFailure(
    value: unknown, body: ChatStreamRequest, revision = contextRevision,
): boolean {
    if (revision !== contextRevision) return true;
    const recovery = readRecovery(value);
    if (!recovery) return false;
    sessionStorage.setItem(storageKey(recovery.conversation_id), recovery.id);
    publish({ recovery, body, waiting: false, checking: false, error: null });
    return true;
}

export async function restoreActionRecovery(conversationId: string, signal: AbortSignal): Promise<void> {
    const id = sessionStorage.getItem(storageKey(conversationId));
    const revision = contextRevision;
    if (!id || notice?.recovery.conversation_id === conversationId) return;
    await actionRecoveryHeaders(signal);
    const value = await recoveryApi(`/api/action-recovery/${encodeURIComponent(id)}`, undefined, signal);
    if (signal.aborted || revision !== contextRevision) return;
    const recovery = readRecovery(value.recovery);
    if (!recovery) {
        sessionStorage.removeItem(storageKey(conversationId));
        return;
    }
    const body = value.pending_body;
    if (!body || typeof body !== 'object' || !('message' in body) || typeof body.message !== 'string'
        || !('conversation_id' in body) || body.conversation_id !== conversationId) {
        throw new Error('The unsent message could not be restored.');
    }
    publish({ recovery, body: { ...body, message: body.message, conversation_id: conversationId },
        waiting: false, checking: false, error: null });
}

export async function reportUnavailableAction(id: string, key: string): Promise<void> {
    const value = await recoveryApi(`/api/action-recovery/${encodeURIComponent(id)}/report`, { action_key: key });
    if (value.reported !== true) throw new Error('Report delivery could not be confirmed. Retry safely.');
}

export function safeRecoveryEditUrl(value: string | undefined): string | undefined {
    return value && /^\/v2\/(?:workspace\/actions\/|groups\/[^/\\]+\/actions\/|admin\/actions\/)[^/\\?#]+$/.test(value)
        ? value : undefined;
}
