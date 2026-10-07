// adminOperations.ts
// The decisions behind the Operations sections of Admin Settings.
//
// Kept apart from the components because these are the parts worth executing in a test
// rather than reviewing by eye: who the Control Center admits under each combination of
// role switches, whether a save will restart a logging timer, and when a daily schedule
// in some other timezone next fires. All three are easy to get subtly wrong, and all
// three are invisible in a screenshot.
//
// Where the server decides something, the rule here mirrors it rather than inventing
// its own -- the server's answer is the one that is stored, so a readout that disagreed
// with it would be describing a schedule that does not exist.

import { asBoolean, asString, type AdminLoggingTimerKeys } from './adminFields';
import type { AdminNavGroup, Json } from './types';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

function has(record: Json, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(record, key);
}

/** A value as it will be after a save: the unsaved edit if there is one, else the stored one. */
function merged(settings: Json, draft: Json, key: string): unknown {
    return has(draft, key) ? draft[key] : settings[key];
}

// ---------------------------------------------------------------------------------
// Stored instants
// ---------------------------------------------------------------------------------

/**
 * A stored timestamp, read the way the server reads it.
 *
 * Values written in UTC carry an offset and are an exact instant. Older logging turnoff
 * times carry none: the server wrote them with its own local clock, which the browser has
 * no way of knowing, so they are reported as `legacy` and shown as written rather than
 * converted on a guess.
 */
export type StoredInstant =
    | { kind: 'none' }
    | { kind: 'instant'; at: Date }
    | { kind: 'legacy'; text: string };

const OFFSET_SUFFIX = /(?:z|[+-]\d{2}:?\d{2})$/i;

export function readStoredInstant(value: unknown): StoredInstant {
    const text = asString(value).trim();
    if (!text) {
        return { kind: 'none' };
    }
    if (!OFFSET_SUFFIX.test(text)) {
        return { kind: 'legacy', text };
    }
    // Python writes microseconds; Date only promises to read milliseconds.
    const at = new Date(text.replace(/(\.\d{3})\d+/, '$1'));
    return Number.isNaN(at.getTime()) ? { kind: 'none' } : { kind: 'instant', at };
}

// ---------------------------------------------------------------------------------
// Logging timers
// ---------------------------------------------------------------------------------

/** Mirrors `LOGGING_TIMER_UNIT_LIMITS` in functions_logging_timers.py. */
export const LOGGING_TIMER_UNIT_LIMITS = {
    minutes: [1, 120],
    hours: [1, 24],
    days: [1, 7],
    weeks: [1, 52],
} as const;

export type LoggingTimerUnit = keyof typeof LOGGING_TIMER_UNIT_LIMITS;

const UNIT_MS: Record<LoggingTimerUnit, number> = {
    minutes: MINUTE_MS,
    hours: HOUR_MS,
    days: DAY_MS,
    weeks: 7 * DAY_MS,
};

/** Mirrors `normalize_logging_timer_unit`: anything unsupported reads as hours. */
export function normalizeTimerUnit(unit: unknown): LoggingTimerUnit {
    const candidate = asString(unit).trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(LOGGING_TIMER_UNIT_LIMITS, candidate)
        ? (candidate as LoggingTimerUnit)
        : 'hours';
}

/** Mirrors `clamp_logging_timer_value`. */
export function clampTimerValue(
    value: unknown,
    unit: unknown,
): { value: number; unit: LoggingTimerUnit } {
    const normalizedUnit = normalizeTimerUnit(unit);
    const [minimum, maximum] = LOGGING_TIMER_UNIT_LIMITS[normalizedUnit];
    const parsed = typeof value === 'boolean' ? Number.NaN : Number.parseFloat(asString(value));
    const whole = Number.isFinite(parsed) ? Math.trunc(parsed) : 1;
    return { value: Math.min(Math.max(whole, minimum), maximum), unit: normalizedUnit };
}

/** How long a timer runs, in milliseconds. */
export function timerDurationMs(value: unknown, unit: unknown): number {
    const timer = clampTimerValue(value, unit);
    return timer.value * UNIT_MS[timer.unit];
}

/**
 * What a log's timer will do.
 *
 * `on-save` carries why a save would set a new turnoff time, because the honest wording
 * differs: an edit is about to restart the clock, while a timer with nothing stored has
 * never started and needs a save of its own.
 */
export type TimerReadout =
    | { kind: 'off' }
    | { kind: 'no-timer' }
    | { kind: 'on-save'; reason: 'changed' | 'enabling' | 'missing'; projected: Date }
    | { kind: 'scheduled'; at: Date }
    | { kind: 'overdue'; at: Date }
    | { kind: 'legacy'; text: string };

