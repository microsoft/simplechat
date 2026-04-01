#!/usr/bin/env python3
# test_background_task_distributed_locks.py
"""
Functional test for distributed background task locks.
Version: 0.239.129
Implemented in: 0.239.129

This test ensures that retention policy and approval expiry background tasks
use Cosmos-backed distributed lock helpers so duplicate execution is reduced
across multiple workers and App Service instances.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND_TASKS_FILE = ROOT / 'application' / 'single_app' / 'background_tasks.py'
CONFIG_FILE = ROOT / 'application' / 'single_app' / 'config.py'


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding='utf-8')
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_background_task_distributed_locks() -> bool:
    print('Testing distributed background task lock wiring...')

    assert_contains(BACKGROUND_TASKS_FILE, 'from azure.core import MatchConditions')
    assert_contains(BACKGROUND_TASKS_FILE, 'from config import cosmos_settings_container, exceptions')
    assert_contains(BACKGROUND_TASKS_FILE, 'def acquire_distributed_task_lock(task_name, lease_seconds):')
    assert_contains(BACKGROUND_TASKS_FILE, 'def release_distributed_task_lock(lock_document):')
    assert_contains(BACKGROUND_TASKS_FILE, 'background_task_lock_')
    assert_contains(BACKGROUND_TASKS_FILE, "acquire_distributed_task_lock('approval_expiry', lease_seconds=1800)")
    assert_contains(BACKGROUND_TASKS_FILE, "acquire_distributed_task_lock('retention_policy', lease_seconds=3600)")
    assert_contains(BACKGROUND_TASKS_FILE, 'release_distributed_task_lock(lock_document)')
    assert_contains(CONFIG_FILE, 'VERSION = "0.239.129"')

    print('Distributed background task lock checks passed!')
    return True


if __name__ == '__main__':
    try:
        success = test_background_task_distributed_locks()
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)