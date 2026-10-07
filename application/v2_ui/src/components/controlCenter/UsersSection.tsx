// UsersSection.tsx
// Server-driven user administration for the V2 Control Center.

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, Search, Shield, Users } from 'lucide-react';
import { api } from '../../lib/apiClient';
import {
    ApprovalSubmittedNotice,
    DataTable,
    DetailDrawer,
    ExportButton,
    FilterBar,
    KpiCard,
    ReasonConfirmDialog,
    StatusBadge,
    useCrossPageSelection,
    useUrlQueryParams,
    type DataColumn,
} from './ControlCenterPrimitives';
import { EmptyState, GlassButton, GlassPanel } from '../ui/primitives';
import { toast } from '../../stores/toastStore';

interface Restriction {
    status: 'allow' | 'deny';
    expires_at: string | null;
}

interface UserRow {
    id: string;
    email: string;
    display_name: string;
    access: Restriction;
    file_uploads: Restriction;
    last_login: string | null;
    total_logins: number | null;
    conversations: number | null;
    documents: number | null;
    tokens: number | null;
    metrics_calculated_at: string | null;
}

interface UserProfile {
    id: string;
    email: string;
    display_name: string;
    access: Restriction;
    file_uploads: Restriction;
}

interface UsersResponse {
    users: UserRow[];
    pagination: {
        page: number;
        per_page: number;
        total_items: number;
        total_pages: number;
    };
    metrics_freshness: {
        oldest_calculated_at: string | null;
        newest_calculated_at: string | null;
        missing_count: number;
        source: string;
    };
}

interface ActivityItem {
    id: string;
    activity_type: string;
    timestamp: string | null;
    resource_name?: string | null;
    workspace_type?: string | null;
    token_type?: string | null;
    status?: string | null;
    usage?: { total_tokens?: number } | null;
}

interface Membership {
    id: string;
    name: string;
    role: string;
    owned: boolean;
}

interface UserDetail {
    user: UserProfile;
    usage: {
        last_login: string | null;
        total_logins: number | null;
        conversations: number | null;
        documents: number | null;
        tokens: number | null;
        metrics_calculated_at: string | null;
    };
    activity: ActivityItem[];
    memberships: {
        groups: Membership[];
        public_workspaces: Membership[];
    };
}

type DetailTab = 'overview' | 'activity' | 'memberships';

const PAGE_SIZE = '25';

function userFilterQuery(params: URLSearchParams, includePaging = true) {
    const query = new URLSearchParams(params);
    query.delete('user_id');
    if (!includePaging) {
        query.delete('page');
        query.delete('per_page');
        query.delete('sort');
        query.delete('direction');
    }
    return query.toString();
}

