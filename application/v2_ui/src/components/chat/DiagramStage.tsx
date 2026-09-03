// DiagramStage.tsx
// The scrolling, resizable area a rendered diagram is drawn in.
//
// Split out of MermaidDiagram so that the sizing behaviour — which is most of what makes a
// diagram readable — is separable from rendering it. This file deliberately contains no HTML
// sink: the markup it shows is passed in already sanitized, and every place diagram markup is
// written into the DOM stays in MermaidDiagram.tsx, so the reviewed sanitizer boundary remains
// a single file.
//
// Two numbers drive everything here:
//
//   - the diagram's natural size, read off the SVG mermaid emitted. Mermaid renders with
//     `useMaxWidth: true`, which produces `width="100%"`, no height attribute and
//     `style="max-width: Npx"`. A percentage width contributes nothing to intrinsic sizing, so
//     a diagram in the shrink-to-fit assistant bubble collapsed the bubble to the width of its
//     own toolbar and then scaled itself down to match. Reading N back and applying it as a
//     definite width is what stops that.
//
//   - the stage height, which is capped. A flowchart with a few hundred edges renders tens of
//     thousands of pixels tall; left in the message list, the browser re-rasterizes it on every
//     scroll frame and the thread becomes unusable.

import { useCallback, useEffect, useRef, useState } from 'react';

/** Smallest stage a reader can drag to. Below this the diagram is not worth showing. */
export const MIN_STAGE_HEIGHT = 140;

/** Largest stage a reader can drag to, and the ceiling on a persisted height. */
export const MAX_STAGE_HEIGHT = 2000;

/**
 * Tallest a diagram is drawn at before its stage starts scrolling.
 *
 * Roughly two thirds of a laptop viewport: tall enough that most diagrams are shown whole,
 * short enough that a very long one does not push the rest of the reply off the screen or
 * leave a huge SVG in the scroll container.
 */
export const DEFAULT_MAX_STAGE_HEIGHT = 520;

/** Narrowest the panel goes, so the toolbar never wraps into a column. */
export const MIN_FIGURE_WIDTH = 320;

/**
 * The stage's own padding, top and bottom.
 *
 * Kept as a number because the automatic height has to account for it: the height is set on the
 * padding box, so a stage sized to the diagram alone is short by exactly this much and shows a
 * scrollbar on a diagram that actually fits.
 */
const STAGE_PADDING = 24;

/** Zoom bounds, as a multiple of the scale that fits the diagram to the stage width. */
export const MIN_ZOOM = 0.4;
export const MAX_ZOOM = 4;

/** Multiplier per press of the zoom buttons. */
export const ZOOM_STEP = 1.25;

/** How much one arrow-key press moves the resize handle. */
const RESIZE_KEY_STEP = 40;

export interface DiagramSize {
    width: number;
    height: number;
}

export function clampStageHeight(value: number): number {
    return Math.min(MAX_STAGE_HEIGHT, Math.max(MIN_STAGE_HEIGHT, Math.round(value)));
}

export function clampZoom(value: number): number {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

/**
 * Read a rendered diagram's natural size out of the SVG markup.
 *
 * `max-width` is what mermaid writes when `useMaxWidth` is on and is the authoritative natural
 * width; the viewBox is the fallback and the only source of the height, because mermaid writes
 * no height attribute in that mode. Returns null rather than a guess when neither is present,
 * so the caller can fall back to letting the browser size the diagram as it did before.
 */
export function readDiagramSize(svg: string): DiagramSize | null {
    const viewBox = /viewBox="([^"]*)"/.exec(svg);
    const parts = viewBox
        ? viewBox[1].trim().split(/[\s,]+/).map(Number)
        : [];
    const boxWidth = parts.length === 4 && Number.isFinite(parts[2]) ? parts[2] : 0;
    const boxHeight = parts.length === 4 && Number.isFinite(parts[3]) ? parts[3] : 0;

    const maxWidth = /max-width:\s*([0-9.]+)px/.exec(svg);
    const declaredWidth = maxWidth ? Number(maxWidth[1]) : 0;

    const width = Number.isFinite(declaredWidth) && declaredWidth > 0 ? declaredWidth : boxWidth;
    if (!(width > 0) || !(boxHeight > 0)) {
        return null;
    }

    // The height that goes with `width`, since the two can differ when mermaid's declared
    // max-width has been rounded away from the viewBox.
    const height = boxWidth > 0 ? (boxHeight * width) / boxWidth : boxHeight;
    return { width: Math.round(width), height: Math.round(height) };
}

/**
 * The stage height to use when nobody has chosen one.
 *
 * The diagram is fitted to the panel width first, because that is how it will actually be
 * drawn, and the resulting height is then capped. A wide, short diagram therefore gets a short
 * stage rather than an empty one, and a tall diagram gets a scrolling stage rather than a
 * thousand-pixel block in the thread.
 *
 * `panelWidth` is the stage's content width, so the padding is added back afterwards.
 */
