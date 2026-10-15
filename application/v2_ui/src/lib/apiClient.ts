// apiClient.ts
// Single entry point for every SimpleChat API call made by the V2 UI.
//
// Routing all traffic through here is what keeps the "same App Service now, separate App
// Service later" decision cheap: switching origins is a change to API_BASE alone, not a
// change to every call site.

import { SESSION_REQUIRED_MESSAGE, useAppSessionStore } from '../stores/appSessionStore';

/**
 * Base URL for API requests.
 *
 * Empty string means same-origin, which is the default deployment: Flask serves this SPA
 * from /v2 on the same host, so the session cookie and the server's same-origin CSRF
 * check both apply without any extra configuration.
 *
 * When the SPA is deployed to its own App Service, VITE_API_BASE is set at build time to
 * the Flask origin. That path additionally requires V2_UI_ALLOWED_ORIGIN to be set on the
 * Flask app so it emits CORS headers and trusts the origin for CSRF.
 *
 * `import.meta.env` is a Vite construct and is absent under any other loader, so it is read
 * defensively. Without that, importing any module in this graph outside a Vite build — a
 * functional test executing the real source, for instance — throws before a single line of
 * the module under test runs.
 */
export const API_BASE: string = import.meta.env?.VITE_API_BASE ?? '';

/** Cross-origin deployments must send credentials explicitly to carry the session cookie. */
export const CREDENTIALS_MODE: RequestCredentials = API_BASE ? 'include' : 'same-origin';

export class ApiError extends Error {
    readonly status: number;
    readonly payload: unknown;

    constructor(message: string, status: number, payload: unknown) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.payload = payload;
    }

    /** True when the session has expired and the user needs to sign in again. */
    get isAuthError(): boolean {
        return this.status === 401 || this.status === 403;
    }
}

export function isAppSessionRequired(status: number, payload: unknown): boolean {
    if ((status !== 401 && status !== 403) || !payload || typeof payload !== 'object') return false;
    const body = payload as Record<string, unknown>;
    return body.requires_reauth === true ||
        (status === 401 && (body.error === 'not_logged_in' ||
            (body.error === 'Unauthorized' && body.message === 'Authentication required')));
}

export function isAppSessionError(error: unknown): boolean {
    return error instanceof ApiError && isAppSessionRequired(error.status, error.payload);
}

function sessionError(): ApiError {
    return new ApiError(SESSION_REQUIRED_MESSAGE, 401, { requires_reauth: true });
}

function isSignInRedirect(response: Response): boolean {
    if (!response.redirected || !response.url) return false;
    const url = new URL(response.url);
    return url.pathname === '/login' || url.pathname.startsWith('/.auth/login/') ||
        /^(login\.microsoftonline\.(com|us|de)|login\.partner\.microsoftonline\.cn)$/.test(url.hostname);
}

let sessionVerification: Promise<boolean> | null = null;
let lastSessionVerification = 0;

function checkWriteSession(method: string): void {
    if (method === 'GET' || method === 'HEAD') return;
    const { status } = useAppSessionStore.getState();
    if (status === 'required') throw sessionError();
    if (status === 'changed') {
        throw new ApiError('Your signed-in account changed. Reload SimpleChat before continuing.',
            409, { error: 'app_account_changed' });
    }
}

async function fetchWithSessionCheck(path: string, init: RequestInit): Promise<Response> {
    try {
        return await fetch(apiUrl(path), init);
    } catch (error) {
        if (error instanceof TypeError && !init.signal?.aborted &&
            useAppSessionStore.getState().viewerId) {
            await verifyAppSession();
            if (useAppSessionStore.getState().status === 'required') throw sessionError();
        }
        throw error;
    }
}

