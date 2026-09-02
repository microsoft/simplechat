// chat-visual-rasterizer.js
/**
 * Browser-side rasterizer for export visuals that need a PNG.
 *
 * Mermaid only renders in a browser, so the diagrams in a message are rasterized here
 * and sent to the export endpoints as `visual_assets`. The server matches each asset
 * back to its fence by normalized source text and embeds the PNG in the document.
 *
 * The Mermaid bundle is large, so it is loaded from its local static path on first use
 * rather than on page load. A diagram that fails to render is skipped, which leaves the
 * original code fence in the exported document.
 */

const MERMAID_SCRIPT_PATH = '/static/js/mermaid/mermaid-11.17.2.min.js';
const MERMAID_FENCE_REGEX = /```mermaid[ \t]*\r?\n([\s\S]*?)```/gi;
const CONVERSATION_VISUAL_SCAN_URL = '/api/conversations/export/visual-scan';

const MERMAID_LOAD_TIMEOUT_MS = 20000;
const MERMAID_RENDER_TIMEOUT_MS = 10000;
const MERMAID_RASTER_SCALE = 2;
const MERMAID_MAX_DIAGRAMS = 20;
const MERMAID_MAX_CANVAS_EDGE = 4000;
const MERMAID_FALLBACK_WIDTH = 800;
const MERMAID_FALLBACK_HEIGHT = 600;

const VISUAL_KIND_DIAGRAM = 'diagram';

let mermaidLoaderPromise = null;
let mermaidRenderSequence = 0;

/**
 * Normalize a fence body so it matches the server's normalize_visual_source().
 */
export function normalizeVisualSource(value) {
    const text = String(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const lines = text.split('\n').map((line) => line.replace(/\s+$/, ''));
    while (lines.length && !lines[0].trim()) {
        lines.shift();
    }
    while (lines.length && !lines[lines.length - 1].trim()) {
        lines.pop();
    }
    return lines.join('\n');
}

/**
 * Collect the distinct Mermaid diagram sources in a markdown string.
 */
export function extractMermaidSources(markdownContent) {
    const content = String(markdownContent || '');
    if (!content) {
        return [];
    }

    const sources = [];
    const seenSources = new Set();
    MERMAID_FENCE_REGEX.lastIndex = 0;

    let match = MERMAID_FENCE_REGEX.exec(content);
    while (match !== null) {
        const normalizedSource = normalizeVisualSource(match[1] || '');
        if (normalizedSource && !seenSources.has(normalizedSource)) {
            seenSources.add(normalizedSource);
            sources.push(normalizedSource);
        }
        if (sources.length >= MERMAID_MAX_DIAGRAMS) {
            break;
        }
        match = MERMAID_FENCE_REGEX.exec(content);
    }

    MERMAID_FENCE_REGEX.lastIndex = 0;
    return sources;
}

/**
 * Rasterize the Mermaid diagrams in a message, returning export `visual_assets`.
 */
export async function buildMessageVisualAssets(markdownContent) {
    const sources = extractMermaidSources(markdownContent);
    if (sources.length === 0) {
        return [];
    }
    return buildMermaidVisualAssets(sources.map((source) => ({ source })));
}

/**
 * Ask the server which diagrams the selected conversations contain, then rasterize them.
 */
export async function buildConversationVisualAssets(conversationIds) {
    const visualSources = await fetchConversationVisualSources(conversationIds);
    if (visualSources.length === 0) {
        return [];
    }
    return buildMermaidVisualAssets(visualSources);
}

/**
 * Fetch the diagram sources the server found in the given conversations.
 */
export async function fetchConversationVisualSources(conversationIds) {
    if (!Array.isArray(conversationIds) || conversationIds.length === 0) {
        return [];
    }

    try {
        const response = await fetch(CONVERSATION_VISUAL_SCAN_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation_ids: conversationIds }),
        });
        if (!response.ok) {
            return [];
        }

        const payload = await response.json();
        const visualSources = payload?.visual_sources;
        return Array.isArray(visualSources) ? visualSources : [];
    } catch (err) {
        console.warn('Unable to scan conversations for diagrams:', err);
        return [];
    }
}

/**
 * Rasterize diagram descriptors into export assets, skipping any that fail.
 */
export async function buildMermaidVisualAssets(visualSources) {
    if (!Array.isArray(visualSources) || visualSources.length === 0) {
        return [];
    }

    const assets = [];
    for (const visualSource of visualSources.slice(0, MERMAID_MAX_DIAGRAMS)) {
        const normalizedSource = normalizeVisualSource(visualSource?.source);
        if (!normalizedSource) {
            continue;
        }

        try {
            const dataUri = await renderMermaidToPngDataUri(normalizedSource);
            if (!dataUri) {
                continue;
            }
            assets.push({
                kind: VISUAL_KIND_DIAGRAM,
                source: normalizedSource,
                data_uri: dataUri,
                alt: String(visualSource?.alt || ''),
                caption: String(visualSource?.caption || ''),
            });
        } catch (err) {
            console.warn('Skipping a diagram that could not be rendered for export:', err);
        }
    }

    return assets;
}

/**
 * Render one diagram to a PNG data URI.
 */
async function renderMermaidToPngDataUri(normalizedSource) {
    const mermaid = await loadMermaid();
    mermaidRenderSequence += 1;
    const renderId = `simplechat-export-mermaid-${Date.now()}-${mermaidRenderSequence}`;

    const result = await withTimeout(
        mermaid.render(renderId, normalizedSource),
        MERMAID_RENDER_TIMEOUT_MS,
        'Timed out rendering a diagram for export.'
    );
    const svgMarkup = typeof result === 'string' ? result : result?.svg;
    if (!svgMarkup) {
        return '';
    }
    return svgToPngDataUri(svgMarkup);
}

