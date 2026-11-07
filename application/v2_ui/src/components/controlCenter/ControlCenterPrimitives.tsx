// ControlCenterPrimitives.tsx
// Reusable building blocks for Control Center management sections.

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Download, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { Modal } from '../ui/Modal';
import { GlassButton, GlassPanel } from '../ui/primitives';

export interface DataColumn<Row> {
    id: string;
    label: string;
    render: (row: Row) => ReactNode;
    sortable?: boolean;
}

export function useCrossPageSelection() {
    const [selection, setSelection] = useState<{
        allMatchingSelected: boolean;
        includedIds: Set<string>;
        excludedIds: Set<string>;
    }>(() => ({ allMatchingSelected: false, includedIds: new Set(), excludedIds: new Set() }));
    return {
        selectedIds: selection.includedIds,
        excludedIds: selection.excludedIds,
        allMatchingSelected: selection.allMatchingSelected,
        isSelected: (id: string) => selection.allMatchingSelected
            ? !selection.excludedIds.has(id)
            : selection.includedIds.has(id),
        selectAllAcrossPages: () => setSelection({
            allMatchingSelected: true, includedIds: new Set(), excludedIds: new Set(),
        }),
        setSelected: (id: string, selected: boolean) => setSelection((current) => {
            const includedIds = new Set(current.includedIds);
            const excludedIds = new Set(current.excludedIds);
            if (current.allMatchingSelected) {
                if (selected) excludedIds.delete(id);
                else excludedIds.add(id);
            } else if (selected) includedIds.add(id);
            else includedIds.delete(id);
            return { ...current, includedIds, excludedIds };
        }),
        setPageSelected: (ids: string[], selected: boolean) => setSelection((current) => {
            const includedIds = new Set(current.includedIds);
            const excludedIds = new Set(current.excludedIds);
            ids.forEach((id) => {
                if (current.allMatchingSelected) {
                    if (selected) excludedIds.delete(id);
                    else excludedIds.add(id);
                } else if (selected) includedIds.add(id);
                else includedIds.delete(id);
            });
            return { ...current, includedIds, excludedIds };
        }),
        clear: () => setSelection({
            allMatchingSelected: false, includedIds: new Set(), excludedIds: new Set(),
        }),
    };
}