/** A read-only check, never a retry of the request that failed. */
export function verifyAppSession(force = false): Promise<boolean> {
    if (sessionVerification) return sessionVerification;
    if (!force && Date.now() - lastSessionVerification < 15_000) return Promise.resolve(false);
    lastSessionVerification = Date.now();
    const { revision } = useAppSessionStore.getState();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    sessionVerification = (async () => {
        try {
            const response = await fetch(apiUrl('/api/v2/bootstrap'), {
                credentials: CREDENTIALS_MODE,
                cache: 'no-store',
                headers: { Accept: 'application/json' },
                signal: controller.signal,
            });
            if (isSignInRedirect(response)) {
                useAppSessionStore.getState().requireSignIn(revision);
                return false;
            }
            if (!response.headers.get('content-type')?.includes('application/json')) return false;
            const data: unknown = await response.json();
            if (!response.ok) {
                if (isAppSessionRequired(response.status, data)) {
                    useAppSessionStore.getState().requireSignIn(revision);
                }
                followServerGate(response.status, data);
                return false;
            }
            const user = (data as { user?: { id?: unknown } } | null)?.user;
            return typeof user?.id === 'string' &&
                useAppSessionStore.getState().confirmUser(user.id, revision);
        } catch (error) {
            if (error instanceof TypeError || error instanceof SyntaxError ||
                (error instanceof Error && error.name === 'AbortError')) return false;
            throw error;
        } finally {
            clearTimeout(timer);
            sessionVerification = null;
        }
    })();
    return sessionVerification;
}

export function apiUrl(path: string): string {
    if (/^https?:\/\//i.test(path)) {
        return path;
    }
    return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

export function safeSameOriginUrl(value: unknown, fallback: string): string {
    const candidate = typeof value === 'string' ? value.trim() : '';
    if (
        candidate.startsWith('/') &&
        !candidate.startsWith('//') &&
        !candidate.includes('\\') &&
        !/[\u0000-\u001f\u007f]/.test(candidate)
    ) {
        return candidate;
    }
    return fallback;
}

interface RequestOptions {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    headers?: Record<string, string>;
    /**
     * Fetch cache mode. Preference confirmations use `no-store` so an earlier cached
     * response cannot stand in for a fresh server read.
     */
    cache?: RequestCache;
}

/** A bare machine code, one lowercase token such as `document_propagation_incomplete`. */
const MACHINE_CODE = /^[a-z][a-z0-9_]*$/;

/** Where the server's Terms of Use gate sends a V2 user, relative to the origin. */
export const V2_TERMS_OF_USE_PATH = '/v2/terms-of-use';

/** True when a failed response is the server's Terms of Use gate rather than a real error. */
export function isTermsOfUseRequired(status: number, payload: unknown): boolean {
    return (
        status === 403 &&
        typeof payload === 'object' &&
        payload !== null &&
        (payload as Record<string, unknown>).error === 'terms_of_use_required'
    );
}

/** The V2 Terms of Use page, set to return to `next` once accepted. */
export function safeTermsOfUseUrl(next: unknown): string {
    return `${V2_TERMS_OF_USE_PATH}?${new URLSearchParams({ next: safeSameOriginUrl(next, '/v2') }).toString()}`;
}

/** Where the server's access gate sends a suspended or blocked V2 user. */
export const V2_ACCESS_RESTRICTED_PATH = '/v2/access-restricted';

/**
 * True when a failed response is the server's access gate: an administrator suspended or
 * blocked this account, so every call is refused until that ends.
 */
export function isAccessRestricted(status: number, payload: unknown): boolean {
    return (
        status === 403 &&
        typeof payload === 'object' &&
        payload !== null &&
        (payload as Record<string, unknown>).error === 'access_restricted'
    );
}

/**
 * Leave for the Access restricted page when the server says this account is restricted.
 *
 * A restriction can be applied while a tab is open, after which every call is refused. The
 * page says why and how long it lasts, which beats a screen full of failures. Skipped on
 * the page itself so a refused call there cannot loop.
 */
export function redirectToAccessRestricted(): boolean {
    if (typeof window === 'undefined' || !window.location) {
        return false;
    }
    if (window.location.pathname === V2_ACCESS_RESTRICTED_PATH) {
        return false;
    }
    window.location.assign(V2_ACCESS_RESTRICTED_PATH);
    return true;
}

/** Follow the server's gates when a failed response is one of them. */
function followServerGate(status: number, payload: unknown): void {
    if (isTermsOfUseRequired(status, payload)) {
        redirectToTermsOfUse();
    } else if (isAccessRestricted(status, payload)) {
        redirectToAccessRestricted();
    }
}

/**
 * Leave for the Terms of Use page when the server says acceptance is now required.
 *
 * Terms can change -- or a daily acceptance lapse -- while a tab is open, after which every
 * call is refused. Sending the tab to the page that settles it beats a screen full of
 * failures. Skipped on the page itself so a refused call there cannot loop.
 */
export function redirectToTermsOfUse(): boolean {
    if (typeof window === 'undefined' || !window.location) {
        return false;
    }
    const { pathname, search, hash } = window.location;
    if (pathname === V2_TERMS_OF_USE_PATH) {
        return false;
    }
    window.location.assign(safeTermsOfUseUrl(`${pathname}${search}${hash}`));
    return true;
}

async function readErrorMessage(response: Response): Promise<{ message: string; payload: unknown }> {
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        try {
            const payload = (await response.json()) as Record<string, unknown> | null;
            const error = payload && typeof payload.error === 'string' ? payload.error : '';
            const sentence = payload && typeof payload.message === 'string' ? payload.message : '';
            // A coded failure carries its machine code in `error` and its sentence in `message`.
            // The sentence is what a person reads; `payload` still carries the code for callers.
            const message =
                (MACHINE_CODE.test(error) && sentence.trim() ? sentence : error || sentence) ||
                `Request failed with status ${response.status}`;
            return { message, payload };
        } catch {
            /* Fall through to the text branch below. */
        }
    }
    const text = await response.text().catch(() => '');
    return {
        message: text.slice(0, 300) || `Request failed with status ${response.status}`,
        payload: text,
    };
}

