#!/usr/bin/env python3
# test_changed_files_action_version.py
"""
Functional test for changed-files GitHub Action version pin.
Version: 0.239.136
Implemented in: 0.239.135

This test ensures the release notes workflow uses the patched
tj-actions/changed-files version and no longer references the known malicious
commit from the March 2025 supply chain incident.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_FILE = ROOT / '.github' / 'workflows' / 'release-notes-check.yml'
CONFIG_FILE = ROOT / 'application' / 'single_app' / 'config.py'
FIX_DOC_FILE = ROOT / 'docs' / 'explanation' / 'fixes' / 'CHANGED_FILES_GITHUB_ACTION_SUPPLY_CHAIN_FIX.md'

SAFE_ACTION_REFERENCE = 'tj-actions/changed-files@v46.0.1'
MALICIOUS_COMMIT = '0e58ed8671d6b60d0890c21b07f8835ace038e67'
CURRENT_VERSION = '0.239.136'
IMPLEMENTED_VERSION = '0.239.135'


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding='utf-8')
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, unexpected: str) -> None:
    content = file_path.read_text(encoding='utf-8')
    if unexpected in content:
        raise AssertionError(f"Did not expect to find {unexpected!r} in {file_path}")


def test_changed_files_action_version() -> bool:
    print('Testing changed-files action version pin...')

    assert_contains(WORKFLOW_FILE, SAFE_ACTION_REFERENCE)
    assert_not_contains(WORKFLOW_FILE, MALICIOUS_COMMIT)
    assert_contains(CONFIG_FILE, f'VERSION = "{CURRENT_VERSION}"')
    assert_contains(FIX_DOC_FILE, f'Fixed/Implemented in version: **{IMPLEMENTED_VERSION}**')

    print('changed-files action version pin checks passed!')
    return True


if __name__ == '__main__':
    try:
        success = test_changed_files_action_version()
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)