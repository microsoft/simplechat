// safetyWarnings.ts
// Safety warnings an administrator sent the signed-in user. A warning has to be acknowledged:
// it stays on screen until the user says they understand it. The server keeps the record of
// which warnings are still waiting, so a reload, another tab or another device shows them too.
//
// Everything here is the user's own data -- what they were sent and when -- rendered as text.

import { api } from './apiClient';

export interface SafetyWarningCategory {
    category: string;
    severity: number | null;
}

export interface SafetyWarning {
    /**
     * The safety violation the warning was sent for. A reviewer can warn about the same
     * violation again, so one warning is this with `issuedAt`: see safetyWarningKey.
     */
    id: string;
    /** Plain text. Rendered as text, never as HTML. */
    title: string;
    /** Plain text. Rendered as text, never as HTML. */
    message: string;
    issuedAt: string | null;
    categories: SafetyWarningCategory[];
}

/** The server's answer when the warning acknowledged was replaced by a newer one. */
export const SAFETY_WARNING_REPLACED_CODE = 'safety_warning_replaced';

const FALLBACK_TITLE = 'Safety Violation Warning';

/** Identifies one warning sent: the violation, and when it was sent. */
export function safetyWarningKey(warning: Pick<SafetyWarning, 'id' | 'issuedAt'>): string {
    return JSON.stringify([warning.id, warning.issuedAt]);
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function parseCategory(value: unknown): SafetyWarningCategory[] {
    if (!value || typeof value !== 'object') {
        return [];
    }
    const raw = value as Record<string, unknown>;
    const category = text(raw.category);
    if (!category) {
        return [];
    }
    const severity = typeof raw.severity === 'number' && Number.isFinite(raw.severity) ? raw.severity : null;
    return [{ category, severity }];
}

/** One warning from the route, or null when it isn't one the dialog can show. */
export function parseSafetyWarning(value: unknown): SafetyWarning | null {
    if (!value || typeof value !== 'object') {
        return null;
    }
    const raw = value as Record<string, unknown>;
    const id = text(raw.id);
    const message = text(raw.message);
    if (!id || !message) {
        return null;
    }
    return {
        id,
        title: text(raw.title) || FALLBACK_TITLE,
        message,
        issuedAt: text(raw.issued_at) || null,
        categories: Array.isArray(raw.triggered_categories)
            ? raw.triggered_categories.flatMap(parseCategory)
            : [],
    };
}

/** The route's answer, oldest warning first. Throws when the answer isn't a warning list. */
export function parsePendingSafetyWarnings(payload: unknown): SafetyWarning[] {
    const body = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
    if (!Array.isArray(body.warnings)) {
        throw new Error('The pending warnings response was invalid.');
    }
    return body.warnings
        .map(parseSafetyWarning)
        .filter((warning): warning is SafetyWarning => warning !== null);
}

export async function fetchPendingSafetyWarnings(signal?: AbortSignal): Promise<SafetyWarning[]> {
    return parsePendingSafetyWarnings(await api.get<unknown>('/api/safety/warnings/pending', signal));
}

/**
 * Acknowledge the warning the user read. Sending when it was sent lets the server refuse
 * (409 SAFETY_WARNING_REPLACED_CODE) when the violation has since been warned about again.
 */
export async function acknowledgeSafetyWarning(warning: Pick<SafetyWarning, 'id' | 'issuedAt'>): Promise<void> {
    await api.post(
        `/api/safety/warnings/${encodeURIComponent(warning.id)}/acknowledge`,
        warning.issuedAt ? { issued_at: warning.issuedAt } : {},
    );
}

/** The flagged categories as one line, such as "Hate (severity 4), Violence (severity 2)". */
export function describeSafetyWarningCategories(categories: SafetyWarningCategory[]): string {
    return categories
        .map(({ category, severity }) => (severity === null ? category : `${category} (severity ${severity})`))
        .join(', ');
}

/** When a warning was sent, in the reader's own locale, or null when it can't be read. */
export function formatSafetyWarningDate(value: string | null, locale?: string): string | null {
    if (!value) {
        return null;
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return null;
    }
    try {
        return parsed.toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' });
    } catch {
        return parsed.toLocaleString();
    }
}
