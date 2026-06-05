#!/usr/bin/env python3
# test_cosmos_throughput_background_scheduler.py
"""
Functional test for Cosmos throughput background scheduler cadence.
Version: 0.241.157
Implemented in: 0.241.157

This test ensures the Cosmos throughput background autoscale loop uses the
configured Metrics Window as its check cadence and emits background-specific
logging markers.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
BACKGROUND_TASKS_FILE = os.path.join(APP_ROOT, "background_tasks.py")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_cosmos_throughput import calculate_cosmos_throughput_autoscale_interval_seconds  # noqa: E402


def _read_background_tasks_source():
    with open(BACKGROUND_TASKS_FILE, "r", encoding="utf-8") as source_file:
        return source_file.read()


def test_autoscale_interval_uses_metrics_window():
    """Metrics Window should control the background check cadence."""
    assert calculate_cosmos_throughput_autoscale_interval_seconds({
        'cosmos_throughput_metrics_window_minutes': 1,
    }) == 60
    assert calculate_cosmos_throughput_autoscale_interval_seconds({
        'cosmos_throughput_metrics_window_minutes': 5,
    }) == 300
    assert calculate_cosmos_throughput_autoscale_interval_seconds({
        'cosmos_throughput_metrics_window_minutes': 10,
    }) == 600
    assert calculate_cosmos_throughput_autoscale_interval_seconds({
        'cosmos_throughput_metrics_window_minutes': 60,
    }) == 3600


def test_background_loop_uses_dynamic_sleep_and_logging():
    """The scheduler should avoid a hard-coded Cosmos autoscale sleep."""
    source = _read_background_tasks_source()

    assert "get_cosmos_throughput_autoscale_sleep_seconds()" in source
    assert "time.sleep(sleep_seconds)" in source
    assert "time.sleep(300)" not in source[source.index("def run_cosmos_throughput_autoscale_loop") : source.index("def check_due_workflows_once")]
    assert "refresh_id = f\"background-{uuid.uuid4()}\"" in source
    assert "[CosmosThroughput] Background autoscale check starting." in source
    assert "[CosmosThroughput] Background autoscale check completed." in source
    assert "[CosmosThroughput] Background autoscale check sleeping." in source


if __name__ == "__main__":
    tests = [
        test_autoscale_interval_uses_metrics_window,
        test_background_loop_uses_dynamic_sleep_and_logging,
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
