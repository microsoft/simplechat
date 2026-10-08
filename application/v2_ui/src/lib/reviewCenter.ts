// reviewCenter.ts
// What the admin Review center says about each feedback record and safety violation, which
// filters its addresses carry, and the defaults its editors start from.
//
// The Review center's workbenches list records as one-line rows beside a detail pane, the way
// the Workflows workbench does. These are the decisions they make about each row -- how a state
// reads, which tone it takes, what a filter in the address means -- kept apart from the
// components so they run in a test. Everything here reads the records the review APIs return;
// nothing is inferred beyond them.

import type { ReviewSectionId } from './reviewAccess';

export type ReviewTone = 'ok' | 'warn' | 'danger' | 'info' | 'neutral' | 'accent';

export const REVIEW_PAGE_SIZES = [10, 20, 50, 100] as const;
export const DEFAULT_REVIEW_PAGE_SIZE = 20;
export const REVIEW_WINDOWS = ['7', '30', '90'] as const;
export type ReviewWindow = (typeof REVIEW_WINDOWS)[number];
export const DEFAULT_REVIEW_WINDOW: ReviewWindow = '30';
/** The most operations one bulk request carries; larger selections are sent in batches. */
export const REVIEW_BULK_BATCH = 100;
export type ArchiveFilter = 'active' | 'archived' | 'all';

const ARCHIVE_FILTERS: readonly ArchiveFilter[] = ['active', 'archived', 'all'];
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function readReviewWindow(value: string | null | undefined): ReviewWindow {
    return (REVIEW_WINDOWS as readonly string[]).includes(value ?? '') ? (value as ReviewWindow) : DEFAULT_REVIEW_WINDOW;
}

function readWindowFilter(value: string | null): '' | ReviewWindow {
    return (REVIEW_WINDOWS as readonly string[]).includes(value ?? '') ? (value as ReviewWindow) : '';
}

function readArchive(value: string | null): ArchiveFilter {
    return ARCHIVE_FILTERS.includes(value as ArchiveFilter) ? (value as ArchiveFilter) : 'active';
}

function readDate(value: string | null): string {
    return value && DATE_PATTERN.test(value) ? value : '';
}

function readText(value: string | null, limit = 200): string {
    return (value ?? '').slice(0, limit);
}

