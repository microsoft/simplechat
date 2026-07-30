#!/usr/bin/env python3
# test_xss_guardrails_checker.py
"""
Functional test for XSS PR guardrail checker.
Version: 0.250.004
Implemented in: 0.241.021

This test ensures the changed-file XSS checker flags the repo's target sink
patterns, allows the approved safe rendering patterns, and stays wired into
the repo instruction, PR workflow, and full-audit prompt.
"""

import importlib.util
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_xss_sinks.py'
WORKFLOW_FILE = ROOT_DIR / '.github' / 'workflows' / 'xss-sink-check.yml'
INSTRUCTION_FILE = ROOT_DIR / '.github' / 'instructions' / 'xss-prevention.instructions.md'
FULL_AUDIT_PROMPT_FILE = ROOT_DIR / '.github' / 'prompts' / 'xss-full-audit-and-remediation.prompt.md'
FEATURE_DOC = ROOT_DIR / 'docs' / 'explanation' / 'features' / 'v0.241.022' / 'XSS_PR_GUARDRAILS.md'
CONFIG_FILE = ROOT_DIR / 'application' / 'single_app' / 'config.py'


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding='utf-8')


def load_checker_module():
    """Import the checker module from disk without touching sys.path."""
    spec = importlib.util.spec_from_file_location('check_xss_sinks', CHECKER_FILE)
    assert spec is not None and spec.loader is not None, 'Expected a module spec for check_xss_sinks.py'
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_config_version() -> str:
    """Extract the current application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def issue_messages(module, file_name: str, source_text: str) -> list[str]:
    """Return the issue messages emitted for one in-memory source string."""
    issues = module.inspect_source(Path(file_name), source_text)
    return [issue.message for issue in issues]


def test_checker_flags_dynamic_html_sinks_and_attribute_interpolation() -> None:
    """Verify dynamic HTML sinks and attribute interpolation are rejected."""
    module = load_checker_module()

    js_source = """
const row = document.createElement('tr');
row.innerHTML = `<td data-user-name="${userName}">${userName}</td>`;
""".strip()
    messages = issue_messages(module, 'sample.js', js_source)

    assert any('innerHTML/outerHTML' in message for message in messages), messages
    assert any('data-* attributes' in message for message in messages), messages


def test_checker_flags_marked_parse_inline_handlers_and_server_side_bypasses() -> None:
    """Verify the checker covers client and server bypass markers."""
    module = load_checker_module()

    js_source = """
const html = marked.parse(markdown);
button.setAttribute('onclick', 'runDanger()');
const rowHtml = `<button onclick="runDanger('${userName}')">Run</button>`;
""".strip()
    js_messages = issue_messages(module, 'sample.js', js_source)
    assert any('DOMPurify.sanitize' in message for message in js_messages), js_messages
    assert any('inline event-handler APIs' in message for message in js_messages), js_messages

    py_source = """
from markupsafe import Markup
safe_markup = Markup(user_supplied_html)
""".strip()
    py_messages = issue_messages(module, 'sample.py', py_source)
    assert any('Markup(...)' in message for message in py_messages), py_messages

    html_source = """
<div>{{ user_bio|safe }}</div>
""".strip()
    html_messages = issue_messages(module, 'sample.html', html_source)
    assert any("Jinja '|safe'" in message for message in html_messages), html_messages


def test_checker_allows_safe_dom_patterns_static_shells_and_reviewed_suppressions() -> None:
    """Verify the checker allows the repo's preferred safe rendering patterns."""
    module = load_checker_module()

    safe_js_source = """
const row = document.createElement('tr');
const nameCell = document.createElement('td');
nameCell.textContent = userName;
const actionButton = document.createElement('button');
actionButton.dataset.userName = userName;
actionButton.addEventListener('click', handleClick);
modal.innerHTML = '<div class="modal"><h5 class="modal-title"></h5></div>';
const renderedHtml = DOMPurify.sanitize(marked.parse(markdown));
const escapedName = escapeHtml(userName);
row.innerHTML = `<td title="${escapeHtml(userName)}" data-user-name="${escapedName}">${escapeHtml(userName)}</td>`;
document.querySelector(`[data-user-id="${userId}"]`);
""".strip()
    assert issue_messages(module, 'safe.js', safe_js_source) == []

    suppressed_js_source = """
// xss-check: ignore reviewed legacy shell with static allowlist
container.innerHTML = htmlFromReviewedBoundary;
""".strip()
    assert issue_messages(module, 'suppressed.js', suppressed_js_source) == []


def test_checker_assets_and_version_are_wired_into_repo() -> None:
    """Verify the new workflow, instruction, prompt, doc, and version bump landed together."""
    assert CHECKER_FILE.exists(), f'Expected checker script at {CHECKER_FILE}'
    assert WORKFLOW_FILE.exists(), f'Expected workflow file at {WORKFLOW_FILE}'
    assert INSTRUCTION_FILE.exists(), f'Expected instruction file at {INSTRUCTION_FILE}'
    assert FULL_AUDIT_PROMPT_FILE.exists(), f'Expected full-audit prompt at {FULL_AUDIT_PROMPT_FILE}'
    assert FEATURE_DOC.exists(), f'Expected feature document at {FEATURE_DOC}'
    assert read_config_version() == '0.250.004'

    workflow_source = read_text(WORKFLOW_FILE)
    assert 'scripts/check_xss_sinks.py' in workflow_source
    assert 'functional_tests/test_xss_guardrails_checker.py' in workflow_source
    assert '.github/prompts/xss-full-audit-and-remediation.prompt.md' in workflow_source

    instruction_source = read_text(INSTRUCTION_FILE)
    assert 'xss-check: ignore' in instruction_source
    assert 'innerHTML' in instruction_source
    assert 'DOMPurify.sanitize' in instruction_source

    feature_doc_source = read_text(FEATURE_DOC)
    assert 'Fixed/Implemented in version: **0.241.021**' in feature_doc_source
    assert 'scripts/check_xss_sinks.py' in feature_doc_source
    assert '.github/workflows/xss-sink-check.yml' in feature_doc_source

    prompt_source = read_text(FULL_AUDIT_PROMPT_FILE)
    assert 'python scripts/check_xss_sinks.py --full-file' in prompt_source
    assert 'rg -n "innerHTML|outerHTML|insertAdjacentHTML' in prompt_source
    assert 'DOMPurify.sanitize(marked.parse' in prompt_source


if __name__ == '__main__':
    tests = [
        test_checker_flags_dynamic_html_sinks_and_attribute_interpolation,
        test_checker_flags_marked_parse_inline_handlers_and_server_side_bypasses,
        test_checker_allows_safe_dom_patterns_static_shells_and_reviewed_suppressions,
        test_checker_assets_and_version_are_wired_into_repo,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            print('✅ PASS')
            results.append(True)
        except Exception as exc:  # pragma: no cover - standalone script reporting
            print(f'❌ FAIL: {exc}')
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)