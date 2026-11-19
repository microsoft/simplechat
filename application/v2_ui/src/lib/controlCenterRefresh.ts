// controlCenterRefresh.ts
// The decisions behind the Control Center's "Refresh data" strip.
//
// The Users and Groups views, and the figures on the Dashboard that come from them, read stored
// snapshots of each user's and group's activity rather than counting live. A refresh
// recalculates those snapshots for everyone. It runs by itself on a daily schedule and on
// demand from the Control Center, and what an administrator needs to see is when it last
// ran, when it runs next, and whether the run they just asked for covered everyone.
//
// Kept apart from the component because the wording is the part worth executing in a test:
// a refresh that skipped some people must not read as a clean one, and a missing timestamp
// must not read as "never". Both routes sit behind the admin level of Control Center access
// (`control_center_required('admin')`), so the strip is drawn only for the capability that
// decorator checks.

import { asBoolean, asString } from './adminFields';
import {
    formatInstant,
    formatRelative,
    formatWallTime,
    readStoredInstant,
    type StoredInstant,
} from './adminOperations';

/** `POST` recalculates every user's and group's stored figures. */
export const CONTROL_CENTER_REFRESH_ENDPOINT = '/api/admin/control-center/refresh';

/** `GET` reports the last refresh and the daily schedule. */
export const CONTROL_CENTER_REFRESH_STATUS_ENDPOINT = '/api/admin/control-center/refresh-status';

/** What `GET /api/admin/control-center/refresh-status` says, read defensively. */
export interface RefreshStatus {
    last: StoredInstant;
    /** A value was stored but could not be read as a time, which is not the same as never. */
    lastUnreadable: boolean;
    autoEnabled: boolean;
    autoTime: string;
    autoTimezone: string;
    /** The next scheduled run, or null when none is scheduled or the value is unreadable. */
    nextRun: Date | null;
}

export function readRefreshStatus(payload: unknown): RefreshStatus | null {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        return null;
    }
    const source = payload as Record<string, unknown>;
    const last = readStoredInstant(source.last_refresh);
    const next = readStoredInstant(source.auto_refresh_next_run_utc);
    return {
        last,
        lastUnreadable: last.kind === 'none' && asString(source.last_refresh).trim().length > 0,
        autoEnabled: asBoolean(source.auto_refresh_enabled),
        autoTime: asString(source.auto_refresh_time).trim(),
        autoTimezone: asString(source.auto_refresh_timezone).trim(),
        nextRun: next.kind === 'instant' ? next.at : null,
    };
}

/** How many users and groups a refresh covered, and how many it could not. */
export interface RefreshOutcome {
    users: number;
    groups: number;
    failedUsers: number;
    failedGroups: number;
}

function count(value: unknown): number {
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

/**
 * Read the answer to a refresh, or null when it does not say the run succeeded.
 *
 * A success the server reports without counts still counts as one: it carries zeros, which
 * the wording below states plainly rather than hiding.
 */
export function readRefreshOutcome(payload: unknown): RefreshOutcome | null {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        return null;
    }
    const source = payload as Record<string, unknown>;
    if (source.success !== true) {
        return null;
    }
    return {
        users: count(source.refreshed_users),
        groups: count(source.refreshed_groups),
        failedUsers: count(source.failed_users),
        failedGroups: count(source.failed_groups),
    };
}

function plural(amount: number, noun: string): string {
    return `${amount.toLocaleString()} ${noun}${amount === 1 ? '' : 's'}`;
}

/**
 * Say what a finished refresh did.
 *
 * A run that skipped anyone is a warning, not a success: the figures for those people are
 * as old as before, and a green message would send the administrator away believing otherwise.
 */
export function describeRefreshOutcome(outcome: RefreshOutcome): { tone: 'success' | 'warning'; text: string } {
    const updated = `${plural(outcome.users, 'user')} and ${plural(outcome.groups, 'group')}`;
    const failed: string[] = [];
    if (outcome.failedUsers) {
        failed.push(plural(outcome.failedUsers, 'user'));
    }
    if (outcome.failedGroups) {
        failed.push(plural(outcome.failedGroups, 'group'));
    }
    if (!failed.length) {
        return { tone: 'success', text: `Data refreshed. Updated ${updated}.` };
    }
    return {
        tone: 'warning',
        text: `Data refreshed with problems. Updated ${updated}; ${failed.join(' and ')} could not be refreshed.`,
    };
}

/** When the figures were last recalculated, in the reader's own time. */
export function describeLastRefresh(status: RefreshStatus, now: Date, locale?: string): string {
    const { last } = status;
    if (last.kind === 'instant') {
        return `Data last refreshed ${formatInstant(last.at)} (${formatRelative(last.at, now, locale)}).`;
    }
    if (last.kind === 'legacy') {
        // An old value carries no zone, so it is shown as written rather than converted on a guess.
        return `Data last refreshed ${last.text}, server time.`;
    }
    return status.lastUnreadable
        ? 'The time of the last refresh could not be read.'
        : 'Data has not been refreshed yet.';
}

/** The daily schedule and its next run, or that there is none. */
export function describeAutoRefresh(status: RefreshStatus, now: Date, locale?: string): string {
    if (!status.autoEnabled) {
        return 'Automatic refresh is off.';
    }
    const schedule = status.autoTime
        ? `daily at ${formatWallTime(status.autoTime, locale)}${status.autoTimezone ? ` ${status.autoTimezone}` : ''}`
        : 'daily';
    return status.nextRun
        ? `Automatic refresh ${schedule}; next ${formatInstant(status.nextRun)} (${formatRelative(status.nextRun, now, locale)}).`
        : `Automatic refresh ${schedule}.`;
}
