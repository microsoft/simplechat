// workflowResults.ts
// Asking chat about a finished workflow run's stored result (roadmap phase 6a, Follow up).
//
// The browser only ever holds the public descriptor: the run's ids, its result digest and
// a display name. Store references and result content never reach it. The server re-reads
// the run with the selected digest on every turn, so a result that changed or was deleted
// is refused rather than answered. The documents the run used are never re-checked: the
// result takes its access from the run.
//
// Everything here is pure, so it is checked in isolation by
// functional_tests/test_workflow_results_clients.mjs.

import { api, ApiError } from './apiClient';
import { messageThreadId } from './threads';
import type {
    ChatMessage,
    ChatStreamEvent,
    ChatStreamRequest,
    WorkflowResultContext,
    WorkflowResultDescriptor,
} from './types';

export const WORKFLOW_RESULT_VERSION = 'workflow-result-v1';
/** The `warning_type` every Follow up refusal carries, on the JSON precheck and on the stream. */
export const WORKFLOW_RESULT_WARNING_TYPE = 'workflow_result_unavailable';
export const WORKFLOW_RESULT_PLACEHOLDER = 'Ask about the workflow results…';
export const WORKFLOW_RESULT_OPENING_NOTICE = 'Opening the workflow result…';
export const WORKFLOW_RESULT_LAUNCH_PENDING_MESSAGE =
    'The workflow result is still opening. Send your question again once it is selected.';
export const WORKFLOW_RESULT_INVALID_LINK_MESSAGE = 'That workflow result link is not valid.';

/** The same shapes the server accepts (functions_workflow_result_reader.py). */
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const WORKFLOW_NAME_MAX_CHARS = 80;
const TIME_ZONE_MAX_CHARS = 64;
const READABLE_STATUSES = new Set(['completed', 'completed_partial']);

/**
 * The server's fixed wording for every closed reason, mirrored so a refusal reads the same
 * whether it arrives as a JSON precheck, a stream error or a failed descriptor read.
 */
const REASON_MESSAGES: Record<string, string> = {
    workflow_results_disabled: 'Workflow results in chat are not available.',
    workflow_result_invalid_context: 'The selected workflow result is invalid.',
    workflow_result_context_conflict: 'Ask about either a saved analysis or a workflow result, not both.',
    workflow_result_private_only: 'Workflow results can only be used in your own private chats.',
    workflow_result_not_found: 'This workflow result is unavailable. The run may have been removed.',
    workflow_result_access_denied:
        'This workflow result is unavailable because access to it could not be confirmed.',
    workflow_result_changed:
        "This workflow run's result has changed since it was selected. "
        + 'Select the run again to ask about its current result.',
    workflow_result_in_progress: "This workflow run hasn't finished yet. Ask about it after it completes.",
    workflow_result_not_finished: "This workflow run didn't complete, so it has no result to ask about.",
    workflow_result_preview_only:
        'This workflow run has no stored result to ask about. Older runs keep previews only.',
    workflow_result_unsupported: "Asking about the results of this kind of workflow isn't supported yet.",
    workflow_result_invalid: "This workflow run's stored result can't be read.",
    workflow_result_storage_unavailable: "The workflow result couldn't be read right now. Try again in a moment.",
    workflow_result_conversation_unavailable:
        'This chat is no longer available. Start a new chat to ask about the workflow result.',
    workflow_result_retry_unsupported:
        "Retrying or editing a question about a workflow result isn't supported yet. Ask the question again.",
    workflow_result_too_large:
        "The workflow result and this chat's history don't fit the selected model. "
        + 'Select a model with a larger context window or start a new chat, then ask again.',
    workflow_result_model_unsupported:
        "The selected model or agent couldn't answer from this workflow result with its tools turned off. "
        + 'Select a model or a local chat agent, then ask again.',
    workflow_result_answer_failed:
        "The answer couldn't be completed. The workflow result is unchanged. Try again in a moment.",
    workflow_result_answer_rejected:
        "The answer wasn't kept because it didn't match the stored workflow result. "
        + 'The result is unchanged. Ask again, or ask a narrower question.',
};

/**
 * Refusals that mean the selected result can no longer be asked about as selected. The chip
 * is removed for these; the rest (storage, model fit, a failed answer) leave it in place so
 * the same question can be asked again.
 */
