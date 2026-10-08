// reviewSuggestions.ts
// What the Review center makes of an AI suggestion: reading one the server sent, saying what it
// would change, deciding which suggestions an approval may apply, building the save that applies
// one, and running a triage of many records ten at a time.
//
// A suggestion only ever proposes. The server stores it on its record, and nothing about the review
// changes until a reviewer applies it through the normal save, which still sends a warning straight
// away and still asks a second reviewer to approve a suspension or block. Everything a suggestion
// holds came from a model, so it is checked field by field here and rendered only as text. Nothing
// here makes a request: the triage runner is handed the function that posts each chunk.

import { codePointPrefix } from './codePoints';
import {
    APPROVAL_REQUIRED_ACTIONS,
    feedbackThemeLabel,
    isFeedbackTheme,
    isSafetyRecordLocked,
    reviewExcerpt,
    SAFETY_STATUSES,
    safetyActionLabel,
    safetyRequestState,
    suspendPresetUntil,
    type FeedbackRecord,
    type FeedbackTheme,
    type SafetyRecord,
    type SafetyStatus,
} from './reviewCenter';
import type { ReviewSectionId } from './reviewAccess';

export const SUGGESTED_SAFETY_ACTIONS = ['None', 'WarnUser', 'SuspendUser', 'BlockUser'] as const;
export type SuggestedSafetyAction = (typeof SUGGESTED_SAFETY_ACTIONS)[number];
export const SUSPEND_DURATIONS = ['24h', '7d', '30d'] as const;
export type SuspendDuration = (typeof SUSPEND_DURATIONS)[number];
export const SUSPEND_DURATION_LABELS: Readonly<Record<SuspendDuration, string>> = {
    '24h': '24 hours',
    '7d': '7 days',
    '30d': '30 days',
};
export const SUGGESTION_CONFIDENCE = ['low', 'medium', 'high'] as const;
export type SuggestionConfidence = (typeof SUGGESTION_CONFIDENCE)[number];
export type SuggestionStatus = 'pending' | 'stale' | 'applied' | 'dismissed' | 'unsaved';

/** Records one triage request covers; the server refuses more. */
export const REVIEW_TRIAGE_CHUNK = 10;
/** The longest wait for the rate limit a triage sits through before it stops. */
export const REVIEW_TRIAGE_MAX_WAIT_SECONDS = 90;

// The server's caps (functions_review_assist.py). Longer text is cut for display only.
export const SUGGESTION_LIMITS = {
    analysisNotes: 2000,
    actionTaken: 1000,
    responseToUser: 1000,
    notes: 2000,
    notificationTitle: 200,
    notificationMessage: 2000,
    rationale: 600,
} as const;

const SERVER_TEXT_LIMIT = 1000;
const SUGGESTION_ID = /^[a-f0-9]{32}$/;
const CODE = /^[a-z0-9_]{1,64}$/;
const CONTROL_CHARACTERS = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function cleanText(value: string, limit: number): string {
    return codePointPrefix(value.replace(CONTROL_CHARACTERS, ' ').trim(), limit);
}

function textOrNull(value: unknown, limit: number): string | null {
    return typeof value === 'string' ? cleanText(value, limit) : null;
}

function personName(value: unknown): string | null {
    if (!isRecord(value)) return null;
    const name = textOrNull(value.name, 200);
    return name || null;
}

/* -------------------------------------------------------------------------- */
/* Reading suggestions                                                         */
/* -------------------------------------------------------------------------- */

export interface FeedbackSuggestionPayload {
    acknowledged: boolean;
    analysisNotes: string;
    actionTaken: string;
    responseToUser: string;
    theme: FeedbackTheme;
    archive: boolean;
}

export interface SafetySuggestionPayload {
    status: SafetyStatus;
    action: SuggestedSafetyAction;
    notes: string;
    notificationTitle: string | null;
    notificationMessage: string | null;
    suspendDuration: SuspendDuration | null;
    archive: boolean;
}

export interface ReviewSuggestion<P> {
    /** Null for an analysis the editor has not stored. */
    id: string | null;
    status: SuggestionStatus;
    createdAt: string | null;
    createdBy: string | null;
    model: string | null;
    payload: P;
    rationale: string;
    confidence: SuggestionConfidence | null;
    appliedAt: string | null;
    appliedBy: string | null;
    edited: boolean;
    dismissedAt: string | null;
    dismissedBy: string | null;
}

export type FeedbackSuggestion = ReviewSuggestion<FeedbackSuggestionPayload>;
export type SafetySuggestion = ReviewSuggestion<SafetySuggestionPayload>;
export type AnySuggestion = FeedbackSuggestion | SafetySuggestion;

const STATUSES: readonly SuggestionStatus[] = ['pending', 'stale', 'applied', 'dismissed', 'unsaved'];

