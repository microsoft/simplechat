// FeedbackWorkbench.tsx
// The Feedback section's workbench: every feedback record as a one-line row beside the
// selected record's detail, with search, filters and bulk actions.
//
// The filters, the page and the selected record live in the address, so a dashboard figure
// can open the list already filtered and a record's editor can return to it exactly as it
// was left. Checking rows offers Acknowledge, Archive or Restore, and Delete for all of
// them at once; each runs through the same server rules as a single save and reports on
// every record it could not change.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Archive, ArchiveRestore, CheckCheck, Download, PencilLine, Sparkles, Trash2 } from 'lucide-react';
import { FeedbackRetest } from '../../components/review/FeedbackRetest';
import { ReviewBulkBar } from '../../components/review/ReviewBulkBar';
import { ReviewList, type ReviewListRow } from '../../components/review/ReviewList';
import {
    FilterChips,
    FilterSelect,
    ReviewDetailTabs,
    ReviewFact,
    ReviewNotice,
    ReviewPager,
    ReviewSearch,
    ReviewTextBlock,
    ToneBadge,
    type FilterChip,
} from '../../components/review/ReviewParts';
import { useReviewTriage } from '../../components/review/useReviewTriage';
import { useReviewWorkbench } from '../../components/review/useReviewWorkbench';
import {
    ReviewDetailEmpty,
    ReviewSavedStatus,
    ReviewWorkbenchLayout,
    useReviewSavedNotice,
} from '../../components/review/ReviewWorkbenchLayout';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { GlassButton } from '../../components/ui/primitives';
import { apiUrl } from '../../lib/apiClient';
import {
    countLabel,
    FEEDBACK_THEME_LABELS,
    FEEDBACK_THEMES,
    feedbackFilterParams,
    feedbackFiltersApplied,
    feedbackRatingTone,
    feedbackReviewerName,
    feedbackReviewState,
    feedbackRowMeta,
    feedbackRowTitle,
    feedbackThemeLabel,
    feedbackUserLabel,
    formatReviewDate,
    readFeedbackFilters,
    safeReviewRecordHref,
    type FeedbackFilters,
    type FeedbackRecord,
} from '../../lib/reviewCenter';
import { bulkFeedback, fetchFeedbackIds, fetchFeedbackPage } from '../../lib/reviewCenterApi';
import { suggestionBadge, triageRetryIds } from '../../lib/reviewSuggestions';
import { useFeature } from '../../stores/bootstrapStore';

const NOUN = { singular: 'feedback record', plural: 'feedback records' };
type DetailTab = 'conversation' | 'review' | 'retest';
const DETAIL_TABS: { id: DetailTab; label: string }[] = [
    { id: 'conversation', label: 'Conversation' },
    { id: 'review', label: 'Review' },
    { id: 'retest', label: 'Retest' },
];

