// SafetyWorkbench.tsx
// The Safety section's workbench: every safety violation as a one-line row beside the
// selected violation's detail, with search, filters and bulk actions.
//
// The filters, the page and the selected violation live in the address, so a dashboard
// figure can open the list already filtered and a violation's editor can return to it
// exactly as it was left. Checking rows offers Set status, Archive or Restore, and Delete
// for all of them at once. Each runs through the same server rules as a single save: a
// violation whose remediation request is still waiting, or whose warning is being sent,
// is left unchanged and the report says why.

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Archive, ArchiveRestore, Download, ExternalLink, ListFilter, PencilLine, Sparkles, Trash2 } from 'lucide-react';
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
import { GlassButton, Skeleton } from '../../components/ui/primitives';
import { apiUrl } from '../../lib/apiClient';
import {
    ACTIONS,
    categorySummary,
    countLabel,
    formatReviewDate,
    isSafetyRecordLocked,
    isWarningSending,
    LEGACY_ESCALATE_ACTION,
    readSafetyFilters,
    remediationStatusText,
    safeApprovalRequestHref,
    safeReviewRecordHref,
    safeViolationsHref,
    SAFETY_STATUSES,
    safetyActionBadge,
    safetyActionLabel,
    safetyFilterParams,
    safetyFiltersApplied,
    safetyRowMeta,
    safetyRowTitle,
    safetyStatusTone,
    safetyUserLabel,
    warningAcknowledgmentText,
    type SafetyFilters,
    type SafetyRecord,
    type SafetyStatus,
} from '../../lib/reviewCenter';
import { bulkSafety, errorText, fetchSafetyIds, fetchSafetyPage, fetchSafetyRecord } from '../../lib/reviewCenterApi';
import { suggestionBadge, triageRetryIds } from '../../lib/reviewSuggestions';
import { useFeature } from '../../stores/bootstrapStore';

const NOUN = { singular: 'violation', plural: 'violations' };
type DetailTab = 'violation' | 'user' | 'remediation';
const DETAIL_TABS: { id: DetailTab; label: string }[] = [
    { id: 'violation', label: 'Violation' },
    { id: 'user', label: 'User' },
    { id: 'remediation', label: 'Remediation' },
];

const REQUEST_LABELS: Readonly<Record<string, string>> = {
    pending: 'Awaiting approval',
    executed: 'Applied or sent',
    failed: 'Failed',
    denied: 'Denied',
    expired: 'Expired',
};

const WARNING_LABELS: Readonly<Record<string, string>> = {
    pending: 'Warning not yet acknowledged',
    acknowledged: 'Warning acknowledged',
    not_tracked: 'Warning sent before tracking',
};

/** The violation's status and action, as the row and the detail header show them. */
function SafetyBadges({ record, showSuggestion = false }: { record: SafetyRecord; showSuggestion?: boolean }) {
    const action = safetyActionBadge(record);
    const suggestion = showSuggestion ? suggestionBadge('safety', record.ai_suggestion) : null;
    return (
        <>
            <ToneBadge tone={safetyStatusTone(record.status)}>{record.status || 'New'}</ToneBadge>
            {record.action && record.action !== 'None' ? (
                <ToneBadge tone={action.tone}>{action.detail ? `${action.label} · ${action.detail}` : action.label}</ToneBadge>
            ) : null}
            {suggestion ? <ToneBadge tone={suggestion.tone}>{suggestion.label}</ToneBadge> : null}
            {record.isArchived ? <ToneBadge tone="neutral">Archived</ToneBadge> : null}
        </>
    );
}

function accessText(record: SafetyRecord): string {
    const access = record.user_access;
    if (!access) return 'Not available';
    if (!access.restricted) return 'Not restricted';
    if (access.kind === 'suspended') return `Suspended until ${formatReviewDate(access.until)}`;
    return 'Blocked';
}

