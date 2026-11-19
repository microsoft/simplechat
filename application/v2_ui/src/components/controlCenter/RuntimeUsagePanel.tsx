// RuntimeUsagePanel.tsx
// Recorded invocation metadata, kept inside the existing Activity Logs permission boundary.

import { useEffect, useMemo, useState } from 'react';
import { api, apiUrl } from '../../lib/apiClient';
import { apiParams, humanize, USAGE_FILTER_KEYS, type ActivityFilters } from '../../lib/activityLogs';
import { GlassButton } from '../ui/primitives';

interface UsageTotal {
    invocations: number;
    unique_users: number;
    outcomes: Record<string, number>;
    average_duration_ms: number | null;
    duration_count: number;
    legacy_records: number;
}

interface UsageEntity extends UsageTotal {
    kind: string;
    entity_id: string;
    name: string;
    scope_type: string;
    scope_id: string;
    entity_type: string;
    endpoint_host: string;
    auth_type: string;
    operation: string;
}

interface UsageReport {
    totals: Record<string, UsageTotal>;
    entities: UsageEntity[];
    complete: boolean;
    recorded_at: string;
    cache_seconds: number;
}

const textFilters = [
    ['usage_entity_id', 'Entity ID'], ['usage_scope_type', 'Configuration scope'],
    ['usage_scope_id', 'Configuration scope ID'], ['usage_host', 'Configured host'],
    ['usage_auth', 'Authentication category'], ['usage_operation', 'Operation'],
] as const;
const FIELD = 'mt-1 h-9 w-full rounded-lg border border-edge bg-surface-1 px-2.5 text-sm text-text-1 focus:border-accent focus:outline-none';

