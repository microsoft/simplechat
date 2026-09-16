// contentScreeningApi.ts
// Contract published in route_backend_content_screening.py's API docstring.

import { ApiError, api, apiUrl, CREDENTIALS_MODE } from './apiClient';
import type { ScreeningState } from './contentScreening';
import type { ScreeningBaselineSummary, ScreeningModelSelection, ScreeningPolicy } from './contentScreeningPolicy';
import type { ScreeningEdit, ScreeningUnit, ScreeningUnitView } from './contentScreeningReview';

export type ScreeningScopeType = 'global' | 'personal' | 'group' | 'public';

export interface ScreeningScope {
    scope_type: ScreeningScopeType;
    scope_id: string;
}

export interface ScreeningTemplatesResponse {
    rules: Record<string, unknown>;
    packs: Record<string, unknown>;
    ai: Record<string, unknown>;
}

export interface ScreeningConfiguration {
    enabled: boolean;
    enhanced_citations_enabled: boolean;
    can_manage_global: boolean;
    can_scan_all: boolean;
    templates: ScreeningTemplatesResponse;
}

export interface ScreeningPolicyResponse extends ScreeningScope {
    policy: ScreeningPolicy;
    etag: string | null;
    inherited_summary: ScreeningBaselineSummary | null;
    allowed_models: ScreeningModelSelection[];
    templates: ScreeningTemplatesResponse;
}

export interface ScreeningPage<T> {
    items: T[];
    continuation: string | null;
    total?: number;
}

export interface ScreeningEvidenceWindow extends ScreeningUnit {
    text_offset: number;
    text_total: number;
}

export interface ScreeningSampleResult {
    status: string;
    complete: boolean;
    finding_count: number;
    findings: Array<Record<string, unknown>>;
    findings_truncated: boolean;
    error_code: string | null;
}

export type ScreeningDecision = 'approve_with_flags' | 'approve_clean' | 'reject' | 'delete' | 'retry_publication';
export type ScreeningJobAction = 'resume' | 'cancel' | 'retry';
export type ScreeningAttachmentKind = 'original' | 'clean';
export type ScreeningReviewAction = ScreeningDecision | 'preview' | 'remediate' | 'download_original' | 'download_clean';

export interface ScreeningAttachment {
    url: string;
    file_name: string;
}

/** Additional metadata is server-allowlisted; evidence has separate authorized routes. */
export interface ScreeningReviewMetadata {
    id: string;
    subject: ScreeningScope & {
        document_id: string;
        source_revision?: string | number;
    };
    state: ScreeningState;
    etag: string;
    content_fingerprint: string;
    policy_fingerprint: string;
    outcome: 'pass' | 'findings' | 'incomplete' | 'error' | null;
    coverage: {
        complete: boolean;
        units_total: number;
        [key: string]: unknown;
    };
    finding_count: number;
    review_required: boolean;
    candidate_of: string | null;
    original_retained: boolean;
    sanitized: boolean;
    evidence: { units_available: boolean; findings_available: boolean };
    downloads: Record<ScreeningAttachmentKind, ScreeningAttachment | null>;
    allowed_actions: ScreeningReviewAction[];
    warning: string | null;
    decision?: { action: string; actor_id: string; reason: string; decided_at: string } | null;
}

export interface ScreeningJob {
    id: string;
    state: string;
    counters: Record<string, number>;
    allowed_actions: ScreeningJobAction[];
    enumeration_complete: boolean;
    cancel_requested: boolean;
}

interface ScreeningWireEditTarget {
    unit_id: string;
    content_hash: string;
}

export type ScreeningWireEdit =
    | (ScreeningWireEditTarget & { action: 'remove_unit' })
    | (ScreeningWireEditTarget & { action: 'remove_span'; start: number; end: number })
    | (ScreeningWireEditTarget & { action: 'replace_cell'; text: string });

export interface ScreeningCandidatePreview {
    units: ScreeningUnit[];
    total_units: number;
    preview_truncated: boolean;
    content_fingerprint: string;
    removed_unit_ids: string[];
    removed_unit_count: number;
    warnings: string[];
}

