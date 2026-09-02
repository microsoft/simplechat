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
//
// Sizing lives in DiagramStage.tsx. The expanded viewer lives here rather than in its own file
// on purpose: it writes diagram markup to the DOM, and keeping every such sink in one reviewed
// file is what test_v2_rich_rendering.py's sanitizer boundary check is protecting.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    ChevronDown,
    Copy,
    Download,
    Maximize2,
    Minus,
    Plus,
    Scan,
    TriangleAlert,
    X,
} from 'lucide-react';
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
import {
    describeMermaidError,
    isRepairWorthTrying,
    repairMermaidSource,
} from '../../lib/mermaidSource';
import { downloadDataUri, fileNameStem, svgElementToPngDataUri } from '../../lib/svgRaster';
import { VisualStyleMenu } from './VisualStyleMenu';
import {
    clampZoom,
    defaultStageHeight,
    DiagramStage,
    MAX_ZOOM,
    MIN_FIGURE_WIDTH,
    MIN_ZOOM,
    readDiagramSize,
    ZOOM_STEP,
    type DiagramSize,
} from './DiagramStage';
import { GlassPanel } from '../ui/primitives';

interface MermaidRuntime {
    mermaid: MermaidStatic;
    purify: DomPurifyStatic;
}

let runtime: MermaidRuntime | null = null;
let runtimeLoad: Promise<MermaidRuntime> | null = null;
let configuredSignature: string | null = null;
let idCounter = 0;

/**
 * How long one diagram is given before it is treated as failed.
 *
 * Matches MERMAID_RENDER_TIMEOUT_MS in static/js/chat/chat-mermaid-runtime.js. Without it a
 * render that never settles leaves "Rendering diagram…" on screen for the life of the page,
 * which is indistinguishable from a diagram that is merely slow.
 */
const RENDER_TIMEOUT_MS = 10000;

/**
 * Longest diagram source that is attempted at all.
 *
 * Matches INLINE_DIAGRAM_MAX_SOURCE_LENGTH in static/js/chat/chat-inline-diagrams.js. Mermaid
 * has its own `maxTextSize`, but it reports the refusal as a render failure; checking first
 * lets the reader be told the diagram is too large rather than that it is broken.
 */
const MAX_SOURCE_LENGTH = 30000;

/**
 * Ceilings handed to mermaid, set explicitly rather than left to its defaults.
 *
 * `maxEdges` matters: a diagram at mermaid's default limit of 500 edges renders roughly fifty
 * thousand pixels tall, so the limit is a rendering safeguard as much as a parsing one and is
 * worth stating where it can be seen.
 */
const MERMAID_MAX_TEXT_SIZE = 50000;
const MERMAID_MAX_EDGES = 500;

/**
 * How wide a label is allowed to get before mermaid wraps it.
 *
 * Mermaid's default is 200px, which turns the long labels models write into narrow columns of
 * text: the same diagram measures 273 x 955 at the default and 497 x 867 at this value, so the
 * default is actively making diagrams taller and harder to read. Diagrams that break their own
 * labels with `<br/>`, which is what the diagram guidance asks for, are unaffected.
 */
const MERMAID_WRAPPING_WIDTH = 500;

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
        flowchart: {
            htmlLabels: false,
            useMaxWidth: true,
            wrappingWidth: MERMAID_WRAPPING_WIDTH,
        },
        class: { htmlLabels: false, useMaxWidth: true },
        sequence: { useMaxWidth: true },
        gantt: { useMaxWidth: true },
        // Stated rather than inherited, so the ceilings a diagram is measured against are
        // visible next to the code that has to explain hitting them.
        maxTextSize: MERMAID_MAX_TEXT_SIZE,
        maxEdges: MERMAID_MAX_EDGES,
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

