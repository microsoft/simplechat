// foundryAuth.ts

import type { ChatStreamEvent } from './types';
import { apiUrl } from './apiClient';

/** Keep a handoff URL on the authenticated API origin before exposing it to a link. */
export function normalizeFoundryAuthUrl(value: unknown): string | null {
    if (typeof value !== 'string' || !value.trim()) {
        return null;
    }
    try {
        const apiBase = new URL(apiUrl('/'), window.location.origin);
        const rawUrl = value.trim();
        const path = rawUrl.startsWith('/') && !rawUrl.startsWith('//') ? apiUrl(rawUrl) : rawUrl;
        const url = new URL(path, apiBase);
        if (
            (url.protocol === 'https:' || url.protocol === 'http:') &&
            url.origin === apiBase.origin &&
            !url.username && !url.password
        ) {
            return url.href;
        }
    } catch {
        // Malformed or revoked handoffs must not become executable browser links.
    }
    return null;
}

/** Consent starts on our authenticated route, never at an event-supplied external site. */
export function foundryAuthUrl(event?: ChatStreamEvent): string | null {
    if (event?.auth_required !== true) {
        return null;
    }
    for (const value of [event.auth_url, event.consent_url]) {
        const normalized = normalizeFoundryAuthUrl(value);
        if (normalized) return normalized;
    }
    return null;
}