/**
 * Read a log's timer, preferring unsaved edits.
 *
 * Mirrors `resolve_logging_timer_settings`: a save recalculates the turnoff time only when
 * the timer switch, duration or unit changes, when the log is being switched on, or when no
 * usable time is stored. Any other save keeps the stored time, so the readout must not
 * claim a save would restart the clock when it would not.
 */
export function describeLoggingTimer(
    keys: AdminLoggingTimerKeys,
    settings: Json,
    draft: Json,
    now: Date,
): TimerReadout {
    if (!asBoolean(merged(settings, draft, keys.enabled_key))) {
        return { kind: 'off' };
    }
    const timerOn = asBoolean(merged(settings, draft, keys.timer_key));
    if (!timerOn) {
        return { kind: 'no-timer' };
    }

    const value = merged(settings, draft, keys.value_key) ?? 1;
    const unit = merged(settings, draft, keys.unit_key) ?? 'hours';
    const timer = clampTimerValue(value, unit);
    const projected = new Date(now.getTime() + timerDurationMs(timer.value, timer.unit));

    const changed =
        timerOn !== asBoolean(settings[keys.timer_key]) ||
        timer.value !== Number(settings[keys.value_key] ?? 1) ||
        timer.unit !== asString(settings[keys.unit_key] ?? 'hours');
    if (changed) {
        return { kind: 'on-save', reason: 'changed', projected };
    }
    if (!asBoolean(settings[keys.enabled_key])) {
        return { kind: 'on-save', reason: 'enabling', projected };
    }

    const stored = readStoredInstant(settings[keys.turnoff_key]);
    if (stored.kind === 'none') {
        return { kind: 'on-save', reason: 'missing', projected };
    }
    if (stored.kind === 'legacy') {
        return { kind: 'legacy', text: stored.text };
    }
    return stored.at.getTime() <= now.getTime()
        ? { kind: 'overdue', at: stored.at }
        : { kind: 'scheduled', at: stored.at };
}

// ---------------------------------------------------------------------------------
// Timezones
// ---------------------------------------------------------------------------------

interface ZonedParts {
    year: number;
    month: number;
    day: number;
    hour: number;
    minute: number;
    second: number;
}

const zonedFormatters = new Map<string, Intl.DateTimeFormat>();

function zonedFormatter(zone: string): Intl.DateTimeFormat {
    let formatter = zonedFormatters.get(zone);
    if (!formatter) {
        formatter = new Intl.DateTimeFormat('en-US', {
            timeZone: zone,
            hourCycle: 'h23',
            year: 'numeric',
            month: 'numeric',
            day: 'numeric',
            hour: 'numeric',
            minute: 'numeric',
            second: 'numeric',
        });
        zonedFormatters.set(zone, formatter);
    }
    return formatter;
}

/** The wall-clock reading of an instant in a zone. */
function partsInZone(instant: Date, zone: string): ZonedParts {
    const values: Record<string, number> = {};
    for (const part of zonedFormatter(zone).formatToParts(instant)) {
        if (part.type !== 'literal') {
            values[part.type] = Number(part.value);
        }
    }
    return {
        year: values.year,
        month: values.month,
        day: values.day,
        // Some engines still write midnight as 24 even when asked for a 0-23 clock.
        hour: values.hour % 24,
        minute: values.minute,
        second: values.second,
    };
}

/** Whether this browser recognises an IANA zone name. */
export function isKnownTimeZone(zone: string): boolean {
    if (!zone.trim()) {
        return false;
    }
    try {
        new Intl.DateTimeFormat('en-US', { timeZone: zone });
        return true;
    } catch {
        return false;
    }
}

/** A zone's offset from UTC at an instant, in minutes east of Greenwich. */
export function zoneOffsetMinutes(zone: string, instant: Date): number {
    const parts = partsInZone(instant, zone);
    const asUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
    const wholeSeconds = Math.floor(instant.getTime() / 1000) * 1000;
    return Math.round((asUtc - wholeSeconds) / MINUTE_MS);
}

/** `UTC-04:00`, for showing beside a zone name. */
export function formatUtcOffset(zone: string, instant: Date): string {
    const offset = zoneOffsetMinutes(zone, instant);
    const sign = offset < 0 ? '-' : '+';
    const absolute = Math.abs(offset);
    const hours = String(Math.floor(absolute / 60)).padStart(2, '0');
    const minutes = String(absolute % 60).padStart(2, '0');
    return `UTC${sign}${hours}:${minutes}`;
}

