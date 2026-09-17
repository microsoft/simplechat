// savedAnalysis.ts
// The public, snapshot-bound Analyze contract. Store references never reach the composer.

import { ApiError } from './apiClient';
import type {
    AnalysisResultContext,
    AnalysisValidationStatus,
    ChatMessage,
    ChatStreamRequest,
    SavedAnalysisDescriptor,
    SavedAnalysisPage,
    SavedAnalysisRecord,
} from './types';

export const ANALYSIS_PAGE_SIZE = 25;
export const ANALYSIS_CONTEXT_NOTICE =
    'Explaining the saved analysis — not running a new pass over the original sources.';

const validationNotices: Record<AnalysisValidationStatus, string> = {
    valid: 'Structural checks passed. Findings are model judgments, not independent factual verification or an exhaustive list of every possible issue.',
    partial: 'Partial analysis: accepted findings only. Counts and totals describe this saved subset; some work or checks remain unresolved.',
    invalid: 'Validation failed. These saved findings are not a validated final result.',
    pending: 'Validation pending. The saved findings are not yet a validated final result.',
    not_validated: 'Not validated. No completed validation is claimed for these saved findings.',
};

function object(value: unknown): value is Record<string, unknown> {
    return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function count(value: unknown): value is number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function validationStatus(value: unknown): value is AnalysisValidationStatus {
    return typeof value === 'string' && Object.hasOwn(validationNotices, value);
}

function analysisRecord(value: unknown): value is SavedAnalysisRecord {
    return object(value) && typeof value.record_id === 'string' &&
        typeof value.document_id === 'string' && object(value.source) &&
        (value.source.file_name === undefined || typeof value.source.file_name === 'string') &&
        object(value.values) && Array.isArray(value.evidence_refs) &&
        value.evidence_refs.every((id) => typeof id === 'string');
}

export function readSavedAnalysis(metadata: unknown): SavedAnalysisDescriptor | null {
    const value = object(metadata) ? metadata.saved_analysis : null;
    if (!object(value) || value.version !== 'analyze-final-v1' ||
        typeof value.conversation_id !== 'string' || !value.conversation_id.trim() ||
        typeof value.message_id !== 'string' || !value.message_id.trim() ||
        typeof value.result_sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(value.result_sha256) ||
        !count(value.record_count) || !count(value.source_count) ||
        !validationStatus(value.validation_status)) {
        return null;
    }
    return {
        version: 'analyze-final-v1',
        conversation_id: value.conversation_id,
        message_id: value.message_id,
        result_sha256: value.result_sha256,
        record_count: value.record_count,
        source_count: value.source_count,
        validation_status: value.validation_status,
        available: value.available !== false,
    };
}

export function analysisResultContext(value: AnalysisResultContext): AnalysisResultContext {
    return {
        conversation_id: value.conversation_id,
        message_id: value.message_id,
        result_sha256: value.result_sha256,
    };
}

export function sameAnalysis(
    left: AnalysisResultContext | null,
    right: AnalysisResultContext | null,
): boolean {
    return Boolean(left && right && left.conversation_id === right.conversation_id &&
        left.message_id === right.message_id && left.result_sha256 === right.result_sha256);
}

export function analysisValidationNotice(status: AnalysisValidationStatus): string {
    return validationNotices[status] ?? validationNotices.not_validated;
}

export function analysisNotices(value: unknown): string[] {
    const items = Array.isArray(value) ? value : [value];
    return items.flatMap((item) => {
        const message = typeof item === 'string' ? item : object(item) ? item.message : null;
        return typeof message === 'string' && message.trim() ? [message] : [];
    });
}

export function analysisValue(value: unknown): string {
    if (value === null || value === undefined) {
        return 'Not provided';
    }
    return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}

export function analysisUnavailableMessage(status?: number): string {
    if (status === 409) {
        return 'Saved analysis is stale or has changed. Reopen the conversation to use its current saved result.';
    }
    if (status === 401) {
        return 'Saved analysis unavailable. Sign in again to check access.';
    }
    return 'Saved analysis unavailable. It may have been removed, or access to a contributing source may have changed.';
}

export function isAnalysisUnavailable(error: unknown): error is ApiError {
    return error instanceof ApiError && [401, 403, 404, 409].includes(error.status);
}

export function validateAnalysisPage(
    value: unknown,
    descriptor: SavedAnalysisDescriptor,
    offset: number,
): SavedAnalysisPage {
    if (!object(value) || value.result_sha256 !== descriptor.result_sha256 ||
        value.offset !== offset || !count(value.total_records) ||
        value.total_records !== descriptor.record_count || !count(value.source_count) ||
        !Array.isArray(value.records) || value.records.length > ANALYSIS_PAGE_SIZE ||
        !value.records.every(analysisRecord) ||
        offset + value.records.length > value.total_records ||
        (offset < value.total_records && value.records.length === 0) ||
        (value.next_offset !== null && (!count(value.next_offset) ||
            (value.next_offset !== offset + value.records.length || value.next_offset >= value.total_records))) ||
        (value.next_offset === null && offset + value.records.length < value.total_records) ||
        !object(value.validation) || !validationStatus(value.validation.status)) {
        throw new ApiError('Saved analysis response does not match this result.', 409, null);
    }
    return {
        records: value.records,
        total_records: value.total_records,
        offset,
        next_offset: value.next_offset,
        result_sha256: value.result_sha256,
        source_count: value.source_count,
        validation: {
            status: value.validation.status,
            limitations: value.validation.limitations,
            issues: value.validation.issues,
        },
    };
}

export function latestSavedAnalysis(messages: ChatMessage[]): SavedAnalysisDescriptor | null {
    const message = [...messages].reverse().find((item) =>
        (item.role === 'assistant' || item.role === 'user') && !item.metadata?.is_deleted,
    );
    if (message?.role !== 'assistant' || message.metadata?.masked ||
        (Array.isArray(message.metadata?.masked_ranges) && message.metadata.masked_ranges.length > 0)) {
        return null;
    }
    const descriptor = readSavedAnalysis(message.metadata);
    return descriptor?.available !== false ? descriptor : null;
}

export function applySavedAnalysisContext(
    request: ChatStreamRequest,
    context: AnalysisResultContext | null,
): ChatStreamRequest {
    if (!context || context.conversation_id !== request.conversation_id) {
        return request;
    }
    const result: ChatStreamRequest = {
        ...request,
        analysis_result_context: analysisResultContext(context),
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
    for (const key of ['document_action', 'analyze', 'document_filter_mode', 'orchestration', 'orchestration_context']) {
        delete result[key];
    }
    return result;
}