export function formatReviewDate(value?: string | null): string {
    if (!value) return 'Not recorded';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** One line of text for a list row: whitespace collapsed and cut to `limit` characters. */
export function reviewExcerpt(value: string | null | undefined, limit = 120): string {
    const flattened = (value ?? '').split(/\s+/).filter(Boolean).join(' ');
    return flattened.length <= limit ? flattened : `${flattened.slice(0, limit - 1).trimEnd()}…`;
}

/* -------------------------------------------------------------------------- */
/* Paging and selection carried in the address                                 */
/* -------------------------------------------------------------------------- */

export interface ReviewPaging {
    page: number;
    pageSize: number;
    selected: string;
}

export function readReviewPaging(params: URLSearchParams): ReviewPaging {
    const page = Number.parseInt(params.get('page') ?? '', 10);
    const size = Number.parseInt(params.get('size') ?? '', 10);
    return {
        page: Number.isFinite(page) && page > 0 ? page : 1,
        pageSize: (REVIEW_PAGE_SIZES as readonly number[]).includes(size) ? size : DEFAULT_REVIEW_PAGE_SIZE,
        selected: readText(params.get('selected')),
    };
}

/* -------------------------------------------------------------------------- */
/* Feedback                                                                    */
/* -------------------------------------------------------------------------- */

export interface FeedbackReviewer {
    id?: string;
    displayName?: string;
}

export interface FeedbackAdminReview {
    acknowledged?: boolean;
    analysisNotes?: string | null;
    responseToUser?: string | null;
    actionTaken?: string | null;
    reviewTimestamp?: string | null;
    analyzedBy?: FeedbackReviewer | string | null;
    userNotifiedAt?: string | null;
}

export interface FeedbackRecord {
    id: string;
    userId?: string;
    userDisplayName?: string | null;
    userEmail?: string | null;
    prompt?: string;
    aiResponse?: string;
    feedbackType?: string;
    reason?: string;
    timestamp?: string;
    isArchived?: boolean;
    adminReview?: FeedbackAdminReview;
    etag?: string;
}

export type FeedbackRating = '' | 'Positive' | 'Negative' | 'Neutral';
export const FEEDBACK_RATINGS: readonly Exclude<FeedbackRating, ''>[] = ['Positive', 'Negative', 'Neutral'];

export interface FeedbackFilters {
    type: FeedbackRating;
    ack: '' | 'true' | 'false';
    archive: ArchiveFilter;
    search: string;
    userId: string;
    date: string;
    days: '' | ReviewWindow;
}

export const DEFAULT_FEEDBACK_FILTERS: FeedbackFilters = {
    type: '',
    ack: '',
    archive: 'active',
    search: '',
    userId: '',
    date: '',
    days: '',
};

export function readFeedbackFilters(params: URLSearchParams): FeedbackFilters {
    const type = params.get('type') ?? '';
    const ack = params.get('ack') ?? '';
    return {
        type: (FEEDBACK_RATINGS as readonly string[]).includes(type) ? (type as FeedbackRating) : '',
        ack: ack === 'true' || ack === 'false' ? ack : '',
        archive: readArchive(params.get('archive')),
        search: readText(params.get('search')),
        userId: readText(params.get('user_id')),
        date: readDate(params.get('date')),
        days: readWindowFilter(params.get('days')),
    };
}

/** The filters as query parameters, defaults left out. The list API reads the same names. */
export function feedbackFilterParams(filters: FeedbackFilters): URLSearchParams {
    const params = new URLSearchParams();
    if (filters.type) params.set('type', filters.type);
    if (filters.ack) params.set('ack', filters.ack);
    if (filters.archive !== 'active') params.set('archive', filters.archive);
    if (filters.search.trim()) params.set('search', filters.search.trim());
    if (filters.userId) params.set('user_id', filters.userId);
    if (filters.date) params.set('date', filters.date);
    if (filters.days) params.set('days', filters.days);
    return params;
}

export function feedbackRatingTone(rating?: string): ReviewTone {
    if (rating === 'Positive') return 'ok';
    if (rating === 'Negative') return 'danger';
    return 'neutral';
}

export function feedbackReviewState(record: FeedbackRecord): { label: string; tone: ReviewTone } {
    if (record.adminReview?.acknowledged) return { label: 'Acknowledged', tone: 'ok' };
    return { label: 'Awaiting review', tone: 'warn' };
}

export function feedbackUserLabel(record: FeedbackRecord): string {
    return record.userDisplayName || record.userEmail || record.userId || 'Unknown user';
}

export function feedbackRowTitle(record: FeedbackRecord): string {
    return reviewExcerpt(record.prompt) || 'No prompt captured';
}

/** What a row says beside its prompt: the rating, the review state, who sent it and when. */
export function feedbackRowMeta(record: FeedbackRecord): string {
    return [
        record.feedbackType || 'Unrated',
        feedbackReviewState(record).label,
        feedbackUserLabel(record),
        formatReviewDate(record.timestamp),
    ].join(' · ');
}

export function feedbackReviewerName(review?: FeedbackAdminReview | null): string {
    const reviewer = review?.analyzedBy;
    if (!reviewer) return '';
    if (typeof reviewer === 'string') return reviewer;
    return reviewer.displayName || reviewer.id || '';
}

/** How many filters other than the search narrow the feedback list. */
export function feedbackFiltersApplied(filters: FeedbackFilters): number {
    return [filters.type, filters.ack, filters.archive !== 'active' ? 'x' : '', filters.userId, filters.date, filters.days]
        .filter(Boolean).length;
}

/* -------------------------------------------------------------------------- */
/* Safety violations                                                           */
/* -------------------------------------------------------------------------- */

export interface TriggeredCategory {
    category?: string;
    severity?: number;
}

export interface UserAccessState {
    restricted: boolean;
    kind?: string | null;
    until?: string | null;
}

export interface SafetyRecord {
    id: string;
    user_id?: string;
    user_display_name?: string | null;
    user_email?: string | null;
    message?: string;
    triggered_categories?: TriggeredCategory[];
    status?: string;
    action?: string;
    notes?: string;
    user_notes?: string;
    created_at?: string;
    last_updated?: string;
    content_origin?: string;
    action_request_status?: string | null;
    action_request_id?: string | null;
    action_request_type?: string | null;
    action_requested_at?: string | null;
    action_request_decided_at?: string | null;
    action_approved_at?: string | null;
    action_executed_at?: string | null;
    action_execution_error?: string | null;
    action_notification_title?: string | null;
    action_notification_message?: string | null;
    action_datetime_to_allow?: string | null;
    /** Set on an executed warning: `pending` until the user acknowledges it. */
    warning_acknowledgment_status?: 'pending' | 'acknowledged' | 'not_tracked' | null;
    warning_acknowledged_at?: string | null;
    warning_issued_at?: string | null;
    isArchived?: boolean;
    etag?: string;
    user_access?: UserAccessState | null;
    user_violation_count?: number | null;
}

export const SAFETY_STATUSES = ['New', 'In-Review', 'Resolved', 'Dismissed'] as const;
export type SafetyStatus = (typeof SAFETY_STATUSES)[number];
// Escalate is no longer an action. A record that already carries it keeps it, labelled as
// legacy, and only that record's review offers it again.
export const ACTIONS = ['None', 'WarnUser', 'SuspendUser', 'BlockUser'];
export const LEGACY_ESCALATE_ACTION = 'Escalate';
export const LEGACY_ESCALATE_LABEL = 'Escalated (legacy)';
export const REMEDIATION_ACTIONS: ReadonlySet<string> = new Set(['WarnUser', 'SuspendUser', 'BlockUser']);
/** Suspend and block restrict access, so another eligible reviewer must approve them. */
export const APPROVAL_REQUIRED_ACTIONS: ReadonlySet<string> = new Set(['SuspendUser', 'BlockUser']);
export const SAFETY_REQUEST_STATES = ['pending', 'executed', 'failed', 'denied', 'expired'] as const;
export type SafetyRequestState = (typeof SAFETY_REQUEST_STATES)[number];
export const SAFETY_WARNING_STATES = ['pending', 'acknowledged', 'not_tracked'] as const;

const ACTION_LABELS: Readonly<Record<string, string>> = {
    None: 'No action',
    WarnUser: 'Warn user',
    SuspendUser: 'Suspend user',
    BlockUser: 'Block user',
    [LEGACY_ESCALATE_ACTION]: LEGACY_ESCALATE_LABEL,
};

export function safetyActionLabel(action?: string | null): string {
    const value = action || 'None';
    return ACTION_LABELS[value] ?? value.replace(/([a-z])([A-Z])/g, '$1 $2');
}

/** The actions a record's review may choose: legacy Escalate only on a record that has it. */
export function selectableSafetyActions(record: Pick<SafetyRecord, 'action'>): string[] {
    return record.action === LEGACY_ESCALATE_ACTION ? [...ACTIONS, LEGACY_ESCALATE_ACTION] : [...ACTIONS];
}

export function safetyStatusTone(status?: string | null): ReviewTone {
    if (status === 'Resolved') return 'ok';
    if (status === 'Dismissed') return 'neutral';
    if (status === 'In-Review') return 'info';
    return 'warn';
}

export function safetyRequestState(record: Pick<SafetyRecord, 'action_request_status'>): string {
    return (record.action_request_status || '').trim().toLowerCase();
}

/** The violation waits on an approval request and cannot be changed or deleted until it is decided. */
export function isRemediationPending(record: SafetyRecord): boolean {
    return safetyRequestState(record) === 'pending';
}

/**
 * Another save is sending this violation's warning right now. Like a pending request it
 * holds the violation until it finishes; a send that stopped part way reads as failed.
 */
export function isWarningSending(record: SafetyRecord): boolean {
    return safetyRequestState(record) === 'sending';
}

/** The violation cannot be saved, archived or deleted until its request or send settles. */
export function isSafetyRecordLocked(record: SafetyRecord): boolean {
    return isRemediationPending(record) || isWarningSending(record);
}

/** A warning that was sent. Saving the record again does not resend it. */
export function isExecutedWarning(record: SafetyRecord): boolean {
    return record.action === 'WarnUser' && safetyRequestState(record) === 'executed';
}

export function topCategory(record: SafetyRecord): TriggeredCategory | null {
    let best: TriggeredCategory | null = null;
    for (const entry of record.triggered_categories ?? []) {
        if (!entry?.category) continue;
        if (!best || (entry.severity ?? -1) > (best.severity ?? -1)) best = entry;
    }
    return best;
}

export function categorySummary(record: SafetyRecord): string {
    return (record.triggered_categories ?? [])
        .filter((entry) => entry?.category)
        .map((entry) => `${entry.category} (severity ${entry.severity ?? '?'})`)
        .join(', ');
}

export function safetyUserLabel(record: SafetyRecord): string {
    return record.user_display_name || record.user_email || record.user_id || 'Unknown user';
}

export function safetyRowTitle(record: SafetyRecord): string {
    return reviewExcerpt(record.message) || 'No message captured';
}

/** What a row says beside its message: the top category, the user and when it was flagged. */
export function safetyRowMeta(record: SafetyRecord): string {
    const top = topCategory(record);
    return [
        top ? `${top.category} · severity ${top.severity ?? '?'}` : 'No category recorded',
        safetyUserLabel(record),
        formatReviewDate(record.created_at),
    ].join(' · ');
}

/** The action a violation records and how far it has got, as a short badge. */
export function safetyActionBadge(record: SafetyRecord): { label: string; detail: string; tone: ReviewTone } {
    const label = safetyActionLabel(record.action);
    const state = safetyRequestState(record);
    if (isExecutedWarning(record)) {
        if (record.warning_acknowledgment_status === 'acknowledged') return { label, detail: 'Acknowledged', tone: 'ok' };
        if (record.warning_acknowledgment_status === 'pending') return { label, detail: 'Not yet acknowledged', tone: 'warn' };
        return { label, detail: 'Sent', tone: 'neutral' };
    }
    switch (state) {
        case 'pending':
            return { label, detail: 'Pending approval', tone: 'warn' };
        case 'sending':
            return { label, detail: 'Sending', tone: 'info' };
        case 'executed':
            return { label, detail: 'Applied', tone: 'ok' };
        case 'failed':
            return { label, detail: 'Failed', tone: 'danger' };
        case 'denied':
            return { label, detail: 'Denied', tone: 'neutral' };
        case 'expired':
            return { label, detail: 'Expired', tone: 'neutral' };
        default:
            return { label, detail: '', tone: record.action && record.action !== 'None' ? 'info' : 'neutral' };
    }
}

/** Whether the user has acknowledged a warning that was sent. */
export function warningAcknowledgmentText(record: SafetyRecord): string | null {
    if (!isExecutedWarning(record)) return null;
    if (record.warning_acknowledgment_status === 'acknowledged') {
        return `Warning acknowledged ${formatReviewDate(record.warning_acknowledged_at)}`;
    }
    if (record.warning_acknowledgment_status === 'pending') {
        return 'Warning sent. Not yet acknowledged by the user.';
    }
    return 'Warning sent before acknowledgment was tracked.';
}

/**
 * Where a remediation request stands, in a sentence. Never quotes the stored failure text,
 * which can carry a technical error; the approval request has the details.
 */
export function remediationStatusText(record: SafetyRecord): string | null {
    const state = safetyRequestState(record);
    const kind = record.action === 'BlockUser' ? 'block' : record.action === 'SuspendUser' ? 'suspension' : 'action';
    switch (state) {
        case 'pending':
            return `The ${kind} is waiting for another eligible reviewer to approve it. Requested ${formatReviewDate(record.action_requested_at)}.`;
        case 'sending':
            return 'Another save is sending this warning now. Reload in a moment to see whether it was sent.';
        case 'executed':
            return record.action === 'WarnUser'
                ? `The warning was sent ${formatReviewDate(record.action_executed_at)}.`
                : `The ${kind} was approved and applied ${formatReviewDate(record.action_executed_at)}.`;
        case 'failed':
            return record.action === 'WarnUser'
                ? 'The warning could not be sent. Save the review again to retry.'
                : `The ${kind} was approved but could not be applied. Open the approval request for details.`;
        case 'denied':
            return `The ${kind} request was denied ${formatReviewDate(record.action_request_decided_at)}. It can be requested again.`;
        case 'expired':
            return `The ${kind} request expired without a decision. It can be requested again.`;
        default:
            return null;
    }
}

/**
 * Whether a violation's review offers to request its suspension or block again: only when
 * the action stays the same, and never while a request waits or a warning is being sent.
 */
export function offersRestrictionReissue(record: SafetyRecord, action: string): boolean {
    const state = safetyRequestState(record);
    return APPROVAL_REQUIRED_ACTIONS.has(action)
        && (record.action || 'None') === action
        && state !== 'pending'
        && state !== 'sending';
}

/**
 * What saving the same suspension or block again does when it isn't asked for again, by
 * where its last request stands. Mirrors the classic review page.
 */
export function existingRestrictionText(record: SafetyRecord, action: string): string {
    const noun = action === 'BlockUser' ? 'block' : 'suspension';
    const where: Readonly<Record<string, string>> = {
        executed: `This ${noun} was approved and applied.`,
        denied: `This ${noun} request was denied.`,
        expired: `This ${noun} request expired without a decision.`,
        failed: `This ${noun} was approved but could not be applied.`,
    };
    const state = where[safetyRequestState(record)] ?? `This violation already records a ${noun}.`;
    return `${state} Saving updates the review only and requests nothing new. To ask another eligible reviewer to approve it again, select "Request this ${noun} again".`;
}

export interface SafetyFilters {
    status: '' | 'open' | SafetyStatus;
    action: string;
    archive: ArchiveFilter;
    search: string;
    userId: string;
    category: string;
    severity: string;
    request: '' | SafetyRequestState;
    warning: '' | (typeof SAFETY_WARNING_STATES)[number];
    restricted: boolean;
    date: string;
    days: '' | ReviewWindow;
}

export const DEFAULT_SAFETY_FILTERS: SafetyFilters = {
    status: '',
    action: '',
    archive: 'active',
    search: '',
    userId: '',
    category: '',
    severity: '',
    request: '',
    warning: '',
    restricted: false,
    date: '',
    days: '',
};

export function readSafetyFilters(params: URLSearchParams): SafetyFilters {
    const status = params.get('status') ?? '';
    const action = params.get('action') ?? '';
    const request = params.get('request') ?? '';
    const warning = params.get('warning') ?? '';
    const severity = params.get('severity') ?? '';
    return {
        status: status === 'open' || (SAFETY_STATUSES as readonly string[]).includes(status)
            ? (status as SafetyFilters['status'])
            : '',
        action: [...ACTIONS, LEGACY_ESCALATE_ACTION].includes(action) ? action : '',
        archive: readArchive(params.get('archive')),
        search: readText(params.get('search')),
        userId: readText(params.get('user_id')),
        category: readText(params.get('category'), 100),
        severity: /^\d{1,2}$/.test(severity) ? severity : '',
        request: (SAFETY_REQUEST_STATES as readonly string[]).includes(request) ? (request as SafetyRequestState) : '',
        warning: (SAFETY_WARNING_STATES as readonly string[]).includes(warning)
            ? (warning as SafetyFilters['warning'])
            : '',
        restricted: params.get('restricted') === '1',
        date: readDate(params.get('date')),
        days: readWindowFilter(params.get('days')),
    };
}

/** The filters as query parameters, defaults left out. The list API reads the same names. */
export function safetyFilterParams(filters: SafetyFilters): URLSearchParams {
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.action) params.set('action', filters.action);
    if (filters.archive !== 'active') params.set('archive', filters.archive);
    if (filters.search.trim()) params.set('search', filters.search.trim());
    if (filters.userId) params.set('user_id', filters.userId);
    if (filters.category) params.set('category', filters.category);
    if (filters.severity) params.set('severity', filters.severity);
    if (filters.request) params.set('request', filters.request);
    if (filters.warning) params.set('warning', filters.warning);
    if (filters.restricted) params.set('restricted', '1');
    if (filters.date) params.set('date', filters.date);
    if (filters.days) params.set('days', filters.days);
    return params;
}

