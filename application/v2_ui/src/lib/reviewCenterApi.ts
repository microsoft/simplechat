// reviewCenterApi.ts
// Every request the admin Review center makes.
//
// The Review center reads and writes through the same review APIs the classic Feedback Review
// and Safety Violations pages use, plus the dashboard, "select all matching" and bulk
// endpoints added for it. The server owns every decision: who may review, what a save does
// and whether a record changed underneath the reviewer.

import { ApiError, api } from './apiClient';
import type { ReviewSectionId } from './reviewAccess';
import {
    REVIEW_BULK_BATCH,
    chunkIds,
    feedbackFilterParams,
    safetyFilterParams,
    type FeedbackFilters,
    type FeedbackRecord,
    type ReviewBulkResponse,
    type ReviewBulkResult,
    type ReviewWindow,
    type SafetyFilters,
    type SafetyRecord,
} from './reviewCenter';

/** The server's code for a save refused because the record changed after it was opened. */
export const RECORD_CHANGED_CODE = 'record_changed';
/** The server's code for a violation locked by a remediation request still being decided. */
export const REMEDIATION_PENDING_CODE = 'remediation_pending';
/** The server's code for a save refused while another save is sending the same warning. */
export const WARNING_IN_PROGRESS_CODE = 'safety_warning_in_progress';
/** The server's code for a warning that was sent but could not be recorded on the violation. */
export const WARNING_NOT_RECORDED_CODE = 'safety_warning_not_recorded';
/** The server's code for an AI suggestion whose record changed after it was made. */
export const SUGGESTION_STALE_CODE = 'suggestion_stale';
/** The server's code for an AI suggestion already applied, dismissed or replaced. */
export const SUGGESTION_NOT_PENDING_CODE = 'suggestion_not_pending';

export function errorCode(error: unknown): string | null {
    if (!(error instanceof ApiError)) return null;
    const payload = error.payload as { code?: unknown } | null;
    return payload && typeof payload === 'object' && typeof payload.code === 'string' ? payload.code : null;
}

export function isRecordChanged(error: unknown): boolean {
    return errorCode(error) === RECORD_CHANGED_CODE;
}

/**
 * Whether the record must be read again before another save can succeed: it changed after
 * it was opened, a warning is being sent, a request now locks it, or the AI suggestion being
 * applied no longer fits it.
 */
export function needsReload(error: unknown): boolean {
    const code = errorCode(error);
    return code === RECORD_CHANGED_CODE || code === WARNING_IN_PROGRESS_CODE || code === REMEDIATION_PENDING_CODE
        || code === WARNING_NOT_RECORDED_CODE || code === SUGGESTION_STALE_CODE || code === SUGGESTION_NOT_PENDING_CODE;
}

export function errorText(error: unknown, fallback: string): string {
    return error instanceof Error && error.message ? error.message : fallback;
}

export interface ReviewPage<T> {
    items: T[];
    page: number;
    pageSize: number;
    total: number;
}

export interface MatchingIds {
    ids: string[];
    total: number;
    capped: boolean;
    cap: number;
}

export interface DailySeries {
    dates: string[];
    series: { key: string; counts: number[] }[];
}

export interface DashboardWindow {
    days: number;
    start_date: string;
    end_date: string;
}

export type BulkOperation =
    | { id: string; op: 'update'; changes: Record<string, unknown>; etag?: string; suggestion_id?: string }
    | { id: string; op: 'archive'; archived: boolean; etag?: string }
    | { id: string; op: 'delete'; etag?: string }
    | { id: string; op: 'dismiss_suggestion'; suggestion_id: string; etag?: string };

function pagedQuery(filters: URLSearchParams, page: number, pageSize: number): string {
    const params = new URLSearchParams(filters);
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
    return params.toString();
}

/**
 * Send operations in batches of at most 100, one batch after another, and return every
 * result in order. A batch that fails as a whole reports each of its operations as failed,
 * so the caller can still say what happened to everything it asked for.
 */