/**
 * The instant a wall-clock time on a calendar date happens in a zone.
 *
 * Resolved the way Python's zoneinfo resolves it with fold=0, which is what stores the
 * run: a time that happens twice, when the clocks go back, is its first occurrence, and
 * one that never happens, when they go forward, keeps the offset in force before the
 * change.
 */
export function wallTimeToInstant(
    zone: string,
    year: number,
    month: number,
    day: number,
    hour: number,
    minute: number,
): Date {
    const guess = Date.UTC(year, month - 1, day, hour, minute);
    const offsetBefore = zoneOffsetMinutes(zone, new Date(guess - 12 * HOUR_MS));
    const offsetAfter = zoneOffsetMinutes(zone, new Date(guess + 12 * HOUR_MS));
    const candidates = [...new Set([offsetBefore, offsetAfter])].map(
        (offset) => guess - offset * MINUTE_MS,
    );
    const matching = candidates.filter((candidate) => {
        const parts = partsInZone(new Date(candidate), zone);
        return (
            parts.year === year &&
            parts.month === month &&
            parts.day === day &&
            parts.hour === hour &&
            parts.minute === minute
        );
    });
    return new Date(matching.length ? Math.min(...matching) : guess - offsetBefore * MINUTE_MS);
}

const SCHEDULE_TIME = /^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$/;

/** Read an `HH:MM` refresh time, or null when it is not one. */
export function parseScheduleTime(value: unknown): { hour: number; minute: number } | null {
    const match = SCHEDULE_TIME.exec(asString(value).trim());
    return match ? { hour: Number(match[1]), minute: Number(match[2]) } : null;
}

/**
 * The next time a daily schedule fires after `now`.
 *
 * Mirrors `calculate_next_control_center_auto_refresh_run`: today's run if it is still
 * ahead, otherwise tomorrow's at the same wall-clock time. Null when the time or zone
 * cannot be read, in which case the server will refuse the save anyway.
 */
export function nextDailyRun(time: unknown, zone: string, now: Date): Date | null {
    const parsed = parseScheduleTime(time);
    if (!parsed || !isKnownTimeZone(zone)) {
        return null;
    }
    const today = partsInZone(now, zone);
    const todaysRun = wallTimeToInstant(zone, today.year, today.month, today.day, parsed.hour, parsed.minute);
    if (todaysRun.getTime() > now.getTime()) {
        return todaysRun;
    }
    const tomorrow = new Date(Date.UTC(today.year, today.month - 1, today.day + 1));
    return wallTimeToInstant(
        zone,
        tomorrow.getUTCFullYear(),
        tomorrow.getUTCMonth() + 1,
        tomorrow.getUTCDate(),
        parsed.hour,
        parsed.minute,
    );
}

/** The browser's own IANA zone, or an empty string when it will not say. */
export function viewerTimeZone(): string {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    } catch {
        return '';
    }
}

/**
 * Every zone this browser can name, for suggestions.
 *
 * Some engines leave UTC out of the list while accepting it, and an administrator may well
 * want it, so it is added.
 */
export function listTimeZones(): string[] {
    const zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
    return [...new Set(['UTC', ...zones])];
}

// ---------------------------------------------------------------------------------
// The daily Control Center refresh
// ---------------------------------------------------------------------------------

/** Where the schedule lives. Mirrors the keys `resolve_control_center_auto_refresh_settings` writes. */
export const CONTROL_CENTER_SCHEDULE_KEYS = {
    enabled: 'control_center_auto_refresh_enabled',
    time: 'control_center_auto_refresh_time',
    timezone: 'control_center_auto_refresh_timezone',
    nextRun: 'control_center_auto_refresh_next_run',
    lastRefresh: 'control_center_last_refresh',
} as const;

/** Mirrors the defaults seeded in functions_settings.py. */
export const CONTROL_CENTER_SCHEDULE_DEFAULTS = {
    enabled: true,
    time: '02:00',
    timezone: 'America/New_York',
} as const;

export type ScheduleReadout =
    | { kind: 'off' }
    | { kind: 'on-save'; projected: Date | null; time: string; timezone: string }
    | { kind: 'scheduled'; at: Date; time: string; timezone: string }
    | { kind: 'overdue'; at: Date; time: string; timezone: string }
    | { kind: 'unscheduled'; time: string; timezone: string };

function scheduleValue(source: Json, key: string, fallback: string): string {
    const value = asString(source[key]).trim();
    return value || fallback;
}

