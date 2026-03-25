#!/usr/bin/env python3
# test_group_public_workspace_expanded_tags.py
"""
Functional test for group and public workspace expanded tag rendering.
Version: 0.239.113
Implemented in: 0.239.113

This test ensures that group and public workspace list-view expanded rows
render document tags like the personal workspace does.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PERSONAL_WORKSPACE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'workspace',
    'workspace-documents.js',
)
GROUP_WORKSPACE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'templates',
    'group_workspaces.html',
)
PUBLIC_WORKSPACE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'public',
    'public_workspace.js',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def assert_contains(content, snippets, label):
    missing = [snippet for snippet in snippets if snippet not in content]
    if missing:
        raise AssertionError(f'{label} is missing required snippets: {missing}')


def assert_in_order(content, snippets, label):
    positions = [content.find(snippet) for snippet in snippets]
    if any(position == -1 for position in positions):
        raise AssertionError(f'{label} is missing snippets required for ordering: {snippets}')
    if positions != sorted(positions):
        raise AssertionError(f'{label} snippets are not in the expected order: {snippets}')


def test_personal_workspace_reference():
    """Verify the personal workspace still provides the parity reference."""
    print('Testing personal workspace tag row reference...')

    content = read_file(PERSONAL_WORKSPACE_FILE)
    assert_contains(
        content,
        ['<p class="mb-1"><strong>Tags:</strong> ${renderTagBadges(doc.tags || [])}</p>'],
        'Personal workspace',
    )

    print('Personal workspace tag row reference is present.')
    return True


def test_group_workspace_expanded_tags():
    """Verify group workspace expanded rows render tag badges."""
    print('Testing group workspace expanded tag rendering...')

    content = read_file(GROUP_WORKSPACE_FILE)
    assert_contains(
        content,
        [
            'function renderGroupTagBadges(tags, maxDisplay = 3)',
            'groupWorkspaceTags.find(t => t.name === tagName)',
            'return \'<span class="text-muted small">No tags</span>\';',
            'html += `<span class="badge bg-secondary">+${tags.length - maxDisplay}</span>`;',
            '<p class="mb-1"><strong>Tags:</strong> ${renderGroupTagBadges(doc.tags || [])}</p>',
        ],
        'Group workspace',
    )
    assert_in_order(
        content,
        [
            '<p class="mb-1"><strong>Keywords:</strong>',
            '<p class="mb-1"><strong>Tags:</strong> ${renderGroupTagBadges(doc.tags || [])}</p>',
            '<p class="mb-0"><strong>Abstract:</strong>',
        ],
        'Group workspace',
    )

    print('Group workspace expanded rows include tag badges.')
    return True


def test_public_workspace_expanded_tags():
    """Verify public workspace expanded rows render tag badges."""
    print('Testing public workspace expanded tag rendering...')

    content = read_file(PUBLIC_WORKSPACE_FILE)
    assert_contains(
        content,
        [
            'function renderPublicTagBadges(tags, maxDisplay = 3)',
            'publicWorkspaceTags.find(t => t.name === tagName)',
            'return \'<span class="text-muted small">No tags</span>\';',
            'html += `<span class="badge bg-secondary">+${tags.length - maxDisplay}</span>`;',
            '<p class="mb-1"><strong>Tags:</strong> ${renderPublicTagBadges(doc.tags || [])}</p>',
        ],
        'Public workspace',
    )
    assert_in_order(
        content,
        [
            '<p class="mb-1"><strong>Keywords:</strong>',
            '<p class="mb-1"><strong>Tags:</strong> ${renderPublicTagBadges(doc.tags || [])}</p>',
            '<p class="mb-0"><strong>Abstract:</strong>',
        ],
        'Public workspace',
    )

    print('Public workspace expanded rows include tag badges.')
    return True


if __name__ == '__main__':
    tests = [
        test_personal_workspace_reference,
        test_group_workspace_expanded_tags,
        test_public_workspace_expanded_tags,
    ]
    results = []

    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f'{test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)