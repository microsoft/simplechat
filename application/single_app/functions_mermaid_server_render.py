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

Two details are what make the picture actually contain its labels:

- **The font is embedded, not borrowed from the operating system.** The container image
  carries no scalable Latin typeface, so a diagram asking for ``Arial, Helvetica, sans-serif``
  resolves to nothing: Chromium then measures every label as zero-width, Mermaid falls back
  to its minimum node size, and the export comes out as uniform empty boxes. DejaVu Sans is
  read from matplotlib, which is already a dependency for TeX export, and injected as an
  ``@font-face`` so rendering does not depend on what the host happens to have installed.

- **The diagram is screenshotted where it is drawn.** Serializing the SVG and repainting it
  through an ``<img>`` onto a canvas silently drops anything the isolated image context will
  not honour, including ``<foreignObject>`` labels, stylesheet rules Mermaid added with
  ``insertRule`` rather than into the SVG, and any font that is not already loaded. Capturing
  the live element with Playwright renders exactly what a browser would show.
"""

import base64
import importlib.util
import math
import os
import re
import threading
from typing import Any, Dict, List, Optional

from functions_export_visuals import (
    EXPORT_VISUAL_ASSET_MAX_COUNT,
    EXPORT_VISUAL_KIND_DIAGRAM,
    build_export_visual_png_data_uri,
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

# Named rather than borrowed from the host, so the family Mermaid asks for is always the
# family that was embedded. Quoted wherever it is used, because it contains spaces.
MERMAID_SERVER_RENDER_FONT_FAMILY = 'SimpleChat Export Sans'
MERMAID_SERVER_RENDER_FONT_STACK = f"'{MERMAID_SERVER_RENDER_FONT_FAMILY}', Arial, Helvetica, sans-serif"

# The element the rendered diagram is mounted into and screenshotted from.
MERMAID_SERVER_RENDER_HOST_ID = 'simplechat-export-host'

# Only real network traffic is blocked. Matching everything would also catch the data: URI
# the embedded font is delivered through, which would put us back to no font at all.
MERMAID_SERVER_RENDER_BLOCKED_URL_PATTERN = re.compile(r'^(?:https?|ws|wss|ftp)://', re.IGNORECASE)

_RENDER_CAPABILITIES_CACHE: Optional[Dict[str, Any]] = None
_EMBEDDED_FONT_CACHE: Optional[str] = None
_EMBEDDED_FONT_RESOLVED = False
_RENDER_LOCK = threading.Lock()

# Mirrors chat-visual-rasterizer.js. htmlLabels stays off in both: keeping labels as SVG
# text removes an entire class of injection from model-authored diagram labels, and it is
# also what lets a diagram survive being turned into a picture at all.
#
# This renders and mounts; it deliberately does not rasterize. Python screenshots the
# mounted element, because a live page render is the only one guaranteed to match what a
# reader would see.
MERMAID_RENDER_SCRIPT = """
(async (source, options) => {
    window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        suppressErrorRendering: true,
        theme: 'neutral',
        htmlLabels: false,
        fontFamily: options.fontFamily,
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

    function withTimeout(promise, timeoutMs) {
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Diagram render timed out.')), timeoutMs);
            Promise.resolve(promise).then(
                (value) => { clearTimeout(timer); resolve(value); },
                (err) => { clearTimeout(timer); reject(err); },
            );
        });
    }

    const host = document.getElementById(options.hostId);
    host.replaceChildren();

    const rendered = await withTimeout(
        window.mermaid.render(options.renderId, source),
        options.diagramTimeoutMs,
    );
    const svgMarkup = typeof rendered === 'string' ? rendered : (rendered && rendered.svg);
    if (!svgMarkup) {
        throw new Error('Mermaid produced no SVG.');
    }

    // Parsed and imported rather than assigned through innerHTML, so model-derived markup
    // is never handed to the HTML parser as script-capable content.
    const parsed = new DOMParser().parseFromString(svgMarkup, 'image/svg+xml');
    if (parsed.getElementsByTagName('parsererror').length > 0) {
        throw new Error('Mermaid produced malformed SVG.');
    }
    const svgElement = document.importNode(parsed.documentElement, true);

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

    // The SVG is vector, so drawing it larger is what produces a high-resolution capture.
    const scale = Math.min(options.scale, options.maxEdge / Math.max(width, height));
    const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
    const paintedWidth = Math.max(1, Math.round(width * safeScale));
    const paintedHeight = Math.max(1, Math.round(height * safeScale));

    svgElement.setAttribute('width', String(paintedWidth));
    svgElement.setAttribute('height', String(paintedHeight));
    svgElement.setAttribute('style', 'max-width:none;display:block;background-color:#ffffff;');

    host.appendChild(svgElement);

    // Labels are measured against the embedded font, so a capture taken before it is in use
    // would record fallback metrics.
    if (document.fonts && document.fonts.ready) {
        await withTimeout(document.fonts.ready, options.diagramTimeoutMs);
    }

    return { width: paintedWidth, height: paintedHeight };
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
        'embedded_font_available': get_embedded_render_font_data_uri() is not None,
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