function FeedbackDetail({
    record,
    busy,
    onOpen,
    onArchive,
    onDelete,
}: {
    record: FeedbackRecord;
    busy: boolean;
    onOpen: () => void;
    onArchive: () => void;
    onDelete: () => void;
}) {
    const [tab, setTab] = useState<DetailTab>('conversation');
    const state = feedbackReviewState(record);
    const review = record.adminReview ?? {};
    const reviewer = feedbackReviewerName(review);
    return (
        <div className="flex min-h-full flex-col" data-testid="v2-feedback-detail">
            <div className="space-y-3 px-4 pt-4 pb-3 sm:px-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-[1_1_16rem]">
                        <h3 className="text-base leading-snug font-semibold break-words text-text-1">{feedbackRowTitle(record)}</h3>
                        <p className="mt-1 text-xs text-text-3">
                            {feedbackUserLabel(record)} · {formatReviewDate(record.timestamp)}
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" size="sm" variant="primary" onClick={onOpen} data-testid="v2-feedback-open-editor">
                            <PencilLine size={14} aria-hidden="true" /> Review
                        </GlassButton>
                        <GlassButton type="button" size="sm" variant="subtle" onClick={onArchive} disabled={busy}>
                            {record.isArchived ? <ArchiveRestore size={14} aria-hidden="true" /> : <Archive size={14} aria-hidden="true" />}
                            {record.isArchived ? 'Restore' : 'Archive'}
                        </GlassButton>
                        <GlassButton type="button" size="sm" variant="danger" onClick={onDelete} disabled={busy}>
                            <Trash2 size={14} aria-hidden="true" /> Delete
                        </GlassButton>
                    </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                    <ToneBadge tone={feedbackRatingTone(record.feedbackType)}>{record.feedbackType || 'Unrated'}</ToneBadge>
                    <ToneBadge tone={state.tone}>{state.label}</ToneBadge>
                    {record.isArchived ? <ToneBadge tone="neutral">Archived</ToneBadge> : null}
                </div>
            </div>
            <ReviewDetailTabs label="Feedback details" tabs={DETAIL_TABS} active={tab} onChange={setTab}>
                {tab === 'conversation' ? (
                    <div className="space-y-4">
                        <ReviewTextBlock label="Prompt" text={record.prompt} empty="No prompt captured." />
                        <ReviewTextBlock label="AI response" text={record.aiResponse} empty="No response captured." />
                        <ReviewTextBlock label="Reason given" text={record.reason} empty="The user gave no reason." />
                    </div>
                ) : tab === 'review' ? (
                    <dl className="divide-y divide-edge">
                        <ReviewFact label="State">{state.label}</ReviewFact>
                        <ReviewFact label="Theme">{feedbackThemeLabel(review.theme)}</ReviewFact>
                        <ReviewFact label="Analysis notes">{review.analysisNotes || 'None recorded'}</ReviewFact>
                        <ReviewFact label="Action taken">{review.actionTaken || 'None recorded'}</ReviewFact>
                        <ReviewFact label="Response to the user">{review.responseToUser || 'None recorded'}</ReviewFact>
                        <ReviewFact label="Reviewed">
                            {review.reviewTimestamp
                                ? `${formatReviewDate(review.reviewTimestamp)}${reviewer ? ` by ${reviewer}` : ''}`
                                : 'Not reviewed yet'}
                        </ReviewFact>
                        <ReviewFact label="User notified">{review.userNotifiedAt ? formatReviewDate(review.userNotifiedAt) : null}</ReviewFact>
                    </dl>
                ) : (
                    <FeedbackRetest key={record.id} record={record} testIdPrefix="v2-feedback-detail" />
                )}
            </ReviewDetailTabs>
        </div>
    );
}

