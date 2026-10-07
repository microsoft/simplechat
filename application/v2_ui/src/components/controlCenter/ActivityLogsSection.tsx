// ActivityLogsSection.tsx
// THESIS: Follow evidence from a bounded activity feed, without implying unbounded totals.
// OWN-WORLD: Inherit the Control Center's semantic surfaces, blue accent, and workhorse type.
// STORY: Filter a UTC window, inspect its distribution, then open the record and its related entity.
// FIRST VIEWPORT: Filters precede the histogram and facet chips; the chronological table owns the workspace.
// FORM: Operate; a local extension of the established management pane, with keyboard-safe details.

import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Download, RefreshCw } from 'lucide-react';
import { clsx } from 'clsx';
import { api, apiUrl, CREDENTIALS_MODE } from '../../lib/apiClient';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { cartesianOptions, StatsChart } from '../settings/StatsChart';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { DetailDrawer } from './ControlCenterPrimitives';

type ActivityRecord = {
    id: string;
    timestamp: string;
    activity_type?: unknown;
    user_id?: unknown;
    workspace_type?: unknown;
    [key: string]: unknown;
};
type ActivityPage = { items: ActivityRecord[]; next_cursor: string | null; snapshot: string };
type ActivitySummary = {
    facets: { activity_type: string; count: number }[];
    histogram: { date: string; count: number }[];
    bucket_days: number;
    sample_size: number;
    sample_limit: number;
    truncated: boolean;
};
type SavedView = { name: string; query: string };
const FILTER_KEYS = ['start_date', 'end_date', 'user_id', 'workspace_type', 'workspace_id', 'group_id',
    'public_workspace_id', 'search', 'token_type', 'model', 'status'] as const;
type FilterKey = typeof FILTER_KEYS[number];
type Filters = Record<FilterKey, string> & { activity_type: string[] };
const FIELD_CLASS = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';
const COMMON_TYPES = ['user_login', 'chat_activity', 'conversation_creation', 'conversation_deletion',
    'document_creation', 'document_deletion', 'token_usage', 'group_status_change', 'public_workspace_status_change'];

function readFilters(params: URLSearchParams): Filters {
    const end = new Date().toISOString().slice(0, 10);
    const start = new Date(`${end}T00:00:00Z`);
    start.setUTCDate(start.getUTCDate() - 29);
    const fields = Object.fromEntries(FILTER_KEYS.map((key) => [key, params.get(key) ?? ''])) as Record<FilterKey, string>;
    fields.start_date ||= params.get('date') || start.toISOString().slice(0, 10);
    fields.end_date ||= params.get('date') || end;
    if (fields.workspace_type === 'public_workspace') fields.workspace_type = 'public';
    return {
        ...fields,
        activity_type: [...new Set(params.getAll('activity_type').flatMap((value) => value.split(',')).filter((value) => value && value !== 'all'))],
    };
}

function filterParams(filters: Filters): URLSearchParams {
    const params = new URLSearchParams();
    FILTER_KEYS.forEach((key) => { if (filters[key]) params.set(key, filters[key]); });
    filters.activity_type.forEach((value) => params.append('activity_type', value));
    return params;
}

function recordText(record: ActivityRecord, ...path: string[]): string {
    let value: unknown = record;
    for (const part of path) {
        if (typeof value !== 'object' || value === null) return '';
        value = (value as Record<string, unknown>)[part];
    }
    return typeof value === 'string' ? value : '';
}

function recordUser(record: ActivityRecord): string {
    return recordText(record, 'user_id') || recordText(record, 'changed_by', 'user_id') || recordText(record, 'admin_user_id');
}

function recordGroup(record: ActivityRecord): string {
    return recordText(record, 'workspace_context', 'group_id') || recordText(record, 'group_id') || recordText(record, 'group', 'group_id');
}

function recordWorkspace(record: ActivityRecord): string {
    return recordText(record, 'workspace_context', 'public_workspace_id') || recordText(record, 'public_workspace_id');
}

