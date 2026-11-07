// activityLogs.ts
// Types, the URL filter contract, date presets and time formatting for Control Center
// Activity Logs.
//
// The URL is the investigation's state, so a bookmark, a Dashboard drill-through or a saved
// view reopens exactly what was on screen. A relative range is stored as `range` (for example
// `range=7`) so a saved "last 7 days" view stays relative; a custom window is stored as
// inclusive UTC `start_date`/`end_date`. The API always receives explicit dates.

export type ActivityRecord = {
    id: string;
    timestamp: string;
    activity_type?: unknown;
    user_id?: unknown;
    workspace_type?: unknown;
    [key: string]: unknown;
};

export interface ActivityPerson {
    id: string;
    name: string;
    email: string;
    kind: 'user' | 'system';
    resolved: boolean;
}

export interface ActivityWorkspaceRef {
    type: string;
    id: string;
    name: string;
    resolved: boolean;
}

export interface ActivityFact {
    label: string;
    value: string;
}

/** The server's readable presentation of one record; the table, drawer and export share it. */
export interface ActivityPresentation {
    activity_type: string;
    label: string;
    category: string;
    summary: string;
    detail: string;
    facts: ActivityFact[];
    status: 'failed' | null;
    actor: ActivityPerson;
    workspace: ActivityWorkspaceRef;
}

export interface ActivityFilterLabels {
    person?: { id: string; name: string; email: string; resolved: boolean };
    workspace?: ActivityWorkspaceRef;
}

export interface ActivityPage {
    items: ActivityRecord[];
    presentation?: ActivityPresentation[];
    filter_labels?: ActivityFilterLabels;
    search_people?: { matched: number; truncated: boolean };
    next_cursor: string | null;
    snapshot: string;
}

export interface ActivityFacet {
    activity_type: string;
    count: number;
    label?: string;
    category?: string;
}

export interface ActivityTypeOption {
    activity_type: string;
    label: string;
    category: string;
    category_label: string;
}

export interface ActivitySummary {
    facets: ActivityFacet[];
    histogram: { date: string; count: number }[];
    bucket_days: number;
    sample_size: number;
    sample_limit: number;
    truncated: boolean;
    type_catalog?: ActivityTypeOption[];
}

export interface ActivityPersonOption {
    id: string;
    display_name: string;
    email: string;
}

export interface ActivityWorkspaceOption {
    type: 'group' | 'public';
    id: string;
    name: string;
}

export const RANGE_PRESETS = [
    { id: 'today', label: 'Today', days: 1 },
    { id: '7', label: 'Last 7 days', days: 7 },
    { id: '30', label: 'Last 30 days', days: 30 },
    { id: '90', label: 'Last 90 days', days: 90 },
] as const;
export type RangePreset = (typeof RANGE_PRESETS)[number]['id'];
export const DEFAULT_RANGE: RangePreset = '30';
export const MAX_RANGE_DAYS = 366;

export type WorkspaceType = '' | 'personal' | 'group' | 'public';

export interface ActivityFilters {
    /** The relative preset in force, or '' for a custom UTC window. */
    range: RangePreset | '';
    start_date: string;
    end_date: string;
    activity_type: string[];
    user_id: string;
    workspace_type: WorkspaceType;
    workspace_id: string;
    search: string;
    token_type: string;
    model: string;
    status: string;
}

export const TEXT_FILTER_KEYS = ['user_id', 'workspace_id', 'search', 'token_type', 'model', 'status'] as const;

export const TOKEN_TYPES = [
    { value: 'chat', label: 'Chat' },
    { value: 'embedding', label: 'Embedding' },
    { value: 'web_search', label: 'Web search' },
] as const;

export const WORKSPACE_TYPE_LABELS: Record<string, string> = {
    personal: 'Personal',
    group: 'Group',
    public: 'Public',
    admin: 'Administration',
    global: 'Global',
};

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function todayUtc(now: Date = new Date()): string {
    return now.toISOString().slice(0, 10);
}

