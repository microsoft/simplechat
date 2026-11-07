// retentionPolicy.ts
// Pure helpers behind the Retention Policy controls in Admin Settings.
//
// Kept apart from the components so the decisions that have to be exactly right -- which
// workspace types a run may touch, whether unsaved edits block it, what an hour or a
// stored timestamp reads as, and how the server's response is summarised -- can be
// executed in a test instead of judged from a screenshot.
//
// Nothing here talks to the network. The components call the existing
// /api/admin/retention-policy/* routes and hand the responses to these functions.

import { ApiError } from './apiClient';
import { asBoolean } from './adminFields';
import type { Json } from './types';

export type RetentionScope = 'personal' | 'group' | 'public';

export const RETENTION_SCOPES: readonly RetentionScope[] = ['personal', 'group', 'public'];

export const RETENTION_SCOPE_LABELS: Readonly<Record<RetentionScope, string>> = {
    personal: 'Personal workspaces',
    group: 'Group workspaces',
    public: 'Public workspaces',
};

/** What a run's "affected" count is counted in, per type. */
export const RETENTION_AFFECTED_NOUNS: Readonly<Record<RetentionScope, readonly [string, string]>> = {
    personal: ['user', 'users'],
    group: ['group', 'groups'],
    public: ['workspace', 'workspaces'],
};

export const RETENTION_EXECUTION_HOUR_KEY = 'retention_policy_execution_hour';
export const RETENTION_LAST_RUN_KEY = 'retention_policy_last_run';
export const RETENTION_NEXT_RUN_KEY = 'retention_policy_next_run';
export const CONVERSATION_ARCHIVING_KEY = 'enable_conversation_archiving';

/** Mirrors RETENTION_EXECUTION_HOUR_DEFAULT in admin_settings_fields.py. */
export const RETENTION_EXECUTION_HOUR_DEFAULT = 2;

export interface RetentionScopeKeys {
    enabled: string;
    conversation: string;
    document: string;
}

export function retentionScopeKeys(scope: RetentionScope): RetentionScopeKeys {
    return {
        enabled: `enable_retention_policy_${scope}`,
        conversation: `default_retention_conversation_${scope}`,
        document: `default_retention_document_${scope}`,
    };
}

/**
 * Every stored setting a reset depends on.
 *
 * An unsaved edit to any of these blocks Reset: the server works from what is saved, so
 * running it beside a different, unsaved set of defaults would apply something other than
 * what is on screen.
 */
export const RETENTION_SETTING_KEYS: readonly string[] = [
    ...RETENTION_SCOPES.flatMap((scope) => {
        const keys = retentionScopeKeys(scope);
        return [keys.enabled, keys.conversation, keys.document];
    }),
    RETENTION_EXECUTION_HOUR_KEY,
];

/** A run also reads whether to archive conversations before removing them. */
export const RETENTION_RUN_KEYS: readonly string[] = [
    ...RETENTION_SETTING_KEYS,
    CONVERSATION_ARCHIVING_KEY,
];

/** Which of `keys` hold an unsaved edit. */
export function unsavedKeys(draft: Json, keys: readonly string[]): string[] {
    return keys.filter((key) => Object.prototype.hasOwnProperty.call(draft, key));
}

/** Workspace types whose retention is switched on in the saved settings. */
export function savedEnabledScopes(settings: Json): RetentionScope[] {
    return RETENTION_SCOPES.filter((scope) => asBoolean(settings[retentionScopeKeys(scope).enabled]));
}

/**
 * A retention period as people read it.
 *
 * Mirrors resolve_retention_value on the server: anything that is not a positive whole
 * number of days means nothing is deleted.
 */
export function retentionPeriodLabel(value: unknown): string {
    const days = readRetentionDays(value);
    return days ? `${days} day${days === 1 ? '' : 's'}` : 'No automatic deletion';
}

/** "deleted after 30 days" or "kept", for a sentence about what a default does. */
export function retentionDefaultPhrase(value: unknown): string {
    const days = readRetentionDays(value);
    return days ? `deleted after ${days} day${days === 1 ? '' : 's'}` : 'kept';
}

/**
 * What a workspace type's saved defaults mean for a run or a reset, in one sentence.
 *
 * When both defaults keep everything the useful fact is who a run can still touch -- only
 * those who chose their own period -- so that is what is said instead of "kept, kept".
 */
