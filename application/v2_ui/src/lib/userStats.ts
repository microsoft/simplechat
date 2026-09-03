// userStats.ts
// The user's own activity figures: what the endpoints return, and everything derived from
// them that is worth testing on its own.
//
// Two responses feed the stats tab, and they answer different questions. `/api/user/settings`
// carries a `metrics` block of *lifetime* totals, recalculated periodically and stamped with
// `calculated_at` — which is why the tab says when they were last worked out rather than
// implying they are live. `/api/user/activity-trends` answers the narrower question of what
// happened inside a chosen window, day by day.
//
// Nothing here imports the API client. The module is pure so a Node test can execute the
// window, alignment and CSV logic against the real source rather than a copy of it.

/** One day of a trend series. Counts and token totals never arrive on the same series. */
export interface DayCount {
    date: string;
    count?: number;
    tokens?: number;
}

/** Response of GET /api/user/activity-trends. */
export interface ActivityTrends {
    success?: boolean;
    logins?: DayCount[];
    conversations?: { creates?: DayCount[]; deletes?: DayCount[] };
    documents?: { uploads?: DayCount[]; deletes?: DayCount[] };
    tokens?: DayCount[];
    storage?: { ai_search_size?: number; storage_account_size?: number };
    /** Every day in the window, including the ones with nothing on them. */
    dateRange?: string[];
    /** The window the server actually resolved, which may not be the one asked for. */
    window?: { type?: string; days?: number; label?: string; startDate?: string; endDate?: string };
}

/**
 * The cached lifetime totals from GET /api/user/settings.
 *
 * `last_login` is the exception to "cached": the route overwrites it from the activity log
 * when that lookup succeeds, so it is current even when the surrounding block is not.
 */
export interface UserMetrics {
    calculated_at?: string;
    login_metrics?: { total_logins?: number; last_login?: string; last_login_source?: string };
    chat_metrics?: {
        total_conversations?: number;
        total_messages?: number;
        total_message_size?: number;
    };
    document_metrics?: {
        total_documents?: number;
        ai_search_size?: number;
        storage_account_size?: number;
    };
}

export interface UserSettingsWithMetrics {
    settings?: { metrics?: UserMetrics; [key: string]: unknown };
}

/**
 * The window the figures cover.
 *
 * A preset carries a day count; a custom range carries two dates. They are not
 * interchangeable on the wire — see `statsWindowQuery`.
 */
export interface StatsWindow {
    days: number;
    startDate: string;
    endDate: string;
}

/**
 * Preset windows, as day counts.
 *
 * These must stay inside `ALLOWED_STATS_WINDOW_DAYS` in functions_stats_windows.py: a value
 * outside it is not rejected, it silently becomes 30, so the tab would show a different
 * window from the one highlighted. A functional test pins the two lists together.
 */
export const STATS_WINDOWS = [
    { days: 7, label: '7 days' },
    { days: 30, label: '30 days' },
    { days: 90, label: '90 days' },
] as const;

export const DEFAULT_STATS_WINDOW: StatsWindow = { days: 30, startDate: '', endDate: '' };

/** True when the window is an explicit date range rather than one of the presets. */
export function isCustomWindow(window: StatsWindow): boolean {
    return Boolean(window.startDate && window.endDate);
}

/**
 * The query string for a window.
 *
 * A custom range sends `start_date`/`end_date` and *not* `days`, because
 * `resolve_stats_time_window` branches on the presence of either date and would otherwise
 * ignore the range entirely. The preset form sends only `days`.
 */
export function statsWindowQuery(window: StatsWindow): string {
    const params = new URLSearchParams();
    if (isCustomWindow(window)) {
        params.set('start_date', window.startDate);
        params.set('end_date', window.endDate);
    } else {
        params.set('days', String(window.days || DEFAULT_STATS_WINDOW.days));
    }
    return params.toString();
}

/**
 * Check a custom range before sending it.
 *
 * The server rejects the same two cases with a 400. Catching them here means the user is
 * told what is wrong with the dates they just typed, rather than being shown a failed
 * request.
 *
 * Returns the resolved window, or a message explaining why it was refused.
 */
export function validateCustomRange(
    startDate: string,
    endDate: string,
): { ok: true; window: StatsWindow } | { ok: false; error: string } {
    if (!startDate || !endDate) {
        return { ok: false, error: 'Choose both a start and an end date.' };
    }

    const start = new Date(startDate);
    const end = new Date(endDate);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
        return { ok: false, error: 'Enter both dates in YYYY-MM-DD form.' };
    }
    if (start > end) {
        return { ok: false, error: 'The start date must be on or before the end date.' };
    }

    // Inclusive of both ends, matching the server's own day count for the same range.
    const days = Math.ceil(Math.abs(end.getTime() - start.getTime()) / 86400000) + 1;
    return { ok: true, window: { days, startDate, endDate } };
}

