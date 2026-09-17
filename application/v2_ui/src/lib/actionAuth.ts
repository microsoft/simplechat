// actionAuth.ts
// Private action-authentication DTOs contain no credential values or conversation text.

import { ApiError, api } from './apiClient';
import { buildAgentInfo } from './agents';
import { isRecord } from './workspaceAuthoring';

export type ActionAuthProfile = 'yamcs_login' | 'http_basic' | 'bearer_token' | 'api_key';
export type ActionIdentityAuthType = 'username_password' | 'bearer_token' | 'api_key';
export type ActionCredentialValues = { username: string; password: string } | { secret: string };

export interface ActionCredentialRequirement {
    id?: string;
    source: 'current_user';
    identity_name: string;
    profile: ActionAuthProfile;
}

export const ACTION_AUTH_PROFILES = {
    yamcs_login: {
        label: 'Yamcs username and password', authType: 'username_password',
        nativeAuthType: 'username_password', authMethod: 'username_password',
    },
    http_basic: {
        label: 'Gateway HTTP Basic', authType: 'username_password',
        nativeAuthType: 'basic', authMethod: 'http_basic',
    },
    bearer_token: {
        label: 'Bearer token', authType: 'bearer_token',
        nativeAuthType: 'key', authMethod: 'bearer_token',
    },
    api_key: {
        label: 'API key', authType: 'api_key',
        nativeAuthType: 'key', authMethod: 'api_key',
    },
} as const;

export const ACTION_AUTH_SHARING_NOTICE =
    'Your account is used for this request. Your message and returned data will be visible to everyone with access to this conversation. Your saved credentials and credential form are private.';

export interface ActionAuthIdentity {
    id: string;
    name: string;
    auth_type: ActionIdentityAuthType;
}

export interface ActionAuthRequirement {
    id: string;
    action_id: string;
    action_name: string;
    identity_name: string;
    profile: ActionAuthProfile;
    auth_type: ActionIdentityAuthType;
    destination: string;
    reason: string;
    identities: ActionAuthIdentity[];
}

export interface ActionAuthState {
    status: 'ready' | 'credentials_required';
    request_id: string | null;
    uses_personal_credentials: boolean;
    shared_conversation: boolean;
    sharing_notice: string | null;
    requirements: ActionAuthRequirement[];
}

export interface ActionCredentialsControl {
    type: 'action_credentials_required';
    error_code: 'action_credentials_required';
    request_id?: string;
    action_ref?: string;
    execution_started?: boolean;
}

export interface ActionAuthPreflight {
    agent_info?: unknown;
    action_ref?: string;
    run_id?: string;
    conversation_id: string | null;
    conversation_kind: 'personal' | 'collaboration';
}

export function isActionAuthProfile(value: unknown): value is ActionAuthProfile {
    return typeof value === 'string' && Object.hasOwn(ACTION_AUTH_PROFILES, value);
}

export function isActionIdentityAuthType(value: unknown): value is ActionIdentityAuthType {
    return value === 'username_password' || value === 'bearer_token' || value === 'api_key';
}

function text(value: unknown, limit = 500): string {
    return typeof value === 'string' ? value.slice(0, limit) : '';
}

export function safeActionAuthDestination(value: unknown): string {
    try {
        const url = new URL(text(value, 2048));
        if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) return '';
        return `${url.origin}${url.pathname}`;
    } catch {
        return '';
    }
}

/** Pick the canonical selection fields, never a prompt, workspace owner, or raw manifest. */
export function actionAuthPreflightBody(input: ActionAuthPreflight): ActionAuthPreflight {
    const agentInfo = isRecord(input.agent_info) ? buildAgentInfo(input.agent_info) : null;
    return {
        ...(agentInfo ? { agent_info: agentInfo } : {}),
        ...(input.action_ref ? { action_ref: input.action_ref } : {}),
        ...(input.run_id ? { run_id: input.run_id } : {}),
        conversation_id: input.conversation_id || null,
        conversation_kind: input.conversation_kind === 'collaboration' ? 'collaboration' : 'personal',
    };
}

export function actionAuthAgentFromMetadata(metadata: unknown): unknown {
    if (!isRecord(metadata)) return undefined;
    if (isRecord(metadata.agent_info)) return buildAgentInfo(metadata.agent_info) ?? undefined;
    const selection = metadata.agent_selection;
    if (!isRecord(selection)) return undefined;
    return buildAgentInfo({
        id: selection.agent_id, name: selection.selected_agent, display_name: selection.agent_display_name,
        is_global: selection.is_global, is_group: selection.is_group,
        group_id: selection.group_id, group_name: selection.group_name,
    }) ?? undefined;
}

