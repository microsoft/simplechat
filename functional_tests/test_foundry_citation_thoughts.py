# test_foundry_citation_thoughts.py
#!/usr/bin/env python3
"""
Functional test for Foundry citation thought display.
Version: 0.250.114
Implemented in: 0.250.114

This test ensures Foundry citation thoughts use each citation value safely instead
of emitting duplicate generic messages for every citation.
"""

import ast
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / 'application' / 'single_app'
ROUTE_FILE = APP_ROOT / 'route_backend_chats.py'
CONFIG_FILE = APP_ROOT / 'config.py'
EXPECTED_VERSION = '0.250.114'

TARGET_NAMES = {
    'FOUNDRY_AGENT_LABELS',
    'FOUNDRY_CITATION_DISPLAY_FIELDS',
    'FOUNDRY_CITATION_NESTED_FIELDS',
    'FOUNDRY_CITATION_URL_FIELDS',
    '_build_foundry_citation_thought_content',
    '_get_foundry_agent_label',
    '_get_foundry_citation_display_label',
    '_get_foundry_citation_url_label',
    '_iter_foundry_citation_sources',
    '_normalize_foundry_citation_display_text',
}


def read_text(path):
    """Read a UTF-8 source file."""
    return path.read_text(encoding='utf-8')


def read_current_version():
    """Return the current app version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError('Expected config.py to define VERSION')


def load_foundry_citation_helpers():
    """Load only the Foundry citation helper definitions from the chat route."""
    route_content = read_text(ROUTE_FILE)
    parsed = ast.parse(route_content, filename=str(ROUTE_FILE))
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            target_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if target_names & TARGET_NAMES:
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in TARGET_NAMES:
            selected_nodes.append(node)

    namespace = {'urlparse': urlparse}
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(ROUTE_FILE), 'exec'), namespace)
    return namespace, route_content


def test_version_matches_fix_header():
    """Validate the functional test header tracks the current app version."""
    print('Testing version header...')
    assert read_current_version() == EXPECTED_VERSION
    print('PASS: version header')


def test_foundry_citation_thoughts_use_safe_display_values():
    """Validate citation-specific thoughts are useful without exposing raw payloads."""
    print('Testing Foundry citation thought labels...')
    helpers, _ = load_foundry_citation_helpers()
    build_thought = helpers['_build_foundry_citation_thought_content']

    cases = [
        (
            'new_foundry',
            {'title': '  Mission Report  '},
            'Agent retrieved citation from New Foundry Application: Mission Report',
        ),
        (
            'foundry_workflow',
            {'metadata': {'file_name': 'analysis-summary.docx'}},
            'Agent retrieved citation from Foundry Workflow: analysis-summary.docx',
        ),
        (
            'aifoundry',
            {'url': 'https://contoso.example/reports/mission.pdf?sig=secret-token'},
            'Agent retrieved citation from Azure AI Foundry Agent: contoso.example',
        ),
        (
            'aifoundry',
            {'url': 'https://user:token@contoso.example:8443/reports/mission.pdf'},
            'Agent retrieved citation from Azure AI Foundry Agent: contoso.example',
        ),
        (
            'new_foundry',
            {'quote': 'Do not surface raw quoted text in the thought stream.'},
            'Agent retrieved citation from New Foundry Application',
        ),
        (
            'foundry_workflow',
            'raw string citation payload',
            'Agent retrieved citation from Foundry Workflow',
        ),
    ]

    for agent_type, citation, expected in cases:
        actual = build_thought(agent_type, citation)
        assert actual == expected, f'Expected {expected!r}, got {actual!r}'

    unsafe_title = build_thought('new_foundry', {'title': '<script>alert(1)</script>'})
    forbidden_fragments = ['<script', '</script>', 'sig=secret-token', "{'", 'raw quoted text']
    for fragment in forbidden_fragments:
        assert fragment not in unsafe_title

    print('PASS: Foundry citation thought labels')


def test_foundry_citation_thought_wiring_uses_citation_variable():
    """Validate regular and streaming Foundry paths use citation-specific thought text."""
    print('Testing Foundry citation thought route wiring...')
    _, route_content = load_foundry_citation_helpers()

    expected_snippets = [
        '_build_foundry_citation_thought_content(selected_agent_type, citation)',
        '_build_foundry_citation_thought_content(stream_selected_agent_type, citation)',
    ]
    for snippet in expected_snippets:
        assert snippet in route_content

    forbidden_snippets = [
        'f"Agent retrieved citation from {_get_foundry_agent_label(selected_agent_type)}"',
        'f"Agent retrieved citation from {_get_foundry_agent_label(stream_selected_agent_type)}"',
    ]
    for snippet in forbidden_snippets:
        assert snippet not in route_content

    print('PASS: Foundry citation thought route wiring')


def run_tests():
    """Run functional tests."""
    tests = [
        test_version_matches_fix_header,
        test_foundry_citation_thoughts_use_safe_display_values,
        test_foundry_citation_thought_wiring_uses_citation_variable,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)