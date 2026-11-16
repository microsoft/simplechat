// scaleFormat.ts
// Formatting and tone rules shared by every live readout in the Admin Settings Scale group.
//
// Redis metrics, the document access index, the caches, Cosmos maintenance and Cosmos
// throughput all report raw numbers and status codes. They are drawn by different cards,
// so the wording and the colour of "Not available", "Running" or "Failed" are decided once
// here. The rules follow the server-rendered page, which administrators already read: the
// same values come out as the same words in both interfaces.

/** How a readout is coloured. Mirrors the Bootstrap variants the classic page uses. */
export type ReadoutTone = 'ok' | 'info' | 'warn' | 'danger' | 'neutral';

/** A display string and the tone to draw it in. */
export interface ToneText {
    text: string;
    tone: ReadoutTone;
}

export const NOT_AVAILABLE = 'Not available';

/** A number from a JSON value, or null when there is none. */
export function toNumber(value: unknown): number | null {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
        return null;
    }
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

export function formatCount(value: unknown): string {
    const numeric = toNumber(value);
    return numeric === null ? NOT_AVAILABLE : numeric.toLocaleString();
}

/** A measurement with its unit, such as `12.5 ms` or `400 RU`. */
export function formatMetric(value: unknown, unit: string, maximumFractionDigits = 2): string {
    const numeric = toNumber(value);
    if (numeric === null) {
        return NOT_AVAILABLE;
    }
    return `${numeric.toLocaleString(undefined, { maximumFractionDigits })} ${unit}`;
}

export function formatPercent(value: unknown, maximumFractionDigits = 2): string {
    const numeric = toNumber(value);
    if (numeric === null) {
        return NOT_AVAILABLE;
    }
    return `${numeric.toLocaleString(undefined, { maximumFractionDigits })}%`;
}

export function formatRu(value: unknown): string {
    const count = formatCount(value);
    return count === NOT_AVAILABLE ? count : `${count} RU/s`;
}

/** A Redis TTL, where -1 means no expiry and -2 means the key is gone. */
export function formatTtl(seconds: unknown): string {
    const numeric = toNumber(seconds);
    if (numeric === null) {
        return NOT_AVAILABLE;
    }
    if (numeric === -2) {
        return 'Expired or missing';
    }
    if (numeric === -1) {
        return 'No expiry';
    }
    return `${numeric.toLocaleString()} sec`;
}

export function formatBytes(bytes: unknown): string {
    const numeric = toNumber(bytes);
    if (numeric === null || numeric < 0) {
        return NOT_AVAILABLE;
    }
    if (numeric >= 1024 * 1024) {
        return `${(numeric / (1024 * 1024)).toLocaleString(undefined, { maximumFractionDigits: 2 })} MB`;
    }
    if (numeric >= 1024) {
        return `${(numeric / 1024).toLocaleString(undefined, { maximumFractionDigits: 2 })} KB`;
    }
    return `${numeric.toLocaleString()} bytes`;
}

/** `succeeded_with_errors` becomes `Succeeded With Errors`, as on the classic page. */
export function humanizeStatus(value: unknown, empty = 'Not loaded'): string {
    const text = String(value ?? '').trim();
    if (!text) {
        return empty;
    }
    return text.replace(/_/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

/** An ISO timestamp in the reader's locale, or the raw text when it does not parse. */
export function formatTimestamp(value: unknown, empty = NOT_AVAILABLE): string {
    const text = String(value ?? '').trim();
    if (!text) {
        return empty;
    }
    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? text : parsed.toLocaleString();
}

/** How long ago a moment was, for "Updated 3 min ago" beside a refresh button. */
export function formatRelativeTime(at: number | null, now: number = Date.now()): string {
    if (at === null || !Number.isFinite(at)) {
        return 'Not loaded yet';
    }
    const seconds = Math.max(0, Math.round((now - at) / 1000));
    if (seconds < 45) {
        return 'Updated just now';
    }
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) {
        return `Updated ${minutes} min ago`;
    }
    const hours = Math.round(minutes / 60);
    if (hours < 24) {
        return `Updated ${hours} h ago`;
    }
    return `Updated ${new Date(at).toLocaleString()}`;
}

const OK_STATUSES = new Set([
    'succeeded',
    'skipped_completed',
    'completed',
    'dry_run_completed',
    'reconciled',
    'matched',
    'aligned',
]);
const INFO_STATUSES = new Set(['running', 'in_progress']);
const WARN_STATUSES = new Set([
    'succeeded_with_errors',
    'completed_with_errors',
    'reconciled_with_errors',
    'mismatch',
    'missing_expected_indexes',
]);
const DANGER_STATUSES = new Set(['failed', 'error']);

/** The tone of a maintenance, backfill, shadow or cleanup status code. */
export function maintenanceStatusTone(value: unknown): ReadoutTone {
    const status = String(value ?? '').trim().toLowerCase();
    if (OK_STATUSES.has(status)) {
        return 'ok';
    }
    if (INFO_STATUSES.has(status)) {
        return 'info';
    }
    if (WARN_STATUSES.has(status)) {
        return 'warn';
    }
    if (DANGER_STATUSES.has(status)) {
        return 'danger';
    }
    return 'neutral';
}

/** A maintenance status as words and tone together. */
export function describeMaintenanceStatus(value: unknown, empty = 'Not loaded'): ToneText {
    return { text: humanizeStatus(value, empty), tone: maintenanceStatusTone(value) };
}

/** Enabled/Disabled pills, where "on" is good news rather than a warning. */
export function describeEnabled(value: unknown, on = 'Enabled', off = 'Disabled'): ToneText {
    return value ? { text: on, tone: 'ok' } : { text: off, tone: 'neutral' };
}