export function FeedbackWorkbench({
    reloadKey,
    onCountChange,
}: {
    reloadKey: number;
    onCountChange: (count: number) => void;
}) {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const filters = readFeedbackFilters(searchParams);
    const filterParams = feedbackFilterParams(filters);
    const filterKey = filterParams.toString();
    const saved = useReviewSavedNotice();
    const [pendingDelete, setPendingDelete] = useState<{ ids: string[]; fromSelection: boolean } | null>(null);
    const [pendingTriage, setPendingTriage] = useState<string[] | null>(null);
    const aiAvailable = useFeature('enable_admin_review_ai_assistant');

    const workbench = useReviewWorkbench<FeedbackRecord>({
        filterKey,
        reloadKey,
        loadPage: (page, pageSize, signal) => fetchFeedbackPage(filters, page, pageSize, signal),
        loadMatchingIds: () => fetchFeedbackIds(filters),
        runBulk: bulkFeedback,
        noun: NOUN,
        describe: (id, items) => {
            const item = items.find((candidate) => candidate.id === id);
            return item ? feedbackRowTitle(item) : `Feedback ${id}`;
        },
    });
    const { items, total, loading, error, paging, updateParams, checked, matching } = workbench;
    const triage = useReviewTriage({
        section: 'feedback',
        noun: NOUN,
        onFinished: (run) => {
            workbench.keepChecked(triageRetryIds(run));
            workbench.reload();
        },
    });

    useEffect(() => {
        if (!loading && !error) onCountChange(total);
    }, [loading, error, total, onCountChange]);

    const selected = items.find((item) => item.id === paging.selected) ?? items[0] ?? null;
    const rows: ReviewListRow[] = useMemo(() => items.map((item) => {
        const state = feedbackReviewState(item);
        const suggestion = aiAvailable ? suggestionBadge('feedback', item.ai_suggestion) : null;
        return {
            id: item.id,
            title: feedbackRowTitle(item),
            meta: feedbackRowMeta(item),
            status: (
                <>
                    <ToneBadge tone={feedbackRatingTone(item.feedbackType)}>{item.feedbackType || 'Unrated'}</ToneBadge>
                    <ToneBadge tone={state.tone}>{state.label}</ToneBadge>
                    {suggestion ? <ToneBadge tone={suggestion.tone}>{suggestion.label}</ToneBadge> : null}
                    {item.isArchived ? <ToneBadge tone="neutral">Archived</ToneBadge> : null}
                </>
            ),
        };
    }), [items, aiAvailable]);

    const setFilter = <K extends keyof FeedbackFilters>(key: K, value: FeedbackFilters[K]) => {
        const next = feedbackFilterParams({ ...filters, [key]: value });
        const changes: Record<string, string | null> = {};
        for (const name of ['type', 'ack', 'archive', 'search', 'user_id', 'date', 'days', 'theme']) {
            changes[name] = next.get(name);
        }
        changes.selected = null;
        updateParams(changes);
    };
    const clearFilters = () => {
        updateParams({
            type: null, ack: null, archive: null, search: null, user_id: null, date: null, days: null, theme: null, selected: null,
        });
    };

    const chips: FilterChip[] = [];
    if (filters.userId) {
        const named = items.find((item) => item.userId === filters.userId);
        chips.push({ key: 'user', label: `User: ${named ? feedbackUserLabel(named) : filters.userId}`, onRemove: () => setFilter('userId', '') });
    }
    if (filters.date) chips.push({ key: 'date', label: `Day: ${filters.date}`, onRemove: () => setFilter('date', '') });
    if (filters.days) chips.push({ key: 'days', label: `Last ${filters.days} days`, onRemove: () => setFilter('days', '') });

    const recordParams = (id: string) => {
        const next = new URLSearchParams(searchParams);
        next.set('selected', id);
        return next;
    };
    const openEditor = (id: string) => navigate(safeReviewRecordHref('feedback', id, recordParams(id)));
    const busy = Boolean(workbench.progress) || triage.running;
    const archiveView = filters.archive;
    const startTriage = (ids: string[]) => {
        const snapshot = items;
        workbench.clearSelection();
        void triage.start(ids, (id) => {
            const item = snapshot.find((candidate) => candidate.id === id);
            return item ? feedbackRowTitle(item) : `Feedback ${id}`;
        });
    };

    const header = (
        <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <ReviewSearch
                    value={filters.search}
                    onCommit={(value) => setFilter('search', value)}
                    label="Search feedback"
                    testId="v2-feedback-search"
                />
                <FilterSelect
                    label="Rating"
                    value={filters.type}
                    options={[['', 'All ratings'], ['Positive', 'Positive'], ['Negative', 'Negative'], ['Neutral', 'Neutral']]}
                    onChange={(value) => setFilter('type', value)}
                    testId="v2-feedback-filter-type"
                />
                <FilterSelect
                    label="Review"
                    value={filters.ack}
                    options={[['', 'Any state'], ['false', 'Awaiting review'], ['true', 'Acknowledged']]}
                    onChange={(value) => setFilter('ack', value)}
                    testId="v2-feedback-filter-ack"
                />
                <FilterSelect
                    label="Show"
                    value={filters.archive}
                    options={[['active', 'Active'], ['archived', 'Archived'], ['all', 'Active and archived']]}
                    onChange={(value) => setFilter('archive', value)}
                    testId="v2-feedback-filter-archive"
                />
                <FilterSelect
                    label="Theme"
                    value={filters.theme}
                    options={[
                        ['', 'Any theme'],
                        ...FEEDBACK_THEMES.map((theme): [FeedbackFilters['theme'], string] => [theme, FEEDBACK_THEME_LABELS[theme]]),
                    ]}
                    onChange={(value) => setFilter('theme', value)}
                    testId="v2-feedback-filter-theme"
                />
                <a
                    href={apiUrl(`/feedback/review/export?${filterKey}`)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-edge px-3 py-2 text-xs font-medium text-text-1 hover:bg-surface-2"
                >
                    <Download size={14} aria-hidden="true" /> Export CSV
                </a>
            </div>
            <FilterChips chips={chips} />
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-3">
                <span>
                    <span className="font-semibold text-text-1 tabular-nums">{total.toLocaleString()}</span>
                    {total === 1 ? ' feedback record' : ' feedback records'}
                </span>
                {feedbackFiltersApplied(filters) || filters.search ? (
                    <button type="button" className="text-accent underline underline-offset-2" onClick={clearFilters}>
                        Clear filters
                    </button>
                ) : null}
            </p>
            <ReviewSavedStatus notice={saved} testId="v2-feedback-saved" />
            {error ? <ReviewNotice tone="danger">{error}</ReviewNotice> : null}
            <ReviewBulkBar
                count={checked.length}
                summary={workbench.summary}
                offerMatching={workbench.pageFullyChecked && !matching && total > items.length ? { total, noun: NOUN.plural } : null}
                matchingBusy={workbench.matchingBusy}
                onSelectMatching={() => void workbench.chooseMatching()}
                onClear={workbench.clearSelection}
                progress={triage.progress ?? workbench.progress}
                onCancel={triage.running ? triage.cancel : undefined}
                report={triage.report ?? workbench.report}
                onDismissReport={() => {
                    triage.setReport(null);
                    workbench.setReport(null);
                }}
                testIdPrefix="v2-feedback"
                actions={(
                    <>
                        {aiAvailable ? (
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                data-testid="v2-feedback-bulk-triage"
                                onClick={() => setPendingTriage([...checked])}
                            >
                                <Sparkles size={14} aria-hidden="true" /> Triage with AI ({checked.length.toLocaleString()})
                            </GlassButton>
                        ) : null}
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="subtle"
                            data-testid="v2-feedback-bulk-acknowledge"
                            onClick={() => void workbench.runBulkOperation('Acknowledging', 'Acknowledged', (id) => ({
                                id,
                                op: 'update',
                                changes: { acknowledged: true },
                            }))}
                        >
                            <CheckCheck size={14} aria-hidden="true" /> Acknowledge
                        </GlassButton>
                        {archiveView !== 'archived' ? (
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                data-testid="v2-feedback-bulk-archive"
                                onClick={() => void workbench.runBulkOperation('Archiving', 'Archived', (id) => ({ id, op: 'archive', archived: true }))}
                            >
                                <Archive size={14} aria-hidden="true" /> Archive
                            </GlassButton>
                        ) : null}
                        {archiveView !== 'active' ? (
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                data-testid="v2-feedback-bulk-restore"
                                onClick={() => void workbench.runBulkOperation('Restoring', 'Restored', (id) => ({ id, op: 'archive', archived: false }))}
                            >
                                <ArchiveRestore size={14} aria-hidden="true" /> Restore
                            </GlassButton>
                        ) : null}
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="danger"
                            data-testid="v2-feedback-bulk-delete"
                            onClick={() => setPendingDelete({ ids: [...checked], fromSelection: true })}
                        >
                            <Trash2 size={14} aria-hidden="true" /> Delete
                        </GlassButton>
                    </>
                )}
            />
        </>
    );

    return (
        <>
            <ReviewWorkbenchLayout
                testId="v2-feedback-workbench"
                label="Feedback workbench"
                header={header}
                list={(
                    <ReviewList
                        label="Feedback"
                        columnLabel="Feedback"
                        statusLabel="State"
                        rows={rows}
                        loading={loading}
                        empty={(
                            <div className="space-y-2 px-3 py-6">
                                <p className="text-sm font-medium text-text-1">
                                    {feedbackFiltersApplied(filters) || filters.search ? 'No feedback matches these filters' : 'No feedback yet'}
                                </p>
                                <p className="text-[0.8125rem] leading-relaxed text-text-3">
                                    {feedbackFiltersApplied(filters) || filters.search
                                        ? 'Try another search, or clear the filters.'
                                        : 'Feedback users give on AI responses appears here.'}
                                </p>
                            </div>
                        )}
                        selectedId={selected?.id ?? null}
                        onSelect={(id) => updateParams({ selected: id }, { keepPage: true })}
                        checkedIds={checked}
                        onToggleCheck={workbench.toggle}
                        onToggleAll={workbench.togglePage}
                        testIdPrefix="v2-feedback"
                    />
                )}
                pager={(
                    <ReviewPager
                        page={paging.page}
                        pageSize={paging.pageSize}
                        total={total}
                        loading={loading}
                        noun={NOUN.plural}
                        onPage={(page) => updateParams({ page: String(page), selected: null }, { keepPage: true })}
                        onPageSize={(size) => updateParams({ size: String(size), selected: null })}
                    />
                )}
                detail={selected ? (
                    <FeedbackDetail
                        key={selected.id}
                        record={selected}
                        busy={busy}
                        onOpen={() => openEditor(selected.id)}
                        onArchive={() => void workbench.runBulkOperation(
                            selected.isArchived ? 'Restoring' : 'Archiving',
                            selected.isArchived ? 'Restored' : 'Archived',
                            (id) => ({ id, op: 'archive', archived: !selected.isArchived }),
                            [selected.id],
                        )}
                        onDelete={() => setPendingDelete({ ids: [selected.id], fromSelection: false })}
                    />
                ) : (
                    <ReviewDetailEmpty
                        title={loading ? 'Loading feedback' : 'No feedback selected'}
                        description="Select feedback in the list to read the conversation and its review."
                    />
                )}
            />
            {pendingDelete ? (
                <ConfirmDialog
                    title={`Permanently delete ${countLabel(pendingDelete.ids.length, NOUN.singular, NOUN.plural)}?`}
                    description="This cannot be undone. The audit history of each record is kept."
                    confirmLabel={`Delete ${countLabel(pendingDelete.ids.length, NOUN.singular, NOUN.plural)}`}
                    busy={busy}
                    onClose={() => {
                        if (!busy) setPendingDelete(null);
                    }}
                    onConfirm={() => {
                        const target = pendingDelete;
                        setPendingDelete(null);
                        void workbench.runBulkOperation(
                            'Deleting',
                            'Deleted',
                            (id) => ({ id, op: 'delete' }),
                            target.fromSelection ? undefined : target.ids,
                        );
                    }}
                />
            ) : null}
            {pendingTriage ? (
                <ConfirmDialog
                    title={`Ask AI to suggest reviews for ${countLabel(pendingTriage.length, NOUN.singular, NOUN.plural)}?`}
                    description={
                        'AI reads each record and stores a suggested review on it, for you or another reviewer to approve '
                        + 'or dismiss in the AI suggestions queue. Nothing about the reviews changes now, and no one is '
                        + 'notified. Records are sent ten at a time, and you can cancel part way.'
                    }
                    confirmLabel={`Triage ${countLabel(pendingTriage.length, NOUN.singular, NOUN.plural)}`}
                    confirmIcon={<Sparkles size={14} aria-hidden="true" />}
                    tone="primary"
                    onClose={() => setPendingTriage(null)}
                    onConfirm={() => {
                        const target = pendingTriage;
                        setPendingTriage(null);
                        startTriage(target);
                    }}
                />
            ) : null}
        </>
    );
}
