// imageMask.ts
// Turning a reader's selection into the mask the images API expects.
//
// A mask is a PNG with an alpha channel where **fully transparent pixels mark the region to
// change** and opaque pixels are preserved. That polarity is the detail most easily got
// backwards, and getting it backwards produces an edit that changes everything *except* what
// was selected — which looks like a model failure rather than a bug.
//
// So it is not written by hand here. The canvas is filled opaque and the selection is *erased*
// out of it with `destination-out`, which produces the required polarity by construction. The
// server verifies it independently.
//
// The mask is always built at the image's natural pixel size, never at the size it happens to
// be laid out at, because the API requires the mask and the image to have identical dimensions.
//
// Nothing here reads the source image's pixels, only its dimensions, so the canvas is never
// tainted and no cross-origin question arises.

/** A rectangle in natural image pixels. */
export interface MaskRect {
    x: number;
    y: number;
    width: number;
    height: number;
}

/** A freehand stroke, in natural image pixels. */
export interface MaskStroke {
    points: { x: number; y: number }[];
    /** Brush diameter in natural image pixels. */
    size: number;
}

export type MaskShape =
    | { kind: 'rect'; rect: MaskRect }
    | { kind: 'stroke'; stroke: MaskStroke };

/** The nine regions the keyboard picker offers, in reading order. */
export const MASK_REGION_KEYS = [
    'top-left',
    'top-center',
    'top-right',
    'middle-left',
    'middle-center',
    'middle-right',
    'bottom-left',
    'bottom-center',
    'bottom-right',
] as const;

export type MaskRegionKey = (typeof MASK_REGION_KEYS)[number];

export const MASK_REGION_LABELS: Record<MaskRegionKey, string> = {
    'top-left': 'Top left',
    'top-center': 'Top centre',
    'top-right': 'Top right',
    'middle-left': 'Middle left',
    'middle-center': 'Centre',
    'middle-right': 'Middle right',
    'bottom-left': 'Bottom left',
    'bottom-center': 'Bottom centre',
    'bottom-right': 'Bottom right',
};

/**
 * The rectangle one of the nine named regions covers.
 *
 * The grid exists because drawing is a pointer-only interaction, and a feature that can only be
 * reached with a mouse is one a keyboard or screen-reader user cannot use at all. Selecting
 * regions produces exactly the same kind of shape as dragging a rectangle over them, so the two
 * are not separate code paths with separate bugs.
 */
export function maskRegionRect(
    region: MaskRegionKey,
    width: number,
    height: number,
): MaskRect {
    const index = MASK_REGION_KEYS.indexOf(region);
    const column = index % 3;
    const row = Math.floor(index / 3);

    // Computed from boundaries rather than as `column * (width / 3)` so that three adjacent
    // regions tile the image exactly, with no seam left by rounding between them.
    const left = Math.round((column * width) / 3);
    const right = Math.round(((column + 1) * width) / 3);
    const top = Math.round((row * height) / 3);
    const bottom = Math.round(((row + 1) * height) / 3);

    return { x: left, y: top, width: right - left, height: bottom - top };
}

/**
 * Where the picture is actually drawn inside an element that uses `object-contain`.
 *
 * This is the difference between the element's box and the picture inside it. The image is laid
 * out with a full width and a capped height, so the box's aspect ratio almost never matches the
 * image's and `object-contain` letterboxes the picture inside it — centred, with bars on two
 * sides.
 *
 * Mapping a pointer straight through the element box therefore stretches the coordinates
 * relative to the picture, and the mask ends up covering a region compressed toward the centre.
 * The model then edits the wrong part of the image, on a paid call, with a preview that looked
 * right because the preview canvas is letterboxed by the browser in step with the picture.
 */
export function containedImageRect(
    boxWidth: number,
    boxHeight: number,
    naturalWidth: number,
    naturalHeight: number,
): MaskRect {
    if (boxWidth <= 0 || boxHeight <= 0 || naturalWidth <= 0 || naturalHeight <= 0) {
        return { x: 0, y: 0, width: 0, height: 0 };
    }

    const scale = Math.min(boxWidth / naturalWidth, boxHeight / naturalHeight);
    const width = naturalWidth * scale;
    const height = naturalHeight * scale;

    return {
        x: (boxWidth - width) / 2,
        y: (boxHeight - height) / 2,
        width,
        height,
    };
}

/**
 * Convert a position within an element's box into natural image pixels.
 *
 * Returns null when the pointer is outside the picture itself, which is a real place to be:
 * the letterbox bars are part of the element and clicking them means nothing.
 */