/** Reject once a render has had long enough, without cancelling the render itself. */
function withTimeout<T>(work: Promise<T>, timeoutMs: number): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const timer = setTimeout(
            () => reject(new Error('Timed out rendering the diagram.')),
            timeoutMs,
        );
        work.then(
            (value) => {
                clearTimeout(timer);
                resolve(value);
            },
            (error) => {
                clearTimeout(timer);
                reject(error);
            },
        );
    });
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

    if (source.length > MAX_SOURCE_LENGTH) {
        throw new Error('The diagram source is too large to draw.');
    }

    const { mermaid, purify } = await loadMermaidRuntime();

    const run = renderQueue.then(async () => {
        const existing = svgCache.get(key);
        if (existing !== undefined) {
            return existing;
        }

        configure(mermaid, theme, style, background, configKey);

        const draw = async (text: string) => {
            idCounter += 1;
            const { svg } = await withTimeout(
                Promise.resolve(mermaid.render(`simplechat-mermaid-${idCounter}`, text)),
                RENDER_TIMEOUT_MS,
            );
            return svg;
        };

        let svg: string;
        try {
            svg = await draw(source);
        } catch (error) {
            // Second attempt only. Repairing source mermaid has already accepted would risk
            // changing a diagram that is drawing correctly, so the original is always tried
            // first and the rewrite is a last resort before showing the reader the source.
            if (!isRepairWorthTrying(source)) {
                throw error;
            }
            svg = await draw(repairMermaidSource(source));
        }

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
    | { status: 'error'; reason: string };

/**
 * The diagram source, shown when it cannot be rendered.
 *
 * The reason mermaid gave is shown rather than swallowed. Before this the only signal a reader
 * or an administrator had was the words "Diagram could not be rendered", which is not enough to
 * tell a malformed diagram from a library that failed to load.
 */
function DiagramSource({ source, reason }: { source: string; reason: string }) {
    const [detailsOpen, setDetailsOpen] = useState(false);
    const [copied, setCopied] = useState(false);
    const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(
        () => () => {
            if (copyTimerRef.current !== null) {
                clearTimeout(copyTimerRef.current);
            }
        },
        [],
    );

    const copySource = async () => {
        try {
            await navigator.clipboard.writeText(source);
            setCopied(true);
            if (copyTimerRef.current !== null) {
                clearTimeout(copyTimerRef.current);
            }
            copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
        } catch {
            setCopied(false);
        }
    };

    return (
        <div className="my-3 overflow-hidden rounded-xl border border-edge-strong">
            <div className="flex flex-wrap items-center gap-1.5 border-b border-edge-strong bg-surface-sunken px-3 py-1.5 text-xs text-text-3">
                <TriangleAlert size={12} />
                Diagram could not be rendered
                <button
                    type="button"
                    onClick={() => setDetailsOpen((open) => !open)}
                    aria-expanded={detailsOpen}
                    className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    {detailsOpen ? 'Hide details' : 'Show details'}
                    <ChevronDown
                        size={11}
                        className={detailsOpen ? 'rotate-180' : undefined}
                    />
                </button>
                <button
                    type="button"
                    onClick={() => void copySource()}
                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <Copy size={11} />
                    {copied ? 'Copied' : 'Copy source'}
                </button>
            </div>

            {detailsOpen && (
                <p className="border-b border-edge-strong bg-surface-sunken px-3 py-2 text-xs text-text-2">
                    {reason}
                </p>
            )}

            <pre className="overflow-x-auto p-3">
                <code className="font-mono text-[13px]">{source}</code>
            </pre>
        </div>
    );
}

/** The first line of a diagram, used to name its downloaded file and title its viewer. */
function diagramName(source: string): string {
    const firstLine = source.trim().split('\n', 1)[0] ?? '';
    return fileNameStem(firstLine, 'diagram');
}

/** Zoom in, zoom out and fit, shared by the inline panel and the expanded viewer. */
function ZoomControls({
    zoom,
    onZoom,
    onReset,
    compact = false,
}: {
    zoom: number;
    onZoom: (next: number) => void;
    onReset: () => void;
    compact?: boolean;
}) {
    const buttonClass = compact
        ? 'shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40'
        : 'inline-flex items-center rounded-md px-1.5 py-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40';

    return (
        <>
            <button
                type="button"
                onClick={() => onZoom(clampZoom(zoom / ZOOM_STEP))}
                disabled={zoom <= MIN_ZOOM}
                title="Make the diagram smaller"
                aria-label="Make the diagram smaller"
                className={buttonClass}
            >
                <Minus size={compact ? 16 : 13} />
            </button>
            <button
                type="button"
                onClick={onReset}
                title="Fit the diagram to the panel"
                aria-label="Fit the diagram to the panel"
                className={buttonClass}
            >
                <Scan size={compact ? 16 : 13} />
            </button>
            <button
                type="button"
                onClick={() => onZoom(clampZoom(zoom * ZOOM_STEP))}
                disabled={zoom >= MAX_ZOOM}
                title="Make the diagram larger"
                aria-label="Make the diagram larger"
                className={buttonClass}
            >
                <Plus size={compact ? 16 : 13} />
            </button>
        </>
    );
}

/**
 * Full-screen view of one diagram.
 *
 * Follows the conventions ImageLightbox established: a click-to-close backdrop, Escape to
 * dismiss, focus moved in on open and handed back on close, and no focus-trap utility, because
 * none of the other dialogs in this interface use one.
 *
 * The diagram is drawn from the same sanitized markup the inline panel is showing, so nothing
 * is re-rendered and the two cannot disagree.
 */
function DiagramLightbox({
    svg,
    size,
    title,
    background,
    onDownload,
    onClose,
}: {
    svg: string;
    size: DiagramSize | null;
    title: string;
    background?: string;
    onDownload: (element: SVGElement | null) => void;
    onClose: () => void;
}) {
    const [zoom, setZoom] = useState(1);
    const [fitWidth, setFitWidth] = useState(0);
    const closeRef = useRef<HTMLButtonElement>(null);
    const viewportRef = useRef<HTMLDivElement>(null);
    const contentRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    // Opening a dialog should move the keyboard focus into it, and closing should hand it back
    // to whatever had it before, which is the button that opened it.
    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        closeRef.current?.focus();
        return () => previous?.focus?.();
    }, []);

    useEffect(() => {
        const element = viewportRef.current;
        if (!element || typeof ResizeObserver === 'undefined') {
            return;
        }
        setFitWidth(element.clientWidth);
        const observer = new ResizeObserver((entries) => {
            setFitWidth(entries[0]?.contentRect.width ?? element.clientWidth);
        });
        observer.observe(element);
        return () => observer.disconnect();
    }, []);

    const scale = size && fitWidth > 0 ? Math.min(1, fitWidth / size.width) * zoom : zoom;

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Diagram"
        >
            <div className="absolute inset-0 bg-black/60" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex h-[90vh] w-full max-w-7xl flex-col overflow-hidden"
            >
                <div className="flex shrink-0 items-center gap-1 border-b border-edge px-5 py-3">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-1">
                        {title}
                    </h2>

                    <ZoomControls zoom={zoom} onZoom={setZoom} onReset={() => setZoom(1)} compact />

                    <button
                        type="button"
                        onClick={() => onDownload(contentRef.current?.querySelector('svg') ?? null)}
                        title="Save the diagram as a PNG"
                        aria-label="Save the diagram as a PNG"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <Download size={16} />
                    </button>
                    <button
                        ref={closeRef}
                        type="button"
                        onClick={onClose}
                        title="Close"
                        aria-label="Close the diagram"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div
                    ref={viewportRef}
                    style={background ? { backgroundColor: background } : undefined}
                    className="min-h-0 flex-1 overflow-auto p-4"
                >
                    <div
                        style={
                            size
                                ? {
                                      width: Math.round(size.width * scale),
                                      height: Math.round(size.height * scale),
                                  }
                                : undefined
                        }
                        className="mx-auto"
                    >
                        <div
                            ref={contentRef}
                            style={
                                size
                                    ? {
                                          width: size.width,
                                          height: size.height,
                                          transform: `scale(${scale})`,
                                          transformOrigin: 'top left',
                                      }
                                    : undefined
                            }
                            // Sanitized in `renderDiagram` by DOMPurify, after mermaid generated
                            // it under securityLevel 'strict'. SVG cannot be expressed as React
                            // children here.
                            dangerouslySetInnerHTML={{ __html: svg }}
                            className="[&_svg]:h-full [&_svg]:w-full [&_svg]:max-w-none"
                        />
                    </div>
                </div>
            </GlassPanel>
        </div>
    );
}

