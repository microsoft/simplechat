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

import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, TriangleAlert } from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import type { DomPurifyStatic, MermaidStatic } from '../../lib/vendor';
import { VENDOR_PATHS, loadDomPurify, loadVendorScript } from '../../lib/vendorAssets';
import { useBlockVisualStyle } from '../../lib/blockVisualStyle';
import {
    isDefaultVisualStyle,
    mermaidThemeVariables,
    resolveBackgroundColor,
    themeSurfaceColor,
    visualStyleSignature,
    type VisualStyle,
} from '../../lib/visualPalettes';
import { downloadDataUri, fileNameStem, svgElementToPngDataUri } from '../../lib/svgRaster';
import { VisualStyleMenu } from './VisualStyleMenu';

interface MermaidRuntime {
    mermaid: MermaidStatic;
    purify: DomPurifyStatic;
}

let runtime: MermaidRuntime | null = null;
let runtimeLoad: Promise<MermaidRuntime> | null = null;
let configuredSignature: string | null = null;
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

/**
 * Apply the configuration one diagram needs.
 *
 * Re-initialising per diagram is safe because mermaid's `setSiteConfig` rebuilds its
 * configuration from its own defaults on every call rather than merging into what was there
 * before, so theme variables set for one diagram cannot leak into the next.
 *
 * A diagram nobody has recoloured keeps mermaid's stock 'default' or 'dark' theme, so an
 * existing conversation looks exactly as it did. Theme variables appear only once someone has
 * actually chosen something.
 */
function configure(
    mermaid: MermaidStatic,
    theme: string,
    style: VisualStyle,
    background: string,
    configKey: string,
) {
    if (configuredSignature === configKey) {
        return;
    }

    const styled = !isDefaultVisualStyle(style);

    mermaid.initialize({
        // Nothing is rendered except through an explicit `render` call below.
        startOnLoad: false,
        // Diagram source is model output, so it is untrusted. 'strict' runs mermaid's
        // bundled DOMPurify over generated markup and disables the `click` directive,
        // which can otherwise bind handlers or navigate.
        securityLevel: 'strict',
        // Labels stay as SVG text rather than embedded HTML, which removes an entire
        // class of injection from diagram labels. It is also what makes a diagram
        // rasterizable: a <foreignObject> label disappears when an SVG is painted onto a
        // canvas, which would produce a PNG with no text in it.
        htmlLabels: false,
        flowchart: { htmlLabels: false, useMaxWidth: true },
        class: { htmlLabels: false, useMaxWidth: true },
        sequence: { useMaxWidth: true },
        gantt: { useMaxWidth: true },
        // Mermaid otherwise writes its own error diagram straight into the page, outside
        // React's control. Failures are handled below instead.
        suppressErrorRendering: true,
        theme: styled ? 'base' : theme === 'dark' ? 'dark' : 'default',
        ...(styled ? { themeVariables: mermaidThemeVariables(style, background) } : {}),
        // The application's own stack, all system fonts, so no webfont is fetched.
        fontFamily:
            "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
        logLevel: 'fatal',
    });
    configuredSignature = configKey;
}

/**
 * Rendered SVG keyed by theme, colours and source, so a streaming thread re-renders nothing.
 *
 * Bounded, because the key now includes the colours: dragging a background picker across a
 * long conversation would otherwise accumulate an entry per intermediate colour, each holding
 * a full SVG string. Oldest-first eviction is enough — the entry being competed for is almost
 * always the one just used.
 */
const svgCache = new Map<string, string>();

const MAX_CACHED_DIAGRAMS = 60;

function cacheSvg(key: string, svg: string) {
    if (svgCache.size >= MAX_CACHED_DIAGRAMS) {
        const oldest = svgCache.keys().next();
        if (!oldest.done) {
            svgCache.delete(oldest.value);
        }
    }
    svgCache.set(key, svg);
}