const CHIP_CLEARING_CODES = new Set([
    'workflow_results_disabled',
    'workflow_result_invalid_context',
    'workflow_result_private_only',
    'workflow_result_not_found',
    'workflow_result_access_denied',
    'workflow_result_changed',
    'workflow_result_in_progress',
    'workflow_result_not_finished',
    'workflow_result_preview_only',
    'workflow_result_unsupported',
    'workflow_result_invalid',
    'workflow_result_conversation_unavailable',
]);

const GENERIC_UNAVAILABLE = 'This workflow result is unavailable.';
const SIGN_IN_AGAIN = 'Sign in again to ask about this workflow result.';

export const WORKFLOW_RESULT_RETRY_UNSUPPORTED_MESSAGE = REASON_MESSAGES.workflow_result_retry_unsupported;

/** A workflow result selected for the composer, and the chat it belongs to. */
export interface SelectedWorkflowResult {
    /** Null until a new chat's first message creates the conversation. */
    conversation_id: string | null;
    descriptor: WorkflowResultDescriptor;
}

export interface WorkflowResultRefusal {
    code: string;
    message: string;
    /** Whether the chip must go: the result can no longer be asked about as selected. */
    clears: boolean;
}

function object(value: unknown): value is Record<string, unknown> {
    return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

export function isWorkflowResultIdentifier(value: unknown): value is string {
    return typeof value === 'string' && IDENTIFIER.test(value);
}

function isoTimestamp(value: unknown): string | null {
    if (typeof value !== 'string' || !value.trim()) {
        return null;
    }
    return Number.isNaN(new Date(value).valueOf()) ? null : value;
}

/** Validate a descriptor as the server sends it. Anything unexpected reads as no descriptor. */
export function parseWorkflowResultDescriptor(value: unknown): WorkflowResultDescriptor | null {
    if (!object(value) || value.version !== WORKFLOW_RESULT_VERSION ||
        !isWorkflowResultIdentifier(value.workflow_id) || !isWorkflowResultIdentifier(value.run_id) ||
        typeof value.result_sha256 !== 'string' || !SHA256.test(value.result_sha256) ||
        typeof value.status !== 'string' || !READABLE_STATUSES.has(value.status) ||
        (value.workflow_name !== undefined && typeof value.workflow_name !== 'string')) {
        return null;
    }
    // User-authored display text: bounded, and only ever rendered as text.
    const name = String(value.workflow_name ?? '').trim().slice(0, WORKFLOW_NAME_MAX_CHARS);
    return {
        version: WORKFLOW_RESULT_VERSION,
        workflow_id: value.workflow_id,
        run_id: value.run_id,
        result_sha256: value.result_sha256,
        workflow_name: name || 'Workflow',
        status: value.status as WorkflowResultDescriptor['status'],
        completed_at: isoTimestamp(value.completed_at),
        available: value.available !== false,
    };
}

/** The descriptor a message's metadata carries, if any. A masked answer carries none. */
export function readWorkflowResult(metadata: unknown): WorkflowResultDescriptor | null {
    return parseWorkflowResultDescriptor(object(metadata) ? metadata.workflow_result : null);
}

/** The only selector the browser sends. */
export function workflowResultContext(value: WorkflowResultContext): WorkflowResultContext {
    return {
        workflow_id: value.workflow_id,
        run_id: value.run_id,
        result_sha256: value.result_sha256,
    };
}

export function sameWorkflowResult(
    left: WorkflowResultContext | null | undefined,
    right: WorkflowResultContext | null | undefined,
): boolean {
    return Boolean(left && right && left.workflow_id === right.workflow_id &&
        left.run_id === right.run_id && left.result_sha256 === right.result_sha256);
}

/**
 * The workflow result the conversation's latest answer was built from, so later turns
 * inherit it without selecting the run again.
 *
 * Read from the latest turn only, as with saved analyses: once anything else has been
 * asked since, the result is no longer what the conversation is about.
 */
export function latestWorkflowResult(messages: ChatMessage[]): WorkflowResultDescriptor | null {
    const message = [...messages].reverse().find((item) =>
        (item.role === 'assistant' || item.role === 'user') && !item.metadata?.is_deleted,
    );
    if (message?.role !== 'assistant' || message.metadata?.masked ||
        (Array.isArray(message.metadata?.masked_ranges) && message.metadata.masked_ranges.length > 0)) {
        return null;
    }
    const descriptor = readWorkflowResult(message.metadata);
    return descriptor?.available !== false ? descriptor : null;
}

/** Whether a message is a question about a workflow result, or the answer to one. */
export function messageAsksAboutWorkflowResult(message: ChatMessage | undefined): boolean {
    const metadata = message?.metadata;
    return object(metadata) && (object(metadata.workflow_result) || object(metadata.workflow_result_context));
}

/**
 * Whether retrying or editing this message would re-ask a workflow result question.
 *
 * Retry and edit build their own request on the server, without the selection, so either
 * would silently become an ordinary chat turn. A masked question has lost its link to the
 * result, so the rest of its thread is checked too.
 */
export function turnAsksAboutWorkflowResult(messages: ChatMessage[], messageId: string): boolean {
    const message = messages.find((item) => item.id === messageId);
    if (!message) {
        return false;
    }
    if (messageAsksAboutWorkflowResult(message)) {
        return true;
    }
    const threadId = messageThreadId(message);
    return Boolean(threadId) && messages.some((item) =>
        messageThreadId(item) === threadId && messageAsksAboutWorkflowResult(item));
}

/** The browser's IANA zone, so the answer's disclosure names the run's time as the reader sees it. */
export function requestTimeZone(): string | undefined {
    try {
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        return typeof zone === 'string' && zone && zone.length <= TIME_ZONE_MAX_CHARS ? zone : undefined;
    } catch {
        return undefined;
    }
}

/**
 * Point a chat request at the selected workflow result, and at nothing else.
 *
 * Applied only when the selection belongs to the conversation the request is for. The server
 * builds this turn's messages itself, so every other source is off and the orchestration and
 * document-action fields are removed; the request cannot widen what the answer reads.
 */
export function applyWorkflowResultContext(
    request: ChatStreamRequest,
    selected: SelectedWorkflowResult | null,
): ChatStreamRequest {
    if (!selected || selected.conversation_id !== (request.conversation_id ?? null)) {
        return request;
    }
    const zone = requestTimeZone();
    const result: ChatStreamRequest = {
        ...request,
        workflow_result_context: workflowResultContext(selected.descriptor),
        ...(zone ? { time_zone: zone } : {}),
        hybrid_search: false,
        document_context_requested: false,
        user_workspace_context_enabled: false,
        web_search_enabled: false,
        url_access_enabled: false,
        source_review_enabled: false,
        deep_research_enabled: false,
        image_generation: false,
        selected_document_id: null,
        selected_document_ids: [],
        conversation_task_document_ids: [],
        tags: [],
        doc_scope: 'personal',
        active_group_ids: [],
        active_group_id: null,
        active_public_workspace_ids: [],
        active_public_workspace_id: null,
    };
    for (const key of [
        'analysis_result_context', 'document_action', 'analyze', 'document_filter_mode',
        'orchestration', 'orchestration_context', 'image_references',
    ]) {
        delete result[key];
    }
    return result;
}

/** What to tell the reader for a closed reason, by code first and status second. */
export function workflowResultErrorMessage(code: unknown, status?: number): string {
    if (typeof code === 'string' && Object.hasOwn(REASON_MESSAGES, code)) {
        return REASON_MESSAGES[code];
    }
    if (status === 401) {
        return SIGN_IN_AGAIN;
    }
    if (status === 400 || status === 403) {
        // Personal workflows turned off, or the WorkflowUser role missing: both answer
        // without a Follow up code.
        return REASON_MESSAGES.workflow_results_disabled;
    }
    if (status === 404) {
        return REASON_MESSAGES.workflow_result_not_found;
    }
    if (status === 503) {
        return REASON_MESSAGES.workflow_result_storage_unavailable;
    }
    return GENERIC_UNAVAILABLE;
}

function eventCode(event: Record<string, unknown>): string {
    const code = event.error_code ?? event.code;
    return typeof code === 'string' ? code : '';
}

/**
 * Read a stream or precheck failure as a Follow up refusal, or null when it is some other
 * failure. Only these carry the Follow up `warning_type` or one of its codes.
 */
export function workflowResultRefusal(event: ChatStreamEvent | undefined | null): WorkflowResultRefusal | null {
    if (!object(event)) {
        return null;
    }
    const code = eventCode(event);
    const known = Object.hasOwn(REASON_MESSAGES, code);
    if (event.warning_type !== WORKFLOW_RESULT_WARNING_TYPE && !known) {
        return null;
    }
    const status = typeof event.status_code === 'number' ? event.status_code : undefined;
    const serverText = typeof event.error === 'string' && event.error.trim() ? event.error : '';
    return {
        code,
        message: known ? REASON_MESSAGES[code] : serverText || workflowResultErrorMessage(code, status),
        clears: CHIP_CLEARING_CODES.has(code),
    };
}

/** What to tell the reader when the descriptor could not be read. */
export function workflowResultFetchErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const payload = object(error.payload) ? error.payload : {};
        return workflowResultErrorMessage(payload.code, error.status);
    }
    return REASON_MESSAGES.workflow_result_storage_unavailable;
}