export function screeningWireEdits(
    edits: ScreeningEdit[], units: ScreeningUnitView[], completeUnitInventory: boolean,
): ScreeningWireEdit[] {
    const operations: ScreeningWireEdit[] = [];
    const removed = new Set<string>();
    for (const edit of edits) {
        if (edit.type === 'remove_page') {
            if (!completeUnitInventory) {
                throw new Error('Load the complete unit inventory before removing an extracted page.');
            }
            for (const unit of units.filter((item) => item.location.physicalPage === edit.page)) {
                if (!removed.has(unit.unit_id)) {
                    operations.push({ action: 'remove_unit', unit_id: unit.unit_id, content_hash: unit.content_hash });
                    removed.add(unit.unit_id);
                }
            }
        } else {
            const target = { unit_id: edit.unit_id, content_hash: edit.content_hash };
            if (edit.type === 'remove_unit') {
                if (!removed.has(edit.unit_id)) {
                    operations.push({ ...target, action: 'remove_unit' });
                    removed.add(edit.unit_id);
                }
            } else if (edit.type === 'remove_span') {
                operations.push({ ...target, action: 'remove_span', start: edit.start, end: edit.end });
            } else {
                operations.push({
                    ...target, action: 'replace_cell',
                    text: edit.type === 'clear_cell' ? '' : edit.replacement,
                });
            }
        }
    }
    return operations.filter((operation) => operation.action === 'remove_unit' || !removed.has(operation.unit_id));
}

const BASE = '/api/content-screening';
const scopePath = (scope: ScreeningScope) =>
    `${encodeURIComponent(scope.scope_type)}/${encodeURIComponent(scope.scope_id)}`;
const reviewPath = (scanId: string) => `${BASE}/reviews/${encodeURIComponent(scanId)}`;

export function screeningAttachment(
    review: ScreeningReviewMetadata, kind: ScreeningAttachmentKind,
): ScreeningAttachment | null {
    const attachment = review.downloads?.[kind];
    if (!review.id || !review.allowed_actions?.includes(`download_${kind}`)
        || attachment?.url !== `${reviewPath(review.id)}/downloads/${kind}`
        || typeof attachment.file_name !== 'string' || !attachment.file_name
        || review.state === 'deleting' || review.state === 'deleted'
        || kind === 'clean' && review.state !== 'cleared' && review.state !== 'approved_with_flags') {
        return null;
    }
    return { url: attachment.url, file_name: attachment.file_name };
}

export async function fetchScreeningAttachment(
    review: ScreeningReviewMetadata, kind: ScreeningAttachmentKind,
): Promise<{ content: ArrayBuffer; fileName: string }> {
    const attachment = screeningAttachment(review, kind);
    if (!attachment) throw new ApiError('This review attachment is not authorized.', 403, null);
    const response = await fetch(apiUrl(attachment.url), {
        credentials: CREDENTIALS_MODE, cache: 'no-store', redirect: 'manual',
        headers: { Accept: 'application/octet-stream' },
    });
    if (response.redirected || response.type === 'opaqueredirect') {
        throw new ApiError('Sign in again before downloading protected evidence.', 401, null);
    }
    if (!response.ok) {
        throw new ApiError('The review attachment is unavailable. Refresh before trying again.', response.status, null);
    }
    if (!/^attachment(?:;|$)/i.test(response.headers.get('Content-Disposition') ?? '')
        || response.headers.get('X-Content-Type-Options')?.toLowerCase() !== 'nosniff'
        || !/\bno-store\b/i.test(response.headers.get('Cache-Control') ?? '')) {
        throw new ApiError('A safe attachment response could not be verified.', 503, null);
    }
    return {
        content: await response.arrayBuffer(),
        fileName: attachment.file_name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_'),
    };
}

function pagingParams(continuation?: string | null) {
    const params = new URLSearchParams({ page_size: '100' });
    if (continuation) {
        params.set('continuation', continuation);
    }
    return params;
}

export const fetchScreeningConfiguration = (signal?: AbortSignal) =>
    api.get<ScreeningConfiguration>(`${BASE}/configuration`, signal);

export const fetchScreeningPolicy = (scope: ScreeningScope, signal?: AbortSignal) =>
    api.get<ScreeningPolicyResponse>(`${BASE}/policies/${scopePath(scope)}`, signal);