export function defaultStageHeight(size: DiagramSize | null, panelWidth: number): number {
    if (!size || panelWidth <= 0) {
        return MIN_STAGE_HEIGHT;
    }
    const fitted = size.height * Math.min(1, panelWidth / size.width);
    return clampStageHeight(Math.min(fitted + STAGE_PADDING, DEFAULT_MAX_STAGE_HEIGHT));
}

/**
 * A grab bar for resizing the stage.
 *
 * A separate control rather than CSS `resize`, which cannot be operated from the keyboard and
 * offers no way back to the automatic height. Exposed as a slider because that is what it is:
 * a single value with a range, a current position and a meaningful reset.
 */
function ResizeHandle({
    height,
    onResize,
    onReset,
}: {
    height: number;
    onResize: (next: number) => void;
    onReset: () => void;
}) {
    const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);

    const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
        event.preventDefault();
        dragRef.current = { startY: event.clientY, startHeight: height };
        event.currentTarget.setPointerCapture(event.pointerId);
    };

    const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
        const drag = dragRef.current;
        if (!drag) {
            return;
        }
        onResize(clampStageHeight(drag.startHeight + (event.clientY - drag.startY)));
    };

    const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
        if (!dragRef.current) {
            return;
        }
        dragRef.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
    };

    return (
        <div
            role="slider"
            tabIndex={0}
            aria-label="Diagram height"
            aria-valuenow={height}
            aria-valuemin={MIN_STAGE_HEIGHT}
            aria-valuemax={MAX_STAGE_HEIGHT}
            aria-orientation="vertical"
            title="Drag to resize the diagram. Home resets it."
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onKeyDown={(event) => {
                if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
                    event.preventDefault();
                    onResize(clampStageHeight(height + RESIZE_KEY_STEP));
                } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
                    event.preventDefault();
                    onResize(clampStageHeight(height - RESIZE_KEY_STEP));
                } else if (event.key === 'Home') {
                    event.preventDefault();
                    onReset();
                }
            }}
            className="group/handle flex cursor-ns-resize touch-none items-center justify-center py-1 outline-none"
        >
            <span
                aria-hidden="true"
                className="h-1 w-10 rounded-full bg-edge-strong transition-colors group-hover/handle:bg-accent group-focus/handle:bg-accent"
            />
        </div>
    );
}

/**
 * The area a diagram is drawn in, with its own scrolling and a handle to resize it.
 *
 * `children` is the already-rendered diagram. This component owns only how much room it gets
 * and how far it is scaled; it never touches the markup.
 */
export function DiagramStage({
    size,
    height,
    zoom,
    onResize,
    onResetHeight,
    onPanelWidth,
    background,
    children,
}: {
    size: DiagramSize | null;
    height: number;
    /** Multiplier applied on top of fitting the diagram to the stage width. */
    zoom: number;
    onResize: (next: number) => void;
    onResetHeight: () => void;
    /** Reports the stage's laid-out width, which the fit scale is computed from. */
    onPanelWidth: (width: number) => void;
    background?: string;
    children: React.ReactNode;
}) {
    const stageRef = useRef<HTMLDivElement>(null);
    const [panelWidth, setPanelWidth] = useState(0);

    const report = useCallback(
        (width: number) => {
            setPanelWidth(width);
            onPanelWidth(width);
        },
        [onPanelWidth],
    );

    // The stage width is what the fit scale divides by, and it changes when the window is
    // resized, the sidebar is toggled or the reading-width preference is changed.
    useEffect(() => {
        const element = stageRef.current;
        if (!element || typeof ResizeObserver === 'undefined') {
            return;
        }
        report(element.clientWidth);
        const observer = new ResizeObserver((entries) => {
            const width = entries[0]?.contentRect.width ?? element.clientWidth;
            report(width);
        });
        observer.observe(element);
        return () => observer.disconnect();
    }, [report]);

    const fitScale = size && panelWidth > 0 ? Math.min(1, panelWidth / size.width) : 1;
    const scale = fitScale * zoom;

    return (
        <>
            <div
                ref={stageRef}
                style={{
                    // Only when the diagram could be measured. An unmeasured one is left to
                    // size itself, which is what it did before any of this existed, rather
                    // than being squeezed into a stage built from a height it did not inform.
                    ...(size ? { height } : {}),
                    ...(background ? { backgroundColor: background } : {}),
                }}
                // `contain` keeps a large diagram's paint work inside this box, which is what
                // stops a tall one from making the whole thread scroll badly.
                className="overflow-auto p-3 [contain:content]"
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
                        // The SVG carries mermaid's own `width: 100%`, so it fills this box,
                        // which is held at the diagram's natural size and scaled as a whole.
                        // Scaling the wrapper rather than the SVG keeps text crisp at any zoom.
                        className="[&_svg]:h-full [&_svg]:w-full [&_svg]:max-w-none"
                    >
                        {children}
                    </div>
                </div>
            </div>

            <ResizeHandle height={height} onResize={onResize} onReset={onResetHeight} />
        </>
    );
}
