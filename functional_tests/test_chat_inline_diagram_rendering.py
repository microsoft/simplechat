#!/usr/bin/env python3
"""
Functional test for classic-UI inline Mermaid diagram rendering.
Version: 0.261.028
Implemented in: 0.261.028

The classic chat client used to render a ```mermaid fence as a plain code block, because
Mermaid was only wired into the export rasterizer. This test ensures chat-inline-diagrams.js
lifts mermaid fences out of the markdown before marked sees them, restores the original
fence for copy and export, renders a real diagram into the DOM, falls back to the diagram
source when parsing fails, and never reaches the network for an asset.

Skipped when Playwright or its Chromium build is unavailable.
"""

import functools
import http.server
import os
import socketserver
import sys
import threading
from typing import Any, Callable, Dict, List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
STATIC_DIR = os.path.join(APP_DIR, 'static')
INLINE_DIAGRAMS_PATH = os.path.join(STATIC_DIR, 'js', 'chat', 'chat-inline-diagrams.js')
RASTERIZER_PATH = os.path.join(STATIC_DIR, 'js', 'chat', 'chat-visual-rasterizer.js')
CHAT_MESSAGES_PATH = os.path.join(STATIC_DIR, 'js', 'chat', 'chat-messages.js')
CHAT_STREAMING_PATH = os.path.join(STATIC_DIR, 'js', 'chat', 'chat-streaming.js')

MERMAID_FENCE_PATTERN_LITERAL = r'/```mermaid[ \t]*\r?\n([\s\S]*?)```/gi'

EXTERNAL_ASSET_MARKERS = (
    'cdn.jsdelivr.net',
    'unpkg.com',
    'cdnjs.cloudflare.com',
    'esm.sh',
    'skypack.dev',
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    '@font-face',
)

from test_support.versioning import assert_app_version_at_least  # noqa: E402

PROBE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>inline diagram probe</title></head>
<body>
<div id="host"></div>
<script src="/static/js/chat/purify.min.js"></script>
<script type="module">
import {
    destroyInlineDiagrams,
    extractInlineDiagramBlocks,
    hydrateInlineDiagrams,
    injectInlineDiagramHtml,
    restoreInlineDiagramTokens,
} from '/static/js/chat/chat-inline-diagrams.js';

const DIAGRAM_SOURCE = [
    'flowchart TD',
    '    browser["Browser"] --> app["Simple Chat App Service"]',
    '    app --> foundry["Azure AI Foundry Agent Service"]',
    '    foundry --> bing["Grounding with Bing Search"]',
].join('\\n');

const MARKDOWN = [
    'Here is how the request travels.',
    '',
    '```mermaid',
    DIAGRAM_SOURCE,
    '```',
    '',
    'The user IP never leaves the App Service.',
].join('\\n');

const PENDING_MARKDOWN = [
    'Here is how the request travels.',
    '',
    '```mermaid',
    'flowchart TD',
    '    browser["Browser"] -->',
].join('\\n');

const BROKEN_MARKDOWN = [
    '```mermaid',
    'flowchart TD',
    '    A --> ((((',
    '```',
].join('\\n');

function waitForHydration(container, timeoutMs = 90000) {
    const started = Date.now();
    return new Promise((resolve, reject) => {
        const tick = () => {
            if (container.getAttribute('data-diagram-hydrated') === 'true') {
                resolve();
                return;
            }
            if (Date.now() - started > timeoutMs) {
                reject(new Error('Timed out waiting for diagram hydration.'));
                return;
            }
            setTimeout(tick, 100);
        };
        tick();
    });
}

async function renderInto(host, markdown) {
    const extraction = extractInlineDiagramBlocks(markdown);
    const fakeParsedHtml = extraction.blocks
        .map((block) => `<p>${block.token}</p>`)
        .join('\\n');
    host.innerHTML = injectInlineDiagramHtml(fakeParsedHtml, extraction.blocks);
    hydrateInlineDiagrams(host);
    return extraction;
}

