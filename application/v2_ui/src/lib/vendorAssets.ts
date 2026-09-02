// vendorAssets.ts
// Loads the pinned third-party browser libraries that are vendored into this repository.
//
// SimpleChat never loads browser runtime code from the public Internet. Each library here is
// a dist bundle downloaded once, committed under `public/vendor/<lib>-<version>/`, and
// verified against the registry's SHA-256. Vite copies `public/` into the build output
// verbatim, so the bytes the browser executes are exactly the bytes under version control —
// which is the point of vendoring rather than resolving from npm at build time.
//
// They are loaded on demand rather than bundled because they are large and most messages
// need none of them: mermaid alone is 3.4 MB. A chat with no diagram, chart or equation
// downloads nothing extra. Nothing here reaches the network beyond the app's own origin, so
// the `default-src 'self'` Content-Security-Policy is unchanged.

import type { DomPurifyStatic } from './vendor';

/**
 * Version-pinned locations of the vendored bundles.
 *
 * The version lives in the directory name so an upgrade is a visible, reviewable change of
 * path rather than a silent replacement of file contents. Keep these in step with the
 * directories under `public/vendor/`; a functional test asserts they exist.
 */
export const VENDOR_PATHS = {
    katexScript: 'vendor/katex-0.18.4/katex.min.js',
    katexStylesheet: 'vendor/katex-0.18.4/katex.min.css',
    mermaid: 'vendor/mermaid-11.17.2/mermaid.min.js',
    chartJs: 'vendor/chartjs-4.5.1/chart.umd.min.js',
    domPurify: 'vendor/dompurify-3.4.14/purify.min.js',
} as const;

/**
 * Resolve a vendored asset to a URL on the app's own origin.
 *
 * `BASE_URL` is Vite's asset prefix (`/static/v2/`), deliberately not `API_BASE`: in the
 * split-origin deployment the API lives on the Flask host while these files ship with the
 * SPA, so they must be fetched from wherever the SPA itself was served.
 */
export function vendorUrl(relativePath: string): string {
    const base = import.meta.env.BASE_URL || '/';
    return `${base.endsWith('/') ? base : `${base}/`}${relativePath}`;
}

/** In-flight and settled loads, so a library is never fetched or evaluated twice. */
const pending = new Map<string, Promise<void>>();

function injectOnce(url: string, createElement: () => HTMLElement): Promise<void> {
    const existing = pending.get(url);
    if (existing) {
        return existing;
    }

    const load = new Promise<void>((resolve, reject) => {
        const element = createElement();
        element.addEventListener('load', () => resolve(), { once: true });
        element.addEventListener(
            'error',
            () => {
                // Allow a later attempt to retry: a failed load is usually a deployment
                // problem, and caching the rejection would make it permanent for the session.
                pending.delete(url);
                reject(new Error(`Failed to load vendored asset: ${url}`));
            },
            { once: true },
        );
        document.head.appendChild(element);
    });

    pending.set(url, load);
    return load;
}

/** Load a vendored script and resolve once its global is available. */
export function loadVendorScript(relativePath: string): Promise<void> {
    const url = vendorUrl(relativePath);
    return injectOnce(url, () => {
        const script = document.createElement('script');
        script.src = url;
        script.async = true;
        return script;
    });
}

/** Load a vendored stylesheet, used for KaTeX's fonts and glyph metrics. */
export function loadVendorStylesheet(relativePath: string): Promise<void> {
    const url = vendorUrl(relativePath);
    return injectOnce(url, () => {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = url;
        return link;
    });
}

/**
 * DOMPurify, used as the explicit sanitizer boundary in front of every HTML sink.
 *
 * KaTeX and Mermaid both hand back markup that has to be injected as HTML. Each library has
 * its own hardening (`trust: false` and `securityLevel: 'strict'` respectively), and this is
 * the independent second boundary required before anything derived from model output is
 * written into the DOM.
 */
export async function loadDomPurify(): Promise<DomPurifyStatic> {
    await loadVendorScript(VENDOR_PATHS.domPurify);
    const purify = window.DOMPurify;
    if (!purify) {
        throw new Error('DOMPurify did not register a global after loading');
    }
    return purify;
}
