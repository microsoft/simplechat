// approvalsApi.ts
// Every request the V2 Approvals page makes, and the labels it shows for them.
//
// The page brings four classic surfaces together: control-center approval requests (which
// include Microsoft 365 data-user approvals), outgoing Microsoft 365 actions, paused
// Microsoft 365 requests, and agent template submissions. The server owns every decision;
// nothing here infers permission. `can_approve` / `can_deny` / `can_cancel` come from the
// server and are only used to decide which buttons to offer.

import { ApiError, api, request } from './apiClient';

/* -------------------------------------------------------------------------- */
/* Generic approval requests                                                   */
/* -------------------------------------------------------------------------- */

export type ApprovalStatus = 'pending' | 'approved' | 'denied' | 'executed' | string;
export type ApprovalStatusFilter = 'pending' | 'all' | 'approved' | 'denied' | 'executed';

export interface ApprovalRequest {
    id: string;
    group_id?: string;
    request_type: string;
    status: ApprovalStatus;
    group_name?: string;
    requester_id?: string;
    requester_name?: string;
    requester_email?: string;
    reason?: string;
    created_at?: string;
    expires_at?: string;
    approved_by_name?: string;
    approved_by_email?: string;
    approved_at?: string;
    approval_comment?: string;
    execution_result?: unknown;
    auto_denied?: boolean;
    metadata?: Record<string, unknown>;
    can_approve?: boolean;
    can_deny?: boolean;
    approval_scope?: string;
    context?: Record<string, unknown>;
}

interface ApprovalListResponse {
    approvals?: ApprovalRequest[];
    total_count?: number;
    total_pages?: number;
}

export const GROUP_REQUEST_TYPES = [
    'take_ownership',
    'transfer_ownership',
    'delete_documents',
    'delete_group',
    'delete_user_documents',
] as const;

/** Warn, suspend and block requests raised from safety violation reviews. */
export const SAFETY_REMEDIATION_TYPES = ['warn_user', 'suspend_user', 'block_user'] as const;

export const M365_REQUEST_TYPES = ['m365_source_sharing', 'm365_extended_analysis', 'm365_workflow_run_as'] as const;
export type M365RequestType = (typeof M365_REQUEST_TYPES)[number];

export const CONTENT_SCREENING_TYPE = 'content_screening_review';

export const REQUEST_TYPE_LABELS: Record<string, string> = {
    take_ownership: 'Take Ownership',
    transfer_ownership: 'Transfer Ownership',
    delete_documents: 'Delete All Documents',
    delete_group: 'Delete Entire Group',
    delete_user_documents: 'Delete User Documents',
    warn_user: 'Warn User',
    suspend_user: 'Suspend User',
    block_user: 'Block User',
    content_screening_review: 'Content Screening',
    m365_source_sharing: 'Share Microsoft 365 evidence',
    m365_extended_analysis: 'Extended file analysis',
    m365_workflow_run_as: 'Workflow Run as authorization',
};

export function requestTypeLabel(type: string): string {
    return REQUEST_TYPE_LABELS[type] ?? type.replace(/_/g, ' ');
}

export function isM365RequestType(type: string): type is M365RequestType {
    return (M365_REQUEST_TYPES as readonly string[]).includes(type);
}

/** Page size used when fetching the list. The server filters in memory, so a larger page is cheap. */
const LIST_PAGE_SIZE = 200;
/** A ceiling so a runaway count cannot loop forever. */
const LIST_MAX_PAGES = 10;

/**
 * Every approval request the caller can see for a status.
 *
 * The server accepts one `action_type` at a time and ignores `search`, but it already reads
 * every record before it paginates. Fetching the visible set once and filtering on the
 * client lets a category span several request types without one request per type.
 */
