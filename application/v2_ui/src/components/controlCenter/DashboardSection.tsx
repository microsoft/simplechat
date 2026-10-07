// DashboardSection.tsx
// Overview metrics and activity charts for the V2 Control Center.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Download, MessageSquareText, RefreshCw } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { cartesianOptions, StatsChart, type StatsChartConfigBuilder } from '../settings/StatsChart';
import { APPROVALS_URL, KpiCard } from './ControlCenterPrimitives';

type Metric = {
    value: number | null;
    delta: number | null;
    percent_change?: number | null;
    previous?: number;
    available?: boolean;
};

type DashboardSummary = {
    period: { start_date: string; end_date: string; days: number; timezone: string };
    refreshed_at: string;
    users: {
        total: Metric;
        active: Metric;
        dau: Metric;
        wau: Metric;
        mau: Metric;
        blocked: Metric;
    };
    groups: { total: Metric; by_status: Record<string, Metric> };
    public_workspaces: { total: Metric; by_status: Record<string, Metric> };
    conversations: Metric;
    document_uploads: { total: Metric; by_workspace_type: Record<string, Metric> };
    document_processing_failures: Metric;
    tokens: Metric;
    pending_approvals: Metric | null;
    status_history_available: boolean;
};

type ActivitySeries = Record<string, number>;
type UploadSeriesKey = 'personal_documents_created' | 'group_documents_created' | 'public_documents_created';

type ActivityTrends = {
    success: boolean;
    activity_data: {
        chats: ActivitySeries;
        logins: ActivitySeries;
        personal_documents_created: ActivitySeries;
        group_documents_created: ActivitySeries;
        public_documents_created: ActivitySeries;
        tokens: Record<string, Record<string, number>>;
    };
};

type RankedItem = { id: string; tokens?: number; activity_count?: number };

type DashboardInsights = {
    token_usage_by_model: { date: string; model: string; tokens: number }[];
    top_tokens: {
        users: RankedItem[];
        groups: RankedItem[];
        public_workspaces: RankedItem[];
    };
    top_activity: {
        users: RankedItem[];
        groups: RankedItem[];
        public_workspaces: RankedItem[];
    };
    login_heatmap: {
        weekday_convention: string;
        timezone: string;
        cells: { weekday: number; hour: number; count: number }[];
    };
};

type FilterOption = { id?: string; value?: string; label: string; name?: string; display_name?: string };
type TokenFilterOptions = {
    filters: {
        users: FilterOption[];
        groups: FilterOption[];
        public_workspaces: FilterOption[];
        models: FilterOption[];
        workspace_types: FilterOption[];
        token_types: FilterOption[];
    };
};

type TokenFilters = {
    user_id: string;
    workspace_type: string;
    group_id: string;
    public_workspace_id: string;
    model: string;
    token_type: string;
};

const EMPTY_FILTERS: TokenFilters = {
    user_id: '',
    workspace_type: '',
    group_id: '',
    public_workspace_id: '',
    model: '',
    token_type: '',
};

const CHART_COLORS = {
    blue: { border: '#4f8cff', fill: 'rgba(79, 140, 255, 0.24)' },
    cyan: { border: '#22b8cf', fill: 'rgba(34, 184, 207, 0.30)' },
    green: { border: '#37b679', fill: 'rgba(55, 182, 121, 0.28)' },
    amber: { border: '#e8a23a', fill: 'rgba(232, 162, 58, 0.28)' },
    purple: { border: '#a78bfa', fill: 'rgba(167, 139, 250, 0.28)' },
    rose: { border: '#f472b6', fill: 'rgba(244, 114, 182, 0.28)' },
};

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function rangeDates(days: number): { startDate: string; endDate: string } {
    const end = new Date();
    const endDate = end.toISOString().slice(0, 10);
    const start = new Date(`${endDate}T00:00:00.000Z`);
    start.setUTCDate(start.getUTCDate() - days + 1);
    return { startDate: start.toISOString().slice(0, 10), endDate };
}

function metricDetail(metric: Metric, days: number): string {
    if (metric.value === null || metric.available === false) {
        return 'Not available for this period';
    }
    if (metric.delta === null) {
        return 'Current status; historical status snapshots are not recorded';
    }
    if (metric.delta === 0) {
        return `No change vs the previous ${days}-day period`;
    }
    const direction = metric.delta > 0 ? '↑' : '↓';
    const percentage = metric.percent_change === null || metric.percent_change === undefined
        ? ''
        : ` (${Math.abs(metric.percent_change)}%)`;
    return `${direction} ${Math.abs(metric.delta).toLocaleString()} vs previous period${percentage}`;
}

