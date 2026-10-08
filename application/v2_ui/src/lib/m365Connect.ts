// m365Connect.ts
// Signs in to Microsoft 365 from V2 in a popup, for chat or for saved workflows.
//
// The server starts an authorization code flow for the named sources and asks for a popup
// completion. The sign-in ends on a small result page that tells this window the outcome and
// closes, so the user stays in V2 and never lands on a classic page. That message can be lost
// when the popup visits Microsoft sign-in or the API is on another origin, so the saved
// connection is checked when the popup closes.

import { apiUrl, request } from './apiClient';

export type M365Source = 'calendar' | 'email' | 'onedrive' | 'spo';

const M365_SOURCES: ReadonlySet<string> = new Set(['calendar', 'email', 'onedrive', 'spo']);
const CHAT_POPUP_NAME = 'simplechat-m365-orchestration-connect';
const WORKFLOW_POPUP_NAME = 'simplechat-m365-workflow-connect';
const POPUP_FEATURES = 'popup,width=720,height=780,resizable=yes,scrollbars=yes';
const CONNECT_TIMEOUT_MS = 300_000;
const POPUP_POLL_MS = 500;
const MAX_FAILURE_MESSAGE_LENGTH = 500;
const INVALID_URL_MESSAGE = 'The server did not return a valid HTTPS Microsoft 365 sign-in URL.';
const CHAT_CONNECTED_TYPE = 'm365-profile-reconnected';
const WORKFLOW_CONNECTED_TYPE = 'm365-workflow-connected';
const CONNECT_FAILED_TYPE = 'm365-connect-failed';

interface ChatConnection {
    status?: string;
    sources?: unknown;
    connected_at?: string;
}

interface WorkflowConnection {
    status?: string;
    sources?: unknown;
    connected_at?: string;
}

interface ChatConnectionResponse {
    connection?: ChatConnection;
    csrf_token?: string;
}

interface WorkflowConnectionResponse {
    connection?: WorkflowConnection | null;
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
export function normalizeAuthorizationUrl(value: unknown): string {
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

function covers(
    connection: ChatConnection | WorkflowConnection | null | undefined,
    status: string,
    sources: M365Source[],
    before?: string,
): boolean {
    const connected = m365Sources(connection?.sources);
    return connection?.status === status
        && typeof connection.connected_at === 'string'
        && connection.connected_at !== before
        && sources.every((source) => connected.includes(source));
}

/** The result page's own wording for a failed sign-in, as plain text. */
function failureMessage(data: { message?: unknown }): string {
    const text = typeof data.message === 'string' ? data.message.trim() : '';
    return text ? text.slice(0, MAX_FAILURE_MESSAGE_LENGTH) : 'Microsoft 365 sign-in did not complete. Connect again when you are ready.';
}

interface PopupSignIn {
    kind: 'chat' | 'workflow';
    popupName: string;
    connectedType: string;
    /** Starts the sign-in and returns the authorization URL; records any state `confirm` needs. */
    start: () => Promise<unknown>;
    /** After the popup closed without a message: whether the connection was saved anyway. */
    confirm: () => Promise<boolean>;
}

/**
 * Runs one popup sign-in. The popup opens before anything is awaited, so call this from a
 * click handler or the browser blocks it.
 */
function runPopupSignIn(signIn: PopupSignIn): Promise<void> {
    const popup = window.open('about:blank', signIn.popupName, POPUP_FEATURES);
    if (!popup) {
        return Promise.reject(new Error(
            'The sign-in window was blocked. Allow pop-ups for this site, then connect Microsoft 365 again.',
        ));
    }
    const apiOrigin = new URL(apiUrl('/'), window.location.origin).origin;
    return new Promise<void>((resolve, reject) => {
        let finished = false;
        let checking = false;
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
                event.source !== popup
                || (event.origin !== window.location.origin && event.origin !== apiOrigin)
            ) {
                return;
            }
            const data = (event.data ?? {}) as { type?: unknown; kind?: unknown; message?: unknown };
            if (data.type === signIn.connectedType) {
                finish();
            } else if (data.type === CONNECT_FAILED_TYPE && data.kind === signIn.kind) {
                finish(new Error(failureMessage(data)));
            }
        };
        const confirmAfterClose = async () => {
            if (checking || finished) return;
            checking = true;
            try {
                finish(await signIn.confirm() ? undefined
                    : new Error('Microsoft 365 sign-in was not completed. Connect again when you are ready.'));
            } catch {
                finish(new Error('Microsoft 365 sign-in could not be confirmed. Refresh Microsoft 365 status, then retry.'));
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
                const authorizationUrl = await signIn.start();
                if (!finished) {
                    popup.location.replace(normalizeAuthorizationUrl(authorizationUrl));
                    popup.focus();
                }
            } catch (error) {
                finish(error instanceof Error ? error : new Error('Microsoft 365 sign-in could not start.'));
            }
        })();
    });
}

function requireCsrf(token: unknown): string {
    if (typeof token !== 'string' || token.length < 32) {
        throw new Error('Microsoft 365 controls are unavailable. Refresh the page and try again.');
    }
    return token;
}

/**
 * Sign in to Microsoft 365 for chat with these sources. Resolves once the sign-in is saved for
 * this session; rejects with a user-facing message otherwise.
 */
export function connectMicrosoft365(sources: M365Source[]): Promise<void> {
    if (!sources.length) {
        return Promise.reject(new Error('Choose the Microsoft 365 sources to connect in Settings.'));
    }
    let connectedBefore: string | undefined;
    return runPopupSignIn({
        kind: 'chat',
        popupName: CHAT_POPUP_NAME,
        connectedType: CHAT_CONNECTED_TYPE,
        start: async () => {
            const current = await request<ChatConnectionResponse>('/api/m365/chat/connection');
            connectedBefore = current.connection?.connected_at;
            const started = await request<ConnectResponse>('/api/m365/chat/connection/connect', {
                method: 'POST',
                body: { sources, completion: 'popup' },
                headers: { 'X-M365-CSRF-Token': requireCsrf(current.csrf_token) },
            });
            return started.authorization_url;
        },
        confirm: async () => {
            const latest = await request<ChatConnectionResponse>('/api/m365/chat/connection');
            return covers(latest.connection, 'available', sources, connectedBefore);
        },
    });
}

/**
 * Save a Microsoft 365 sign-in that workflows can run as, for these sources. Resolves once the
 * workflow connection is saved; rejects with a user-facing message otherwise.
 */
export function connectMicrosoft365Workflow(sources: M365Source[]): Promise<void> {
    if (!sources.length) {
        return Promise.reject(new Error('Select at least one source to connect for workflows.'));
    }
    let connectedBefore: string | undefined;
    return runPopupSignIn({
        kind: 'workflow',
        popupName: WORKFLOW_POPUP_NAME,
        connectedType: WORKFLOW_CONNECTED_TYPE,
        start: async () => {
            const current = await request<WorkflowConnectionResponse>('/api/m365/connections');
            connectedBefore = current.connection?.connected_at;
            const started = await request<ConnectResponse>('/api/m365/connections/connect', {
                method: 'POST',
                body: { sources, completion: 'popup' },
                headers: { 'X-M365-CSRF-Token': requireCsrf(current.csrf_token) },
            });
            return started.authorization_url;
        },
        confirm: async () => {
            const latest = await request<WorkflowConnectionResponse>('/api/m365/connections');
            return covers(latest.connection, 'connected', sources, connectedBefore);
        },
    });
}