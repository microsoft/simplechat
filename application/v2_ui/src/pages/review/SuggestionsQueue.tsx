// SuggestionsQueue.tsx
// A Review center section's AI suggestions queue: every record with an AI suggestion still waiting
// for a reviewer, what it would change and why, to approve or dismiss.
//
// Approving a suggestion saves it as the reviewer's own review, through the same bulk save and the
// same rules as any other save: a warning is sent at once, a suspension or block creates an approval
// request another reviewer must decide, and a record that changed underneath is refused. "Approve
// all" leaves suspensions and blocks out; each is approved with its own tick, and selecting the
// whole page never ticks one. A suggestion whose record changed since is stale and can only be
// dismissed; a violation held by a request in progress waits. Every approval says first how many
// users it warns and how many requests it creates, and afterwards what happened to each record.

import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Ban, CheckCheck, Sparkles, X } from 'lucide-react';
import { ReviewBulkBar, type BulkRunProgress, type BulkRunReport } from '../../components/review/ReviewBulkBar';
import { ReviewNotice, ReviewPager, ToneBadge } from '../../components/review/ReviewParts';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { EmptyState, GlassButton, Skeleton } from '../../components/ui/primitives';
import type { ReviewSectionId } from '../../lib/reviewAccess';
import {
    buildBulkReport,
    countLabel,
    feedbackRowMeta,
    feedbackRowTitle,
    readReviewPaging,
    safeReviewRecordHref,
    safetyRowMeta,
    safetyRowTitle,
    type FeedbackRecord,
    type ReviewBulkResult,
    type SafetyRecord,
} from '../../lib/reviewCenter';
import { bulkFeedback, bulkSafety, errorText, fetchSuggestionsPage, type BulkOperation } from '../../lib/reviewCenterApi';
import {
    approvalConfirmation,
    approveAllIds,
    archiveFollowUps,
    buildSuggestionOperation,
    feedbackSuggestionChanges,
    parseSuggestion,
    planApproval,
    queueEntryRestrictive,
    requestsRestriction,
    safetySuggestionChanges,
    sendsWarning,
    SUGGESTION_LIMITS,
    suggestionRowState,
    suggestionSummary,
    type ApprovalPlan,
    type FeedbackSuggestion,
    type NotificationOverride,
    type QueueEntry,
    type SafetySuggestion,
} from '../../lib/reviewSuggestions';

type QueueRecord = FeedbackRecord | SafetyRecord;
type RowResult = { tone: 'ok' | 'warn' | 'danger'; message: string };
type Pending =
    | { kind: 'approve'; plan: ApprovalPlan }
    | { kind: 'dismiss'; ids: string[] };

const FIELD_CLASS = 'w-full rounded-lg border border-edge bg-surface-0 px-2.5 py-1.5 text-sm text-text-1 focus:border-accent focus:outline-none';
const SUGGESTION_NOUN = { singular: 'suggestion', plural: 'suggestions' };
const NOUNS: Readonly<Record<ReviewSectionId, { singular: string; plural: string }>> = {
    feedback: { singular: 'feedback record', plural: 'feedback records' },
    safety: { singular: 'violation', plural: 'violations' },
};
const CONFIDENCE_LABELS = { low: 'Low confidence', medium: 'Medium confidence', high: 'High confidence' } as const;

function rowTitle(entry: QueueEntry): string {
    return entry.section === 'safety' ? safetyRowTitle(entry.record as SafetyRecord) : feedbackRowTitle(entry.record as FeedbackRecord);
}

function rowMeta(entry: QueueEntry): string {
    return entry.section === 'safety' ? safetyRowMeta(entry.record as SafetyRecord) : feedbackRowMeta(entry.record as FeedbackRecord);
}

function changesOf(entry: QueueEntry) {
    return entry.section === 'safety'
        ? safetySuggestionChanges(entry.record as SafetyRecord, (entry.suggestion as SafetySuggestion).payload)
        : feedbackSuggestionChanges(entry.record as FeedbackRecord, (entry.suggestion as FeedbackSuggestion).payload);
}