export function RuntimeUsagePanel({ filters, onChange, refresh }: {
    filters: ActivityFilters;
    onChange: (filters: ActivityFilters) => void;
    refresh: number;
}) {
    const [expanded, setExpanded] = useState(false);
    const [report, setReport] = useState<UsageReport | null>(null);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    const [page, setPage] = useState(0);
    const [draft, setDraft] = useState(filters);
    const query = useMemo(() => {
        const params = apiParams(filters);
        for (const key of ['activity_type', 'search', 'token_type', 'model', 'status']) params.delete(key);
        return params.toString();
    }, [filters]);
    useEffect(() => { setDraft(filters); setPage(0); }, [filters]);
    useEffect(() => {
        if (!expanded) return;
        const controller = new AbortController();
        setReport(null);
        setError('');
        api.get<UsageReport>(`/api/v2/control-center/activity-logs/usage?${query}&refresh=true`, controller.signal)
            .then((result) => {
                if (!controller.signal.aborted) {
                    if (!result.complete) setError('Usage is incomplete. Narrow the date range.');
                    else setReport(result);
                }
            })
            .catch((failure: unknown) => {
                if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Unable to load usage. Retry.');
            });
        return () => controller.abort();
    }, [query, expanded, refresh, revision]);
    const set = (key: keyof ActivityFilters, value: string) => setDraft((previous) => ({ ...previous, [key]: value }));
    const drill = (entity: UsageEntity) => {
        onChange({
            ...filters, activity_type: [`${entity.kind}_run`], search: '', model: '', token_type: '', status: '',
            usage_kind: entity.kind, usage_entity_id: entity.entity_id,
            usage_scope_type: entity.scope_type, usage_scope_id: entity.scope_id,
            usage_host: entity.endpoint_host, usage_auth: entity.auth_type, usage_operation: entity.operation,
        });
    };
    return (
        <section className="rounded-xl border border-edge bg-surface-1 p-3" aria-labelledby="runtime-usage-heading">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 id="runtime-usage-heading" className="font-semibold text-text-1">Agent, action &amp; workflow usage</h3>
                <GlassButton size="sm" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
                    {expanded ? 'Hide usage' : 'Show usage'}
                </GlassButton>
            </div>
            {expanded ? <div className="mt-3 space-y-3">
                <p className="max-w-prose text-sm text-text-2">
                    Recorded completed attempts, including retries. Uses the date, person, workspace and usage filters;
                    log search and token filters do not apply. No prompts, inputs, outputs or credentials.
                </p>
                <form className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => {
                    event.preventDefault();
                    const next = { ...filters };
                    for (const key of USAGE_FILTER_KEYS) next[key] = draft[key] ?? '';
                    onChange(next);
                }}>
                    <label className="text-sm text-text-1" htmlFor="runtime-usage-kind">Entity kind
                        <select id="runtime-usage-kind" aria-label="Entity kind" className={FIELD} value={draft.usage_kind ?? ''}
                            onChange={(event) => set('usage_kind', event.target.value)}>
                            <option value="">All kinds</option>
                            {['agent', 'action', 'workflow'].map((kind) => <option key={kind} value={kind}>{humanize(kind)}</option>)}
                        </select>
                    </label>
                    <label className="text-sm text-text-1" htmlFor="runtime-usage-outcome">Outcome
                        <select id="runtime-usage-outcome" aria-label="Outcome" className={FIELD} value={draft.usage_outcome ?? ''}
                            onChange={(event) => set('usage_outcome', event.target.value)}>
                            <option value="">All outcomes</option>
                            {['succeeded', 'failed', 'cancelled', 'timeout', 'partial', 'unknown'].map((value) =>
                                <option key={value} value={value}>{humanize(value)}</option>)}
                        </select>
                    </label>
                    {textFilters.map(([key, label]) => <label key={key} className="text-sm text-text-1">{label}
                        <input className={FIELD} maxLength={256}
                            value={draft[key] ?? ''} onChange={(event) => set(key, event.target.value)} />
                    </label>)}
                    <div className="col-span-full flex flex-wrap gap-2">
                        <GlassButton type="submit" size="sm">Apply usage filters</GlassButton>
                        <GlassButton size="sm" onClick={() => {
                            const next = { ...filters };
                            for (const key of USAGE_FILTER_KEYS) next[key] = '';
                            onChange(next);
                        }}>Clear usage filters</GlassButton>
                        <GlassButton size="sm" onClick={() => setRevision((value) => value + 1)}>Reload usage</GlassButton>
                    </div>
                </form>
                {error ? <p role="alert" className="text-sm text-danger">{error}</p> : !report ? <p role="status">Loading usage...</p> : <>
                    <dl className="flex flex-wrap gap-x-8 gap-y-3 text-sm text-text-1">
                        {Object.entries(report.totals).map(([kind, total]) => <div key={kind}>
                            <dt className="font-semibold">{humanize(kind)} attempts</dt>
                            <dd>{total.invocations.toLocaleString()} · {total.unique_users.toLocaleString()} distinct users</dd>
                            <dd>{Object.entries(total.outcomes).map(([key, count]) => `${humanize(key)}: ${count}`).join(' · ') || 'No outcomes'}</dd>
                        </div>)}
                    </dl>
                    <p className="text-sm text-text-2">
                        Missing historical metadata is unknown, not zero or no authentication. Durations overlap for nested calls.
                        Updated {new Date(report.recorded_at).toLocaleString()}.
                    </p>
                    <a className="inline-block text-sm text-accent underline" href={apiUrl(`/api/v2/control-center/activity-logs/usage?${query}&format=csv`)}>
                        Export usage CSV
                    </a>
                    {!report.entities.length ? <p>No recorded usage matches these filters.</p> : <div className="overflow-x-auto">
                        <table className="w-full min-w-[960px] text-left text-sm text-text-1">
                            <caption className="sr-only">Ranked recorded runtime usage</caption>
                            <thead><tr>{['Entity', 'Host / authentication', 'Operation', 'Attempts / users', 'Outcomes', 'Average duration', 'Coverage', 'Events'].map((label) =>
                                <th key={label} scope="col" className="p-2 font-semibold">{label}</th>)}</tr></thead>
                            <tbody>{report.entities.slice(page * 20, (page + 1) * 20).map((entity, index) => <tr key={index} className="border-t border-edge">
                                <td className="max-w-64 break-words p-2">{entity.name}<br /><span className="text-text-2">{entity.kind} · {entity.scope_type}: {entity.scope_id || 'unknown'}<br />{entity.entity_id}</span></td>
                                <td className="max-w-48 break-words p-2">{entity.endpoint_host}<br />{entity.auth_type}</td>
                                <td className="max-w-48 break-words p-2">{entity.operation}</td>
                                <td className="p-2">{entity.invocations} / {entity.unique_users}</td>
                                <td className="p-2">{Object.entries(entity.outcomes).map(([key, count]) => `${key}: ${count}`).join(', ')}</td>
                                <td className="p-2">{entity.average_duration_ms === null ? 'Unknown' : `${entity.average_duration_ms.toLocaleString()} ms`}</td>
                                <td className="p-2">{entity.duration_count} timed; {entity.legacy_records} legacy</td>
                                <td className="p-2"><GlassButton size="sm" onClick={() => drill(entity)}>View events</GlassButton></td>
                            </tr>)}</tbody>
                        </table>
                        <div className="mt-2 flex items-center gap-3">
                            <GlassButton size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous entities</GlassButton>
                            <span>Page {page + 1} of {Math.ceil(report.entities.length / 20)}</span>
                            <GlassButton size="sm" disabled={(page + 1) * 20 >= report.entities.length} onClick={() => setPage(page + 1)}>Next entities</GlassButton>
                        </div>
                    </div>}
                </>}
            </div> : null}
        </section>
    );
}
