// exportVisuals.ts
// Supplies the export endpoints with pictures of the diagrams already drawn on screen.
//
// Without this, a V2 export sends only the message and conversation id, so the server has to
// re-render every diagram itself in headless Chromium. That costs roughly a second of browser
// startup per export, and the result is whatever the *server* environment can draw rather than
// what the reader is looking at — a container with no scalable font installed produces boxes
// with no text in them.
//
// The diagram is already rendered in the page, so it is rasterized from there instead. That
// removes the server round trip entirely for the common case and means the exported picture
// keeps the colours the reader chose.
//
// Anything not covered here still falls back to server-side rendering, so a diagram that fails
// to rasterize is omitted rather than sent broken.

import { svgElementToPngDataUri } from './svgRaster';

/** Matches `MESSAGE_EXPORT_VISUAL_ASSET_MAX_COUNT` in route_backend_conversation_export.py. */
const MAX_ASSETS_PER_MESSAGE = 20;

/** The only visual kind the browser rasterizes; charts and formulas are drawn server-side. */
const VISUAL_KIND_DIAGRAM = 'diagram';

/** One asset in the shape `normalize_visual_assets()` expects. */
export interface ExportVisualAsset {
    kind: string;
    source: string;
    data_uri: string;
    alt?: string;
    caption?: string;
}

interface RegisteredDiagram {
    messageId: string;
    source: string;
    background: string;
    /** Read at export time, so the picture matches the diagram as it is currently drawn. */
    getSvg: () => SVGElement | null;
}

/**
 * Diagrams currently mounted, keyed by message and block.
 *
 * Keyed rather than appended so a re-render replaces its own entry instead of accumulating,
 * and so unmounting removes exactly one diagram.
 */
const registry = new Map<string, RegisteredDiagram>();

function registryKey(messageId: string, blockIndex: number): string {
    return `${messageId}::${blockIndex}`;
}

/** Register a mounted diagram. Returns the cleanup an effect should run on unmount. */
export function registerExportDiagram(
    messageId: string | undefined,
    blockIndex: number | undefined,
    entry: Omit<RegisteredDiagram, 'messageId'>,
): () => void {
    // A reply that is still streaming has neither id, and its diagram cannot be exported yet.
    if (!messageId || blockIndex === undefined) {
        return () => {};
    }

    const key = registryKey(messageId, blockIndex);
    registry.set(key, { ...entry, messageId });

    return () => {
        // Guard against a later registration for the same slot having replaced this one.
        if (registry.get(key)?.getSvg === entry.getSvg) {
            registry.delete(key);
        }
    };
}

/**
 * Normalize a fence body the way the server's `normalize_visual_source()` does.
 *
 * The server matches each asset back to its fence by this exact text, so the two
 * implementations have to agree: line endings collapsed, trailing whitespace stripped per
 * line, and blank leading and trailing lines dropped.
 */
export function normalizeVisualSource(value: string): string {
    const lines = String(value ?? '')
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
        .split('\n')
        .map((line) => line.replace(/\s+$/, ''));

    while (lines.length > 0 && lines[0].trim() === '') {
        lines.shift();
    }
    while (lines.length > 0 && lines[lines.length - 1].trim() === '') {
        lines.pop();
    }

    return lines.join('\n');
}

/**
 * Rasterize the diagrams rendered for one message into export assets.
 *
 * Never rejects: an export must still go out when a diagram cannot be turned into a picture,
 * because the server renders whatever this does not cover.
 */
export async function buildMessageVisualAssets(messageId: string): Promise<ExportVisualAsset[]> {
    const assets: ExportVisualAsset[] = [];
    const seenSources = new Set<string>();

    for (const entry of registry.values()) {
        if (assets.length >= MAX_ASSETS_PER_MESSAGE) {
            break;
        }
        if (entry.messageId !== messageId) {
            continue;
        }

        const source = normalizeVisualSource(entry.source);
        if (!source || seenSources.has(source)) {
            continue;
        }

        const svg = entry.getSvg();
        if (!svg) {
            continue;
        }

        try {
            const dataUri = await svgElementToPngDataUri(svg, entry.background);
            seenSources.add(source);
            assets.push({ kind: VISUAL_KIND_DIAGRAM, source, data_uri: dataUri });
        } catch {
            /* Left for the server to render. */
        }
    }

    return assets;
}
