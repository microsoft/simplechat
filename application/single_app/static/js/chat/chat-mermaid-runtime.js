// chat-mermaid-runtime.js
/**
 * Shared Mermaid runtime for the classic chat client.
 *
 * `mermaid.initialize()` sets global configuration and `mermaid.render()` reads it back, so
 * the inline chat renderer and the export rasterizer cannot each configure the library once
 * and assume it stays that way: whichever configured last would silently decide the theme
 * and sizing for the other. Inline diagrams want a theme-aware, width-constrained SVG, while
 * export wants a neutral, fixed-size SVG that survives being painted onto a canvas.
 *
 * Every render therefore goes through this module, which applies the caller's preset
 * immediately before rendering and serialises renders so a configuration always stays paired
 * with the diagram that asked for it.
 *
 * The bundle is 3.4 MB, so it is fetched from its local static path on first use rather than
 * on page load.
 */

const MERMAID_SCRIPT_PATH = '/static/js/mermaid/mermaid-11.17.2.min.js';
const MERMAID_LOAD_TIMEOUT_MS = 20000;
const MERMAID_RENDER_TIMEOUT_MS = 10000;

export const MERMAID_PRESET_INLINE = 'inline';
export const MERMAID_PRESET_EXPORT = 'export';

// The application's own stack, all system fonts, so no webfont is ever fetched.
const INLINE_FONT_FAMILY =
    "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif";
const EXPORT_FONT_FAMILY = 'Arial, Helvetica, sans-serif';

let mermaidLoaderPromise = null;
let renderQueue = Promise.resolve();
let appliedConfigSignature = null;
let renderSequence = 0;

/**
 * Read the theme inline diagrams should follow.
 */
export function getInlineMermaidTheme() {
    return document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'dark' : 'light';
}

/**
 * Build the Mermaid configuration for a preset.
 *
 * `htmlLabels` stays off everywhere: labels drawn with <foreignObject> disappear when an SVG
 * is painted onto a canvas for export, and keeping labels as SVG text also removes an entire
 * class of injection from model-authored diagram labels.
 */
function buildConfig(preset, theme) {
    const baseConfig = {
        // Nothing renders except through an explicit `render` call below.
        startOnLoad: false,
        // Diagram source is model output, so it is untrusted. 'strict' runs Mermaid's bundled
        // DOMPurify over the generated markup and disables the `click` directive, which can
        // otherwise bind handlers or navigate.
        securityLevel: 'strict',
        // Mermaid otherwise writes its own error diagram straight into the page. Failures are
        // handled by the caller instead.
        suppressErrorRendering: true,
        htmlLabels: false,
        logLevel: 'fatal',
    };

    if (preset === MERMAID_PRESET_EXPORT) {
        return {
            ...baseConfig,
            theme: 'neutral',
            fontFamily: EXPORT_FONT_FAMILY,
            flowchart: { htmlLabels: false, useMaxWidth: false },
            sequence: { useMaxWidth: false },
            class: { htmlLabels: false, useMaxWidth: false },
        };
    }

    return {
        ...baseConfig,
        theme: theme === 'dark' ? 'dark' : 'default',
        fontFamily: INLINE_FONT_FAMILY,
        flowchart: { htmlLabels: false, useMaxWidth: true },
        sequence: { useMaxWidth: true },
        class: { htmlLabels: false, useMaxWidth: true },
        gantt: { useMaxWidth: true },
    };
}

/**
 * Apply a preset, skipping the call when the global configuration already matches.
 *
 * The signature is only trustworthy because this module is the sole caller of
 * `mermaid.initialize` in the client.
 */
function applyConfig(mermaid, preset, theme) {
    const signature = `${preset}:${theme}`;
    if (appliedConfigSignature === signature) {
        return;
    }

    mermaid.initialize(buildConfig(preset, theme));
    appliedConfigSignature = signature;
}

/**
 * Load the vendored Mermaid bundle on first use.
 */
export function loadMermaid() {
    if (mermaidLoaderPromise) {
        return mermaidLoaderPromise;
    }

    mermaidLoaderPromise = new Promise((resolve, reject) => {
        if (window.mermaid) {
            resolve(window.mermaid);
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
            resolve(window.mermaid);
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
        appliedConfigSignature = null;
    });
    return mermaidLoaderPromise;
}

/**
 * Render one diagram to SVG markup using the requested preset.
 *
 * The returned SVG is still model-derived markup and must be sanitized by the caller before
 * it is written to the DOM as HTML.
 */
export function renderMermaidSvg(source, options = {}) {
    const normalizedSource = String(source || '').trim();
    if (!normalizedSource) {
        return Promise.reject(new Error('The diagram source is empty.'));
    }

    const preset =
        options.preset === MERMAID_PRESET_EXPORT ? MERMAID_PRESET_EXPORT : MERMAID_PRESET_INLINE;
    const theme =
        preset === MERMAID_PRESET_EXPORT ? 'neutral' : options.theme || getInlineMermaidTheme();
    const idPrefix = String(options.idPrefix || 'simplechat-mermaid');
    const timeoutMs = Number(options.timeoutMs) > 0 ? Number(options.timeoutMs) : MERMAID_RENDER_TIMEOUT_MS;

    const run = renderQueue.then(async () => {
        const mermaid = await loadMermaid();
        applyConfig(mermaid, preset, theme);

        renderSequence += 1;
        const result = await withTimeout(
            mermaid.render(`${idPrefix}-${Date.now()}-${renderSequence}`, normalizedSource),
            timeoutMs,
            'Timed out rendering a diagram.'
        );

        const svgMarkup = typeof result === 'string' ? result : result?.svg;
        if (!svgMarkup) {
            throw new Error('Mermaid returned no SVG for the diagram.');
        }
        // `bindFunctions` from the render result is deliberately never called, so no
        // interaction handler is ever attached to a model-authored diagram.
        return svgMarkup;
    });

    // Keep the chain alive after a rejection so one bad diagram does not wedge the queue.
    renderQueue = run.catch(() => undefined);
    return run;
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