function parseMeta<P>(value: unknown, payload: P | null): ReviewSuggestion<P> | null {
    if (!isRecord(value) || payload === null) return null;
    const status = value.status;
    if (typeof status !== 'string' || !(STATUSES as readonly string[]).includes(status)) return null;
    const id = value.id;
    if (status === 'unsaved' ? id !== null : typeof id !== 'string' || !SUGGESTION_ID.test(id)) return null;
    const confidence = value.confidence;
    return {
        id: typeof id === 'string' ? id : null,
        status: status as SuggestionStatus,
        createdAt: textOrNull(value.created_at, 64),
        createdBy: personName(value.created_by),
        model: textOrNull(value.model, 200) || null,
        payload,
        rationale: textOrNull(value.rationale, SUGGESTION_LIMITS.rationale) ?? '',
        confidence: (SUGGESTION_CONFIDENCE as readonly unknown[]).includes(confidence)
            ? (confidence as SuggestionConfidence)
            : null,
        appliedAt: textOrNull(value.applied_at, 64),
        appliedBy: personName(value.applied_by),
        edited: value.edited === true,
        dismissedAt: textOrNull(value.dismissed_at, 64),
        dismissedBy: personName(value.dismissed_by),
    };
}

function parseFeedbackPayload(value: unknown): FeedbackSuggestionPayload | null {
    if (!isRecord(value)) return null;
    const { acknowledged, analysisNotes, actionTaken, responseToUser, theme, archive } = value;
    if (typeof acknowledged !== 'boolean' || typeof archive !== 'boolean' || !isFeedbackTheme(theme)) return null;
    if (typeof analysisNotes !== 'string' || typeof actionTaken !== 'string' || typeof responseToUser !== 'string') return null;
    return {
        acknowledged,
        analysisNotes: cleanText(analysisNotes, SUGGESTION_LIMITS.analysisNotes),
        actionTaken: cleanText(actionTaken, SUGGESTION_LIMITS.actionTaken),
        responseToUser: cleanText(responseToUser, SUGGESTION_LIMITS.responseToUser),
        theme,
        archive,
    };
}

function parseSafetyPayload(value: unknown): SafetySuggestionPayload | null {
    if (!isRecord(value)) return null;
    const { status, action, notes, archive } = value;
    if (typeof status !== 'string' || !(SAFETY_STATUSES as readonly string[]).includes(status)) return null;
    if (typeof action !== 'string' || !(SUGGESTED_SAFETY_ACTIONS as readonly string[]).includes(action)) return null;
    if (typeof notes !== 'string' || typeof archive !== 'boolean') return null;
    const remediation = action !== 'None';
    const title = textOrNull(value.notification_title, SUGGESTION_LIMITS.notificationTitle);
    const message = textOrNull(value.notification_message, SUGGESTION_LIMITS.notificationMessage);
    if (remediation && (!title || !message)) return null;
    const duration = value.suspend_duration;
    const suspendDuration = (SUSPEND_DURATIONS as readonly unknown[]).includes(duration) ? (duration as SuspendDuration) : null;
    if (action === 'SuspendUser' && !suspendDuration) return null;
    return {
        status: status as SafetyStatus,
        action: action as SuggestedSafetyAction,
        notes: cleanText(notes, SUGGESTION_LIMITS.notes),
        notificationTitle: remediation ? title : null,
        notificationMessage: remediation ? message : null,
        suspendDuration: action === 'SuspendUser' ? suspendDuration : null,
        archive,
    };
}

/** A feedback record's AI suggestion as the server presented it, or null when there is none or it can't be read. */
export function parseFeedbackSuggestion(value: unknown): FeedbackSuggestion | null {
    return isRecord(value) ? parseMeta(value, parseFeedbackPayload(value.payload)) : null;
}

/** A violation's AI suggestion as the server presented it, or null when there is none or it can't be read. */
export function parseSafetySuggestion(value: unknown): SafetySuggestion | null {
    return isRecord(value) ? parseMeta(value, parseSafetyPayload(value.payload)) : null;
}

export function parseSuggestion(section: ReviewSectionId, value: unknown): AnySuggestion | null {
    return section === 'safety' ? parseSafetySuggestion(value) : parseFeedbackSuggestion(value);
}

/** A list row's AI suggestion badge: one waiting for a reviewer, or one whose record has changed since. */
export function suggestionBadge(section: ReviewSectionId, value: unknown): { label: string; tone: 'accent' | 'neutral' } | null {
    const suggestion = parseSuggestion(section, value);
    if (suggestion?.status === 'pending') return { label: 'AI suggestion', tone: 'accent' };
    if (suggestion?.status === 'stale') return { label: 'AI suggestion out of date', tone: 'neutral' };
    return null;
}

/* -------------------------------------------------------------------------- */
/* The assist response                                                         */
/* -------------------------------------------------------------------------- */

export const REVIEW_ASSIST_OUTCOMES = [
    'suggested', 'content_filtered', 'not_found', 'locked', 'no_suggestion', 'not_analyzed', 'record_changed',
    'save_failed', 'too_large', 'deferred',
] as const;
/**
 * What happened to one record: the server's outcomes, and `failed` for a request that failed as a
 * whole. `deferred` means the server ran out of time before it reached the record; a triage sends
 * it again, so it never ends a run.
 */
export type ReviewAssistOutcome = (typeof REVIEW_ASSIST_OUTCOMES)[number] | 'failed';

export interface ReviewAssistResult {
    id: string;
    outcome: ReviewAssistOutcome;
    suggestion: AnySuggestion | null;
    message: string;
    code: string | null;
}

export type ReviewAssistMode = 'analyze' | 'triage';

/**
 * The results of one assist request, checked against what was asked: the same section and mode,
 * one result per requested id in the same order, a known outcome, and a readable suggestion with
 * every `suggested` record. Null when any of that does not hold.
 */
