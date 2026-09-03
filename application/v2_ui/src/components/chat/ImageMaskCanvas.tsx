// ImageMaskCanvas.tsx
// Selecting the region of an image a change should apply to.
//
// This is the part of image editing a text instruction cannot express. "Make the sky orange" is
// unambiguous; "change this bit" is not, unless you can point at it.
//
// The mask is built by `imageMask.ts` at the image's natural pixel size, which is what the API
// requires. This component only collects shapes and draws a preview of them; it never produces
// the mask polarity itself, so there is one place where "transparent means edit" can be wrong
// rather than two.
//
// Drawing is a pointer-only interaction, so a nine-region grid offers the same selection from
// the keyboard. That is not a token gesture: it produces the same `MaskShape` values a drag
// would, so both paths go through identical code.

import { useCallback, useEffect, useRef, useState } from 'react';
import { Brush, Grid3x3, Square, Undo2, X } from 'lucide-react';
import {
    estimateCoverage,
    MASK_REGION_KEYS,
    MASK_REGION_LABELS,
    maskRegionRect,
    normalizeRect,
    pointerToImagePoint,
    renderMaskDataUrl,
    type MaskRegionKey,
    type MaskShape,
} from '../../lib/imageMask';

/** Brush diameters offered, as a fraction of the image's smaller side. */
const BRUSH_SIZES = [
    { label: 'Small', fraction: 0.04 },
    { label: 'Medium', fraction: 0.09 },
    { label: 'Large', fraction: 0.18 },
];

type Tool = 'rect' | 'brush';

export interface MaskSelection {
    /** A PNG data URL whose transparent pixels mark the region to change, or null. */
    dataUrl: string | null;
    /** How many separate shapes were drawn, recorded with the version for the history. */
    regions: number;
    /** Roughly how much of the image is selected, as a fraction. */
    coverage: number;
}