def get_embedded_render_font_path() -> Optional[str]:
    """Return a scalable font file this runtime can embed into the render page.

    matplotlib ships DejaVu Sans and is already required for TeX export, so the font
    travels with the application rather than depending on a distribution package that a
    given base image may not carry.
    """
    try:
        import matplotlib

        candidate = os.path.join(matplotlib.get_data_path(), 'fonts', 'ttf', 'DejaVuSans.ttf')
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass

    return None


def get_embedded_render_font_data_uri() -> Optional[str]:
    """Return the render font as a data URI, reading it from disk at most once."""
    global _EMBEDDED_FONT_CACHE, _EMBEDDED_FONT_RESOLVED
    if _EMBEDDED_FONT_RESOLVED:
        return _EMBEDDED_FONT_CACHE

    font_path = get_embedded_render_font_path()
    if font_path:
        try:
            with open(font_path, 'rb') as font_handle:
                encoded_font = base64.b64encode(font_handle.read()).decode('ascii')
            _EMBEDDED_FONT_CACHE = f'data:font/ttf;base64,{encoded_font}'
        except Exception:
            _EMBEDDED_FONT_CACHE = None

    _EMBEDDED_FONT_RESOLVED = True
    return _EMBEDDED_FONT_CACHE


def build_render_page_style() -> str:
    """Build the page stylesheet that supplies the render font and an opaque background."""
    font_data_uri = get_embedded_render_font_data_uri()
    font_face = ''
    if font_data_uri:
        font_face = (
            '@font-face{'
            f"font-family:'{MERMAID_SERVER_RENDER_FONT_FAMILY}';"
            f"src:url({font_data_uri}) format('truetype');"
            'font-weight:normal;font-style:normal;font-display:block;'
            '}'
        )

    return (
        f'{font_face}'
        'html,body{margin:0;padding:0;background:#ffffff;}'
        f'#{MERMAID_SERVER_RENDER_HOST_ID}{{display:inline-block;background:#ffffff;}}'
    )


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
    """Render every diagram in a single headless Chromium session.

    Each diagram is mounted into the page and captured with an element screenshot, so the
    picture is a real browser render rather than a reconstruction of one. Diagrams are
    captured one at a time because each needs its own viewport size.
    """
    from playwright.sync_api import sync_playwright

    render_options = {
        'scale': MERMAID_SERVER_RENDER_SCALE,
        'maxEdge': MERMAID_SERVER_RENDER_MAX_CANVAS_EDGE,
        'diagramTimeoutMs': MERMAID_SERVER_RENDER_DIAGRAM_TIMEOUT_MS,
        'fontFamily': MERMAID_SERVER_RENDER_FONT_STACK,
        'hostId': MERMAID_SERVER_RENDER_HOST_ID,
    }

    results: List[Dict[str, Any]] = []

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

                # The page never needs the network: the bundle and the font are both
                # inlined from disk and the diagram sources are passed in as data. Only
                # real network schemes are blocked, so the font's data: URI still resolves.
                page.route(MERMAID_SERVER_RENDER_BLOCKED_URL_PATTERN, lambda route: route.abort())
                page.set_content(
                    '<!doctype html><html lang="en"><head><meta charset="utf-8"></head>'
                    f'<body><div id="{MERMAID_SERVER_RENDER_HOST_ID}"></div></body></html>'
                )
                page.add_style_tag(content=build_render_page_style())
                page.add_script_tag(path=get_mermaid_bundle_path())

                host = page.locator(f'#{MERMAID_SERVER_RENDER_HOST_ID}')
                for index, source in enumerate(sources):
                    render_options['renderId'] = f'simplechat-export-server-{index}'
                    try:
                        results.append({
                            'source': source,
                            'dataUri': _capture_one_diagram(page, host, source, render_options),
                        })
                    except Exception as render_error:
                        results.append({'source': source, 'error': str(render_error)[:220]})
            finally:
                browser.close()

    return results


def _capture_one_diagram(page: Any, host: Any, source: str, render_options: Dict[str, Any]) -> str:
    """Mount one diagram in the page and return its screenshot as a PNG data URI."""
    layout = page.evaluate(
        f'([source, options]) => ({MERMAID_RENDER_SCRIPT})(source, options)',
        [source, render_options],
    )
    if not isinstance(layout, dict):
        raise RuntimeError('The diagram renderer returned no layout.')

    # An element taller or wider than the viewport is captured by scrolling, which can seam
    # a long diagram. Sizing the viewport to the diagram keeps every capture a single paint.
    page.set_viewport_size({
        'width': _clamp_viewport_edge(layout.get('width')),
        'height': _clamp_viewport_edge(layout.get('height')),
    })

    image_bytes = host.screenshot(type='png', animations='disabled')
    if not image_bytes:
        raise RuntimeError('The diagram screenshot was empty.')

    return build_export_visual_png_data_uri(image_bytes)


def _clamp_viewport_edge(value: Any) -> int:
    """Keep a viewport edge inside what Chromium will allocate."""
    try:
        edge = int(math.ceil(float(value)))
    except (TypeError, ValueError):
        edge = 0
    return max(1, min(edge, MERMAID_SERVER_RENDER_MAX_CANVAS_EDGE))


def _is_chromium_no_sandbox_enabled() -> bool:
    return str(os.getenv('SOURCE_REVIEW_CHROMIUM_NO_SANDBOX', 'false')).strip().lower() in (
        '1', 'true', 'yes', 'on',
    )
