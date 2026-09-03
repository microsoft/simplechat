#!/usr/bin/env python3
"""
Functional test for message export progress feedback and client-supplied diagrams.
Version: 0.261.035
Implemented in: 0.261.035

Two things are covered here, both from the same report: a message export that contains a
Mermaid diagram produced empty boxes, and it ran for a long time with nothing on screen to
say it was working, so it looked like it had hung and then failed.

This test ensures that:

  * both interfaces raise a progress notification before an export request and clear it
    afterwards, and disable the control while it runs so a second click cannot start a
    duplicate export;
  * the V2 interface sends the diagram it has already drawn, so the server does not have to
    start a browser to redraw it;
  * the browser's fence normalization agrees exactly with the server's
    ``normalize_visual_source()``, which is what the server matches assets to fences by. A
    disagreement here does not fail loudly: every asset is silently ignored and every
    diagram is quietly re-rendered server-side.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Callable, List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
V2_SRC = os.path.join(ROOT_DIR, 'application', 'v2_ui', 'src')
sys.path.insert(0, APP_DIR)

from functions_export_visuals import normalize_visual_source  # noqa: E402

TOAST_STORE_PATH = os.path.join(V2_SRC, 'stores', 'toastStore.ts')
TOASTER_PATH = os.path.join(V2_SRC, 'components', 'ui', 'Toaster.tsx')
MESSAGE_ACTIONS_PATH = os.path.join(V2_SRC, 'components', 'chat', 'MessageActions.tsx')
MERMAID_DIAGRAM_PATH = os.path.join(V2_SRC, 'components', 'chat', 'MermaidDiagram.tsx')
EXPORT_VISUALS_PATH = os.path.join(V2_SRC, 'lib', 'exportVisuals.ts')
ENDPOINTS_PATH = os.path.join(V2_SRC, 'lib', 'endpoints.ts')

GLOBAL_TOAST_PATH = os.path.join(APP_DIR, 'static', 'js', 'toast.js')
CHAT_TOAST_PATH = os.path.join(APP_DIR, 'static', 'js', 'chat', 'chat-toast.js')
CHAT_EXPORT_PATH = os.path.join(APP_DIR, 'static', 'js', 'chat', 'chat-message-export.js')
CHAT_MESSAGES_PATH = os.path.join(APP_DIR, 'static', 'js', 'chat', 'chat-messages.js')
EXPORT_ROUTE_PATH = os.path.join(APP_DIR, 'route_backend_conversation_export.py')

# Fence bodies chosen for the ways normalization can disagree: line endings, per-line
# trailing whitespace, blank lines at either end, and interior blank lines that must survive.
NORMALIZATION_CASES = [
    'graph TD\n    A[One] --> B[Two]',
    '\n\ngraph TD\r\n    A --> B\r\n\n  \n',
    'graph TD   \n    A --> B\t\n',
    'graph TD\n\n    A --> B\n\n    B --> C',
    '   \n\t\n',
    'sequenceDiagram\r    Alice->>Bob: Hi\r',
]


def read_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


def assert_contains(haystack: str, needle: str, label: str) -> None:
    assert needle in haystack, f'{label}: expected to find {needle!r}'


def test_v2_toast_store_supports_pending_work():
    """A pending toast must stay put until the caller settles it."""
    print("Testing V2 pending toast store...")

    source = read_text(TOAST_STORE_PATH)

    assert_contains(source, "'pending'", 'pending tone')
    assert_contains(source, 'settle:', 'settle action')
    assert_contains(source, "if (tone !== 'pending')", 'pending must skip the auto-dismiss timer')

    # A pending toast with no TTL entry would auto-dismiss on `undefined` milliseconds,
    # which fires immediately and puts us back to no feedback at all.
    ttl_block = re.search(r'TOAST_TTL[^=]*=\s*\{(.*?)\}', source, re.DOTALL)
    assert ttl_block, 'the toast TTL table could not be found'
    assert 'pending' not in ttl_block.group(1), 'pending must not have an auto-dismiss delay'

    assert_contains(source, 'pending: (message: string)', 'toast.pending helper')
    assert_contains(source, 'settle: (id: number', 'toast.settle helper')

    # Settling a failure whose pending toast has gone must not swallow it. A silent failure
    # is indistinguishable from a dead button, which is the complaint this store exists for.
    assert_contains(source, "if (tone === 'error')", 'a lost pending toast must still report errors')

    print("V2 pending toast store passed!")


def test_v2_toaster_renders_pending_state():
    """The pending toast needs a spinner, and must not offer a close button."""
    print("Testing V2 toaster pending rendering...")

    source = read_text(TOASTER_PATH)

    assert_contains(source, 'pending: Loader2', 'spinner icon for the pending tone')
    assert_contains(source, "animate-spin", 'the spinner has to actually spin')
    assert_contains(source, '{!pending && (', 'a running export must not offer a dismiss button')

    print("V2 toaster pending rendering passed!")


def test_v2_export_reports_progress_and_disables_itself():
    """The V2 export must announce itself, settle in place, and refuse a second click."""
    print("Testing V2 export progress feedback...")

    source = read_text(MESSAGE_ACTIONS_PATH)

    assert_contains(source, 'EXPORT_PENDING_MESSAGE', 'per-format progress wording')
    assert_contains(source, 'toast.pending(EXPORT_PENDING_MESSAGE[format])', 'pending toast')

    # Raised before the work starts, not after it: a toast that goes up once the export
    # returns tells the user nothing while they are waiting.
    pending_index = source.index('toast.pending(EXPORT_PENDING_MESSAGE[format])')
    for awaited in ('await downloadMessageExport', 'await fetchMessageEmailDraft'):
        assert source.index(awaited) > pending_index, f'{awaited} runs before the pending toast'

    assert source.count('toast.settle(') >= 3, 'every outcome must settle the pending toast'
    assert_contains(source, "'error',", 'a failed export must settle as an error')

    assert_contains(source, 'busyExport', 'busy state for the running export')
    assert_contains(source, 'disabled={busyExport !== null}', 'a running export disables the menu')
    assert_contains(source, 'setBusyExport(null)', 'the busy state has to be cleared')
    assert_contains(source, '.finally(', 'the busy state must clear on failure too')

    print("V2 export progress feedback passed!")


def test_v2_sends_the_diagram_it_already_drew():
    """The V2 export should not make the server redraw what is already on screen."""
    print("Testing V2 client-supplied diagrams...")

    actions = read_text(MESSAGE_ACTIONS_PATH)
    endpoints = read_text(ENDPOINTS_PATH)
    diagram = read_text(MERMAID_DIAGRAM_PATH)
    visuals = read_text(EXPORT_VISUALS_PATH)

    assert_contains(actions, 'buildMessageVisualAssets(message.id)', 'export builds visual assets')
    assert_contains(actions, 'visual_assets:', 'assets are sent on the request')
    assert_contains(endpoints, 'visual_assets?: ExportVisualAsset[]', 'request type carries assets')

    assert_contains(diagram, 'registerExportDiagram', 'diagrams register themselves for export')
    assert_contains(diagram, 'getSvg:', 'the SVG is read back at export time')

    assert_contains(visuals, "kind: VISUAL_KIND_DIAGRAM", 'assets are tagged as diagrams')
    assert_contains(visuals, "'diagram'", 'the kind has to match the server')

    # The server drops anything past its own cap, so sending more is wasted work and a
    # silently truncated export.
    route = read_text(EXPORT_ROUTE_PATH)
    server_cap = re.search(r'MESSAGE_EXPORT_VISUAL_ASSET_MAX_COUNT\s*=\s*(\d+)', route)
    client_cap = re.search(r'MAX_ASSETS_PER_MESSAGE\s*=\s*(\d+)', visuals)
    assert server_cap and client_cap, (server_cap, client_cap)
    assert server_cap.group(1) == client_cap.group(1), (
        f'client sends up to {client_cap.group(1)} assets but the server keeps '
        f'{server_cap.group(1)}'
    )

    print("V2 client-supplied diagrams passed!")


def test_browser_and_server_normalize_fences_identically():
    """The two normalizations must agree, or every client asset is silently discarded.

    The server indexes assets by normalized fence text and re-renders anything it cannot
    match, so a mismatch costs the whole optimisation without producing an error anywhere.
    """
    print("Testing fence normalization parity...")

    source = read_text(EXPORT_VISUALS_PATH)
    match = re.search(
        r'export function normalizeVisualSource\(.*?\n\}',
        source,
        re.DOTALL,
    )
    assert match, 'normalizeVisualSource could not be located'

    # Run the browser's own implementation rather than a restatement of it, with the one
    # TypeScript annotation removed so plain Node can execute the body unchanged.
    js_function = match.group(0).replace('export function', 'function').replace(
        'normalizeVisualSource(value: string): string',
        'normalizeVisualSource(value)',
    )
    script = (
        f'{js_function}\n'
        f'const cases = {json.dumps(NORMALIZATION_CASES)};\n'
        'process.stdout.write(JSON.stringify(cases.map(normalizeVisualSource)));\n'
    )

    with tempfile.TemporaryDirectory() as work_dir:
        script_path = os.path.join(work_dir, 'normalize.mjs')
        with open(script_path, 'w', encoding='utf-8') as handle:
            handle.write(script)
        try:
            completed = subprocess.run(
                ['node', script_path],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
        except FileNotFoundError:
            print("Skipping parity assertion: Node is not available on this machine.")
            return

    browser_results = json.loads(completed.stdout)
    server_results = [normalize_visual_source(case) for case in NORMALIZATION_CASES]

    for case, from_browser, from_server in zip(
        NORMALIZATION_CASES, browser_results, server_results
    ):
        assert from_browser == from_server, (
            f'normalization disagrees for {case!r}: browser {from_browser!r} '
            f'vs server {from_server!r}'
        )

    print("Fence normalization parity passed!")


def test_classic_toast_supports_work_in_progress():
    """The classic toast utility must be able to stay on screen until work finishes."""
    print("Testing classic progress toast...")

    global_toast = read_text(GLOBAL_TOAST_PATH)
    assert_contains(global_toast, 'options.autohide !== false', 'autohide option')
    assert_contains(global_toast, 'return { dismiss:', 'a handle to dismiss the toast')
    assert_contains(global_toast, 'spinner-border', 'a progress toast shows a spinner')

    chat_toast = read_text(CHAT_TOAST_PATH)
    assert_contains(chat_toast, 'return window.showToast', 'the handle must be forwarded')

    print("Classic progress toast passed!")


def test_classic_export_reports_progress():
    """Every classic export must raise a progress toast and always clear it."""
    print("Testing classic export progress feedback...")

    source = read_text(CHAT_EXPORT_PATH)

    assert source.count('{ autohide: false }') >= 3, (
        'Word, PowerPoint and email exports each need a progress toast'
    )
    assert source.count('progressToast?.dismiss();') >= 3, (
        'a progress toast that is never dismissed hides the result behind it'
    )
    assert source.count('} finally {') >= 3, 'the toast must clear on failure as well'

    print("Classic export progress feedback passed!")


def test_classic_export_menu_items_show_a_pending_state():
    """The classic dropdown entries need the pending state its inline buttons already have."""
    print("Testing classic export menu pending state...")

    source = read_text(CHAT_MESSAGES_PATH)

    for selector in (
        'dropdown-export-word-btn',
        'dropdown-export-ppt-btn',
        'dropdown-open-email-btn',
    ):
        for occurrence in re.findall(rf'<a class="dropdown-item {selector}"[^>]*>', source):
            assert 'data-pending-label' in occurrence, (
                f'{selector} has no pending label, so it never spins or disables: {occurrence}'
            )

    # The click handler only shows a pending state when the button declares a pending label,
    # and only refuses repeat clicks once aria-busy is set by that same path.
    assert_contains(source, 'actionButton.dataset.pendingLabel', 'pending state gate')
    assert_contains(source, "getAttribute('aria-busy') === 'true'", 'repeat click guard')

    print("Classic export menu pending state passed!")


if __name__ == "__main__":
    tests: List[Callable[[], None]] = [
        test_v2_toast_store_supports_pending_work,
        test_v2_toaster_renders_pending_state,
        test_v2_export_reports_progress_and_disables_itself,
        test_v2_sends_the_diagram_it_already_drew,
        test_browser_and_server_normalize_fences_identically,
        test_classic_toast_supports_work_in_progress,
        test_classic_export_reports_progress,
        test_classic_export_menu_items_show_a_pending_state,
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
