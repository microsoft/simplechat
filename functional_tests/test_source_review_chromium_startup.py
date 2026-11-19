# test_source_review_chromium_startup.py
"""
Regression coverage for the Chromium driver startup in Admin Settings and Source Review.
Version: 0.261.465
Implemented in: 0.261.465

The image launcher removes only the incompatible Azure preload, and an
unresponsive driver cannot indefinitely block configuration or rendering.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib
from pathlib import Path
import runpy
from threading import Event
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "docker-customization" / "simplechat_playwright_node.py"
AZURE_LOADER = "/agents/nodejs/build/src/Loader.js"


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (f"--require {AZURE_LOADER}", ""),
        (
            f'--max-old-space-size=256 --require="{AZURE_LOADER}" --require "/custom loader.cjs"',
            '--max-old-space-size=256 --require "/custom loader.cjs"',
        ),
        (
            f'--title="keeps --require {AZURE_LOADER} as text" -r {AZURE_LOADER} --no-deprecation',
            f'--title="keeps --require {AZURE_LOADER} as text" --no-deprecation',
        ),
        (f"--require {AZURE_LOADER}.backup", f"--require {AZURE_LOADER}.backup"),
        (f'--require "{AZURE_LOADER}', f'--require "{AZURE_LOADER}'),
        ("  --require /custom.js --no-deprecation  ", "  --require /custom.js --no-deprecation  "),
    ],
)
def test_launcher_removes_only_the_platform_preload(monkeypatch, options, expected):
    launcher = runpy.run_path(str(LAUNCHER))
    node_calls = []
    monkeypatch.setenv("NODE_OPTIONS", options)
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/custom.pem")
    monkeypatch.setattr("sys.argv", [str(LAUNCHER), "cli.js", "run-driver"])
    monkeypatch.setattr(
        "os.execve", lambda node, args, env: node_calls.append((node, args, env))
    )

    launcher["main"]()

    [(node, args, env)] = node_calls
    assert Path(node).parts[-3:] == ("playwright", "driver", "node")
    assert args == [node, "cli.js", "run-driver"]
    assert env["NODE_OPTIONS"] == expected
    assert env["NODE_EXTRA_CA_CERTS"] == "/custom.pem"
    assert launcher["os"].environ["NODE_OPTIONS"] == options


@pytest.fixture
def review_module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "application" / "single_app"))
    review = importlib.import_module("functions_source_review")
    monkeypatch.setattr(review, "_SOURCE_REVIEW_RUNTIME_PROBE", None)
    monkeypatch.setattr(review, "_SOURCE_REVIEW_RUNTIME_CAPABILITIES_CACHE", None)
    return review


def test_stalled_driver_returns_unavailable_without_starting_more_drivers(monkeypatch, review_module):
    sync_api = importlib.import_module("playwright.sync_api")
    entered, release = Event(), Event()
    starts = []

    @contextmanager
    def stalled_driver():
        starts.append(True)
        entered.set()
        if not release.wait(5):
            raise RuntimeError("The test did not release its stalled driver")
        yield SimpleNamespace(
            chromium=SimpleNamespace(launch=lambda **_: SimpleNamespace(close=lambda: None))
        )

    monkeypatch.setattr(sync_api, "sync_playwright", stalled_driver)
    monkeypatch.setattr(review_module, "_SOURCE_REVIEW_RUNTIME_PROBE_TIMEOUT_SECONDS", 0.05)

    with ThreadPoolExecutor(max_workers=2) as callers:
        start = time.monotonic()
        first = callers.submit(review_module.get_source_review_runtime_capabilities)
        probe = None
        try:
            driver_entered = entered.wait(1)
            assert driver_entered
            probe = review_module._SOURCE_REVIEW_RUNTIME_PROBE
            second = callers.submit(review_module.get_source_review_runtime_capabilities, True)
            for result in (first.result(timeout=1), second.result(timeout=1)):
                assert result["playwright_available"] is True
                assert result["js_rendering_available"] is False
                assert "timed out" in result["message"]
            assert time.monotonic() - start < 2
            assert len(starts) == 1
            page = asyncio.run(review_module._try_rendered_page_fetch(
                "https://example.test/article", "What happened?", {}, 0, None, None
            ))
            assert page["skip_reason"] == "js_rendering_runtime_unavailable"
        finally:
            release.set()
            if probe is not None:
                probe.result(timeout=2)

    recovered = review_module.get_source_review_runtime_capabilities()
    assert recovered["js_rendering_available"] is True
    assert recovered["chromium_launch_available"] is True
    assert len(starts) == 1