/**
 * Read the refresh schedule, preferring unsaved edits.
 *
 * Mirrors `resolve_control_center_auto_refresh_settings`: a save moves the next run only
 * when the switch, time or timezone changes. A stored run is otherwise kept, so it is what
 * the readout shows.
 */
export function describeRefreshSchedule(settings: Json, draft: Json, now: Date): ScheduleReadout {
    const keys = CONTROL_CENTER_SCHEDULE_KEYS;
    const defaults = CONTROL_CENTER_SCHEDULE_DEFAULTS;
    const enabledValue = merged(settings, draft, keys.enabled);
    const enabled = enabledValue === undefined ? defaults.enabled : asBoolean(enabledValue);
    if (!enabled) {
        return { kind: 'off' };
    }

    const effective = { ...settings, ...draft };
    const time = scheduleValue(effective, keys.time, defaults.time);
    const timezone = scheduleValue(effective, keys.timezone, defaults.timezone);

    const savedEnabled = settings[keys.enabled] === undefined
        ? defaults.enabled
        : asBoolean(settings[keys.enabled]);
    const savedTime = parseScheduleTime(scheduleValue(settings, keys.time, defaults.time));
    const draftTime = parseScheduleTime(time);
    const changed =
        enabled !== savedEnabled ||
        timezone !== scheduleValue(settings, keys.timezone, defaults.timezone) ||
        draftTime?.hour !== savedTime?.hour ||
        draftTime?.minute !== savedTime?.minute;
    if (changed) {
        return { kind: 'on-save', projected: nextDailyRun(time, timezone, now), time, timezone };
    }

    const stored = readStoredInstant(settings[keys.nextRun]);
    if (stored.kind !== 'instant') {
        return { kind: 'unscheduled', time, timezone };
    }
    return stored.at.getTime() <= now.getTime()
        ? { kind: 'overdue', at: stored.at, time, timezone }
        : { kind: 'scheduled', at: stored.at, time, timezone };
}

// ---------------------------------------------------------------------------------
// Control Center access
// ---------------------------------------------------------------------------------

export const CONTROL_CENTER_ACCESS_KEYS = {
    requireAdminRole: 'require_member_of_control_center_admin',
    allowDashboardReader: 'require_member_of_control_center_dashboard_reader',
} as const;

export type ControlCenterAccessLevel = 'full' | 'dashboard' | 'none';

export type ControlCenterRole = 'Admin' | 'ControlCenterAdmin' | 'ControlCenterDashboardReader';

export interface ControlCenterAccessRow {
    role: ControlCenterRole;
    access: ControlCenterAccessLevel;
}

/**
 * Who the Control Center admits, one role at a time.
 *
 * Mirrors `control_center_required` and the navigation templates. Each row is the role
 * held on its own; an account holding two of them gets the better of the two rows.
 */
export function controlCenterAccess(
    requireAdminRole: boolean,
    allowDashboardReader: boolean,
): ControlCenterAccessRow[] {
    return [
        { role: 'Admin', access: requireAdminRole ? 'none' : 'full' },
        { role: 'ControlCenterAdmin', access: requireAdminRole ? 'full' : 'none' },
        { role: 'ControlCenterDashboardReader', access: allowDashboardReader ? 'dashboard' : 'none' },
    ];
}

// ---------------------------------------------------------------------------------
// Restart-bound settings
// ---------------------------------------------------------------------------------

/**
 * How a setting the app only reads at startup compares with the running process.
 *
 * `unavailable` is for a setting that cannot take effect whatever is saved, such as
 * global logging with no Application Insights destination; another readout says why.
 */
export type RestartState =
    | { kind: 'unavailable' }
    | { kind: 'save-then-restart'; next: boolean }
    | { kind: 'restart'; saved: boolean; running: boolean }
    | { kind: 'in-sync'; running: boolean };

export function describeRestartState({
    saved,
    draft,
    running,
    available,
}: {
    saved: boolean;
    draft: boolean;
    running: boolean;
    available: boolean;
}): RestartState {
    if (!available) {
        return { kind: 'unavailable' };
    }
    if (draft !== saved) {
        return { kind: 'save-then-restart', next: draft };
    }
    if (saved !== running) {
        return { kind: 'restart', saved, running };
    }
    return { kind: 'in-sync', running };
}

// ---------------------------------------------------------------------------------
// Endpoints and links
// ---------------------------------------------------------------------------------

/**
 * The full address of a path on this deployment, or null when it would leave it.
 *
 * The address is pasted into monitoring tools and offered as a link, so it must be this
 * deployment's own: a path that resolves to another origin, or to a scheme such as
 * `javascript:`, is refused rather than shown.
 */
