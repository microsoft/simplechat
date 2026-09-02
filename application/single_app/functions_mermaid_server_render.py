# functions_mermaid_server_render.py
"""Server-side Mermaid rasterization using the Chromium build already in the image.

Mermaid is a browser rendering library, so a faithful diagram needs a real browser
somewhere. The container already installs Playwright's Chromium for Source Review and
Deep Research (``INSTALL_PLAYWRIGHT_CHROMIUM``, on by default), so rendering here costs
no new dependency and no new install step.

This exists so an export that has no browser attached still gets pictures: exports started
from the V2 interface, and anything server-initiated. When Chromium is unavailable, because
a deployment opted out of it, every function here reports that cleanly and the export falls
back to the diagram's original code block.

The same vendored Mermaid bundle the browser uses is loaded from disk, so a server-rendered
diagram and a browser-rendered one come from identical library code.
"""

import importlib.util
import os
import threading
from typing import Any, Dict, List, Optional

from functions_export_visuals import (
    EXPORT_VISUAL_ASSET_MAX_COUNT,
    EXPORT_VISUAL_KIND_DIAGRAM,
    normalize_visual_assets,
    normalize_visual_source,
)


MERMAID_BUNDLE_RELATIVE_PATH = os.path.join(
    'static', 'js', 'mermaid', 'mermaid-11.17.2.min.js',
)
MERMAID_SERVER_RENDER_MAX_DIAGRAMS = EXPORT_VISUAL_ASSET_MAX_COUNT
MERMAID_SERVER_RENDER_BROWSER_TIMEOUT_MS = 20000
MERMAID_SERVER_RENDER_PAGE_TIMEOUT_MS = 60000
MERMAID_SERVER_RENDER_DIAGRAM_TIMEOUT_MS = 10000
MERMAID_SERVER_RENDER_SCALE = 2
MERMAID_SERVER_RENDER_MAX_CANVAS_EDGE = 4000

_RENDER_CAPABILITIES_CACHE: Optional[Dict[str, Any]] = None
_RENDER_LOCK = threading.Lock()

# Mirrors chat-visual-rasterizer.js. htmlLabels must stay off in both: Mermaid draws labels
# inside <foreignObject>, and that content is dropped when an SVG is painted onto a canvas,
# which yields diagrams with shapes and arrows but no text.
MERMAID_RENDER_SCRIPT = """
(async (sources, options) => {
    const results = [];
    window.mermaid.initialize({
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

    function parseSvgLength(value) {
        const candidate = String(value || '').trim();
        if (!candidate || candidate.includes('%')) {
            return 0;
        }
        const parsed = Number.parseFloat(candidate);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
    }

    function normalizeSvgMarkup(svgMarkup) {
        const parsed = new DOMParser().parseFromString(svgMarkup, 'image/svg+xml');
        const svgElement = parsed.documentElement;
        let width = parseSvgLength(svgElement.getAttribute('width'));
        let height = parseSvgLength(svgElement.getAttribute('height'));
        const viewBox = String(svgElement.getAttribute('viewBox') || '')
            .split(/[\\s,]+/)
            .map(Number);
        if (viewBox.length === 4 && Number.isFinite(viewBox[2]) && Number.isFinite(viewBox[3])) {
            width = width || viewBox[2];
            height = height || viewBox[3];
        }
        width = width || 800;
        height = height || 600;

        svgElement.setAttribute('width', String(width));
        svgElement.setAttribute('height', String(height));
        svgElement.setAttribute('style', 'max-width:none;background-color:#ffffff;');
        if (!svgElement.getAttribute('xmlns')) {
            svgElement.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        }

        const scale = Math.min(options.scale, options.maxEdge / Math.max(width, height));
        const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
        return {
            markup: new XMLSerializer().serializeToString(svgElement),
            canvasWidth: Math.max(1, Math.round(width * safeScale)),
            canvasHeight: Math.max(1, Math.round(height * safeScale)),
        };
    }

    function base64EncodeUnicode(text) {
        const bytes = new TextEncoder().encode(text);
        const chunkSize = 0x8000;
        let binary = '';
        for (let index = 0; index < bytes.length; index += chunkSize) {
            binary += String.fromCharCode.apply(null, bytes.subarray(index, index + chunkSize));
        }
        return btoa(binary);
    }

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
            image.src = 'data:image/svg+xml;base64,' + base64EncodeUnicode(normalized.markup);
        });
    }

    function withTimeout(promise, timeoutMs) {
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Diagram render timed out.')), timeoutMs);
            Promise.resolve(promise).then(
                (value) => { clearTimeout(timer); resolve(value); },
                (err) => { clearTimeout(timer); reject(err); },
            );
        });
    }

    for (let index = 0; index < sources.length; index += 1) {
        const source = sources[index];
        try {
            const rendered = await withTimeout(
                window.mermaid.render('simplechat-export-server-' + index, source),
                options.diagramTimeoutMs,
            );
            const svgMarkup = typeof rendered === 'string' ? rendered : (rendered && rendered.svg);
            if (!svgMarkup) {
                results.push({ source, error: 'Mermaid produced no SVG.' });
                continue;
            }
            const dataUri = await withTimeout(svgToPngDataUri(svgMarkup), options.diagramTimeoutMs);
            results.push({ source, dataUri });
        } catch (err) {
            results.push({ source, error: String((err && err.message) || err) });
        }
    }

    return results;
})
"""