/** How many filters other than the search narrow the violation list. */
export function safetyFiltersApplied(filters: SafetyFilters): number {
    return [
        filters.status, filters.action, filters.archive !== 'active' ? 'x' : '', filters.userId, filters.category,
        filters.severity, filters.request, filters.warning, filters.restricted ? 'x' : '', filters.date, filters.days,
    ].filter(Boolean).length;
}

/* -------------------------------------------------------------------------- */
/* Remediation editor defaults                                                 */
/* -------------------------------------------------------------------------- */

/** The title the server sends when none is given. Mirrors _default_notification_title. */
export function defaultNotificationTitle(action: string): string {
    if (action === 'WarnUser') return 'Safety Violation Warning';
    if (action === 'SuspendUser') return 'Account Suspension Notice';
    if (action === 'BlockUser') return 'Account Access Blocked';
    return 'Safety Violation Notice';
}

/** The message the server sends when none is given. Mirrors _default_notification_message. */
export function defaultNotificationMessage(
    record: SafetyRecord,
    action: string,
    notes: string,
    restoreAt?: string | null,
): string {
    const lines = [
        'A safety review has been completed for recent activity in your workspace.',
        `Violation ID: ${record.id || 'Unknown'}`,
    ];
    const categories = (record.triggered_categories ?? [])
        .filter((entry) => entry?.category)
        .map((entry) => (entry.severity !== undefined && entry.severity !== null
            ? `${entry.category}(s=${entry.severity})`
            : `${entry.category}`))
        .join(', ');
    if (categories) lines.push(`Triggered categories: ${categories}`);
    if (action === 'WarnUser') {
        lines.push('Action taken: Warning issued. Please review our acceptable use requirements before continuing.');
    } else if (action === 'SuspendUser') {
        lines.push('Action taken: Your access has been temporarily suspended pending the date below.');
        if (restoreAt) lines.push(`Access restores automatically after: ${restoreAt}`);
    } else if (action === 'BlockUser') {
        lines.push('Action taken: Your access has been blocked with no automatic restore date.');
    }
    if (notes.trim()) lines.push(`Admin notes: ${notes.trim()}`);
    return lines.join('\n');
}

