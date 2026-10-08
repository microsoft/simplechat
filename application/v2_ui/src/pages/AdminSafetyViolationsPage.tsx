// AdminSafetyViolationsPage.tsx

import { useEffect, useMemo, useState } from 'react';
import { Archive, Check, Download, Eye, Grid2X2, List, RefreshCw, RotateCcw, ShieldAlert, Trash2 } from 'lucide-react';
import { api, apiUrl, ApiError } from '../lib/apiClient';
import { PageHeader } from '../components/layout/PageHeader';
import { AdminModal } from '../components/admin/AdminModal';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';

const PAGE_SIZES = [10, 20, 50, 100];
const VIEW_STORAGE_KEY = 'simplechat.v2.admin.safety.viewMode';
const STATUSES = ['New', 'In-Review', 'Resolved', 'Dismissed'];
const ACTIONS = ['None', 'WarnUser', 'SuspendUser', 'BlockUser'];
// Escalate is no longer an action. A record that already carries it keeps it, labelled as
// legacy, and only that record's review offers it again.
const LEGACY_ESCALATE_ACTION = 'Escalate';
const REMEDIATION_ACTIONS = new Set(['WarnUser', 'SuspendUser', 'BlockUser']);

function actionLabel(value: string): string {
    if (value === LEGACY_ESCALATE_ACTION) return 'Escalated (legacy)';
    return value === 'None' ? 'None' : value.replace(/([a-z])([A-Z])/g, '$1 $2');
}

/** A warning that was sent. Saving the record again does not resend it. */
function isExecutedWarning(log: SafetyLog): boolean {
    return log.action === 'WarnUser' && (log.action_request_status || '').toLowerCase() === 'executed';
}

interface TriggeredCategory {
    category?: string;
    severity?: number;
}

interface SafetyLog {
    id: string;
    user_id?: string;
    message?: string;
    triggered_categories?: TriggeredCategory[];
    status?: string;
    action?: string;
    user_notes?: string;
    notes?: string;
    created_at?: string;
    last_updated?: string;
    content_origin?: string;
    action_request_status?: string;
    action_notification_message?: string;
    action_datetime_to_allow?: string;
    /** Set on an executed warning: `pending` until the user acknowledges it. */
    warning_acknowledgment_status?: 'pending' | 'acknowledged' | 'not_tracked' | null;
    warning_acknowledged_at?: string | null;
    warning_issued_at?: string | null;
    isArchived?: boolean;
}

interface SafetyPageResponse {
    logs?: SafetyLog[];
    page?: number;
    page_size?: number;
    total_count?: number;
}

interface SafetyStats {
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
    latest_timestamp?: string;
}

interface Filters {
    status: string;
    action: string;
    archive: string;
}

interface ReviewDraft {
    status: string;
    action: string;
    notes: string;
    notificationMessage: string;
    datetimeToAllow: string;
}

interface UncheckedChatItem {
    source: string;
    conversation_id: string;
    message_id: string;
    etag?: string;
    check?: {
        checkpoint?: string;
        attempted_at?: string;
        status?: string;
        scanners?: Array<{
            scanner?: string;
            complete?: boolean;
            error_code?: string;
        }>;
    };
}

interface UncheckedChatPage {
    items?: UncheckedChatItem[];
    continuation?: string | null;
}