def get_mermaid_server_render_capabilities(force_refresh: bool = False) -> Dict[str, Any]:
    """Return cached runtime support details for server-side diagram rendering."""
    global _RENDER_CAPABILITIES_CACHE
    if _RENDER_CAPABILITIES_CACHE is not None and not force_refresh:
        return dict(_RENDER_CAPABILITIES_CACHE)

    capabilities = {
        'server_rendering_available': False,
        'playwright_available': False,
        'chromium_launch_available': False,
        'bundle_available': os.path.exists(get_mermaid_bundle_path()),
        'message': 'Playwright is not installed in this app runtime.',
    }

    if not capabilities['bundle_available']:
        capabilities['message'] = 'The vendored Mermaid bundle is missing from this runtime.'
        _RENDER_CAPABILITIES_CACHE = capabilities
        return dict(capabilities)

    if importlib.util.find_spec('playwright') is None:
        _RENDER_CAPABILITIES_CACHE = capabilities
        return dict(capabilities)

    capabilities['playwright_available'] = True
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright_instance:
            browser = playwright_instance.chromium.launch(
                headless=True,
                args=get_chromium_launch_args(),
                timeout=MERMAID_SERVER_RENDER_BROWSER_TIMEOUT_MS,
            )
            browser.close()
        capabilities.update({
            'server_rendering_available': True,
            'chromium_launch_available': True,
            'message': 'Playwright Chromium launch verified for diagram rendering.',
        })
    except Exception as runtime_error:
        capabilities['message'] = (
            f'Playwright is installed, but Chromium launch failed: {str(runtime_error)[:220]}'
        )

    _RENDER_CAPABILITIES_CACHE = capabilities
    return dict(capabilities)


def is_mermaid_server_rendering_available() -> bool:
    """Return True only when this runtime can rasterize diagrams without a browser client."""
    return bool(get_mermaid_server_render_capabilities().get('server_rendering_available'))


