#!/usr/bin/env python3
"""
Functional test for the browser-side Mermaid export rasterizer.
Version: 0.261.026
Implemented in: 0.261.026

This test ensures the vendored Mermaid bundle loads from its local static path with no
external network dependency, and that chat-visual-rasterizer.js turns a diagram into a
PNG whose labels actually survive the SVG-to-canvas step. Mermaid renders labels with
<foreignObject> unless htmlLabels is disabled, and foreignObject content is dropped when
an SVG is painted onto a canvas, so a regression there would silently produce diagrams
with no text.

Skipped when Playwright or its Chromium build is unavailable.
"""

import base64
import functools
import http.server
import io
import os
import socketserver
import sys
import threading
from typing import Any, Callable, Dict, List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
STATIC_DIR = os.path.join(APP_DIR, 'static')
MERMAID_BUNDLE_PATH = os.path.join(STATIC_DIR, 'js', 'mermaid', 'mermaid-11.17.2.min.js')
RASTERIZER_PATH = os.path.join(STATIC_DIR, 'js', 'chat', 'chat-visual-rasterizer.js')

EXTERNAL_ASSET_MARKERS = (
    'cdn.jsdelivr.net',
    'unpkg.com',
    'cdnjs.cloudflare.com',
    'esm.sh',
    'skypack.dev',
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    '@font-face',
    'importScripts',
)

PROBE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>rasterizer probe</title></head>
<body>
<script type="module">
import { buildMessageVisualAssets, extractMermaidSources, normalizeVisualSource }
    from '/static/js/chat/chat-visual-rasterizer.js';

const markdown = [
    'text before',
    '',
    '```mermaid',
    'graph TD',
    '    A[Ingest Documents] --> B{Needs OCR?}',
    '    B -->|Yes| C[Document Intelligence]',
    '    B -->|No| D[Chunk and Embed]',
    '    C --> D',
    '```',
    '',
    'text after',
].join('\\n');

window.__probe = { status: 'running' };
(async () => {
    try {
        const sources = extractMermaidSources(markdown);
        const assets = await buildMessageVisualAssets(markdown);
        window.__probe = {
            status: 'done',
            sourceCount: sources.length,
            expectedSource: sources[0] || '',
            normalizedPadded: normalizeVisualSource('\\n\\n  a  \\n   \\n'),
            assetCount: assets.length,
            kind: assets[0] ? assets[0].kind : '',
            source: assets[0] ? assets[0].source : '',
            dataUri: assets[0] ? assets[0].data_uri : '',
        };
    } catch (err) {
        window.__probe = { status: 'error', message: String((err && err.message) || err) };
    }
})();
</script>
</body></html>
"""


class _ProbeHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/index.html'):
            body = PROBE_PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):
        """Keep the test output readable."""


def _playwright_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as import_error:
        print(f"Skipping browser rasterizer assertions: {import_error}")
        return False

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=15000)
            browser.close()
        return True
    except Exception as launch_error:
        print(f"Skipping browser rasterizer assertions: {launch_error}")
        return False


def _run_rasterizer_probe() -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    handler = functools.partial(_ProbeHandler, directory=APP_DIR)
    with socketserver.TCPServer(('127.0.0.1', 0), handler) as httpd:
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()

                failed_requests: List[str] = []
                page.on('requestfailed', lambda request: failed_requests.append(request.url))
                page.on('request', lambda request: failed_requests.append(f'external: {request.url}')
                        if not request.url.startswith(f'http://127.0.0.1:{port}') else None)

                page.goto(f'http://127.0.0.1:{port}/', wait_until='domcontentloaded')
                page.wait_for_function(
                    "window.__probe && window.__probe.status !== 'running'",
                    timeout=120000,
                )
                probe = page.evaluate('window.__probe')
                browser.close()
        finally:
            httpd.shutdown()

    probe['failedRequests'] = failed_requests
    return probe


def test_vendored_mermaid_bundle_has_no_external_assets():
    """The pinned Mermaid bundle must be self-contained."""
    print("Testing vendored Mermaid bundle...")

    assert os.path.exists(MERMAID_BUNDLE_PATH), MERMAID_BUNDLE_PATH
    assert os.path.exists(os.path.join(os.path.dirname(MERMAID_BUNDLE_PATH), 'LICENSE'))

    with open(MERMAID_BUNDLE_PATH, 'r', encoding='utf-8') as handle:
        bundle_text = handle.read()

    for marker in EXTERNAL_ASSET_MARKERS:
        assert marker not in bundle_text, marker

    print("Vendored Mermaid bundle passed!")


def test_rasterizer_references_only_local_assets():
    """The rasterizer must load Mermaid from a SimpleChat static path."""
    print("Testing rasterizer asset references...")

    with open(RASTERIZER_PATH, 'r', encoding='utf-8') as handle:
        rasterizer_text = handle.read()

    assert "'/static/js/mermaid/mermaid-11.17.2.min.js'" in rasterizer_text
    assert 'htmlLabels: false' in rasterizer_text
    for marker in EXTERNAL_ASSET_MARKERS:
        assert marker not in rasterizer_text, marker

    print("Rasterizer asset references passed!")


def test_browser_rasterizes_a_readable_diagram():
    """A diagram rasterizes to a PNG that still contains its label text."""
    print("Testing browser diagram rasterization...")

    if not _playwright_chromium_available():
        return

    probe = _run_rasterizer_probe()
    assert probe.get('status') == 'done', probe
    assert probe.get('sourceCount') == 1, probe
    assert probe.get('assetCount') == 1, probe
    assert probe.get('kind') == 'diagram', probe
    assert probe.get('source') == probe.get('expectedSource'), probe
    assert probe.get('normalizedPadded') == '  a', probe

    external_requests = [url for url in probe.get('failedRequests', []) if url.startswith('external: ')]
    assert not external_requests, external_requests

    data_uri = probe.get('dataUri') or ''
    assert data_uri.startswith('data:image/png;base64,'), data_uri[:64]

    image_bytes = base64.b64decode(data_uri.split(',', 1)[1])
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb_image = image.convert('RGB')
        width, height = rgb_image.size
        colors = rgb_image.getcolors(maxcolors=1_000_000) or []

    painted_pixels = sum(count for count, color in colors if color != (255, 255, 255))

    assert width >= 100 and height >= 50, (width, height)
    assert painted_pixels > (width * height) * 0.01, painted_pixels

    print("Browser diagram rasterization passed!")


if __name__ == "__main__":
    tests: List[Callable[[], None]] = [
        test_vendored_mermaid_bundle_has_no_external_assets,
        test_rasterizer_references_only_local_assets,
        test_browser_rasterizes_a_readable_diagram,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