function formatDate(value?: string): string {
    if (!value) return 'N/A';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function toLocalDateTime(value?: string): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function toIsoDateTime(value: string): string | null {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function queryFor(filters: Filters, page?: number, pageSize?: number): string {
    const params = new URLSearchParams();
    if (page !== undefined) params.set('page', String(page));
    if (pageSize !== undefined) params.set('page_size', String(pageSize));
    if (filters.status) params.set('status', filters.status);
    if (filters.action) params.set('action', filters.action);
    params.set('archive', filters.archive);
    return params.toString();
}

function categoryText(log: SafetyLog): string {
    return (log.triggered_categories ?? [])
        .filter((entry) => entry?.category)
        .map((entry) => `${entry.category} (severity ${entry.severity ?? '?'})`)
        .join(', ');
}

function defaultNotification(log: SafetyLog, action: string): string {
    const lines = [
        'A safety review has been completed for recent activity in your workspace.',
        `Violation ID: ${log.id || '-'}`,
    ];
    const categories = categoryText(log);
    if (categories) lines.push(`Triggered categories: ${categories}`);
    if (action === 'WarnUser') {
        lines.push('Action taken: Warning issued. Please review the acceptable use requirements before continuing.');
    } else if (action === 'SuspendUser') {
        lines.push('Action taken: Your access has been temporarily suspended pending the restore date below.');
    } else if (action === 'BlockUser') {
        lines.push('Action taken: Your access has been blocked with no automatic restore date.');
    }
    if (log.notes) lines.push(`Admin notes: ${log.notes}`);
    return lines.join('\n');
}

function StatusBadge({ value }: { value?: string }) {
    const tone = value === 'Resolved'
        ? 'bg-ok-soft text-ok'
        : value === 'Dismissed'
            ? 'bg-surface-2 text-text-3'
            : value === 'In-Review'
                ? 'bg-info-soft text-info'
                : 'bg-warn-soft text-warn';
    return <span className={`rounded-full px-2 py-0.5 text-xs ${tone}`}>{value || 'New'}</span>;
}

function ActionBadge({ log }: { log: SafetyLog }) {
    const label = actionLabel(log.action || 'None');
    const requestStatus = (log.action_request_status || '').toLowerCase();
    let suffix = requestStatus === 'pending' ? ' · Pending approval' : requestStatus === 'failed' ? ' · Failed' : '';
    if (isExecutedWarning(log)) {
        if (log.warning_acknowledgment_status === 'acknowledged') suffix = ' · Acknowledged';
        else if (log.warning_acknowledgment_status === 'pending') suffix = ' · Not yet acknowledged';
    }
    return <span className="rounded-full border border-edge px-2 py-0.5 text-xs text-text-2">{label}{suffix}</span>;
}

/** Whether the user has acknowledged a warning that was sent, for the review dialog. */
function warningAcknowledgmentText(log: SafetyLog): string | null {
    if (!isExecutedWarning(log)) return null;
    if (log.warning_acknowledgment_status === 'acknowledged') {
        return `Warning acknowledged ${formatDate(log.warning_acknowledged_at ?? undefined)}`;
    }
    if (log.warning_acknowledgment_status === 'pending') {
        return 'Warning sent. Not yet acknowledged by the user.';
    }
    return 'Warning sent before acknowledgment was tracked.';
}

function Stat({ label, value }: { label: string; value?: number }) {
    return (
        <GlassPanel elevation="flat" className="p-3">
            <div className="text-lg font-semibold text-text-1">{value ?? 0}</div>
            <div className="text-xs text-text-3">{label}</div>
        </GlassPanel>
    );
}

function ViolationActions({
    log,
    onReview,
    onArchive,
    onDelete,
    busy,
}: {
    log: SafetyLog;
    onReview: (log: SafetyLog) => void;
    onArchive: (log: SafetyLog) => void;
    onDelete: (log: SafetyLog) => void;
    busy: boolean;
}) {
    return (
        <div className="flex flex-wrap gap-1.5">
            <GlassButton type="button" size="sm" variant="subtle" onClick={() => onReview(log)} disabled={busy}>
                <Eye size={13} /> Review
            </GlassButton>
            <GlassButton type="button" size="sm" variant="ghost" onClick={() => onArchive(log)} disabled={busy}>
                {log.isArchived ? <RotateCcw size={13} /> : <Archive size={13} />}
                {log.isArchived ? 'Restore' : 'Archive'}
            </GlassButton>
            <GlassButton type="button" size="sm" variant="danger" onClick={() => onDelete(log)} disabled={busy || (log.action_request_status || '').toLowerCase() === 'pending'}>
                <Trash2 size={13} /> Delete
            </GlassButton>
        </div>
    );
}

export function AdminSafetyViolationsPage() {
    const [filters, setFilters] = useState<Filters>({ status: '', action: '', archive: 'active' });
    const [draftFilters, setDraftFilters] = useState<Filters>(filters);
    const [logs, setLogs] = useState<SafetyLog[]>([]);
    const [stats, setStats] = useState<SafetyStats | null>(null);
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
    const [selected, setSelected] = useState<SafetyLog | null>(null);
    const [draft, setDraft] = useState<ReviewDraft | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [pendingDelete, setPendingDelete] = useState<SafetyLog | null>(null);
    const [deleteError, setDeleteError] = useState<string | null>(null);
    const [refresh, setRefresh] = useState(0);
    const filterQuery = useMemo(() => queryFor(filters), [filters]);

    const [uncheckedFilters, setUncheckedFilters] = useState({ source: 'all', checkpoint: '', scanner: '' });
    const [uncheckedItems, setUncheckedItems] = useState<UncheckedChatItem[]>([]);
    const [uncheckedContinuation, setUncheckedContinuation] = useState<string | null>(null);
    const [uncheckedLoading, setUncheckedLoading] = useState(true);
    const [uncheckedMoreLoading, setUncheckedMoreLoading] = useState(false);
    const [uncheckedError, setUncheckedError] = useState<string | null>(null);
    const [uncheckedNotice, setUncheckedNotice] = useState<{ message: string; warning?: boolean } | null>(null);
    const [uncheckedRefresh, setUncheckedRefresh] = useState(0);
    const [pendingRecheck, setPendingRecheck] = useState<UncheckedChatItem | null>(null);
    const [rechecking, setRechecking] = useState(false);
    const [recheckError, setRecheckError] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        const listQuery = queryFor(filters, page, pageSize);
        void Promise.allSettled([
            api.get<SafetyPageResponse>(`/api/safety/logs?${listQuery}`, controller.signal),
            api.get<SafetyStats>(`/api/safety/logs/stats?${filterQuery}`, controller.signal),
        ]).then(([listResult, statsResult]) => {
            if (controller.signal.aborted) return;
            if (listResult.status === 'fulfilled') {
                const response = listResult.value;
                setLogs(response?.logs ?? []);
                setPage(response?.page ?? page);
                setPageSize(response?.page_size ?? pageSize);
                setTotalCount(response?.total_count ?? 0);
            } else {
                setError(listResult.reason instanceof Error ? listResult.reason.message : 'Safety violations could not be loaded.');
                setLogs([]);
            }
            setStats(statsResult.status === 'fulfilled' ? statsResult.value : null);
            setStatsError(statsResult.status === 'rejected'
                ? statsResult.reason instanceof Error
                    ? statsResult.reason.message
                    : 'Safety statistics could not be loaded.'
                : null);
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [filters, filterQuery, page, pageSize, refresh]);

    useEffect(() => {
        const controller = new AbortController();
        const params = new URLSearchParams({ source: uncheckedFilters.source, page_size: '25' });
        if (uncheckedFilters.checkpoint) params.set('checkpoint', uncheckedFilters.checkpoint);
        if (uncheckedFilters.scanner) params.set('scanner', uncheckedFilters.scanner);
        setUncheckedLoading(true);
        setUncheckedError(null);
        setUncheckedItems([]);
        setUncheckedContinuation(null);
        void api.get<UncheckedChatPage>(`/api/safety/chat-checks?${params}`, controller.signal)
            .then((response) => {
                if (controller.signal.aborted) return;
                if (!Array.isArray(response?.items)) throw new Error('The unchecked-message response was invalid.');
                setUncheckedItems(response.items);
                setUncheckedContinuation(response.continuation ?? null);
            })
            .catch((caught) => {
                if (!controller.signal.aborted) {
                    setUncheckedError(caught instanceof Error ? caught.message : 'Unchecked messages could not be loaded.');
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) setUncheckedLoading(false);
            });
        return () => controller.abort();
    }, [uncheckedFilters, uncheckedRefresh]);

    const setMode = (mode: 'list' | 'cards') => {
        setViewMode(mode);
        try {
            window.localStorage.setItem(VIEW_STORAGE_KEY, mode);
        } catch {
            // The current session's selection remains usable when storage is unavailable.
        }
    };

    const openReview = (log: SafetyLog) => {
        setSelected(log);
        setDetailError(null);
        setDraft({
            status: log.status || 'New',
            action: log.action || 'None',
            notes: log.notes || '',
            notificationMessage: log.action_notification_message || (
                REMEDIATION_ACTIONS.has(log.action || '') ? defaultNotification(log, log.action || '') : ''
            ),
            datetimeToAllow: toLocalDateTime(log.action_datetime_to_allow),
        });
    };

    const saveReview = async () => {
        if (!selected || !draft) return;
        const action = draft.action;
        const payload: Record<string, unknown> = {
            status: draft.status,
            action,
            notes: draft.notes,
        };
        if (REMEDIATION_ACTIONS.has(action) && !(action === 'WarnUser' && isExecutedWarning(selected))) {
            payload.notification_message = draft.notificationMessage;
            if (action === 'SuspendUser') {
                const restoreDate = toIsoDateTime(draft.datetimeToAllow);
                if (!restoreDate) {
                    setDetailError('Restore access date is required for a suspension.');
                    return;
                }
                payload.datetime_to_allow = restoreDate;
            }
        }
        setSaving(true);
        setDetailError(null);
        try {
            const result = await api.patch<{ message?: string; approval_required?: boolean; audit_warning?: string }>(
                `/api/safety/logs/${encodeURIComponent(selected.id)}`,
                payload,
            );
            setSelected(null);
            setDraft(null);
            setNotice({
                message: result.audit_warning || result.message || 'Safety review saved.',
                warning: Boolean(result.approval_required || result.audit_warning),
            });
            setRefresh((value) => value + 1);
        } catch (caught) {
            setDetailError(caught instanceof ApiError ? caught.message : 'Safety review could not be saved.');
        } finally {
            setSaving(false);
        }
    };

    const updateArchive = async (log: SafetyLog) => {
        setBusyId(log.id);
        setError(null);
        try {
            const result = await api.patch<{ message?: string; audit_warning?: string }>(
                `/api/safety/logs/${encodeURIComponent(log.id)}/archive`,
                { archived: !log.isArchived },
            );
            setNotice({
                message: result.audit_warning || result.message || 'Safety violation updated.',
                warning: Boolean(result.audit_warning),
            });
            setRefresh((value) => value + 1);
            if (selected?.id === log.id) {
                setSelected(null);
                setDraft(null);
            }
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Safety violation could not be archived.');
        } finally {
            setBusyId(null);
        }
    };

    const deleteViolation = async () => {
        if (!pendingDelete) return;
        const log = pendingDelete;
        setBusyId(log.id);
        setDeleteError(null);
        try {
            const result = await api.delete<{ message?: string; audit_warning?: string }>(
                `/api/safety/logs/${encodeURIComponent(log.id)}`,
            );
            setPendingDelete(null);
            setDeleteError(null);
            if (selected?.id === log.id) {
                setSelected(null);
                setDraft(null);
            }
            if (logs.length === 1 && page > 1) setPage((value) => value - 1);
            else setRefresh((value) => value + 1);
            setNotice({
                message: result.audit_warning || result.message || 'Safety violation permanently deleted.',
                warning: Boolean(result.audit_warning),
            });
        } catch (caught) {
            setDeleteError(caught instanceof Error ? caught.message : 'Safety violation could not be deleted.');
        } finally {
            setBusyId(null);
        }
    };

    const loadMoreUnchecked = async () => {
        if (!uncheckedContinuation || uncheckedMoreLoading) return;
        const params = new URLSearchParams({
            source: uncheckedFilters.source,
            page_size: '25',
            continuation: uncheckedContinuation,
        });
        if (uncheckedFilters.checkpoint) params.set('checkpoint', uncheckedFilters.checkpoint);
        if (uncheckedFilters.scanner) params.set('scanner', uncheckedFilters.scanner);
        setUncheckedMoreLoading(true);
        setUncheckedError(null);
        try {
            const response = await api.get<UncheckedChatPage>(`/api/safety/chat-checks?${params}`);
            if (!Array.isArray(response?.items)) throw new Error('The unchecked-message response was invalid.');
            setUncheckedItems((current) => [
                ...current,
                ...response.items!.filter((item) => !current.some((existing) => (
                    existing.source === item.source
                    && existing.conversation_id === item.conversation_id
                    && existing.message_id === item.message_id
                ))),
            ]);
            setUncheckedContinuation(response.continuation ?? null);
        } catch (caught) {
            setUncheckedError(caught instanceof Error ? caught.message : 'More unchecked messages could not be loaded.');
        } finally {
            setUncheckedMoreLoading(false);
        }
    };

    const recheckUnchecked = async () => {
        if (!pendingRecheck || rechecking) return;
        const item = pendingRecheck;
        setRechecking(true);
        setRecheckError(null);
        try {
            const outcome = await api.post<{
                removed?: boolean;
                check?: { status?: string };
            }>('/api/safety/chat-checks/recheck', {
                source: item.source,
                conversation_id: item.conversation_id,
                message_id: item.message_id,
                etag: item.etag,
            });
            setPendingRecheck(null);
            if (outcome.removed) {
                setUncheckedNotice({ message: 'The AI reply was removed from saved chat and its shared copies.' });
            } else if (outcome.check?.status === 'passed') {
                setUncheckedNotice({ message: 'The message passed its required checks.' });
            } else if (outcome.check?.status === 'findings') {
                setUncheckedNotice({
                    message: 'The submitted message was flagged for review. Earlier model calls and actions have not been undone.',
                    warning: true,
                });
            } else {
                setUncheckedNotice({
                    message: 'The check could not finish. The message remains marked not checked and can be retried.',
                    warning: true,
                });
            }
            setUncheckedRefresh((value) => value + 1);
        } catch (caught) {
            setRecheckError(caught instanceof Error ? caught.message : 'The message could not be rechecked.');
        } finally {
            setRechecking(false);
        }
    };

    const maxPage = Math.max(1, Math.ceil(totalCount / pageSize));
    const isBusy = (id: string) => busyId === id;

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader
                title="Safety Violations"
                description="Review flagged activity, track remediation, and recheck messages with incomplete safety checks."
                actions={
                    <a
                        href={apiUrl(`/api/safety/logs/export?${filterQuery}`)}
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
                {statsError && <p role="alert" className="rounded-xl border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-warn">Safety statistics are unavailable: {statsError}</p>}

                <section aria-labelledby="unchecked-chat-heading" className="space-y-3">
                    <GlassPanel elevation="flat" className="space-y-3 p-4">
                        <div className="flex items-start gap-2">
                            <ShieldAlert size={18} className="mt-0.5 shrink-0 text-warn" />
                            <div>
                                <h2 id="unchecked-chat-heading" className="text-sm font-semibold text-text-1">Unchecked chat content</h2>
                                <p className="mt-1 text-xs text-text-3">
                                    These messages were allowed through when a required check could not finish. Rechecking uses current rules; confirmed findings can remove AI replies from saved and shared chat, but cannot undo earlier views or external actions.
                                </p>
                            </div>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                            <label className="block text-xs font-medium text-text-2">
                                Conversation source
                                <select value={uncheckedFilters.source} onChange={(event) => setUncheckedFilters((current) => ({ ...current, source: event.target.value }))} className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1">
                                    <option value="all">All sources</option>
                                    <option value="chat">Chat and canonical AI messages</option>
                                    <option value="shared">Shared user messages</option>
                                </select>
                            </label>
                            <label className="block text-xs font-medium text-text-2">
                                Message type
                                <select value={uncheckedFilters.checkpoint} onChange={(event) => setUncheckedFilters((current) => ({ ...current, checkpoint: event.target.value }))} className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1">
                                    <option value="">All message types</option>
                                    <option value="chat_input">Submitted messages</option>
                                    <option value="chat_output">AI replies</option>
                                </select>
                            </label>
                            <label className="block text-xs font-medium text-text-2">
                                Incomplete scanner
                                <select value={uncheckedFilters.scanner} onChange={(event) => setUncheckedFilters((current) => ({ ...current, scanner: event.target.value }))} className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1">
                                    <option value="">All scanners</option>
                                    <option value="content_screening">Content Screening</option>
                                    <option value="content_safety">Azure Content Safety</option>
                                </select>
                            </label>
                            <GlassButton type="button" variant="subtle" size="sm" className="self-end" disabled={uncheckedLoading} onClick={() => setUncheckedRefresh((value) => value + 1)}>
                                <RefreshCw size={14} /> Refresh unchecked messages
                            </GlassButton>
                        </div>
                        {uncheckedNotice && (
                            <p role="status" className={`rounded-lg border px-3 py-2 text-xs ${uncheckedNotice.warning ? 'border-warn/30 bg-warn-soft text-warn' : 'border-ok/30 bg-ok-soft text-ok'}`}>
                                {uncheckedNotice.message}
                            </p>
                        )}
                        {uncheckedError && <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger">{uncheckedError}</p>}
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[620px] text-left text-xs">
                                <caption className="sr-only">Private check metadata grouped by source. Message bodies are not shown in this queue.</caption>
                                <thead className="border-b border-edge text-text-3"><tr><th className="p-2">Message</th><th className="p-2">Type</th><th className="p-2">Incomplete checks</th><th className="p-2">Last attempt</th><th className="p-2">Action</th></tr></thead>
                                <tbody className="divide-y divide-edge">
                                    {uncheckedLoading ? (
                                        <tr><td colSpan={5} className="p-4 text-center text-text-3">Loading unchecked messages…</td></tr>
                                    ) : uncheckedItems.length === 0 ? (
                                        <tr><td colSpan={5} className="p-4 text-center text-text-3">No unchecked messages match these filters.</td></tr>
                                    ) : uncheckedItems.map((item) => (
                                        <tr key={`${item.source}:${item.conversation_id}:${item.message_id}`}>
                                            <td className="max-w-xs break-all p-2">{item.message_id}<span className="mt-1 block text-text-3">Conversation: {item.conversation_id}</span></td>
                                            <td className="p-2">{item.check?.checkpoint === 'chat_output' ? 'AI reply' : 'Submitted message'}</td>
                                            <td className="max-w-sm p-2">{(item.check?.scanners ?? []).filter((entry) => !entry.complete).map((entry) => `${entry.scanner === 'content_safety' ? 'Content Safety' : 'Content Screening'}: ${entry.error_code || 'incomplete'}`).join('; ') || 'Not recorded'}</td>
                                            <td className="whitespace-nowrap p-2 text-text-3">{formatDate(item.check?.attempted_at)}</td>
                                            <td className="p-2"><GlassButton type="button" size="sm" variant="subtle" disabled={!item.etag || uncheckedMoreLoading || rechecking} onClick={() => setPendingRecheck(item)}>Recheck</GlassButton></td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        {uncheckedContinuation && (
                            <GlassButton type="button" variant="ghost" size="sm" disabled={uncheckedMoreLoading || uncheckedLoading} onClick={() => void loadMoreUnchecked()}>
                                {uncheckedMoreLoading ? 'Loading…' : 'Load more unchecked messages'}
                            </GlassButton>
                        )}
                    </GlassPanel>
                </section>

                <div className="grid grid-cols-2 gap-2 lg:grid-cols-3 2xl:grid-cols-6">
                    <Stat label="Total" value={stats?.total_count} />
                    <Stat label="Open" value={(stats?.new_count ?? 0) + (stats?.in_review_count ?? 0)} />
                    <Stat label="Resolved" value={stats?.resolved_count} />
                    <Stat label="Dismissed" value={stats?.dismissed_count} />
                    <Stat label="Recent 30 days" value={stats?.recent_30_day_count} />
                    <Stat
                        label={(stats?.escalate_count ?? 0) > 0 ? `Blocked · ${stats?.escalate_count} escalated (legacy)` : 'Blocked'}
                        value={stats?.block_user_count}
                    />
                </div>
                <GlassPanel elevation="flat" className="grid gap-3 p-3 sm:grid-cols-2">
                    <div className="text-xs text-text-2">
                        <h2 className="mb-2 font-semibold text-text-1">Status distribution</h2>
                        <div className="flex flex-wrap gap-x-4 gap-y-1">
                            <span>New {stats?.new_count ?? 0}</span><span>In review {stats?.in_review_count ?? 0}</span>
                            <span>Resolved {stats?.resolved_count ?? 0}</span><span>Dismissed {stats?.dismissed_count ?? 0}</span>
                        </div>
                    </div>
                    <div className="text-xs text-text-2">
                        <h2 className="mb-2 font-semibold text-text-1">Action distribution</h2>
                        <div className="flex flex-wrap gap-x-4 gap-y-1">
                            <span>None {stats?.none_action_count ?? 0}</span><span>Warn {stats?.warn_user_count ?? 0}</span>
                            <span>Suspend {stats?.suspend_user_count ?? 0}</span><span>Block {stats?.block_user_count ?? 0}</span>
                            {(stats?.escalate_count ?? 0) > 0 && <span>Escalated (legacy) {stats?.escalate_count}</span>}
                        </div>
                    </div>
                </GlassPanel>

                <GlassPanel elevation="flat" className="space-y-3 p-3">
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_auto_auto] xl:items-end">
                        <label className="block text-xs font-medium text-text-2">
                            Status
                            <select value={draftFilters.status} onChange={(event) => setDraftFilters((current) => ({ ...current, status: event.target.value }))} className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1">
                                <option value="">All statuses</option>
                                {STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
                            </select>
                        </label>
                        <label className="block text-xs font-medium text-text-2">
                            Action
                            <select value={draftFilters.action} onChange={(event) => setDraftFilters((current) => ({ ...current, action: event.target.value }))} className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1">
                                <option value="">All actions</option>
                                {ACTIONS.map((value) => <option key={value} value={value}>{actionLabel(value)}</option>)}
                            </select>
                        </label>
                        <label className="block text-xs font-medium text-text-2">
                            Records
                            <select value={draftFilters.archive} onChange={(event) => setDraftFilters((current) => ({ ...current, archive: event.target.value }))} className="mt-1 block w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1">
                                <option value="active">Active</option>
                                <option value="archived">Archived</option>
                            </select>
                        </label>
                        <div className="flex gap-2">
                            <GlassButton type="button" size="sm" variant="primary" onClick={() => { setPage(1); setFilters(draftFilters); }}>Apply filters</GlassButton>
                            <GlassButton type="button" size="sm" variant="ghost" onClick={() => {
                                const cleared = { status: '', action: '', archive: 'active' };
                                setDraftFilters(cleared);
                                setFilters(cleared);
                                setPage(1);
                            }}>Clear</GlassButton>
                        </div>
                        <div className="flex justify-end gap-1">
                            <button type="button" aria-label="List view" aria-pressed={viewMode === 'list'} onClick={() => setMode('list')} className={`rounded-lg p-2 ${viewMode === 'list' ? 'bg-accent-soft text-accent' : 'text-text-3 hover:bg-surface-2'}`}><List size={16} /></button>
                            <button type="button" aria-label="Card view" aria-pressed={viewMode === 'cards'} onClick={() => setMode('cards')} className={`rounded-lg p-2 ${viewMode === 'cards' ? 'bg-accent-soft text-accent' : 'text-text-3 hover:bg-surface-2'}`}><Grid2X2 size={16} /></button>
                        </div>
                    </div>
                    <div className="flex items-center justify-between border-t border-edge pt-3">
                        <label className="flex items-center gap-2 text-xs text-text-3">
                            Rows
                            <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} className="rounded-lg border border-edge bg-surface-solid px-2 py-1 text-text-1">
                                {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
                            </select>
                        </label>
                        <button type="button" onClick={() => setRefresh((value) => value + 1)} disabled={loading} className="inline-flex items-center gap-1 text-xs text-text-3 hover:text-text-1 disabled:opacity-50"><RefreshCw size={13} /> Refresh</button>
                    </div>
                </GlassPanel>

                {loading ? (
                    <div className="space-y-2"><Skeleton className="h-24 w-full" /><Skeleton className="h-24 w-full" /></div>
                ) : logs.length === 0 ? (
                    <GlassPanel elevation="flat" className="p-8 text-center text-sm text-text-3">No safety violations found for the current filters.</GlassPanel>
                ) : viewMode === 'list' ? (
                    <GlassPanel elevation="flat" className="overflow-x-auto p-0">
                        <table className="w-full min-w-[780px] text-left text-sm">
                            <thead className="border-b border-edge text-xs text-text-3"><tr><th className="p-3">Message</th><th className="p-3">Triggered categories</th><th className="p-3">Status</th><th className="p-3">Action</th><th className="p-3">Review</th></tr></thead>
                            <tbody className="divide-y divide-edge">
                                {logs.map((log) => (
                                    <tr key={log.id} className="align-top">
                                        <td className="max-w-sm p-3"><p className="line-clamp-3 break-words">{log.message || 'No message captured.'}</p></td>
                                        <td className="max-w-sm p-3 text-xs text-text-3">{categoryText(log) || 'No triggered categories'}</td>
                                        <td className="p-3"><StatusBadge value={log.status} /></td>
                                        <td className="p-3"><ActionBadge log={log} /></td>
                                        <td className="p-3"><ViolationActions log={log} onReview={openReview} onArchive={(value) => void updateArchive(value)} onDelete={(value) => { setDeleteError(null); setPendingDelete(value); }} busy={isBusy(log.id)} /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </GlassPanel>
                ) : (
                    <div className="grid gap-3 xl:grid-cols-2 2xl:grid-cols-3">
                        {logs.map((log) => (
                            <GlassPanel key={log.id} elevation="flat" className="flex min-w-0 flex-col gap-3 p-4">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <span className="text-xs text-text-3">{formatDate(log.last_updated || log.created_at)}</span>
                                    <div className="flex flex-wrap gap-1.5"><StatusBadge value={log.status} /><ActionBadge log={log} /></div>
                                </div>
                                <p className="line-clamp-4 break-words text-sm font-medium text-text-1">{log.message || 'No message captured.'}</p>
                                <p className="text-xs text-text-3">{categoryText(log) || 'No triggered categories'}</p>
                                <div className="mt-auto"><ViolationActions log={log} onReview={openReview} onArchive={(value) => void updateArchive(value)} onDelete={(value) => { setDeleteError(null); setPendingDelete(value); }} busy={isBusy(log.id)} /></div>
                            </GlassPanel>
                        ))}
                    </div>
                )}
                <div className="flex items-center justify-between text-xs text-text-3">
                    <span>{totalCount ? `Page ${page} of ${maxPage} · ${totalCount} records` : 'No records'}</span>
                    <div className="flex gap-2">
                        <GlassButton type="button" size="sm" variant="ghost" disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</GlassButton>
                        <GlassButton type="button" size="sm" variant="ghost" disabled={page >= maxPage || loading} onClick={() => setPage((value) => Math.min(maxPage, value + 1))}>Next</GlassButton>
                    </div>
                </div>
            </div>

            {selected && draft && (
                <AdminModal
                    title="Safety violation review"
                    description={`Violation ${selected.id} · User ${selected.user_id || 'unknown'}`}
                    size="lg"
                    onClose={() => {
                        if (!saving) {
                            setSelected(null);
                            setDraft(null);
                        }
                    }}
                    footer={
                        <>
                            <GlassButton type="button" variant="ghost" size="sm" onClick={() => { setSelected(null); setDraft(null); }} disabled={saving}>Close</GlassButton>
                            <GlassButton type="button" variant="subtle" size="sm" onClick={() => void updateArchive(selected)} disabled={saving || isBusy(selected.id)}>
                                {selected.isArchived ? <RotateCcw size={14} /> : <Archive size={14} />}
                                {selected.isArchived ? 'Restore' : 'Archive'}
                            </GlassButton>
                            <GlassButton type="button" variant="primary" size="sm" onClick={() => void saveReview()} disabled={saving || (selected.action_request_status || '').toLowerCase() === 'pending'}>
                                <Check size={14} /> {saving ? 'Saving…' : 'Save review'}
                            </GlassButton>
                        </>
                    }
                >
                    <div className="space-y-4">
                        {detailError && <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{detailError}</p>}
                        {(selected.action_request_status || '').toLowerCase() === 'pending' && (
                            <p role="status" className="rounded-lg bg-info-soft p-3 text-xs text-info">A remediation approval is pending. This record cannot be changed or deleted until the request is decided.</p>
                        )}
                        <div className="flex flex-wrap gap-2"><StatusBadge value={selected.status} /><ActionBadge log={selected} /></div>
                        {warningAcknowledgmentText(selected) && (
                            <p className="rounded-lg bg-surface-2 p-3 text-xs text-text-2" data-testid="v2-safety-warning-acknowledgment">
                                {warningAcknowledgmentText(selected)}
                            </p>
                        )}
                        <div><h3 className="text-xs font-semibold text-text-3">Flagged message</h3><p className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-3 text-sm text-text-1">{selected.message || 'No message captured.'}</p></div>
                        <div><h3 className="text-xs font-semibold text-text-3">Triggered categories</h3><p className="mt-1 text-sm text-text-2">{categoryText(selected) || 'No triggered categories.'}</p></div>
                        {selected.user_notes ? <div><h3 className="text-xs font-semibold text-text-3">User notes</h3><p className="mt-1 whitespace-pre-wrap text-sm text-text-2">{selected.user_notes}</p></div> : null}
                        <label className="block text-xs font-medium text-text-2">
                            Status
                            <select value={draft.status} onChange={(event) => setDraft((current) => current ? { ...current, status: event.target.value } : current)} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1">
                                {STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
                            </select>
                        </label>
                        <label className="block text-xs font-medium text-text-2">
                            Action
                            <select value={draft.action} onChange={(event) => {
                                const action = event.target.value;
                                setDraft((current) => current ? {
                                    ...current,
                                    action,
                                    notificationMessage: REMEDIATION_ACTIONS.has(action) ? defaultNotification(selected, action) : '',
                                    datetimeToAllow: action === 'SuspendUser' && selected.action === action
                                        ? toLocalDateTime(selected.action_datetime_to_allow)
                                        : '',
                                } : current);
                            }} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1">
                                {(selected.action === LEGACY_ESCALATE_ACTION ? [...ACTIONS, LEGACY_ESCALATE_ACTION] : ACTIONS).map((value) => (
                                    <option key={value} value={value} disabled={selected.content_origin === 'assistant' && REMEDIATION_ACTIONS.has(value)}>
                                        {actionLabel(value)}
                                    </option>
                                ))}
                            </select>
                        </label>
                        {REMEDIATION_ACTIONS.has(draft.action) && (
                            <div className="space-y-3 rounded-xl border border-info/30 bg-info-soft p-3">
                                <p className="text-xs text-info">
                                    {draft.action === 'WarnUser'
                                        ? isExecutedWarning(selected)
                                            ? 'This warning was already sent. Saving updates the review without sending the warning again.'
                                            : 'The warning is sent to the user as soon as you save, without a second reviewer. The user must acknowledge it the next time they use SimpleChat.'
                                        : draft.action === 'SuspendUser'
                                            ? 'A suspension restricts access, so saving creates an approval request. It applies only after another eligible reviewer approves it.'
                                            : 'A block restricts access, so saving creates an approval request. It applies only after another eligible reviewer approves it.'}
                                </p>
                                {selected.content_origin === 'assistant' && <p className="text-xs text-warn">AI-generated findings cannot be used to warn or restrict a user.</p>}
                                {!(draft.action === 'WarnUser' && isExecutedWarning(selected)) && (
                                <label className="block text-xs font-medium text-text-2">
                                    Notification message
                                    <textarea rows={4} value={draft.notificationMessage} onChange={(event) => setDraft((current) => current ? { ...current, notificationMessage: event.target.value } : current)} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1" />
                                </label>
                                )}
                                {draft.action === 'SuspendUser' && (
                                    <label className="block text-xs font-medium text-text-2">
                                        Restore access on
                                        <input type="datetime-local" value={draft.datetimeToAllow} onChange={(event) => setDraft((current) => current ? { ...current, datetimeToAllow: event.target.value } : current)} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1" />
                                    </label>
                                )}
                            </div>
                        )}
                        <label className="block text-xs font-medium text-text-2">
                            Administrator notes
                            <textarea rows={3} value={draft.notes} onChange={(event) => setDraft((current) => current ? { ...current, notes: event.target.value } : current)} className="mt-1 w-full rounded-lg border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1" />
                        </label>
                    </div>
                </AdminModal>
            )}

            {pendingDelete && (
                <ConfirmDialog
                    title="Permanently delete safety violation?"
                    description="This cannot be undone. Approval and activity audit records are preserved. A violation with pending remediation approval cannot be deleted."
                    confirmLabel="Permanently delete"
                    busy={busyId === pendingDelete.id}
                    onClose={() => {
                        if (busyId !== pendingDelete.id) {
                            setPendingDelete(null);
                            setDeleteError(null);
                        }
                    }}
                    onConfirm={() => void deleteViolation()}
                >
                    <div className="space-y-2 text-xs text-text-2">
                        <p>The audit history is preserved. The server refuses deletion while remediation approval is pending.</p>
                        {deleteError && <p role="alert" className="text-danger">{deleteError}</p>}
                    </div>
                </ConfirmDialog>
            )}

            {pendingRecheck && (
                <ConfirmDialog
                    title="Recheck this message?"
                    description="The current rules will be applied. An AI reply with confirmed findings will be removed from saved and shared chat. A checker outage leaves the message available and marked for another attempt."
                    confirmLabel="Recheck and apply rules"
                    confirmIcon={<RefreshCw size={14} />}
                    tone="primary"
                    busy={rechecking}
                    onClose={() => {
                        if (!rechecking) {
                            setPendingRecheck(null);
                            setRecheckError(null);
                        }
                    }}
                    onConfirm={() => void recheckUnchecked()}
                >
                    <div className="space-y-2 text-xs text-text-2">
                        <p>Message ID: <span className="break-all">{pendingRecheck.message_id}</span></p>
                        {recheckError && <p role="alert" className="text-danger">{recheckError}</p>}
                    </div>
                </ConfirmDialog>
            )}
        </div>
    );
}