export function pointerToImagePoint(
    offsetX: number,
    offsetY: number,
    boxWidth: number,
    boxHeight: number,
    naturalWidth: number,
    naturalHeight: number,
): { x: number; y: number } | null {
    const drawn = containedImageRect(boxWidth, boxHeight, naturalWidth, naturalHeight);
    if (drawn.width <= 0 || drawn.height <= 0) {
        return null;
    }

    return {
        x: ((offsetX - drawn.x) / drawn.width) * naturalWidth,
        y: ((offsetY - drawn.y) / drawn.height) * naturalHeight,
    };
}

/** Normalise a drag into a positive-area rectangle clamped to the image. */
export function normalizeRect(
    from: { x: number; y: number },
    to: { x: number; y: number },
    width: number,
    height: number,
): MaskRect {
    const left = Math.max(0, Math.min(Math.min(from.x, to.x), width));
    const top = Math.max(0, Math.min(Math.min(from.y, to.y), height));
    const right = Math.max(0, Math.min(Math.max(from.x, to.x), width));
    const bottom = Math.max(0, Math.min(Math.max(from.y, to.y), height));
    return { x: left, y: top, width: right - left, height: bottom - top };
}

/** Paint the selected shapes onto a context that is already filled opaque. */
function eraseShapes(
    context: CanvasRenderingContext2D,
    shapes: MaskShape[],
): void {
    // `destination-out` removes what is drawn, so painting here *creates* transparency. That is
    // the whole trick: the selection becomes the transparent region the API edits, without
    // anything having to remember to invert.
    context.globalCompositeOperation = 'destination-out';
    context.fillStyle = 'rgba(0, 0, 0, 1)';
    context.strokeStyle = 'rgba(0, 0, 0, 1)';
    context.lineCap = 'round';
    context.lineJoin = 'round';

    for (const shape of shapes) {
        if (shape.kind === 'rect') {
            const { x, y, width, height } = shape.rect;
            if (width > 0 && height > 0) {
                context.fillRect(x, y, width, height);
            }
            continue;
        }

        const { points, size } = shape.stroke;
        if (points.length === 0) {
            continue;
        }

        context.lineWidth = Math.max(1, size);
        if (points.length === 1) {
            context.beginPath();
            context.arc(points[0].x, points[0].y, Math.max(1, size) / 2, 0, Math.PI * 2);
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

    context.globalCompositeOperation = 'source-over';
}

/** Whether any shape would actually remove something. */
export function hasSelection(shapes: MaskShape[]): boolean {
    return shapes.some((shape) =>
        shape.kind === 'rect'
            ? shape.rect.width > 0 && shape.rect.height > 0
            : shape.stroke.points.length > 0,
    );
}

/**
 * Render the selection as a mask PNG data URL at the image's natural size.
 *
 * Returns null when nothing is selected, so a caller sends no mask rather than one that asks
 * the model to change nothing while still charging for the request.
 */
export function renderMaskDataUrl(
    shapes: MaskShape[],
    width: number,
    height: number,
): string | null {
    if (!hasSelection(shapes) || width <= 0 || height <= 0) {
        return null;
    }

    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width);
    canvas.height = Math.round(height);

    const context = canvas.getContext('2d');
    if (!context) {
        return null;
    }

    context.fillStyle = 'rgba(0, 0, 0, 1)';
    context.fillRect(0, 0, canvas.width, canvas.height);
    eraseShapes(context, shapes);

    return canvas.toDataURL('image/png');
}

/**
 * Approximately how much of the image the selection covers, as a fraction.
 *
 * Shown so a reader can tell a deliberate region from an accidental one before paying for a
 * generation. Measured off a downscaled render rather than the full-size one, because this runs
 * on every pointer move and the exact number matters much less than the response staying
 * smooth. The server measures the real mask for what it stores.
 */
export function estimateCoverage(
    shapes: MaskShape[],
    width: number,
    height: number,
): number {
    if (!hasSelection(shapes) || width <= 0 || height <= 0) {
        return 0;
    }

    const sampleWidth = Math.max(1, Math.min(120, Math.round(width)));
    const scale = sampleWidth / width;
    const sampleHeight = Math.max(1, Math.round(height * scale));

    const canvas = document.createElement('canvas');
    canvas.width = sampleWidth;
    canvas.height = sampleHeight;

    const context = canvas.getContext('2d');
    if (!context) {
        return 0;
    }

    context.fillStyle = 'rgba(0, 0, 0, 1)';
    context.fillRect(0, 0, sampleWidth, sampleHeight);
    context.scale(scale, scale);
    eraseShapes(context, shapes);

    const { data } = context.getImageData(0, 0, sampleWidth, sampleHeight);
    let transparent = 0;
    for (let index = 3; index < data.length; index += 4) {
        if (data[index] < 8) {
            transparent += 1;
        }
    }

    return transparent / (sampleWidth * sampleHeight);
}