export function ImageMaskCanvas({
    src,
    alt,
    disabled,
    onChange,
}: {
    src: string;
    alt: string;
    disabled?: boolean;
    onChange: (selection: MaskSelection) => void;
}) {
    const [shapes, setShapes] = useState<MaskShape[]>([]);
    const [tool, setTool] = useState<Tool>('rect');
    const [brushFraction, setBrushFraction] = useState(BRUSH_SIZES[1].fraction);
    const [showRegions, setShowRegions] = useState(false);
    const [natural, setNatural] = useState({ width: 0, height: 0 });
    const [drawing, setDrawing] = useState<MaskShape | null>(null);

    const imageRef = useRef<HTMLImageElement>(null);
    const overlayRef = useRef<HTMLCanvasElement>(null);

    const brushSize = Math.max(
        4,
        Math.round(Math.min(natural.width, natural.height) * brushFraction),
    );

    /** Convert a pointer position into natural image pixels. */
    const toImagePoint = useCallback(
        (event: React.PointerEvent) => {
            const element = imageRef.current;
            if (!element || !natural.width || !natural.height) {
                return null;
            }
            const bounds = element.getBoundingClientRect();
            // Through the *drawn* picture, not the element box. The image is laid out with a
            // full width and a capped height, so `object-contain` letterboxes it inside a box
            // whose aspect ratio almost never matches, and mapping through the box would
            // stretch every coordinate relative to what the reader is pointing at.
            return pointerToImagePoint(
                event.clientX - bounds.left,
                event.clientY - bounds.top,
                bounds.width,
                bounds.height,
                natural.width,
                natural.height,
            );
        },
        [natural.height, natural.width],
    );

    // Report the selection upward whenever it changes. Rendering the full-size mask on every
    // pointer move would be wasteful, so this runs on committed shapes only -- `drawing` is
    // previewed but not reported until the pointer is released.
    useEffect(() => {
        if (!natural.width || !natural.height) {
            return;
        }
        onChange({
            dataUrl: renderMaskDataUrl(shapes, natural.width, natural.height),
            regions: shapes.length,
            coverage: estimateCoverage(shapes, natural.width, natural.height),
        });
    }, [shapes, natural.width, natural.height, onChange]);

    // Draw the preview. The overlay is a highlight of what is selected, not the mask itself:
    // showing the reader a mostly-black rectangle with holes in it would be a poor way to
    // communicate "this is the part that will change".
    useEffect(() => {
        const canvas = overlayRef.current;
        if (!canvas || !natural.width || !natural.height) {
            return;
        }

        canvas.width = natural.width;
        canvas.height = natural.height;

        const context = canvas.getContext('2d');
        if (!context) {
            return;
        }

        context.clearRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = 'rgba(56, 189, 248, 0.35)';
        context.strokeStyle = 'rgba(56, 189, 248, 0.95)';
        context.lineCap = 'round';
        context.lineJoin = 'round';

        const preview = drawing ? [...shapes, drawing] : shapes;
        for (const shape of preview) {
            if (shape.kind === 'rect') {
                const { x, y, width, height } = shape.rect;
                context.fillRect(x, y, width, height);
                context.lineWidth = Math.max(2, natural.width / 300);
                context.strokeRect(x, y, width, height);
                continue;
            }

            const { points, size } = shape.stroke;
            if (points.length === 0) {
                continue;
            }
            context.lineWidth = size;
            if (points.length === 1) {
                context.beginPath();
                context.arc(points[0].x, points[0].y, size / 2, 0, Math.PI * 2);
                context.fill();
                continue;
            }
            context.beginPath();
            context.moveTo(points[0].x, points[0].y);
            for (const point of points.slice(1)) {
                context.lineTo(point.x, point.y);
            }
            context.stroke();
        }
    }, [shapes, drawing, natural.width, natural.height]);

    const handlePointerDown = (event: React.PointerEvent) => {
        if (disabled) {
            return;
        }
        const point = toImagePoint(event);
        if (!point) {
            return;
        }
        event.currentTarget.setPointerCapture(event.pointerId);

        setDrawing(
            tool === 'rect'
                ? { kind: 'rect', rect: { x: point.x, y: point.y, width: 0, height: 0 } }
                : { kind: 'stroke', stroke: { points: [point], size: brushSize } },
        );
    };

    const handlePointerMove = (event: React.PointerEvent) => {
        if (disabled || !drawing) {
            return;
        }
        const point = toImagePoint(event);
        if (!point) {
            return;
        }

        setDrawing((previous) => {
            if (!previous) {
                return previous;
            }
            if (previous.kind === 'rect') {
                const origin = { x: previous.rect.x, y: previous.rect.y };
                // The origin is kept as the anchor while the rectangle is normalised for
                // display, so dragging up and left works the same as down and right.
                const rect = normalizeRect(origin, point, natural.width, natural.height);
                return { kind: 'rect', rect: { ...rect, x: origin.x, y: origin.y } };
            }
            return {
                kind: 'stroke',
                stroke: {
                    ...previous.stroke,
                    points: [...previous.stroke.points, point],
                },
            };
        });
    };

    const handlePointerUp = (event: React.PointerEvent) => {
        if (!drawing) {
            return;
        }
        const point = toImagePoint(event);

        let committed: MaskShape | null = drawing;
        if (drawing.kind === 'rect' && point) {
            const rect = normalizeRect(
                { x: drawing.rect.x, y: drawing.rect.y },
                point,
                natural.width,
                natural.height,
            );
            // A click without a drag is not a rectangle. Discarded rather than stored as a
            // zero-area shape that would count toward the region total but select nothing.
            committed = rect.width > 1 && rect.height > 1 ? { kind: 'rect', rect } : null;
        }

        if (committed) {
            setShapes((previous) => [...previous, committed as MaskShape]);
        }
        setDrawing(null);
    };

    const toggleRegion = (region: MaskRegionKey) => {
        const rect = maskRegionRect(region, natural.width, natural.height);
        setShapes((previous) => {
            const existing = previous.findIndex(
                (shape) =>
                    shape.kind === 'rect' &&
                    shape.rect.x === rect.x &&
                    shape.rect.y === rect.y &&
                    shape.rect.width === rect.width &&
                    shape.rect.height === rect.height,
            );
            if (existing >= 0) {
                return previous.filter((_, index) => index !== existing);
            }
            return [...previous, { kind: 'rect', rect }];
        });
    };

    const regionSelected = (region: MaskRegionKey) => {
        const rect = maskRegionRect(region, natural.width, natural.height);
        return shapes.some(
            (shape) =>
                shape.kind === 'rect' &&
                shape.rect.x === rect.x &&
                shape.rect.y === rect.y &&
                shape.rect.width === rect.width &&
                shape.rect.height === rect.height,
        );
    };

    const ready = natural.width > 0 && natural.height > 0;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1">
                <ToolButton
                    active={tool === 'rect'}
                    disabled={disabled || !ready}
                    onClick={() => setTool('rect')}
                    label="Select a rectangle"
                >
                    <Square size={13} />
                    Box
                </ToolButton>
                <ToolButton
                    active={tool === 'brush'}
                    disabled={disabled || !ready}
                    onClick={() => setTool('brush')}
                    label="Paint a region freehand"
                >
                    <Brush size={13} />
                    Brush
                </ToolButton>
                <ToolButton
                    active={showRegions}
                    disabled={disabled || !ready}
                    onClick={() => setShowRegions((previous) => !previous)}
                    label="Choose regions from a grid, without a mouse"
                >
                    <Grid3x3 size={13} />
                    Regions
                </ToolButton>

                <div className="ml-auto flex items-center gap-1">
                    <button
                        type="button"
                        onClick={() => setShapes((previous) => previous.slice(0, -1))}
                        disabled={disabled || shapes.length === 0}
                        title="Undo the last selection"
                        aria-label="Undo the last selection"
                        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        <Undo2 size={13} />
                        Undo
                    </button>
                    <button
                        type="button"
                        onClick={() => setShapes([])}
                        disabled={disabled || shapes.length === 0}
                        title="Clear the selection"
                        aria-label="Clear the selection"
                        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        <X size={13} />
                        Clear
                    </button>
                </div>
            </div>

            {tool === 'brush' && (
                <div className="flex items-center gap-1">
                    <span className="text-[11px] text-text-3">Brush</span>
                    {BRUSH_SIZES.map((size) => (
                        <ToolButton
                            key={size.label}
                            active={brushFraction === size.fraction}
                            disabled={disabled || !ready}
                            onClick={() => setBrushFraction(size.fraction)}
                            label={`${size.label} brush`}
                        >
                            {size.label}
                        </ToolButton>
                    ))}
                </div>
            )}

            <div className="flex justify-center">
                {/*
                  The wrapper shrink-wraps the image rather than stretching it, so the element
                  box *is* the picture. That keeps the overlay canvas and the region grid --
                  both positioned with `inset-0` -- aligned with what the reader sees, instead
                  of with a letterboxed box that is wider or taller than the picture inside it.
                */}
                <div className="relative overflow-hidden rounded-xl border border-edge bg-surface-2">
                    <img
                        ref={imageRef}
                        src={src}
                        alt={alt}
                        draggable={false}
                        onLoad={(event) =>
                            setNatural({
                                // The natural size, never the laid-out size: the API requires
                                // the mask and the image to have identical pixel dimensions.
                                width: event.currentTarget.naturalWidth,
                                height: event.currentTarget.naturalHeight,
                            })
                        }
                        className="block max-h-[46vh] w-auto max-w-full select-none"
                    />

                    <canvas
                        ref={overlayRef}
                        aria-hidden="true"
                        className="pointer-events-none absolute inset-0 size-full"
                    />

                    <div
                        role="presentation"
                        onPointerDown={handlePointerDown}
                        onPointerMove={handlePointerMove}
                        onPointerUp={handlePointerUp}
                        onPointerCancel={handlePointerUp}
                        className={`absolute inset-0 ${
                            disabled || !ready ? 'cursor-not-allowed' : 'cursor-crosshair'
                        }`}
                    />

                    {showRegions && ready && (
                        <div className="absolute inset-0 grid grid-cols-3 grid-rows-3">
                            {MASK_REGION_KEYS.map((region) => {
                                const selected = regionSelected(region);
                                return (
                                    <button
                                        key={region}
                                        type="button"
                                        disabled={disabled}
                                        aria-pressed={selected}
                                        onClick={() => toggleRegion(region)}
                                        title={MASK_REGION_LABELS[region]}
                                        className={`border border-dashed transition-colors ${
                                            selected
                                                ? 'border-accent bg-accent/25'
                                                : 'border-white/40 hover:bg-white/10'
                                        }`}
                                    >
                                        <span className="sr-only">
                                            {MASK_REGION_LABELS[region]}
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function ToolButton({
    active,
    disabled,
    onClick,
    label,
    children,
}: {
    active: boolean;
    disabled?: boolean;
    onClick: () => void;
    label: string;
    children: React.ReactNode;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            title={label}
            aria-label={label}
            aria-pressed={active}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                active
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-edge-strong text-text-2 hover:bg-surface-2 hover:text-text-1'
            }`}
        >
            {children}
        </button>
    );
}