/** Ignore server/model form schemas: only the four app-authored profiles can render inputs. */
export function normalizeActionAuthState(value: unknown): ActionAuthState {
    if (!isRecord(value) || !['ready', 'credentials_required'].includes(String(value.status))) {
        throw new Error('This credential request is no longer available. Cancel and submit again.');
    }
    const requestId = text(value.request_id, 255) || null;
    const requirements = (Array.isArray(value.requirements) ? value.requirements : []).map((item): ActionAuthRequirement => {
        if (!isRecord(item) || !isActionAuthProfile(item.profile) || !text(item.id, 255) ||
            item.auth_type !== ACTION_AUTH_PROFILES[item.profile].authType || !safeActionAuthDestination(item.destination)) {
            throw new Error('The action returned an unsupported credential requirement.');
        }
        const profile = item.profile;
        const authType = ACTION_AUTH_PROFILES[profile].authType;
        return {
            id: text(item.id, 255), action_id: text(item.action_id, 255),
            action_name: text(item.action_name, 120), identity_name: text(item.identity_name, 120) || 'Yamcs',
            profile, auth_type: authType, destination: safeActionAuthDestination(item.destination),
            reason: text(item.reason, 80),
            identities: (Array.isArray(item.identities) ? item.identities : []).flatMap((identity) =>
                isRecord(identity) && text(identity.id, 255) && identity.auth_type === authType
                    ? [{ id: text(identity.id, 255), name: text(identity.name, 120), auth_type: authType }] : []),
        };
    });
    if (value.status === 'credentials_required' && (!requestId || requirements.length === 0)) {
        throw new Error('This credential request cannot be continued. Cancel and submit again.');
    }
    if (value.uses_personal_credentials === true && !requestId || value.status === 'ready' && requirements.length > 0) {
        throw new Error('The action returned an inconsistent credential request.');
    }
    return {
        status: value.status as ActionAuthState['status'],
        request_id: requestId,
        uses_personal_credentials: value.uses_personal_credentials === true || requirements.length > 0,
        shared_conversation: value.shared_conversation === true,
        sharing_notice: value.shared_conversation === true ? ACTION_AUTH_SHARING_NOTICE : null,
        requirements,
    };
}

export function isActionCredentialsRequired(value: unknown): boolean {
    return normalizeActionCredentialsControl(value) !== null;
}

export function normalizeActionCredentialsControl(value: unknown): ActionCredentialsControl | null {
    const payload = value instanceof ApiError ? value.payload : value;
    if (!isRecord(payload) || (payload.error_code !== 'action_credentials_required' &&
        payload.type !== 'action_credentials_required')) return null;
    const requestId = text(payload.request_id, 255);
    const actionRef = typeof payload.action_ref === 'string' && payload.action_ref.length <= 4096 &&
        /^action:v1:(personal|group|global):[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$/.test(payload.action_ref)
        ? payload.action_ref : '';
    return {
        type: 'action_credentials_required',
        error_code: 'action_credentials_required',
        ...(requestId ? { request_id: requestId } : {}),
        ...(actionRef ? { action_ref: actionRef } : {}),
        ...(typeof payload.execution_started === 'boolean' ? { execution_started: payload.execution_started } : {}),
    };
}

/** Error responses are not allowed to echo submitted credentials into the interface. */
export function actionAuthErrorMessage(error: unknown): string {
    const payload = error instanceof ApiError && isRecord(error.payload) ? error.payload : {};
    const code = text(payload.error_code || payload.code);
    if (/rejected|invalid_credentials|authentication_failed/.test(code)) {
        return 'The service rejected this credential. Check the values and try again. Your saved identity has not been replaced.';
    }
    if (/permission|forbidden|access_denied/.test(code) || error instanceof ApiError && error.status === 403) {
        return 'Your account is not permitted to use this action or resource. Check access with your administrator.';
    }
    if (/connection|network|timeout|unreachable/.test(code) || error instanceof TypeError) {
        return 'The service could not be reached. Check the connection and try again; this is not a password rejection.';
    }
    if (/storage|key_vault|keyvault/.test(code) || error instanceof ApiError && error.status >= 500) {
        return 'The credential could not be stored or validated. Nothing will run. Check again or contact your administrator.';
    }
    if (error instanceof ApiError && [404, 409, 410].includes(error.status)) {
        return 'The request, action, or identity changed or expired. Cancel and submit again to review the current destination.';
    }
    return 'The credential request could not be completed. Check the required fields, or cancel and try again.';
}

export const preflightActionAuth = async (input: ActionAuthPreflight, signal?: AbortSignal) =>
    normalizeActionAuthState(await api.post('/api/action-auth/preflight', actionAuthPreflightBody(input), signal));

export const readActionAuthRequest = async (requestId: string, signal?: AbortSignal) =>
    normalizeActionAuthState(await api.get(`/api/action-auth/requests/${encodeURIComponent(requestId)}`, signal));

export async function saveActionAuthCredentials(
    requestId: string,
    requirementId: string,
    identityId: string | undefined,
    credentials: ActionCredentialValues | undefined,
    signal?: AbortSignal,
): Promise<ActionAuthState> {
    const fields = credentials
        ? 'username' in credentials ? { username: credentials.username, password: credentials.password } : { secret: credentials.secret }
        : undefined;
    return normalizeActionAuthState(await api.post(
        `/api/action-auth/requests/${encodeURIComponent(requestId)}/credentials`,
        {
            requirement_id: requirementId,
            ...(identityId ? { identity_id: identityId } : {}),
            ...(fields ? { credentials: fields } : {}),
            confirm_destination: true,
        },
        signal,
    ));
}

export const cancelActionAuthRequest = (requestId: string) =>
    api.post(`/api/action-auth/requests/${encodeURIComponent(requestId)}/cancel`);