function ActivityDetail({ record, onClose }: { record: ActivityRecord; onClose: () => void }) {
    const user = recordUser(record);
    const group = recordGroup(record);
    const workspace = recordWorkspace(record);
    const approval = recordText(record, 'approval_id') || recordText(record, 'approval', 'id');
    return (
        <DetailDrawer title="Activity details" onClose={onClose}>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-3 text-sm">
                {[['Activity', recordText(record, 'activity_type') || 'Unknown'], ['UTC timestamp', record.timestamp],
                    ['Record ID', record.id], ['User', user || 'Not recorded'],
                    ['Workspace type', recordText(record, 'workspace_type') || 'Not recorded']].map(([label, value]) => (
                    <div key={label} className="contents"><dt className="text-text-3">{label}</dt><dd className="break-all text-text-1">{value}</dd></div>
                ))}
            </dl>
            <nav aria-label="Related activity records" className="mt-5 flex flex-wrap gap-3 text-sm text-accent">
                {user ? <Link className="underline" to={`/control-center/users?user_id=${encodeURIComponent(user)}`}>View user</Link> : null}
                {group ? <Link className="underline" to={`/control-center/groups?id=${encodeURIComponent(group)}`}>View group</Link> : null}
                {workspace ? <Link className="underline" to={`/control-center/public-workspaces?id=${encodeURIComponent(workspace)}`}>View workspace</Link> : null}
                {approval ? <Link className="underline" to={`/approvals/all/${encodeURIComponent(approval)}${group ? `?group_id=${encodeURIComponent(group)}` : ''}`}>View approval</Link> : null}
            </nav>
            <h3 className="mb-2 mt-6 font-semibold text-text-1">Raw JSON</h3>
            <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-2 p-4 text-xs text-text-2">
                {JSON.stringify(record, null, 2)}
            </pre>
        </DetailDrawer>
    );
}

