// actionCredentials.ts

import { apiUrl, CREDENTIALS_MODE, request } from './apiClient';
import { readCredentialRequest } from './actionCredentialEvents';
import type { CredentialRequest, CredentialSubmission } from './actionCredentialTypes';

let csrfToken = '';
let sessionEpoch = 0;

export function clearCredentialSession(): void {
    csrfToken = '';
    sessionEpoch += 1;
}

function captureCsrf(result: { csrf_token?: unknown }, epoch: number): void {
    if (epoch === sessionEpoch && typeof result.csrf_token === 'string') csrfToken = result.csrf_token;
}

async function credentialHeaders(credentialRequest: CredentialRequest, signal?: AbortSignal): Promise<Record<string, string>> {
    if (!csrfToken) {
        const epoch = sessionEpoch;
        const result = await request<{ credential_request: unknown; csrf_token?: unknown }>(
            `/api/action-credentials/${encodeURIComponent(credentialRequest.id)}`,
            { cache: 'no-store', signal },
        );
        const current = readCredentialRequest(result.credential_request);
        if (current.id !== credentialRequest.id || current.conversation_id !== credentialRequest.conversation_id) {
            throw new Error('The credential request no longer belongs to this conversation.');
        }
        captureCsrf(result, epoch);
    }
    if (!csrfToken) throw new Error('The credential request could not be authorized. Reload this conversation.');
    return { 'X-CSRFToken': csrfToken };
}

export async function fetchCredentialRequests(conversationId: string, signal?: AbortSignal): Promise<CredentialRequest[]> {
    const epoch = sessionEpoch;
    const result = await request<{ requests: unknown[]; csrf_token?: unknown }>(
        `/api/action-credentials/pending?${new URLSearchParams({ conversation_id: conversationId })}`,
        { cache: 'no-store', signal },
    );
    captureCsrf(result, epoch);
    return result.requests.map(readCredentialRequest);
}

export async function saveActionCredentials(
    credentialRequest: CredentialRequest, slots: CredentialSubmission[], signal?: AbortSignal,
): Promise<CredentialRequest> {
    const headers = await credentialHeaders(credentialRequest, signal);
    const result = await request<{ credential_request: unknown }>(
        `/api/action-credentials/${encodeURIComponent(credentialRequest.id)}/submit`,
        { method: 'POST', body: { expected_etag: credentialRequest.etag, slots }, cache: 'no-store', headers, signal },
    );
    const updated = readCredentialRequest(result.credential_request);
    if (updated.id !== credentialRequest.id || updated.conversation_id !== credentialRequest.conversation_id ||
        updated.status !== 'ready') {
        throw new Error('Saving could not be confirmed. Reload this credential request before continuing.');
    }
    return updated;
}

export async function cancelActionCredentials(credentialRequest: CredentialRequest, signal?: AbortSignal): Promise<void> {
    const headers = await credentialHeaders(credentialRequest, signal);
    await request(`/api/action-credentials/${encodeURIComponent(credentialRequest.id)}/cancel`, {
        method: 'POST', body: { expected_etag: credentialRequest.etag }, cache: 'no-store', headers, signal,
    });
}

export async function openCredentialContinuation(
    credentialRequest: CredentialRequest, signal?: AbortSignal,
): Promise<Response> {
    const headers = await credentialHeaders(credentialRequest, signal);
    const response = await fetch(apiUrl(`/api/action-credentials/${encodeURIComponent(credentialRequest.id)}/continue`), {
        method: 'POST', credentials: CREDENTIALS_MODE, cache: 'no-store', signal,
        headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify({ expected_etag: credentialRequest.etag }),
    });
    if (!response.ok) {
        throw new Error(response.status === 409
            ? 'This credential request changed or was already continued. Reload the conversation before continuing.'
            : 'The blocked action could not be continued. Reload the conversation and try again.');
    }
    return response;
}