window.__probe = { status: 'running' };
(async () => {
    try {
        const host = document.getElementById('host');

        const extraction = extractInlineDiagramBlocks(MARKDOWN);
        const restored = restoreInlineDiagramTokens(extraction.markdown, extraction.blocks);

        const pendingExtraction = extractInlineDiagramBlocks(PENDING_MARKDOWN);
        const pendingHtml = injectInlineDiagramHtml(
            pendingExtraction.blocks.map((block) => `<p>${block.token}</p>`).join(''),
            pendingExtraction.blocks
        );

        await renderInto(host, MARKDOWN);
        const container = host.querySelector('.sc-inline-diagram');
        await waitForHydration(container);
        const svg = container.querySelector('svg');
        const renderedText = svg ? svg.textContent : '';

        // A second render of the same source must come straight from the cache.
        await renderInto(host, MARKDOWN);
        const cachedContainer = host.querySelector('.sc-inline-diagram');
        const cachedSvgImmediately = Boolean(cachedContainer.querySelector('svg'));

        // Destroying must clear the rendered markup.
        destroyInlineDiagrams(host);
        const svgAfterDestroy = Boolean(host.querySelector('.sc-inline-diagram svg'));

        await renderInto(host, BROKEN_MARKDOWN);
        const brokenContainer = host.querySelector('.sc-inline-diagram');
        await waitForHydration(brokenContainer);
        const fallbackCode = brokenContainer.querySelector('.sc-inline-diagram-fallback code');

        window.__probe = {
            status: 'done',
            blockCount: extraction.blocks.length,
            markdownHasToken: extraction.markdown.includes('SIMPLECHAT_INLINE_DIAGRAM_TOKEN_0__'),
            markdownKeepsProse: extraction.markdown.includes('The user IP never leaves the App Service.'),
            markdownDroppedFence: !extraction.markdown.includes('```mermaid'),
            restoredFence: restored.includes('```mermaid') && restored.includes('flowchart TD'),
            pendingBlockCount: pendingExtraction.blocks.length,
            pendingIsPending: Boolean(pendingExtraction.blocks[0] && pendingExtraction.blocks[0].pending),
            pendingHtmlIsPlaceholder: pendingHtml.includes('sc-inline-diagram-pending'),
            svgRendered: Boolean(svg),
            renderedText,
            cachedSvgImmediately,
            svgAfterDestroy,
            fallbackText: fallbackCode ? fallbackCode.textContent : '',
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
        print(f"Skipping browser diagram assertions: {import_error}")
        return False

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=15000)
            browser.close()
        return True
    except Exception as launch_error:
        print(f"Skipping browser diagram assertions: {launch_error}")
        return False


def _run_inline_diagram_probe() -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    handler = functools.partial(_ProbeHandler, directory=APP_DIR)
    with socketserver.TCPServer(('127.0.0.1', 0), handler) as httpd:
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()

                external_requests: List[str] = []
                page.on(
                    'request',
                    lambda request: external_requests.append(request.url)
                    if not request.url.startswith(f'http://127.0.0.1:{port}')
                    else None,
                )

                page.goto(f'http://127.0.0.1:{port}/', wait_until='domcontentloaded')
                page.wait_for_function(
                    "window.__probe && window.__probe.status !== 'running'",
                    timeout=180000,
                )
                probe = page.evaluate('window.__probe')
                browser.close()
        finally:
            httpd.shutdown()

    probe['externalRequests'] = external_requests
    return probe


def test_app_version_covers_the_fix():
    """The application version must be at least the version this landed in."""
    print('Testing application version...')

    assert_app_version_at_least(
        '0.261.028',
        reason='Classic-UI inline Mermaid rendering landed in 0.261.028.',
    )

    print('PASS: application version')


def test_inline_diagrams_are_wired_into_the_render_pipeline():
    """Extraction, injection, restoration, hydration and teardown must all be wired up."""
    print('Testing inline diagram wiring...')

    with open(CHAT_MESSAGES_PATH, 'r', encoding='utf-8') as handle:
        messages_text = handle.read()

    with open(CHAT_STREAMING_PATH, 'r', encoding='utf-8') as handle:
        streaming_text = handle.read()

    # Extraction must happen before marked parses, and injection after sanitization.
    assert 'extractInlineDiagramBlocks(chartExtraction.markdown)' in messages_text
    assert 'injectInlineDiagramHtml(htmlWithCharts, diagramExtraction.blocks)' in messages_text
    assert 'restoreInlineDiagramTokens(' in messages_text
    assert messages_text.count('hydrateInlineDiagrams(') >= 2
    assert 'destroyInlineDiagrams(' in messages_text

    # Every streaming path that hydrates charts must also hydrate diagrams.
    assert streaming_text.count('hydrateInlineDiagrams(') == streaming_text.count('hydrateInlineCharts(')
    assert 'destroyInlineDiagrams(' in streaming_text

    # Preview text and text-to-speech must not read internal placeholders aloud.
    assert 'previewMarkdown: stripInlineRenderTokens(' in messages_text
    assert 'SIMPLECHAT_INLINE_[A-Z_]*TOKEN_' in messages_text
    assert '@@SC_INLINE_IMAGE_PROPOSAL_' in messages_text

    print('PASS: inline diagram wiring')


def test_inline_diagram_module_references_only_local_assets():
    """The inline renderer must not introduce a third-party browser asset."""
    print('Testing inline diagram asset references...')

    with open(INLINE_DIAGRAMS_PATH, 'r', encoding='utf-8') as handle:
        module_text = handle.read()

    for marker in EXTERNAL_ASSET_MARKERS:
        assert marker not in module_text, marker

    # Model-derived SVG must be sanitized before it reaches the DOM.
    assert 'DOMPurify.sanitize' in module_text
    assert 'innerHTML' in module_text

    print('PASS: inline diagram asset references')


def test_inline_and_export_agree_on_what_a_diagram_is():
    """The chat renderer and the export rasterizer must match the same fences.

    If they diverged, a fence could render on screen but ship to an export as a code block,
    or the reverse, and the server matches export assets back to fences by source text.
    """
    print('Testing fence detection parity...')

    with open(INLINE_DIAGRAMS_PATH, 'r', encoding='utf-8') as handle:
        module_text = handle.read()

    with open(RASTERIZER_PATH, 'r', encoding='utf-8') as handle:
        rasterizer_text = handle.read()

    assert MERMAID_FENCE_PATTERN_LITERAL in module_text, MERMAID_FENCE_PATTERN_LITERAL
    assert MERMAID_FENCE_PATTERN_LITERAL in rasterizer_text, MERMAID_FENCE_PATTERN_LITERAL

    print('PASS: fence detection parity')


def test_browser_renders_and_falls_back_for_inline_diagrams():
    """A mermaid fence renders as SVG, and an unparseable one falls back to its source."""
    print('Testing browser inline diagram rendering...')

    if not _playwright_chromium_available():
        return

    probe = _run_inline_diagram_probe()
    assert probe.get('status') == 'done', probe

    # Extraction keeps the prose and hides the fence from marked.
    assert probe.get('blockCount') == 1, probe
    assert probe.get('markdownHasToken') is True, probe
    assert probe.get('markdownKeepsProse') is True, probe
    assert probe.get('markdownDroppedFence') is True, probe

    # Copy and export still get the original fence back.
    assert probe.get('restoredFence') is True, probe

    # A half-streamed fence becomes a pending placeholder instead of a parse failure.
    assert probe.get('pendingBlockCount') == 1, probe
    assert probe.get('pendingIsPending') is True, probe
    assert probe.get('pendingHtmlIsPlaceholder') is True, probe

    # The diagram actually renders, with its labels intact.
    assert probe.get('svgRendered') is True, probe
    rendered_text = probe.get('renderedText') or ''
    assert 'Browser' in rendered_text, rendered_text[:200]
    assert 'Grounding with Bing Search' in rendered_text, rendered_text[:200]

    # A repeat render is served from the cache without another async round trip.
    assert probe.get('cachedSvgImmediately') is True, probe

    # Teardown clears the rendered markup.
    assert probe.get('svgAfterDestroy') is False, probe

    # An unparseable diagram shows its source rather than disappearing.
    fallback_text = probe.get('fallbackText') or ''
    assert 'flowchart TD' in fallback_text, fallback_text[:200]

    assert not probe.get('externalRequests'), probe.get('externalRequests')

    print('PASS: browser inline diagram rendering')


if __name__ == '__main__':
    tests: List[Callable[[], None]] = [
        test_app_version_covers_the_fix,
        test_inline_diagrams_are_wired_into_the_render_pipeline,
        test_inline_diagram_module_references_only_local_assets,
        test_inline_and_export_agree_on_what_a_diagram_is,
        test_browser_renders_and_falls_back_for_inline_diagrams,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:  # pylint: disable=broad-except
            print(f'Test failed: {exc}')
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
