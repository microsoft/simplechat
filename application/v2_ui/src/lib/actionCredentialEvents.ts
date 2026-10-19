// actionCredentialEvents.ts

import type { CredentialRequest, CredentialSlot, PersonalCredentialAuth } from './actionCredentialTypes';

export const ACTION_CREDENTIAL_EVENT = 'simplechat:action-credentials';
const record = (value: unknown): value is Record<string, unknown> =>
    !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): string => typeof value === 'string' ? value : '';
const authType = (value: unknown): value is PersonalCredentialAuth =>
    value === 'username_password' || value === 'api_key' || value === 'bearer_token';
const slotType = (value: unknown): value is CredentialSlot => value === 'service' || value === 'proxy';

export function readCredentialRequest(value: unknown): CredentialRequest {
    if (!record(value) || !text(value.id) || !text(value.etag) || !text(value.conversation_id) ||
        !Array.isArray(value.requirements) || !Array.isArray(value.identities)) {
        throw new Error('The credential request could not be read. Reload this conversation.');
    }
    if (value.conversation_kind !== undefined && value.conversation_kind !== 'personal' &&
        value.conversation_kind !== 'collaborative') {
        throw new Error('The credential request belongs to an unsupported conversation.');
    }
    const requirements = value.requirements.map((item) => {
        if (!record(item) || !slotType(item.slot) || !authType(item.auth_type) ||
            (item.slot === 'proxy' && item.auth_type !== 'username_password')) {
            throw new Error('This credential request requires an unsupported authentication method.');
        }
        return { slot: item.slot, auth_type: item.auth_type, label: text(item.label) };
    });
    if (new Set(requirements.map((item) => item.slot)).size !== requirements.length) {
        throw new Error('This credential request contains conflicting authentication slots.');
    }
    return {
        id: text(value.id), etag: text(value.etag), conversation_id: text(value.conversation_id),
        action_name: text(value.action_name), destination_label: text(value.destination_label),
        reason: text(value.reason), status: text(value.status), requirements,
        ...(value.conversation_kind ? { conversation_kind: value.conversation_kind } : {}),
        identities: value.identities.flatMap((item) => record(item) && text(item.id)
            ? [{ id: text(item.id), name: text(item.name), auth_type: text(item.auth_type),
                ...(text(item.etag) ? { etag: text(item.etag) } : {}) }] : []),
        ...(text(value.run_id) ? { run_id: text(value.run_id) } : {}),
        ...(text(value.turn_id) ? { turn_id: text(value.turn_id) } : {}),
    };
}

export function publishCredentialRequest(value: unknown): void {
    const credentialRequest = readCredentialRequest(value);
    if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent(ACTION_CREDENTIAL_EVENT, { detail: credentialRequest }));
    }
}