export function parseReviewAssistResponse(
    section: ReviewSectionId,
    mode: ReviewAssistMode,
    value: unknown,
    requestedIds: readonly string[],
): ReviewAssistResult[] | null {
    if (!isRecord(value) || value.section !== section || value.mode !== mode || !Array.isArray(value.results)) return null;
    if (value.results.length !== requestedIds.length) return null;
    const results: ReviewAssistResult[] = [];
    for (const [index, raw] of value.results.entries()) {
        if (!isRecord(raw) || raw.id !== requestedIds[index]) return null;
        const outcome = raw.outcome;
        if (typeof outcome !== 'string' || !(REVIEW_ASSIST_OUTCOMES as readonly string[]).includes(outcome)) return null;
        let suggestion: AnySuggestion | null = null;
        if (outcome === 'suggested') {
            suggestion = parseSuggestion(section, raw.suggestion);
            const expected = mode === 'analyze' ? 'unsaved' : 'pending';
            if (!suggestion || suggestion.status !== expected) return null;
        }
        results.push({
            id: requestedIds[index],
            outcome: outcome as ReviewAssistOutcome,
            suggestion,
            message: textOrNull(raw.message, SERVER_TEXT_LIMIT) ?? '',
            code: typeof raw.code === 'string' && CODE.test(raw.code) ? raw.code : null,
        });
    }
    return results;
}

export interface ReviewAssistFailure {
    status: number;
    code: string;
    message: string;
    retryAfterSeconds: number | null;
}

const STATUS_FALLBACKS: Readonly<Record<number, string>> = {
    400: "The assistant couldn't use this request. Nothing was suggested.",
    401: 'Your session expired. Sign in again to use AI assist.',
    403: "AI assist isn't available to you right now.",
    413: 'This request is too large for the assistant.',
    429: 'The assistant is busy. Wait a moment, then try again.',
    500: 'The assistant failed. Nothing was suggested. Try again.',
    502: "The assistant's answer couldn't be used. Nothing was suggested. Try again.",
    503: 'The assistant is unavailable right now. Try again later.',
};
const MAX_RETRY_AFTER_SECONDS = 3600;

function clampRetryAfter(seconds: number): number {
    return Math.min(MAX_RETRY_AFTER_SECONDS, Math.max(1, Math.ceil(seconds)));
}

/** Seconds to wait, from a `Retry-After` header (seconds or an HTTP date), or else the body. */
export function reviewAssistRetryAfter(header: string | null, body: unknown, now = Date.now()): number | null {
    const text = (header ?? '').trim();
    if (/^\d{1,10}$/.test(text)) return clampRetryAfter(Number(text));
    if (text) {
        const date = Date.parse(text);
        if (!Number.isNaN(date)) return clampRetryAfter((date - now) / 1000);
    }
    const seconds = isRecord(body) ? body.retry_after_seconds : undefined;
    return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0 ? clampRetryAfter(seconds) : null;
}

/** What a failed assist request means for the reader. The server's text is shown as plain text. */
export function describeReviewAssistFailure(status: number, body: unknown, retryAfterHeader: string | null = null): ReviewAssistFailure {
    const code = isRecord(body) && typeof body.code === 'string' && CODE.test(body.code) ? body.code : '';
    const fallback = STATUS_FALLBACKS[status] ?? `The assistant request failed (status ${status}). Nothing was suggested.`;
    // A rate-limit answer carries the administrator's Markdown message; the fallback reads better here.
    const serverText = isRecord(body) && code !== 'assistant_rate_limited' ? textOrNull(body.error, SERVER_TEXT_LIMIT) : null;
    const retryAfterSeconds = status === 429 || status === 503 ? reviewAssistRetryAfter(retryAfterHeader, body) : null;
    return {
        status,
        code,
        message: serverText || fallback,
        retryAfterSeconds: status === 429 && retryAfterSeconds === null ? 1 : retryAfterSeconds,
    };
}

/* -------------------------------------------------------------------------- */
/* What a suggestion would change                                              */
/* -------------------------------------------------------------------------- */

export interface SuggestionChange {
    field: string;
    label: string;
    /** A short description of the new value, or a before and after. */
    detail: string;
}

function yesNo(value: boolean): string {
    return value ? 'Yes' : 'No';
}

function sameText(left: string | null | undefined, right: string | null | undefined): boolean {
    return (left ?? '').trim() === (right ?? '').trim();
}

/** What applying a feedback suggestion changes in the stored review. */
export function feedbackSuggestionChanges(record: FeedbackRecord, payload: FeedbackSuggestionPayload): SuggestionChange[] {
    const review = record.adminReview ?? {};
    const changes: SuggestionChange[] = [];
    if (Boolean(review.acknowledged) !== payload.acknowledged) {
        changes.push({ field: 'acknowledged', label: 'Acknowledged', detail: `${yesNo(Boolean(review.acknowledged))} → ${yesNo(payload.acknowledged)}` });
    }
    const currentTheme = review.theme;
    if (currentTheme !== payload.theme) {
        changes.push({ field: 'theme', label: 'Theme', detail: `${feedbackThemeLabel(currentTheme)} → ${feedbackThemeLabel(payload.theme)}` });
    }
    if (!sameText(review.analysisNotes, payload.analysisNotes)) {
        changes.push({ field: 'analysisNotes', label: 'Analysis notes', detail: reviewExcerpt(payload.analysisNotes, 80) || 'Cleared' });
    }
    if (!sameText(review.actionTaken, payload.actionTaken)) {
        changes.push({ field: 'actionTaken', label: 'Action taken', detail: reviewExcerpt(payload.actionTaken, 80) || 'Cleared' });
    }
    if (!sameText(review.responseToUser, payload.responseToUser)) {
        changes.push({ field: 'responseToUser', label: 'Response to the user', detail: reviewExcerpt(payload.responseToUser, 80) || 'Cleared' });
    }
    if (payload.archive && !record.isArchived) {
        changes.push({ field: 'archive', label: 'Archive', detail: 'Moves it out of the active list' });
    }
    return changes;
}