export async function fetchApprovalRequests(
    status: ApprovalStatusFilter,
    signal?: AbortSignal,
): Promise<ApprovalRequest[]> {
    const results: ApprovalRequest[] = [];
    for (let page = 1; page <= LIST_MAX_PAGES; page += 1) {
        const params = new URLSearchParams({
            page: String(page),
            page_size: String(LIST_PAGE_SIZE),
            status,
            action_type: 'all',
        });
        const data = await api.get<ApprovalListResponse>(`/api/approvals?${params.toString()}`, signal);
        results.push(...(Array.isArray(data.approvals) ? data.approvals : []));
        if (!data.total_pages || page >= data.total_pages) break;
    }
    return results;
}

function groupQuery(groupId?: string): string {
    return groupId ? `?${new URLSearchParams({ group_id: groupId }).toString()}` : '';
}

export async function fetchApprovalRequest(id: string, groupId?: string, signal?: AbortSignal): Promise<ApprovalRequest> {
    const data = await api.get<{ approval?: ApprovalRequest } & Partial<ApprovalRequest>>(
        `/api/approvals/${encodeURIComponent(id)}${groupQuery(groupId)}`,
        signal,
    );
    const approval = (data.approval ?? data) as ApprovalRequest;
    if (!approval || typeof approval.id !== 'string') {
        throw new Error('The approval request could not be loaded.');
    }
    return approval;
}

export function approveApprovalRequest(id: string, groupId: string | undefined, comment: string) {
    return api.post<unknown>(`/api/approvals/${encodeURIComponent(id)}/approve`, {
        group_id: groupId,
        comment: comment.trim() || null,
    });
}

export interface ApprovalStats {
    window?: { days: number };
    waiting_on_me?: number;
    my_pending_requests?: number;
    expiring_within_24h?: number;
    pending_visible?: number;
    decided_in_window?: Partial<Record<'approved' | 'denied' | 'executed' | 'failed' | 'expired', number>>;
    pending_by_type?: { request_type: string; count: number }[];
    oldest_actionable?: {
        id: string;
        group_id?: string;
        request_type: string;
        group_name?: string;
        created_at?: string;
        expires_at?: string;
    }[];
}

/** What the Approvals dashboard counts: only requests the caller can see, over the last `days`. */
export function fetchApprovalStats(days: string, signal?: AbortSignal) {
    return api.get<ApprovalStats>(`/api/approvals/stats?${new URLSearchParams({ days }).toString()}`, signal);
}

export function denyApprovalRequest(id: string, groupId: string | undefined, comment: string) {
    return api.post<unknown>(`/api/approvals/${encodeURIComponent(id)}/deny`, {
        group_id: groupId,
        comment: comment.trim(),
    });
}

/**
 * The Content Review link for a screening request, reduced to the parameters it reads.
 *
 * `metadata.review_url` is server data, so only a same-origin `/content-review` path is
 * trusted, and only its three known parameters are carried into the V2 route.
 */
export function contentReviewPath(approval: ApprovalRequest): string | null {
    const raw = approval.metadata?.review_url;
    if (typeof raw !== 'string' || !raw.trim()) return null;
    let url: URL;
    try {
        url = new URL(raw, window.location.origin);
    } catch {
        return null;
    }
    if (url.origin !== window.location.origin || url.pathname !== '/content-review') return null;
    const params = new URLSearchParams();
    for (const key of ['scope_type', 'scope_id', 'scan_id']) {
        const value = url.searchParams.get(key);
        if (value) params.set(key, value);
    }
    const query = params.toString();
    return query ? `/content-review?${query}` : '/content-review';
}

/* -------------------------------------------------------------------------- */
/* Microsoft 365 requests (CSRF-protected)                                     */
/* -------------------------------------------------------------------------- */

let m365CsrfToken: string | null = null;
let m365CsrfRefresh: Promise<unknown> | null = null;

function rememberCsrf(payload: unknown) {
    const token = (payload as { csrf_token?: unknown } | null)?.csrf_token;
    if (typeof token === 'string' && token.length >= 32) m365CsrfToken = token;
}

async function ensureCsrf(): Promise<void> {
    if (m365CsrfToken) return;
    await refreshCsrf();
}

