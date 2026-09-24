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

/** A bare machine code, one lowercase token such as `document_propagation_incomplete`. */
const MACHINE_CODE = /^[a-z][a-z0-9_]*$/;

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

    return { data: (await response.json()) as T, status: response.status };
}

export async function uploadFile<T>(path: string, formData: FormData, signal?: AbortSignal): Promise<T> {
    return (await uploadFileWithStatus<T>(path, formData, signal)).data;
}