def get_mermaid_bundle_path() -> str:
    """Return the on-disk path of the vendored Mermaid bundle."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), MERMAID_BUNDLE_RELATIVE_PATH)


def get_chromium_launch_args() -> List[str]:
    """Match the Chromium flags Source Review already uses in this runtime."""
    launch_args = ['--disable-dev-shm-usage', '--disable-gpu']
    if _is_chromium_no_sandbox_enabled():
        launch_args.append('--no-sandbox')
    return launch_args


def render_mermaid_visual_assets(
    sources: List[Dict[str, str]],
    max_diagrams: int = MERMAID_SERVER_RENDER_MAX_DIAGRAMS,
) -> List[Dict[str, Any]]:
    """Rasterize diagram sources to validated export assets, skipping any that fail.

    Every diagram is rendered in one browser session. Returns an empty list when the
    runtime cannot launch Chromium, which leaves the fences untouched.
    """
    normalized_sources = _normalize_render_sources(sources, max_diagrams)
    if not normalized_sources or not is_mermaid_server_rendering_available():
        return []

    try:
        rendered_results = _render_with_chromium([item['source'] for item in normalized_sources])
    except Exception:
        return []

    metadata_by_source = {item['source']: item for item in normalized_sources}
    raw_assets = []
    for result in rendered_results:
        if not isinstance(result, dict):
            continue
        source = normalize_visual_source(result.get('source'))
        data_uri = result.get('dataUri')
        if not source or not data_uri:
            continue
        metadata = metadata_by_source.get(source, {})
        raw_assets.append({
            'kind': EXPORT_VISUAL_KIND_DIAGRAM,
            'source': source,
            'data_uri': data_uri,
            'alt': metadata.get('alt', ''),
            'caption': metadata.get('caption', ''),
        })

    return normalize_visual_assets(raw_assets, max_count=max_diagrams)


def _normalize_render_sources(
    sources: Any,
    max_diagrams: int,
) -> List[Dict[str, str]]:
    if not isinstance(sources, list):
        return []

    normalized_sources: List[Dict[str, str]] = []
    seen_sources = set()
    for source in sources:
        if len(normalized_sources) >= max_diagrams:
            break
        if isinstance(source, str):
            source = {'source': source}
        if not isinstance(source, dict):
            continue

        normalized_source = normalize_visual_source(source.get('source'))
        if not normalized_source or normalized_source in seen_sources:
            continue
        seen_sources.add(normalized_source)
        normalized_sources.append({
            'source': normalized_source,
            'alt': str(source.get('alt') or ''),
            'caption': str(source.get('caption') or ''),
        })
    return normalized_sources


def _render_with_chromium(sources: List[str]) -> List[Dict[str, Any]]:
    """Render every diagram in a single headless Chromium session."""
    from playwright.sync_api import sync_playwright

    render_options = {
        'scale': MERMAID_SERVER_RENDER_SCALE,
        'maxEdge': MERMAID_SERVER_RENDER_MAX_CANVAS_EDGE,
        'diagramTimeoutMs': MERMAID_SERVER_RENDER_DIAGRAM_TIMEOUT_MS,
    }

    with _RENDER_LOCK:
        with sync_playwright() as playwright_instance:
            browser = playwright_instance.chromium.launch(
                headless=True,
                args=get_chromium_launch_args(),
                timeout=MERMAID_SERVER_RENDER_BROWSER_TIMEOUT_MS,
            )
            try:
                page = browser.new_page()
                page.set_default_timeout(MERMAID_SERVER_RENDER_PAGE_TIMEOUT_MS)

                # The page never needs the network: the bundle is inlined from disk and the
                # diagram sources are passed in as data.
                page.route('**/*', lambda route: route.abort())
                page.set_content('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                                 '</head><body></body></html>')
                page.add_script_tag(path=get_mermaid_bundle_path())

                results = page.evaluate(
                    f'([sources, options]) => ({MERMAID_RENDER_SCRIPT})(sources, options)',
                    [sources, render_options],
                )
            finally:
                browser.close()

    return results if isinstance(results, list) else []


def _is_chromium_no_sandbox_enabled() -> bool:
    return str(os.getenv('SOURCE_REVIEW_CHROMIUM_NO_SANDBOX', 'false')).strip().lower() in (
        '1', 'true', 'yes', 'on',
    )
