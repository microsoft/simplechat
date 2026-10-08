// accessRestriction.ts
// The call behind the V2 Access restricted page. The server decides everything -- whether the
// account is restricted, until when, and what the user was told -- so the page only renders
// what this returns. The route only ever describes the signed-in user's own account.

import { request } from './apiClient';
import type { TermsOfUseBranding } from './termsOfUse';

export type AccessRestrictionKind = 'suspended' | 'blocked';

export interface AccessRestriction {
    kind: AccessRestrictionKind;
    /** ISO 8601 UTC. Set only for a suspension, which ends on its own. */
    until: string | null;
    /** Plain text. Rendered as text, never as HTML. */
    title: string;
    /** Plain text. Rendered as text, never as HTML. */
    message: string;
    /** The safety violation the restriction was applied for, when there is one. */
    referenceId: string | null;
}

export interface AccessRestrictionStatus {
    restricted: boolean;
    restriction: AccessRestriction | null;
    branding: Partial<TermsOfUseBranding>;
}

/** Shown when the server sends no notice text, matching the server's own fallback copy. */
const FALLBACK_COPY: Record<AccessRestrictionKind, { title: string; message: string }> = {
    suspended: {
        title: 'Your access is temporarily suspended',
        message:
            'An administrator has temporarily suspended your access to this application. '
            + 'Your access is restored automatically at the time shown.',
    },
    blocked: {
        title: 'Your access has been blocked',
        message:
            'An administrator has blocked your access to this application. '
            + 'Contact your administrator if you have questions about this decision.',
    },
};

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/** Read the route's answer defensively; anything it can't vouch for falls back to safe copy. */
export function parseAccessRestrictionStatus(payload: unknown): AccessRestrictionStatus {
    const body = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
    const branding = (body.branding && typeof body.branding === 'object'
        ? body.branding
        : {}) as Partial<TermsOfUseBranding>;
    if (body.restricted !== true) {
        return { restricted: false, restriction: null, branding };
    }
    const raw = (body.restriction && typeof body.restriction === 'object'
        ? body.restriction
        : {}) as Record<string, unknown>;
    const kind: AccessRestrictionKind = raw.kind === 'suspended' && text(raw.until) ? 'suspended' : 'blocked';
    return {
        restricted: true,
        restriction: {
            kind,
            until: kind === 'suspended' ? text(raw.until) : null,
            title: text(raw.title) || FALLBACK_COPY[kind].title,
            message: text(raw.message) || FALLBACK_COPY[kind].message,
            referenceId: text(raw.reference_id) || null,
        },
        branding,
    };
}

export async function fetchAccessRestriction(signal?: AbortSignal): Promise<AccessRestrictionStatus> {
    return parseAccessRestrictionStatus(
        await request<unknown>('/api/v2/access-restriction', { signal }),
    );
}

/** A restore time in the reader's own locale and time zone, or null when it can't be read. */
export function formatRestoreTime(until: string | null | undefined, locale?: string): string | null {
    if (!until) {
        return null;
    }
    const parsed = new Date(until);
    if (Number.isNaN(parsed.getTime())) {
        return null;
    }
    try {
        return parsed.toLocaleString(locale, { dateStyle: 'full', timeStyle: 'short' });
    } catch {
        return parsed.toLocaleString();
    }
}
