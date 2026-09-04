# harness_build.py
"""
Shared plumbing for the V2 orchestration Playwright UI tests (test artifact, not app source).

The V2 UI ships as a bundled React SPA, so its orchestration components cannot be imported as
plain browser ES modules the way the classic chat JS can. Mirroring the esbuild approach the
functional_tests/test_v2_*.py files already use, this module bundles the real components (via
harness_entry.tsx) for the browser once, then -- mirroring the ui_tests static-harness tests --
serves the repository over a local HTTP server so a Playwright page can load the bundle, seed the
real stores, mount a component into a real DOM, and drive it with genuine clicks. No network, no
Azure credentials.

The bundle is rebuilt only when the entry or any V2 source file is newer than it, so reruns are
fast. If the front-end toolchain is not installed (application/v2_ui/node_modules missing), the
build is unavailable and the caller is expected to skip -- the same convention the functional V2
tests keep.
"""

import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
V2_UI = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_UI / "src"
NODE_MODULES = V2_UI / "node_modules"
ENTRY = HERE / "harness_entry.tsx"
BUNDLE = HERE / "harness.bundle.js"
HARNESS_HTML_REL = "ui_tests/fixtures/orchestration/harness.html"


class HarnessUnavailable(RuntimeError):
    """Raised when the front-end toolchain needed to build the harness bundle is not installed."""


def _newest_source_mtime():
    """The newest modification time among the harness entry and every V2 source file."""
    newest = ENTRY.stat().st_mtime
    for path in V2_SRC.rglob("*"):
        if path.is_file():
            mtime = path.stat().st_mtime
            if mtime > newest:
                newest = mtime
    return newest


def ensure_bundle():
    """Build the browser bundle if missing or stale, and return its path.

    Raises HarnessUnavailable when application/v2_ui/node_modules is absent, so a caller on a
    machine without the front-end toolchain can skip rather than fail.
    """
    if not NODE_MODULES.exists():
        raise HarnessUnavailable(
            "application/v2_ui/node_modules is missing; run `npm install` in application/v2_ui"
        )

    if BUNDLE.exists() and BUNDLE.stat().st_mtime >= _newest_source_mtime():
        return BUNDLE

    env = dict(os.environ)
    # esbuild resolves the entry's bare imports (react, react-dom/client, zustand, ...) through
    # NODE_PATH; the entry lives outside application/v2_ui and so has no node_modules of its own.
    env["NODE_PATH"] = str(NODE_MODULES)

    command = [
        "npx",
        "esbuild",
        str(ENTRY),
        "--bundle",
        "--format=iife",
        "--platform=browser",
        "--jsx=automatic",
        # apiClient.ts reads Vite's import.meta.env at module scope; the browser has no such
        # object, so it is defined away. The code under test degrades to '' via optional chaining.
        "--define:import.meta.env={}",
        # React's development build reads process.env.NODE_ENV, which does not exist in the
        # browser; define it so the bundle evaluates instead of throwing a ReferenceError.
        '--define:process.env.NODE_ENV="development"',
        f"--outfile={BUNDLE}",
        "--log-level=warning",
    ]
    result = subprocess.run(
        command,
        cwd=str(V2_UI),
        env=env,
        capture_output=True,
        text=True,
        shell=(sys.platform == "win32"),
    )
    if result.returncode != 0:
        raise AssertionError(
            "esbuild failed to bundle the orchestration harness:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return BUNDLE


def _get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def start_static_server():
    """Serve the repository root over a local HTTP server for the duration of the block."""
    port = _get_free_local_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def harness_page(collect_errors=None):
    """Yield a Playwright page with the built harness loaded and window.OrchHarness ready.

    Builds the bundle (raising HarnessUnavailable when the toolchain is absent), serves the repo,
    launches headless chromium, and navigates to the harness. Uncaught page errors are appended to
    ``collect_errors`` when a list is supplied, so a test can assert the components ran clean.
    """
    ensure_bundle()
    try:
        import playwright.sync_api as playwright_sync_api
    except ImportError as exc:
        raise HarnessUnavailable(
            "playwright is not installed; run `pip install -r ui_tests/requirements.txt`"
        ) from exc

    with playwright_sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        if collect_errors is not None:
            page.on("pageerror", lambda error: collect_errors.append(str(error)))
        try:
            with start_static_server() as base_url:
                response = page.goto(
                    f"{base_url}/{HARNESS_HTML_REL}", wait_until="domcontentloaded"
                )
                if not (response and response.ok):
                    raise AssertionError("harness html failed to load")
                page.wait_for_function('() => typeof window.OrchHarness === "object"')
                yield page
        finally:
            context.close()
            browser.close()