async function runBulk(
    path: string,
    operations: readonly BulkOperation[],
    onProgress?: (done: number, total: number) => void,
): Promise<ReviewBulkResult[]> {
    const results: ReviewBulkResult[] = [];
    let done = 0;
    onProgress?.(0, operations.length);
    for (const batch of chunkIds(operations, REVIEW_BULK_BATCH)) {
        try {
            const response = await api.post<ReviewBulkResponse>(path, { operations: batch });
            results.push(...(Array.isArray(response?.results) ? response.results : []));
        } catch (error) {
            const message = errorText(error, 'The change could not be made.');
            for (const operation of batch) {
                results.push({ id: operation.id, op: operation.op, ok: false, status: 0, error: message });
            }
        }
        done += batch.length;
        onProgress?.(done, operations.length);
    }
    return results;
}

/* -------------------------------------------------------------------------- */
/* Feedback                                                                    */
/* -------------------------------------------------------------------------- */

export interface FeedbackStats {
    total_count?: number;
    positive_count?: number;
    negative_count?: number;
    neutral_count?: number;
    acknowledged_count?: number;
    unacknowledged_count?: number;
    recent_30_day_count?: number;
    window?: DashboardWindow;
    received_count?: number;
    awaiting_review_count?: number;
    negative_count_in_window?: number;
    acknowledged_count_in_window?: number;
    acknowledgement_rate?: number | null;
    archived_count?: number;
    daily_by_rating?: DailySeries;
    /** Feedback received in the window, by the theme a reviewer gave it. */
    theme_mix?: { theme: string; count: number }[];
    unthemed_count_in_window?: number;
    oldest_awaiting?: {
        id: string;
        feedbackType?: string;
        timestamp?: string;
        userId?: string;
        userDisplayName?: string | null;
        promptExcerpt?: string;
    }[];
}

export async function fetchFeedbackPage(
    filters: FeedbackFilters,
    page: number,
    pageSize: number,
    signal?: AbortSignal,
): Promise<ReviewPage<FeedbackRecord>> {
    const response = await api.get<{
        feedback?: FeedbackRecord[];
        page?: number;
        page_size?: number;
        total_count?: number;
    }>(`/feedback/review?${pagedQuery(feedbackFilterParams(filters), page, pageSize)}`, signal);
    return {
        items: Array.isArray(response?.feedback) ? response.feedback : [],
        page: response?.page ?? page,
        pageSize: response?.page_size ?? pageSize,
        total: response?.total_count ?? 0,
    };
}

export function fetchFeedbackIds(filters: FeedbackFilters, signal?: AbortSignal): Promise<MatchingIds> {
    const query = feedbackFilterParams(filters).toString();
    return api.get<MatchingIds>(`/feedback/review/ids${query ? `?${query}` : ''}`, signal);
}

export function fetchFeedbackRecord(id: string, signal?: AbortSignal): Promise<FeedbackRecord> {
    return api.get<FeedbackRecord>(`/feedback/review/${encodeURIComponent(id)}`, signal);
}

export function fetchFeedbackStats(days: ReviewWindow, signal?: AbortSignal): Promise<FeedbackStats> {
    return api.get<FeedbackStats>(`/feedback/review/stats?${new URLSearchParams({ days })}`, signal);
}

export interface FeedbackReviewChanges {
    acknowledged?: boolean;
    analysisNotes?: string;
    responseToUser?: string;
    actionTaken?: string;
    /** One of FEEDBACK_THEMES, or '' to clear it. */
    theme?: string;
    notify_user?: boolean;
    etag?: string;
}

export function saveFeedbackReview(id: string, changes: FeedbackReviewChanges) {
    return api.patch<{ success?: boolean; etag?: string; notified?: boolean; notification_warning?: string }>(
        `/feedback/review/${encodeURIComponent(id)}`,
        changes,
    );
}

export function retestFeedbackPrompt(id: string, prompt: string) {
    return api.post<{ retestResponse?: string }>(`/feedback/retest/${encodeURIComponent(id)}`, { prompt });
}

export function bulkFeedback(operations: readonly BulkOperation[], onProgress?: (done: number, total: number) => void) {
    return runBulk('/feedback/review/bulk', operations, onProgress);
}

/* -------------------------------------------------------------------------- */
/* Safety                                                                      */
/* -------------------------------------------------------------------------- */

