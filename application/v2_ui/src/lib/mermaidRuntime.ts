// mermaidRuntime.ts
// The shared Mermaid runtime: loading the vendored library, configuring it for untrusted
// input, and rendering one diagram to sanitized SVG.
//
// This lives apart from MermaidDiagram.tsx because two callers need it and only one of them
// is a component. Inline chat rendering draws diagrams that are on screen; conversation
// export has to draw diagrams from conversations nobody is looking at, so it cannot rely on
// a mounted component having already produced the SVG. The classic interface separates the
// same two concerns the same way, in static/js/chat/chat-mermaid-runtime.js.
//
// The sanitizer boundary for diagram markup lives here. Diagram source is model output, so
// mermaid runs at its 'strict' security level and its result is passed through DOMPurify
// before any caller writes it to the DOM. test_v2_rich_rendering.py asserts both halves.

import type { DomPurifyStatic, MermaidStatic } from './vendor';
import { VENDOR_PATHS, loadDomPurify, loadVendorScript } from './vendorAssets';
import {
    DEFAULT_VISUAL_STYLE,
    isDefaultVisualStyle,
    mermaidThemeVariables,
    visualStyleSignature,
    type VisualStyle,
} from './visualPalettes';
import { isRepairWorthTrying, repairMermaidSource } from './mermaidSource';

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
        // React's control. Failures are handled by the caller instead.
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

function cacheKey(theme: string, signature: string, source: string): string {
    return `${theme}|${signature}|${source}`;
}

function cacheSvg(key: string, svg: string) {
    if (svgCache.size >= MAX_CACHED_DIAGRAMS) {
        const oldest = svgCache.keys().next();
        if (!oldest.done) {
            svgCache.delete(oldest.value);
        }
    }
    svgCache.set(key, svg);
}

/**
 * The already-rendered SVG for a diagram, if there is one.
 *
 * Lets a component show a cached diagram in its first render rather than flashing a
 * "pending" state on the way to the same result.
 */
export function peekMermaidSvg(
    theme: string,
    signature: string,
    source: string,
): string | undefined {
    return svgCache.get(cacheKey(theme, signature, source));
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

/** Render one diagram to sanitized SVG markup. */
export async function renderMermaidSvg(
    source: string,
    theme: string,
    style: VisualStyle,
    background: string,
    signature: string,
): Promise<string> {
    const configKey = `${theme}|${signature}`;
    const key = cacheKey(theme, signature, source);
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

/**
 * How a diagram is drawn for an export rather than for the screen.
 *
 * Deliberately not the reader's current theme. An export is read outside the application —
 * pasted into Word, printed to PDF — where a dark diagram on white paper is unreadable, so
 * exports always use mermaid's stock light theme on an opaque white background. This mirrors
 * MERMAID_PRESET_EXPORT in static/js/chat/chat-visual-rasterizer.js.
 *
 * Per-diagram colour overrides are not applied here for the same reason: an export covers
 * whole conversations, and the overrides are addressed by a block's position within one
 * message, which an export has no reliable way to resolve.
 */
export const MERMAID_EXPORT_PRESET = Object.freeze({
    theme: 'light',
    style: DEFAULT_VISUAL_STYLE,
    background: '#ffffff',
    signature: visualStyleSignature(DEFAULT_VISUAL_STYLE, '#ffffff'),
});

/** Render one diagram the way an export needs it. */
export function renderMermaidSvgForExport(source: string): Promise<string> {
    return renderMermaidSvg(
        source,
        MERMAID_EXPORT_PRESET.theme,
        MERMAID_EXPORT_PRESET.style,
        MERMAID_EXPORT_PRESET.background,
        MERMAID_EXPORT_PRESET.signature,
    );
}