/** Whether applying a safety suggestion sends the user a warning now. A warning already sent is not sent again. */
export function sendsWarning(record: SafetyRecord, payload: SafetySuggestionPayload): boolean {
    if (payload.action !== 'WarnUser') return false;
    return !(record.action === 'WarnUser' && safetyRequestState(record) === 'executed');
}

/** Whether applying a safety suggestion asks a second reviewer to approve a suspension or block. */
export function requestsRestriction(record: SafetyRecord, payload: SafetySuggestionPayload): boolean {
    return APPROVAL_REQUIRED_ACTIONS.has(payload.action) && payload.action !== (record.action || 'None');
}

export function isRestrictiveSuggestion(payload: SafetySuggestionPayload): boolean {
    return APPROVAL_REQUIRED_ACTIONS.has(payload.action);
}

/**
 * Whether a suspension or block suggestion repeats the one the violation already records. Applying
 * it updates the review only: a restriction is requested again only when a reviewer asks for that
 * explicitly in the violation's editor, never by applying a suggestion.
 */
export function repeatsRestriction(record: SafetyRecord, payload: SafetySuggestionPayload): boolean {
    return APPROVAL_REQUIRED_ACTIONS.has(payload.action) && payload.action === (record.action || 'None');
}

const RESTRICTION_STANDING: Readonly<Record<string, string>> = {
    executed: 'was approved and applied',
    denied: 'request was denied',
    expired: 'request expired without a decision',
    failed: 'was approved but could not be applied',
};

/**
 * What approving a suggestion that repeats the violation's suspension or block does, by where
 * its last request stands. The queue never asks for it again; only the violation's editor can.
 */
export function repeatedRestrictionText(record: SafetyRecord, action: string): string {
    const noun = action === 'BlockUser' ? 'block' : 'suspension';
    const standing = RESTRICTION_STANDING[safetyRequestState(record)];
    const lead = standing ? `This ${noun} ${standing}.` : `This violation already records a ${noun}.`;
    return `${lead} Approving updates the review only and requests nothing new. To ask another eligible reviewer to approve it again, open the violation and select "Request this ${noun} again".`;
}

/** What a refused approval or dismissal means for its row, in the reviewer's terms. */
export function suggestionFailureText(code: string | null | undefined, fallback: string): string {
    if (code === 'record_changed') {
        return 'The record changed since this suggestion was shown, so nothing was saved. Reload the queue, or triage the record again for a current suggestion.';
    }
    if (code === 'suggestion_stale') {
        return 'The record changed after the suggestion was made, so it no longer fits. Dismiss it, or triage the record again.';
    }
    if (code === 'suggestion_not_pending') return 'This suggestion was already applied, dismissed or replaced.';
    return fallback;
}

function actionChangeLabel(payload: SafetySuggestionPayload): string {
    if (payload.action === 'SuspendUser' && payload.suspendDuration) {
        return `Suspend user for ${SUSPEND_DURATION_LABELS[payload.suspendDuration]}`;
    }
    return safetyActionLabel(payload.action);
}

/** What applying a safety suggestion changes in the stored review, and what it sets off. */
export function safetySuggestionChanges(record: SafetyRecord, payload: SafetySuggestionPayload): SuggestionChange[] {
    const changes: SuggestionChange[] = [];
    const status = record.status || 'New';
    if (status !== payload.status) {
        changes.push({ field: 'status', label: 'Status', detail: `${status} → ${payload.status}` });
    }
    const action = record.action || 'None';
    if (action !== payload.action) {
        changes.push({ field: 'action', label: actionChangeLabel(payload), detail: `${safetyActionLabel(action)} → ${safetyActionLabel(payload.action)}` });
    }
    if (!sameText(record.notes, payload.notes)) {
        changes.push({ field: 'notes', label: 'Notes', detail: reviewExcerpt(payload.notes, 80) || 'Cleared' });
    }
    if (sendsWarning(record, payload) || requestsRestriction(record, payload)) {
        changes.push({
            field: 'notification',
            label: 'Notification',
            detail: reviewExcerpt(payload.notificationTitle, 60) || 'The standard notification',
        });
    }
    if (payload.archive && !record.isArchived) {
        changes.push({ field: 'archive', label: 'Archive', detail: 'Moves it out of the active list' });
    }
    return changes;
}