function displayDate(value: string | null | undefined) {
    if (!value || value === 'Never') return 'Never';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function displayMetric(value: number | null | undefined) {
    return value === null || value === undefined ? 'Not refreshed' : Number(value).toLocaleString();
}

export function UsersSection() {
    const { params, setParam } = useUrlQueryParams();
    const selection = useCrossPageSelection();
    const [search, setSearch] = useState(() => new URLSearchParams(window.location.search).get('search') ?? '');
    const [rows, setRows] = useState<UserRow[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [freshness, setFreshness] = useState<UsersResponse['metrics_freshness'] | null>(null);
    const [reload, setReload] = useState(0);
    const [selectedTab, setSelectedTab] = useState<DetailTab>('overview');
    const [detail, setDetail] = useState<UserDetail | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [expiryInput, setExpiryInput] = useState('');
    const [bulkAccess, setBulkAccess] = useState<'allow' | 'deny'>('deny');
    const [bulkUploads, setBulkUploads] = useState<'allow' | 'deny'>('deny');
    const [busyAction, setBusyAction] = useState<string | null>(null);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [approvalId, setApprovalId] = useState<string | null>(null);

    const selectedUserId = params.get('user_id');
    const currentPage = Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1);
    const accessStatus = params.get('access_status')
        ?? (params.get('status') === 'blocked' ? 'deny' : 'all');
    const uploadStatus = params.get('upload_status') ?? 'all';
    const lastLogin = params.get('last_login')
        ?? (params.get('filter') === 'active' ? '30' : 'all');
    const hasDocuments = params.get('has_documents') ?? 'all';
    const sort = params.get('sort') ?? 'name';
    const direction = params.get('direction') === 'desc' ? 'desc' : 'asc';
    const requestQuery = useMemo(() => {
        const query = new URLSearchParams(params);
        query.set('page', String(currentPage));
        query.set('per_page', PAGE_SIZE);
        return query.toString();
    }, [currentPage, params]);
    const selectionFilterKey = [
        params.get('search'), params.get('filter'), params.get('status'),
        params.get('access_status'), params.get('upload_status'),
        params.get('last_login'), params.get('has_documents'),
    ].join('|');

    useEffect(() => {
        setSearch(params.get('search') ?? '');
    }, [params]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            if (search !== (params.get('search') ?? '')) {
                setParam('page', null);
                setParam('search', search.trim() || null);
            }
        }, 250);
        return () => window.clearTimeout(timer);
    }, [params, search, setParam]);

    useEffect(() => {
        selection.clear();
    // A changed filter creates a different all-matching population; page and sort changes do not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectionFilterKey]);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        api.get<UsersResponse>(`/api/v2/control-center/users?${requestQuery}`, controller.signal)
            .then((response) => {
                setRows(response.users);
                setTotal(response.pagination.total_items);
                setPage(response.pagination.page);
                setFreshness(response.metrics_freshness);
            })
            .catch((requestError: unknown) => {
                if (controller.signal.aborted) return;
                setError(requestError instanceof Error ? requestError.message : 'Unable to load users.');
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [requestQuery, reload]);

    useEffect(() => {
        if (!selectedUserId) {
            setDetail(null);
            setDetailError(null);
            setApprovalId(null);
            return;
        }
        const controller = new AbortController();
        setDetailLoading(true);
        setDetailError(null);
        api.get<UserDetail>(
            `/api/v2/control-center/users/${encodeURIComponent(selectedUserId)}`,
            controller.signal,
        )
            .then((response) => {
                setDetail(response);
                setApprovalId(null);
            })
            .catch((requestError: unknown) => {
                if (controller.signal.aborted) return;
                setDetailError(requestError instanceof Error ? requestError.message : 'Unable to load user details.');
            })
            .finally(() => {
                if (!controller.signal.aborted) setDetailLoading(false);
            });
        return () => controller.abort();
    }, [selectedUserId]);

    const updateParam = useCallback((key: string, value: string) => {
        setParam('page', null);
        if (['access_status', 'last_login', 'upload_status', 'has_documents'].includes(key)) {
            setParam('filter', null);
            setParam('status', null);
        }
        setParam(key, value === 'all' ? null : value);
    }, [setParam]);

    const openUser = useCallback((id: string) => {
        setSelectedTab('overview');
        setExpiryInput('');
        setApprovalId(null);
        setParam('user_id', id);
    }, [setParam]);

    const closeDrawer = useCallback(() => {
        setParam('user_id', null);
        setApprovalId(null);
    }, [setParam]);

    const columns = useMemo<DataColumn<UserRow>[]>(() => [
        {
            id: 'name',
            label: 'User',
            sortable: true,
            render: (row) => (
                <div className="min-w-44">
                    <button type="button" onClick={() => openUser(row.id)}
                        aria-label={`Open details for ${row.display_name || row.email || row.id}`}
                        className="text-left font-medium text-text-1 underline-offset-2 hover:text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                        {row.display_name || 'Unnamed user'}
                    </button>
                    <p className="mt-0.5 break-all text-xs text-text-3">{row.email || 'No email recorded'}</p>
                </div>
            ),
        },
        {
            id: 'access',
            label: 'Access',
            render: (row) => <StatusBadge status={row.access.status === 'deny' ? 'Denied' : 'Allowed'} />,
        },
        {
            id: 'file_uploads',
            label: 'Uploads',
            render: (row) => <StatusBadge status={row.file_uploads.status === 'deny' ? 'Denied' : 'Allowed'} />,
        },
        { id: 'last_login', label: 'Last login', sortable: true, render: (row) => displayDate(row.last_login) },
        { id: 'conversations', label: 'Conversations', sortable: true, render: (row) => displayMetric(row.conversations) },
        { id: 'documents', label: 'Documents', sortable: true, render: (row) => displayMetric(row.documents) },
        { id: 'tokens', label: 'Tokens', sortable: true, render: (row) => displayMetric(row.tokens) },
    ], [openUser]);

    const setCurrentFilter = (key: string, value: string) => updateParam(key, value);

    const applyBulkAction = async (actionType: 'access' | 'file_uploads', status: 'allow' | 'deny') => {
        if (!selection.allMatchingSelected && selection.selectedIds.size === 0) return;
        const datetimeToAllow = status === 'deny' && expiryInput
            ? new Date(expiryInput).toISOString()
            : null;
        const payload: Record<string, unknown> = {
            action_type: actionType,
            settings: { status, datetime_to_allow: datetimeToAllow },
        };
        if (selection.allMatchingSelected) {
            const filter = new URLSearchParams(params);
            filter.delete('user_id');
            filter.delete('page');
            filter.delete('per_page');
            filter.delete('sort');
            filter.delete('direction');
            payload.filter = Object.fromEntries(filter.entries());
            payload.exclude_ids = Array.from(selection.excludedIds);
        } else {
            payload.user_ids = Array.from(selection.selectedIds);
        }

        const previousRows = rows;
        setRows((current) => current.map((row) => selection.isSelected(row.id)
            ? { ...row, [actionType]: { status, expires_at: datetimeToAllow } }
            : row));
        setBusyAction(`bulk-${actionType}`);
        try {
            const result = await api.post<{ success_count: number; failed_count: number }>(
                '/api/v2/control-center/users/bulk-action',
                payload,
            );
            selection.clear();
            setReload((value) => value + 1);
            if (result.failed_count) {
                toast.error(`${result.success_count} updated; ${result.failed_count} users could not be updated.`);
            } else {
                toast.success(`${result.success_count.toLocaleString()} users updated.`);
            }
        } catch (requestError) {
            setRows(previousRows);
            toast.error(requestError instanceof Error ? requestError.message : 'Bulk update failed.');
        } finally {
            setBusyAction(null);
        }
    };

    const updateRestriction = async (actionType: 'access' | 'file_uploads', status: 'allow' | 'deny') => {
        if (!selectedUserId || !detail) return;
        const expiry = status === 'deny' && expiryInput
            ? new Date(expiryInput).toISOString()
            : null;
        const priorDetail = detail;
        const priorRows = rows;
        setDetail((current) => current ? {
            ...current,
            user: { ...current.user, [actionType]: { status, expires_at: expiry } },
        } : current);
        setRows((current) => current.map((row) => row.id === selectedUserId
            ? { ...row, [actionType]: { status, expires_at: expiry } }
            : row));
        setBusyAction(actionType);
        try {
            await api.patch(
                `/api/admin/control-center/users/${encodeURIComponent(selectedUserId)}/${actionType === 'access' ? 'access' : 'file-uploads'}`,
                { status, datetime_to_allow: expiry },
            );
            const reconciled = await api.get<UserDetail>(
                `/api/v2/control-center/users/${encodeURIComponent(selectedUserId)}`,
            );
            setDetail(reconciled);
            setReload((value) => value + 1);
            toast.success(`${actionType === 'access' ? 'Access' : 'File uploads'} ${status === 'deny' ? 'denied' : 'allowed'}.`);
        } catch (requestError) {
            setDetail(priorDetail);
            setRows(priorRows);
            toast.error(requestError instanceof Error ? requestError.message : 'User setting could not be saved.');
        } finally {
            setBusyAction(null);
        }
    };

    const requestDocumentDeletion = async (reason: string) => {
        if (!selectedUserId) return;
        setConfirmDelete(false);
        setBusyAction('delete-documents');
        try {
            const result = await api.post<{ approval_id: string }>(
                `/api/admin/control-center/users/${encodeURIComponent(selectedUserId)}/delete-documents`,
                { reason },
            );
            setApprovalId(result.approval_id);
            toast.success('Document deletion submitted for approval.');
        } catch (requestError) {
            toast.error(requestError instanceof Error ? requestError.message : 'Approval request could not be created.');
        } finally {
            setBusyAction(null);
        }
    };

    const exportQuery = userFilterQuery(params, false);
    const selectedCount = selection.allMatchingSelected
        ? Math.max(0, total - selection.excludedIds.size)
        : selection.selectedIds.size;

    return (
        <section className="space-y-4 p-4 md:p-6" aria-labelledby="control-center-users-heading">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 id="control-center-users-heading" className="text-xl font-semibold text-text-1">Users</h2>
                    <p className="mt-1 max-w-3xl text-sm text-text-3">
                        Review account access, upload permissions, and cached usage. Changes are recorded against the selected account.
                    </p>
                </div>
                <ExportButton filename="control-center-users.csv" serverQuery={exportQuery} />
            </div>

            <FilterBar search={search} onSearch={setSearch}>
                <label className="flex items-center gap-2 text-xs text-text-3">
                    Access
                    <select aria-label="Filter by access status" value={accessStatus}
                        onChange={(event) => setCurrentFilter('access_status', event.target.value)}
                        className="rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1">
                        <option value="all">Any</option><option value="allow">Allowed</option><option value="deny">Denied</option>
                    </select>
                </label>
                <label className="flex items-center gap-2 text-xs text-text-3">
                    Uploads
                    <select aria-label="Filter by file-upload status" value={uploadStatus}
                        onChange={(event) => setCurrentFilter('upload_status', event.target.value)}
                        className="rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1">
                        <option value="all">Any</option><option value="allow">Allowed</option><option value="deny">Denied</option>
                    </select>
                </label>
                <label className="flex items-center gap-2 text-xs text-text-3">
                    Last login
                    <select aria-label="Filter by last-login window" value={lastLogin}
                        onChange={(event) => setCurrentFilter('last_login', event.target.value)}
                        className="rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1">
                        <option value="all">Any time</option><option value="never">Never</option>
                        <option value="7">Within 7 days</option><option value="30">Within 30 days</option>
                        <option value="90">Within 90 days</option><option value="90_plus">90+ days ago</option>
                    </select>
                </label>
                <label className="flex items-center gap-2 text-xs text-text-3">
                    Documents
                    <select aria-label="Filter by document ownership" value={hasDocuments}
                        onChange={(event) => setCurrentFilter('has_documents', event.target.value)}
                        className="rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1">
                        <option value="all">Any</option><option value="yes">Has documents</option><option value="no">No documents</option>
                    </select>
                </label>
            </FilterBar>

            {selectedCount > 0 ? (
                <GlassPanel className="flex flex-wrap items-end gap-3 p-3" role="region" aria-label="Bulk user actions">
                    <p className="mr-auto self-center text-sm font-medium text-text-1">
                        {selection.allMatchingSelected ? `All ${selectedCount.toLocaleString()} matching users selected` : `${selectedCount.toLocaleString()} selected`}
                    </p>
                    <label className="grid gap-1 text-xs text-text-3">
                        Deny until (optional)
                        <input aria-label="Bulk restriction expiry" type="datetime-local" value={expiryInput}
                            onChange={(event) => setExpiryInput(event.target.value)}
                            className="rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-sm text-text-1" />
                    </label>
                    <label className="grid gap-1 text-xs text-text-3">
                        Access
                        <select aria-label="Bulk access status" value={bulkAccess}
                            onChange={(event) => setBulkAccess(event.target.value as 'allow' | 'deny')}
                            className="rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-sm text-text-1">
                            <option value="allow">Allow</option><option value="deny">Deny</option>
                        </select>
                    </label>
                    <GlassButton size="sm" disabled={Boolean(busyAction)}
                        onClick={() => void applyBulkAction('access', bulkAccess)}>
                        Apply access
                    </GlassButton>
                    <label className="grid gap-1 text-xs text-text-3">
                        File uploads
                        <select aria-label="Bulk file-upload status" value={bulkUploads}
                            onChange={(event) => setBulkUploads(event.target.value as 'allow' | 'deny')}
                            className="rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-sm text-text-1">
                            <option value="allow">Allow</option><option value="deny">Deny</option>
                        </select>
                    </label>
                    <GlassButton size="sm" disabled={Boolean(busyAction)}
                        onClick={() => void applyBulkAction('file_uploads', bulkUploads)}>
                        Apply uploads
                    </GlassButton>
                    <GlassButton size="sm" onClick={selection.clear}>Clear selection</GlassButton>
                </GlassPanel>
            ) : null}

            <DataTable rows={rows} columns={columns} total={total} page={page} pageSize={25}
                sort={sort} sortDirection={direction} loading={loading} error={error}
                selectable selectedIds={selection.selectedIds} isRowSelected={selection.isSelected}
                allMatchingSelected={selection.allMatchingSelected}
                onSelect={selection.setSelected} onSelectPage={selection.setPageSelected}
                onSelectAllMatchingPages={selection.selectAllAcrossPages}
                onSort={(field, nextDirection) => {
                    setParam('sort', field);
                    setParam('direction', nextDirection);
                }}
                onPageChange={(nextPage) => setParam('page', String(nextPage))}
                emptyMessage="No users match these filters." />

            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-3" aria-live="polite">
                <span>
                    Usage metrics come from the scheduled Control Center refresh.
                    {freshness?.oldest_calculated_at
                        ? ` Oldest value on this page: ${displayDate(freshness.oldest_calculated_at)}.`
                        : ' No usage metrics have been refreshed for this page yet.'}
                </span>
                {freshness?.missing_count ? <span>{freshness.missing_count} rows on this page have no cached metrics.</span> : null}
            </div>

            {selectedUserId ? (
                <DetailDrawer title={detail?.user.display_name || detail?.user.email || 'User details'} onClose={closeDrawer}>
                    {detailLoading && !detail ? <p role="status" className="py-6 text-sm text-text-3">Loading user details…</p> : null}
                    {detailError ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{detailError}</p> : null}
                    {detail ? (
                        <div className="space-y-5">
                            <div>
                                <p className="text-sm text-text-2">{detail.user.email || 'No email recorded'}</p>
                                <p className="mt-1 break-all text-xs text-text-3">Account ID: {detail.user.id}</p>
                            </div>
                            <div role="tablist" aria-label="User detail sections" className="flex gap-1 border-b border-edge">
                                {(['overview', 'activity', 'memberships'] as const).map((tab) => (
                                    <button key={tab} type="button" role="tab" aria-selected={selectedTab === tab}
                                        aria-controls="user-detail-panel"
                                        onClick={() => setSelectedTab(tab)}
                                        className={`px-3 py-2 text-sm capitalize focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${selectedTab === tab ? 'border-b-2 border-accent font-semibold text-accent' : 'text-text-3 hover:text-text-1'}`}>
                                        {tab}
                                    </button>
                                ))}
                            </div>
                            <div id="user-detail-panel" role="tabpanel" className="space-y-4">
                                {selectedTab === 'overview' ? (
                                    <>
                                        <div className="grid grid-cols-2 gap-3">
                                            <KpiCard label="Last login" value={<span className="text-base">{displayDate(detail.usage.last_login)}</span>} />
                                            <KpiCard label="Conversations" value={displayMetric(detail.usage.conversations)} />
                                            <KpiCard label="Documents" value={displayMetric(detail.usage.documents)} />
                                            <KpiCard label="Tokens" value={displayMetric(detail.usage.tokens)} />
                                        </div>
                                        <p className="text-xs text-text-3">
                                            Metrics refreshed: {displayDate(detail.usage.metrics_calculated_at)}
                                        </p>
                                        <GlassPanel className="space-y-3 p-4">
                                            <h3 className="font-medium text-text-1">Account controls</h3>
                                            <div className="grid gap-3 sm:grid-cols-2">
                                                <div className="space-y-2">
                                                    <p className="text-sm text-text-2">Access <StatusBadge status={detail.user.access.status === 'deny' ? 'Denied' : 'Allowed'} /></p>
                                                    <p className="text-xs text-text-3">{detail.user.access.expires_at ? `Expires ${displayDate(detail.user.access.expires_at)}` : 'No expiry scheduled'}</p>
                                                    <div className="flex gap-2">
                                                        <GlassButton size="sm" disabled={Boolean(busyAction)} onClick={() => void updateRestriction('access', 'allow')}>Allow</GlassButton>
                                                        <GlassButton size="sm" variant="danger" disabled={Boolean(busyAction)} onClick={() => void updateRestriction('access', 'deny')}>Deny</GlassButton>
                                                    </div>
                                                </div>
                                                <div className="space-y-2">
                                                    <p className="text-sm text-text-2">File uploads <StatusBadge status={detail.user.file_uploads.status === 'deny' ? 'Denied' : 'Allowed'} /></p>
                                                    <p className="text-xs text-text-3">{detail.user.file_uploads.expires_at ? `Expires ${displayDate(detail.user.file_uploads.expires_at)}` : 'No expiry scheduled'}</p>
                                                    <div className="flex gap-2">
                                                        <GlassButton size="sm" disabled={Boolean(busyAction)} onClick={() => void updateRestriction('file_uploads', 'allow')}>Allow</GlassButton>
                                                        <GlassButton size="sm" variant="danger" disabled={Boolean(busyAction)} onClick={() => void updateRestriction('file_uploads', 'deny')}>Deny</GlassButton>
                                                    </div>
                                                </div>
                                            </div>
                                            <label className="block text-xs text-text-3">
                                                Deny until (optional)
                                                <input type="datetime-local" value={expiryInput}
                                                    onChange={(event) => setExpiryInput(event.target.value)}
                                                    className="mt-1 block w-full rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-sm text-text-1" />
                                            </label>
                                        </GlassPanel>
                                        {approvalId ? (
                                            <ApprovalSubmittedNotice>
                                                Document deletion approval {approvalId} was submitted for another administrator to review.
                                            </ApprovalSubmittedNotice>
                                        ) : null}
                                        <GlassButton variant="danger" disabled={Boolean(busyAction)}
                                            onClick={() => setConfirmDelete(true)}>
                                            Request deletion of all documents
                                        </GlassButton>
                                        <Link className="flex w-fit items-center gap-2 text-sm text-accent hover:underline"
                                            to={`/control-center/activity-logs?user_id=${encodeURIComponent(detail.user.id)}`}>
                                            <ExternalLink size={14} aria-hidden="true" />View in Activity Logs
                                        </Link>
                                    </>
                                ) : selectedTab === 'activity' ? (
                                    <div className="space-y-3">
                                        <div className="flex items-center justify-between gap-2">
                                            <h3 className="font-medium text-text-1">Recent activity</h3>
                                            <Link className="text-xs text-accent hover:underline"
                                                to={`/control-center/activity-logs?user_id=${encodeURIComponent(detail.user.id)}`}>
                                                View all in Activity Logs
                                            </Link>
                                        </div>
                                        {detail.activity.length ? detail.activity.map((item) => (
                                            <GlassPanel key={item.id} elevation="flat" className="flex flex-wrap items-center justify-between gap-2 p-3">
                                                <div>
                                                    <p className="text-sm font-medium text-text-1">{item.activity_type.replaceAll('_', ' ')}</p>
                                                    <p className="mt-1 text-xs text-text-3">
                                                        {displayDate(item.timestamp)}{item.resource_name ? ` · ${item.resource_name}` : ''}
                                                    </p>
                                                </div>
                                                <div className="text-right text-xs text-text-3">
                                                    {item.workspace_type ? <p>{item.workspace_type}</p> : null}
                                                    {item.usage?.total_tokens ? <p>{item.usage.total_tokens.toLocaleString()} tokens</p> : null}
                                                </div>
                                            </GlassPanel>
                                        )) : <EmptyState icon={<Search size={20} />} title="No recent activity" description="No activity records are available for this account." />}
                                    </div>
                                ) : (
                                    <div className="space-y-5">
                                        <MembershipList title="Groups" items={detail.memberships.groups} icon={<Users size={16} />} />
                                        <MembershipList title="Public workspaces" items={detail.memberships.public_workspaces} icon={<Shield size={16} />} />
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : null}
                </DetailDrawer>
            ) : null}
            {confirmDelete ? (
                <ReasonConfirmDialog title="Request deletion of all user documents?"
                    description="This creates an approval request. A different administrator must approve it before documents are deleted."
                    reasonRequired confirmLabel="Submit approval request"
                    onClose={() => setConfirmDelete(false)}
                    onConfirm={(reason) => void requestDocumentDeletion(reason)} />
            ) : null}
        </section>
    );
}

function MembershipList({ title, items, icon }: { title: string; items: Membership[]; icon: ReactNode }) {
    return (
        <section aria-label={title}>
            <h3 className="mb-2 flex items-center gap-2 font-medium text-text-1">{icon}{title}</h3>
            {items.length ? (
                <ul className="divide-y divide-edge rounded-xl border border-edge">
                    {items.map((item) => (
                        <li key={item.id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                            <span className="min-w-0 truncate text-text-1">{item.name || item.id}</span>
                            <span className="shrink-0 text-xs text-text-3">{item.owned ? 'Owner' : item.role}</span>
                        </li>
                    ))}
                </ul>
            ) : <p className="text-sm text-text-3">No {title.toLowerCase()} memberships.</p>}
        </section>
    );
}
