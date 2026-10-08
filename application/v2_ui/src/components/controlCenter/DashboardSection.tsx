// DashboardSection.tsx
// THESIS: Answer "how is SimpleChat being used?" in the order an operator asks it.
// OWN-WORLD: Inherit the Control Center's semantic glass surfaces, compact workhorse type, and blue accent.
// STORY: Today's directory, then who signed in, what they created, what it cost, and who did the most.
// FIRST VIEWPORT: The date range and actions lead; each section pairs its figures with the charts behind them.
// FORM: Operate; sections are separated by headings and space, and every filter sits beside what it changes.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Download, RefreshCw } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { cartesianOptions, StatsChart, type StatsChartConfigBuilder } from '../settings/StatsChart';
import { GlassPanel } from '../ui/primitives';
import { APPROVALS_URL } from './ControlCenterPrimitives';
import { DashboardChatButton } from './DashboardChat';

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
};

type DailyActivityRow = {
    date: string;
    sign_ins: number;
    conversations_created: number;
    uploads_personal: number;
    uploads_group: number;
    uploads_public: number;
};

type TokenTypeRow = { date: string; chat: number; embedding: number; web_search: number };

type RankedItem = {
    id: string;
    name?: string;
    detail?: string;
    found?: boolean;
    tokens?: number;
    activity_count?: number;
};

type Rankings = { users: RankedItem[]; groups: RankedItem[]; public_workspaces: RankedItem[] };

type DashboardInsights = {
    refreshed_at?: string;
    daily_activity: DailyActivityRow[];
    token_usage_by_type: TokenTypeRow[];
    token_usage_by_model: { date: string; model: string; tokens: number }[];
    top_tokens: Rankings;
    top_activity: Rankings;
    login_heatmap: { cells: { weekday: number; hour: number; count: number }[] };
};

type FilterOption = { id?: string; value?: string; label?: string; name?: string; display_name?: string };
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
type ChartColor = keyof typeof CHART_COLORS;
type ChartElement = { index: number; datasetIndex: number };
type ClickableChart = {
    getElementsAtEventForMode?: (event: unknown, mode: string, options: { intersect: boolean }, useFinalPosition: boolean) => ChartElement[];
};
type EntitySection = 'users' | 'groups' | 'public-workspaces';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const UPLOAD_SERIES: { label: string; key: keyof DailyActivityRow; color: ChartColor; workspaceType: string }[] = [
    { label: 'Personal', key: 'uploads_personal', color: 'blue', workspaceType: 'personal' },
    { label: 'Group', key: 'uploads_group', color: 'cyan', workspaceType: 'group' },
    { label: 'Public', key: 'uploads_public', color: 'green', workspaceType: 'public' },
];
const TOKEN_SERIES: { label: string; key: keyof Omit<TokenTypeRow, 'date'>; color: ChartColor }[] = [
    { label: 'Chat', key: 'chat', color: 'blue' },
    { label: 'Embedding', key: 'embedding', color: 'green' },
    { label: 'Web search', key: 'web_search', color: 'amber' },
];
const STATUS_LABELS: Record<string, string> = {
    active: 'Active',
    locked: 'Locked',
    upload_disabled: 'Uploads disabled',
    inactive: 'Inactive',
};

function rangeDates(days: number): { startDate: string; endDate: string } {
    const end = new Date();
    const endDate = end.toISOString().slice(0, 10);
    const start = new Date(`${endDate}T00:00:00.000Z`);
    start.setUTCDate(start.getUTCDate() - days + 1);
    return { startDate: start.toISOString().slice(0, 10), endDate };
}

const DAY_FORMAT = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });

/** A UTC calendar date as people read it, such as "Oct 7, 2026". */
function formatDay(day: string): string {
    const parsed = new Date(`${day}T00:00:00Z`);
    return Number.isNaN(parsed.getTime()) ? day : DAY_FORMAT.format(parsed);
}

function formatNumber(value: number | null | undefined): string {
    return Number(value ?? 0).toLocaleString();
}

function comparisonText(metric: Metric, days: number): string | null {
    if (metric.value === null || metric.available === false || metric.delta === null) {
        return null;
    }
    if (metric.delta === 0) {
        return `Same as the previous ${days} days`;
    }
    const direction = metric.delta > 0 ? 'Up' : 'Down';
    const percentage = metric.percent_change === null || metric.percent_change === undefined
        ? ''
        : ` (${Math.abs(metric.percent_change)}%)`;
    return `${direction} ${Math.abs(metric.delta).toLocaleString()}${percentage} from the previous ${days} days`;
}