async function renderDiagram(
    source: string,
    theme: string,
    style: VisualStyle,
    background: string,
    signature: string,
): Promise<string> {
    const configKey = `${theme}|${signature}`;
    const key = `${configKey}|${source}`;
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

        configure(mermaid, theme, style, background, configKey);

        idCounter += 1;
        const { svg } = await mermaid.render(`simplechat-mermaid-${idCounter}`, source);

        // Sanitizer boundary. Mermaid's 'strict' level already sanitizes internally; this
        // is the independent second pass required before model-derived markup is written
        // to the DOM as HTML. `bindFunctions` from the render result is deliberately never
        // called, so no interaction handler is ever attached.
        const safe = purify.sanitize(svg);
        cacheSvg(key, safe);
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

/** The first line of a diagram, used to name its downloaded file. */
function diagramName(source: string): string {
    const firstLine = source.trim().split('\n', 1)[0] ?? '';
    return fileNameStem(firstLine, 'diagram');
}

/**
 * A rendered mermaid diagram.
 *
 * A diagram that fails to parse falls back to its source rather than disappearing: the
 * source is still the answer the model gave, and hiding it would lose information.
 *
 * `messageId` and `blockIndex` are what a saved colour choice is filed under. A diagram in a
 * reply that is still streaming has neither, so it renders with the reader's default and its
 * colour control says the choice will be kept once the reply finishes.
 */
export function MermaidDiagram({
    source,
    messageId,
    blockIndex,
}: {
    source: string;
    messageId?: string;
    blockIndex?: number;
}) {
    const theme = useUiStore((state) => state.theme);
    const [state, setState] = useState<DiagramState>({ status: 'pending' });
    const [menuOpen, setMenuOpen] = useState(false);
    const [downloadError, setDownloadError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    const { style, setStyle, reset, canPersist, error } = useBlockVisualStyle(
        'mermaid',
        source,
        messageId,
        blockIndex,
    );

    // `theme` is a dependency because the "match theme" background resolves through the app's
    // own surface colour, which is exactly what the theme switch changes.
    const background = useMemo(
        () =>
            resolveBackgroundColor(
                style,
                themeSurfaceColor(theme === 'dark' ? '#101728' : '#ffffff'),
            ),
        [style, theme],
    );
    const signature = useMemo(
        () => visualStyleSignature(style, background),
        [style, background],
    );
    const styled = !isDefaultVisualStyle(style);

    useEffect(() => {
        const trimmed = source.trim();
        if (trimmed === '') {
            setState({ status: 'error' });
            return;
        }

        const cached = svgCache.get(`${theme}|${signature}|${trimmed}`);
        if (cached !== undefined) {
            setState({ status: 'ready', svg: cached });
            return;
        }

        setState({ status: 'pending' });
        let cancelled = false;

        renderDiagram(trimmed, theme, style, background, signature)
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
    }, [source, theme, style, background, signature]);

    /**
     * Save the diagram as it is currently drawn.
     *
     * Rasterized from the SVG already on screen rather than re-rendered, so the file matches
     * what the reader is looking at, colours included.
     */
    const downloadPng = async () => {
        const svg = containerRef.current?.querySelector('svg');
        if (!svg) {
            return;
        }
        setDownloadError(null);
        try {
            const dataUri = await svgElementToPngDataUri(svg, background);
            downloadDataUri(dataUri, `${diagramName(source)}.png`);
        } catch {
            setDownloadError('The diagram could not be saved as an image.');
        }
    };

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
        <figure className="my-3 overflow-hidden rounded-xl border border-edge-strong bg-surface-sunken">
            <div
                ref={containerRef}
                // Sanitized in `renderDiagram` by DOMPurify, after mermaid generated it under
                // securityLevel 'strict'. SVG cannot be expressed as React children here.
                dangerouslySetInnerHTML={{ __html: state.svg }}
                // Set inline only once someone has chosen colours, so an untouched diagram
                // keeps the panel surface it has always sat on.
                style={styled ? { backgroundColor: background } : undefined}
                className="flex justify-center overflow-x-auto p-3 [&_svg]:max-w-full"
            />

            <div className="flex flex-wrap items-center justify-end gap-1 px-3 pb-2">
                <button
                    type="button"
                    onClick={downloadPng}
                    title="Download this diagram as a PNG"
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <Download size={13} />
                    PNG
                </button>

                <VisualStyleMenu
                    style={style}
                    onChange={setStyle}
                    onReset={reset}
                    open={menuOpen}
                    onToggle={() => setMenuOpen((open) => !open)}
                    canPersist={canPersist}
                    error={error ?? downloadError}
                    noun="diagram"
                />
            </div>

            {downloadError && !menuOpen && (
                <p className="px-3 pb-2 text-right text-[11px] text-danger">{downloadError}</p>
            )}
        </figure>
    );
}