export const saveScreeningPolicy = (scope: ScreeningScope, policy: ScreeningPolicy, etag: string | null) =>
    api.put<ScreeningPolicyResponse>(`${BASE}/policies/${scopePath(scope)}`, { policy, etag });

export const testScreeningPolicy = (scope: ScreeningScope, policy: ScreeningPolicy, sampleText: string) =>
    api.post<ScreeningSampleResult>(`${BASE}/policies/${scopePath(scope)}/test`, { policy, sample_text: sampleText });

export function fetchScreeningReviews(
    scope?: ScreeningScope,
    state: 'pending' | 'resolved' | 'all' = 'pending',
    continuation?: string | null,
    signal?: AbortSignal,
) {
    const params = pagingParams(continuation);
    params.set('state', state);
    if (scope) {
        params.set('scope_type', scope.scope_type);
        params.set('scope_id', scope.scope_id);
    }
    return api.get<ScreeningPage<ScreeningReviewMetadata>>(`${BASE}/reviews?${params}`, signal);
}

export const fetchScreeningReview = (scanId: string, signal?: AbortSignal) =>
    api.get<ScreeningReviewMetadata>(reviewPath(scanId), signal);

export function fetchScreeningUnits(scanId: string, continuation?: string | null, signal?: AbortSignal) {
    return api.get<ScreeningPage<ScreeningEvidenceWindow>>(
        `${reviewPath(scanId)}/units?${pagingParams(continuation)}`, signal,
    );
}

export function fetchScreeningFindings(scanId: string, continuation?: string | null, signal?: AbortSignal) {
    return api.get<ScreeningPage<Record<string, unknown>>>(
        `${reviewPath(scanId)}/findings?${pagingParams(continuation)}`, signal,
    );
}

export const previewScreeningCandidate = (scanId: string, etag: string, edits: ScreeningWireEdit[]) =>
    api.post<ScreeningCandidatePreview>(`${reviewPath(scanId)}/preview`, { etag, edits });

export const remediateScreeningReview = (scanId: string, etag: string, edits: ScreeningWireEdit[]) =>
    api.post<ScreeningReviewMetadata>(`${reviewPath(scanId)}/remediate`, { etag, edits });

export const decideScreeningReview = (
    scanId: string, etag: string, action: ScreeningDecision, reason: string,
) => api.post<ScreeningReviewMetadata>(`${reviewPath(scanId)}/decision`, {
    etag,
    action,
    reason,
    ...(action === 'approve_with_flags' ? { acknowledge_flags: true } : {}),
});

export const startScreeningScan = (scope: ScreeningScope, documentIds?: string[]) =>
    api.post<ScreeningJob>(`${BASE}/scans`, {
        ...scope,
        ...(documentIds?.length ? { document_ids: documentIds } : {}),
    });

export const startAllWorkspaceScreeningScan = () =>
    api.post<ScreeningJob>(`${BASE}/scans`, { all_workspaces: true });

export function fetchScreeningScans(scope?: ScreeningScope, continuation?: string | null, signal?: AbortSignal) {
    const params = pagingParams(continuation);
    if (scope && scope.scope_type !== 'global') {
        params.set('scope_type', scope.scope_type);
        params.set('scope_id', scope.scope_id);
    }
    return api.get<ScreeningPage<ScreeningJob>>(`${BASE}/scans?${params}`, signal);
}

export const fetchScreeningScan = (jobId: string, signal?: AbortSignal) =>
    api.get<ScreeningJob>(`${BASE}/scans/${encodeURIComponent(jobId)}`, signal);

export const changeScreeningScan = (jobId: string, action: ScreeningJobAction) =>
    api.post<ScreeningJob>(`${BASE}/scans/${encodeURIComponent(jobId)}/actions`, { action });

export function isStaleScreeningError(error: unknown): boolean {
    return error instanceof ApiError && (error.status === 409 || error.status === 412);
}

export function screeningErrorMessage(error: unknown): string {
    if (isStaleScreeningError(error)) {
        return 'This screening revision changed. Refresh the review or policy before trying again.';
    }
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        return 'You are not authorized for this screening action. Your workspace access may have changed.';
    }
    return error instanceof ApiError ? error.message : 'Content screening is unavailable. Refresh and try again.';
}
