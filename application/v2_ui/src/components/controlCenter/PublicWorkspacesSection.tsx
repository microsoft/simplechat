// PublicWorkspacesSection.tsx
// Operate: query-backed inventory with explicit recorded-metric freshness and governed details.

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/apiClient';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { DataTable, ExportButton, FilterBar, ReasonConfirmDialog, StatusBadge, useCrossPageSelection, useUrlQueryParams, type DataColumn } from './ControlCenterPrimitives';
import { GROUP_INPUT, GroupDetailDrawer, type GroupRow } from './GroupDetailDrawer';
import { entityDate } from './EntityDetailSections';

interface WorkspaceResponse {
    workspaces: GroupRow[];
    pagination: { total_items: number; page: number };
}

const FILTER_KEYS = ['search', 'status', 'owner'];
const STATUSES = ['active', 'locked', 'upload_disabled', 'inactive'];

export function PublicWorkspacesSection() {
    const { params, setParam } = useUrlQueryParams();
    const selection = useCrossPageSelection();
    const [response, setResponse] = useState<WorkspaceResponse | null>(null);
    const [error, setError] = useState('');
    const [actionError, setActionError] = useState('');
    const [loading, setLoading] = useState(true);
    const [revision, setRevision] = useState(0);
    const [busy, setBusy] = useState(false);
    const [bulkStatus, setBulkStatus] = useState('locked');
    const [confirm, setConfirm] = useState(false);
    const query = useMemo(() => {
        const value = new URLSearchParams();
        for (const key of [...FILTER_KEYS, 'sort', 'direction', 'page']) {
            if (params.has(key)) value.set(key, params.get(key)!);
        }
        value.set('per_page', '25');
        return value.toString();
    }, [params]);
    const filterKey = FILTER_KEYS.map((key) => params.get(key)).join('|');
    useEffect(() => {
        selection.clear();
        // Selection survives page/sort changes, not filter changes.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterKey]);
    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        api.get<WorkspaceResponse>(`/api/v2/control-center/public-workspaces?${query}`, controller.signal)
            .then((data) => { if (!controller.signal.aborted) setResponse(data); })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Unable to load public workspaces.');
            })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [query, revision]);
    const updateFilter = (key: string, value: string) => {
        setParam('page', null);
        setParam(key, !value || value === 'all' ? null : value);
    };
    const total = response?.pagination.total_items ?? 0;
    const count = selection.allMatchingSelected ? Math.max(0, total - selection.excludedIds.size) : selection.selectedIds.size;
    const columns: DataColumn<GroupRow>[] = [
        { id: 'name', label: 'Public workspace', sortable: true, render: (row) =>
            <button type="button" className="text-left font-medium text-text-1 hover:text-accent hover:underline focus-visible:outline-2 focus-visible:outline-accent"
                aria-label={`Open details for ${row.name || row.id}`} onClick={() => setParam('id', row.id)}>{row.name || 'Unnamed workspace'}</button> },
        { id: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> },
        { id: 'owner', label: 'Owner', sortable: true, render: (row) => row.owner.id
            ? <Link className="text-accent underline" to={`/control-center/users?user_id=${encodeURIComponent(row.owner.id)}`}>{row.owner.display_name || row.owner.email || row.owner.id}</Link>
            : 'No owner recorded' },
        { id: 'members', label: 'Managers', render: (row) => row.members.toLocaleString() },
        { id: 'documents', label: 'Recorded documents', sortable: true, render: (row) => row.documents?.toLocaleString() ?? 'Not recorded' },
        { id: 'tokens', label: 'Recorded tokens', sortable: true, render: (row) => row.tokens?.toLocaleString() ?? 'Not recorded' },
        { id: 'last_activity', label: 'Recorded last activity', sortable: true, render: (row) => entityDate(row.last_activity) },
        { id: 'created_at', label: 'Created', sortable: true, render: (row) => entityDate(row.created_at) },
        { id: 'metrics_calculated_at', label: 'Metrics refreshed', render: (row) => entityDate(row.metrics_calculated_at) },
    ];
    const applyBulk = async (reason: string) => {
        if (busy) return;
        setConfirm(false);
        setBusy(true);
        setActionError('');
        const payload = selection.allMatchingSelected
            ? { filter: Object.fromEntries(FILTER_KEYS.flatMap((key) => params.has(key) ? [[key, params.get(key)]] : [])), exclude_ids: Array.from(selection.excludedIds) }
            : { workspace_ids: Array.from(selection.selectedIds) };
        try {
            const result = await api.post<{ success_count: number; failed_count: number; failed_workspaces: { id: string; error: string }[] }>(
                '/api/v2/control-center/public-workspaces/bulk-status', { ...payload, status: bulkStatus, reason },
            );
            selection.clear();
            setRevision((value) => value + 1);
            if (result.failed_count) {
                setActionError(`${result.success_count} succeeded; ${result.failed_count} failed. ${result.failed_workspaces.map((item) => `${item.id}: ${item.error}`).join('; ')}`);
                toast.error('Some workspaces could not be updated. Review the failure details.');
            } else toast.success(`${result.success_count} public workspaces updated.`);
        } catch (cause) {
            setActionError(cause instanceof Error ? cause.message : 'Unable to update public workspaces.');
        } finally { setBusy(false); }
    };
    const exportQuery = new URLSearchParams(query);
    exportQuery.delete('page');
    exportQuery.delete('per_page');
    return <section className="space-y-4 p-4 md:p-6" aria-labelledby="public-workspaces-heading">
        <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
                <h2 id="public-workspaces-heading" className="text-xl font-semibold text-text-1">Public Workspaces</h2>
                <p className="mt-1 max-w-3xl text-sm text-text-3">Review public knowledge spaces, their managers and recorded usage.</p>
            </div>
            <div className="flex gap-2">
                <GlassButton disabled={loading || busy} onClick={() => setRevision((value) => value + 1)}>Refresh workspaces</GlassButton>
                <ExportButton entity="public-workspaces" filename="control-center-public-workspaces.csv" serverQuery={exportQuery.toString()} />
            </div>
        </div>
        <FilterBar search={params.get('search') ?? ''} onSearch={(value) => updateFilter('search', value)}>
            <label className="grid gap-1 text-xs text-text-3">Status
                <select className={GROUP_INPUT} aria-label="Filter by workspace status" value={params.get('status') ?? 'all'} onChange={(event) => updateFilter('status', event.target.value)}>
                    <option value="all">Any status</option>
                    {STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
                </select>
            </label>
            <label className="grid gap-1 text-xs text-text-3">Owner
                <input className={GROUP_INPUT} maxLength={200} value={params.get('owner') ?? ''} onChange={(event) => updateFilter('owner', event.target.value)} placeholder="Name, email or ID" />
            </label>
        </FilterBar>
        <p className="text-xs text-text-3">List metrics are stored snapshots, not live counts. Unrecorded values are unavailable, not zero. Refresh reloads stored data; open details for live document and token totals. Managers include the owner, not implicit public readers. Export limit: 10,000 workspaces.</p>
        {count ? <div role="region" aria-label="Bulk workspace actions" className="flex flex-wrap items-center gap-3 rounded-xl border border-edge bg-surface-2 p-3">
            <span className="mr-auto text-sm text-text-1">{count} selected (limit 500)</span>
            <label className="text-xs text-text-3">Bulk status
                <select aria-label="Bulk workspace status" className={`ml-2 ${GROUP_INPUT}`} value={bulkStatus} disabled={busy} onChange={(event) => setBulkStatus(event.target.value)}>
                    {STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
                </select>
            </label>
            <GlassButton disabled={busy || loading || count > 500} onClick={() => setConfirm(true)}>Apply bulk status</GlassButton>
            <GlassButton disabled={busy} onClick={selection.clear}>Clear selection</GlassButton>
        </div> : null}
        {actionError ? <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{actionError}</p> : null}
        <DataTable rows={response?.workspaces ?? []} columns={columns} total={total} page={response?.pagination.page ?? 1} pageSize={25}
            sort={params.get('sort') ?? 'name'} sortDirection={params.get('direction') === 'desc' ? 'desc' : 'asc'}
            loading={loading} error={error} emptyMessage="No public workspaces match these filters." selectable={!busy && !error}
            selectedIds={selection.selectedIds} isRowSelected={selection.isSelected} allMatchingSelected={selection.allMatchingSelected}
            onSelect={selection.setSelected} onSelectPage={selection.setPageSelected} onSelectAllMatchingPages={selection.selectAllAcrossPages}
            onSort={(field, direction) => { setParam('page', null); setParam('sort', field); setParam('direction', direction); }}
            onPageChange={(page) => setParam('page', String(page))} />
        {params.get('id') ? <GroupDetailDrawer key={params.get('id')} entity="public" id={params.get('id')!}
            onClose={() => setParam('id', null)} onChanged={() => setRevision((value) => value + 1)} /> : null}
        {confirm ? <ReasonConfirmDialog title={`Set ${count} workspaces to ${bulkStatus}?`}
            description="This applies immediately and records status history. Active unlocks the workspace and enables uploads."
            reasonRequired={['locked', 'inactive'].includes(bulkStatus)} confirmLabel="Apply bulk status"
            onClose={() => setConfirm(false)} onConfirm={(reason) => void applyBulk(reason)} /> : null}
    </section>;
}