export function scopeDefaultsSummary(
    settings: Json,
    scope: RetentionScope,
    action: 'run' | 'reset',
): string {
    const keys = retentionScopeKeys(scope);
    const conversation = retentionDefaultPhrase(settings[keys.conversation]);
    const document = retentionDefaultPhrase(settings[keys.document]);
    if (conversation === 'kept' && document === 'kept') {
        return action === 'run'
            ? `Defaults keep everything, so only ${RETENTION_AFFECTED_NOUNS[scope][1]} with their own period are affected.`
            : 'Will follow defaults that keep everything.';
    }
    const detail = `conversations ${conversation}, documents ${document}.`;
    return action === 'run' ? `Defaults: ${detail}` : `Will follow: ${detail}`;
}

function readRetentionDays(value: unknown): number | null {
    const text = String(value ?? '').trim();
    if (!/^\d+$/.test(text)) {
        return null;
    }
    const days = Number.parseInt(text, 10);
    return days > 0 ? days : null;
}

/** The saved hour, read defensively: settings written by hand may hold a string. */
export function readExecutionHour(value: unknown): number {
    const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
    return Number.isInteger(parsed) && parsed >= 0 && parsed <= 23
        ? parsed
        : RETENTION_EXECUTION_HOUR_DEFAULT;
}

/** The keys whose saved change moves the next run. Mirrors RETENTION_SCHEDULE_KEYS. */
export const RETENTION_SCHEDULE_KEYS: readonly string[] = [
    ...RETENTION_SCOPES.map((scope) => retentionScopeKeys(scope).enabled),
    RETENTION_EXECUTION_HOUR_KEY,
];

/**
 * Whether saving the draft will move the next run.
 *
 * Mirrors _apply_retention_schedule: a schedule key has to be in the save, and either its
 * value differs from what is stored or no next run is stored yet. A switch flipped and
 * flipped back is still in the draft but moves nothing.
 */
export function willReschedule(settings: Json, draft: Json): boolean {
    const submitted = unsavedKeys(draft, RETENTION_SCHEDULE_KEYS);
    if (!submitted.length) {
        return false;
    }
    const changed = submitted.some((key) => draft[key] !== settings[key]);
    return changed || !settings[RETENTION_NEXT_RUN_KEY];
}

/**
 * The next run a save would schedule for `hour`, as an ISO timestamp.
 *
 * Mirrors compute_retention_next_run: today at that hour UTC, or tomorrow once it has
 * passed.
 */
export function projectNextRun(hour: number, now: Date = new Date()): string {
    const next = new Date(
        Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, 0, 0, 0),
    );
    if (next.getTime() <= now.getTime()) {
        next.setUTCDate(next.getUTCDate() + 1);
    }
    return next.toISOString();
}

/** `02:00 UTC (2 AM)` -- the option wording for the run-time select. */
export function utcHourLabel(hour: number): string {
    const clock = `${String(hour).padStart(2, '0')}:00 UTC`;
    const spoken =
        hour === 0 ? 'midnight' : hour === 12 ? 'noon' : hour < 12 ? `${hour} AM` : `${hour - 12} PM`;
    return `${clock} (${spoken})`;
}

/**
 * The run hour on the reader's own clock, or null when their clock already reads UTC.
 *
 * Worked out for today's date, so a daylight-saving change is reflected the day it happens.
 * `timeZone` and `locale` exist for tests; the browser's own are used otherwise.
 */
export function localTimeForUtcHour(
    hour: number,
    now: Date = new Date(),
    { locale, timeZone }: { locale?: string; timeZone?: string } = {},
): string | null {
    const instant = new Date(
        Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, 0, 0),
    );
    const parts = new Intl.DateTimeFormat('en-US', {
        hour: 'numeric',
        minute: 'numeric',
        hourCycle: 'h23',
        timeZone,
    }).formatToParts(instant);
    const localHour = Number(parts.find((part) => part.type === 'hour')?.value);
    const localMinute = Number(parts.find((part) => part.type === 'minute')?.value);
    if (localHour === hour && localMinute === 0) {
        return null;
    }
    return new Intl.DateTimeFormat(locale, {
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
        timeZone,
    }).format(instant);
}

