#!/usr/bin/env python3
# test_route_backend_chats_redundant_assignment.py
"""
Functional test for redundant self-assignment removal in route_backend_chats.py.
Version: 0.239.148
Implemented in: 0.239.148

This test ensures route_backend_chats.py does not contain standalone assignments
that assign a local name to itself, which would be a no-op and usually indicates
an implementation mistake.
"""

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
CONFIG_FILE = ROOT / 'application' / 'single_app' / 'config.py'
FIX_DOC_FILE = ROOT / 'docs' / 'explanation' / 'fixes' / 'REDUNDANT_CONVERSATION_ID_ASSIGNMENT_FIX.md'
CURRENT_VERSION = '0.239.148'


def find_self_assignments(tree: ast.AST) -> list[tuple[str, int]]:
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue

        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Name):
            if target.id == node.value.id:
                matches.append((target.id, node.lineno))

    return matches


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding='utf-8')
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_route_backend_chats_redundant_assignment() -> bool:
    print('Testing route_backend_chats.py for redundant self-assignments...')

    source = TARGET_FILE.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(TARGET_FILE))
    matches = find_self_assignments(tree)

    if matches:
        formatted_matches = ', '.join(f'{name} at line {line}' for name, line in matches)
        raise AssertionError(f'Found redundant self-assignments: {formatted_matches}')

    assert_contains(CONFIG_FILE, f'VERSION = "{CURRENT_VERSION}"')
    assert_contains(FIX_DOC_FILE, f'Fixed/Implemented in version: **{CURRENT_VERSION}**')

    print('route_backend_chats.py redundant self-assignment checks passed!')
    return True


if __name__ == '__main__':
    try:
        success = test_route_backend_chats_redundant_assignment()
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)