export function DataTable<Row extends { id: string }>({
    rows,
    columns,
    total,
    page,
    pageSize,
    sort,
    sortDirection,
    loading = false,
    error,
    emptyMessage = 'No records found.',
    selectable = false,
    selectedIds = new Set<string>(),
    isRowSelected,
    allMatchingSelected = false,
    onSelect,
    onSelectPage,
    onSelectAllMatchingPages,
    onSort,
    onPageChange,
}: {
    rows: Row[];
    columns: DataColumn<Row>[];
    total: number;
    page: number;
    pageSize: number;
    sort?: string;
    sortDirection?: 'asc' | 'desc';
    loading?: boolean;
    error?: string | null;
    emptyMessage?: string;
    selectable?: boolean;
    selectedIds?: ReadonlySet<string>;
    isRowSelected?: (id: string) => boolean;
    allMatchingSelected?: boolean;
    onSelect?: (id: string, selected: boolean) => void;
    onSelectPage?: (ids: string[], selected: boolean) => void;
    onSelectAllMatchingPages?: () => void;
    onSort?: (columnId: string, direction: 'asc' | 'desc') => void;
    onPageChange?: (page: number) => void;
}) {
    const pageIds = rows.map((row) => row.id);
    const rowIsSelected = (id: string) => isRowSelected?.(id) ?? selectedIds.has(id);
    const allSelected = pageIds.length > 0 && pageIds.every(rowIsSelected);
    const pageCount = Math.max(1, Math.ceil(total / pageSize));
    return (
        <div className="overflow-hidden rounded-2xl border border-edge bg-surface-1">
            {selectable && total > rows.length && allSelected && !allMatchingSelected && onSelectAllMatchingPages ? (
                <div className="border-b border-edge bg-accent-soft px-4 py-2 text-center text-sm text-text-2" role="status">
                    All {rows.length} records on this page are selected.{' '}
                    <button type="button" className="font-semibold text-accent underline"
                        onClick={onSelectAllMatchingPages}>
                        Select all {total.toLocaleString()} matching records
                    </button>
                </div>
            ) : null}
            <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                    <thead className="bg-surface-2 text-xs text-text-3">
                        <tr>
                            {selectable ? (
                                <th className="w-10 px-3 py-3">
                                    <input aria-label="Select all rows on this page" type="checkbox"
                                        checked={allSelected}
                                        onChange={(event) => onSelectPage?.(pageIds, event.target.checked)} />
                                </th>
                            ) : null}
                            {columns.map((column) => (
                                <th key={column.id} scope="col" className="px-4 py-3 font-medium">
                                    {column.sortable && onSort ? (
                                        <button type="button" onClick={() => onSort(
                                            column.id,
                                            sort === column.id && sortDirection === 'asc' ? 'desc' : 'asc',
                                        )} aria-label={`Sort by ${column.label}`}>
                                            {column.label}
                                            {sort === column.id ? (sortDirection === 'asc' ? ' ↑' : ' ↓') : ''}
                                        </button>
                                    ) : column.label}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-edge">
                        {loading ? (
                            <tr><td colSpan={columns.length + Number(selectable)} className="px-4 py-8 text-center text-text-3" role="status">Loading records…</td></tr>
                        ) : error ? (
                            <tr><td colSpan={columns.length + Number(selectable)} className="px-4 py-8 text-center text-danger" role="alert">{error}</td></tr>
                        ) : rows.length === 0 ? (
                            <tr><td colSpan={columns.length + Number(selectable)} className="px-4 py-8 text-center text-text-3">{emptyMessage}</td></tr>
                        ) : rows.map((row) => (
                            <tr key={row.id} className="text-text-2 hover:bg-surface-2">
                                {selectable ? (
                                    <td className="px-3 py-3">
                                        <input type="checkbox" aria-label={`Select row ${row.id}`}
                                            checked={rowIsSelected(row.id)}
                                            onChange={(event) => onSelect?.(row.id, event.target.checked)} />
                                    </td>
                                ) : null}
                                {columns.map((column) => <td key={column.id} className="px-4 py-3">{column.render(row)}</td>)}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="flex items-center justify-between border-t border-edge px-4 py-2 text-xs text-text-3">
                <span>{total.toLocaleString()} records · Page {page} of {pageCount}</span>
                <div className="flex gap-2">
                    <GlassButton size="sm" disabled={page <= 1 || loading} onClick={() => onPageChange?.(page - 1)}>Previous</GlassButton>
                    <GlassButton size="sm" disabled={page >= pageCount || loading} onClick={() => onPageChange?.(page + 1)}>Next</GlassButton>
                </div>
            </div>
        </div>
    );
}

export function FilterBar({
    search,
    onSearch,
    filters,
    children,
}: {
    search: string;
    onSearch: (value: string) => void;
    filters?: { id: string; label: string; active: boolean; onRemove: () => void }[];
    children?: ReactNode;
}) {
    return (
        <div className="flex flex-wrap items-center gap-2" role="search">
            <label className="flex min-w-52 flex-1 items-center gap-2 rounded-xl border border-edge bg-surface-1 px-3 py-2">
                <Search size={15} aria-hidden="true" className="text-text-3" />
                <span className="sr-only">Search records</span>
                <input className="w-full bg-transparent text-sm text-text-1 outline-none placeholder:text-text-3"
                    value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search…" />
            </label>
            {filters?.filter((filter) => filter.active).map((filter) => (
                <button key={filter.id} type="button" onClick={filter.onRemove}
                    className="rounded-full bg-accent-soft px-3 py-1.5 text-xs text-accent">
                    {filter.label} <span aria-hidden="true">×</span><span className="sr-only">Remove filter</span>
                </button>
            ))}
            {children}
        </div>
    );
}

export function useUrlQueryParams() {
    const [search, setSearch] = useState(() => window.location.search);
    useEffect(() => {
        const onPopState = () => setSearch(window.location.search);
        window.addEventListener('popstate', onPopState);
        return () => window.removeEventListener('popstate', onPopState);
    }, []);
    const params = useMemo(() => new URLSearchParams(search), [search]);
    return {
        params,
        setParam: (key: string, value: string | null) => {
            const next = new URLSearchParams(window.location.search);
            if (value) next.set(key, value);
            else next.delete(key);
            const query = next.toString();
            window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
            setSearch(window.location.search);
        },
    };
}

export function DetailDrawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
    return (
        <Modal title={title} onClose={onClose} placement="drawer" bodyClassName="overflow-y-auto p-5"
            banner={
                <div className="flex items-center justify-between gap-3 border-b border-edge p-5">
                    <h2 className="text-lg font-semibold text-text-1">{title}</h2>
                    <GlassButton size="sm" onClick={onClose}>Close</GlassButton>
                </div>
            }>
            {children}
        </Modal>
    );
}

export function StatusBadge({ status }: { status: string }) {
    const tone = /^(active|approved|complete|enabled)$/i.test(status)
        ? 'bg-ok-soft text-ok' : /pending|review|processing/i.test(status)
            ? 'bg-warn-soft text-warn' : /blocked|denied|failed|disabled|locked|inactive/i.test(status)
                ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-text-2';
    return <span className={clsx('inline-flex rounded-full px-2 py-0.5 text-xs font-medium', tone)}>{status}</span>;
}

export function KpiCard({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
    return <GlassPanel className="p-4"><p className="text-xs text-text-3">{label}</p><p className="mt-1 text-2xl font-semibold text-text-1">{value}</p>{detail ? <p className="mt-1 text-xs text-text-3">{detail}</p> : null}</GlassPanel>;
}

export function ReasonConfirmDialog({
    title, description, reasonRequired = false, onConfirm, onClose, confirmLabel,
}: {
    title: string; description: string; reasonRequired?: boolean; confirmLabel: string;
    onConfirm: (reason: string) => void; onClose: () => void;
}) {
    const [reason, setReason] = useState('');
    return (
        <ConfirmDialog title={title} description={description} confirmLabel={confirmLabel}
            confirmDisabled={reasonRequired && !reason.trim()} tone="primary" onClose={onClose}
            onConfirm={() => onConfirm(reason.trim())}>
            <label className="block text-sm text-text-2">
                Reason {reasonRequired ? '(required)' : '(optional)'}
                <textarea className="mt-2 min-h-24 w-full rounded-xl border border-edge bg-surface-1 p-3 text-sm text-text-1"
                    value={reason} onChange={(event) => setReason(event.target.value)} required={reasonRequired} />
            </label>
        </ConfirmDialog>
    );
}

export const APPROVALS_URL = '/approvals';

export function ApprovalSubmittedNotice({ children, approvalId, groupId }: {
    children: ReactNode; approvalId?: string; groupId?: string;
}) {
    const path = approvalId ? `${APPROVALS_URL}/all/${encodeURIComponent(approvalId)}` : APPROVALS_URL;
    const query = groupId ? `?${new URLSearchParams({ group_id: groupId })}` : '';
    return <GlassPanel role="status" className="border border-warn/30 bg-warn-soft p-4 text-sm text-text-1">
        <p>{children}</p><Link className="mt-2 inline-block text-accent underline" to={`${path}${query}`}>View approval requests</Link>
    </GlassPanel>;
}

export function ExportButton({
    filename,
    rows,
    serverQuery,
    entity = 'users',
}: {
    filename: string;
    rows?: Record<string, unknown>[];
    serverQuery?: string;
    entity?: 'users' | 'groups' | 'public-workspaces';
}) {
    if (serverQuery !== undefined) {
        return (
            <a className="inline-flex items-center gap-2 rounded-xl border border-edge bg-surface-1 px-3 py-1.5 text-xs font-medium text-text-1 hover:bg-surface-2"
                href={`/api/v2/control-center/${entity}/export.csv${serverQuery ? `?${serverQuery}` : ''}`}
                download={filename}>
                <Download size={14} aria-hidden="true" />Export CSV
            </a>
        );
    }

    const exportCsv = () => {
        if (!rows) return;
        const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
        const escape = (value: unknown) => {
            const text = typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '');
            const safe = /^[\s]*[=+\-@]/.test(text) ? `'${text}` : text;
            return `"${safe.replaceAll('"', '""')}"`;
        };
        const csv = [headers.map(escape).join(','), ...rows.map((row) => headers.map((key) => escape(row[key])).join(','))].join('\r\n');
        const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
        URL.revokeObjectURL(url);
    };
    return <GlassButton size="sm" onClick={exportCsv}><Download size={14} aria-hidden="true" />Export CSV</GlassButton>;
}