function refreshCsrf(): Promise<unknown> {
    m365CsrfRefresh =
        m365CsrfRefresh ??
        request<unknown>('/api/m365/preferences')
            .then(rememberCsrf)
            .finally(() => {
                m365CsrfRefresh = null;
            });
    return m365CsrfRefresh;
}

/**
 * A Microsoft 365 API call carrying the session's CSRF token.
 *
 * Mirrors the classic `requestJson`: a refused token is refreshed once and the call
 * retried, and a `success: false` body is treated as a failure even on a 2xx.
 */
export async function m365Request<T>(
    path: string,
    options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
    retried = false,
): Promise<T> {
    const method = options.method ?? 'GET';
    if (method !== 'GET') await ensureCsrf();
    try {
        const data = await request<T>(path, {
            ...options,
            method,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                ...(m365CsrfToken ? { 'X-M365-CSRF-Token': m365CsrfToken } : {}),
            },
        });
        if ((data as { success?: unknown } | null)?.success === false) {
            const message = (data as { message?: unknown }).message;
            throw new ApiError(
                typeof message === 'string' && message ? message : 'The Microsoft 365 request could not be completed.',
                400,
                data,
            );
        }
        rememberCsrf(data);
        return data;
    } catch (error) {
        const code = error instanceof ApiError ? (error.payload as { error?: unknown } | null)?.error : undefined;
        if (!retried && method !== 'GET' && error instanceof ApiError && error.status === 403 && code === 'm365_csrf_invalid') {
            m365CsrfToken = null;
            await refreshCsrf();
            return m365Request<T>(path, options, true);
        }
        throw error;
    }
}

/** The machine code on a failed Microsoft 365 response, if it has one. */
export function m365ErrorPayload(error: unknown): Record<string, unknown> {
    if (error instanceof ApiError && error.payload && typeof error.payload === 'object') {
        return error.payload as Record<string, unknown>;
    }
    return {};
}

/* Data-user approvals ------------------------------------------------------- */

export type M365Source = 'calendar' | 'email' | 'onedrive' | 'spo';
export type SharingDuration = 'no' | 'request' | 'today' | 'always';

export interface M365Approval extends ApprovalRequest {
    request_type: M365RequestType;
    approval_scope: 'user';
    execution_status?: string;
    self_authored?: boolean;
    decisions?: Record<string, { duration?: string; expires_at?: string }>;
    analysis_choice?: string;
    sources?: Record<string, { allowed_durations?: string[]; maximum_sharing_acknowledgement?: string }>;
    proposal?: Record<string, unknown>;
    binding?: { review?: Record<string, unknown> };
}

export const M365_SOURCE_LABELS: Record<string, string> = {
    calendar: 'Calendar',
    email: 'Email',
    onedrive: 'OneDrive',
    spo: 'SharePoint Online (SPO)',
};

export const SHARING_DURATION_LABELS: Record<SharingDuration, string> = {
    no: 'No',
    request: 'Allow this request',
    today: 'Allow for today',
    always: 'Always allow',
};

export const ANALYSIS_CHOICE_LABELS: Record<string, string> = {
    request: 'Analyze more for this request',
    always: 'Always allow deeper analysis',
    fast: 'Use a faster answer',
};

export const RUN_AS_REVIEW_LABELS: Record<string, string> = {
    instructions: 'Instructions',
    capabilities: 'Capabilities',
    runtime_inputs: 'Accepted runtime inputs',
    triggers: 'Manual triggers and schedule',
    destinations: 'Destinations and audience',
};

export function m365ApprovalFromResponse(payload: unknown): M365Approval {
    const candidate = ((payload as { approval?: unknown } | null)?.approval ?? payload) as M365Approval | null;
    if (
        !candidate ||
        typeof candidate.id !== 'string' ||
        !isM365RequestType(candidate.request_type) ||
        candidate.approval_scope !== 'user'
    ) {
        throw new Error('The server did not return a user-owned Microsoft 365 approval.');
    }
    return candidate;
}

