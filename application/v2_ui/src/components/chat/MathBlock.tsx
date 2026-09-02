// MathBlock.tsx
// Renders TeX expressions lifted out of a message by `mathSegments.ts`.
//
// KaTeX is loaded from the vendored copy on first use rather than bundled, because most
// messages contain no maths and the library plus its fonts are ~1.3 MB. Until it arrives the
// raw TeX is shown, which is what an unrendered expression looks like anyway and is far
// better than an empty gap.

import { useEffect, useState } from 'react';
import type { DomPurifyStatic, KatexStatic } from '../../lib/vendor';
import {
    VENDOR_PATHS,
    loadDomPurify,
    loadVendorScript,
    loadVendorStylesheet,
} from '../../lib/vendorAssets';

interface KatexRuntime {
    katex: KatexStatic;
    purify: DomPurifyStatic;
}

let runtime: KatexRuntime | null = null;
let runtimeLoad: Promise<KatexRuntime> | null = null;

/** Load KaTeX, its stylesheet and DOMPurify once per session. */
function loadKatexRuntime(): Promise<KatexRuntime> {
    if (runtime) {
        return Promise.resolve(runtime);
    }

    const started =
        runtimeLoad ??
        Promise.all([
            loadVendorScript(VENDOR_PATHS.katexScript),
            loadVendorStylesheet(VENDOR_PATHS.katexStylesheet),
            loadDomPurify(),
        ])
            .then(([, , purify]) => {
                const katex = window.katex;
                if (!katex) {
                    throw new Error('KaTeX did not register a global after loading');
                }
                const loaded: KatexRuntime = { katex, purify };
                runtime = loaded;
                return loaded;
            })
            .catch((error) => {
                // Not cached as a rejection: a failed load is usually a deployment problem,
                // and a later message should be allowed to try again.
                runtimeLoad = null;
                throw error;
            });

    runtimeLoad = started;
    return started;
}

type RenderState =
    | { status: 'pending' }
    | { status: 'ready'; html: string }
    | { status: 'error' };

/**
 * Rendered output, keyed by expression.
 *
 * The same expression is commonly repeated down a thread, and every message re-renders while
 * a reply streams, so rendering is done once per distinct expression rather than per mount.
 */
const renderCache = new Map<string, string>();

function cacheKeyFor(tex: string, display: boolean): string {
    return `${display ? 'display' : 'inline'}:${tex}`;
}

function render(tex: string, display: boolean): RenderState {
    const key = cacheKeyFor(tex, display);
    const cached = renderCache.get(key);
    if (cached !== undefined) {
        return { status: 'ready', html: cached };
    }
    if (!runtime) {
        return { status: 'pending' };
    }

    try {
        const markup = runtime.katex.renderToString(tex, {
            displayMode: display,
            // Model output is untrusted. `trust: false` disables \href, \url,
            // \includegraphics and \htmlClass, so no expression can inject a link,
            // load a remote resource or attach a class of its own choosing.
            trust: false,
            // Render questionable-but-valid TeX rather than refusing it, and show
            // unparseable input as flagged source instead of throwing mid-render.
            strict: 'ignore',
            throwOnError: false,
            errorColor: 'currentColor',
            // Bounds macro expansion, so a crafted expression cannot spin the main thread.
            maxExpand: 1000,
            // MathML alongside the visual output is what screen readers announce.
            output: 'htmlAndMathml',
        });

        // Sanitizer boundary. KaTeX's own `trust: false` is the first line of defence; this
        // is the independent second one, and it is required because the result below is
        // written to the DOM as HTML rather than as React children.
        const safe = runtime.purify.sanitize(markup);
        renderCache.set(key, safe);
        return { status: 'ready', html: safe };
    } catch {
        return { status: 'error' };
    }
}

/** Raw TeX, shown while KaTeX loads and if it cannot render the expression. */
function TexFallback({ tex, display }: { tex: string; display: boolean }) {
    return (
        <code
            className={
                display
                    ? 'my-2 block overflow-x-auto whitespace-pre-wrap text-center font-mono text-[13px] text-text-2'
                    : 'font-mono text-[13px] text-text-2'
            }
        >
            {tex}
        </code>
    );
}

function MathExpression({ tex, display }: { tex: string; display: boolean }) {
    const key = cacheKeyFor(tex, display);
    const [state, setState] = useState<RenderState>(() => render(tex, display));

    useEffect(() => {
        const immediate = render(tex, display);
        if (immediate.status !== 'pending') {
            setState(immediate);
            return;
        }

        setState({ status: 'pending' });
        let cancelled = false;

        loadKatexRuntime()
            .then(() => {
                if (!cancelled) {
                    setState(render(tex, display));
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setState({ status: 'error' });
                }
            });

        return () => {
            cancelled = true;
        };
        // `key` covers both inputs and keeps the effect from re-running on equal values.
    }, [key, tex, display]);

    if (state.status !== 'ready') {
        return <TexFallback tex={tex} display={display} />;
    }

    return (
        <span
            // Sanitized immediately above by DOMPurify, after KaTeX rendered it with
            // `trust: false`. KaTeX positions glyphs with inline styles, so this markup
            // cannot be expressed as React children.
            dangerouslySetInnerHTML={{ __html: state.html }}
            className={display ? 'block overflow-x-auto py-1' : undefined}
        />
    );
}

/** An expression set inline with the surrounding sentence. */
export function MathInline({ tex }: { tex: string }) {
    return <MathExpression tex={tex} display={false} />;
}

/** An expression set as a centred block of its own. */
export function MathDisplay({ tex }: { tex: string }) {
    return <MathExpression tex={tex} display />;
}