/** One line for a queue row, such as "Status New → Resolved · Warn user · Notes: A hateful remark". */
export function suggestionSummary(changes: readonly SuggestionChange[]): string {
    if (!changes.length) return 'Leaves the review as it is';
    return changes.map((change) => {
        if (change.field === 'action') return change.label;
        if (change.field === 'status' || change.field === 'acknowledged' || change.field === 'theme') {
            return `${change.label} ${change.detail}`;
        }
        if (change.field === 'archive') return 'Archive';
        return `${change.label}: ${change.detail}`;
    }).join(' · ');
}

/* -------------------------------------------------------------------------- */
/* The suggestions queue                                                       */
/* -------------------------------------------------------------------------- */

/** One field of a suggestion that its record's user can read once it is applied. */
export interface UserVisibleText {
    field: string;
    label: string;
    /** The whole text the user would read; empty when the suggestion clears the field. */
    text: string;
    /** The suggestion empties a field the user can read something in now. */
    cleared: boolean;
}

function visibleField(
    items: UserVisibleText[],
    field: string,
    label: string,
    next: string | null | undefined,
    current: string | null | undefined,
) {
    if (next && next.trim()) items.push({ field, label, text: next, cleared: false });
    else if (current && current.trim()) items.push({ field, label, text: '', cleared: true });
}

/**
 * The text a suggestion saves that its record's user can read, in full: a feedback review's analysis
 * notes, action taken and response to the user, which the user reads with their feedback, and a
 * violation's notes, which the user can read in their violations and the export of them. A warning,
 * suspension or block's notification is shown on its own, where it can be edited.
 */
export function userVisibleText(entry: QueueEntry): UserVisibleText[] {
    const items: UserVisibleText[] = [];
    if (entry.section === 'feedback') {
        const payload = (entry.suggestion as FeedbackSuggestion).payload;
        const review = (entry.record as FeedbackRecord).adminReview ?? {};
        visibleField(items, 'analysisNotes', 'Analysis notes', payload.analysisNotes, review.analysisNotes);
        visibleField(items, 'actionTaken', 'Action taken', payload.actionTaken, review.actionTaken);
        visibleField(items, 'responseToUser', 'Response to the user', payload.responseToUser, review.responseToUser);
    } else {
        visibleField(items, 'notes', 'Notes', (entry.suggestion as SafetySuggestion).payload.notes, (entry.record as SafetyRecord).notes);
    }
    return items;
}

/** A queue row: ready to apply, stale because its record changed, or locked by a request in progress. */
export type SuggestionRowState = 'ready' | 'stale' | 'locked';

export function suggestionRowState(
    section: ReviewSectionId,
    record: FeedbackRecord | SafetyRecord,
    suggestion: AnySuggestion,
): SuggestionRowState {
    if (suggestion.status === 'stale') return 'stale';
    if (section === 'safety' && isSafetyRecordLocked(record as SafetyRecord)) return 'locked';
    return 'ready';
}

export interface QueueEntry {
    id: string;
    section: ReviewSectionId;
    record: FeedbackRecord | SafetyRecord;
    suggestion: AnySuggestion;
    state: SuggestionRowState;
}

export function queueEntryRestrictive(entry: QueueEntry): boolean {
    return entry.section === 'safety' && isRestrictiveSuggestion((entry.suggestion as SafetySuggestion).payload);
}

/** "Approve all": the ready suggestions that restrict nobody. Suspensions and blocks are ticked one by one. */
export function approveAllIds(entries: readonly QueueEntry[]): string[] {
    return entries.filter((entry) => entry.state === 'ready' && !queueEntryRestrictive(entry)).map((entry) => entry.id);
}

export interface ApprovalPlan {
    ids: string[];
    skipped: { id: string; reason: string }[];
    /** Users who are sent a warning as soon as the suggestions are applied. */
    warnings: number;
    /** Suspension and block requests created, each waiting for a second reviewer. */
    restrictions: number;
    /** Suspensions and blocks the violation already records: applying updates the review only. */
    repeats: number;
    archives: number;
    /** Reviews that save text their record's user can read. */
    userVisible: number;
}

/**
 * Which of the requested suggestions an approval applies. Stale and locked suggestions are never
 * applied; "Approve all" also leaves out suspensions and blocks, which only an individual tick
 * approves.
 */
export function planApproval(entries: readonly QueueEntry[], ids: readonly string[], mode: 'all' | 'selected'): ApprovalPlan {
    const byId = new Map(entries.map((entry) => [entry.id, entry]));
    const plan: ApprovalPlan = { ids: [], skipped: [], warnings: 0, restrictions: 0, repeats: 0, archives: 0, userVisible: 0 };
    for (const id of ids) {
        const entry = byId.get(id);
        if (!entry) {
            plan.skipped.push({ id, reason: 'It is no longer in the queue.' });
            continue;
        }
        if (entry.state === 'stale') {
            plan.skipped.push({ id, reason: 'The record changed after the suggestion was made.' });
            continue;
        }
        if (entry.state === 'locked') {
            plan.skipped.push({ id, reason: 'A request in progress holds the record.' });
            continue;
        }
        if (mode === 'all' && queueEntryRestrictive(entry)) {
            plan.skipped.push({ id, reason: 'A suspension or block is approved one at a time.' });
            continue;
        }
        plan.ids.push(id);
        if (userVisibleText(entry).some((item) => !item.cleared)) plan.userVisible += 1;
        if (entry.section === 'safety') {
            const record = entry.record as SafetyRecord;
            const payload = (entry.suggestion as SafetySuggestion).payload;
            if (sendsWarning(record, payload)) plan.warnings += 1;
            if (requestsRestriction(record, payload)) plan.restrictions += 1;
            if (repeatsRestriction(record, payload)) plan.repeats += 1;
            if (payload.archive && !record.isArchived) plan.archives += 1;
        } else {
            const payload = (entry.suggestion as FeedbackSuggestion).payload;
            if (payload.archive && !entry.record.isArchived) plan.archives += 1;
        }
    }
    return plan;
}

