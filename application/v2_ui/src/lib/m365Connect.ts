// m365Connect.ts
// Connects Microsoft 365 for orchestration steps that stopped for sign-in.
//
// The flow is the classic Profile reconnect: the server starts an authorization code flow
// for the named sources and stores the result in the signed-in session. The sign-in runs in
// a popup that ends on the Profile page, which tells its opener it connected. That message
// can be lost when the popup visits Microsoft sign-in or the API is on another origin, so
// the saved connection is checked when the popup closes.

import { apiUrl, request } from './apiClient';

export type M365Source = 'calendar' | 'email' | 'onedrive' | 'spo';

const M365_SOURCES: ReadonlySet<string> = new Set(['calendar', 'email', 'onedrive', 'spo']);
const POPUP_NAME = 'simplechat-m365-orchestration-connect';
const POPUP_FEATURES = 'popup,width=720,height=780,resizable=yes,scrollbars=yes';
const CONNECT_TIMEOUT_MS = 300_000;
const POPUP_POLL_MS = 500;
const INVALID_URL_MESSAGE = 'The server did not return a valid HTTPS Microsoft 365 sign-in URL.';

/** Classic pages that own Microsoft 365 connections and approvals, on the Flask origin. */
export const M365_PROFILE_CONNECTION_HREF = apiUrl('/profile?tab=settings#m365-chat-connection');
export const M365_APPROVALS_HREF = apiUrl('/approvals');

interface ChatConnection {
    status?: string;
    sources?: unknown;
    connected_at?: string;
}

interface ChatConnectionResponse {
    connection?: ChatConnection;
    csrf_token?: string;
}

interface ConnectResponse {
    authorization_url?: unknown;
}

/** Only known Microsoft 365 sources, in a stable order and without duplicates. */
export function m365Sources(values: unknown): M365Source[] {
    if (!Array.isArray(values)) return [];
    return Array.from(new Set(values.filter((value): value is M365Source => (
        typeof value === 'string' && M365_SOURCES.has(value)
    )))).sort();
}

/** A Microsoft sign-in URL the browser may navigate to: HTTPS, with a host and no credentials. */
export function authorizationUrl(value: unknown): string {
    if (typeof value !== 'string' || !value.trim()) throw new Error(INVALID_URL_MESSAGE);
    let target: URL;
    try {
        target = new URL(value);
    } catch {
        throw new Error(INVALID_URL_MESSAGE);
    }
    // The server validates the configured authority, including sovereign and custom clouds.
    if (target.protocol !== 'https:' || !target.hostname || target.username || target.password) {
        throw new Error(INVALID_URL_MESSAGE);
    }
    return target.href;
}

function connectionCovers(connection: ChatConnection | undefined, sources: M365Source[], before?: string): boolean {
    const connected = m365Sources(connection?.sources);
    return connection?.status === 'available'
        && typeof connection.connected_at === 'string'
        && connection.connected_at !== before
        && sources.every((source) => connected.includes(source));
}

/**
 * Sign in to Microsoft 365 for these sources. Resolves once the sign-in is saved for this
 * session; rejects with a user-facing message otherwise. Call it from a click handler: the
 * popup opens before anything is awaited, so the browser does not block it.
 */
export function connectMicrosoft365(sources: M365Source[]): Promise<void> {
    if (!sources.length) {
        return Promise.reject(new Error('Open Profile settings to choose the Microsoft 365 sources to connect.'));
    }
    const popup = window.open('about:blank', POPUP_NAME, POPUP_FEATURES);
    if (!popup) {
        return Promise.reject(new Error(
            'The sign-in window was blocked. Allow pop-ups for this site, or connect Microsoft 365 in Profile settings.',
        ));
    }
    const apiOrigin = new URL(apiUrl('/'), window.location.origin).origin;
    return new Promise<void>((resolve, reject) => {
        let finished = false;
        let checking = false;
        let connectedBefore: string | undefined;
        const finish = (error?: Error) => {
            if (finished) return;
            finished = true;
            window.clearInterval(poll);
            window.clearTimeout(timeout);
            window.removeEventListener('message', onMessage);
            if (!popup.closed) popup.close();
            if (error) reject(error);
            else resolve();
        };
        const onMessage = (event: MessageEvent) => {
            if (
                event.source === popup
                && (event.origin === window.location.origin || event.origin === apiOrigin)
                && (event.data as { type?: unknown } | null)?.type === 'm365-profile-reconnected'
            ) {
                finish();
            }
        };
        const confirmAfterClose = async () => {
            if (checking || finished) return;
            checking = true;
            try {
                const latest = await request<ChatConnectionResponse>('/api/m365/chat/connection');
                finish(connectionCovers(latest.connection, sources, connectedBefore) ? undefined
                    : new Error('Microsoft 365 sign-in was not completed. Connect again when you are ready.'));
            } catch {
                finish(new Error('Microsoft 365 sign-in could not be confirmed. Check Profile settings, then retry.'));
            }
        };
        const poll = window.setInterval(() => {
            if (popup.closed) void confirmAfterClose();
        }, POPUP_POLL_MS);
        const timeout = window.setTimeout(() => {
            finish(new Error('Microsoft 365 sign-in timed out. Connect again when you are ready.'));
        }, CONNECT_TIMEOUT_MS);
        window.addEventListener('message', onMessage);
        void (async () => {
            try {
                const current = await request<ChatConnectionResponse>('/api/m365/chat/connection');
                connectedBefore = current.connection?.connected_at;
                const csrfToken = current.csrf_token;
                if (typeof csrfToken !== 'string' || csrfToken.length < 32) {
                    throw new Error('Microsoft 365 controls are unavailable. Refresh the page and try again.');
                }
                const started = await request<ConnectResponse>('/api/m365/chat/connection/connect', {
                    method: 'POST',
                    body: { sources },
                    headers: { 'X-M365-CSRF-Token': csrfToken },
                });
                if (!finished) {
                    popup.location.replace(authorizationUrl(started.authorization_url));
                    popup.focus();
                }
            } catch (error) {
                finish(error instanceof Error ? error : new Error('Microsoft 365 sign-in could not start.'));
            }
        })();
    });
}