export function safeSameOriginUrl(path: string, origin: string): string | null {
    try {
        const base = new URL(origin);
        const url = new URL(path, base);
        return url.origin === base.origin ? url.href : null;
    } catch {
        return null;
    }
}

/** An outside link, such as the documentation site, kept only when it is plain HTTPS. */
export function safeHttpsUrl(value: unknown): string | null {
    if (typeof value !== 'string') {
        return null;
    }
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
    } catch {
        return null;
    }
}

/** Where a section lives on the classic page, whose address names a tab, not a section. */
export function findNavLocation(
    nav: AdminNavGroup[],
    sectionId: string,
): { groupLabel: string; tabId: string; tabLabel: string; sectionLabel: string } | null {
    for (const group of nav) {
        for (const tab of group.tabs) {
            const section = tab.sections.find((candidate) => candidate.id === sectionId);
            if (section) {
                return {
                    groupLabel: group.label,
                    tabId: tab.id,
                    tabLabel: tab.label,
                    sectionLabel: section.label,
                };
            }
        }
    }
    return null;
}

// ---------------------------------------------------------------------------------
// Deleting stored file processing logs
// ---------------------------------------------------------------------------------

/** The existing admin endpoint the server-rendered page uses for the same action. */
export const FILE_PROCESSING_LOG_CLEANUP_ENDPOINT = '/api/admin/settings/file-processing-logs/cleanup';

/** Mirrors `FILE_PROCESSING_LOG_AGE_UNITS` in functions_logging.py. */
export const LOG_CLEANUP_UNITS = [
    { value: 'days', label: 'Days' },
    { value: 'weeks', label: 'Weeks' },
    { value: 'months', label: 'Months (30 days)' },
] as const;

export type LogCleanupUnit = (typeof LOG_CLEANUP_UNITS)[number]['value'];

export type LogCleanupRequest =
    | { delete_all: true }
    | { delete_all: false; age: number; unit: LogCleanupUnit };

/**
 * Turn the cleanup form into a request, or say what is wrong with it.
 *
 * The confirmation sentence is built here as well, because it has to describe exactly
 * what the request will delete and nothing vaguer.
 */
export function buildLogCleanupRequest(
    mode: 'older' | 'all',
    ageText: string,
    unit: string,
): { request: LogCleanupRequest; confirmation: string } | { error: string } {
    if (mode === 'all') {
        return {
            request: { delete_all: true },
            confirmation: 'Delete every stored file processing log?',
        };
    }

    const age = Number(ageText.trim());
    if (!ageText.trim() || !Number.isInteger(age) || age < 1) {
        return { error: 'Enter a whole number greater than zero.' };
    }
    const selected = LOG_CLEANUP_UNITS.find((option) => option.value === unit);
    if (!selected) {
        return { error: 'Choose days, weeks or months.' };
    }
    const noun = age === 1 ? selected.value.replace(/s$/, '') : selected.value;
    return {
        request: { delete_all: false, age, unit: selected.value },
        confirmation: `Delete every file processing log older than ${age} ${noun}?`,
    };
}

// ---------------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------------

/** A date and time, in a given zone or the viewer's own. */
export function formatInstant(at: Date, zone?: string): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
        ...(zone ? { timeZone: zone } : {}),
    }).format(at);
}

/**
 * A stored "HH:MM" schedule time as the reader's locale writes it, so the readout says
 * "2:00 AM" where the time picker beside it does. It is a time of day with no date or
 * zone of its own, so it is formatted in UTC to keep any offset out of it.
 */
export function formatWallTime(time: unknown, locale?: string): string {
    const parsed = parseScheduleTime(time);
    if (!parsed) {
        return asString(time);
    }
    return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }).format(
        new Date(Date.UTC(2000, 0, 1, parsed.hour, parsed.minute)),
    );
}

/**
 * "in 3 hours", "12 minutes ago".
 *
 * Each unit takes over a little before it is exact, the way people round, so a turnoff
 * 59 minutes away reads as "in 1 hour" rather than "in 59 minutes", and one 23 hours
 * away as "tomorrow".
 */
export function formatRelative(at: Date, now: Date, locale?: string): string {
    const difference = at.getTime() - now.getTime();
    const distance = Math.abs(difference);
    const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    if (distance >= 22 * HOUR_MS) {
        return formatter.format(Math.round(difference / DAY_MS), 'day');
    }
    if (distance >= 45 * MINUTE_MS) {
        return formatter.format(Math.round(difference / HOUR_MS), 'hour');
    }
    return formatter.format(Math.round(difference / MINUTE_MS), 'minute');
}