export async function fetchM365Approval(id: string, signal?: AbortSignal): Promise<M365Approval> {
    return m365ApprovalFromResponse(await m365Request<unknown>(`/api/m365/approvals/${encodeURIComponent(id)}`, { signal }));
}

export type M365DecisionPayload =
    | { choice: string }
    | { decisions: Record<string, { duration: SharingDuration; timezone?: string }> };

export async function decideM365Approval(id: string, payload: M365DecisionPayload): Promise<M365Approval> {
    const saved = m365ApprovalFromResponse(
        await m365Request<unknown>(`/api/m365/approvals/${encodeURIComponent(id)}/decision`, { method: 'POST', body: payload }),
    );
    if (saved.id !== id || saved.status === 'pending') {
        throw new Error('The server has not recorded this decision. Refresh before continuing.');
    }
    return saved;
}

export function canDecideM365(approval: M365Approval): boolean {
    return approval.status === 'pending' && (approval.can_approve === true || approval.can_deny === true);
}

/**
 * The sharing durations a source may be given, in the order the classic dialog offers them.
 *
 * Throws when the source policy cannot be verified: offering a choice the server did not
 * describe would be guessing at a permission.
 */
export function sharingChoices(approval: M365Approval, source: string): SharingDuration[] {
    const policy = approval.sources?.[source];
    if (!M365_SOURCE_LABELS[source] || !policy || !Array.isArray(policy.allowed_durations)) {
        throw new Error('The sharing request has an unsupported source policy.');
    }
    const ladder: SharingDuration[] = ['request', 'today', 'always'];
    const ceiling = ladder.indexOf(policy.maximum_sharing_acknowledgement as SharingDuration);
    if (ceiling < 0) {
        throw new Error('The action sharing limit could not be verified.');
    }
    const allowed = policy.allowed_durations;
    const approveChoices = approval.can_approve === true
        ? ladder.slice(0, ceiling + 1).filter((duration) => allowed.includes(duration))
        : [];
    return [...(approval.can_deny === true ? (['no'] as SharingDuration[]) : []), ...approveChoices];
}

export function isValidTimezone(value: string): boolean {
    if (!value.trim()) return false;
    try {
        new Intl.DateTimeFormat('en-US', { timeZone: value.trim() });
        return true;
    } catch {
        return false;
    }
}

export function describeM365Status(approval: M365Approval): string {
    if (approval.self_authored === true && approval.status === 'approved') {
        return 'Decision: approved automatically because you saved this workflow revision yourself.';
    }
    const status = typeof approval.status === 'string' ? approval.status : 'unknown';
    const execution = typeof approval.execution_status === 'string' ? approval.execution_status : 'not reported';
    return `Decision: ${status.replace(/_/g, ' ')}. Execution: ${execution.replace(/_/g, ' ')}.`;
}

/** The extended-analysis counts, verified as safe non-negative integers. */
export const ANALYSIS_COUNT_LABELS: Record<string, string> = {
    file_count: 'Files',
    download_count: 'Content downloads',
    total_bytes: 'Content bytes',
    context_tokens: 'Context tokens',
};

export function analysisCounts(approval: M365Approval): Array<[string, number]> {
    const proposal = approval.proposal ?? {};
    const counts: Array<[string, number]> = [];
    for (const [key, label] of Object.entries(ANALYSIS_COUNT_LABELS)) {
        if (!Object.prototype.hasOwnProperty.call(proposal, key)) continue;
        const value = proposal[key];
        if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
            throw new Error('The requested analysis counts could not be verified. Refresh before deciding.');
        }
        counts.push([label, value]);
    }
    return counts;
}

/** The Run as review text, or null when any part the user must review is missing. */
export function runAsReview(approval: M365Approval): Array<[string, string]> | null {
    const review = approval.binding?.review;
    if (!review || typeof review !== 'object' || Array.isArray(review)) return null;
    const entries: Array<[string, string]> = [];
    for (const [key, label] of Object.entries(RUN_AS_REVIEW_LABELS)) {
        const value = review[key];
        if (typeof value !== 'string' || !value.trim()) return null;
        entries.push([label, value]);
    }
    return entries;
}