/** Parse a stored ISO timestamp, tolerating Python's six fractional digits. */
export function parseStoredTimestamp(value: unknown): Date | null {
    const text = typeof value === 'string' ? value.trim() : '';
    if (!text) {
        return null;
    }
    const parsed = new Date(text.replace(/(\.\d{3})\d+/, '$1'));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** "in 12 hours", "yesterday", "3 days ago". */
export function relativeTimeLabel(date: Date, now: Date = new Date(), locale?: string): string {
    const difference = date.getTime() - now.getTime();
    const distance = Math.abs(difference);
    const minute = 60_000;
    const hour = 60 * minute;
    const day = 24 * hour;
    if (distance < minute) {
        return difference >= 0 ? 'in under a minute' : 'just now';
    }
    const [amount, unit]: [number, Intl.RelativeTimeFormatUnit] =
        distance < hour
            ? [Math.round(distance / minute), 'minute']
            : distance < day
              ? [Math.round(distance / hour), 'hour']
              : [Math.round(distance / day), 'day'];
    return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(
        difference >= 0 ? amount : -amount,
        unit,
    );
}

export interface RunTimeReadout {
    /** The moment in UTC, which is what the schedule is set in. */
    absolute: string;
    relative: string;
    /** Whether the moment has already passed. */
    past: boolean;
    iso: string;
}

export function describeRunTime(
    value: unknown,
    now: Date = new Date(),
    locale?: string,
): RunTimeReadout | null {
    const date = parseStoredTimestamp(value);
    if (!date) {
        return null;
    }
    return {
        absolute: new Intl.DateTimeFormat(locale, {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZone: 'UTC',
            timeZoneName: 'short',
        }).format(date),
        relative: relativeTimeLabel(date, now, locale),
        past: date.getTime() <= now.getTime(),
        iso: date.toISOString(),
    };
}

function readCount(value: unknown): number {
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
}

function asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function readScopes(value: unknown, fallback: readonly RetentionScope[]): RetentionScope[] {
    if (!Array.isArray(value)) {
        return [...fallback];
    }
    const named = value.filter((item): item is RetentionScope =>
        (RETENTION_SCOPES as readonly unknown[]).includes(item),
    );
    return RETENTION_SCOPES.filter((scope) => named.includes(scope));
}

export interface RetentionRunRow {
    scope: RetentionScope;
    conversations: number;
    documents: number;
    affected: number;
}

export interface RetentionRunSummary {
    ok: boolean;
    rows: RetentionRunRow[];
    conversations: number;
    documents: number;
    /**
     * How many problems the run reported. The server's text is not shown: it can be a raw
     * exception message, which is for the logs rather than the browser.
     */
    errorCount: number;
}

/** Summarise `POST /api/admin/retention-policy/execute`. */
export function summarizeRetentionRun(
    response: unknown,
    requested: readonly RetentionScope[],
): RetentionRunSummary {
    const body = asRecord(response);
    const results = asRecord(body.results);
    const scopes = readScopes(results.scopes_processed, requested);
    const rows = scopes.map((scope) => {
        const counts = asRecord(results[scope]);
        return {
            scope,
            conversations: readCount(counts.conversations),
            documents: readCount(counts.documents),
            affected: readCount(scope === 'personal' ? counts.users_affected : counts.workspaces_affected),
        };
    });
    const errors = Array.isArray(results.errors) ? results.errors.length : 0;
    return {
        ok: body.success !== false && results.success !== false,
        rows,
        conversations: rows.reduce((total, row) => total + row.conversations, 0),
        documents: rows.reduce((total, row) => total + row.documents, 0),
        errorCount: errors,
    };
}

export interface RetentionResetSummary {
    ok: boolean;
    rows: { scope: RetentionScope; updated: number }[];
    total: number;
}

/** Summarise `POST /api/admin/retention-policy/force-push`. */
export function summarizeRetentionReset(
    response: unknown,
    requested: readonly RetentionScope[],
): RetentionResetSummary {
    const body = asRecord(response);
    const details = asRecord(body.details);
    const rows = readScopes(body.scopes, requested).map((scope) => ({
        scope,
        updated: readCount(details[scope]),
    }));
    return {
        ok: body.success !== false,
        rows,
        total: readCount(body.updated_count) || rows.reduce((total, row) => total + row.updated, 0),
    };
}

/**
 * What to say when a run or reset request fails.
 *
 * A 400 carries a validation message the route wrote for people, so it is shown. Anything
 * else is described rather than quoted, because a 500 from these routes can carry raw
 * exception text. A gateway timeout or a dropped connection gets its own wording: the work
 * keeps going on the server after the browser stops waiting.
 */
export function retentionRequestError(error: unknown, action: 'run' | 'reset'): string {
    if (error instanceof ApiError) {
        if (error.status === 400) {
            const payload = asRecord(error.payload);
            if (typeof payload.error === 'string' && payload.error.trim()) {
                return payload.error.trim();
            }
        }
        if (error.isAuthError) {
            return 'Your session no longer has administrator access. Sign in again, then retry.';
        }
        if (error.status !== 502 && error.status !== 503 && error.status !== 504) {
            return action === 'run'
                ? 'Retention could not finish. Check the application logs for the cause.'
                : 'The reset could not finish. Check the application logs for the cause.';
        }
    }
    return action === 'run'
        ? 'The page stopped waiting before retention reported back. It may still be running; check Last run in a few minutes.'
        : 'The page stopped waiting before the reset reported back. Some workspaces may already follow the defaults.';
}
