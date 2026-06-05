#!/usr/bin/env python3
# test_cosmos_throughput_refresh_logging.py
"""
Functional test for Cosmos throughput refresh logging.
Version: 0.241.149
Implemented in: 0.241.149

This test ensures that Admin Settings Cosmos throughput refreshes emit
route-level and helper-level backend logs with a refresh correlation ID and
phase timing markers.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(REPO_ROOT, "application", "single_app", "route_backend_settings.py")
HELPER_FILE = os.path.join(REPO_ROOT, "application", "single_app", "functions_cosmos_throughput.py")


def _read_file(path):
    with open(path, "r", encoding="utf-8") as source_file:
        return source_file.read()


def test_refresh_route_logs_request_lifecycle():
    """The admin refresh route should log request start, completion, and failure."""
    source = _read_file(ROUTE_FILE)
    expected_markers = [
        "refresh_id = str(uuid.uuid4())",
        "[CosmosThroughput] Admin status refresh requested.",
        "[CosmosThroughput] Admin status refresh completed.",
        "[CosmosThroughput] Failed to load admin status.",
        "elapsed_ms",
    ]

    for marker in expected_markers:
        assert marker in source, f"Missing route logging marker: {marker}"


def test_refresh_helper_logs_backend_phases():
    """The helper should log ARM, container, metrics, and total refresh phases."""
    source = _read_file(HELPER_FILE)
    expected_markers = [
        "def _log_refresh_event",
        "[CosmosThroughput] ARM request starting.",
        "[CosmosThroughput] ARM credential acquisition starting.",
        "[CosmosThroughput] ARM credential acquired.",
        "[CosmosThroughput] ARM HTTP request sending.",
        "[CosmosThroughput] ARM request completed.",
        "credential_elapsed_ms",
        "[CosmosThroughput] Container list resolved.",
        "[CosmosThroughput] Container throughput scan completed.",
        "[CosmosThroughput] Azure Monitor metrics query starting.",
        "[CosmosThroughput] Azure Monitor metrics query completed.",
        "[CosmosThroughput] Throughput status refresh completed.",
    ]

    for marker in expected_markers:
        assert marker in source, f"Missing helper logging marker: {marker}"


if __name__ == "__main__":
    tests = [
        test_refresh_route_logs_request_lifecycle,
        test_refresh_helper_logs_backend_phases,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