export interface SafetyStats {
    total_count?: number;
    new_count?: number;
    in_review_count?: number;
    resolved_count?: number;
    dismissed_count?: number;
    warn_user_count?: number;
    suspend_user_count?: number;
    escalate_count?: number;
    block_user_count?: number;
    none_action_count?: number;
    recent_30_day_count?: number;
    window?: DashboardWindow;
    received_count?: number;
    open_count?: number;
    pending_remediation_count?: number;
    restricted_user_count?: number | null;
    warnings_sent_count?: number;
    warnings_acknowledged_count?: number;
    warnings_pending_count?: number;
    unchecked_chat_count?: number | null;
    daily_by_category?: DailySeries;
    severity_mix?: { severity: number | null; count: number }[];
    action_mix?: { action: string; count: number }[];
    repeat_users?: { user_id: string; display_name?: string | null; email?: string | null; count: number }[];
}

export async function fetchSafetyPage(
    filters: SafetyFilters,
    page: number,
    pageSize: number,
    signal?: AbortSignal,
): Promise<ReviewPage<SafetyRecord>> {
    const response = await api.get<{
        logs?: SafetyRecord[];
        page?: number;
        page_size?: number;
        total_count?: number;
    }>(`/api/safety/logs?${pagedQuery(safetyFilterParams(filters), page, pageSize)}`, signal);
    return {
        items: Array.isArray(response?.logs) ? response.logs : [],
        page: response?.page ?? page,
        pageSize: response?.page_size ?? pageSize,
        total: response?.total_count ?? 0,
    };
}

export function fetchSafetyIds(filters: SafetyFilters, signal?: AbortSignal): Promise<MatchingIds> {
    const query = safetyFilterParams(filters).toString();
    return api.get<MatchingIds>(`/api/safety/logs/ids${query ? `?${query}` : ''}`, signal);
}

export function fetchSafetyRecord(id: string, signal?: AbortSignal): Promise<SafetyRecord> {
    return api.get<SafetyRecord>(`/api/safety/logs/${encodeURIComponent(id)}`, signal);
}

export function fetchSafetyStats(days: ReviewWindow, signal?: AbortSignal): Promise<SafetyStats> {
    return api.get<SafetyStats>(`/api/safety/logs/stats?${new URLSearchParams({ days })}`, signal);
}

export interface SafetyReviewChanges {
    status?: string;
    action?: string;
    notes?: string;
    notification_title?: string;
    notification_message?: string;
    datetime_to_allow?: string;
    reissue?: boolean;
    etag?: string;
}

export interface SafetyReviewResult {
    message?: string;
    approval_required?: boolean;
    approval_id?: string | null;
    warning_already_sent?: boolean;
    remediation_already_applied?: boolean;
    remediation_unchanged?: boolean;
    remediation_status?: string | null;
    audit_warning?: string;
}

export function saveSafetyReview(id: string, changes: SafetyReviewChanges) {
    return api.patch<SafetyReviewResult>(`/api/safety/logs/${encodeURIComponent(id)}`, changes);
}

export function bulkSafety(operations: readonly BulkOperation[], onProgress?: (done: number, total: number) => void) {
    return runBulk('/api/safety/logs/bulk', operations, onProgress);
}

/* -------------------------------------------------------------------------- */
/* AI suggestions                                                              */
/* -------------------------------------------------------------------------- */

/** One page of the AI suggestions queue: records whose suggestion still waits for a reviewer. */
export async function fetchSuggestionsPage<T>(
    section: ReviewSectionId,
    page: number,
    pageSize: number,
    signal?: AbortSignal,
): Promise<ReviewPage<T>> {
    const filters = new URLSearchParams({ ai: 'pending', archive: 'all' });
    if (section === 'safety') {
        const response = await api.get<{ logs?: T[]; page?: number; page_size?: number; total_count?: number }>(
            `/api/safety/logs?${pagedQuery(filters, page, pageSize)}`,
            signal,
        );
        return {
            items: Array.isArray(response?.logs) ? response.logs : [],
            page: response?.page ?? page,
            pageSize: response?.page_size ?? pageSize,
            total: response?.total_count ?? 0,
        };
    }
    const response = await api.get<{ feedback?: T[]; page?: number; page_size?: number; total_count?: number }>(
        `/feedback/review?${pagedQuery(filters, page, pageSize)}`,
        signal,
    );
    return {
        items: Array.isArray(response?.feedback) ? response.feedback : [],
        page: response?.page ?? page,
        pageSize: response?.page_size ?? pageSize,
        total: response?.total_count ?? 0,
    };
}

