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
import { api } from './apiClient';
import { MERMAID_EXPORT_PRESET, renderMermaidSvgForExport } from './mermaidRuntime';

/** Matches `MESSAGE_EXPORT_VISUAL_ASSET_MAX_COUNT` in route_backend_conversation_export.py. */
const MAX_ASSETS_PER_MESSAGE = 20;

/**
 * Matches `EXPORT_VISUAL_ASSET_MAX_COUNT` in functions_export_visuals.py.
 *
 * Deliberately not the per-message figure above. The conversation routes take the default
 * budget rather than passing the message one, so the scan endpoint returns up to 60 sources
 * and the export accepts up to 60 assets. Capping the client at 20 would fetch diagrams
 * 21-60 and then throw them away, leaving the server to render them in headless Chromium —
 * or, where that is unavailable, to emit them as raw code blocks.
 */
const MAX_ASSETS_PER_CONVERSATION_EXPORT = 60;

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

/** One diagram the server found while scanning conversations for an export. */
interface ConversationVisualSource {
    kind?: string;
    source: string;
}

interface VisualScanResponse {
    visual_sources?: ConversationVisualSource[];
}

/**
 * Ask the server which diagrams the given conversations contain.
 *
 * A conversation export covers messages that were never rendered — an old conversation, or
 * one that is not even open — so the registry above has nothing to offer. The server reads
 * the stored messages and returns the fence bodies instead, which the browser can then draw.
 */
export async function fetchConversationVisualSources(
    conversationIds: string[],
): Promise<ConversationVisualSource[]> {
    if (!Array.isArray(conversationIds) || conversationIds.length === 0) {
        return [];
    }

    const response = await api.post<VisualScanResponse>('/api/conversations/export/visual-scan', {
        conversation_ids: conversationIds,
    });

    return Array.isArray(response?.visual_sources) ? response.visual_sources : [];
}

/**
 * Turn one already-rendered SVG string into a PNG data URI.
 *
 * The markup is measured and painted through the same path an on-screen diagram takes, which
 * needs an element rather than a string. It is parsed and briefly attached off-screen so the
 * browser lays it out: a detached element reports a zero-sized bounding box, which is the
 * fallback `normalizeSvg` reaches for when a diagram carries no usable dimensions.
 *
 * `d-none` is deliberately not used here. A hidden element has no layout at all, so it would
 * defeat the point of attaching it; the host is instead positioned far outside the viewport.
 */
async function rasterizeSvgMarkup(markup: string): Promise<string> {
    const parsed = new DOMParser().parseFromString(markup, 'image/svg+xml');
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName === 'parsererror' || svg.nodeName.toLowerCase() !== 'svg') {
        throw new Error('The rendered diagram was not valid SVG.');
    }

    const host = document.createElement('div');
    host.setAttribute('aria-hidden', 'true');
    host.style.cssText =
        'position:absolute;left:-10000px;top:0;width:2000px;height:auto;pointer-events:none;';
    const adopted = document.importNode(svg, true) as unknown as SVGElement;
    host.appendChild(adopted);
    document.body.appendChild(host);

    try {
        return await svgElementToPngDataUri(adopted, MERMAID_EXPORT_PRESET.background);
    } finally {
        host.remove();
    }
}

/**
 * Rasterize every diagram in the given conversations into export assets.
 *
 * Never rejects, for the same reason the per-message version does not: a diagram that cannot
 * be drawn is left out and the server falls back to rendering it, so a broken diagram costs
 * fidelity rather than the whole export.
 *
 * Diagrams are drawn with the export preset rather than the reader's theme, because the file
 * is read outside the application where a dark diagram on white paper is unreadable.
 */
export async function buildConversationVisualAssets(
    conversationIds: string[],
): Promise<ExportVisualAsset[]> {
    let visualSources: ConversationVisualSource[];
    try {
        visualSources = await fetchConversationVisualSources(conversationIds);
    } catch {
        /* The export itself is still worth attempting; the server will draw them. */
        return [];
    }

    const assets: ExportVisualAsset[] = [];
    const seenSources = new Set<string>();

    for (const entry of visualSources) {
        if (assets.length >= MAX_ASSETS_PER_CONVERSATION_EXPORT) {
            break;
        }

        const source = normalizeVisualSource(entry?.source ?? '');
        if (!source || seenSources.has(source)) {
            continue;
        }
        seenSources.add(source);

        try {
            const markup = await renderMermaidSvgForExport(source);
            assets.push({
                kind: VISUAL_KIND_DIAGRAM,
                source,
                data_uri: await rasterizeSvgMarkup(markup),
            });
        } catch {
            /* Left for the server to render. */
        }
    }

    return assets;
}
