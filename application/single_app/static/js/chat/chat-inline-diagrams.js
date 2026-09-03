// chat-inline-diagrams.js
/**
 * Inline Mermaid diagram rendering for the classic chat client.
 *
 * The V2 client renders ```mermaid fences through MermaidDiagram.tsx. The classic client
 * previously only rasterized diagrams for export, so a mermaid fence in a chat answer showed
 * up as a plain code block. This module closes that gap using the same
 * extract -> tokenize -> sanitize -> inject -> hydrate pipeline as chat-inline-charts.js, so
 * diagram markup never passes through marked and never survives as raw HTML.
 *
 * A fence that has not finished streaming is replaced with a pending token, otherwise the
 * renderer is handed half of its own source repeatedly and fails to parse each time. This
 * mirrors INLINE_CHART_PENDING_REGEX in chat-inline-charts.js.
 */

import {
    MERMAID_PRESET_INLINE,
    getInlineMermaidTheme,
    renderMermaidSvg,
} from './chat-mermaid-runtime.js';

const INLINE_DIAGRAM_LANGUAGE = 'mermaid';

// Deliberately identical to MERMAID_FENCE_REGEX in chat-visual-rasterizer.js and to the
// server-side scan. If inline rendering and export disagreed about what counts as a
// diagram, a fence could render on screen but ship as a code block, or vice versa.
const INLINE_DIAGRAM_REGEX = /```mermaid[ \t]*\r?\n([\s\S]*?)```/gi;
const INLINE_DIAGRAM_PENDING_REGEX = /```mermaid\b[\s\S]*$/i;

/** Guard against a pathological answer wedging the render queue. */
const INLINE_DIAGRAM_MAX_SOURCE_LENGTH = 20000;

/** Rendered SVG keyed by theme and source, so a streaming thread re-renders nothing. */
const diagramSvgCache = new Map();

let themeObserverStarted = false;

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function replaceAllOccurrences(source, target, replacement) {
    return source.split(target).join(replacement);
}

/**
 * Normalize a fence body so cache keys and export sources agree.
 */
function normalizeDiagramSource(value) {
    const text = String(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const lines = text.split('\n').map(line => line.replace(/\s+$/, ''));
    while (lines.length && !lines[0].trim()) {
        lines.shift();
    }
    while (lines.length && !lines[lines.length - 1].trim()) {
        lines.pop();
    }
    return lines.join('\n');
}

function createInlineDiagramToken(blocks, block) {
    const token = `SIMPLECHAT_INLINE_DIAGRAM_TOKEN_${blocks.length}__`;
    blocks.push({ token, ...block });
    return `\n\n${token}\n\n`;
}

/**
 * The exact set `String.prototype.trim` removes.
 *
 * Spelled out because the fingerprint below has to agree, character for character, with
 * `fingerprintSource` in the V2 client and `fingerprint_source` on the server. A regular
 * `.trim()` would in fact do, but writing the set down is what makes the agreement checkable.
 */
const JS_TRIM_PATTERN = /^[\s\uFEFF\u00A0]+|[\s\uFEFF\u00A0]+$/g;

/**
 * Fingerprint a diagram's source.
 *
 * A port of `fingerprintSource` in application/v2_ui/src/lib/visualPalettes.ts, which is what
 * computes the hashes that get stored. A revision is filed under the fingerprint of the block's
 * original source, so classic can only find the right entry by computing the same value.
 */
function fingerprintSource(value) {
    const normalized = String(value ?? '').replace(/\r\n/g, '\n').replace(JS_TRIM_PATTERN, '');
    let hash = 0x811c9dc5;
    for (let index = 0; index < normalized.length; index += 1) {
        hash ^= normalized.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

/** The source a stored entry currently points at, or null when the original still applies. */
function readCurrentRevisionSource(entry) {
    if (!entry || typeof entry !== 'object' || !Array.isArray(entry.revisions)) {
        return null;
    }
    const current = entry.current;
    if (!Number.isInteger(current) || current <= 0 || current >= entry.revisions.length) {
        return null;
    }
    const source = entry.revisions[current]?.source;
    return typeof source === 'string' && source ? source : null;
}

/**
 * Swap in the current version of any diagram that has been edited in the V2 client.
 *
 * Editing happens only in V2, but a conversation is readable in both, and a reader who moved
 * here would otherwise see the version the model first produced with no sign that it had been
 * changed — and would then export that stale version.
 *
 * Identified by position and confirmed by fingerprint, the same rule the server applies. A
 * block whose fingerprint does not match is left alone rather than replaced with another
 * diagram's source, so every way this can go wrong shows the original.
 */
export function applyStoredDiagramRevisions(blocks, blockRevisions) {
    const entries = blockRevisions && typeof blockRevisions === 'object'
        ? blockRevisions[INLINE_DIAGRAM_LANGUAGE]
        : null;
    if (!entries || typeof entries !== 'object' || !Array.isArray(blocks)) {
        return blocks;
    }

    return blocks.map((block, index) => {
        if (!block || block.pending || typeof block.sourceHash !== 'string') {
            return block;
        }

        let entry = entries[String(index)];
        if (!entry || entry.source_hash !== block.sourceHash) {
            // The position disagrees, which happens when the two clients number the fences
            // differently. Fall back to the fingerprint, and only when it is unambiguous.
            const matches = Object.values(entries).filter(
                candidate => candidate && candidate.source_hash === block.sourceHash,
            );
            entry = matches.length === 1 ? matches[0] : null;
        }

        const source = readCurrentRevisionSource(entry);
        return source ? { ...block, source: normalizeDiagramSource(source) } : block;
    });
}

/**
 * Pull mermaid fences out of the markdown, leaving tokens marked's parser will not touch.
 */
export function extractInlineDiagramBlocks(markdownText = '') {
    const blocks = [];
    let markdown = String(markdownText ?? '').replace(INLINE_DIAGRAM_REGEX, (match, payload) => {
        const source = normalizeDiagramSource(payload);
        if (!source) {
            return match;
        }

        // Hashed from the raw fence body rather than the normalized source. Normalizing strips
        // trailing whitespace from every line, which the reference implementation does not, so
        // a diagram with a trailing space on an interior line would hash differently here and
        // its stored revisions would silently stop resolving.
        return createInlineDiagramToken(blocks, {
            source,
            sourceHash: fingerprintSource(payload),
            originalBlock: match,
        });
    });

    markdown = markdown.replace(INLINE_DIAGRAM_PENDING_REGEX, match => createInlineDiagramToken(blocks, {
        originalBlock: match,
        pending: true,
    }));

    return { markdown, blocks };
}

/**
 * Put the original fences back, so copying a message yields the markdown the model wrote.
 */
export function restoreInlineDiagramTokens(markdownText = '', blocks = []) {
    let restored = String(markdownText ?? '');
    blocks.forEach(block => {
        restored = replaceAllOccurrences(restored, block.token, block.originalBlock || '');
    });
    return restored;
}

function buildDiagramPlaceholderHtml(block, index) {
    const label = `Diagram ${index + 1}`;

    if (block.pending) {
        return `
        <figure class="sc-inline-diagram sc-inline-diagram-pending my-3" data-diagram-hydrated="pending" aria-label="${escapeHtml(label)}">
            <div class="sc-inline-diagram-stage text-muted small">Preparing diagram...</div>
        </figure>
    `;
    }

    return `
        <figure class="sc-inline-diagram my-3" data-diagram-source="${escapeHtml(encodeURIComponent(block.source))}" aria-label="${escapeHtml(label)}">
            <div class="sc-inline-diagram-stage text-muted small">Rendering diagram...</div>
        </figure>
    `;
}

/**
 * Swap diagram tokens for placeholder markup after the surrounding markdown is sanitized.
 */
export function injectInlineDiagramHtml(html = '', blocks = []) {
    let renderedHtml = String(html ?? '');

    blocks.forEach((block, index) => {
        const placeholderHtml = buildDiagramPlaceholderHtml(block, index);
        renderedHtml = replaceAllOccurrences(renderedHtml, `<p>${block.token}</p>`, placeholderHtml);
        renderedHtml = replaceAllOccurrences(renderedHtml, block.token, placeholderHtml);
    });

    return renderedHtml;
}

/**
 * Show the diagram source when it cannot be rendered.
 *
 * The source is still the answer the model gave, so hiding it would lose information.
 */
function renderDiagramSourceFallback(stage, source, reason) {
    stage.innerHTML = `
        <div class="sc-inline-diagram-fallback">
            <div class="small text-muted mb-1">${escapeHtml(reason)}</div>
            <pre class="mb-0"><code>${escapeHtml(source)}</code></pre>
        </div>
    `;
}

function sanitizeSvgMarkup(svgMarkup) {
    if (typeof window.DOMPurify === 'undefined') {
        return '';
    }
    // Sanitizer boundary. Mermaid's 'strict' security level already sanitizes internally;
    // this is the independent second pass required before model-derived markup is written
    // to the DOM as HTML.
    return window.DOMPurify.sanitize(String(svgMarkup || ''));
}

/**
 * Re-render diagrams when the user switches between light and dark mode.
 */
function startThemeObserver() {
    if (themeObserverStarted || typeof MutationObserver === 'undefined') {
        return;
    }

    themeObserverStarted = true;
    new MutationObserver(() => hydrateInlineDiagrams(document)).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-bs-theme'],
    });
}

/**
 * Render every placeholder in `root` that is missing or stale for the current theme.
 */
export function hydrateInlineDiagrams(root = document) {
    if (!root || typeof root.querySelectorAll !== 'function') {
        return;
    }

    startThemeObserver();

    const theme = getInlineMermaidTheme();
    const containers = root.querySelectorAll('.sc-inline-diagram[data-diagram-source]');

    containers.forEach(container => {
        const stage = container.querySelector('.sc-inline-diagram-stage');
        if (!stage) {
            return;
        }

        if (
            container.getAttribute('data-diagram-hydrated') === 'true'
            && container.getAttribute('data-diagram-theme') === theme
        ) {
            return;
        }

        let source = '';
        try {
            source = decodeURIComponent(container.getAttribute('data-diagram-source') || '');
        } catch (err) {
            source = '';
        }

        if (!source) {
            container.setAttribute('data-diagram-hydrated', 'true');
            container.setAttribute('data-diagram-theme', theme);
            renderDiagramSourceFallback(stage, '', 'Diagram could not be rendered');
            return;
        }

        if (source.length > INLINE_DIAGRAM_MAX_SOURCE_LENGTH) {
            container.setAttribute('data-diagram-hydrated', 'true');
            container.setAttribute('data-diagram-theme', theme);
            renderDiagramSourceFallback(stage, source, 'Diagram is too large to render');
            return;
        }

        const cacheKey = `${theme}:${source}`;
        const cachedSvg = diagramSvgCache.get(cacheKey);
        if (cachedSvg !== undefined) {
            stage.innerHTML = cachedSvg;
            container.setAttribute('data-diagram-hydrated', 'true');
            container.setAttribute('data-diagram-theme', theme);
            return;
        }

        container.setAttribute('data-diagram-hydrated', 'pending');
        stage.textContent = 'Rendering diagram...';

        renderMermaidSvg(source, { preset: MERMAID_PRESET_INLINE, theme })
            .then(svgMarkup => {
                const safeSvg = sanitizeSvgMarkup(svgMarkup);
                if (!safeSvg) {
                    throw new Error('The diagram SVG could not be sanitized.');
                }
                diagramSvgCache.set(cacheKey, safeSvg);

                // The message may have been re-rendered or removed while this was queued.
                if (!container.isConnected) {
                    return;
                }
                stage.innerHTML = safeSvg;
                container.setAttribute('data-diagram-hydrated', 'true');
                container.setAttribute('data-diagram-theme', theme);
            })
            .catch(err => {
                console.warn('Unable to render an inline diagram:', err);
                if (!container.isConnected) {
                    return;
                }
                renderDiagramSourceFallback(stage, source, 'Diagram could not be rendered');
                container.setAttribute('data-diagram-hydrated', 'true');
                container.setAttribute('data-diagram-theme', theme);
            });
    });
}

/**
 * Drop rendered diagram markup, used before a message element is replaced or removed.
 */
export function destroyInlineDiagrams(root = document) {
    if (!root) {
        return;
    }

    const containers = root.matches?.('.sc-inline-diagram')
        ? [root]
        : root.querySelectorAll?.('.sc-inline-diagram') || [];

    containers.forEach(container => {
        const stage = container.querySelector('.sc-inline-diagram-stage');
        if (stage) {
            stage.textContent = '';
        }
        container.removeAttribute('data-diagram-hydrated');
        container.removeAttribute('data-diagram-theme');
    });
}

export { INLINE_DIAGRAM_LANGUAGE };
