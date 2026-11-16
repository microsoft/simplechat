// v2SourcePolicy.ts
// UI semantics only: the server still authorizes every source independently.

function firstPartySourceUrl(value: string): URL | null {
    if (!value || value.startsWith('//') || /[\\\u0000-\u0020\u007f]/.test(value)) return null;
    const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
    try {
        const url = new URL(value, origin);
        if (url.origin !== origin || url.username || url.password || !/^https?:$/.test(url.protocol)) return null;
        return url.pathname === '/api' || url.pathname.startsWith('/api/')
            || url.pathname === '/enhanced_citations' || url.pathname.startsWith('/enhanced_citations/')
            ? url : null;
    } catch {
        return null;
    }
}

const NAVIGATION_SOURCE_PATHS = new Set([
    '/api/enhanced_citations/audio',
    '/api/enhanced_citations/video',
    '/api/enhanced_citations/image',
    '/api/enhanced_citations/visio',
    '/api/enhanced_citations/tabular_workspace',
    '/api/enhanced_citations/tabular',
    '/api/workspace_documents/download',
    '/api/workspace_documents/image_preview',
]);

/** Only explicit source navigation routes accept this query contract, not arbitrary APIs. */
export function safeV2SourceUrl(value: string): string {
    const url = firstPartySourceUrl(value);
    if (!url || !(NAVIGATION_SOURCE_PATHS.has(url.pathname) || /^\/api\/image\/[^/]+$/.test(url.pathname))) return value;
    url.searchParams.set('ui_version', 'v2');
    return value.startsWith('/') ? `${url.pathname}${url.search}${url.hash}` : url.href;
}

/** Shared by JSON, multipart, streaming, recovery, and raw source reads. */
export function v2ApiFetch(url: string, init: RequestInit = {}): Promise<Response> {
    const headers: Record<string, string> = init.headers instanceof Headers || Array.isArray(init.headers)
        ? Object.fromEntries(new Headers(init.headers))
        : { ...init.headers };
    const firstParty = firstPartySourceUrl(url) !== null;
    for (const key of Object.keys(headers)) {
        if (key.toLowerCase() === 'x-simplechat-ui') delete headers[key];
    }
    if (firstParty) headers['X-SimpleChat-UI'] = 'v2';
    return fetch(url, {
        ...init,
        headers,
        // Fetch forwards custom headers on cross-origin redirects. Refuse rather than
        // leak the UI marker to a redirected external or signed-blob destination.
        ...(firstParty ? { redirect: init.redirect === 'manual' ? 'manual' : 'error' } : {}),
    });
}