function buildParams(
    startDate: string,
    endDate: string,
    filters: TokenFilters,
    forceRefresh = false,
): string {
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    Object.entries(filters).forEach(([key, value]) => {
        if (value) {
            params.set(key, value);
        }
    });
    if (forceRefresh) {
        params.set('force_refresh', '1');
    }
    return params.toString();
}

function seriesValues(series: ActivitySeries, dates: string[]): number[] {
    return dates.map((date) => Number(series[date] ?? 0));
}

function makeDatasets(series: { label: string; values: number[]; color: keyof typeof CHART_COLORS }[]) {
    return series.map(({ label, values, color }) => ({
        label,
        data: values,
        borderColor: CHART_COLORS[color].border,
        backgroundColor: CHART_COLORS[color].fill,
        borderWidth: 2,
        borderRadius: 3,
        pointRadius: 1,
        tension: 0.3,
    }));
}

function safeControlCenterHref(value: string): string {
    try {
        const url = new URL(value, window.location.origin);
        const isControlCenterPath = url.pathname === '/control-center'
            || url.pathname.startsWith('/control-center/');
        if (url.origin !== window.location.origin
            || (!isControlCenterPath && url.pathname !== '/approvals')) {
            return '/control-center';
        }
        return `${url.pathname}${url.search}${url.hash}`;
    } catch {
        return '/control-center';
    }
}

function MetricTile({
    label,
    metric,
    to,
    days,
    valueLabel,
}: {
    label: string;
    metric: Metric;
    to: string;
    days: number;
    valueLabel?: string;
}) {
    const value = metric.value === null || metric.available === false
        ? 'Not tracked'
        : valueLabel ?? metric.value.toLocaleString();
    return (
        <Link to={safeControlCenterHref(to)} className="block rounded-2xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            <KpiCard label={label} value={value} detail={metricDetail(metric, days)} />
        </Link>
    );
}

