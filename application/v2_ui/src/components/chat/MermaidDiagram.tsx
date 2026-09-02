// MermaidDiagram.tsx
// Renders ```mermaid fences in assistant messages as diagrams.
//
// Mermaid already reaches the chat without this: Content Understanding writes ```mermaid
// blocks into extracted document text (functions_content_understanding.py), so a document
// with a diagram in it has been arriving as raw source.
//
// The library is loaded from the vendored copy on first use rather than bundled. It is 3.4 MB
// — larger than the rest of the application put together — and most conversations never show
// a diagram.

import { useEffect, useRef, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import type { DomPurifyStatic, MermaidStatic } from '../../lib/vendor';
import { VENDOR_PATHS, loadDomPurify, loadVendorScript } from '../../lib/vendorAssets';

interface MermaidRuntime {
    mermaid: MermaidStatic;
    purify: DomPurifyStatic;
}

let runtime: MermaidRuntime | null = null;
let runtimeLoad: Promise<MermaidRuntime> | null = null;
let configuredTheme: string | null = null;
let idCounter = 0;

/**
 * Serialises rendering.
 *
 * `mermaid.initialize` sets global configuration and `mermaid.render` reads it, so two
 * diagrams rendering concurrently can pick up each other's theme. Chaining the work keeps
 * each render paired with the configuration it asked for.
 */
let renderQueue: Promise<unknown> = Promise.resolve();

function loadMermaidRuntime(): Promise<MermaidRuntime> {
    if (runtime) {
        return Promise.resolve(runtime);
    }

    const started =
        runtimeLoad ??
        Promise.all([loadVendorScript(VENDOR_PATHS.mermaid), loadDomPurify()])
            .then(([, purify]) => {
                const mermaid = window.mermaid;
                if (!mermaid) {
                    throw new Error('Mermaid did not register a global after loading');
                }
                const loaded: MermaidRuntime = { mermaid, purify };
                runtime = loaded;
                return loaded;
            })
            .catch((error) => {
                runtimeLoad = null;
                throw error;
            });

    runtimeLoad = started;
    return started;
}

function configure(mermaid: MermaidStatic, theme: string) {
    if (configuredTheme === theme) {
        return;
    }
    mermaid.initialize({
        // Nothing is rendered except through an explicit `render` call below.
        startOnLoad: false,
        // Diagram source is model output, so it is untrusted. 'strict' runs mermaid's
        // bundled DOMPurify over generated markup and disables the `click` directive,
        // which can otherwise bind handlers or navigate.
        securityLevel: 'strict',
        // Labels stay as SVG text rather than embedded HTML, which removes an entire
        // class of injection from diagram labels.
        htmlLabels: false,
        flowchart: { htmlLabels: false, useMaxWidth: true },
        class: { htmlLabels: false, useMaxWidth: true },
        sequence: { useMaxWidth: true },
        gantt: { useMaxWidth: true },
        // Mermaid otherwise writes its own error diagram straight into the page, outside
        // React's control. Failures are handled below instead.
        suppressErrorRendering: true,
        theme: theme === 'dark' ? 'dark' : 'default',
        // The application's own stack, all system fonts, so no webfont is fetched.
        fontFamily:
            "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
        logLevel: 'fatal',
    });
    configuredTheme = theme;
}

/** Rendered SVG keyed by theme and source, so a streaming thread re-renders nothing. */
const svgCache = new Map<string, string>();

async function renderDiagram(source: string, theme: string): Promise<string> {
    const key = `${theme}:${source}`;
    const cached = svgCache.get(key);
    if (cached !== undefined) {
        return cached;
    }

    const { mermaid, purify } = await loadMermaidRuntime();

    const run = renderQueue.then(async () => {
        const existing = svgCache.get(key);
        if (existing !== undefined) {
            return existing;
        }

        configure(mermaid, theme);

        idCounter += 1;
        const { svg } = await mermaid.render(`simplechat-mermaid-${idCounter}`, source);

        // Sanitizer boundary. Mermaid's 'strict' level already sanitizes internally; this
        // is the independent second pass required before model-derived markup is written
        // to the DOM as HTML. `bindFunctions` from the render result is deliberately never
        // called, so no interaction handler is ever attached.
        const safe = purify.sanitize(svg);
        svgCache.set(key, safe);
        return safe;
    });

    // Keep the chain alive after a rejection so one bad diagram does not wedge the queue.
    renderQueue = run.catch(() => undefined);
    return run;
}

type DiagramState =
    | { status: 'pending' }
    | { status: 'ready'; svg: string }
    | { status: 'error' };

/** The diagram source, shown when it cannot be rendered. */
function DiagramSource({ source, reason }: { source: string; reason: string }) {
    return (
        <div className="my-3 overflow-hidden rounded-xl border border-edge-strong">
            <div className="flex items-center gap-1.5 border-b border-edge-strong bg-surface-sunken px-3 py-1.5 text-xs text-text-3">
                <TriangleAlert size={12} />
                {reason}
            </div>
            <pre className="overflow-x-auto p-3">
                <code className="font-mono text-[13px]">{source}</code>
            </pre>
        </div>
    );
}

/**
 * A rendered mermaid diagram.
 *
 * A diagram that fails to parse falls back to its source rather than disappearing: the
 * source is still the answer the model gave, and hiding it would lose information.
 */
export function MermaidDiagram({ source }: { source: string }) {
    const theme = useUiStore((state) => state.theme);
    const [state, setState] = useState<DiagramState>({ status: 'pending' });
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const trimmed = source.trim();
        if (trimmed === '') {
            setState({ status: 'error' });
            return;
        }

        const cached = svgCache.get(`${theme}:${trimmed}`);
        if (cached !== undefined) {
            setState({ status: 'ready', svg: cached });
            return;
        }

        setState({ status: 'pending' });
        let cancelled = false;

        renderDiagram(trimmed, theme)
            .then((svg) => {
                if (!cancelled) {
                    setState({ status: 'ready', svg });
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
    }, [source, theme]);

    if (state.status === 'error') {
        return <DiagramSource source={source.trim()} reason="Diagram could not be rendered" />;
    }

    if (state.status === 'pending') {
        return (
            <div className="my-3 flex h-24 items-center justify-center rounded-xl bg-surface-sunken text-xs text-text-3">
                Rendering diagram…
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            // Sanitized immediately above by DOMPurify, after mermaid generated it under
            // securityLevel 'strict'. SVG cannot be expressed as React children here.
            dangerouslySetInnerHTML={{ __html: state.svg }}
            className="my-3 flex justify-center overflow-x-auto rounded-xl bg-surface-sunken p-3 [&_svg]:max-w-full"
        />
    );
}
