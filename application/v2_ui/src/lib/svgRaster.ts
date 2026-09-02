// svgRaster.ts
// Turns a rendered SVG element into a PNG the browser can download.
//
// Mermaid produces SVG, and an SVG saved straight to disk is not much use for pasting into a
// document or a ticket. The path here — serialise, load through an <img>, paint onto a canvas —
// is the one static/js/chat/chat-visual-rasterizer.js already uses to embed diagrams in
// exported conversations, so both interfaces produce comparable images.
//
// Two details matter and are easy to get wrong:
//
//   - The SVG needs explicit pixel dimensions. Mermaid emits `width="100%"` with a viewBox,
//     and an <img> given that has no intrinsic size to rasterize at.
//   - The canvas needs an opaque fill first. A transparent PNG of dark text is invisible on
//     any dark surface it is later pasted onto.
//
// The data: URI this builds is same-document data, which `img-src 'self' data: https: blob:`
// in config.py already allows, so no Content-Security-Policy change is involved.

/** Retina-ish output without producing enormous files. */
const RASTER_SCALE = 2;

/** Canvas edge ceiling. Browsers refuse to allocate beyond a few thousand pixels per side. */
const MAX_CANVAS_EDGE = 4000;

const FALLBACK_WIDTH = 800;
const FALLBACK_HEIGHT = 600;

function parseLength(value: string | null): number {
    if (!value) {
        return 0;
    }
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
}

interface NormalizedSvg {
    markup: string;
    canvasWidth: number;
    canvasHeight: number;
}

/**
 * Give a copy of the SVG explicit dimensions and an opaque background.
 *
 * Works on a clone, so the diagram on screen keeps its responsive `max-width` sizing.
 */
function normalizeSvg(svg: SVGElement, background: string): NormalizedSvg {
    const clone = svg.cloneNode(true) as SVGElement;

    let width = parseLength(clone.getAttribute('width'));
    let height = parseLength(clone.getAttribute('height'));

    const viewBox = String(clone.getAttribute('viewBox') || '')
        .split(/[\s,]+/)
        .map(Number);
    if (viewBox.length === 4 && Number.isFinite(viewBox[2]) && Number.isFinite(viewBox[3])) {
        width = width || viewBox[2];
        height = height || viewBox[3];
    }

    // Falling back to the element's laid-out size covers a diagram sized purely by CSS.
    if (!width || !height) {
        const box = svg.getBoundingClientRect();
        width = width || box.width;
        height = height || box.height;
    }

    width = width || FALLBACK_WIDTH;
    height = height || FALLBACK_HEIGHT;

    clone.setAttribute('width', String(width));
    clone.setAttribute('height', String(height));
    clone.setAttribute('style', `max-width:none;background-color:${background};`);
    if (!clone.getAttribute('xmlns')) {
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    }
    if (!clone.getAttribute('xmlns:xlink')) {
        clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
    }

    const scale = Math.min(RASTER_SCALE, MAX_CANVAS_EDGE / Math.max(width, height));
    const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;

    return {
        markup: new XMLSerializer().serializeToString(clone),
        canvasWidth: Math.max(1, Math.round(width * safeScale)),
        canvasHeight: Math.max(1, Math.round(height * safeScale)),
    };
}

/** Base64 that survives non-ASCII diagram labels, which `btoa` alone does not. */
function encodeSvg(markup: string): string {
    const bytes = new TextEncoder().encode(markup);
    let binary = '';
    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }
    return btoa(binary);
}

/** Paint an SVG element onto an opaque canvas and read it back as a PNG data URI. */
export function svgElementToPngDataUri(svg: SVGElement, background: string): Promise<string> {
    const normalized = normalizeSvg(svg, background);

    return new Promise((resolve, reject) => {
        const image = new Image();

        image.onload = () => {
            try {
                const canvas = document.createElement('canvas');
                canvas.width = normalized.canvasWidth;
                canvas.height = normalized.canvasHeight;

                const context = canvas.getContext('2d');
                if (!context) {
                    reject(new Error('Canvas is unavailable in this browser.'));
                    return;
                }

                context.fillStyle = background;
                context.fillRect(0, 0, canvas.width, canvas.height);
                context.drawImage(image, 0, 0, canvas.width, canvas.height);
                resolve(canvas.toDataURL('image/png'));
            } catch (error) {
                reject(error instanceof Error ? error : new Error('Rasterizing failed.'));
            }
        };
        image.onerror = () => reject(new Error('Unable to rasterize the diagram.'));

        image.src = `data:image/svg+xml;base64,${encodeSvg(normalized.markup)}`;
    });
}

/** Trigger a download of a data URI under the given file name. */
export function downloadDataUri(dataUri: string, fileName: string) {
    const link = document.createElement('a');
    link.href = dataUri;
    link.download = fileName;
    link.click();
}

/** A safe, readable file name stem from arbitrary text. */
export function fileNameStem(text: string, fallback: string): string {
    const slug = text
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60);
    return slug || fallback;
}