/* Paused requests ----------------------------------------------------------- */

export interface PausedRequest {
    id: string;
    status: 'awaiting_approval' | 'awaiting_sign_in' | 'recovery_required' | 'ready_to_resume' | string;
    conversation_id?: string;
    workflow_id?: string;
    sources?: unknown;
    created_at?: string;
    updated_at?: string;
}

export const PAUSED_STATUS_LABELS: Record<string, string> = {
    awaiting_approval: 'Waiting for approval',
    awaiting_sign_in: 'Waiting for Microsoft 365 sign-in',
    recovery_required: 'Needs recovery',
    ready_to_resume: 'Ready to resume',
};

export async function fetchPausedRequests(
    continuationToken: string,
    signal?: AbortSignal,
): Promise<{ items: PausedRequest[]; continuationToken: string }> {
    const query = continuationToken ? `?${new URLSearchParams({ continuation_token: continuationToken }).toString()}` : '';
    const data = await m365Request<{ items?: PausedRequest[]; continuation_token?: string }>(`/api/m365/requests${query}`, { signal });
    return {
        items: Array.isArray(data.items) ? data.items.filter((item) => typeof item?.id === 'string') : [],
        continuationToken: typeof data.continuation_token === 'string' ? data.continuation_token : '',
    };
}

export interface ResumeResult {
    auth_required?: boolean;
    message?: string;
    sources?: unknown;
}

export function resumePausedRequest(id: string): Promise<ResumeResult> {
    return m365Request<ResumeResult>(`/api/m365/requests/${encodeURIComponent(id)}/resume`, { method: 'POST', body: {} });
}

/* Outgoing actions ---------------------------------------------------------- */

export interface PendingActionSummary {
    subject?: string;
    to_recipients?: unknown;
    cc_recipients?: unknown;
    bcc_recipients?: unknown;
    attendee_recipients?: unknown;
    start_datetime?: string;
    end_datetime?: string;
    timezone?: string;
    location?: string;
    teams_meeting_requested?: boolean;
    body_preview?: string;
    body_preview_truncated?: boolean;
    content_type?: string;
    body_length?: number;
}

export interface PendingAction {
    type: 'msgraph_pending_action';
    id: string;
    version?: string;
    status: string;
    operation?: string;
    graph_resource_type?: string;
    subject?: string;
    summary?: PendingActionSummary;
    will_auto_send?: boolean;
    auto_send_at_utc?: string;
    action_mode?: string;
    can_cancel?: boolean;
    can_send_now?: boolean;
    can_approve?: boolean;
    viewer_is_owner?: boolean;
    requires_recreation?: boolean;
    requires_review?: boolean;
    review_details_required?: boolean;
    review_message?: string;
    error?: string;
    delivery_note?: string;
    web_link?: string;
    conversation_id?: string;
    workflow_id?: string;
    run_id?: string;
    request_id?: string;
    message_id?: string;
    event_id?: string;
    error_code?: string;
    delay_seconds?: number;
    /** Set when the owner's Microsoft 365 sign-in has to be renewed before this action can be sent. */
    auth_required?: boolean;
    sources?: unknown;
    scopes?: unknown;
    updated_at?: string;
    created_at?: string;
    completed_at?: string;
    cancelled_at?: string;
    failed_at?: string;
}

export const ACTIONABLE_PENDING_STATUSES = new Set(['pending', 'scheduled', 'review_required']);

export function isPendingAction(value: unknown): value is PendingAction {
    const action = value as PendingAction | null;
    return (
        action?.type === 'msgraph_pending_action' &&
        typeof action.id === 'string' &&
        Boolean(action.id.trim()) &&
        !['.', '..'].includes(action.id)
    );
}