function buildParams(startDate: string, endDate: string, filters: TokenFilters, forceRefresh = false): string {
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

function makeDatasets(series: { label: string; values: number[]; color: ChartColor }[]) {
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

function stackedOptions(theme: Parameters<typeof cartesianOptions>[0]) {
    const base = cartesianOptions(theme, true);
    return {
        ...base,
        scales: {
            ...base.scales,
            x: { ...base.scales.x, stacked: true },
            y: { ...base.scales.y, stacked: true },
        },
    };
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

function optionLabel(options: FilterOption[] | undefined, value: string): string {
    const option = options?.find((item) => (item.id ?? item.value ?? '') === value);
    return option?.label || option?.name || option?.display_name || value;
}

function DashboardBlock({
    id,
    title,
    description,
    children,
}: {
    id: string;
    title: string;
    description: string;
    children: ReactNode;
}) {
    return (
        <section aria-labelledby={`${id}-title`} className="space-y-3">
            <div>
                <h3 id={`${id}-title`} className="text-base font-semibold text-text-1">{title}</h3>
                <p className="mt-0.5 text-sm text-text-2">{description}</p>
            </div>
            {children}
        </section>
    );
}

function MetricTile({
    label,
    value,
    comparison,
    definition,
    to,
    children,
}: {
    label: string;
    value: string;
    comparison?: string | null;
    definition?: string;
    to?: string | null;
    /** Extra content, such as status links. With children, only the label links to `to`. */
    children?: ReactNode;
}) {
    const href = to ? safeControlCenterHref(to) : null;
    const labelLinked = Boolean(href && children);
    const body = (
        <GlassPanel className="h-full p-4">
            <p className="text-xs font-medium text-text-2">
                {labelLinked && href ? <Link to={href} className="text-accent hover:underline">{label}</Link> : label}
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-text-1">{value}</p>
            {comparison ? <p className="mt-1 text-xs text-text-2">{comparison}</p> : null}
            {definition ? <p className="mt-2 text-xs leading-snug text-text-3">{definition}</p> : null}
            {children}
        </GlassPanel>
    );
    if (!href || labelLinked) {
        return <div className="h-full">{body}</div>;
    }
    return (
        <Link to={href}
            className="block h-full rounded-2xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            {body}
        </Link>
    );
}

function ChartPanel({ title, children }: { title: string; children: ReactNode }) {
    return (
        <div className="min-w-0 rounded-2xl border border-edge bg-surface-1 p-4">
            <h4 className="mb-3 text-sm font-semibold text-text-1">{title}</h4>
            {children}
        </div>
    );
}

function EmptyChart({ children }: { children: ReactNode }) {
    return <p className="flex h-40 items-center justify-center text-center text-sm text-text-3">{children}</p>;
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
            <summary className="cursor-pointer font-medium">View {title.toLowerCase()} as a table</summary>
            <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-edge">
                <table className="w-full text-left">
                    <caption className="sr-only">{title} by UTC day</caption>
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
                                {series.map((item) => (
                                    <td key={item.label} className="px-2 py-1 tabular-nums">{formatNumber(item.values[index])}</td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </details>
    );
}

function RankedList({
    title,
    rows,
    valueKey,
    unit,
    section,
}: {
    title: string;
    rows: RankedItem[];
    valueKey: 'tokens' | 'activity_count';
    unit: string;
    /** The Control Center section that manages these entities, or null when the viewer cannot open it. */
    section: EntitySection | null;
}) {
    return (
        <div className="min-w-0">
            <h5 className="mb-2 text-xs font-semibold text-text-2">{title}</h5>
            {rows.length === 0 ? (
                <p className="text-xs text-text-3">Nothing recorded in this range.</p>
            ) : (
                <ol className="space-y-2 text-sm">
                    {rows.slice(0, 10).map((row, index) => {
                        const name = row.name || row.id;
                        return (
                            <li key={row.id} className="flex items-start justify-between gap-3">
                                <span className="flex min-w-0 gap-2">
                                    <span aria-hidden="true" className="w-4 shrink-0 text-right text-xs tabular-nums text-text-3">{index + 1}</span>
                                    <span className="min-w-0">
                                        {section && row.found !== false ? (
                                            <Link className="block truncate text-accent hover:underline" title={`ID ${row.id}`}
                                                to={`/control-center/${section}?${section === 'users' ? 'user_id' : 'id'}=${encodeURIComponent(row.id)}`}>
                                                {name}
                                            </Link>
                                        ) : (
                                            <span className={row.found === false ? 'block truncate text-text-3' : 'block truncate text-text-1'}
                                                title={`ID ${row.id}`}>
                                                {name}
                                            </span>
                                        )}
                                        {row.detail ? <span className="block truncate text-xs text-text-3">{row.detail}</span> : null}
                                    </span>
                                </span>
                                <span className="shrink-0 text-xs tabular-nums text-text-2">
                                    {formatNumber(row[valueKey])}<span className="sr-only"> {unit}</span>
                                </span>
                            </li>
                        );
                    })}
                </ol>
            )}
        </div>
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
        <div className="min-w-40 flex-1">
            <label className="block text-xs text-text-2" htmlFor={id}>{label}</label>
            <select id={id} value={value} onChange={(event) => onChange(event.target.value)}
                className="mt-1 block w-full rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1">
                <option value="">All</option>
                {options.map((option) => {
                    const optionValue = option.id ?? option.value ?? '';
                    return <option key={optionValue} value={optionValue}>{option.label || option.name || option.display_name || optionValue}</option>;
                })}
            </select>
        </div>
    );
}

function LoginHeatmap({ cells }: { cells: { weekday: number; hour: number; count: number }[] }) {
    const counts = new Map(cells.map((cell) => [`${cell.weekday}-${cell.hour}`, cell.count]));
    const busiest = Math.max(0, ...cells.map((cell) => cell.count));
    const shade = (count: number) => {
        if (!count || !busiest) return 'text-text-3';
        const share = count / busiest;
        if (share > 0.66) return 'rounded bg-accent text-on-accent';
        if (share > 0.33) return 'rounded bg-accent-soft text-accent font-semibold';
        return 'rounded bg-accent-soft text-accent';
    };
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-center text-[10px] text-text-3">
                <caption className="sr-only">Sign-ins by weekday and hour, UTC</caption>
                <thead>
                    <tr>
                        <th scope="col" className="px-1 py-1 text-left">Weekday</th>
                        {Array.from({ length: 24 }, (_, hour) => <th key={hour} scope="col" className="px-1 py-1 tabular-nums">{hour}</th>)}
                    </tr>
                </thead>
                <tbody>
                    {WEEKDAYS.map((weekday, dayIndex) => (
                        <tr key={weekday}>
                            <th scope="row" className="px-1 py-1 text-left font-normal text-text-2">{weekday.slice(0, 3)}</th>
                            {Array.from({ length: 24 }, (_, hour) => {
                                const count = counts.get(`${dayIndex}-${hour}`) ?? 0;
                                return (
                                    <td key={hour} className={`px-1 py-1 tabular-nums ${shade(count)}`}
                                        aria-label={`${weekday} ${hour}:00 UTC: ${count} sign-ins`}>
                                        {count || '·'}
                                    </td>
                                );
                            })}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

export function DashboardSection() {
    const navigate = useNavigate();
    const capabilities = useBootstrapStore((state) => state.data?.control_center);
    const [preset, setPreset] = useState<'7' | '30' | '90' | 'custom'>('30');
    const [customStart, setCustomStart] = useState(() => rangeDates(30).startDate);
    const [customEnd, setCustomEnd] = useState(() => rangeDates(30).endDate);
    const [filters, setFilters] = useState<TokenFilters>(EMPTY_FILTERS);
    const [filterOptions, setFilterOptions] = useState<TokenFilterOptions['filters'] | null>(null);
    const [summary, setSummary] = useState<DashboardSummary | null>(null);
    const [insights, setInsights] = useState<DashboardInsights | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [filterError, setFilterError] = useState<string | null>(null);
    const [refreshVersion, setRefreshVersion] = useState(0);
    const handledRefreshVersion = useRef(0);
    const [exporting, setExporting] = useState(false);
    const [actionError, setActionError] = useState<string | null>(null);

    const canViewLogs = Boolean(capabilities?.can_view_activity_logs);
    const canManageUsers = Boolean(capabilities?.can_manage_users);
    const canManageGroups = Boolean(capabilities?.can_manage_groups);
    const canManageWorkspaces = Boolean(capabilities?.can_manage_workspaces);

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
        const forceRefresh = refreshVersion > handledRefreshVersion.current;
        handledRefreshVersion.current = refreshVersion;
        const requestQuery = buildParams(dates.startDate, dates.endDate, filters, forceRefresh);
        Promise.all([
            api.get<DashboardSummary>(`/api/v2/control-center/dashboard/summary?${requestQuery}`, controller.signal),
            api.get<DashboardInsights>(`/api/v2/control-center/dashboard/insights?${requestQuery}`, controller.signal),
        ])
            .then(([summaryResponse, insightResponse]) => {
                setSummary(summaryResponse);
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
    const startDay = summary?.period.start_date ?? dates.startDate;
    const endDay = summary?.period.end_date ?? dates.endDate;
    const daily = useMemo(() => insights?.daily_activity ?? [], [insights]);
    const dailyDates = useMemo(() => daily.map((row) => row.date), [daily]);
    const tokenDays = useMemo(() => insights?.token_usage_by_type ?? [], [insights]);
    const tokenDates = useMemo(() => tokenDays.map((row) => row.date), [tokenDays]);
    const modelNames = useMemo(
        () => [...new Set((insights?.token_usage_by_model ?? []).map((row) => row.model))].sort(),
        [insights],
    );
    const modelDates = useMemo(
        () => [...new Set((insights?.token_usage_by_model ?? []).map((row) => row.date))].sort(),
        [insights],
    );
    const modelTotals = useMemo(() => {
        const totals = new Map<string, number>();
        (insights?.token_usage_by_model ?? []).forEach((row) => {
            const key = `${row.date}|${row.model}`;
            totals.set(key, (totals.get(key) ?? 0) + row.tokens);
        });
        return totals;
    }, [insights]);
    const filtersActive = Object.values(filters).some(Boolean);

    const tokenFilterDescriptions = useMemo(() => {
        const described: string[] = [];
        if (filters.user_id) described.push(`user ${optionLabel(filterOptions?.users, filters.user_id)}`);
        if (filters.workspace_type) described.push(`${optionLabel(filterOptions?.workspace_types, filters.workspace_type).toLowerCase()} workspaces`);
        if (filters.group_id) described.push(`group ${optionLabel(filterOptions?.groups, filters.group_id)}`);
        if (filters.public_workspace_id) described.push(`public workspace ${optionLabel(filterOptions?.public_workspaces, filters.public_workspace_id)}`);
        if (filters.model) described.push(`model ${filters.model}`);
        if (filters.token_type) described.push(`${optionLabel(filterOptions?.token_types, filters.token_type).toLowerCase()} tokens`);
        return described;
    }, [filters, filterOptions]);

    const updateFilter = (key: keyof TokenFilters, value: string) => {
        setFilters((current) => ({ ...current, [key]: value }));
    };

    const activityLogsHref = (activityType: string, extras: Record<string, string> = {}) => {
        const params = new URLSearchParams({ activity_type: activityType, ...extras });
        return `/control-center/activity-logs?${params.toString()}`;
    };

    const tokenLogExtras = (): Record<string, string> => {
        const extras: Record<string, string> = {};
        Object.entries(filters).forEach(([key, value]) => {
            if (value) {
                extras[key] = value;
            }
        });
        return extras;
    };

    const openActivityLogs = (activityType: string, date: string | undefined, extras: Record<string, string> = {}) => {
        if (!canViewLogs || !date) {
            return;
        }
        navigate(safeControlCenterHref(activityLogsHref(activityType, { date, ...extras })));
    };

    const exportTrends = async () => {
        setExporting(true);
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
            setExporting(false);
        }
    };

    // The charts hover by index, so the elements Chart.js passes to onClick are every series at
    // that date. Ask for the segment actually under the pointer; a click beside a stack (or on a
    // single-series chart) opens the logs for the whole day instead of an arbitrary series.
    const clickHandler = (handler: (index: number, datasetIndex: number | null) => void) => (
        canViewLogs
            ? (event: unknown, elements: ChartElement[], chart?: ClickableChart) => {
                const precise = chart?.getElementsAtEventForMode?.(event, 'nearest', { intersect: true }, true) ?? [];
                if (precise[0]) {
                    handler(precise[0].index, precise[0].datasetIndex);
                } else if (elements[0]) {
                    handler(elements[0].index, null);
                }
            }
            : undefined
    );

    const signInConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'line',
        data: {
            labels: dailyDates,
            datasets: makeDatasets([{ label: 'Sign-ins', values: daily.map((row) => row.sign_ins), color: 'amber' }]),
        },
        options: {
            ...cartesianOptions(theme, false),
            onClick: clickHandler((index) => openActivityLogs('user_login', dailyDates[index])),
        },
    });

    const conversationConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: dailyDates,
            datasets: makeDatasets([
                { label: 'Conversations created', values: daily.map((row) => row.conversations_created), color: 'blue' },
            ]),
        },
        options: {
            ...cartesianOptions(theme, false),
            onClick: clickHandler((index) => openActivityLogs('conversation_creation', dailyDates[index])),
        },
    });

    const uploadConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: dailyDates,
            datasets: makeDatasets(UPLOAD_SERIES.map((series) => ({
                label: series.label,
                values: daily.map((row) => Number(row[series.key] ?? 0)),
                color: series.color,
            }))),
        },
        options: {
            ...stackedOptions(theme),
            onClick: clickHandler((index, datasetIndex) => {
                const series = datasetIndex === null ? undefined : UPLOAD_SERIES[datasetIndex];
                openActivityLogs('document_creation', dailyDates[index],
                    series ? { workspace_type: series.workspaceType } : {});
            }),
        },
    });

    const tokenConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: tokenDates,
            datasets: makeDatasets(TOKEN_SERIES.map((series) => ({
                label: series.label,
                values: tokenDays.map((row) => Number(row[series.key] ?? 0)),
                color: series.color,
            }))),
        },
        options: {
            ...stackedOptions(theme),
            onClick: clickHandler((index, datasetIndex) => {
                const series = datasetIndex === null ? undefined : TOKEN_SERIES[datasetIndex];
                openActivityLogs('token_usage', tokenDates[index],
                    series ? { ...tokenLogExtras(), token_type: series.key } : tokenLogExtras());
            }),
        },
    });

    const modelValues = (model: string) => modelDates.map((date) => modelTotals.get(`${date}|${model}`) ?? 0);
    const modelConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: modelDates,
            datasets: makeDatasets(modelNames.map((model, index) => ({
                label: model,
                values: modelValues(model),
                color: (Object.keys(CHART_COLORS) as ChartColor[])[index % Object.keys(CHART_COLORS).length],
            }))),
        },
        options: {
            ...stackedOptions(theme),
            onClick: clickHandler((index, datasetIndex) => {
                const model = datasetIndex === null ? undefined : modelNames[datasetIndex];
                openActivityLogs('token_usage', modelDates[index],
                    model ? { ...tokenLogExtras(), model } : tokenLogExtras());
            }),
        },
    });

    const totalOf = (rows: DailyActivityRow[], key: keyof DailyActivityRow) => rows.reduce((total, row) => total + Number(row[key] ?? 0), 0);
    const signInTotal = totalOf(daily, 'sign_ins');
    const conversationTotal = totalOf(daily, 'conversations_created');
    const uploadTotal = UPLOAD_SERIES.reduce((total, series) => total + totalOf(daily, series.key), 0);
    const tokenTotal = tokenDays.reduce((total, row) => total + row.chat + row.embedding + row.web_search, 0);
    const clickHint = canViewLogs ? ' Select a point to open the matching activity logs.' : '';
    const rangeText = `${formatDay(startDay)} to ${formatDay(endDay)}`;
    // Charts rebuild only when their signature changes, so a refresh that returns new data must change it too.
    const chartVersion = `${query}|${insights?.refreshed_at ?? ''}|${canViewLogs ? 'logs' : 'no-logs'}`;

    const userSection: EntitySection | null = canManageUsers ? 'users' : null;
    const groupSection: EntitySection | null = canManageGroups ? 'groups' : null;
    const workspaceSection: EntitySection | null = canManageWorkspaces ? 'public-workspaces' : null;
    // The Users page filters by last sign-in over 7, 30 or 90 days; a custom range has no equivalent.
    const signedInUsersHref = canManageUsers && preset !== 'custom'
        ? `/control-center/users?last_login=${encodeURIComponent(preset)}`
        : null;

    const statusLinks = (byStatus: Record<string, Metric>, section: EntitySection, canLink: boolean) => {
        const notable = Object.entries(byStatus).filter(([status, metric]) => status !== 'active' && Number(metric.value ?? 0) > 0);
        if (notable.length === 0) {
            return null;
        }
        return (
            <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Not active, by status">
                {notable.map(([status, metric]) => {
                    const text = `${STATUS_LABELS[status] ?? status.replaceAll('_', ' ')}: ${formatNumber(metric.value)}`;
                    return (
                        <li key={status}>
                            {canLink ? (
                                <Link to={safeControlCenterHref(`/control-center/${section}?status=${encodeURIComponent(status)}`)}
                                    className="inline-flex rounded-full bg-surface-2 px-2.5 py-1 text-xs text-text-2 hover:text-text-1">
                                    {text}
                                </Link>
                            ) : <span className="inline-flex rounded-full bg-surface-2 px-2.5 py-1 text-xs text-text-2">{text}</span>}
                        </li>
                    );
                })}
            </ul>
        );
    };

    const tileGrid = 'grid gap-3 grid-cols-[repeat(auto-fill,minmax(13rem,1fr))]';
    const controlClass = 'mt-1 block rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1';
    const secondaryButtonClass = 'inline-flex items-center gap-2 rounded-lg border border-edge px-3 py-2 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-50';

    return (
        <div className="space-y-8 p-4 md:p-6">
            <div className="space-y-2">
                <div className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                        <h2 className="text-xl font-semibold text-text-1">Dashboard</h2>
                        <p className="mt-1 text-sm text-text-2">How SimpleChat is being used, for the dates you choose (UTC).</p>
                    </div>
                    <div className="flex flex-wrap items-end gap-2">
                        <div>
                            <label htmlFor="dashboard-range" className="block text-xs text-text-2">Date range</label>
                            <select id="dashboard-range" value={preset} onChange={(event) => setPreset(event.target.value as typeof preset)}
                                className={controlClass}>
                                <option value="7">Last 7 days</option>
                                <option value="30">Last 30 days</option>
                                <option value="90">Last 90 days</option>
                                <option value="custom">Custom</option>
                            </select>
                        </div>
                        {preset === 'custom' ? (
                            <>
                                <div>
                                    <label htmlFor="dashboard-start-date" className="block text-xs text-text-2">Start</label>
                                    <input id="dashboard-start-date" type="date" value={customStart}
                                        onChange={(event) => setCustomStart(event.target.value)} className={controlClass} />
                                </div>
                                <div>
                                    <label htmlFor="dashboard-end-date" className="block text-xs text-text-2">End</label>
                                    <input id="dashboard-end-date" type="date" value={customEnd}
                                        onChange={(event) => setCustomEnd(event.target.value)} className={controlClass} />
                                </div>
                            </>
                        ) : null}
                        <button type="button" onClick={() => setRefreshVersion((current) => current + 1)} disabled={loading}
                            className={secondaryButtonClass}>
                            <RefreshCw size={14} aria-hidden="true" /> Refresh
                        </button>
                        <button type="button" onClick={() => void exportTrends()} disabled={loading || exporting}
                            className={secondaryButtonClass}>
                            <Download size={14} aria-hidden="true" /> {exporting ? 'Exporting…' : 'Export'}
                        </button>
                        <DashboardChatButton disabled={loading && !summary}
                            context={{ startDate: startDay, endDate: endDay, tokenFilters: tokenFilterDescriptions }} />
                    </div>
                </div>
                {preset === 'custom' ? (
                    <p className="text-right text-xs text-text-3">Custom ranges can cover up to 366 days. Dates are UTC.</p>
                ) : null}
                <p role="status" className="text-xs text-text-3">{loading && summary ? 'Refreshing dashboard data…' : ''}</p>
            </div>

            {actionError ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{actionError}</p> : null}

            {error ? (
                <div role="alert" className="rounded-xl bg-danger-soft p-4 text-sm text-danger">
                    <p>{error}</p>
                    <button type="button" className="mt-2 font-semibold underline" onClick={() => setRefreshVersion((current) => current + 1)}>Try again</button>
                </div>
            ) : null}

            {loading && !summary ? (
                <div className="space-y-8" aria-label="Loading dashboard" aria-busy="true">
                    {Array.from({ length: 3 }, (_, section) => (
                        <div key={section} className="space-y-3">
                            <div className="h-5 w-40 animate-pulse rounded bg-surface-2" />
                            <div className={tileGrid}>
                                {Array.from({ length: 4 }, (_, index) => (
                                    <div key={index} className="h-24 animate-pulse rounded-2xl border border-edge bg-surface-2" />
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            ) : null}

            {summary ? (
                <DashboardBlock id="dashboard-directory" title="Directory"
                    description="Totals as they stand now. The date range does not change them.">
                    <div className={tileGrid}>
                        <MetricTile label="Total users" value={formatNumber(summary.users.total.value)}
                            definition="Everyone with a SimpleChat profile."
                            to={canManageUsers ? '/control-center/users' : null} />
                        <MetricTile label="Blocked users" value={formatNumber(summary.users.blocked.value)}
                            definition="Accounts currently denied access."
                            to={canManageUsers ? '/control-center/users?status=blocked' : null} />
                        <MetricTile label="Groups" value={formatNumber(summary.groups.total.value)}
                            definition={`${formatNumber(summary.groups.by_status.active?.value)} active.`}
                            to={canManageGroups ? '/control-center/groups' : null}>
                            {statusLinks(summary.groups.by_status, 'groups', canManageGroups)}
                        </MetricTile>
                        <MetricTile label="Public workspaces" value={formatNumber(summary.public_workspaces.total.value)}
                            definition={`${formatNumber(summary.public_workspaces.by_status.active?.value)} active.`}
                            to={canManageWorkspaces ? '/control-center/public-workspaces' : null}>
                            {statusLinks(summary.public_workspaces.by_status, 'public-workspaces', canManageWorkspaces)}
                        </MetricTile>
                        {summary.pending_approvals ? (
                            <MetricTile label="Pending approvals" value={formatNumber(summary.pending_approvals.value)}
                                definition="Requests waiting for a decision." to={APPROVALS_URL} />
                        ) : null}
                    </div>
                </DashboardBlock>
            ) : null}

            {summary && insights ? (
                <>
                    <DashboardBlock id="dashboard-sign-ins" title="Sign-ins"
                        description={`Who signed in from ${rangeText}. Each figure counts a person once, however often they signed in.`}>
                        <div className={tileGrid}>
                            <MetricTile label="Signed-in users" value={formatNumber(summary.users.active.value)}
                                comparison={comparisonText(summary.users.active, periodDays)}
                                definition="People who signed in at least once in the range."
                                to={signedInUsersHref} />
                            <MetricTile label="Daily active users" value={formatNumber(summary.users.dau.value)}
                                definition={`People who signed in on ${formatDay(endDay)}.`} />
                            <MetricTile label="Weekly active users" value={formatNumber(summary.users.wau.value)}
                                definition={`People who signed in during the 7 days ending ${formatDay(endDay)}.`} />
                            <MetricTile label="Monthly active users" value={formatNumber(summary.users.mau.value)}
                                definition={`People who signed in during the 30 days ending ${formatDay(endDay)}.`} />
                        </div>
                        <div className="grid gap-4 xl:grid-cols-2">
                            <ChartPanel title="Sign-ins per day">
                                {signInTotal ? (
                                    <>
                                        <StatsChart buildConfig={signInConfig} signature={`${chartVersion}|sign-ins`}
                                            ariaLabel={`Daily sign-in counts.${clickHint}`} />
                                        <ChartDataTable title="Sign-ins" dates={dailyDates}
                                            series={[{ label: 'Sign-ins', values: daily.map((row) => row.sign_ins) }]} />
                                    </>
                                ) : <EmptyChart>No sign-ins were recorded in this range.</EmptyChart>}
                            </ChartPanel>
                            <ChartPanel title="Sign-ins by weekday and hour (UTC)">
                                {insights.login_heatmap.cells.length ? (
                                    <>
                                        <p className="mb-2 text-xs text-text-3">Every sign-in in the range, added up by weekday and hour, so regular busy times stand out.</p>
                                        <LoginHeatmap cells={insights.login_heatmap.cells} />
                                    </>
                                ) : <EmptyChart>No sign-ins were recorded in this range.</EmptyChart>}
                            </ChartPanel>
                        </div>
                    </DashboardBlock>

                    <DashboardBlock id="dashboard-content" title="Conversations and documents"
                        description={`What people started and uploaded from ${rangeText}.`}>
                        <div className={tileGrid}>
                            <MetricTile label="Conversations created" value={formatNumber(summary.conversations.value)}
                                comparison={comparisonText(summary.conversations, periodDays)}
                                definition="New conversations started in the range."
                                to={canViewLogs ? activityLogsHref('conversation_creation', { start_date: startDay, end_date: endDay }) : null} />
                            <MetricTile label="Document uploads" value={formatNumber(summary.document_uploads.total.value)}
                                comparison={comparisonText(summary.document_uploads.total, periodDays)}
                                definition={UPLOAD_SERIES.map((series) => `${series.label} ${formatNumber(summary.document_uploads.by_workspace_type[series.workspaceType]?.value)}`).join(' · ')}
                                to={canViewLogs ? activityLogsHref('document_creation', { start_date: startDay, end_date: endDay }) : null} />
                            <MetricTile label="Processing failures"
                                value={summary.document_processing_failures.available === false ? 'Not tracked' : formatNumber(summary.document_processing_failures.value)}
                                comparison={comparisonText(summary.document_processing_failures, periodDays)}
                                definition="Documents uploaded in the range whose processing failed."
                                to={canViewLogs ? activityLogsHref('document_creation', { status: 'failed', start_date: startDay, end_date: endDay }) : null} />
                        </div>
                        <div className="grid gap-4 xl:grid-cols-2">
                            <ChartPanel title="Conversations created per day">
                                {conversationTotal ? (
                                    <>
                                        <StatsChart buildConfig={conversationConfig} signature={`${chartVersion}|conversations`}
                                            ariaLabel={`Daily conversation creation counts.${clickHint}`} />
                                        <ChartDataTable title="Conversations created" dates={dailyDates}
                                            series={[{ label: 'Conversations', values: daily.map((row) => row.conversations_created) }]} />
                                    </>
                                ) : <EmptyChart>No conversations were created in this range.</EmptyChart>}
                            </ChartPanel>
                            <ChartPanel title="Document uploads by workspace">
                                {uploadTotal ? (
                                    <>
                                        <StatsChart buildConfig={uploadConfig} signature={`${chartVersion}|uploads`}
                                            ariaLabel={`Daily document uploads, stacked by personal, group and public workspace.${clickHint}`} />
                                        <ChartDataTable title="Document uploads" dates={dailyDates} series={UPLOAD_SERIES.map((series) => ({
                                            label: series.label,
                                            values: daily.map((row) => Number(row[series.key] ?? 0)),
                                        }))} />
                                    </>
                                ) : <EmptyChart>No documents were uploaded in this range.</EmptyChart>}
                            </ChartPanel>
                        </div>
                    </DashboardBlock>

                    <DashboardBlock id="dashboard-tokens" title="Token usage"
                        description={`Model tokens recorded from ${rangeText}.`}>
                        <div role="group" aria-labelledby="dashboard-token-filters-title"
                            className="rounded-2xl border border-edge bg-surface-1 p-4">
                            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                                <p id="dashboard-token-filters-title" className="text-sm font-semibold text-text-1">Filter token usage</p>
                                <p className="text-xs text-text-3">These filters change only the token figures in this section.</p>
                            </div>
                            <div className="flex flex-wrap items-end gap-3">
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
                                {filtersActive ? (
                                    <button type="button" onClick={() => setFilters(EMPTY_FILTERS)} className={secondaryButtonClass}>
                                        Clear filters
                                    </button>
                                ) : null}
                            </div>
                            {filterError ? <p role="alert" className="mt-3 text-xs text-warn">{filterError} Token filters may be incomplete.</p> : null}
                        </div>
                        <div className={tileGrid}>
                            <MetricTile label="Tokens used" value={formatNumber(summary.tokens.value)}
                                comparison={comparisonText(summary.tokens, periodDays)}
                                definition={filtersActive
                                    ? `Tokens matching ${tokenFilterDescriptions.join(', ')}.`
                                    : 'Chat, embedding and web search tokens recorded in the range.'}
                                to={canViewLogs ? activityLogsHref('token_usage', { start_date: startDay, end_date: endDay, ...tokenLogExtras() }) : null} />
                        </div>
                        <div className="grid gap-4 xl:grid-cols-2">
                            <ChartPanel title="Tokens by usage type">
                                {tokenTotal ? (
                                    <>
                                        <StatsChart buildConfig={tokenConfig} signature={`${chartVersion}|tokens`}
                                            ariaLabel={`Daily token counts stacked by chat, embedding and web search.${clickHint}`} />
                                        <ChartDataTable title="Tokens by usage type" dates={tokenDates} series={TOKEN_SERIES.map((series) => ({
                                            label: series.label,
                                            values: tokenDays.map((row) => Number(row[series.key] ?? 0)),
                                        }))} />
                                    </>
                                ) : <EmptyChart>{filtersActive ? 'No token usage matches these filters.' : 'No token usage was recorded in this range.'}</EmptyChart>}
                            </ChartPanel>
                            <ChartPanel title="Tokens by model">
                                {modelDates.length > 0 ? (
                                    <>
                                        <StatsChart buildConfig={modelConfig} signature={`${chartVersion}|models`}
                                            ariaLabel={`Daily token usage stacked by model.${clickHint}`} />
                                        <ChartDataTable title="Tokens by model" dates={modelDates} series={modelNames.map((model) => ({
                                            label: model,
                                            values: modelValues(model),
                                        }))} />
                                    </>
                                ) : <EmptyChart>{filtersActive ? 'No model usage matches these filters.' : 'No model usage was recorded in this range.'}</EmptyChart>}
                            </ChartPanel>
                        </div>
                        <ChartPanel title="Top token consumers">
                            <div className="grid gap-5 md:grid-cols-3">
                                <RankedList title="Users" rows={insights.top_tokens.users} valueKey="tokens" unit="tokens" section={userSection} />
                                <RankedList title="Groups" rows={insights.top_tokens.groups} valueKey="tokens" unit="tokens" section={groupSection} />
                                <RankedList title="Public workspaces" rows={insights.top_tokens.public_workspaces} valueKey="tokens" unit="tokens" section={workspaceSection} />
                            </div>
                        </ChartPanel>
                    </DashboardBlock>

                    <DashboardBlock id="dashboard-most-active" title="Most active"
                        description="Ranked by how many activity records each one has in the range, such as sign-ins, conversations, uploads and token use. Token filters do not apply here.">
                        <div className="rounded-2xl border border-edge bg-surface-1 p-4">
                            <div className="grid gap-5 md:grid-cols-3">
                                <RankedList title="Users" rows={insights.top_activity.users} valueKey="activity_count" unit="activity records" section={userSection} />
                                <RankedList title="Groups" rows={insights.top_activity.groups} valueKey="activity_count" unit="activity records" section={groupSection} />
                                <RankedList title="Public workspaces" rows={insights.top_activity.public_workspaces} valueKey="activity_count" unit="activity records" section={workspaceSection} />
                            </div>
                        </div>
                    </DashboardBlock>
                </>
            ) : null}

            {summary?.refreshed_at ? <p className="text-right text-xs text-text-3">Updated {new Date(summary.refreshed_at).toLocaleString()}</p> : null}
        </div>
    );
}