/**
 * Save an editor's review as the application of the record's AI suggestion, so the suggestion
 * is marked applied and credited in the audit log. The bulk route runs the same save as PATCH;
 * a refusal is thrown as the PATCH would throw it, with the server's code.
 */
export async function saveReviewWithSuggestion(
    section: ReviewSectionId,
    id: string,
    changes: Record<string, unknown>,
    suggestionId: string,
): Promise<ReviewBulkResult> {
    const { etag, ...rest } = changes;
    const operation: BulkOperation = {
        id,
        op: 'update',
        changes: rest,
        suggestion_id: suggestionId,
        ...(typeof etag === 'string' && etag ? { etag } : {}),
    };
    const path = section === 'safety' ? '/api/safety/logs/bulk' : '/feedback/review/bulk';
    const response = await api.post<ReviewBulkResponse>(path, { operations: [operation] });
    const result = Array.isArray(response?.results) ? response.results[0] : undefined;
    if (!result || result.id !== id) throw new ApiError('The review could not be saved.', 0, null);
    if (!result.ok) {
        const message = result.error || result.message || 'The review could not be saved.';
        throw new ApiError(message, result.status, { error: message, code: result.code });
    }
    return result;
}

/* -------------------------------------------------------------------------- */
/* Unchecked chat content                                                      */
/* -------------------------------------------------------------------------- */

export interface UncheckedChatItem {
    source: string;
    conversation_id: string;
    message_id: string;
    role?: string;
    timestamp?: string;
    etag?: string;
    check?: {
        checkpoint?: string;
        attempted_at?: string;
        status?: string;
        scanners?: { scanner?: string; complete?: boolean; error_code?: string }[];
    };
}

export interface UncheckedChatFilters {
    source: 'all' | 'chat' | 'shared';
    checkpoint: '' | 'chat_input' | 'chat_output';
    scanner: '' | 'content_screening' | 'content_safety';
}

export const DEFAULT_UNCHECKED_FILTERS: UncheckedChatFilters = { source: 'all', checkpoint: '', scanner: '' };

export function uncheckedKey(item: Pick<UncheckedChatItem, 'source' | 'conversation_id' | 'message_id'>): string {
    return `${item.source}:${item.conversation_id}:${item.message_id}`;
}

export async function fetchUncheckedChat(
    filters: UncheckedChatFilters,
    continuation: string | null,
    signal?: AbortSignal,
): Promise<{ items: UncheckedChatItem[]; continuation: string | null }> {
    const params = new URLSearchParams({ source: filters.source, page_size: '25' });
    if (filters.checkpoint) params.set('checkpoint', filters.checkpoint);
    if (filters.scanner) params.set('scanner', filters.scanner);
    if (continuation) params.set('continuation', continuation);
    const response = await api.get<{ items?: UncheckedChatItem[]; continuation?: string | null }>(
        `/api/safety/chat-checks?${params}`,
        signal,
    );
    if (!Array.isArray(response?.items)) throw new Error('The unchecked-message response was invalid.');
    return { items: response.items, continuation: response.continuation ?? null };
}

export interface RecheckOutcome {
    removed?: boolean;
    check?: { status?: string };
}

export function recheckChatMessage(item: UncheckedChatItem) {
    return api.post<RecheckOutcome>('/api/safety/chat-checks/recheck', {
        source: item.source,
        conversation_id: item.conversation_id,
        message_id: item.message_id,
        etag: item.etag,
    });
}

/** What a recheck did, in a sentence the reviewer can act on. */
export function recheckOutcomeText(outcome: RecheckOutcome): { message: string; warning: boolean } {
    if (outcome.removed) return { message: 'The AI reply was removed from saved chat and its shared copies.', warning: false };
    if (outcome.check?.status === 'passed') return { message: 'The message passed its required checks.', warning: false };
    if (outcome.check?.status === 'findings') {
        return {
            message: 'The submitted message was flagged for review. Earlier model calls and actions have not been undone.',
            warning: true,
        };
    }
    return {
        message: 'The check could not finish. The message remains marked not checked and can be retried.',
        warning: true,
    };
}