export function pendingActionHeading(action: PendingAction): string {
    return action.graph_resource_type === 'calendar' ? 'Microsoft 365 calendar invitation' : 'Microsoft 365 email';
}

export function pendingActionStatusText(action: PendingAction): string {
    const labels: Record<string, string> = {
        pending: 'Pending — not sent.',
        scheduled: 'Scheduled — not yet sent.',
        review_required: 'Review required — not sent.',
        sending: 'Sending — the Microsoft 365 request is in progress. Do not submit it again.',
        sent:
            action.graph_resource_type === 'mail' || action.operation === 'send_mail'
                ? 'Accepted for sending — recipient delivery is not confirmed.'
                : 'Sent — calendar invitation created.',
        cancelled: 'Cancelled — no further delivery is scheduled for this action.',
        canceled: 'Cancelled — no further delivery is scheduled for this action.',
        failed: 'Failed — review the delivery note before creating another action.',
        recovery_required: 'Delivery outcome needs recovery. Check Microsoft 365 before creating or sending another action.',
    };
    return labels[action.status] ?? 'The delivery status is not recognized. Refresh status to check it.';
}

/** Whether the complete saved content must be loaded before the action may be sent. */
export function pendingActionNeedsFullReview(action: PendingAction): boolean {
    return action.review_details_required === true || action.summary?.body_preview_truncated === true;
}

/** Which send route applies, or '' when this account cannot send it from here. */
export function pendingActionSendRoute(action: PendingAction): '' | 'send-now' | 'approve' {
    if (action.viewer_is_owner === false || action.requires_recreation === true || pendingActionNeedsFullReview(action)) {
        return '';
    }
    return action.can_send_now === true ? 'send-now' : action.can_approve === true ? 'approve' : '';
}

export function canChangePendingAction(action: PendingAction): boolean {
    return (
        action.viewer_is_owner !== false &&
        typeof action.version === 'string' &&
        Boolean(action.version) &&
        ACTIONABLE_PENDING_STATUSES.has(action.status)
    );
}

export async function fetchPendingActions(
    continuationToken: string,
    signal?: AbortSignal,
): Promise<{ items: PendingAction[]; continuationToken: string }> {
    const params = new URLSearchParams({ active_only: '1', limit: '30' });
    if (continuationToken) params.set('continuation_token', continuationToken);
    const data = await m365Request<{ pending_actions?: unknown[]; continuation_token?: string }>(
        `/api/msgraph/pending-actions?${params.toString()}`,
        { signal },
    );
    return {
        items: (Array.isArray(data.pending_actions) ? data.pending_actions : []).filter(isPendingAction),
        continuationToken: typeof data.continuation_token === 'string' ? data.continuation_token : '',
    };
}

/**
 * One page of the outgoing actions saved in a conversation, for the chat view.
 *
 * Unlike the Approvals inbox this includes finished actions, so a reply that saved an email
 * still shows what became of it. A page with a row that is not a saved action is refused
 * rather than filtered, because a partly read page must never look like a complete one.
 */
export async function fetchConversationPendingActions(
    conversationId: string,
    continuationToken = '',
    signal?: AbortSignal,
): Promise<{ items: PendingAction[]; continuationToken: string }> {
    const params = new URLSearchParams({ conversation_id: conversationId, limit: '30' });
    if (continuationToken) params.set('continuation_token', continuationToken);
    const data = await m365Request<{ pending_actions?: unknown; continuation_token?: unknown }>(
        `/api/msgraph/pending-actions?${params.toString()}`,
        { signal },
    );
    if (!Array.isArray(data?.pending_actions) || !data.pending_actions.every(isPendingAction)) {
        throw new Error('Outgoing actions could not be verified.');
    }
    return {
        items: data.pending_actions,
        continuationToken: typeof data.continuation_token === 'string' ? data.continuation_token : '',
    };
}

function actionFromResponse(payload: unknown, id: string): PendingAction {
    const action = (payload as { pending_action?: unknown } | null)?.pending_action;
    if (!isPendingAction(action) || action.id !== id) {
        throw new Error('The saved action could not be verified. Refresh its status before trying again.');
    }
    return action;
}