function plural(count: number, one: string, many: string): string {
    return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

/** The confirmation an approval asks for: how many suggestions, and what they set off. */
export function approvalConfirmation(
    plan: ApprovalPlan,
    noun: { singular: string; plural: string },
): { title: string; description: string; confirmLabel: string } {
    const count = plural(plan.ids.length, 'suggestion', 'suggestions');
    const parts = [`Each is saved as your review of its ${noun.singular}, through the same checks as saving it yourself.`];
    if (plan.warnings) parts.push(`${plural(plan.warnings, 'user is', 'users are')} sent a warning straight away.`);
    if (plan.restrictions) {
        parts.push(`${plural(plan.restrictions, 'suspension or block is', 'suspensions or blocks are')} requested; each applies only after another eligible reviewer approves it.`);
    }
    if (plan.repeats) {
        parts.push(`${plural(plan.repeats, 'suspension or block is', 'suspensions or blocks are')} already on ${plan.repeats === 1 ? 'its violation' : 'their violations'}, so nothing new is requested for ${plan.repeats === 1 ? 'it' : 'them'}.`);
    }
    if (plan.archives) parts.push(`${plural(plan.archives, noun.singular, noun.plural)} will be archived.`);
    if (plan.userVisible) {
        parts.push(plan.userVisible === 1
            ? '1 review saves text its user can read; check it under "Visible to the user".'
            : `${plan.userVisible.toLocaleString()} reviews save text their users can read; check it under "Visible to the user".`);
    }
    if (plan.skipped.length) parts.push(`${plural(plan.skipped.length, 'suggestion is', 'suggestions are')} left in the queue.`);
    return { title: `Apply ${count}?`, description: parts.join(' '), confirmLabel: `Apply ${count}` };
}

export interface SuggestionOperation {
    id: string;
    op: 'update';
    suggestion_id: string;
    etag?: string;
    changes: Record<string, unknown>;
}

export interface NotificationOverride {
    title?: string;
    message?: string;
}

/** The save that applies a suggestion, with the reviewer's edits to the notification. */
export function buildSuggestionOperation(
    entry: QueueEntry,
    override: NotificationOverride | undefined,
    now: Date = new Date(),
): SuggestionOperation | null {
    const { suggestion } = entry;
    if (!suggestion.id) return null;
    let changes: Record<string, unknown>;
    if (entry.section === 'safety') {
        const payload = (suggestion as SafetySuggestion).payload;
        changes = { status: payload.status, action: payload.action, notes: payload.notes };
        if (payload.action !== 'None') {
            changes.notification_title = (override?.title ?? payload.notificationTitle ?? '').trim();
            changes.notification_message = (override?.message ?? payload.notificationMessage ?? '').trim();
        }
        if (payload.action === 'SuspendUser' && payload.suspendDuration) {
            changes.datetime_to_allow = suspendPresetUntil(payload.suspendDuration, now)?.toISOString();
        }
    } else {
        const payload = (suggestion as FeedbackSuggestion).payload;
        changes = {
            acknowledged: payload.acknowledged,
            analysisNotes: payload.analysisNotes,
            actionTaken: payload.actionTaken,
            responseToUser: payload.responseToUser,
            theme: payload.theme,
        };
    }
    const record = entry.record as { etag?: string; fingerprint?: string };
    // The fingerprint lets the save go ahead when only bookkeeping, such as another AI suggestion
    // operation, changed the record's version since the queue read it.
    if (typeof record.fingerprint === 'string' && record.fingerprint) changes.fingerprint = record.fingerprint;
    return { id: entry.id, op: 'update', suggestion_id: suggestion.id, ...(record.etag ? { etag: record.etag } : {}), changes };
}

/** The archives that follow applied suggestions which also suggested archiving. */
export function archiveFollowUps(
    entries: readonly QueueEntry[],
    applied: readonly string[],
): { id: string; op: 'archive'; archived: true }[] {
    const done = new Set(applied);
    return entries
        .filter((entry) => done.has(entry.id) && entry.suggestion.payload.archive && !entry.record.isArchived)
        .map((entry) => ({ id: entry.id, op: 'archive', archived: true }));
}

/* -------------------------------------------------------------------------- */
/* Applying a suggestion to an editor's draft                                  */
/* -------------------------------------------------------------------------- */

/** Draft fields that change together, such as an action and its notification. */
export interface DraftGroup<D> {
    label: string;
    keys: readonly (keyof D)[];
}

/** The groups a suggestion changed when it was applied to the draft. */
export function changedDraftGroups<D>(before: D, after: D, groups: readonly DraftGroup<D>[]): DraftGroup<D>[] {
    return groups.filter((group) => group.keys.some((key) => !Object.is(before[key], after[key])));
}

/** Whether a field still holds what the suggestion put there, so the editor marks it. */
export function draftKeyMarked<D>(current: D, before: D, after: D, key: keyof D): boolean {
    return !Object.is(before[key], after[key]) && Object.is(current[key], after[key]);
}

/**
 * Undo an applied suggestion: each group it changed goes back to what it was, unless the reviewer
 * has changed that group since, which is kept and reported as skipped.
 */
export function undoDraftGroups<D>(
    current: D,
    before: D,
    after: D,
    groups: readonly DraftGroup<D>[],
): { draft: D; reverted: string[]; skipped: string[] } {
    const draft = { ...current };
    const reverted: string[] = [];
    const skipped: string[] = [];
    for (const group of changedDraftGroups(before, after, groups)) {
        if (group.keys.every((key) => Object.is(current[key], after[key]))) {
            for (const key of group.keys) draft[key] = before[key];
            reverted.push(group.label);
        } else {
            skipped.push(group.label);
        }
    }
    return { draft, reverted, skipped };
}

/** The sentence an undo leaves in the panel. */
export function undoReportText(reverted: readonly string[], skipped: readonly string[]): string {
    const parts = [];
    if (reverted.length) parts.push(`Undone: ${reverted.join(', ')}.`);
    if (skipped.length) parts.push(`Kept because you changed ${skipped.length === 1 ? 'it' : 'them'} since: ${skipped.join(', ')}.`);
    return parts.join(' ') || 'Nothing to undo.';
}

/* -------------------------------------------------------------------------- */
/* Triage                                                                      */
/* -------------------------------------------------------------------------- */

export type TriagePostResult =
    | { ok: true; results: ReviewAssistResult[] }
    | { ok: false; aborted: true }
    | { ok: false; aborted?: false; failure: ReviewAssistFailure };

export interface TriageProgress {
    done: number;
    total: number;
    /** Seconds left to wait for the rate limit, or null while working. */
    waitingSeconds: number | null;
}

export interface TriageRun {
    results: ReviewAssistResult[];
    cancelled: boolean;
    /** Why the triage stopped before the end, or null. */
    stopped: ReviewAssistFailure | null;
    /** Ids never sent, because the triage was cancelled or stopped. */
    unprocessed: string[];
}

export function chunkTriageIds(ids: readonly string[], size = REVIEW_TRIAGE_CHUNK): string[][] {
    const chunks: string[][] = [];
    for (let start = 0; start < ids.length; start += size) chunks.push(ids.slice(start, start + size));
    return chunks;
}

const TRIAGE_NOT_REACHED = "The assistant didn't reach this record. Triage it again.";

/**
 * Triage chunks of at most `size` records that keep each user's records together. The server asks
 * the model about one user's records at a time, so a chunk spread over fewer users needs fewer
 * model calls. A record whose user isn't known is a group of its own. A user with more than `size`
 * records fills whole chunks; every other group goes in the first chunk with room for all of it.
 */
export function planTriageChunks(
    ids: readonly string[],
    ownerOf: ((id: string) => string | null | undefined) | undefined,
    size = REVIEW_TRIAGE_CHUNK,
): string[][] {
    const groups = new Map<string, string[]>();
    for (const id of new Set(ids)) {
        const owner = ownerOf?.(id);
        const key = typeof owner === 'string' && owner ? `owner:${owner}` : `record:${id}`;
        const group = groups.get(key);
        if (group) group.push(id);
        else groups.set(key, [id]);
    }
    const chunks: string[][] = [];
    for (const group of groups.values()) {
        for (let start = 0; start < group.length; start += size) {
            const piece = group.slice(start, start + size);
            const roomy = chunks.find((chunk) => chunk.length + piece.length <= size);
            if (roomy) roomy.push(...piece);
            else chunks.push(piece);
        }
    }
    return chunks;
}

/** Wait `seconds`, a second at a time, unless the signal aborts first. Resolves false when aborted. */
export function waitSeconds(
    seconds: number,
    signal: AbortSignal,
    onTick: (left: number) => void,
    sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<boolean> {
    return (async () => {
        for (let left = seconds; left > 0; left -= 1) {
            if (signal.aborted) return false;
            onTick(left);
            await sleep(1000);
        }
        return !signal.aborted;
    })();
}

function failed(ids: readonly string[], failure: ReviewAssistFailure): ReviewAssistResult[] {
    return ids.map((id) => ({ id, outcome: 'failed', suggestion: null, message: failure.message, code: failure.code || null }));
}

/** How many times a triage waits out the assistant for one chunk before it stops. */
export const REVIEW_TRIAGE_MAX_WAITS = 3;

/**
 * The seconds to wait before sending a chunk again, or null when its answer is not worth waiting
 * out: it succeeded, was cancelled, failed for good, or asks for a longer wait than the triage
 * accepts. Only a rate limit, or a brief outage other than the limiter's own, is waited out.
 */
export function triageRetryWait(answer: TriagePostResult, maxWaitSeconds: number): number | null {
    if (answer.ok || ('aborted' in answer && answer.aborted)) return null;
    const { failure } = answer as { failure: ReviewAssistFailure };
    const transient = failure.status === 429 || (failure.status === 503 && failure.code !== 'assistant_limit_unavailable');
    const wait = failure.retryAfterSeconds;
    return transient && wait !== null && wait <= maxWaitSeconds ? wait : null;
}

/**
 * Triage `ids` ten at a time, one request after another, each user's records kept together (see
 * `planTriageChunks`). A rate-limited or briefly unavailable assistant is waited for, up to
 * `maxWaitSeconds` and `REVIEW_TRIAGE_MAX_WAITS` times per chunk; an answer that can't be used
 * fails only its own chunk. Records the server answers `deferred`, because it ran out of time
 * before it reached them, are sent again next. Anything else stops the run, and so does the
 * signal: the records not yet sent are returned as unprocessed.
 */
export async function runTriage({
    ids,
    post,
    signal,
    onProgress,
    sleep,
    ownerOf,
    maxWaitSeconds = REVIEW_TRIAGE_MAX_WAIT_SECONDS,
    chunkSize = REVIEW_TRIAGE_CHUNK,
}: {
    ids: readonly string[];
    post: (chunk: string[], signal: AbortSignal) => Promise<TriagePostResult>;
    signal: AbortSignal;
    onProgress?: (progress: TriageProgress) => void;
    sleep?: (ms: number) => Promise<void>;
    /** The user a record is about, when the page knows it. */
    ownerOf?: (id: string) => string | null | undefined;
    maxWaitSeconds?: number;
    chunkSize?: number;
}): Promise<TriageRun> {
    const queue = planTriageChunks(ids, ownerOf, chunkSize);
    const run: TriageRun = { results: [], cancelled: false, stopped: null, unprocessed: [] };
    const total = queue.reduce((count, chunk) => count + chunk.length, 0);
    const report = (waitingSeconds: number | null) => onProgress?.({ done: run.results.length, total, waitingSeconds });

    /** Send one chunk, waiting out a rate limit or a brief outage as `triageRetryWait` allows. */
    const send = async (chunk: string[]): Promise<TriagePostResult> => {
        let answer = await post(chunk, signal);
        let wait = triageRetryWait(answer, maxWaitSeconds);
        for (let waits = 0; wait !== null && waits < REVIEW_TRIAGE_MAX_WAITS; waits += 1) {
            const waited = await waitSeconds(wait, signal, report, sleep);
            report(null);
            if (!waited) return { ok: false, aborted: true };
            answer = await post(chunk, signal);
            wait = triageRetryWait(answer, maxWaitSeconds);
        }
        return answer;
    };

    report(null);
    while (queue.length) {
        if (signal.aborted) {
            run.cancelled = true;
            break;
        }
        const chunk = queue[0];
        const answer = await send(chunk);
        if (answer.ok) {
            const deferred = answer.results.filter((result) => result.outcome === 'deferred');
            const answered = answer.results.filter((result) => result.outcome !== 'deferred');
            if (deferred.length && !answered.length) {
                // The server always answers at least one record; never send the same chunk forever.
                run.results.push(...deferred.map((result) => ({ ...result, outcome: 'failed' as const, message: TRIAGE_NOT_REACHED })));
            } else {
                run.results.push(...answered);
                if (deferred.length) queue.splice(1, 0, deferred.map((result) => result.id));
            }
        } else if ('aborted' in answer && answer.aborted) {
            run.cancelled = true;
            break;
        } else {
            const { failure } = answer as { failure: ReviewAssistFailure };
            if (failure.status !== 502) {
                // Anything but an unusable answer -- a refusal, an outage, a wait too long or
                // waited out too often -- stops the run.
                run.stopped = failure;
                break;
            }
            run.results.push(...failed(chunk, failure));
        }
        queue.shift();
        report(null);
    }
    // Empty after a full run; after a cancel or stop, the chunk in hand and every one after it.
    run.unprocessed = queue.flat();
    return run;
}

export interface TriageReport {
    summary: string;
    failures: { id: string; label: string; message: string }[];
    tone: 'ok' | 'warn';
    suggested: number;
}

/**
 * The records a triage made no suggestion for, including any it never sent, in the order they
 * were triaged. The workbench leaves them checked, as it does the records a bulk action couldn't
 * change, so they can be tried again or dealt with by hand.
 */
export function triageRetryIds(run: TriageRun): string[] {
    const ids = run.results.filter((result) => result.outcome !== 'suggested').map((result) => result.id);
    return [...new Set([...ids, ...run.unprocessed])];
}

/** What a triage did, for the report under the bulk bar. */
export function buildTriageReport(
    run: TriageRun,
    noun: { singular: string; plural: string },
    describe: (id: string) => string,
): TriageReport {
    const suggested = run.results.filter((result) => result.outcome === 'suggested').length;
    const total = run.results.length + run.unprocessed.length;
    const parts = [`AI suggested reviews for ${suggested.toLocaleString()} of ${plural(total, noun.singular, noun.plural)}.`];
    if (run.cancelled) parts.push(`Cancelled; ${plural(run.unprocessed.length, noun.singular, noun.plural)} not sent.`);
    else if (run.stopped) parts.push(`Stopped: ${run.stopped.message}`);
    if (suggested) parts.push('Nothing changes until you approve them in the AI suggestions queue.');
    const failures = run.results
        .filter((result) => result.outcome !== 'suggested')
        .map((result) => ({ id: result.id, label: describe(result.id), message: result.message || 'No suggestion was made.' }));
    return {
        summary: parts.join(' '),
        failures,
        tone: failures.length || run.cancelled || run.stopped ? 'warn' : 'ok',
        suggested,
    };
}