/** Whether applying the row sends the user something, so its notification is shown for editing. */
function notifies(entry: QueueEntry): boolean {
    if (entry.section !== 'safety') return false;
    const record = entry.record as SafetyRecord;
    const payload = (entry.suggestion as SafetySuggestion).payload;
    return sendsWarning(record, payload) || requestsRestriction(record, payload);
}

function resultMessage(result: ReviewBulkResult): string {
    if (!result.ok) return result.error || result.message || 'The suggestion could not be applied.';
    return (typeof result.message === 'string' && result.message) || 'Review saved.';
}

function SuggestionRow({
    entry,
    checked,
    busy,
    override,
    result,
    backParams,
    onToggle,
    onOverride,
    onApprove,
    onDismiss,
}: {
    entry: QueueEntry;
    checked: boolean;
    busy: boolean;
    override: NotificationOverride | undefined;
    result: RowResult | undefined;
    backParams: URLSearchParams;
    onToggle: () => void;
    onOverride: (override: NotificationOverride) => void;
    onApprove: () => void;
    onDismiss: () => void;
}) {
    const { suggestion, state, section, id } = entry;
    const title = rowTitle(entry);
    const restrictive = queueEntryRestrictive(entry);
    const safety = section === 'safety' ? (suggestion as SafetySuggestion).payload : null;
    const warns = safety ? sendsWarning(entry.record as SafetyRecord, safety) : false;
    const testId = `v2-${section}-suggestion-${id}`;
    return (
        <li data-testid={testId} data-state={state}
            className="rounded-2xl border border-edge bg-surface-1 p-3 shadow-sm sm:p-4">
            <div className="flex flex-wrap items-start gap-3">
                <input
                    type="checkbox"
                    aria-label={`Select the suggestion for ${title}`}
                    checked={checked}
                    onChange={onToggle}
                    disabled={busy}
                    data-testid={`${testId}-check`}
                    className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-accent)]"
                />
                <div className="min-w-0 flex-[1_1_18rem] space-y-1.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                        <Link to={safeReviewRecordHref(section, id, backParams)}
                            className="min-w-0 break-words text-sm font-semibold text-text-1 hover:text-accent">
                            {title}
                        </Link>
                        {state === 'stale' ? <ToneBadge tone="warn">Out of date</ToneBadge> : null}
                        {state === 'locked' ? <ToneBadge tone="info">Held by a request</ToneBadge> : null}
                        {restrictive ? <ToneBadge tone="danger">Needs a second reviewer</ToneBadge> : null}
                        {warns ? <ToneBadge tone="warn">Sends a warning</ToneBadge> : null}
                        {suggestion.confidence ? <ToneBadge tone="neutral">{CONFIDENCE_LABELS[suggestion.confidence]}</ToneBadge> : null}
                    </div>
                    <p className="text-xs text-text-3">{rowMeta(entry)}</p>
                    <p className="break-words text-sm text-text-1" data-testid={`${testId}-summary`}>
                        <Sparkles size={13} aria-hidden="true" className="mr-1 inline text-change-ai" />
                        {suggestionSummary(changesOf(entry))}
                    </p>
                    {suggestion.rationale ? (
                        <p className="break-words text-xs text-text-2">
                            <span className="font-medium text-text-1">Why the AI suggests this: </span>{suggestion.rationale}
                        </p>
                    ) : null}
                    {state === 'stale' ? (
                        <p className="text-xs text-text-2">
                            The record changed after this suggestion was made, so it can no longer be applied. Dismiss it,
                            or triage the record again.
                        </p>
                    ) : null}
                    {state === 'locked' ? (
                        <p className="text-xs text-text-2">
                            A remediation request waiting for approval, or a warning being sent, holds this violation.
                            Approve this suggestion once that settles, or dismiss it.
                        </p>
                    ) : null}
                    {safety && notifies(entry) && state === 'ready' ? (
                        <fieldset className="space-y-1.5 rounded-xl bg-surface-2 p-2.5" disabled={busy}>
                            <legend className="sr-only">The notification the user receives</legend>
                            <p className="text-xs font-medium text-text-1">
                                {restrictive
                                    ? 'What the user is told once another reviewer approves'
                                    : 'The warning the user receives when you approve'}
                            </p>
                            <label className="block text-xs text-text-2">
                                Title
                                <input
                                    type="text"
                                    value={override?.title ?? safety.notificationTitle ?? ''}
                                    maxLength={SUGGESTION_LIMITS.notificationTitle}
                                    onChange={(event) => onOverride({ ...override, title: event.target.value })}
                                    className={`${FIELD_CLASS} mt-0.5`}
                                    data-testid={`${testId}-title`}
                                />
                            </label>
                            <label className="block text-xs text-text-2">
                                Message
                                <textarea
                                    rows={3}
                                    value={override?.message ?? safety.notificationMessage ?? ''}
                                    maxLength={SUGGESTION_LIMITS.notificationMessage}
                                    onChange={(event) => onOverride({ ...override, message: event.target.value })}
                                    className={`${FIELD_CLASS} mt-0.5`}
                                    data-testid={`${testId}-message`}
                                />
                            </label>
                        </fieldset>
                    ) : null}
                    {result ? (
                        <ReviewNotice tone={result.tone} testId={`${testId}-result`}>{result.message}</ReviewNotice>
                    ) : null}
                </div>
                <div className="flex shrink-0 flex-wrap gap-1.5 sm:flex-col">
                    <GlassButton type="button" size="sm" variant="primary" onClick={onApprove}
                        disabled={busy || state !== 'ready'} aria-label={`Approve the suggestion for ${title}`}
                        data-testid={`${testId}-approve`}>
                        <CheckCheck size={14} aria-hidden="true" /> Approve
                    </GlassButton>
                    <GlassButton type="button" size="sm" variant="ghost" onClick={onDismiss} disabled={busy}
                        aria-label={`Dismiss the suggestion for ${title}`} data-testid={`${testId}-dismiss`}>
                        <X size={14} aria-hidden="true" /> Dismiss
                    </GlassButton>
                </div>
            </div>
        </li>
    );
}

