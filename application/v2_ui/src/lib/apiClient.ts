// apiClient.ts
// Single entry point for every SimpleChat API call made by the V2 UI.
//
// Routing all traffic through here is what keeps the "same App Service now, separate App
// Service later" decision cheap: switching origins is a change to API_BASE alone, not a
// change to every call site.

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
 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '';

/** Cross-origin deployments must send credentials explicitly to carry the session cookie. */
const CREDENTIALS_MODE: RequestCredentials = API_BASE ? 'include' : 'same-origin';

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

export function apiUrl(path: string): string {
    if (/^https?:\/\//i.test(path)) {
        return path;
    }
    return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

interface RequestOptions {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    headers?: Record<string, string>;
}

async function readErrorMessage(response: Response): Promise<{ message: string; payload: unknown }> {
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        try {
            const payload = (await response.json()) as Record<string, unknown> | null;
            const message =
                (payload && typeof payload.error === 'string' && payload.error) ||
                (payload && typeof payload.message === 'string' && payload.message) ||
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
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { method = 'GET', body, signal, headers = {} } = options;

    const init: RequestInit = {
        method,
        credentials: CREDENTIALS_MODE,
        signal,
        headers: {
            Accept: 'application/json',
            ...headers,
        },
    };

    if (body !== undefined) {
        init.headers = { ...init.headers, 'Content-Type': 'application/json' };
        init.body = JSON.stringify(body);
    }

    const response = await fetch(apiUrl(path), init);

    if (!response.ok) {
        const { message, payload } = await readErrorMessage(response);
        throw new ApiError(message, response.status, payload);
    }

    if (response.status === 204) {
        return undefined as T;
    }

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        return (await response.text()) as unknown as T;
    }

    return (await response.json()) as T;
}

export const api = {
    get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: 'GET', signal }),
    post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
        request<T>(path, { method: 'POST', body, signal }),
    put: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
        request<T>(path, { method: 'PUT', body, signal }),
    patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
        request<T>(path, { method: 'PATCH', body, signal }),
    delete: <T>(path: string, signal?: AbortSignal) =>
        request<T>(path, { method: 'DELETE', signal }),
};

/**
 * Multipart upload. Deliberately does not set Content-Type so the browser can generate
 * the multipart boundary itself.
 */
export async function uploadFile<T>(
    path: string,
    formData: FormData,
    signal?: AbortSignal,
): Promise<T> {
    const response = await fetch(apiUrl(path), {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        body: formData,
        signal,
    });

    if (!response.ok) {
        const { message, payload } = await readErrorMessage(response);
        throw new ApiError(message, response.status, payload);
    }

    return (await response.json()) as T;
}