/** Whether a failed descriptor read means the result is unavailable, rather than transiently unreadable. */
export function isWorkflowResultUnavailable(error: unknown): error is ApiError {
    return error instanceof ApiError && [400, 401, 403, 404, 409].includes(error.status);
}

export function workflowResultContextPath(workflowId: string, runId: string): string {
    return `/api/user/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/result-context`;
}

/**
 * Read the current descriptor of one finished personal run.
 *
 * Every entry point reads it fresh rather than trusting one it was handed, so the chip always
 * names the result as it is now. A body that does not describe the run asked for is refused.
 */
export async function fetchWorkflowResultDescriptor(
    workflowId: string,
    runId: string,
    signal?: AbortSignal,
): Promise<WorkflowResultDescriptor> {
    if (!isWorkflowResultIdentifier(workflowId) || !isWorkflowResultIdentifier(runId)) {
        throw new ApiError(REASON_MESSAGES.workflow_result_not_found, 404, { code: 'workflow_result_not_found' });
    }
    const payload = await api.get<unknown>(workflowResultContextPath(workflowId, runId), signal);
    const descriptor = parseWorkflowResultDescriptor(object(payload) ? payload.workflow_result : null);
    if (!descriptor || descriptor.available === false ||
        descriptor.workflow_id !== workflowId || descriptor.run_id !== runId) {
        throw new ApiError(REASON_MESSAGES.workflow_result_invalid, 409, { code: 'workflow_result_invalid' });
    }
    return descriptor;
}