/**
 * Load the vendored Mermaid bundle on first use.
 */
function loadMermaid() {
    if (mermaidLoaderPromise) {
        return mermaidLoaderPromise;
    }

    mermaidLoaderPromise = new Promise((resolve, reject) => {
        if (window.mermaid) {
            resolve(configureMermaid(window.mermaid));
            return;
        }

        const script = document.createElement('script');
        let settled = false;
        const timer = setTimeout(() => {
            if (!settled) {
                settled = true;
                reject(new Error('Timed out loading the Mermaid bundle.'));
            }
        }, MERMAID_LOAD_TIMEOUT_MS);

        script.src = MERMAID_SCRIPT_PATH;
        script.async = true;
        script.onload = () => {
            if (settled) {
                return;
            }
            settled = true;
            clearTimeout(timer);
            if (!window.mermaid) {
                reject(new Error('The Mermaid bundle loaded but did not register.'));
                return;
            }
            resolve(configureMermaid(window.mermaid));
        };
        script.onerror = () => {
            if (settled) {
                return;
            }
            settled = true;
            clearTimeout(timer);
            reject(new Error('Unable to load the local Mermaid bundle.'));
        };

        document.head.appendChild(script);
    });

    mermaidLoaderPromise.catch(() => {
        mermaidLoaderPromise = null;
    });
    return mermaidLoaderPromise;
}

/**
 * Configure Mermaid for rasterization.
 *
 * htmlLabels must stay off: labels drawn with <foreignObject> disappear when an SVG is
 * painted onto a canvas, which would produce diagrams with no text.
 */
function configureMermaid(mermaid) {
    mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        suppressErrorRendering: true,
        theme: 'neutral',
        htmlLabels: false,
        fontFamily: 'Arial, Helvetica, sans-serif',
        flowchart: { htmlLabels: false, useMaxWidth: false },
        sequence: { useMaxWidth: false },
        class: { htmlLabels: false, useMaxWidth: false },
    });
    return mermaid;
}

/**
 * Paint a rendered SVG onto a canvas and read it back as a PNG data URI.
 */
function svgToPngDataUri(svgMarkup) {
    return new Promise((resolve, reject) => {
        const normalized = normalizeSvgMarkup(svgMarkup);
        const image = new Image();

        image.onload = () => {
            try {
                const canvas = document.createElement('canvas');
                canvas.width = normalized.canvasWidth;
                canvas.height = normalized.canvasHeight;

                const context = canvas.getContext('2d');
                context.fillStyle = '#ffffff';
                context.fillRect(0, 0, canvas.width, canvas.height);
                context.drawImage(image, 0, 0, canvas.width, canvas.height);
                resolve(canvas.toDataURL('image/png'));
            } catch (err) {
                reject(err);
            }
        };
        image.onerror = () => reject(new Error('Unable to rasterize the diagram SVG.'));
        image.src = `data:image/svg+xml;base64,${base64EncodeUnicode(normalized.markup)}`;
    });
}

/**
 * Give the SVG explicit pixel dimensions so it rasterizes at a predictable size.
 */
function normalizeSvgMarkup(svgMarkup) {
    const parsed = new DOMParser().parseFromString(svgMarkup, 'image/svg+xml');
    const svgElement = parsed.documentElement;

    let width = parseSvgLength(svgElement.getAttribute('width'));
    let height = parseSvgLength(svgElement.getAttribute('height'));

    const viewBox = String(svgElement.getAttribute('viewBox') || '')
        .split(/[\s,]+/)
        .map(Number);
    if (viewBox.length === 4 && Number.isFinite(viewBox[2]) && Number.isFinite(viewBox[3])) {
        width = width || viewBox[2];
        height = height || viewBox[3];
    }

    width = width || MERMAID_FALLBACK_WIDTH;
    height = height || MERMAID_FALLBACK_HEIGHT;

    svgElement.setAttribute('width', String(width));
    svgElement.setAttribute('height', String(height));
    svgElement.setAttribute('style', 'max-width:none;background-color:#ffffff;');
    if (!svgElement.getAttribute('xmlns')) {
        svgElement.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    }

    const scale = Math.min(
        MERMAID_RASTER_SCALE,
        MERMAID_MAX_CANVAS_EDGE / Math.max(width, height)
    );
    const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;

    return {
        markup: new XMLSerializer().serializeToString(svgElement),
        canvasWidth: Math.max(1, Math.round(width * safeScale)),
        canvasHeight: Math.max(1, Math.round(height * safeScale)),
    };
}

/**
 * Read an SVG length attribute, ignoring relative units such as "100%".
 */
function parseSvgLength(value) {
    const candidate = String(value || '').trim();
    if (!candidate || candidate.includes('%')) {
        return 0;
    }
    const parsedLength = Number.parseFloat(candidate);
    return Number.isFinite(parsedLength) && parsedLength > 0 ? parsedLength : 0;
}

/**
 * Base64-encode UTF-8 markup without blowing the argument limit on large diagrams.
 */
function base64EncodeUnicode(text) {
    const bytes = new TextEncoder().encode(text);
    const chunkSize = 0x8000;
    let binary = '';
    for (let index = 0; index < bytes.length; index += chunkSize) {
        binary += String.fromCharCode.apply(null, bytes.subarray(index, index + chunkSize));
    }
    return btoa(binary);
}

function withTimeout(promise, timeoutMs, timeoutMessage) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
        Promise.resolve(promise).then(
            (value) => {
                clearTimeout(timer);
                resolve(value);
            },
            (err) => {
                clearTimeout(timer);
                reject(err);
            }
        );
    });
}
