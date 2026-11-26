// chat-math.js
import { MAX_MATH_LENGTH } from './chat-math-segments.js';

const VENDOR_ROOT = '/static/vendor/katex-0.18.4/';
const MAX_CACHE_ENTRIES = 200;
const renderCache = new Map();
const pendingAssets = new Map();
let runtimeLoad = null;

function loadAsset(path, stylesheet) {
    if (pendingAssets.has(path)) return pendingAssets.get(path);
    const promise = new Promise((resolve, reject) => {
        const element = document.createElement(stylesheet ? 'link' : 'script');
        if (stylesheet) {
            element.rel = 'stylesheet';
            element.href = path;
        } else {
            element.src = path;
            element.async = true;
        }
        const timer = setTimeout(() => finish(new Error('Math asset load timed out')), 15000);
        function finish(error) {
            clearTimeout(timer);
            if (error) {
                pendingAssets.delete(path);
                element.remove();
                reject(error);
            } else {
                resolve();
            }
        }
        element.addEventListener('load', () => finish(), { once: true });
        element.addEventListener('error', () => finish(new Error('Math asset failed to load')), { once: true });
        document.head.appendChild(element);
    });
    pendingAssets.set(path, promise);
    return promise;
}

function loadMathRuntime() {
    if (!runtimeLoad) {
        runtimeLoad = Promise.all([
            loadAsset(`${VENDOR_ROOT}katex.min.js`, false),
            loadAsset(`${VENDOR_ROOT}katex.min.css`, true),
        ]).then(() => {
            if (!window.katex || !window.DOMPurify) throw new Error('Math rendering dependencies unavailable');
            return window.katex;
        }).catch(error => {
            runtimeLoad = null;
            console.warn('Math renderer unavailable; showing source text.', error.name);
            throw error;
        });
    }
    return runtimeLoad;
}

export function injectMathPlaceholders(html, parsed) {
    if (!parsed.segments.length) return html;
    const template = document.createElement('template');
    template.innerHTML = DOMPurify.sanitize(html);
    const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
        const parts = node.textContent.split(parsed.pattern);
        if (parts.length === 1) continue;
        const fragment = document.createDocumentFragment();
        parts.forEach((part, index) => {
            const segment = index % 2 ? parsed.segments[Number(part)] : null;
            if (!segment) {
                fragment.appendChild(document.createTextNode(part));
            } else if (node.parentElement?.closest('pre, code, a, textarea, script, style')) {
                fragment.appendChild(document.createTextNode(segment.source));
            } else {
                const span = document.createElement('span');
                span.className = segment.display ? 'sc-math sc-math-display' : 'sc-math';
                span.dataset.mathTex = segment.tex;
                span.dataset.mathSource = segment.source;
                span.dataset.mathDisplay = String(segment.display);
                // Keep the pre-backport display text for existing persisted mask offsets.
                const legacy = document.createElement('template');
                legacy.innerHTML = DOMPurify.sanitize(marked.parseInline(segment.source));
                span.dataset.mathText = legacy.content.textContent;
                span.textContent = span.dataset.mathText;
                fragment.appendChild(span);
            }
        });
        node.replaceWith(fragment);
    }
    return template.innerHTML;
}

function renderExpression(element, katex) {
    const tex = element.dataset.mathTex || '';
    const display = element.dataset.mathDisplay === 'true';
    if (!tex || tex.length > MAX_MATH_LENGTH) throw new Error('Invalid math expression length');
    const key = `${display}:${tex}`;
    let rendered = renderCache.get(key);
    if (!rendered) {
        const markup = katex.renderToString(tex, {
            displayMode: display,
            trust: false,
            strict: 'ignore',
            throwOnError: false,
            errorColor: 'currentColor',
            maxExpand: 1000,
            maxSize: 20,
            output: 'htmlAndMathml',
        });
        const fragment = DOMPurify.sanitize(markup, { RETURN_DOM_FRAGMENT: true });
        rendered = { fragment, invalid: Boolean(fragment.querySelector('.katex-error')) };
        if (renderCache.size >= MAX_CACHE_ENTRIES) renderCache.delete(renderCache.keys().next().value);
        renderCache.set(key, rendered);
    }
    if (rendered.invalid) throw new Error('Unsupported math expression');
    element.replaceChildren(rendered.fragment.cloneNode(true));
    element.dataset.mathState = 'ready';
    element.removeAttribute('title');
}

function showMathError(element) {
    element.dataset.mathState = 'error';
    element.title = 'Math could not be rendered. Showing source text.';
    const notice = document.createElement('span');
    notice.className = 'sc-math-error text-warning small';
    notice.textContent = ' [Math unavailable]';
    element.replaceChildren(document.createTextNode(element.dataset.mathText || ''), notice);
}

export async function hydrateMath(root) {
    const elements = Array.from(root.querySelectorAll('.sc-math'))
        .filter(element => !element.dataset.mathState
            && !element.closest('.masked-content')
            && !element.querySelector('.masked-content'));
    if (!elements.length) return;
    elements.forEach(element => { element.dataset.mathState = 'pending'; });
    let katex;
    try {
        katex = await loadMathRuntime();
    } catch {
        elements.filter(element => element.isConnected).forEach(showMathError);
        return;
    }
    for (const element of elements) {
        if (!element.isConnected) continue;
        try {
            renderExpression(element, katex);
        } catch (error) {
            console.warn('Math expression could not be rendered; showing source text.', error.name);
            showMathError(element);
        }
    }
}

function canonicalText(fragment, source = false) {
    fragment.querySelectorAll('.sc-math').forEach(element => {
        element.replaceWith(document.createTextNode(
            (source ? element.dataset.mathSource : element.dataset.mathText) || ''
        ));
    });
    return fragment.textContent;
}

export function getMathAwareSelection(messageText, selectionRange) {
    const range = selectionRange.cloneRange();
    const mathAncestor = node => (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)?.closest('.sc-math');
    const firstMath = mathAncestor(range.startContainer);
    const lastMath = mathAncestor(range.endContainer);
    // A visual glyph has no stable TeX offset. Mask the entire expression when selected.
    if (firstMath) range.setStartBefore(firstMath);
    if (lastMath) range.setEndAfter(lastMath);
    const before = range.cloneRange();
    before.selectNodeContents(messageText);
    before.setEnd(range.startContainer, range.startOffset);
    const start = canonicalText(before.cloneContents()).length;
    const text = canonicalText(range.cloneContents());
    return {
        start,
        end: start + text.length,
        text,
        sourceText: canonicalText(range.cloneContents(), true),
    };
}