export function isUtcDate(value: string): boolean {
    if (!DATE_PATTERN.test(value)) return false;
    const date = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function shiftUtcDate(value: string, days: number): string {
    const date = new Date(`${value}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
}

export function daysBetween(start: string, end: string): number {
    return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000);
}

export function presetDates(range: RangePreset, now: Date = new Date()): { start_date: string; end_date: string } {
    const end = todayUtc(now);
    const days = RANGE_PRESETS.find((preset) => preset.id === range)?.days ?? 30;
    return { start_date: shiftUtcDate(end, -(days - 1)), end_date: end };
}

function isRangePreset(value: string | null): value is RangePreset {
    return RANGE_PRESETS.some((preset) => preset.id === value);
}

export function defaultFilters(now: Date = new Date()): ActivityFilters {
    return {
        range: DEFAULT_RANGE,
        ...presetDates(DEFAULT_RANGE, now),
        activity_type: [],
        user_id: '',
        workspace_type: '',
        workspace_id: '',
        search: '',
        token_type: '',
        model: '',
        status: '',
    };
}

/**
 * Read filters from the URL, accepting every link shape that already points here: the
 * Dashboard's single `date`, the group drawer's `group_id`, and the legacy
 * `workspace_type=public_workspace`.
 */
export function readFilters(params: URLSearchParams, now: Date = new Date()): ActivityFilters {
    const filters = defaultFilters(now);
    const range = params.get('range');
    const single = params.get('date') ?? '';
    const start = params.get('start_date') ?? '';
    const end = params.get('end_date') ?? '';
    if (isRangePreset(range)) {
        Object.assign(filters, { range }, presetDates(range, now));
    } else if (start || end || single) {
        const endDate = end || single || todayUtc(now);
        filters.range = '';
        filters.end_date = endDate;
        filters.start_date = start || single || (isUtcDate(endDate) ? shiftUtcDate(endDate, -29) : endDate);
    }
    filters.activity_type = [...new Set(params.getAll('activity_type')
        .flatMap((value) => value.split(','))
        .map((value) => value.trim())
        .filter((value) => value && value !== 'all'))];
    for (const key of TEXT_FILTER_KEYS) filters[key] = (params.get(key) ?? '').trim();
    const rawType = params.get('workspace_type') ?? '';
    const type = rawType === 'public_workspace' ? 'public' : rawType;
    filters.workspace_type = (['personal', 'group', 'public'].includes(type) ? type : '') as WorkspaceType;
    const groupId = (params.get('group_id') ?? '').trim();
    const publicId = (params.get('public_workspace_id') ?? '').trim();
    if (groupId) {
        filters.workspace_type = 'group';
        filters.workspace_id = groupId;
    } else if (publicId) {
        filters.workspace_type = 'public';
        filters.workspace_id = publicId;
    }
    if (!filters.workspace_type) filters.workspace_id = '';
    return filters;
}

function appendShared(params: URLSearchParams, filters: ActivityFilters) {
    filters.activity_type.forEach((value) => params.append('activity_type', value));
    if (filters.user_id) params.set('user_id', filters.user_id);
    if (filters.workspace_type) params.set('workspace_type', filters.workspace_type);
    if (filters.workspace_type && filters.workspace_id) params.set('workspace_id', filters.workspace_id);
    for (const key of ['search', 'token_type', 'model', 'status'] as const) {
        if (filters[key]) params.set(key, filters[key]);
    }
}

/** The canonical URL for a filter set: the default 30-day range is implied, not written. */
export function filterParams(filters: ActivityFilters): URLSearchParams {
    const params = new URLSearchParams();
    if (filters.range && filters.range !== DEFAULT_RANGE) params.set('range', filters.range);
    if (!filters.range) {
        params.set('start_date', filters.start_date);
        params.set('end_date', filters.end_date);
    }
    appendShared(params, filters);
    return params;
}

/** The API query: always explicit inclusive UTC dates. */
export function apiParams(filters: ActivityFilters): URLSearchParams {
    const params = new URLSearchParams({ start_date: filters.start_date, end_date: filters.end_date });
    appendShared(params, filters);
    return params;
}

export function rangeValidationError(start: string, end: string): string {
    if (!isUtcDate(start) || !isUtcDate(end)) return 'Enter both dates as valid calendar dates.';
    if (end < start) return 'The end date must be on or after the start date.';
    if (daysBetween(start, end) + 1 > MAX_RANGE_DAYS) return `Choose a range of ${MAX_RANGE_DAYS} days or fewer.`;
    return '';
}

const SHORT_DATE = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
const LONG_DATE = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });

/** "Oct 1, 2026" for a UTC calendar date. */
export function formatUtcDay(value: string, withYear = true): string {
    if (!isUtcDate(value)) return value;
    return (withYear ? LONG_DATE : SHORT_DATE).format(new Date(`${value}T00:00:00Z`));
}

export function dateRangeLabel(filters: ActivityFilters): string {
    const preset = RANGE_PRESETS.find((item) => item.id === filters.range);
    if (preset) return preset.label;
    if (filters.start_date === filters.end_date) return `${formatUtcDay(filters.start_date)} (UTC)`;
    const sameYear = filters.start_date.slice(0, 4) === filters.end_date.slice(0, 4);
    return `${formatUtcDay(filters.start_date, !sameYear)} – ${formatUtcDay(filters.end_date)} (UTC)`;
}

export function isDefaultFilters(filters: ActivityFilters): boolean {
    return filterParams(filters).toString() === '';
}

export function humanize(value: string): string {
    const text = value.replace(/[_-]+/g, ' ').trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

export type ActivityTimeZone = 'local' | 'utc';
export type ActivityDensity = 'comfortable' | 'compact';

export interface ActivityLogPrefs {
    timeZone: ActivityTimeZone;
    density: ActivityDensity;
    showTrend: boolean;
}

export const DEFAULT_ACTIVITY_LOG_PREFS: ActivityLogPrefs = {
    timeZone: 'local',
    density: 'comfortable',
    showTrend: true,
};

/** Stored settings are untrusted: keep only recognized values. */
export function parseActivityLogPrefs(value: unknown): ActivityLogPrefs {
    const stored = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    return {
        timeZone: stored.timeZone === 'utc' ? 'utc' : 'local',
        density: stored.density === 'compact' ? 'compact' : 'comfortable',
        showTrend: stored.showTrend !== false,
    };
}

/** Activity timestamps are UTC; older writers stored them without a zone designator. */
export function parseActivityTime(value: string): Date | null {
    if (!value) return null;
    const zoned = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
    const date = new Date(zoned ? value : `${value}Z`);
    return Number.isNaN(date.getTime()) ? null : date;
}

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

function relativeTime(date: Date, now: Date): string {
    const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
    const absolute = Math.abs(seconds);
    if (absolute < 45) return 'just now';
    if (absolute < 3600) return RELATIVE.format(Math.round(seconds / 60), 'minute');
    if (absolute < 86_400) return RELATIVE.format(Math.round(seconds / 3600), 'hour');
    if (absolute < 30 * 86_400) return RELATIVE.format(Math.round(seconds / 86_400), 'day');
    return '';
}

export function utcStamp(date: Date): string {
    return `${date.toISOString().slice(0, 19).replace('T', ' ')} UTC`;
}

/** The table's time cell: the chosen zone up front, the other one on hover. */
export function formatActivityTime(value: string, zone: ActivityTimeZone, now: Date = new Date()) {
    const date = parseActivityTime(value);
    if (!date) return { primary: value || 'Not recorded', secondary: '', title: value, utc: value, local: value };
    const local = new Intl.DateTimeFormat(undefined, {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
        year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
    }).format(date);
    const localLong = new Intl.DateTimeFormat(undefined, { dateStyle: 'full', timeStyle: 'long' }).format(date);
    return {
        primary: zone === 'utc' ? utcStamp(date) : local,
        secondary: relativeTime(date, now),
        title: zone === 'utc' ? localLong : utcStamp(date),
        utc: utcStamp(date),
        local: localLong,
    };
}

/** The display name for a person, never an empty string. */
export function personName(person: Pick<ActivityPerson, 'name' | 'email' | 'id' | 'kind'>): string {
    if (person.kind === 'system') return 'System';
    return person.name || person.email || (person.id ? 'Unknown user' : 'Unknown');
}

export function workspaceName(workspace: ActivityWorkspaceRef): string {
    if (workspace.name) return workspace.name;
    if (workspace.type === 'group') return 'Unknown group';
    if (workspace.type === 'public') return 'Unknown public workspace';
    return WORKSPACE_TYPE_LABELS[workspace.type] ?? '';
}

export function shortId(value: string): string {
    return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

/**
 * True when a picker's search text is plausibly an ID rather than a name: no spaces or @,
 * and a digit or hyphen, as every SimpleChat user and workspace ID has. Used to offer
 * filtering by the ID of someone or something no longer in SimpleChat.
 */
export function looksLikeId(value: string): boolean {
    return /^[^\s@]{4,256}$/.test(value) && /[\d-]/.test(value);
}

export interface ActivityLogSavedView {
    id: string;
    name: string;
    /** The canonical filter query string, as written by filterParams. */
    query: string;
}
