// userInput.ts

import { apiUrl, CREDENTIALS_MODE, request } from './apiClient';
import { v2ApiFetch } from './v2SourcePolicy';
import { useUserInputStore, type UserInputRequest } from '../stores/userInputStore';
import type { ElicitationContext, ElicitationResponse } from './orchestration';

export function publishUserInput(value: UserInputRequest): void {
    useUserInputStore.getState().accept(value);
}

export function fetchUserInput(conversationId: string, signal?: AbortSignal) {
    return request<{ requests: UserInputRequest[]; csrf_token: string }>(
        `/api/v2/user-input/pending?${new URLSearchParams({ conversation_id: conversationId })}`,
        { cache: 'no-store', signal },
    );
}

export async function saveUserInput(
    input: UserInputRequest, submissionId: string, response: ElicitationResponse,
    context: ElicitationContext | undefined, csrf: string,
): Promise<UserInputRequest> {
    const result = await request<{ input_request: UserInputRequest }>(
        `/api/v2/user-input/${encodeURIComponent(input.id)}/answer`,
        { method: 'POST', cache: 'no-store', headers: { 'X-CSRFToken': csrf },
            body: { revision: input.revision, submission_id: submissionId, response,
                context: response.action === 'accept' ? context ?? {} : {} } },
    );
    if (result.input_request.id !== input.id || result.input_request.actor_id !== input.actor_id
        || result.input_request.conversation_id !== input.conversation_id) {
        throw new Error('The saved answers could not be confirmed.');
    }
    return result.input_request;
}

export async function openUserInputContinuation(
    input: UserInputRequest, submissionId: string, csrf: string, signal?: AbortSignal,
): Promise<Response> {
    const response = await v2ApiFetch(apiUrl(`/api/v2/user-input/${encodeURIComponent(input.id)}/continue`), {
        method: 'POST', credentials: CREDENTIALS_MODE, cache: 'no-store', signal,
        headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ submission_id: submissionId }),
    });
    if (!response.ok) throw new Error(response.status === 409
        ? 'This request changed or is already continuing. Refresh its saved status; no work was replayed.'
        : 'The saved work could not continue. Refresh the conversation and try again.');
    return response;
}

export async function stopUserInput(input: UserInputRequest, submissionId: string, csrf: string): Promise<void> {
    const result = await request<{ cancel_requested: boolean; status: string }>(
        `/api/v2/user-input/${encodeURIComponent(input.id)}/stop`,
        { method: 'POST', cache: 'no-store', headers: { 'X-CSRFToken': csrf },
            body: { submission_id: submissionId } },
    );
    if (!result.cancel_requested && !['completed', 'cancelled', 'failed', 'superseded'].includes(result.status)) {
        throw new Error('Stopping could not be confirmed. Refresh the saved status.');
    }
}