/** The label to show for a window before the server has told us what it resolved. */
export function statsWindowLabel(window: StatsWindow): string {
    if (isCustomWindow(window)) {
        return `${formatDisplayDate(window.startDate)} - ${formatDisplayDate(window.endDate)}`;
    }
    return `Last ${window.days || DEFAULT_STATS_WINDOW.days} Days`;
}

/** `M/D/YYYY`, matching how the server formats the same range in `window.label`. */
export function formatDisplayDate(value: string): string {
    const parts = String(value || '').split('-');
    if (parts.length !== 3) {
        return value;
    }
    const [year, month, day] = parts;
    return `${Number(month)}/${Number(day)}/${year}`;
}

/** `M/D`, the axis label form. */
export function formatShortDate(value: string): string {
    const parts = String(value || '').split('-');
    if (parts.length !== 3) {
        return value;
    }
    return `${Number(parts[1])}/${Number(parts[2])}`;
}

/**
 * Line a series up against the window's days.
 *
 * The series and `dateRange` normally match one for one, but relying on that would make a
 * chart silently mislabel itself if they ever diverged: the values would be drawn against
 * whichever labels happened to sit at the same index. Looking each day up by date keeps a
 * bar over its own date, and fills a missing day with zero rather than dropping it.
 */
export function alignSeries(
    series: DayCount[] | undefined,
    dateRange: string[],
    valueKey: 'count' | 'tokens' = 'count',
): number[] {
    const byDate = new Map((series ?? []).map((day) => [day.date, day[valueKey] ?? 0]));
    return dateRange.map((date) => byDate.get(date) ?? 0);
}

/** Total of a series across the whole window. */
export function sumSeries(
    series: DayCount[] | undefined,
    valueKey: 'count' | 'tokens' = 'count',
): number {
    return (series ?? []).reduce((total, day) => total + (day[valueKey] ?? 0), 0);
}

/** Every day in the window, falling back to the client's own count when absent. */
export function resolveDateRange(trends: ActivityTrends | null, window: StatsWindow): string[] {
    if (trends?.dateRange && trends.dateRange.length > 0) {
        return trends.dateRange;
    }
    return lastDays(window.days || DEFAULT_STATS_WINDOW.days);
}

/** The last `count` dates, most recent last, as `YYYY-MM-DD`. */
export function lastDays(count: number): string[] {
    const days: string[] = [];
    for (let offset = Math.max(count, 1) - 1; offset >= 0; offset -= 1) {
        const date = new Date();
        date.setDate(date.getDate() - offset);
        days.push(date.toISOString().split('T')[0]);
    }
    return days;
}

/** `1.2K` / `3.4M`, matching the abbreviation the classic stat cards use. */
export function formatCompactNumber(value: number): string {
    const number = Number(value) || 0;
    if (Math.abs(number) >= 1000000) {
        return `${(number / 1000000).toFixed(1)}M`;
    }
    if (Math.abs(number) >= 1000) {
        return `${(number / 1000).toFixed(1)}K`;
    }
    return String(number);
}

/** Storage sizes, in the units the storage figures are actually reported in. */
export function formatBytes(bytes: number): string {
    const value = Number(bytes) || 0;
    if (value === 0) {
        return '0 Bytes';
    }
    const units = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const exponent = Math.min(Math.floor(Math.log(Math.abs(value)) / Math.log(1024)), units.length - 1);
    const scaled = value / 1024 ** exponent;
    return `${Math.round(scaled * 100) / 100} ${units[exponent]}`;
}

/**
 * How long ago something happened, in words.
 *
 * Used for the last sign-in and for when the cached totals were worked out. Both are
 * questions of recency rather than of exact time, and "3 days ago" answers them better than
 * a timestamp does.
 */
export function formatRelativeTime(value: string | undefined, now: Date = new Date()): string {
    if (!value) {
        return 'Never';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return 'Unknown';
    }

    const elapsed = now.getTime() - date.getTime();
    const minutes = Math.floor(elapsed / 60000);
    const hours = Math.floor(elapsed / 3600000);
    const days = Math.floor(elapsed / 86400000);

    if (minutes < 1) {
        return 'Just now';
    }
    if (minutes < 60) {
        return `${minutes} min ago`;
    }
    if (hours < 24) {
        return `${hours} hr ago`;
    }
    if (days < 7) {
        return `${days} day${days > 1 ? 's' : ''} ago`;
    }
    return date.toLocaleDateString();
}

/** Which parts of the export to include. */
export interface ExportSections {
    metrics: boolean;
    logins: boolean;
    conversations: boolean;
    documents: boolean;
    tokens: boolean;
}