/**
 * A rendered mermaid diagram.
 *
 * A diagram that fails to parse falls back to its source rather than disappearing: the
 * source is still the answer the model gave, and hiding it would lose information.
 *
 * `messageId` and `blockIndex` are what a saved colour choice and a saved height are filed
 * under. A diagram in a reply that is still streaming has neither, so it renders with the
 * reader's defaults and its controls say the choice will be kept once the reply finishes.
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
    const [expanded, setExpanded] = useState(false);
    const [zoom, setZoom] = useState(1);
    const [panelWidth, setPanelWidth] = useState(0);
    const [downloadError, setDownloadError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    const { style, setStyle, reset, height, setHeight, resetHeight, canPersist, error } =
        useBlockVisualStyle('mermaid', source, messageId, blockIndex);

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
            setState({ status: 'error', reason: 'The diagram source is empty.' });
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
            .catch((renderError) => {
                // Logged as well as shown. Someone looking into a report that a diagram will
                // not draw needs the parser's own words, and the panel only shows them to
                // whoever happens to be reading that message.
                console.warn('Unable to render an inline diagram:', renderError);
                if (!cancelled) {
                    setState({ status: 'error', reason: describeMermaidError(renderError) });
                }
            });

        return () => {
            cancelled = true;
        };
    }, [source, theme, style, background, signature]);

    const svg = state.status === 'ready' ? state.svg : '';
    const size = useMemo(() => (svg ? readDiagramSize(svg) : null), [svg]);

    // The height someone chose for this diagram, or one derived from how it actually measures.
    const stageHeight = height ?? defaultStageHeight(size, panelWidth || size?.width || 0);

    /**
     * Save the diagram as it is currently drawn.
     *
     * Rasterized from the SVG already on screen rather than re-rendered, so the file matches
     * what the reader is looking at, colours included.
     */
    const downloadPng = useCallback(
        async (element: SVGElement | null) => {
            const target = element ?? containerRef.current?.querySelector('svg') ?? null;
            if (!target) {
                return;
            }
            setDownloadError(null);
            try {
                const dataUri = await svgElementToPngDataUri(target, background);
                downloadDataUri(dataUri, `${diagramName(source)}.png`);
            } catch {
                setDownloadError('The diagram could not be saved as an image.');
            }
        },
        [background, source],
    );

    if (state.status === 'error') {
        return <DiagramSource source={source.trim()} reason={state.reason} />;
    }

    if (state.status === 'pending') {
        return (
            <div className="my-3 flex h-24 items-center justify-center rounded-xl bg-surface-sunken text-xs text-text-3">
                Rendering diagram…
            </div>
        );
    }

    return (
        <>
            <figure
                ref={containerRef}
                // A definite width, so the diagram sizes the panel instead of the panel sizing
                // the diagram. The assistant bubble is shrink-to-fit and mermaid emits
                // `width: 100%`, which contributes nothing to intrinsic sizing: without this the
                // bubble collapsed to the width of this toolbar and the diagram was drawn
                // illegibly small, then jumped wider whenever the colour menu — which does have
                // a natural width — was opened.
                style={
                    size
                        ? { width: Math.max(size.width, MIN_FIGURE_WIDTH), maxWidth: '100%' }
                        : undefined
                }
                className="my-3 overflow-hidden rounded-xl border border-edge-strong bg-surface-sunken"
            >
                <DiagramStage
                    size={size}
                    height={stageHeight}
                    zoom={zoom}
                    onResize={setHeight}
                    onResetHeight={resetHeight}
                    onPanelWidth={setPanelWidth}
                    // Set only once someone has chosen colours, so an untouched diagram keeps
                    // the panel surface it has always sat on.
                    background={styled ? background : undefined}
                >
                    <div
                        // Sanitized in `renderDiagram` by DOMPurify, after mermaid generated it
                        // under securityLevel 'strict'. SVG cannot be expressed as React
                        // children here.
                        dangerouslySetInnerHTML={{ __html: state.svg }}
                        className="h-full w-full"
                    />
                </DiagramStage>

                <div className="flex flex-wrap items-center gap-1 px-3 pb-2">
                    <ZoomControls zoom={zoom} onZoom={setZoom} onReset={() => setZoom(1)} />

                    <div className="ml-auto flex flex-wrap items-center gap-1">
                        <button
                            type="button"
                            onClick={() => setExpanded(true)}
                            title="View the diagram full screen"
                            aria-haspopup="dialog"
                            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <Maximize2 size={13} />
                            Expand
                        </button>

                        <button
                            type="button"
                            onClick={() => void downloadPng(null)}
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
                </div>

                {downloadError && !menuOpen && (
                    <p className="px-3 pb-2 text-right text-[11px] text-danger">{downloadError}</p>
                )}
            </figure>

            {/* Outside the figure, which clips its overflow and would otherwise be an odd place
                to nest a dialog. */}
            {expanded && (
                <DiagramLightbox
                    svg={state.svg}
                    size={size}
                    title={source.trim().split('\n', 1)[0] || 'Diagram'}
                    background={styled ? background : undefined}
                    onDownload={(element) => void downloadPng(element)}
                    onClose={() => setExpanded(false)}
                />
            )}
        </>
    );
}