export function ActivityLogsSection() {
    const [params, setParams] = useSearchParams();
    const paramString = params.toString();
    const applied = useMemo(() => readFilters(new URLSearchParams(paramString)), [paramString]);
    const query = filterParams(applied).toString();
    const [draft, setDraft] = useState(applied);
    const [paging, setPaging] = useState<{ query: string; cursors: (string | null)[]; index: number }>({ query, cursors: [null], index: 0 });
    const currentPaging = paging.query === query ? paging : { query, cursors: [null], index: 0 };
    const cursor = currentPaging.cursors[currentPaging.index];
    const [data, setData] = useState<ActivityPage | null>(null);
    const [summary, setSummary] = useState<ActivitySummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [summaryError, setSummaryError] = useState('');
    const [selected, setSelected] = useState<ActivityRecord | null>(null);
    const [refresh, setRefresh] = useState(0);
    const [density, setDensity] = useState<'comfortable' | 'compact'>('comfortable');
    const [viewName, setViewName] = useState('');
    const [views, setViews] = useState<SavedView[]>([]);
    const [storageError, setStorageError] = useState('');
    const [exporting, setExporting] = useState(false);
    const [exportError, setExportError] = useState('');
    const userId = useBootstrapStore((state) => state.data?.user.id ?? '');
    const storageKey = `simplechat.activity-views.${userId}`;

    useEffect(() => { setDraft(applied); setSelected(null); }, [applied]);
    useEffect(() => {
        try {
            const stored: unknown = JSON.parse(localStorage.getItem(storageKey) || '[]');
            if (!Array.isArray(stored) || stored.length > 20 || !stored.every((item: unknown) => (
                typeof item === 'object' && item !== null && 'name' in item && 'query' in item
                && typeof item.name === 'string' && item.name.length <= 80
                && typeof item.query === 'string' && item.query.length <= 4096
            ))) throw new Error('Invalid saved views');
            setViews(stored as SavedView[]);
            setStorageError('');
        } catch {
            setViews([]);
            setStorageError('Saved views could not be read from this browser.');
        }
    }, [storageKey]);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        setData(null);
        const pageQuery = new URLSearchParams(query);
        pageQuery.set('page_size', '50');
        if (cursor) pageQuery.set('cursor', cursor);
        api.get<ActivityPage>(`/api/v2/control-center/activity-logs?${pageQuery}`, controller.signal)
            .then((result) => { if (!controller.signal.aborted) setData(result); })
            .catch((failure: unknown) => {
                if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Unable to load activity. Retry or narrow the filters.');
            })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [query, cursor, refresh]);

    useEffect(() => {
        const controller = new AbortController();
        setSummary(null);
        setSummaryError('');
        api.get<ActivitySummary>(`/api/v2/control-center/activity-logs/summary?${query}`, controller.signal)
            .then((result) => { if (!controller.signal.aborted) setSummary(result); })
            .catch((failure: unknown) => {
                if (!controller.signal.aborted) setSummaryError(failure instanceof Error ? failure.message : 'Unable to load the summary. Retry.');
            });
        return () => controller.abort();
    }, [query, refresh]);

    const update = (key: FilterKey, value: string) => setDraft((previous) => ({ ...previous, [key]: value }));
    const apply = (event: FormEvent) => { event.preventDefault(); setParams(filterParams(draft)); };
    const toggleType = (type: string) => {
        const types = applied.activity_type.includes(type) ? applied.activity_type.filter((item) => item !== type) : [...applied.activity_type, type];
        setParams(filterParams({ ...applied, activity_type: types }));
    };
    const persistViews = (next: SavedView[]) => {
        try {
            localStorage.setItem(storageKey, JSON.stringify(next));
            setViews(next);
            setStorageError('');
            setViewName('');
        } catch {
            setStorageError('This browser could not save the view. Check storage permissions and retry.');
        }
    };
    const saveView = (event: FormEvent) => {
        event.preventDefault();
        const name = viewName.trim();
        if (!name) return;
        persistViews([...views.filter((view) => view.name !== name), { name, query }].slice(-20));
    };
    const openPreset = (activityType: string) => {
        const preset = readFilters(new URLSearchParams());
        const start = new Date(`${preset.end_date}T00:00:00Z`);
        start.setUTCDate(start.getUTCDate() - 6);
        preset.start_date = start.toISOString().slice(0, 10);
        preset.activity_type = [activityType];
        setParams(filterParams(preset));
    };
    const exportCsv = async () => {
        setExporting(true);
        setExportError('');
        try {
            const response = await fetch(apiUrl(`/api/v2/control-center/activity-logs/export.csv?${query}`), { credentials: CREDENTIALS_MODE });
            if (!response.ok) throw new Error('Activity export failed. Check the filters and retry.');
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            try {
                const anchor = document.createElement('a');
                anchor.href = url;
                anchor.download = 'activity_logs.csv';
                anchor.click();
            } finally {
                URL.revokeObjectURL(url);
            }
        } catch (failure) {
            setExportError(failure instanceof Error ? failure.message : 'Activity export failed. Retry.');
        } finally {
            setExporting(false);
        }
    };
    const types = [...new Set([...COMMON_TYPES, ...applied.activity_type, ...(summary?.facets.map((facet) => facet.activity_type) || [])])];
    const counts = new Map(summary?.facets.map((facet) => [facet.activity_type, facet.count]));
    const cellClass = density === 'compact' ? 'px-4 py-2' : 'px-4 py-4';

    return (
        <div className="space-y-5 p-5 md:p-8">
            <header className="flex flex-wrap items-start justify-between gap-3">
                <div><h2 className="text-xl font-semibold text-text-1">Activity Logs</h2>
                    <p className="mt-1 max-w-prose text-sm text-text-2">Trace recorded activity across users and workspaces. Date filters use UTC.</p></div>
                <div className="flex gap-2">
                    <GlassButton size="sm" disabled={loading} onClick={() => { setPaging({ query, cursors: [null], index: 0 }); setRefresh((value) => value + 1); }}>
                        <RefreshCw size={14} aria-hidden="true" />Refresh
                    </GlassButton>
                    <GlassButton size="sm" disabled={exporting || loading || Boolean(error)} onClick={() => void exportCsv()}>
                        <Download size={14} aria-hidden="true" />{exporting ? 'Exporting...' : 'Export CSV'}
                    </GlassButton>
                </div>
            </header>
            <form onSubmit={apply} className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <label className="text-xs text-text-2">Start date (UTC)<input type="date" required className={FIELD_CLASS} value={draft.start_date} onChange={(event) => update('start_date', event.target.value)} /></label>
                    <label className="text-xs text-text-2">End date (UTC)<input type="date" required className={FIELD_CLASS} value={draft.end_date} onChange={(event) => update('end_date', event.target.value)} /></label>
                    <label className="text-xs text-text-2">User ID<input className={FIELD_CLASS} maxLength={256} value={draft.user_id} onChange={(event) => update('user_id', event.target.value)} /></label>
                    <label className="text-xs text-text-2">Search activity<input className={FIELD_CLASS} maxLength={200} value={draft.search} onChange={(event) => update('search', event.target.value)} placeholder="Name, ID, file, action..." /></label>
                    <label className="text-xs text-text-2">Workspace type<select className={FIELD_CLASS} value={draft.workspace_type} onChange={(event) => update('workspace_type', event.target.value)}>
                        <option value="">All workspaces</option><option value="personal">Personal</option><option value="group">Group</option><option value="public">Public</option>
                    </select></label>
                    <label className="text-xs text-text-2">Workspace ID<input className={FIELD_CLASS} maxLength={256} value={draft.workspace_id} onChange={(event) => update('workspace_id', event.target.value)} /></label>
                    <label className="text-xs text-text-2">Model<input className={FIELD_CLASS} maxLength={256} value={draft.model} onChange={(event) => update('model', event.target.value)} /></label>
                    <label className="text-xs text-text-2">Token type<select className={FIELD_CLASS} value={draft.token_type} onChange={(event) => update('token_type', event.target.value)}>
                        <option value="">All token types</option><option value="chat">Chat</option><option value="embedding">Embedding</option><option value="web_search">Web search</option>
                    </select></label>
                </div>
                <details className="text-sm text-text-2"><summary className="cursor-pointer">More filters</summary>
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                        {(['group_id', 'public_workspace_id', 'status'] as const).map((key) => (
                            <label key={key} className="text-xs">{key === 'group_id' ? 'Group ID' : key === 'public_workspace_id' ? 'Public workspace ID' : 'Recorded status'}
                                <input className={FIELD_CLASS} maxLength={256} value={draft[key]} onChange={(event) => update(key, event.target.value)} />
                            </label>
                        ))}
                    </div>
                </details>
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="submit" size="sm" variant="primary">Apply filters</GlassButton>
                    <GlassButton size="sm" onClick={() => setParams(new URLSearchParams())}>Clear filters</GlassButton>
                    <span className="text-xs text-text-3">Up to 366 days. CSV includes at most 10,000 records.</span>
                </div>
            </form>
            {exportError ? <p role="alert" className="text-sm text-danger">{exportError}</p> : null}
            <div className="flex flex-wrap items-end gap-3 border-y border-edge py-3">
                <div className="flex gap-2">
                    <GlassButton size="sm" onClick={() => openPreset('user_login')}>Recent logins</GlassButton>
                    <GlassButton size="sm" onClick={() => openPreset('token_usage')}>Recent token usage</GlassButton>
                </div>
                <label className="min-w-48 text-xs text-text-2">Saved views<select aria-label="Saved views" className={FIELD_CLASS} value="" onChange={(event) => {
                    const view = views.find((item) => item.name === event.target.value);
                    if (view) setParams(filterParams(readFilters(new URLSearchParams(view.query))));
                }}><option value="">Choose a saved view</option>{views.map((view) => <option key={view.name} value={view.name}>{view.name}</option>)}</select></label>
                <form onSubmit={saveView} className="flex items-end gap-2">
                    <label className="text-xs text-text-2">View name<input maxLength={80} className={FIELD_CLASS} value={viewName} onChange={(event) => setViewName(event.target.value)} /></label>
                    <GlassButton size="sm" type="submit" disabled={!viewName.trim()}>Save current filters</GlassButton>
                </form>
                {views.length ? <details className="text-xs text-text-2"><summary className="cursor-pointer">Manage saved views</summary>
                    {views.map((view) => <div key={view.name} className="mt-2 flex items-center gap-2"><span>{view.name}</span>
                        <GlassButton size="sm" aria-label={`Remove saved view ${view.name}`} onClick={() => persistViews(views.filter((item) => item.name !== view.name))}>Remove</GlassButton>
                    </div>)}</details> : null}
                {storageError ? <p role="alert" className="text-xs text-danger">{storageError}</p> : null}
            </div>
            <GlassPanel className="p-4">
                <h3 className="font-semibold text-text-1">Activity in this range</h3>
                {summaryError ? <p role="alert" className="mt-2 text-sm text-danger">{summaryError}</p> : !summary ? <p role="status" className="py-6 text-sm text-text-3">Loading summary...</p> : <>
                    <p className="mt-1 text-xs text-text-3">{summary.truncated
                        ? `Sampled: newest ${summary.sample_limit.toLocaleString()} matching records. Counts are not full-range totals.`
                        : `${summary.sample_size.toLocaleString()} matching records in this range.`} UTC buckets of {summary.bucket_days} day(s).</p>
                    <StatsChart ariaLabel="Matching activity by UTC date" signature={JSON.stringify(summary)} className="mt-3 h-40"
                        buildConfig={(theme) => ({
                            type: 'bar', data: { labels: summary.histogram.map((bin) => bin.date),
                                datasets: [{ label: 'Matching records', data: summary.histogram.map((bin) => bin.count), backgroundColor: '#4f8cff' }] },
                            options: cartesianOptions(theme, false),
                        })} />
                    <details className="mt-3 text-xs text-text-2"><summary className="cursor-pointer">Histogram data and date drill-through</summary>
                        <table className="mt-2 w-full text-left"><caption className="sr-only">Activity histogram data</caption><thead><tr><th scope="col">UTC bucket start</th><th scope="col">Records</th></tr></thead>
                            <tbody>{summary.histogram.map((bin) => <tr key={bin.date}><td>
                                <button type="button" className="py-1 text-accent underline" onClick={() => {
                                    const end = new Date(`${bin.date}T00:00:00Z`);
                                    end.setUTCDate(end.getUTCDate() + summary.bucket_days - 1);
                                    setParams(filterParams({ ...applied, start_date: bin.date, end_date: end.toISOString().slice(0, 10) < applied.end_date ? end.toISOString().slice(0, 10) : applied.end_date }));
                                }}>{bin.date}</button></td><td>{bin.count.toLocaleString()}</td></tr>)}</tbody>
                        </table>
                    </details>
                </>}
            </GlassPanel>
            <fieldset><legend className="mb-2 text-sm font-medium text-text-1">Activity types</legend>
                <div className="flex flex-wrap gap-2">{types.map((type) => (
                    <button key={type} type="button" aria-pressed={applied.activity_type.includes(type)} onClick={() => toggleType(type)}
                        className={clsx('rounded-full border px-3 py-1.5 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent',
                            applied.activity_type.includes(type) ? 'border-accent bg-accent-soft text-accent' : 'border-edge bg-surface-1 text-text-2 hover:bg-surface-2')}>
                        {type.replaceAll('_', ' ')}{counts.has(type) ? ` (${counts.get(type)?.toLocaleString()})` : ''}
                    </button>
                ))}</div>
            </fieldset>
            <div className="flex justify-between gap-3 text-xs text-text-3">
                <span>Newest first. Page {currentPaging.index + 1}{data ? ` · ${data.items.length} records` : ''}</span>
                <label>Density <select className="rounded border border-edge bg-surface-1 px-2 py-1 text-text-1" value={density} onChange={(event) => setDensity(event.target.value === 'compact' ? 'compact' : 'comfortable')}>
                    <option value="comfortable">Comfortable</option><option value="compact">Compact</option>
                </select></label>
            </div>
            <div className="overflow-hidden rounded-xl border border-edge">
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <caption className="sr-only">Activity logs in newest-first order</caption>
                        <thead className="bg-surface-2 text-xs text-text-3"><tr>{['UTC time', 'Activity', 'User', 'Workspace', 'Details'].map((label) => <th key={label} scope="col" className="px-4 py-3 font-medium">{label}</th>)}</tr></thead>
                        <tbody className="divide-y divide-edge text-text-2">
                            {loading ? <tr><td colSpan={5} className="p-8 text-center" role="status">Loading activity...</td></tr>
                                : error ? <tr><td colSpan={5} className="p-8 text-center text-danger" role="alert">{error} <button className="underline" onClick={() => setRefresh((value) => value + 1)}>Retry</button></td></tr>
                                    : !data?.items.length ? <tr><td colSpan={5} className="p-8 text-center">No activity matches these filters. Widen the dates or clear a filter.</td></tr>
                                        : data.items.map((record) => <tr key={JSON.stringify([record.timestamp, record.id, record.user_id, 'user_id' in record])} className="hover:bg-surface-2">
                                            <td className={`${cellClass} whitespace-nowrap tabular-nums`}>{record.timestamp.replace('T', ' ').replace(/\+00:00$|Z$/, '')}</td>
                                            <td className={cellClass}>{recordText(record, 'activity_type').replaceAll('_', ' ') || 'Unknown'}</td>
                                            <td className={`${cellClass} max-w-52 break-all`}>{recordUser(record) || 'Not recorded'}</td>
                                            <td className={`${cellClass} max-w-52 break-all`}>{recordText(record, 'workspace_type') || 'Not recorded'}{recordGroup(record) || recordWorkspace(record) ? <span className="block text-xs text-text-3">{recordGroup(record) || recordWorkspace(record)}</span> : null}</td>
                                            <td className={cellClass}><GlassButton size="sm" aria-label={`Inspect activity ${record.id}`} onClick={() => setSelected(record)}>Inspect</GlassButton></td>
                                        </tr>)}
                        </tbody>
                    </table>
                </div>
                <div className="flex justify-end gap-2 border-t border-edge px-4 py-3">
                    <GlassButton size="sm" disabled={loading || currentPaging.index === 0} onClick={() => setPaging({ ...currentPaging, index: currentPaging.index - 1 })}>Previous</GlassButton>
                    <GlassButton size="sm" disabled={loading || !data?.next_cursor} onClick={() => {
                        if (data?.next_cursor) setPaging({ query, cursors: [...currentPaging.cursors.slice(0, currentPaging.index + 1), data.next_cursor], index: currentPaging.index + 1 });
                    }}>Next</GlassButton>
                </div>
            </div>
            {selected ? <ActivityDetail record={selected} onClose={() => setSelected(null)} /> : null}
        </div>
    );
}