/** A run's completion time as the reader would say it: weekday, date and time. */
export function formatWorkflowRunTime(
    value: string | null | undefined,
    locale?: string | string[],
    timeZone?: string,
): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) {
        return '';
    }
    try {
        return new Intl.DateTimeFormat(locale, {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            ...(timeZone ? { timeZone } : {}),
        }).format(parsed);
    } catch {
        return '';
    }
}

/** The chip's sentence. The workflow name is user-authored and is only ever rendered as text. */
export function workflowResultChipLabel(
    descriptor: WorkflowResultDescriptor,
    locale?: string | string[],
    timeZone?: string,
): string {
    const time = formatWorkflowRunTime(descriptor.completed_at, locale, timeZone);
    const run = time ? `the ${descriptor.workflow_name} run of ${time}` : `the ${descriptor.workflow_name} run`;
    return `Answering from ${run} — not re-running the workflow`;
}

/** The run row fields Ask in chat depends on. */
export interface WorkflowRunForChat {
    id?: unknown;
    run_id?: unknown;
    status?: unknown;
    definition_version?: unknown;
    started_at?: unknown;
    completed_at?: unknown;
}

/** The id Ask in chat would name, or null when the row has no usable one. */
export function workflowRunChatId(run: WorkflowRunForChat): string | null {
    const id = run.id ?? run.run_id;
    return isWorkflowResultIdentifier(id) ? id : null;
}

/** Whether a run in this status finished with a result chat could answer from. */
export function isWorkflowResultReadableStatus(status: unknown): boolean {
    return typeof status === 'string' && READABLE_STATUSES.has(status);
}

/**
 * Whether a run history row offers Ask in chat.
 *
 * Personal workflows only (roadmap decision 3), finished runs whose result can be read, and
 * not structured (v3) runs, which the reader does not support yet. The server decides in the
 * end; this only keeps a button off rows it would certainly refuse.
 */
export function canAskAboutWorkflowRun(
    scope: { type: string },
    run: WorkflowRunForChat,
    enabled: boolean,
): boolean {
    return enabled && scope.type === 'personal' && workflowRunChatId(run) !== null &&
        isWorkflowResultReadableStatus(run.status) && run.definition_version !== 3;
}