function SafetyDetail({
    record,
    busy,
    onOpen,
    onArchive,
    onDelete,
}: {
    record: SafetyRecord;
    busy: boolean;
    onOpen: () => void;
    onArchive: () => void;
    onDelete: () => void;
}) {
    const [tab, setTab] = useState<DetailTab>('violation');
    const [detail, setDetail] = useState<SafetyRecord | null>(null);
    const [detailError, setDetailError] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        setDetail(null);
        setDetailError('');
        fetchSafetyRecord(record.id, controller.signal)
            .then((next) => setDetail(next))
            .catch((cause) => {
                if (!controller.signal.aborted) setDetailError(errorText(cause, 'The violation details could not be loaded.'));
            });
        return () => controller.abort();
    }, [record.id, record.last_updated, record.action_request_status, record.isArchived]);

    const shown = detail ?? record;
    const locked = isSafetyRecordLocked(shown);
    const sending = isWarningSending(shown);
    const remediation = remediationStatusText(shown);
    const acknowledgment = warningAcknowledgmentText(shown);
    const approvalId = shown.action_request_id;

    return (
        <div className="flex min-h-full flex-col" data-testid="v2-safety-detail">
            <div className="space-y-3 px-4 pt-4 pb-3 sm:px-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-[1_1_16rem]">
                        <h3 className="text-base leading-snug font-semibold break-words text-text-1">{safetyRowTitle(shown)}</h3>
                        <p className="mt-1 text-xs text-text-3">
                            {safetyUserLabel(shown)} · {formatReviewDate(shown.created_at)}
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" size="sm" variant="primary" onClick={onOpen} data-testid="v2-safety-open-editor">
                            <PencilLine size={14} aria-hidden="true" /> Review
                        </GlassButton>
                        <GlassButton type="button" size="sm" variant="subtle" onClick={onArchive} disabled={busy || sending}>
                            {shown.isArchived ? <ArchiveRestore size={14} aria-hidden="true" /> : <Archive size={14} aria-hidden="true" />}
                            {shown.isArchived ? 'Restore' : 'Archive'}
                        </GlassButton>
                        <GlassButton type="button" size="sm" variant="danger" onClick={onDelete} disabled={busy || locked}>
                            <Trash2 size={14} aria-hidden="true" /> Delete
                        </GlassButton>
                    </div>
                </div>
                <div className="flex flex-wrap gap-1.5"><SafetyBadges record={shown} /></div>
                {locked ? (
                    <ReviewNotice tone="info">
                        {remediation} {sending
                            ? 'Until it finishes this violation cannot be changed, archived or deleted.'
                            : 'Until it is decided this violation cannot be changed or deleted.'}
                    </ReviewNotice>
                ) : null}
            </div>
            <ReviewDetailTabs label="Violation details" tabs={DETAIL_TABS} active={tab} onChange={setTab}>
                {tab === 'violation' ? (
                    <div className="space-y-4">
                        <ReviewTextBlock label="Flagged message" text={shown.message} empty="No message captured." />
                        <dl className="divide-y divide-edge">
                            <ReviewFact label="Triggered categories">{categorySummary(shown) || 'No triggered categories'}</ReviewFact>
                            <ReviewFact label="Flagged content">
                                {shown.content_origin === 'assistant' ? 'An AI response' : 'A message the user sent'}
                            </ReviewFact>
                            <ReviewFact label="Status">{shown.status || 'New'}</ReviewFact>
                            <ReviewFact label="Reviewer notes">{shown.notes || null}</ReviewFact>
                            <ReviewFact label="The user's notes">{shown.user_notes || null}</ReviewFact>
                            <ReviewFact label="Last updated">{shown.last_updated ? formatReviewDate(shown.last_updated) : null}</ReviewFact>
                        </dl>
                    </div>
                ) : tab === 'user' ? (
                    <div className="space-y-3">
                        {detailError ? <ReviewNotice tone="warn">{detailError}</ReviewNotice> : null}
                        {!detail && !detailError ? (
                            <div role="status" className="space-y-2">
                                <span className="sr-only">Loading the user's details</span>
                                <Skeleton className="h-5 w-2/3" />
                                <Skeleton className="h-5 w-1/2" />
                            </div>
                        ) : (
                            <dl className="divide-y divide-edge">
                                <ReviewFact label="User">
                                    {[shown.user_display_name, shown.user_email].filter(Boolean).join(' · ') || shown.user_id || 'Unknown user'}
                                </ReviewFact>
                                <ReviewFact label="Access now">{accessText(shown)}</ReviewFact>
                                <ReviewFact label="Other violations by this user">
                                    {shown.user_violation_count === null || shown.user_violation_count === undefined
                                        ? 'Not available'
                                        : shown.user_violation_count.toLocaleString()}
                                </ReviewFact>
                            </dl>
                        )}
                        {shown.user_id ? (
                            <Link
                                to={safeViolationsHref({ userId: shown.user_id, archive: 'all' })}
                                className="inline-flex items-center gap-1.5 text-sm text-accent underline underline-offset-2"
                            >
                                <ListFilter size={14} aria-hidden="true" /> Show every violation by this user
                            </Link>
                        ) : null}
                    </div>
                ) : (
                    <div className="space-y-3">
                        <dl className="divide-y divide-edge">
                            <ReviewFact label="Action">{safetyActionLabel(shown.action)}</ReviewFact>
                            <ReviewFact label="Where it stands">{remediation}</ReviewFact>
                            <ReviewFact label="Warning">{acknowledgment}</ReviewFact>
                            <ReviewFact label="Notification title">{shown.action_notification_title || null}</ReviewFact>
                            <ReviewFact label="Notification message">{shown.action_notification_message || null}</ReviewFact>
                            <ReviewFact label="Access restores">
                                {shown.action === 'SuspendUser' && shown.action_datetime_to_allow
                                    ? formatReviewDate(shown.action_datetime_to_allow)
                                    : null}
                            </ReviewFact>
                        </dl>
                        {approvalId ? (
                            <Link
                                to={safeApprovalRequestHref(approvalId, shown.user_id)}
                                className="inline-flex items-center gap-1.5 text-sm text-accent underline underline-offset-2"
                                data-testid="v2-safety-approval-link"
                            >
                                <ExternalLink size={14} aria-hidden="true" /> Open the approval request
                            </Link>
                        ) : null}
                        {!remediation && !acknowledgment ? (
                            <p className="text-sm text-text-3">No warning, suspension or block has been requested for this violation.</p>
                        ) : null}
                    </div>
                )}
            </ReviewDetailTabs>
        </div>
    );
}