/**
 * The current state of one saved action.
 *
 * Pass the conversation to read an action someone else saved in a shared conversation; the
 * server then checks access to that conversation instead of ownership of the action.
 */
export async function fetchPendingAction(
    id: string,
    signal?: AbortSignal,
    conversationId = '',
): Promise<PendingAction> {
    const query = conversationId ? `?${new URLSearchParams({ conversation_id: conversationId }).toString()}` : '';
    return actionFromResponse(
        await m365Request<unknown>(`/api/msgraph/pending-actions/${encodeURIComponent(id)}${query}`, { signal }),
        id,
    );
}

export async function mutatePendingAction(
    id: string,
    operation: 'send-now' | 'approve' | 'cancel',
    expectedVersion: string,
): Promise<PendingAction> {
    // The classic card refreshes the CSRF token first; a mutation must never ride a stale one.
    await refreshCsrf();
    return actionFromResponse(
        await m365Request<unknown>(`/api/msgraph/pending-actions/${encodeURIComponent(id)}/${operation}`, {
            method: 'POST',
            body: { expected_version: expectedVersion },
        }),
        id,
    );
}

/* -------------------------------------------------------------------------- */
/* Agent templates (administrators)                                            */
/* -------------------------------------------------------------------------- */

export type TemplateStatusFilter = 'pending' | 'approved' | 'rejected' | 'all';

export interface AgentTemplate {
    id: string;
    title?: string;
    display_name?: string;
    helper_text?: string;
    description?: string;
    instructions?: string;
    status?: string;
    created_by_name?: string;
    created_by_email?: string;
    created_at?: string;
    updated_at?: string;
    actions_to_load?: string[];
    additional_settings?: unknown;
    tags?: string[];
    review_notes?: string;
    rejection_reason?: string;
}

export function templateTitle(template: AgentTemplate): string {
    return template.title || template.display_name || 'Untitled template';
}

export async function fetchAgentTemplates(status: TemplateStatusFilter, signal?: AbortSignal): Promise<AgentTemplate[]> {
    const data = await api.get<{ templates?: AgentTemplate[] }>(
        `/api/admin/agent-templates?${new URLSearchParams({ status }).toString()}`,
        signal,
    );
    return Array.isArray(data.templates) ? data.templates : [];
}

export async function fetchAgentTemplate(id: string, signal?: AbortSignal): Promise<AgentTemplate> {
    const data = await api.get<{ template?: AgentTemplate }>(`/api/admin/agent-templates/${encodeURIComponent(id)}`, signal);
    if (!data.template || typeof data.template.id !== 'string') {
        throw new Error('The template could not be loaded.');
    }
    return data.template;
}

export function approveAgentTemplate(id: string, notes: string) {
    return api.post<unknown>(`/api/admin/agent-templates/${encodeURIComponent(id)}/approve`, { notes: notes.trim() });
}

export function rejectAgentTemplate(id: string, reason: string, notes: string) {
    return api.post<unknown>(`/api/admin/agent-templates/${encodeURIComponent(id)}/reject`, {
        reason: reason.trim(),
        notes: notes.trim(),
    });
}

export function deleteAgentTemplate(id: string) {
    return api.delete<unknown>(`/api/admin/agent-templates/${encodeURIComponent(id)}`);
}

/* -------------------------------------------------------------------------- */
/* Shared formatting                                                           */
/* -------------------------------------------------------------------------- */

export function formatDateTime(value: unknown): string {
    if (typeof value !== 'string' || !value) return '';
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString() : value;
}

export function textList(value: unknown): string {
    if (Array.isArray(value)) {
        return value
            .map((item) => (typeof item === 'string' || typeof item === 'number' ? String(item) : ''))
            .filter(Boolean)
            .join(', ');
    }
    return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

export function errorMessage(error: unknown, fallback: string): string {
    return error instanceof Error && error.message ? error.message : fallback;
}
