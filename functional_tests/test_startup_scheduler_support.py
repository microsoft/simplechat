#!/usr/bin/env python3
# test_startup_scheduler_support.py
"""
Functional test for startup and scheduler separation support.
Version: 0.239.129
Implemented in: 0.239.129

This test ensures that the web process uses shared background-task helpers,
the dedicated scheduler entrypoint exists, and the deployment guidance
documentation describes native Python and container startup behavior.
"""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_FILE = ROOT / 'application' / 'single_app' / 'app.py'
BACKGROUND_TASKS_FILE = ROOT / 'application' / 'single_app' / 'background_tasks.py'
SCHEDULER_FILE = ROOT / 'application' / 'single_app' / 'simplechat_scheduler.py'
DOC_FILE = ROOT / 'docs' / 'explanation' / 'features' / 'SIMPLECHAT_STARTUP.md'
CONFIG_FILE = ROOT / 'application' / 'single_app' / 'config.py'


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding='utf-8')
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_startup_scheduler_support() -> bool:
    print('Testing startup and scheduler support...')

    assert_contains(APP_FILE, 'from background_tasks import start_background_task_threads')
    assert_contains(APP_FILE, 'start_background_task_threads()')
    assert_contains(APP_FILE, 'def should_start_background_tasks():')
    assert_contains(BACKGROUND_TASKS_FILE, 'def acquire_distributed_task_lock(task_name, lease_seconds):')
    assert_contains(BACKGROUND_TASKS_FILE, 'def release_distributed_task_lock(lock_document):')
    assert_contains(BACKGROUND_TASKS_FILE, 'def run_scheduler_forever():')
    assert_contains(BACKGROUND_TASKS_FILE, 'def check_retention_policy_once():')
    assert_contains(BACKGROUND_TASKS_FILE, "acquire_distributed_task_lock('approval_expiry', lease_seconds=1800)")
    assert_contains(BACKGROUND_TASKS_FILE, "acquire_distributed_task_lock('retention_policy', lease_seconds=3600)")
    assert_contains(SCHEDULER_FILE, 'def initialize_scheduler_runtime():')
    assert_contains(SCHEDULER_FILE, 'run_scheduler_forever()')
    assert_contains(DOC_FILE, '## Native Python App Service')
    assert_contains(DOC_FILE, '## Container Runtime')
    assert_contains(DOC_FILE, 'simplechat_scheduler.py')
    assert_contains(CONFIG_FILE, 'VERSION = "0.239.129"')

    print('Startup and scheduler support checks passed!')
    return True


if __name__ == '__main__':
    try:
        success = test_startup_scheduler_support()
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)