/**
 * Perform a JSON request. Throws ApiError on any non-2xx response so callers can handle
 * failure in one place rather than checking response.ok everywhere.
 */
export interface ApiResponse<T> {
    data: T;
    status: number;
}

export async function requestWithStatus<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
    const { method = 'GET', body, signal, headers = {}, cache } = options;
    checkWriteSession(method);
    const sessionRevision = useAppSessionStore.getState().revision;

    const init: RequestInit = {
        method,
        credentials: CREDENTIALS_MODE,
        signal,
        headers: {
            Accept: 'application/json',
            ...headers,
        },
    };

    if (cache) {
        init.cache = cache;
    }

    if (body !== undefined) {
        init.headers = { ...init.headers, 'Content-Type': 'application/json' };
        init.body = JSON.stringify(body);
    }

    const response = await fetchWithSessionCheck(path, init);

    if (isSignInRedirect(response)) {
        useAppSessionStore.getState().requireSignIn(sessionRevision);
        throw sessionError();
    }

    if (!response.ok) {
        const { message, payload } = await readErrorMessage(response);
        followServerGate(response.status, payload);
        if (isAppSessionRequired(response.status, payload)) {
            useAppSessionStore.getState().requireSignIn(sessionRevision);
            throw sessionError();
        }
        throw new ApiError(message, response.status, payload);
    }

    if (response.status === 204) {
        return { data: undefined as T, status: response.status };
    }

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        return { data: (await response.text()) as unknown as T, status: response.status };
    }

    return { data: (await response.json()) as T, status: response.status };
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return (await requestWithStatus<T>(path, options)).data;
}

export const api = {
    get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: 'GET', signal }),
    post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
        request<T>(path, { method: 'POST', body, signal }),
    put: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
        request<T>(path, { method: 'PUT', body, signal }),
    patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
        request<T>(path, { method: 'PATCH', body, signal }),
    // Some DELETE endpoints read options from a JSON body rather than the query string,
    // so a body is supported here even though it is unusual for the verb.
    delete: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
        request<T>(path, { method: 'DELETE', body, signal }),
};

/**
 * Multipart upload. Deliberately does not set Content-Type so the browser can generate
 * the multipart boundary itself.
 */
export async function uploadFileWithStatus<T>(
    path: string,
    formData: FormData,
    signal?: AbortSignal,
): Promise<ApiResponse<T>> {
    checkWriteSession('POST');
    const sessionRevision = useAppSessionStore.getState().revision;
    const response = await fetchWithSessionCheck(path, {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        body: formData,
        signal,
    });

    if (isSignInRedirect(response)) {
        useAppSessionStore.getState().requireSignIn(sessionRevision);
        throw sessionError();
    }
    if (!response.ok) {
        const { message, payload } = await readErrorMessage(response);
        followServerGate(response.status, payload);
        if (isAppSessionRequired(response.status, payload)) {
            useAppSessionStore.getState().requireSignIn(sessionRevision);
            throw sessionError();
        }
        throw new ApiError(message, response.status, payload);
    }

    return { data: (await response.json()) as T, status: response.status };
}

export async function uploadFile<T>(path: string, formData: FormData, signal?: AbortSignal): Promise<T> {
    return (await uploadFileWithStatus<T>(path, formData, signal)).data;
}