export function SafetyWorkbench({
    reloadKey,
    onCountChange,
}: {
    reloadKey: number;
    onCountChange: (count: number) => void;
}) {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const filters = readSafetyFilters(searchParams);
    const filterKey = safetyFilterParams(filters).toString();
    const saved = useReviewSavedNotice();
    const [pendingDelete, setPendingDelete] = useState<{ ids: string[]; fromSelection: boolean } | null>(null);
    const [bulkStatus, setBulkStatus] = useState<SafetyStatus>('Resolved');
    const [pendingTriage, setPendingTriage] = useState<string[] | null>(null);
    const aiAvailable = useFeature('enable_admin_review_ai_assistant');

    const workbench = useReviewWorkbench<SafetyRecord>({
        filterKey,
        reloadKey,
        loadPage: (page, pageSize, signal) => fetchSafetyPage(filters, page, pageSize, signal),
        loadMatchingIds: () => fetchSafetyIds(filters),
        runBulk: bulkSafety,
        noun: NOUN,
        describe: (id, items) => {
            const item = items.find((candidate) => candidate.id === id);
            return item ? safetyRowTitle(item) : `Violation ${id}`;
        },
        ownerOf: (item) => item.user_id,
    });
    const { items, total, loading, error, paging, updateParams, checked, matching } = workbench;
    const triage = useReviewTriage({
        section: 'safety',
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
    const rows: ReviewListRow[] = useMemo(() => items.map((item) => ({
        id: item.id,
        title: safetyRowTitle(item),
        meta: safetyRowMeta(item),
        status: <SafetyBadges record={item} showSuggestion={aiAvailable} />,
    })), [items, aiAvailable]);

    const setFilter = <K extends keyof SafetyFilters>(key: K, value: SafetyFilters[K]) => {
        const next = safetyFilterParams({ ...filters, [key]: value });
        const changes: Record<string, string | null> = {};
        for (const name of [
            'status', 'action', 'archive', 'search', 'user_id', 'category', 'severity',
            'request', 'warning', 'restricted', 'date', 'days',
        ]) {
            changes[name] = next.get(name);
        }
        changes.selected = null;
        updateParams(changes);
    };
    const clearFilters = () => updateParams({
        status: null, action: null, archive: null, search: null, user_id: null, category: null, severity: null,
        request: null, warning: null, restricted: null, date: null, days: null, selected: null,
    });

    const chips: FilterChip[] = [];
    if (filters.userId) {
        const named = items.find((item) => item.user_id === filters.userId);
        chips.push({ key: 'user', label: `User: ${named ? safetyUserLabel(named) : filters.userId}`, onRemove: () => setFilter('userId', '') });
    }
    if (filters.category) chips.push({ key: 'category', label: `Category: ${filters.category}`, onRemove: () => setFilter('category', '') });
    if (filters.severity) chips.push({ key: 'severity', label: `Severity ${filters.severity}`, onRemove: () => setFilter('severity', '') });
    if (filters.warning) chips.push({ key: 'warning', label: WARNING_LABELS[filters.warning] ?? filters.warning, onRemove: () => setFilter('warning', '') });
    if (filters.restricted) chips.push({ key: 'restricted', label: 'Users restricted now', onRemove: () => setFilter('restricted', false) });
    if (filters.date) chips.push({ key: 'date', label: `Day: ${filters.date}`, onRemove: () => setFilter('date', '') });
    if (filters.days) chips.push({ key: 'days', label: `Last ${filters.days} days`, onRemove: () => setFilter('days', '') });

    const openEditor = (id: string) => {
        const next = new URLSearchParams(searchParams);
        next.set('selected', id);
        navigate(safeReviewRecordHref('safety', id, next));
    };
    const busy = Boolean(workbench.progress) || triage.running;
    const startTriage = (ids: string[]) => {
        const snapshot = items;
        workbench.clearSelection();
        void triage.start(ids, (id) => {
            const item = snapshot.find((candidate) => candidate.id === id);
            return item ? safetyRowTitle(item) : `Violation ${id}`;
        }, workbench.recordOwner);
    };
    const actionOptions: [string, string][] = [
        ['', 'Any action'],
        ...ACTIONS.map((action): [string, string] => [action, safetyActionLabel(action)]),
        [LEGACY_ESCALATE_ACTION, safetyActionLabel(LEGACY_ESCALATE_ACTION)],
    ];

    const header = (
        <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <ReviewSearch
                    value={filters.search}
                    onCommit={(value) => setFilter('search', value)}
                    label="Search violations"
                    testId="v2-safety-search"
                />
                <FilterSelect
                    label="Status"
                    value={filters.status}
                    options={[
                        ['', 'Any status'],
                        ['open', 'Open (new or in review)'],
                        ...SAFETY_STATUSES.map((status): [SafetyFilters['status'], string] => [status, status]),
                    ]}
                    onChange={(value) => setFilter('status', value)}
                    testId="v2-safety-filter-status"
                />
                <FilterSelect
                    label="Action"
                    value={filters.action}
                    options={actionOptions}
                    onChange={(value) => setFilter('action', value)}
                    testId="v2-safety-filter-action"
                />
                <FilterSelect
                    label="Remediation"
                    value={filters.request}
                    options={[['', 'Any'], ...Object.entries(REQUEST_LABELS) as [SafetyFilters['request'], string][]]}
                    onChange={(value) => setFilter('request', value)}
                    testId="v2-safety-filter-request"
                />
                <FilterSelect
                    label="Show"
                    value={filters.archive}
                    options={[['active', 'Active'], ['archived', 'Archived'], ['all', 'Active and archived']]}
                    onChange={(value) => setFilter('archive', value)}
                    testId="v2-safety-filter-archive"
                />
                <a
                    href={apiUrl(`/api/safety/logs/export?${filterKey}`)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-edge px-3 py-2 text-xs font-medium text-text-1 hover:bg-surface-2"
                >
                    <Download size={14} aria-hidden="true" /> Export CSV
                </a>
            </div>
            <FilterChips chips={chips} />
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-3">
                <span>
                    <span className="font-semibold text-text-1 tabular-nums">{total.toLocaleString()}</span>
                    {total === 1 ? ' violation' : ' violations'}
                </span>
                {safetyFiltersApplied(filters) || filters.search ? (
                    <button type="button" className="text-accent underline underline-offset-2" onClick={clearFilters}>
                        Clear filters
                    </button>
                ) : null}
            </p>
            <ReviewSavedStatus notice={saved} testId="v2-safety-saved" />
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
                testIdPrefix="v2-safety"
                actions={(
                    <>
                        {aiAvailable ? (
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                data-testid="v2-safety-bulk-triage"
                                onClick={() => setPendingTriage([...checked])}
                            >
                                <Sparkles size={14} aria-hidden="true" /> Triage with AI ({checked.length.toLocaleString()})
                            </GlassButton>
                        ) : null}
                        <div className="flex items-center gap-1.5">
                            <label htmlFor="v2-safety-bulk-status" className="sr-only">New status</label>
                            <select
                                id="v2-safety-bulk-status"
                                value={bulkStatus}
                                onChange={(event) => setBulkStatus(event.target.value as SafetyStatus)}
                                className="h-8 rounded-lg border border-edge bg-surface-1 px-2 text-sm text-text-1"
                                data-testid="v2-safety-bulk-status"
                            >
                                {SAFETY_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
                            </select>
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                data-testid="v2-safety-bulk-set-status"
                                onClick={() => void workbench.runBulkOperation('Updating', `Set ${bulkStatus} on`, (id) => ({
                                    id,
                                    op: 'update',
                                    changes: { status: bulkStatus },
                                }))}
                            >
                                Set status
                            </GlassButton>
                        </div>
                        {filters.archive !== 'archived' ? (
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                data-testid="v2-safety-bulk-archive"
                                onClick={() => void workbench.runBulkOperation('Archiving', 'Archived', (id) => ({ id, op: 'archive', archived: true }))}
                            >
                                <Archive size={14} aria-hidden="true" /> Archive
                            </GlassButton>
                        ) : null}
                        {filters.archive !== 'active' ? (
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                data-testid="v2-safety-bulk-restore"
                                onClick={() => void workbench.runBulkOperation('Restoring', 'Restored', (id) => ({ id, op: 'archive', archived: false }))}
                            >
                                <ArchiveRestore size={14} aria-hidden="true" /> Restore
                            </GlassButton>
                        ) : null}
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="danger"
                            data-testid="v2-safety-bulk-delete"
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
                testId="v2-safety-workbench"
                label="Safety violations workbench"
                header={header}
                list={(
                    <ReviewList
                        label="Safety violations"
                        columnLabel="Violation"
                        statusLabel="State"
                        rows={rows}
                        loading={loading}
                        empty={(
                            <div className="space-y-2 px-3 py-6">
                                <p className="text-sm font-medium text-text-1">
                                    {safetyFiltersApplied(filters) || filters.search ? 'No violations match these filters' : 'No violations yet'}
                                </p>
                                <p className="text-[0.8125rem] leading-relaxed text-text-3">
                                    {safetyFiltersApplied(filters) || filters.search
                                        ? 'Try another search, or clear the filters.'
                                        : 'Messages flagged by content safety or content screening appear here.'}
                                </p>
                            </div>
                        )}
                        selectedId={selected?.id ?? null}
                        onSelect={(id) => updateParams({ selected: id }, { keepPage: true })}
                        checkedIds={checked}
                        onToggleCheck={workbench.toggle}
                        onToggleAll={workbench.togglePage}
                        testIdPrefix="v2-safety"
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
                    <SafetyDetail
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
                        title={loading ? 'Loading violations' : 'No violation selected'}
                        description="Select a violation in the list to read it, the user's history and its remediation."
                    />
                )}
            />
            {pendingDelete ? (
                <ConfirmDialog
                    title={`Permanently delete ${countLabel(pendingDelete.ids.length, NOUN.singular, NOUN.plural)}?`}
                    description="This cannot be undone. Approval and activity audit records are kept. A violation whose remediation request is still waiting cannot be deleted, and is left as it is."
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
                        'AI reads each violation and stores a suggested review on it, for you or another reviewer to '
                        + 'approve or dismiss in the AI suggestions queue. Nothing changes now: no one is warned, suspended '
                        + 'or blocked unless a reviewer approves a suggestion. Violations held by a request in progress are '
                        + 'skipped. Records are sent ten at a time, and you can cancel part way.'
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