export type SuspendPreset = '24h' | '7d' | '30d' | 'custom';

export const SUSPEND_PRESETS: readonly { id: SuspendPreset; label: string; hours?: number }[] = [
    { id: '24h', label: '24 hours', hours: 24 },
    { id: '7d', label: '7 days', hours: 24 * 7 },
    { id: '30d', label: '30 days', hours: 24 * 30 },
    { id: 'custom', label: 'Custom date' },
];

/** When a preset suspension ends, counted from `now`; null for the custom date. */
export function suspendPresetUntil(preset: SuspendPreset, now: Date = new Date()): Date | null {
    const hours = SUSPEND_PRESETS.find((option) => option.id === preset)?.hours;
    return hours ? new Date(now.getTime() + hours * 3600 * 1000) : null;
}

/** A time as a `datetime-local` value in the reader's time zone, or '' when it can't be read. */
export function toLocalDateTimeInput(value?: string | Date | null): string {
    if (!value) return '';
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** A `datetime-local` value as an ISO 8601 time, or null when it is empty or unreadable. */
export function fromLocalDateTimeInput(value: string): string | null {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/* -------------------------------------------------------------------------- */
/* Bulk results                                                                */
/* -------------------------------------------------------------------------- */

export interface ReviewBulkResult {
    id: string;
    op: string;
    ok: boolean;
    status: number;
    code?: string;
    error?: string;
    message?: string;
    [key: string]: unknown;
}

export interface ReviewBulkResponse {
    results: ReviewBulkResult[];
    succeeded: number;
    failed: number;
}

export function chunkIds<T>(items: readonly T[], size = REVIEW_BULK_BATCH): T[][] {
    const chunks: T[][] = [];
    for (let start = 0; start < items.length; start += size) {
        chunks.push(items.slice(start, start + size));
    }
    return chunks;
}

export interface BulkOutcome {
    succeeded: string[];
    failures: { id: string; message: string }[];
}

/** Every result from one or more bulk responses, split into what succeeded and why the rest failed. */
export function bulkOutcome(results: readonly ReviewBulkResult[]): BulkOutcome {
    const outcome: BulkOutcome = { succeeded: [], failures: [] };
    for (const result of results) {
        if (result.ok) outcome.succeeded.push(result.id);
        else outcome.failures.push({ id: result.id, message: result.error || result.message || 'The change could not be made.' });
    }
    return outcome;
}

/** "3 violations" / "1 feedback record", for counts in confirmations and results. */
export function countLabel(count: number, singular: string, plural: string): string {
    return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

export interface BulkReport {
    summary: string;
    failures: { id: string; label: string; message: string }[];
}

/**
 * What a bulk action did, for the report under the bulk bar: a sentence for the whole run,
 * then each record it could not change, named the way the list names it, with the reason
 * the server gave.
 */
export function buildBulkReport(
    results: readonly ReviewBulkResult[],
    verb: string,
    noun: { singular: string; plural: string },
    describe: (id: string) => string,
): BulkReport {
    const outcome = bulkOutcome(results);
    const total = results.length;
    const done = outcome.succeeded.length;
    const failed = outcome.failures.length;
    const summary = failed
        ? `${verb} ${done.toLocaleString()} of ${countLabel(total, noun.singular, noun.plural)}. ${failed.toLocaleString()} ${failed === 1 ? 'was' : 'were'} not changed.`
        : `${verb} ${countLabel(done, noun.singular, noun.plural)}.`;
    return {
        summary,
        failures: outcome.failures.map((failure) => ({ ...failure, label: describe(failure.id) })),
    };
}

/* -------------------------------------------------------------------------- */
/* Addresses                                                                   */
/* -------------------------------------------------------------------------- */

export type ReviewView = 'dashboard' | 'queue' | 'violations' | 'unchecked';

const VIEW_SEGMENTS: Readonly<Record<ReviewView, string>> = {
    dashboard: '',
    queue: '/queue',
    violations: '/violations',
    unchecked: '/unchecked',
};

function withQuery(path: string, params?: URLSearchParams | null): string {
    const query = params?.toString() ?? '';
    return query ? `${path}?${query}` : path;
}

/** A Review center page: a section's dashboard, workbench or unchecked queue, with its filters. */
export function safeReviewViewHref(section: ReviewSectionId, view: ReviewView, params?: URLSearchParams | null): string {
    const sectionSegment = section === 'safety' ? 'safety' : 'feedback';
    return withQuery(`/admin/review/${sectionSegment}${VIEW_SEGMENTS[view]}`, params);
}

/** One record's editor, keeping the workbench filters so Back returns to the same list. */
export function safeReviewRecordHref(section: ReviewSectionId, recordId: string, params?: URLSearchParams | null): string {
    const base = section === 'safety' ? '/admin/review/safety/violations' : '/admin/review/feedback/queue';
    return withQuery(`${base}/${encodeURIComponent(recordId)}`, params);
}

/** The approval request a violation's remediation created, on the Approvals page. */
export function safeApprovalRequestHref(approvalId: string, groupId?: string | null): string {
    const params = groupId ? new URLSearchParams({ group_id: groupId }) : null;
    return withQuery(`/approvals/all/${encodeURIComponent(approvalId)}`, params);
}

/** The feedback workbench filtered as a dashboard tile or chart says. */
export function safeFeedbackQueueHref(filters: Partial<FeedbackFilters>): string {
    return safeReviewViewHref('feedback', 'queue', feedbackFilterParams({ ...DEFAULT_FEEDBACK_FILTERS, ...filters }));
}

/** The violations workbench filtered as a dashboard tile or chart says. */
export function safeViolationsHref(filters: Partial<SafetyFilters>): string {
    return safeReviewViewHref('safety', 'violations', safetyFilterParams({ ...DEFAULT_SAFETY_FILTERS, ...filters }));
}