export const DEFAULT_EXPORT_SECTIONS: ExportSections = {
    metrics: true,
    logins: true,
    conversations: true,
    documents: true,
    tokens: true,
};

/** A single CSV field, quoted only when it has to be. */
function csvField(value: unknown): string {
    const text = value === null || value === undefined ? '' : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function csvRow(values: unknown[]): string {
    return values.map(csvField).join(',');
}

/**
 * The activity export.
 *
 * Assembled here rather than on the server because the two responses it draws on are
 * already loaded, and a dedicated endpoint would be a second implementation of totals the
 * client is displaying anyway. The section titles, column headers and ordering match the
 * classic profile page's export so a saved spreadsheet keeps working across both interfaces.
 */
export function buildActivityCsv({
    trends,
    metrics,
    sections,
    userName,
    userEmail,
    windowLabel,
    exportedAt = new Date(),
}: {
    trends: ActivityTrends;
    metrics: UserMetrics;
    sections: ExportSections;
    userName: string;
    userEmail: string;
    windowLabel: string;
    exportedAt?: Date;
}): string {
    const rows: string[] = [];
    const blank = () => rows.push('');

    rows.push('User Activity Export');
    rows.push(csvRow(['User', userName]));
    rows.push(csvRow(['Email', userEmail]));
    rows.push(csvRow(['Export Date', exportedAt.toLocaleString()]));
    rows.push(csvRow(['Data Period', windowLabel]));
    blank();

    if (sections.metrics) {
        rows.push('SUMMARY METRICS');
        rows.push(csvRow(['Metric', 'Value']));

        if (metrics.login_metrics) {
            rows.push(csvRow(['Total Logins', metrics.login_metrics.total_logins || 0]));
            rows.push(csvRow(['Last Login', metrics.login_metrics.last_login || 'Never']));
        }
        if (metrics.chat_metrics) {
            rows.push(csvRow(['Total Conversations', metrics.chat_metrics.total_conversations || 0]));
            rows.push(csvRow(['Total Messages', metrics.chat_metrics.total_messages || 0]));
            rows.push(
                csvRow([
                    'Total Message Size (bytes)',
                    metrics.chat_metrics.total_message_size || 0,
                ]),
            );
        }
        if (metrics.document_metrics) {
            rows.push(csvRow(['Total Documents', metrics.document_metrics.total_documents || 0]));
            rows.push(csvRow(['AI Search Size (bytes)', metrics.document_metrics.ai_search_size || 0]));
            rows.push(
                csvRow([
                    'Storage Size (bytes)',
                    metrics.document_metrics.storage_account_size || 0,
                ]),
            );
        }
        if (metrics.calculated_at) {
            rows.push(csvRow(['Metrics Calculated At', metrics.calculated_at]));
        }
        blank();
    }

    if (sections.logins && trends.logins) {
        rows.push(`LOGIN ACTIVITY (${windowLabel})`);
        rows.push(csvRow(['Date', 'Logins']));
        trends.logins.forEach((day) => rows.push(csvRow([day.date, day.count ?? 0])));
        blank();
    }

    if (sections.conversations && trends.conversations) {
        rows.push(`CONVERSATION ACTIVITY (${windowLabel})`);
        rows.push(csvRow(['Date', 'Conversations Created', 'Conversations Deleted']));
        const deletes = new Map(
            (trends.conversations.deletes ?? []).map((day) => [day.date, day.count ?? 0]),
        );
        (trends.conversations.creates ?? []).forEach((day) =>
            rows.push(csvRow([day.date, day.count ?? 0, deletes.get(day.date) ?? 0])),
        );
        blank();
    }

    if (sections.documents && trends.documents) {
        rows.push(`DOCUMENT ACTIVITY (${windowLabel})`);
        rows.push(csvRow(['Date', 'Documents Uploaded', 'Documents Deleted']));
        const deletes = new Map(
            (trends.documents.deletes ?? []).map((day) => [day.date, day.count ?? 0]),
        );
        (trends.documents.uploads ?? []).forEach((day) =>
            rows.push(csvRow([day.date, day.count ?? 0, deletes.get(day.date) ?? 0])),
        );
        blank();
    }

    if (sections.tokens && trends.tokens) {
        rows.push(`TOKEN USAGE (${windowLabel})`);
        rows.push(csvRow(['Date', 'Total Tokens']));
        trends.tokens.forEach((day) => rows.push(csvRow([day.date, day.tokens ?? 0])));
        blank();
    }

    return rows.join('\n');
}

/** The file name for a downloaded export, dated so successive exports do not collide. */
export function activityCsvFileName(exportedAt: Date = new Date()): string {
    return `activity_export_${exportedAt.toISOString().split('T')[0]}.csv`;
}