export function SuggestionsQueue({
    section,
    reloadKey,
    onCountChange,
}: {
    section: ReviewSectionId;
    reloadKey: number;
    onCountChange: (count: number) => void;
}) {
    const noun = NOUNS[section];
    const prefix = `v2-${section}-suggestions`;
    const [searchParams, setSearchParams] = useSearchParams();
    const paging = readReviewPaging(searchParams);
    const [records, setRecords] = useState<QueueRecord[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [reload, setReload] = useState(0);
    const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
    const [overrides, setOverrides] = useState<Record<string, NotificationOverride>>({});
    const [rowResults, setRowResults] = useState<Record<string, RowResult>>({});
    const [progress, setProgress] = useState<BulkRunProgress | null>(null);
    const [report, setReport] = useState<BulkRunReport | null>(null);
    const [pending, setPending] = useState<Pending | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        fetchSuggestionsPage<QueueRecord>(section, paging.page, paging.pageSize, controller.signal)
            .then((result) => {
                if (controller.signal.aborted) return;
                setRecords(result.items);
                setTotal(result.total);
                const shown = new Set(result.items.map((item) => item.id));
                setChecked((current) => new Set([...current].filter((id) => shown.has(id))));
            })
            .catch((cause) => {
                if (!controller.signal.aborted) setError(errorText(cause, 'The AI suggestions could not be loaded.'));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [section, paging.page, paging.pageSize, reloadKey, reload]);

    useEffect(() => {
        if (!loading && !error) onCountChange(total);
    }, [loading, error, total, onCountChange]);

    const entries: QueueEntry[] = useMemo(() => records.flatMap((record) => {
        const suggestion = parseSuggestion(section, record.ai_suggestion);
        if (!suggestion || !suggestion.id || (suggestion.status !== 'pending' && suggestion.status !== 'stale')) return [];
        return [{ id: record.id, section, record, suggestion, state: suggestionRowState(section, record, suggestion) }];
    }), [records, section]);
    const readyIds = approveAllIds(entries);
    // Selecting the page never ticks a suspension or block: those are approved one tick at a time.
    const pageSelectable = entries.filter((entry) => !queueEntryRestrictive(entry)).map((entry) => entry.id);
    const pageChecked = pageSelectable.length > 0 && pageSelectable.every((id) => checked.has(id));
    const busy = Boolean(progress);
    const backParams = new URLSearchParams();
    const describe = (id: string) => {
        const entry = entries.find((candidate) => candidate.id === id);
        return entry ? rowTitle(entry) : `${noun.singular} ${id}`;
    };
    const bulk = (operations: readonly BulkOperation[], onProgress?: (done: number, all: number) => void) => (
        section === 'safety' ? bulkSafety(operations, onProgress) : bulkFeedback(operations, onProgress)
    );

    const toggle = (id: string) => setChecked((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
    });

    const askToApprove = (ids: readonly string[], mode: 'all' | 'selected') => {
        const plan = planApproval(entries, ids, mode);
        if (!plan.ids.length) {
            setReport({
                summary: 'Nothing was applied: none of these suggestions can be applied now.',
                failures: plan.skipped.map((item) => ({ id: item.id, label: describe(item.id), message: item.reason })),
                tone: 'warn',
            });
            return;
        }
        setPending({ kind: 'approve', plan });
    };

    const approve = async (plan: ApprovalPlan) => {
        setReport(null);
        setRowResults({});
        setProgress({ label: 'Applying', done: 0, total: plan.ids.length });
        const now = new Date();
        const operations = plan.ids.flatMap((id) => {
            const entry = entries.find((candidate) => candidate.id === id);
            const operation = entry ? buildSuggestionOperation(entry, overrides[id], now) : null;
            return operation ? [operation] : [];
        });
        try {
            const results = await bulk(operations, (done, all) => setProgress({ label: 'Applying', done, total: all }));
            const applied = results.filter((result) => result.ok).map((result) => result.id);
            const follow = archiveFollowUps(entries, applied);
            const archived = follow.length ? await bulk(follow) : [];
            const built = buildBulkReport(results, 'Applied', SUGGESTION_NOUN, describe);
            const failures = [...built.failures];
            const outcomes: Record<string, RowResult> = {};
            for (const result of results) {
                if (!result.ok) outcomes[result.id] = { tone: 'danger', message: resultMessage(result) };
                else if (typeof result.suggestion_warning === 'string') {
                    failures.push({ id: result.id, label: describe(result.id), message: result.suggestion_warning });
                }
            }
            for (const result of archived) {
                if (!result.ok) {
                    failures.push({
                        id: result.id,
                        label: describe(result.id),
                        message: `Applied, but it could not be archived: ${resultMessage(result)}`,
                    });
                }
            }
            const okSet = new Set(applied);
            const warned = plan.ids.filter((id) => {
                const entry = entries.find((candidate) => candidate.id === id);
                return entry?.section === 'safety' && okSet.has(id)
                    && sendsWarning(entry.record as SafetyRecord, (entry.suggestion as SafetySuggestion).payload);
            }).length;
            const requested = results.filter((result) => result.ok && result.approval_required === true).length;
            const extra = [
                warned ? `${countLabel(warned, 'warning was', 'warnings were')} sent.` : '',
                requested ? `${countLabel(requested, 'suspension or block request waits', 'suspension or block requests wait')} for another reviewer.` : '',
                plan.skipped.length ? `${countLabel(plan.skipped.length, 'suggestion was', 'suggestions were')} left in the queue.` : '',
            ].filter(Boolean).join(' ');
            setReport({ summary: [built.summary, extra].filter(Boolean).join(' '), failures, tone: failures.length ? 'warn' : 'ok' });
            setRowResults(outcomes);
            setChecked(new Set(Object.keys(outcomes)));
            setOverrides((current) => Object.fromEntries(Object.entries(current).filter(([id]) => !okSet.has(id))));
        } catch (cause) {
            setReport({ summary: errorText(cause, 'The suggestions could not be applied.'), failures: [], tone: 'warn' });
        } finally {
            setProgress(null);
            setReload((value) => value + 1);
        }
    };

    const dismiss = async (ids: readonly string[]) => {
        setReport(null);
        setRowResults({});
        const operations: BulkOperation[] = ids.flatMap((id) => {
            const entry = entries.find((candidate) => candidate.id === id);
            if (!entry?.suggestion.id) return [];
            const etag = (entry.record as { etag?: string }).etag;
            return [{ id, op: 'dismiss_suggestion' as const, suggestion_id: entry.suggestion.id, ...(etag ? { etag } : {}) }];
        });
        if (!operations.length) return;
        setProgress({ label: 'Dismissing', done: 0, total: operations.length });
        try {
            const results = await bulk(operations, (done, all) => setProgress({ label: 'Dismissing', done, total: all }));
            const built = buildBulkReport(results, 'Dismissed', SUGGESTION_NOUN, describe);
            const outcomes: Record<string, RowResult> = {};
            for (const result of results) {
                if (!result.ok) outcomes[result.id] = { tone: 'danger', message: resultMessage(result) };
            }
            setReport({ summary: built.summary, failures: built.failures });
            setRowResults(outcomes);
            setChecked(new Set(Object.keys(outcomes)));
        } catch (cause) {
            setReport({ summary: errorText(cause, 'The suggestions could not be dismissed.'), failures: [], tone: 'warn' });
        } finally {
            setProgress(null);
            setReload((value) => value + 1);
        }
    };

    const selectedIds = entries.filter((entry) => checked.has(entry.id)).map((entry) => entry.id);
    const confirmation = pending?.kind === 'approve' ? approvalConfirmation(pending.plan, noun) : null;

    return (
        <div className="h-full overflow-y-auto" data-testid={prefix}>
            <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
                <p className="max-w-3xl text-sm text-text-2">
                    AI suggested these reviews when a reviewer asked it to triage {noun.plural}. Nothing has changed yet:
                    approve a suggestion to save it as your review, edit what the user will be told first, or dismiss it.
                    Check each one; AI can be wrong.
                </p>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <label className="inline-flex items-center gap-2 text-sm text-text-1">
                        <input
                            type="checkbox"
                            checked={pageChecked}
                            disabled={!pageSelectable.length || busy}
                            onChange={() => setChecked(pageChecked ? new Set() : new Set(pageSelectable))}
                            data-testid={`${prefix}-select-page`}
                            className="h-4 w-4 accent-[var(--color-accent)]"
                        />
                        Select all on this page except suspensions and blocks
                    </label>
                    <GlassButton type="button" size="sm" variant="primary" disabled={!readyIds.length || busy}
                        onClick={() => askToApprove(readyIds, 'all')} data-testid={`${prefix}-approve-all`}>
                        <CheckCheck size={14} aria-hidden="true" /> Approve all ready ({readyIds.length.toLocaleString()})
                    </GlassButton>
                    <span className="text-xs text-text-3">
                        <span className="font-semibold text-text-1 tabular-nums">{total.toLocaleString()}</span>
                        {total === 1 ? ' suggestion waiting' : ' suggestions waiting'}
                    </span>
                </div>
                {error ? <ReviewNotice tone="danger">{error}</ReviewNotice> : null}
                <ReviewBulkBar
                    count={selectedIds.length}
                    summary={`${countLabel(selectedIds.length, 'suggestion', 'suggestions')} selected`}
                    onClear={() => setChecked(new Set())}
                    progress={progress}
                    report={report}
                    onDismissReport={() => setReport(null)}
                    testIdPrefix={prefix}
                    actions={(
                        <>
                            <GlassButton type="button" size="sm" variant="subtle" onClick={() => askToApprove(selectedIds, 'selected')}
                                data-testid={`${prefix}-approve-selected`}>
                                <CheckCheck size={14} aria-hidden="true" /> Approve selected
                            </GlassButton>
                            <GlassButton type="button" size="sm" variant="ghost"
                                onClick={() => setPending({ kind: 'dismiss', ids: selectedIds })}
                                data-testid={`${prefix}-dismiss-selected`}>
                                <Ban size={14} aria-hidden="true" /> Dismiss selected
                            </GlassButton>
                        </>
                    )}
                />
                {loading && !entries.length ? (
                    <div role="status" className="space-y-3">
                        <span className="sr-only">Loading the AI suggestions</span>
                        {Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-32 w-full" />)}
                    </div>
                ) : entries.length ? (
                    <ul aria-label="AI suggestions" aria-busy={loading || undefined} className="space-y-3">
                        {entries.map((entry) => (
                            <SuggestionRow
                                key={entry.id}
                                entry={entry}
                                checked={checked.has(entry.id)}
                                busy={busy}
                                override={overrides[entry.id]}
                                result={rowResults[entry.id]}
                                backParams={backParams}
                                onToggle={() => toggle(entry.id)}
                                onOverride={(override) => setOverrides((current) => ({ ...current, [entry.id]: override }))}
                                onApprove={() => askToApprove([entry.id], 'selected')}
                                onDismiss={() => void dismiss([entry.id])}
                            />
                        ))}
                    </ul>
                ) : !error ? (
                    <EmptyState
                        icon={<Sparkles size={28} />}
                        title="No AI suggestions are waiting"
                        description={`Select ${noun.plural} in the list and choose Triage with AI to get suggested reviews.`}
                    />
                ) : null}
                {total > paging.pageSize ? (
                    <ReviewPager
                        page={paging.page}
                        pageSize={paging.pageSize}
                        total={total}
                        loading={loading}
                        noun="suggestions"
                        onPage={(page) => setSearchParams((current) => {
                            const next = new URLSearchParams(current);
                            next.set('page', String(page));
                            return next;
                        }, { replace: true })}
                        onPageSize={(size) => setSearchParams((current) => {
                            const next = new URLSearchParams(current);
                            next.set('size', String(size));
                            next.delete('page');
                            return next;
                        }, { replace: true })}
                    />
                ) : null}
            </div>
            {pending?.kind === 'approve' && confirmation ? (
                <ConfirmDialog
                    title={confirmation.title}
                    description={confirmation.description}
                    confirmLabel={confirmation.confirmLabel}
                    tone={pending.plan.restrictions || pending.plan.warnings ? 'danger' : 'primary'}
                    onClose={() => setPending(null)}
                    onConfirm={() => {
                        const { plan } = pending;
                        setPending(null);
                        void approve(plan);
                    }}
                />
            ) : null}
            {pending?.kind === 'dismiss' ? (
                <ConfirmDialog
                    title={`Dismiss ${countLabel(pending.ids.length, 'suggestion', 'suggestions')}?`}
                    description="Each suggestion leaves the queue, and its review stays as it is. Dismissals are recorded in the audit log."
                    confirmLabel={`Dismiss ${countLabel(pending.ids.length, 'suggestion', 'suggestions')}`}
                    tone="primary"
                    onClose={() => setPending(null)}
                    onConfirm={() => {
                        const { ids } = pending;
                        setPending(null);
                        void dismiss(ids);
                    }}
                />
            ) : null}
        </div>
    );
}