function ChartDataTable({
    title,
    dates,
    series,
}: {
    title: string;
    dates: string[];
    series: { label: string; values: number[] }[];
}) {
    return (
        <details className="mt-3 text-xs text-text-2">
            <summary className="cursor-pointer font-medium">View {title.toLowerCase()} as a data table</summary>
            <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-edge">
                <table className="w-full text-left">
                    <caption className="sr-only">{title} chart data by day</caption>
                    <thead className="bg-surface-2">
                        <tr>
                            <th scope="col" className="px-2 py-1">Date</th>
                            {series.map((item) => <th key={item.label} scope="col" className="px-2 py-1">{item.label}</th>)}
                        </tr>
                    </thead>
                    <tbody>
                        {dates.map((date, index) => (
                            <tr key={date} className="border-t border-edge">
                                <th scope="row" className="px-2 py-1 font-normal">{date}</th>
                                {series.map((item) => <td key={item.label} className="px-2 py-1">{item.values[index] ?? 0}</td>)}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </details>
    );
}

function ChartPanel({
    title,
    children,
}: {
    title: string;
    children: ReactNode;
}) {
    return (
        <section className="min-w-0 rounded-2xl border border-edge bg-surface-1 p-4">
            <h3 className="mb-3 text-sm font-semibold text-text-1">{title}</h3>
            {children}
        </section>
    );
}

function TokenFilterSelect({
    id,
    label,
    value,
    options,
    onChange,
}: {
    id: string;
    label: string;
    value: string;
    options: FilterOption[];
    onChange: (value: string) => void;
}) {
    return (
        <label className="min-w-36 flex-1 text-xs text-text-3" htmlFor={id}>
            {label}
            <select id={id} value={value} onChange={(event) => onChange(event.target.value)}
                className="mt-1 block w-full rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1">
                <option value="">All</option>
                {options.map((option) => {
                    const optionValue = option.id ?? option.value ?? '';
                    return <option key={optionValue} value={optionValue}>{option.label || option.name || option.display_name || optionValue}</option>;
                })}
            </select>
        </label>
    );
}

function RankedTable({
    title,
    rows,
    valueKey,
    section,
}: {
    title: string;
    rows: RankedItem[];
    valueKey: 'tokens' | 'activity_count';
    section: 'users' | 'groups' | 'public-workspaces';
}) {
    return (
        <div>
            <h4 className="mb-2 text-xs font-semibold text-text-2">{title}</h4>
            {rows.length === 0 ? (
                <p className="text-xs text-text-3">No activity recorded in this period.</p>
            ) : (
                <ol className="space-y-1 text-xs">
                    {rows.slice(0, 10).map((row, index) => (
                        <li key={row.id} className="flex items-center justify-between gap-3">
                            <Link className="min-w-0 truncate text-accent hover:underline"
                                to={`/control-center/${section}?${section === 'users' ? 'user_id' : 'id'}=${encodeURIComponent(row.id)}`}
                                title={row.id}>
                                {index + 1}. {row.id}
                            </Link>
                            <span className="shrink-0 text-text-2">{Number(row[valueKey] ?? 0).toLocaleString()}</span>
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}

export function DashboardSection() {
    const navigate = useNavigate();
    const [preset, setPreset] = useState<'7' | '30' | '90' | 'custom'>('30');
    const [customStart, setCustomStart] = useState(() => rangeDates(30).startDate);
    const [customEnd, setCustomEnd] = useState(() => rangeDates(30).endDate);
    const [filters, setFilters] = useState<TokenFilters>(EMPTY_FILTERS);
    const [filterOptions, setFilterOptions] = useState<TokenFilterOptions['filters'] | null>(null);
    const [summary, setSummary] = useState<DashboardSummary | null>(null);
    const [trends, setTrends] = useState<ActivityTrends | null>(null);
    const [insights, setInsights] = useState<DashboardInsights | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [filterError, setFilterError] = useState<string | null>(null);
    const [refreshVersion, setRefreshVersion] = useState(0);
    const handledRefreshVersion = useRef(0);
    const [action, setAction] = useState<'export' | 'chat' | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [chatUrl, setChatUrl] = useState<string | null>(null);

    const dates = useMemo(
        () => (preset === 'custom' ? { startDate: customStart, endDate: customEnd } : rangeDates(Number(preset))),
        [preset, customStart, customEnd],
    );
    const validRange = dates.startDate <= dates.endDate;
    const query = useMemo(
        () => buildParams(dates.startDate, dates.endDate, filters),
        [dates.startDate, dates.endDate, filters],
    );

    useEffect(() => {
        let cancelled = false;
        api.get<TokenFilterOptions>('/api/admin/control-center/token-filters')
            .then((response) => {
                if (!cancelled) {
                    setFilterOptions(response.filters);
                    setFilterError(null);
                }
            })
            .catch((requestError: unknown) => {
                if (!cancelled) {
                    setFilterError(requestError instanceof Error ? requestError.message : 'Token filter options could not be loaded.');
                }
            });
        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        if (!validRange) {
            setError('The start date must be on or before the end date.');
            setLoading(false);
            return;
        }
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        setChatUrl(null);
        const forceRefresh = refreshVersion > handledRefreshVersion.current;
        handledRefreshVersion.current = refreshVersion;
        const requestQuery = buildParams(dates.startDate, dates.endDate, filters, forceRefresh);
        const trendUrl = `/api/admin/control-center/activity-trends?${requestQuery}`;
        Promise.all([
            api.get<DashboardSummary>(`/api/v2/control-center/dashboard/summary?${requestQuery}`, controller.signal),
            api.get<ActivityTrends>(trendUrl, controller.signal),
            api.get<DashboardInsights>(`/api/v2/control-center/dashboard/insights?${requestQuery}`, controller.signal),
        ])
            .then(([summaryResponse, trendResponse, insightResponse]) => {
                setSummary(summaryResponse);
                setTrends(trendResponse);
                setInsights(insightResponse);
            })
            .catch((requestError: unknown) => {
                if (!controller.signal.aborted) {
                    setError(requestError instanceof Error ? requestError.message : 'Dashboard data could not be loaded.');
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setLoading(false);
                }
            });
        return () => controller.abort();
    }, [dates.endDate, dates.startDate, filters, query, refreshVersion, validRange]);

    const periodDays = summary?.period.days ?? Number(preset === 'custom' ? 30 : preset);
    const activity = trends?.activity_data;
    const trendDates = useMemo(() => Object.keys(activity?.chats ?? {}).sort(), [activity]);
    const tokensByDay = useMemo(() => activity?.tokens ?? {}, [activity]);
    const tokenDates = useMemo(() => Object.keys(tokensByDay).sort(), [tokensByDay]);
    const modelNames = useMemo(
        () => [...new Set((insights?.token_usage_by_model ?? []).map((row) => row.model))].sort(),
        [insights],
    );
    const modelDates = useMemo(
        () => [...new Set((insights?.token_usage_by_model ?? []).map((row) => row.date))].sort(),
        [insights],
    );
    const uploadSeries: { label: string; key: UploadSeriesKey; color: keyof typeof CHART_COLORS }[] = [
        { label: 'Personal', key: 'personal_documents_created', color: 'blue' },
        { label: 'Group', key: 'group_documents_created', color: 'cyan' },
        { label: 'Public', key: 'public_documents_created', color: 'green' },
    ];
    const tokenSeries = [
        { label: 'Chat', key: 'chat', color: 'blue' as const },
        { label: 'Embedding', key: 'embedding', color: 'green' as const },
        { label: 'Web search', key: 'web_search', color: 'amber' as const },
    ];

    const updateFilter = (key: keyof TokenFilters, value: string) => {
        setFilters((current) => ({ ...current, [key]: value }));
    };

    const navigateToActivity = (activityType: string, date?: string, extras: Record<string, string> = {}) => {
        const params = new URLSearchParams({ activity_type: activityType, ...extras });
        if (date) {
            params.set('date', date);
        }
        navigate(`/control-center/activity-logs?${params.toString()}`);
    };

    const exportTrends = async () => {
        setAction('export');
        setActionError(null);
        try {
            const response = await api.post<string>('/api/admin/control-center/activity-trends/export', {
                charts: ['logins', 'chats', 'personal_documents', 'group_documents', 'public_documents'],
                time_window: 'custom',
                start_date: dates.startDate,
                end_date: dates.endDate,
                token_filters: filters,
            });
            const url = URL.createObjectURL(new Blob([response], { type: 'text/csv;charset=utf-8' }));
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = `control-center-trends-${dates.startDate}-${dates.endDate}.csv`;
            anchor.click();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (requestError) {
            setActionError(requestError instanceof Error ? requestError.message : 'Trend export failed.');
        } finally {
            setAction(null);
        }
    };

    const chatWithTrends = async () => {
        setAction('chat');
        setActionError(null);
        setChatUrl(null);
        try {
            const response = await api.post<{ conversation_id: string }>(
                '/api/admin/control-center/activity-trends/chat',
                {
                    charts: ['logins', 'chats', 'documents'],
                    time_window: 'custom',
                    start_date: dates.startDate,
                    end_date: dates.endDate,
                    token_filters: filters,
                },
            );
            setChatUrl(`/chat/${encodeURIComponent(response.conversation_id)}`);
        } catch (requestError) {
            setActionError(requestError instanceof Error ? requestError.message : 'Could not create a trends chat.');
        } finally {
            setAction(null);
        }
    };

    const activityConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'line',
        data: {
            labels: trendDates,
            datasets: makeDatasets([
                { label: 'Conversations created', values: seriesValues(activity?.chats ?? {}, trendDates), color: 'blue' },
                { label: 'Logins', values: seriesValues(activity?.logins ?? {}, trendDates), color: 'amber' },
            ]),
        },
        options: {
            ...cartesianOptions(theme, true),
            onClick: (_event: unknown, elements: { index: number }[]) => {
                const date = trendDates[elements[0]?.index ?? -1];
                if (date) {
                    navigateToActivity('conversation_creation', date);
                }
            },
        },
    });

    const uploadConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: trendDates,
            datasets: makeDatasets(uploadSeries.map((series) => ({
                label: series.label,
                values: seriesValues(activity?.[series.key] ?? {}, trendDates),
                color: series.color,
            }))),
        },
        options: {
            ...cartesianOptions(theme, true),
            scales: {
                ...cartesianOptions(theme, true).scales,
                x: { ...cartesianOptions(theme, true).scales.x, stacked: true },
                y: { ...cartesianOptions(theme, true).scales.y, stacked: true },
            },
            onClick: (_event: unknown, elements: { index: number; datasetIndex: number }[]) => {
                const element = elements[0];
                const series = uploadSeries[element?.datasetIndex ?? -1];
                const date = trendDates[element?.index ?? -1];
                if (series && date) {
                    navigateToActivity('document_creation', date, {
                        workspace_type: series.key.startsWith('personal') ? 'personal' : series.key.startsWith('group') ? 'group' : 'public',
                    });
                }
            },
        },
    });

    const tokenConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: tokenDates,
            datasets: makeDatasets(tokenSeries.map((series) => ({
                label: series.label,
                values: tokenDates.map((date) => Number(tokensByDay[date]?.[series.key] ?? 0)),
                color: series.color,
            }))),
        },
        options: {
            ...cartesianOptions(theme, true),
            scales: {
                ...cartesianOptions(theme, true).scales,
                x: { ...cartesianOptions(theme, true).scales.x, stacked: true },
                y: { ...cartesianOptions(theme, true).scales.y, stacked: true },
            },
            onClick: (_event: unknown, elements: { index: number; datasetIndex: number }[]) => {
                const element = elements[0];
                const series = tokenSeries[element?.datasetIndex ?? -1];
                const date = tokenDates[element?.index ?? -1];
                if (series && date) {
                    navigateToActivity('token_usage', date, { token_type: series.key });
                }
            },
        },
    });

    const modelConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: modelDates,
            datasets: makeDatasets(modelNames.map((model, index) => ({
                label: model,
                values: modelDates.map((date) => (insights?.token_usage_by_model ?? [])
                    .filter((row) => row.date === date && row.model === model)
                    .reduce((total, row) => total + row.tokens, 0)),
                color: (Object.keys(CHART_COLORS) as (keyof typeof CHART_COLORS)[])[index % Object.keys(CHART_COLORS).length],
            }))),
        },
        options: {
            ...cartesianOptions(theme, true),
            scales: {
                ...cartesianOptions(theme, true).scales,
                x: { ...cartesianOptions(theme, true).scales.x, stacked: true },
                y: { ...cartesianOptions(theme, true).scales.y, stacked: true },
            },
            onClick: (_event: unknown, elements: { index: number; datasetIndex: number }[]) => {
                const element = elements[0];
                const model = modelNames[element?.datasetIndex ?? -1];
                const date = modelDates[element?.index ?? -1];
                if (model && date) {
                    navigateToActivity('token_usage', date, { model });
                }
            },
        },
    });

    const makeChartTable = (title: string, series: { label: string; values: number[] }[]) => (
        <ChartDataTable title={title} dates={trendDates} series={series} />
    );

    return (
        <div className="space-y-5 p-4 md:p-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                    <h2 className="text-xl font-semibold text-text-1">Dashboard</h2>
                    <p className="mt-1 text-sm text-text-2">Usage and activity for the selected UTC date range.</p>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                    <label htmlFor="dashboard-range" className="text-xs text-text-3">
                        Date range
                        <select id="dashboard-range" value={preset} onChange={(event) => setPreset(event.target.value as typeof preset)}
                            className="mt-1 block rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1">
                            <option value="7">Last 7 days</option>
                            <option value="30">Last 30 days</option>
                            <option value="90">Last 90 days</option>
                            <option value="custom">Custom</option>
                        </select>
                    </label>
                    {preset === 'custom' ? (
                        <>
                            <label htmlFor="dashboard-start-date" className="text-xs text-text-3">
                                Start
                                <input id="dashboard-start-date" type="date" value={customStart} onChange={(event) => setCustomStart(event.target.value)}
                                    className="mt-1 block rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1" />
                            </label>
                            <label htmlFor="dashboard-end-date" className="text-xs text-text-3">
                                End
                                <input id="dashboard-end-date" type="date" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)}
                                    className="mt-1 block rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1" />
                            </label>
                        </>
                    ) : null}
                    <button type="button" onClick={() => setRefreshVersion((current) => current + 1)} disabled={loading}
                        className="inline-flex items-center gap-2 rounded-lg border border-edge px-3 py-2 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-50">
                        <RefreshCw size={14} aria-hidden="true" /> Refresh
                    </button>
                    <button type="button" onClick={() => void exportTrends()} disabled={loading || action !== null}
                        className="inline-flex items-center gap-2 rounded-lg border border-edge px-3 py-2 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-50">
                        <Download size={14} aria-hidden="true" /> {action === 'export' ? 'Exporting…' : 'Export'}
                    </button>
                    <button type="button" onClick={() => void chatWithTrends()} disabled={loading || action !== null}
                        className="inline-flex items-center gap-2 rounded-lg border border-edge px-3 py-2 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-50">
                        <MessageSquareText size={14} aria-hidden="true" /> {action === 'chat' ? 'Creating chat…' : 'Chat with these trends'}
                    </button>
                </div>
            </div>

            {preset === 'custom' ? (
                <p className="text-xs text-text-3">Custom ranges can cover up to 366 days. All dates are interpreted as UTC.</p>
            ) : null}

            <section aria-label="Token usage filters" className="rounded-2xl border border-edge bg-surface-1 p-4">
                <h3 className="mb-3 text-sm font-semibold text-text-1">Token filters</h3>
                <div className="flex flex-wrap gap-3">
                    <TokenFilterSelect id="dashboard-filter-user" label="User" value={filters.user_id}
                        options={filterOptions?.users ?? []} onChange={(value) => updateFilter('user_id', value)} />
                    <TokenFilterSelect id="dashboard-filter-workspace-type" label="Workspace type" value={filters.workspace_type}
                        options={filterOptions?.workspace_types ?? []} onChange={(value) => updateFilter('workspace_type', value)} />
                    <TokenFilterSelect id="dashboard-filter-group" label="Group" value={filters.group_id}
                        options={filterOptions?.groups ?? []} onChange={(value) => updateFilter('group_id', value)} />
                    <TokenFilterSelect id="dashboard-filter-public-workspace" label="Public workspace" value={filters.public_workspace_id}
                        options={filterOptions?.public_workspaces ?? []} onChange={(value) => updateFilter('public_workspace_id', value)} />
                    <TokenFilterSelect id="dashboard-filter-model" label="Model" value={filters.model}
                        options={filterOptions?.models ?? []} onChange={(value) => updateFilter('model', value)} />
                    <TokenFilterSelect id="dashboard-filter-token-type" label="Token type" value={filters.token_type}
                        options={filterOptions?.token_types ?? []} onChange={(value) => updateFilter('token_type', value)} />
                </div>
                {filterError ? <p role="alert" className="mt-3 text-xs text-warn">{filterError} Token filters may be incomplete.</p> : null}
            </section>

            {actionError ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{actionError}</p> : null}
            {chatUrl ? <p role="status" className="rounded-xl bg-ok-soft p-3 text-sm text-ok">
                Trend chat created. <Link className="font-semibold underline" to={chatUrl}>Open conversation</Link>
            </p> : null}

            {error ? (
                <div role="alert" className="rounded-xl bg-danger-soft p-4 text-sm text-danger">
                    <p>{error}</p>
                    <button type="button" className="mt-2 font-semibold underline" onClick={() => setRefreshVersion((current) => current + 1)}>Try again</button>
                </div>
            ) : null}

            {loading && !summary ? (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Loading dashboard metrics" aria-busy="true">
                    {Array.from({ length: 9 }, (_, index) => (
                        <div key={index} className="h-24 animate-pulse rounded-2xl border border-edge bg-surface-2" />
                    ))}
                </div>
            ) : summary ? (
                <section aria-label="Dashboard metrics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    <MetricTile label="Total users" metric={summary.users.total} to="/control-center/users" days={periodDays} />
                    <MetricTile label="Active users" metric={summary.users.active} to="/control-center/users?filter=active" days={periodDays}
                        valueLabel={summary.users.active.value?.toLocaleString()} />
                    <MetricTile label="Blocked users" metric={summary.users.blocked} to="/control-center/users?status=blocked" days={periodDays} />
                    <MetricTile label="Groups" metric={summary.groups.total} to="/control-center/groups" days={periodDays}
                        valueLabel={`${summary.groups.total.value?.toLocaleString() ?? 0} total · ${summary.groups.by_status.active?.value ?? 0} active`} />
                    <MetricTile label="Public workspaces" metric={summary.public_workspaces.total} to="/control-center/public-workspaces" days={periodDays}
                        valueLabel={`${summary.public_workspaces.total.value?.toLocaleString() ?? 0} total · ${summary.public_workspaces.by_status.active?.value ?? 0} active`} />
                    <MetricTile label="Conversations created" metric={summary.conversations}
                        to={`/control-center/activity-logs?activity_type=conversation_creation&start_date=${summary.period.start_date}&end_date=${summary.period.end_date}`}
                        days={periodDays} />
                    <MetricTile label="Document uploads" metric={summary.document_uploads.total}
                        to={`/control-center/activity-logs?activity_type=document_creation&start_date=${summary.period.start_date}&end_date=${summary.period.end_date}`}
                        days={periodDays} />
                    <MetricTile label="Processing failures" metric={summary.document_processing_failures}
                        to={`/control-center/activity-logs?activity_type=document_creation&status=failed&start_date=${summary.period.start_date}&end_date=${summary.period.end_date}`}
                        days={periodDays} />
                    <MetricTile label="Tokens used" metric={summary.tokens}
                        to={`/control-center/activity-logs?activity_type=token_usage&start_date=${summary.period.start_date}&end_date=${summary.period.end_date}`}
                        days={periodDays} />
                    {summary.pending_approvals ? (
                        <MetricTile label="Pending approvals" metric={summary.pending_approvals} to={APPROVALS_URL} days={periodDays} />
                    ) : null}
                    <div className="rounded-2xl border border-edge bg-surface-1 p-4 sm:col-span-2 xl:col-span-3">
                        <p className="text-xs font-semibold text-text-2">Login activity</p>
                        <p className="mt-2 text-sm text-text-2">
                            DAU <strong className="text-text-1">{summary.users.dau.value?.toLocaleString() ?? '—'}</strong>
                            <span className="mx-3 text-text-3">·</span>
                            WAU <strong className="text-text-1">{summary.users.wau.value?.toLocaleString() ?? '—'}</strong>
                            <span className="mx-3 text-text-3">·</span>
                            MAU <strong className="text-text-1">{summary.users.mau.value?.toLocaleString() ?? '—'}</strong>
                            <span className="ml-2 text-xs text-text-3">(unique users, measured through the selected end date)</span>
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2">
                            {Object.entries(summary.groups.by_status).map(([status, metric]) => (
                                <Link key={`group-${status}`} to={`/control-center/groups?status=${encodeURIComponent(status)}`}
                                    className="rounded-full bg-surface-2 px-3 py-1 text-xs text-text-2">
                                    Groups {status.replace('_', ' ')}: {metric.value?.toLocaleString() ?? 0}
                                </Link>
                            ))}
                            {Object.entries(summary.public_workspaces.by_status).map(([status, metric]) => (
                                <Link key={`workspace-${status}`} to={`/control-center/public-workspaces?status=${encodeURIComponent(status)}`}
                                    className="rounded-full bg-surface-2 px-3 py-1 text-xs text-text-2">
                                    Workspaces {status.replace('_', ' ')}: {metric.value?.toLocaleString() ?? 0}
                                </Link>
                            ))}
                            {summary.pending_approvals ? (
                                <Link to={APPROVALS_URL} className="rounded-full bg-accent-soft px-3 py-1 text-xs text-accent">
                                    Pending approvals: {summary.pending_approvals.value?.toLocaleString() ?? 'Unavailable'}
                                </Link>
                            ) : null}
                        </div>
                    </div>
                </section>
            ) : null}

            {loading && summary ? <p role="status" className="text-xs text-text-3">Refreshing dashboard data…</p> : null}

            {trends && activity && trendDates.length > 0 ? (
                <section className="grid gap-4 lg:grid-cols-2" aria-label="Activity charts">
                    <ChartPanel title="Conversations and logins">
                        <StatsChart buildConfig={activityConfig} signature={`${query}-activity`}
                            ariaLabel="Daily conversation creation and login counts. Select a point to open filtered activity logs." />
                        {makeChartTable('Conversations and logins', [
                            { label: 'Conversations', values: seriesValues(activity.chats, trendDates) },
                            { label: 'Logins', values: seriesValues(activity.logins, trendDates) },
                        ])}
                    </ChartPanel>
                    <ChartPanel title="Document uploads by workspace">
                        <StatsChart buildConfig={uploadConfig} signature={`${query}-uploads`}
                            ariaLabel="Daily document creation counts, stacked by personal, group, and public workspace. Select a bar to open filtered activity logs." />
                        {makeChartTable('Document uploads by workspace', uploadSeries.map((series) => ({
                            label: series.label,
                            values: seriesValues(activity[series.key], trendDates),
                        })))}
                    </ChartPanel>
                    <ChartPanel title="Tokens by usage type">
                        <StatsChart buildConfig={tokenConfig} signature={`${query}-tokens`}
                            ariaLabel="Daily token counts stacked by chat, embedding, and web search usage." />
                        <ChartDataTable title="Token usage" dates={tokenDates} series={tokenSeries.map((series) => ({
                            label: series.label,
                            values: tokenDates.map((date) => Number(tokensByDay[date]?.[series.key] ?? 0)),
                        }))} />
                    </ChartPanel>
                    <ChartPanel title="Token usage by model">
                        {modelDates.length > 0 ? (
                            <>
                                <StatsChart buildConfig={modelConfig} signature={`${query}-models`}
                                    ariaLabel="Daily token usage by model, stacked. Select a bar to open filtered token activity logs." />
                                <ChartDataTable title="Token usage by model" dates={modelDates} series={modelNames.map((model) => ({
                                    label: model,
                                    values: modelDates.map((date) => (insights?.token_usage_by_model ?? [])
                                        .filter((row) => row.date === date && row.model === model)
                                        .reduce((total, row) => total + row.tokens, 0)),
                                }))} />
                            </>
                        ) : <p className="py-8 text-center text-sm text-text-3">No model-level token records for this period.</p>}
                    </ChartPanel>
                </section>
            ) : !loading && !error ? (
                <p className="rounded-xl border border-dashed border-edge p-8 text-center text-sm text-text-3">
                    No activity has been recorded for this date range.
                </p>
            ) : null}

            {insights && (insights.top_tokens.users.length > 0 || insights.login_heatmap.cells.length > 0) ? (
                <section className="grid gap-4 lg:grid-cols-2" aria-label="Additional usage insights">
                    <ChartPanel title="Top token consumers">
                        <div className="grid gap-4 sm:grid-cols-3">
                            <RankedTable title="Users" rows={insights.top_tokens.users} valueKey="tokens" section="users" />
                            <RankedTable title="Groups" rows={insights.top_tokens.groups} valueKey="tokens" section="groups" />
                            <RankedTable title="Public workspaces" rows={insights.top_tokens.public_workspaces} valueKey="tokens" section="public-workspaces" />
                        </div>
                    </ChartPanel>
                    <ChartPanel title="Top activity and login times">
                        <div className="grid gap-4 sm:grid-cols-3">
                            <RankedTable title="Users" rows={insights.top_activity.users} valueKey="activity_count" section="users" />
                            <RankedTable title="Groups" rows={insights.top_activity.groups} valueKey="activity_count" section="groups" />
                            <RankedTable title="Public workspaces" rows={insights.top_activity.public_workspaces} valueKey="activity_count" section="public-workspaces" />
                        </div>
                        <div className="mt-5 overflow-x-auto">
                            <table className="w-full text-center text-[10px] text-text-3">
                                <caption className="mb-2 text-left text-xs font-medium text-text-2">
                                    Logins by weekday and hour (UTC; Monday = 0)
                                </caption>
                                <thead>
                                    <tr>
                                        <th scope="col" className="px-1 py-1 text-left">Weekday</th>
                                        {Array.from({ length: 24 }, (_, hour) => <th key={hour} scope="col" className="px-1 py-1">{hour}</th>)}
                                    </tr>
                                </thead>
                                <tbody>
                                    {WEEKDAYS.map((weekday, dayIndex) => (
                                        <tr key={weekday}>
                                            <th scope="row" className="px-1 py-1 text-left">{weekday}</th>
                                            {Array.from({ length: 24 }, (_, hour) => {
                                                const count = insights.login_heatmap.cells.find((cell) => cell.weekday === dayIndex && cell.hour === hour)?.count ?? 0;
                                                return <td key={hour} className={count ? 'rounded bg-accent-soft px-1 py-1 text-accent' : 'px-1 py-1'}
                                                    aria-label={`${weekday} ${hour}:00 UTC: ${count} logins`}>
                                                    {count || '·'}
                                                </td>;
                                            })}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </ChartPanel>
                </section>
            ) : null}

            {summary?.refreshed_at ? <p className="text-right text-xs text-text-3">Updated {new Date(summary.refreshed_at).toLocaleString()}</p> : null}
        </div>
    );
}
