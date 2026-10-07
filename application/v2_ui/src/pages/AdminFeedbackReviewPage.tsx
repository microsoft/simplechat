// AdminFeedbackReviewPage.tsx

import { useEffect, useMemo, useState } from 'react';
import { Archive, Check, Download, Eye, Grid2X2, List, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { api, apiUrl, ApiError } from '../lib/apiClient';
import { PageHeader } from '../components/layout/PageHeader';
import { AdminModal } from '../components/admin/AdminModal';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';

const PAGE_SIZES = [10, 20, 50, 100];
const VIEW_STORAGE_KEY = 'simplechat.v2.admin.feedback.viewMode';

interface AdminReview {
    acknowledged?: boolean;
    analysisNotes?: string;
    responseToUser?: string;
    actionTaken?: string;
    reviewTimestamp?: string;
}

interface FeedbackItem {
    id: string;
    userId?: string;
    prompt?: string;
    aiResponse?: string;
    feedbackType?: string;
    reason?: string;
    timestamp?: string;
    isArchived?: boolean;
    adminReview?: AdminReview;
}

interface FeedbackPageResponse {
    feedback?: FeedbackItem[];
    page?: number;
    page_size?: number;
    total_count?: number;
}

interface FeedbackStats {
    total_count?: number;
    positive_count?: number;
    negative_count?: number;
    neutral_count?: number;
    acknowledged_count?: number;
    unacknowledged_count?: number;
    recent_30_day_count?: number;
    latest_timestamp?: string;
}

interface Filters {
    type: string;
    acknowledged: string;
    archive: string;
}

interface ReviewDraft {
    acknowledged: boolean;
    analysisNotes: string;
    responseToUser: string;
    actionTaken: string;
}

function formatDate(value?: string): string {
    if (!value) return 'N/A';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function queryFor(filters: Filters, page?: number, pageSize?: number): string {
    const params = new URLSearchParams();
    if (page !== undefined) params.set('page', String(page));
    if (pageSize !== undefined) params.set('page_size', String(pageSize));
    if (filters.type) params.set('type', filters.type);
    if (filters.acknowledged) params.set('ack', filters.acknowledged);
    params.set('archive', filters.archive);
    return params.toString();
}

function TypeBadge({ value }: { value?: string }) {
    const tone = value === 'Positive'
        ? 'bg-ok-soft text-ok'
        : value === 'Negative'
            ? 'bg-danger-soft text-danger'
            : 'bg-surface-2 text-text-2';
    return <span className={`rounded-full px-2 py-0.5 text-xs ${tone}`}>{value || 'Unknown'}</span>;
}

function AcknowledgedBadge({ value }: { value: boolean }) {
    return (
        <span className={`rounded-full px-2 py-0.5 text-xs ${value ? 'bg-ok-soft text-ok' : 'bg-warn-soft text-warn'}`}>
            {value ? 'Acknowledged' : 'Awaiting review'}
        </span>
    );
}

function Stat({ label, value }: { label: string; value?: number }) {
    return (
        <GlassPanel elevation="flat" className="p-3">
            <div className="text-lg font-semibold text-text-1">{value ?? 0}</div>
            <div className="text-xs text-text-3">{label}</div>
        </GlassPanel>
    );
}

function ActionButtons({
    item,
    onReview,
    onRetest,
    onArchive,
    onDelete,
    busy,
}: {
    item: FeedbackItem;
    onReview: (item: FeedbackItem) => void;
    onRetest: (item: FeedbackItem) => void;
    onArchive: (item: FeedbackItem) => void;
    onDelete: (item: FeedbackItem) => void;
    busy: boolean;
}) {
    return (
        <div className="flex flex-wrap gap-1.5">
            <GlassButton type="button" size="sm" variant="subtle" onClick={() => onReview(item)} disabled={busy}>
                <Eye size={13} /> Review
            </GlassButton>
            <GlassButton type="button" size="sm" variant="ghost" onClick={() => onRetest(item)} disabled={busy}>
                <RefreshCw size={13} /> Retest
            </GlassButton>
            <GlassButton type="button" size="sm" variant="ghost" onClick={() => onArchive(item)} disabled={busy}>
                {item.isArchived ? <RotateCcw size={13} /> : <Archive size={13} />}
                {item.isArchived ? 'Restore' : 'Archive'}
            </GlassButton>
            <GlassButton type="button" size="sm" variant="danger" onClick={() => onDelete(item)} disabled={busy}>
                <Trash2 size={13} /> Delete
            </GlassButton>
        </div>
    );
}

export function AdminFeedbackReviewPage() {
    const [filters, setFilters] = useState<Filters>({ type: '', acknowledged: '', archive: 'active' });
    const [draftFilters, setDraftFilters] = useState<Filters>(filters);
    const [items, setItems] = useState<FeedbackItem[]>([]);
    const [stats, setStats] = useState<FeedbackStats | null>(null);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [totalCount, setTotalCount] = useState(0);
    const [statsError, setStatsError] = useState<string | null>(null);
    const [viewMode, setViewMode] = useState<'list' | 'cards'>(() => {
        try {
            return window.localStorage.getItem(VIEW_STORAGE_KEY) === 'cards' ? 'cards' : 'list';
        } catch {
            return 'list';
        }
    });
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<{ message: string; warning?: boolean } | null>(null);
    const [selected, setSelected] = useState<FeedbackItem | null>(null);
    const [draft, setDraft] = useState<ReviewDraft | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [retestItem, setRetestItem] = useState<FeedbackItem | null>(null);
    const [retestText, setRetestText] = useState('');
    const [retestLoading, setRetestLoading] = useState(false);
    const [retestError, setRetestError] = useState<string | null>(null);
    const [pendingDelete, setPendingDelete] = useState<FeedbackItem | null>(null);
    const [deleteError, setDeleteError] = useState<string | null>(null);
    const [refresh, setRefresh] = useState(0);

    const filterQuery = useMemo(() => queryFor(filters), [filters]);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        const listQuery = queryFor(filters, page, pageSize);
        void Promise.allSettled([
            api.get<FeedbackPageResponse>(`/feedback/review?${listQuery}`, controller.signal),
            api.get<FeedbackStats>(`/feedback/review/stats?${filterQuery}`, controller.signal),
        ]).then(([listResult, statsResult]) => {
            if (controller.signal.aborted) return;
            if (listResult.status === 'fulfilled') {
                const response = listResult.value;
                setItems(response?.feedback ?? []);
                setPage(response?.page ?? page);
                setPageSize(response?.page_size ?? pageSize);
                setTotalCount(response?.total_count ?? 0);
            } else {
                setError(listResult.reason instanceof Error
                    ? listResult.reason.message
                    : 'Feedback could not be loaded.');
                setItems([]);
            }
            setStats(statsResult.status === 'fulfilled' ? statsResult.value : null);
            setStatsError(statsResult.status === 'rejected'
                ? statsResult.reason instanceof Error
                    ? statsResult.reason.message
                    : 'Feedback statistics could not be loaded.'
                : null);
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [filters, filterQuery, page, pageSize, refresh]);

    const setMode = (mode: 'list' | 'cards') => {
        setViewMode(mode);
        try {
            window.localStorage.setItem(VIEW_STORAGE_KEY, mode);
        } catch {
            // The current session's selection remains usable when storage is unavailable.
        }
    };

    const openReview = async (item: FeedbackItem) => {
        setSelected(item);
        setDraft(null);
        setDetailError(null);
        setDetailLoading(true);
        try {
            const detail = await api.get<FeedbackItem>(`/feedback/review/${encodeURIComponent(item.id)}`);
            setSelected(detail);
            setDraft({
                acknowledged: Boolean(detail.adminReview?.acknowledged),
                analysisNotes: detail.adminReview?.analysisNotes ?? '',
                responseToUser: detail.adminReview?.responseToUser ?? '',
                actionTaken: detail.adminReview?.actionTaken ?? '',
            });
        } catch (caught) {
            setDetailError(caught instanceof Error ? caught.message : 'Feedback details could not be loaded.');
        } finally {
            setDetailLoading(false);
        }
    };

    const saveReview = async () => {
        if (!selected || !draft) return;
        setSaving(true);
        setDetailError(null);
        try {
            await api.patch(`/feedback/review/${encodeURIComponent(selected.id)}`, draft);
            setSelected(null);
            setDraft(null);
            setRefresh((value) => value + 1);
            setNotice({ message: 'Feedback review saved.' });
        } catch (caught) {
            setDetailError(caught instanceof ApiError ? caught.message : 'Feedback review could not be saved.');
        } finally {
            setSaving(false);
        }
    };

    const updateArchive = async (item: FeedbackItem) => {
        setBusyId(item.id);
        setError(null);
        try {
            const result = await api.patch<{ message?: string; audit_warning?: string }>(
                `/feedback/review/${encodeURIComponent(item.id)}/archive`,
                { archived: !item.isArchived },
            );
            setNotice({
                message: result.audit_warning || result.message || 'Feedback record updated.',
                warning: Boolean(result.audit_warning),
            });
            setRefresh((value) => value + 1);
            if (selected?.id === item.id) setSelected(null);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Feedback record could not be archived.');
        } finally {
            setBusyId(null);
        }
    };

    const deleteFeedback = async () => {
        if (!pendingDelete) return;
        const item = pendingDelete;
        setBusyId(item.id);
        setDeleteError(null);
        try {
            const result = await api.delete<{ message?: string; audit_warning?: string }>(
                `/feedback/review/${encodeURIComponent(item.id)}`,
            );
            setPendingDelete(null);
            setDeleteError(null);
            if (selected?.id === item.id) {
                setSelected(null);
                setDraft(null);
            }
            if (items.length === 1 && page > 1) setPage((value) => value - 1);
            else setRefresh((value) => value + 1);
            setNotice({
                message: result.audit_warning || result.message || 'Feedback record permanently deleted.',
                warning: Boolean(result.audit_warning),
            });
        } catch (caught) {
            setDeleteError(caught instanceof Error ? caught.message : 'Feedback could not be deleted.');
        } finally {
            setBusyId(null);
        }
    };

    const runRetest = async (item: FeedbackItem) => {
        setRetestItem(item);
        setRetestText('');
        setRetestError(null);
        setRetestLoading(true);
        try {
            const result = await api.post<{ retestResponse?: string }>(
                `/feedback/retest/${encodeURIComponent(item.id)}`,
                { prompt: item.prompt ?? '' },
            );
            setRetestText(result.retestResponse || 'No retest response was returned.');
        } catch (caught) {
            setRetestError(caught instanceof Error ? caught.message : 'The prompt could not be retested.');
        } finally {
            setRetestLoading(false);
        }
    };

    const maxPage = Math.max(1, Math.ceil(totalCount / pageSize));
    const isBusy = (id: string) => busyId === id;

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader
                title="Feedback Review"
                description="Review user feedback, track acknowledgement coverage, and manage the review queue."
                actions={
                    <a
                        href={apiUrl(`/feedback/review/export?${filterQuery}`)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-edge px-3 py-2 text-xs font-medium text-text-1 hover:bg-surface-2"
                    >
                        <Download size={14} /> Export CSV
                    </a>
                }
            />
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
                {notice && (
                    <p role="status" className={`rounded-xl border px-3 py-2 text-sm ${notice.warning ? 'border-warn/30 bg-warn-soft text-warn' : 'border-ok/30 bg-ok-soft text-ok'}`}>
                        {notice.message}
                    </p>
                )}
                {error && <p role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
                {statsError && <p role="alert" className="rounded-xl border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-warn">Feedback statistics are unavailable: {statsError}</p>}

                <div className="grid grid-cols-2 gap-2 lg:grid-cols-3 2xl:grid-cols-6">
                    <Stat label="Total" value={stats?.total_count} />
                    <Stat label="Positive" value={stats?.positive_count} />
                    <Stat label="Negative" value={stats?.negative_count} />
                    <Stat label="Neutral" value={stats?.neutral_count} />
                    <Stat label="Acknowledged" value={stats?.acknowledged_count} />
                    <Stat label="Recent 30 days" value={stats?.recent_30_day_count} />
                </div>

                <GlassPanel elevation="flat" className="space-y-3 p-3">
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_auto_auto] xl:items-end">
                        <label className="block text-xs font-medium text-text-2">
                            Feedback type
                            <select
                                value={draftFilters.type}
                                onChange={(event) => setDraftFilters((current) => ({ ...current, type: event.target.value }))}
                                className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1"
                            >
                                <option value="">All types</option>
                                <option value="Positive">Positive</option>
                                <option value="Negative">Negative</option>
                                <option value="Neutral">Neutral</option>
                            </select>
                        </label>
                        <label className="block text-xs font-medium text-text-2">
                            Acknowledgement
                            <select
                                value={draftFilters.acknowledged}
                                onChange={(event) => setDraftFilters((current) => ({ ...current, acknowledged: event.target.value }))}
                                className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1"
                            >
                                <option value="">All statuses</option>
                                <option value="true">Acknowledged</option>
                                <option value="false">Not acknowledged</option>
                            </select>
                        </label>
                        <label className="block text-xs font-medium text-text-2">
                            Records
                            <select
                                value={draftFilters.archive}
                                onChange={(event) => setDraftFilters((current) => ({ ...current, archive: event.target.value }))}
                                className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1"
                            >
                                <option value="active">Active</option>
                                <option value="archived">Archived</option>
                            </select>
                        </label>
                        <div className="flex gap-2">
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="primary"
                                onClick={() => {
                                    setPage(1);
                                    setFilters(draftFilters);
                                }}
                            >
                                Apply filters
                            </GlassButton>
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                    const cleared = { type: '', acknowledged: '', archive: 'active' };
                                    setDraftFilters(cleared);
                                    setFilters(cleared);
                                    setPage(1);
                                }}
                            >
                                Clear
                            </GlassButton>
                        </div>
                        <div className="flex justify-end gap-1">
                            <button
                                type="button"
                                aria-label="List view"
                                aria-pressed={viewMode === 'list'}
                                onClick={() => setMode('list')}
                                className={`rounded-lg p-2 ${viewMode === 'list' ? 'bg-accent-soft text-accent' : 'text-text-3 hover:bg-surface-2'}`}
                            >
                                <List size={16} />
                            </button>
                            <button
                                type="button"
                                aria-label="Card view"
                                aria-pressed={viewMode === 'cards'}
                                onClick={() => setMode('cards')}
                                className={`rounded-lg p-2 ${viewMode === 'cards' ? 'bg-accent-soft text-accent' : 'text-text-3 hover:bg-surface-2'}`}
                            >
                                <Grid2X2 size={16} />
                            </button>
                        </div>
                    </div>
                    <div className="flex items-center justify-between border-t border-edge pt-3">
                        <label className="flex items-center gap-2 text-xs text-text-3">
                            Rows
                            <select
                                value={pageSize}
                                onChange={(event) => {
                                    setPageSize(Number(event.target.value));
                                    setPage(1);
                                }}
                                className="rounded-lg border border-edge bg-surface-solid px-2 py-1 text-text-1"
                            >
                                {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
                            </select>
                        </label>
                        <button type="button" onClick={() => setRefresh((value) => value + 1)} disabled={loading} className="inline-flex items-center gap-1 text-xs text-text-3 hover:text-text-1 disabled:opacity-50">
                            <RefreshCw size={13} /> Refresh
                        </button>
                    </div>
                </GlassPanel>

                {loading ? (
                    <div className="space-y-2"><Skeleton className="h-24 w-full" /><Skeleton className="h-24 w-full" /></div>
                ) : items.length === 0 ? (
                    <GlassPanel elevation="flat" className="p-8 text-center text-sm text-text-3">
                        No feedback found for the current filters.
                    </GlassPanel>
                ) : viewMode === 'list' ? (
                    <GlassPanel elevation="flat" className="overflow-x-auto p-0">
                        <table className="w-full min-w-[760px] text-left text-sm">
                            <thead className="border-b border-edge text-xs text-text-3">
                                <tr><th className="p-3">Submitted</th><th className="p-3">Prompt</th><th className="p-3">Rating</th><th className="p-3">Review</th><th className="p-3">Actions</th></tr>
                            </thead>
                            <tbody className="divide-y divide-edge">
                                {items.map((item) => (
                                    <tr key={item.id} className="align-top">
                                        <td className="whitespace-nowrap p-3 text-xs text-text-3">{formatDate(item.timestamp)}</td>
                                        <td className="max-w-md p-3"><p className="line-clamp-3 break-words">{item.prompt || 'No prompt captured.'}</p></td>
                                        <td className="p-3"><TypeBadge value={item.feedbackType} /></td>
                                        <td className="p-3"><AcknowledgedBadge value={Boolean(item.adminReview?.acknowledged)} /></td>
                                        <td className="p-3"><ActionButtons item={item} onReview={(value) => void openReview(value)} onRetest={(value) => void runRetest(value)} onArchive={(value) => void updateArchive(value)} onDelete={(value) => { setDeleteError(null); setPendingDelete(value); }} busy={isBusy(item.id)} /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </GlassPanel>
                ) : (
                    <div className="grid gap-3 xl:grid-cols-2 2xl:grid-cols-3">
                        {items.map((item) => (
                            <GlassPanel key={item.id} elevation="flat" className="flex min-w-0 flex-col gap-3 p-4">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <span className="text-xs text-text-3">{formatDate(item.timestamp)}</span>
                                    <div className="flex flex-wrap gap-1.5"><TypeBadge value={item.feedbackType} /><AcknowledgedBadge value={Boolean(item.adminReview?.acknowledged)} /></div>
                                </div>
                                <p className="line-clamp-3 break-words text-sm font-medium text-text-1">{item.prompt || 'No prompt captured.'}</p>
                                {item.reason ? <p className="text-sm text-text-2">{item.reason}</p> : null}
                                {item.adminReview?.actionTaken ? <p className="text-xs text-text-3">Action: {item.adminReview.actionTaken}</p> : null}
                                <div className="mt-auto"><ActionButtons item={item} onReview={(value) => void openReview(value)} onRetest={(value) => void runRetest(value)} onArchive={(value) => void updateArchive(value)} onDelete={(value) => { setDeleteError(null); setPendingDelete(value); }} busy={isBusy(item.id)} /></div>
                            </GlassPanel>
                        ))}
                    </div>
                )}

                <div className="flex items-center justify-between text-xs text-text-3">
                    <span>{totalCount ? `Page ${page} of ${maxPage} · ${totalCount} submissions` : 'No submissions'}</span>
                    <div className="flex gap-2">
                        <GlassButton type="button" size="sm" variant="ghost" disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</GlassButton>
                        <GlassButton type="button" size="sm" variant="ghost" disabled={page >= maxPage || loading} onClick={() => setPage((value) => Math.min(maxPage, value + 1))}>Next</GlassButton>
                    </div>
                </div>
            </div>

            {selected && (
                <AdminModal
                    title="Feedback review"
                    description={`Submitted ${formatDate(selected.timestamp)} · User ${selected.userId || 'unknown'}`}
                    size="lg"
                    onClose={() => {
                        if (!saving) {
                            setSelected(null);
                            setDraft(null);
                        }
                    }}
                    footer={
                        <>
                            <GlassButton type="button" variant="ghost" size="sm" onClick={() => setSelected(null)} disabled={saving}>Close</GlassButton>
                            {selected.isArchived ? (
                                <GlassButton type="button" variant="subtle" size="sm" onClick={() => void updateArchive(selected)} disabled={saving || isBusy(selected.id)}>
                                    <RotateCcw size={14} /> Restore
                                </GlassButton>
                            ) : (
                                <GlassButton type="button" variant="subtle" size="sm" onClick={() => void updateArchive(selected)} disabled={saving || isBusy(selected.id)}>
                                    <Archive size={14} /> Archive
                                </GlassButton>
                            )}
                            <GlassButton type="button" variant="primary" size="sm" onClick={() => void saveReview()} disabled={!draft || saving || detailLoading}>
                                <Check size={14} /> {saving ? 'Saving…' : 'Save review'}
                            </GlassButton>
                        </>
                    }
                >
                    {detailLoading ? <Skeleton className="h-48 w-full" /> : detailError ? (
                        <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{detailError}</p>
                    ) : (
                        <div className="space-y-4">
                            <div className="flex flex-wrap gap-2"><TypeBadge value={selected.feedbackType} /><AcknowledgedBadge value={Boolean(draft?.acknowledged)} /></div>
                            <div><h3 className="text-xs font-semibold text-text-3">Prompt</h3><p className="mt-1 whitespace-pre-wrap break-words text-sm text-text-1">{selected.prompt || 'No prompt captured.'}</p></div>
                            <div><h3 className="text-xs font-semibold text-text-3">Assistant response</h3><p className="mt-1 max-h-56 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-3 text-sm text-text-1">{selected.aiResponse || 'No response captured.'}</p></div>
                            <div><h3 className="text-xs font-semibold text-text-3">User feedback</h3><p className="mt-1 whitespace-pre-wrap break-words text-sm text-text-1">{selected.reason || 'No additional reason provided.'}</p></div>
                            {draft && (
                                <>
                                    <label className="flex items-center gap-2 text-sm text-text-1">
                                        <input type="checkbox" checked={draft.acknowledged} onChange={(event) => setDraft((value) => value ? { ...value, acknowledged: event.target.checked } : value)} />
                                        Acknowledged
                                    </label>
                                    <label className="block text-xs font-medium text-text-2">Analysis notes<textarea rows={3} value={draft.analysisNotes} onChange={(event) => setDraft({ ...draft, analysisNotes: event.target.value })} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1" /></label>
                                    <label className="block text-xs font-medium text-text-2">Response to user<textarea rows={3} value={draft.responseToUser} onChange={(event) => setDraft({ ...draft, responseToUser: event.target.value })} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1" /></label>
                                    <label className="block text-xs font-medium text-text-2">Action taken<input value={draft.actionTaken} onChange={(event) => setDraft({ ...draft, actionTaken: event.target.value })} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1" /></label>
                                </>
                            )}
                        </div>
                    )}
                </AdminModal>
            )}

            {retestItem && (
                <AdminModal title="Prompt retest" description={`Current model configuration · ${formatDate(retestItem.timestamp)}`} size="lg" onClose={() => setRetestItem(null)}>
                    {retestLoading ? <div className="space-y-3"><Skeleton className="h-5 w-40" /><Skeleton className="h-36 w-full" /></div> : retestError ? (
                        <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{retestError}</p>
                    ) : (
                        <div className="space-y-3">
                            <div><h3 className="text-xs font-semibold text-text-3">Original prompt</h3><p className="mt-1 whitespace-pre-wrap break-words text-sm text-text-1">{retestItem.prompt || 'No prompt captured.'}</p></div>
                            <div><h3 className="text-xs font-semibold text-text-3">Retest response</h3><p className="mt-1 whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-3 text-sm text-text-1">{retestText}</p></div>
                        </div>
                    )}
                </AdminModal>
            )}

            {pendingDelete && (
                <ConfirmDialog
                    title="Permanently delete feedback?"
                    description="This removes the feedback record and cannot be undone. The lifecycle audit entry is retained."
                    confirmLabel="Permanently delete"
                    busy={busyId === pendingDelete.id}
                    onClose={() => {
                        if (busyId !== pendingDelete.id) {
                            setPendingDelete(null);
                            setDeleteError(null);
                        }
                    }}
                    onConfirm={() => void deleteFeedback()}
                >
                    <div className="space-y-2 text-xs text-text-2">
                        <p>This cannot be undone. The lifecycle audit entry is retained.</p>
                        {deleteError && <p role="alert" className="text-danger">{deleteError}</p>}
                    </div>
                </ConfirmDialog>
            )}
        </div>
    );
}
