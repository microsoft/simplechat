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
    PenLine,
    Plus,
    Scan,
    TriangleAlert,
    X,
} from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import { useBlockVisualStyle } from '../../lib/blockVisualStyle';
import { useBlockRevisions } from '../../lib/blockRevisions';
import {
    isDefaultVisualStyle,
    resolveBackgroundColor,
    themeSurfaceColor,
    visualStyleSignature,
    type VisualStyle,
} from '../../lib/visualPalettes';
import { describeMermaidError } from '../../lib/mermaidSource';
import { peekMermaidSvg, renderMermaidSvg } from '../../lib/mermaidRuntime';
import { downloadDataUri, fileNameStem, svgElementToPngDataUri } from '../../lib/svgRaster';
import { registerExportDiagram } from '../../lib/exportVisuals';
import { VisualStyleMenu } from './VisualStyleMenu';
import { DiagramEditor } from './DiagramEditor';
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
                            // Sanitized in `renderMermaidSvg` by DOMPurify, after mermaid
                            // generated it under securityLevel 'strict'. SVG cannot be
                            // expressed as React children here.
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
 * Render a diagram, reporting progress as state.
 *
 * Extracted so the inline panel and the editor's live preview draw diagrams the same way, and
 * so both go through `renderMermaidSvg`, which is where the DOMPurify boundary and mermaid's
 * strict configuration live.
 */
function useRenderedDiagram(
    source: string,
    theme: string,
    style: VisualStyle,
    background: string,
    signature: string,
): DiagramState {
    const [state, setState] = useState<DiagramState>({ status: 'pending' });

    useEffect(() => {
        const trimmed = source.trim();
        if (trimmed === '') {
            setState({ status: 'error', reason: 'The diagram source is empty.' });
            return;
        }

        const cached = peekMermaidSvg(theme, signature, trimmed);
        if (cached !== undefined) {
            setState({ status: 'ready', svg: cached });
            return;
        }

        setState({ status: 'pending' });
        let cancelled = false;

        renderMermaidSvg(trimmed, theme, style, background, signature)
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

    return state;
}

/**
 * A diagram drawn from an arbitrary source, for the editor's live preview.
 *
 * Lives in this file rather than beside the editor because it writes diagram markup to the DOM,
 * and every such sink is deliberately kept here — see the header, and the boundary check in
 * test_v2_rich_rendering.py.
 */
function DiagramPreview({
    source,
    theme,
    style,
    background,
    signature,
}: {
    source: string;
    theme: string;
    style: VisualStyle;
    background: string;
    signature: string;
}) {
    const state = useRenderedDiagram(source, theme, style, background, signature);

    if (state.status === 'pending') {
        return (
            <div className="flex h-24 items-center justify-center text-xs text-text-3">
                Rendering diagram…
            </div>
        );
    }

    if (state.status === 'error') {
        return <DiagramSource source={source.trim()} reason={state.reason} />;
    }

    return (
        <div
            // Sanitized in `renderMermaidSvg` by DOMPurify, after mermaid generated it under
            // securityLevel 'strict'. SVG cannot be expressed as React children here.
            dangerouslySetInnerHTML={{ __html: state.svg }}
            className="mx-auto [&_svg]:h-auto [&_svg]:max-w-full"
        />
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
    const [menuOpen, setMenuOpen] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [editing, setEditing] = useState(false);
    const [zoom, setZoom] = useState(1);
    const [panelWidth, setPanelWidth] = useState(0);
    const [downloadError, setDownloadError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // Deliberately keyed off `source`, the block's original text, not the version being shown.
    // Colours are filed under the original's fingerprint, so editing a diagram keeps whatever
    // colours were chosen for it instead of silently resetting them.
    const { style, setStyle, reset, height, setHeight, resetHeight, canPersist, error } =
        useBlockVisualStyle('mermaid', source, messageId, blockIndex);

    const revisions = useBlockRevisions('mermaid', source, messageId, blockIndex);
    /** The version to draw, export and download: the current revision, or the original. */
    const shownSource = revisions.source;

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

    const state = useRenderedDiagram(shownSource, theme, style, background, signature);

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
                downloadDataUri(dataUri, `${diagramName(shownSource)}.png`);
            } catch {
                setDownloadError('The diagram could not be saved as an image.');
            }
        },
        [background, shownSource],
    );

    /**
     * Offer this diagram to a Word, PowerPoint or email export of the same message.
     *
     * The SVG is read back at export time rather than captured here, so the export gets the
     * diagram as it stands, and a message whose diagrams are all registered never makes the
     * server start a browser to redraw them.
     */
    useEffect(
        () =>
            registerExportDiagram(messageId, blockIndex, {
                source: shownSource,
                background,
                getSvg: () => containerRef.current?.querySelector('svg') ?? null,
            }),
        [messageId, blockIndex, shownSource, background],
    );

    if (state.status === 'error') {
        return <DiagramSource source={shownSource.trim()} reason={state.reason} />;
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
                        // Sanitized in `renderMermaidSvg` by DOMPurify, after mermaid generated
                        // it under securityLevel 'strict'. SVG cannot be expressed as React
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
                            onClick={() => setEditing(true)}
                            title="Edit this diagram"
                            aria-haspopup="dialog"
                            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <PenLine size={13} />
                            Edit
                            {revisions.isEdited && (
                                <span
                                    title="This diagram has been edited"
                                    aria-label="Edited"
                                    className="size-1.5 rounded-full bg-accent"
                                />
                            )}
                        </button>

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
                    title={shownSource.trim().split('\n', 1)[0] || 'Diagram'}
                    background={styled ? background : undefined}
                    onDownload={(element) => void downloadPng(element)}
                    onClose={() => setExpanded(false)}
                />
            )}

            {editing && (
                <DiagramEditor
                    title={shownSource.trim().split('\n', 1)[0] || 'Diagram'}
                    currentSource={shownSource}
                    revisions={revisions.revisions}
                    currentIndex={revisions.currentIndex}
                    chat={revisions.chat}
                    canPersist={revisions.canPersist}
                    busy={revisions.busy}
                    error={revisions.error}
                    onClearError={revisions.clearError}
                    onSave={revisions.save}
                    onRestore={revisions.restore}
                    onAsk={revisions.ask}
                    // Passed as a render prop so the editor never writes diagram markup itself:
                    // every such sink stays in this file, which is what the boundary check in
                    // test_v2_rich_rendering.py protects.
                    renderPreview={(previewSource) => (
                        <DiagramPreview
                            source={previewSource}
                            theme={theme}
                            style={style}
                            background={background}
                            signature={signature}
                        />
                    )}
                    onClose={() => setEditing(false)}
                />
            )}
        </>
    );
}
