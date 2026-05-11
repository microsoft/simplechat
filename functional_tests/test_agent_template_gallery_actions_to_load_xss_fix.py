#!/usr/bin/env python3
# test_agent_template_gallery_actions_to_load_xss_fix.py
"""
Functional test for agent template gallery actions_to_load XSS hardening.
Version: 0.241.022
Implemented in: 0.241.020

This test ensures the gallery renders actions_to_load as inert text and that
agent template helpers normalize the field consistently before read and write
paths use it.
"""

import ast
import os
import sys
from typing import Any, List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GALLERY_JS = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'agent_templates_gallery.js',
)
HELPERS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'functions_agent_templates.py',
)
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.020',
    'AGENT_TEMPLATE_GALLERY_ACTIONS_TO_LOAD_XSS_FIX.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_helper(function_name):
    source = read_file_text(HELPERS_FILE)
    parsed = ast.parse(source, filename=HELPERS_FILE)
    selected_node = next(
        (
            node
            for node in parsed.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ),
        None,
    )
    assert selected_node is not None, f'Expected helper {function_name} in {HELPERS_FILE}'

    module = ast.Module(body=[selected_node], type_ignores=[])
    namespace = {
        'Any': Any,
        'List': List,
    }
    exec(compile(module, HELPERS_FILE, 'exec'), namespace)
    return namespace[function_name]


def test_gallery_renders_actions_with_text_nodes():
    """Verify actions_to_load no longer reaches innerHTML in the gallery."""
    print('🔍 Testing gallery actions_to_load rendering...')

    source = read_file_text(GALLERY_JS)

    required_snippets = [
        'const actionLabel = document.createElement("strong");',
        'actionLabel.textContent = "Recommended actions:";',
        'document.createTextNode(` ${template.actions_to_load.map((action) => String(action)).join(", ")}`)',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing gallery hardening snippets: {missing}'

    forbidden_snippets = [
        'actionLine.innerHTML = `<strong>Recommended actions:</strong> ${template.actions_to_load.join(", ")}`;',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f'Unexpected unsafe gallery rendering snippets found: {present}'

    print('✅ Gallery actions_to_load rendering passed')


def test_actions_normalizer_trims_values_and_rejects_invalid_write_shapes():
    """Verify the shared normalizer handles read and write normalization correctly."""
    print('🔍 Testing shared actions_to_load normalizer...')

    normalize_actions = load_helper('_normalize_actions_to_load')

    assert normalize_actions(None) == []
    assert normalize_actions('') == []
    assert normalize_actions([' action-a ', ' ', 'action-b ']) == ['action-a', 'action-b']
    assert normalize_actions('not-a-list') == []
    assert normalize_actions(['action-a', 3]) == ['action-a', '3']

    try:
        normalize_actions('not-a-list', strict=True)
    except ValueError as exc:
        assert 'actions_to_load must be an array of strings' in str(exc)
    else:
        raise AssertionError('Expected strict writes to reject non-list actions_to_load values')

    try:
        normalize_actions(['action-a', 3], strict=True)
    except ValueError as exc:
        assert 'actions_to_load entries must be strings' in str(exc)
    else:
        raise AssertionError('Expected strict writes to reject non-string actions_to_load entries')

    print('✅ Shared actions_to_load normalizer passed')


def test_template_helpers_use_the_shared_actions_normalizer():
    """Verify create, update, and read paths all use the same normalizer."""
    print('🔍 Testing template helper integration markers...')

    source = read_file_text(HELPERS_FILE)
    required_snippets = [
        "cleaned['actions_to_load'] = _normalize_actions_to_load(cleaned.get('actions_to_load'))",
        "actions = _normalize_actions_to_load(payload.get('actions_to_load'), strict=True)",
        "payload['actions_to_load'] = _normalize_actions_to_load(payload['actions_to_load'], strict=True)",
        "payload['actions_to_load'] = _normalize_actions_to_load(doc.get('actions_to_load'))",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing template helper normalization snippets: {missing}'

    print('✅ Template helper integration markers passed')


def test_fix_documentation_and_version_exist():
    """Verify the fix note and current version stay in sync for this change."""
    print('🔍 Testing fix documentation and version...')

    assert read_config_version() == '0.241.022'
    assert os.path.exists(FIX_DOC), f'Expected fix documentation at {FIX_DOC}'

    fix_doc = read_file_text(FIX_DOC)
    assert 'Fixed/Implemented in version: **0.241.020**' in fix_doc
    assert 'functional_tests/test_agent_template_gallery_actions_to_load_xss_fix.py' in fix_doc
    assert 'ui_tests/test_agent_template_gallery_actions_escaping.py' in fix_doc

    print('✅ Fix documentation and version passed')


if __name__ == '__main__':
    tests = [
        test_gallery_renders_actions_with_text_nodes,
        test_actions_normalizer_trims_values_and_rejects_invalid_write_shapes,
        test_template_helpers_use_the_shared_actions_normalizer,
        test_fix_documentation_and_version_exist,
    ]

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        test()

    print(f'\n📊 Results: {len(tests)}/{len(tests)} tests passed')
    sys.exit(0)