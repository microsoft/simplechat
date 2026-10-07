// GroupsSection.tsx
// Server-filtered group inventory with URL state, cross-page selection and audited bulk updates.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/apiClient';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { DataTable, ExportButton, FilterBar, ReasonConfirmDialog, StatusBadge, useCrossPageSelection, useUrlQueryParams, type DataColumn } from './ControlCenterPrimitives';
import { GROUP_INPUT, GroupDetailDrawer, type GroupRow } from './GroupDetailDrawer';
import { entityDate } from './EntityDetailSections';

interface GroupsResponse {
    groups: GroupRow[];
    pagination: { total_items: number; page: number };
    metrics_freshness: { calculated_at: string; ttl_seconds: number };
}

const FILTER_KEYS = ['search', 'status', 'owner', 'members_min', 'members_max', 'has_documents', 'created_from', 'created_to', 'activity_from', 'activity_to'];
const STATUSES = ['active', 'locked', 'upload_disabled', 'inactive'];

function groupQuery(params: URLSearchParams) {
    const query = new URLSearchParams(params);
    query.delete('id');
    return query;
}

export function GroupsSection() {
    const { params, setParam } = useUrlQueryParams();
    const selection = useCrossPageSelection();
    const [response, setResponse] = useState<GroupsResponse | null>(null);
    const [error, setError] = useState('');
    const [actionError, setActionError] = useState('');
    const [loading, setLoading] = useState(true);
    const [revision, setRevision] = useState(0);
    const refreshedRevision = useRef(0);
    const [bulkStatus, setBulkStatus] = useState('locked');
    const [confirmBulk, setConfirmBulk] = useState(false);
    const [busy, setBusy] = useState(false);
    const requestQuery = useMemo(() => {
        const query = groupQuery(params);
        query.set('per_page', '25');
        return query.toString();
    }, [params]);
    const filterKey = FILTER_KEYS.map((key) => params.get(key)).join('|');

    useEffect(() => {
        selection.clear();
    // Paging and sorting preserve the selected population; filters do not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterKey]);
    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        const query = new URLSearchParams(requestQuery);
        if (revision > refreshedRevision.current) query.set('force_refresh', '1');
        api.get<GroupsResponse>(`/api/v2/control-center/groups?${query}`, controller.signal)
            .then((data) => {
                if (!controller.signal.aborted) {
                    refreshedRevision.current = revision;
                    setResponse(data);
                }
            })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Unable to load groups.');
            })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [requestQuery, revision]);

    const updateFilter = (key: string, value: string) => {
        setParam('page', null);
        setParam(key, value === 'all' || !value ? null : value);
    };
    const columns: DataColumn<GroupRow>[] = [
        { id: 'name', label: 'Group', sortable: true, render: (row) =>
            <button type="button" className="text-left font-medium text-text-1 hover:text-accent hover:underline focus-visible:outline-2 focus-visible:outline-accent"
                aria-label={`Open details for ${row.name || row.id}`} onClick={() => setParam('id', row.id)}>{row.name || 'Unnamed group'}</button> },
        { id: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> },
        { id: 'owner', label: 'Owner', sortable: true, render: (row) => row.owner.id
            ? <Link className="text-accent underline" to={`/control-center/users?user_id=${encodeURIComponent(row.owner.id)}`}>{row.owner.display_name || row.owner.email || row.owner.id}</Link>
            : 'No owner recorded' },
        { id: 'members', label: 'Members', sortable: true, render: (row) => row.members.toLocaleString() },
        { id: 'documents', label: 'Documents', sortable: true, render: (row) => row.documents.toLocaleString() },
        { id: 'tokens', label: 'Tokens', sortable: true, render: (row) => row.tokens.toLocaleString() },
        { id: 'last_activity', label: 'Last activity', sortable: true, render: (row) => entityDate(row.last_activity) },
    ];
    const total = response?.pagination.total_items ?? 0;
    const count = selection.allMatchingSelected ? Math.max(0, total - selection.excludedIds.size) : selection.selectedIds.size;
    const applyBulk = async (reason: string) => {
        if (busy) return;
        setConfirmBulk(false);
        setBusy(true);
        setActionError('');
        const payload = selection.allMatchingSelected
            ? { filter: Object.fromEntries(FILTER_KEYS.flatMap((key) => params.has(key) ? [[key, params.get(key)]] : [])),
                exclude_ids: Array.from(selection.excludedIds) }
            : { group_ids: Array.from(selection.selectedIds) };
        try {
            const result = await api.post<{ success_count: number; failed_count: number; failed_groups: { id: string; error: string }[] }>(
                '/api/v2/control-center/groups/bulk-status', { ...payload, status: bulkStatus, reason },
            );
            selection.clear();
            setRevision((value) => value + 1);
            if (result.failed_count) {
                setActionError(`${result.success_count} succeeded; ${result.failed_count} failed. ${result.failed_groups.map((group) => `${group.id}: ${group.error}`).join('; ')}`);
                toast.error('Some groups could not be updated. Review the failure details.');
            } else { toast.success(`${result.success_count} groups updated.`); }
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : 'Unable to update groups.');
        } finally { setBusy(false); }
    };
    const exportQuery = groupQuery(params);
    exportQuery.delete('page');
    exportQuery.delete('per_page');
    exportQuery.delete('force_refresh');

    return <section className="space-y-4 p-4 md:p-6" aria-labelledby="control-center-groups-heading">
        <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
                <h2 id="control-center-groups-heading" className="text-xl font-semibold text-text-1">Groups</h2>
                <p className="mt-1 max-w-3xl text-sm text-text-3">Review shared workspaces, membership, usage and governed actions.</p>
            </div>
            <div className="flex gap-2">
                <GlassButton disabled={loading || busy} onClick={() => setRevision((value) => value + 1)}>Refresh groups</GlassButton>
                <ExportButton entity="groups" filename="control-center-groups.csv" serverQuery={exportQuery.toString()} />
            </div>
        </div>
        <FilterBar search={params.get('search') ?? ''} onSearch={(value) => updateFilter('search', value)}>
            <label className="grid gap-1 text-xs text-text-3">Status
                <select className={GROUP_INPUT} aria-label="Filter by group status" value={params.get('status') ?? 'all'} onChange={(event) => updateFilter('status', event.target.value)}>
                    <option value="all">Any status</option>
                    {STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
                </select>
            </label>
            <label className="grid gap-1 text-xs text-text-3">Owner
                <input className={GROUP_INPUT} value={params.get('owner') ?? ''} onChange={(event) => updateFilter('owner', event.target.value)} placeholder="Name, email or ID" />
            </label>
            <label className="grid gap-1 text-xs text-text-3">Documents
                <select aria-label="Filter by group documents" className={GROUP_INPUT} value={params.get('has_documents') ?? 'all'} onChange={(event) => updateFilter('has_documents', event.target.value)}>
                    <option value="all">Any</option><option value="yes">Has documents</option><option value="no">No documents</option>
                </select>
            </label>
        </FilterBar>
        <details className="rounded-xl border border-edge p-3">
            <summary className="cursor-pointer text-sm text-text-2">Member and date filters</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {[
                    ['members_min', 'Minimum members', 'number'], ['members_max', 'Maximum members', 'number'],
                    ['created_from', 'Created from', 'date'], ['created_to', 'Created through', 'date'],
                    ['activity_from', 'Activity from', 'date'], ['activity_to', 'Activity through', 'date'],
                ].map(([key, label, type]) => <label key={key} className="grid gap-1 text-xs text-text-3">{label}
                    <input type={type} min={type === 'number' ? 0 : undefined} className={GROUP_INPUT}
                        value={params.get(key) ?? ''} onChange={(event) => updateFilter(key, event.target.value)} />
                </label>)}
            </div>
        </details>
        {count ? <div role="region" aria-label="Bulk group actions" className="flex flex-wrap items-center gap-3 rounded-xl border border-edge bg-surface-2 p-3">
            <span className="mr-auto text-sm text-text-1">{selection.allMatchingSelected ? `All ${count} matching groups selected` : `${count} selected`} (limit 500)</span>
            <label className="text-xs text-text-3">Bulk status
                <select aria-label="Bulk group status" className={`ml-2 ${GROUP_INPUT}`} value={bulkStatus} disabled={busy} onChange={(event) => setBulkStatus(event.target.value)}>
                    {STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
                </select>
            </label>
            <GlassButton disabled={busy || loading || count > 500} onClick={() => setConfirmBulk(true)}>Apply bulk status</GlassButton>
            <GlassButton disabled={busy} onClick={selection.clear}>Clear selection</GlassButton>
        </div> : null}
        {actionError ? <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{actionError}</p> : null}
        <DataTable rows={response?.groups ?? []} columns={columns} total={total} page={response?.pagination.page ?? 1} pageSize={25}
            sort={params.get('sort') ?? 'name'} sortDirection={params.get('direction') === 'desc' ? 'desc' : 'asc'}
            loading={loading} error={error} emptyMessage="No groups match these filters." selectable={!busy}
            selectedIds={selection.selectedIds} isRowSelected={selection.isSelected} allMatchingSelected={selection.allMatchingSelected}
            onSelect={selection.setSelected} onSelectPage={selection.setPageSelected} onSelectAllMatchingPages={selection.selectAllAcrossPages}
            onSort={(field, direction) => { setParam('sort', field); setParam('direction', direction); }}
            onPageChange={(page) => setParam('page', String(page))} />
        {response ? <p className="text-xs text-text-3" aria-live="polite">
            Totals calculated {entityDate(response.metrics_freshness.calculated_at)}. Server snapshot cached for {response.metrics_freshness.ttl_seconds} seconds.
        </p> : null}
        {params.get('id') ? <GroupDetailDrawer key={params.get('id')} id={params.get('id')!}
            onClose={() => setParam('id', null)} onChanged={() => setRevision((value) => value + 1)} /> : null}
        {confirmBulk ? <ReasonConfirmDialog title={`Set ${count} groups to ${bulkStatus}?`}
            description="This applies immediately to the selected groups and records each transition in its audit history."
            reasonRequired={['locked', 'inactive'].includes(bulkStatus)} confirmLabel="Apply bulk status"
            onClose={() => setConfirmBulk(false)} onConfirm={(reason) => void applyBulk(reason)} /> : null}
    </section>;
}
