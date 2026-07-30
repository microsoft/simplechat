#!/usr/bin/env python3
# test_malicious_pr_security_review_checker.py
"""
Functional test for Malicious PR Security Review CI guardrails.
Version: 0.250.006
Implemented in: 0.250.006

This test ensures the malicious PR/file security review checker flags the
highest-risk dependency and hidden-payload patterns, records suspicious egress
markers for human review, and stays wired into the GitHub Actions workflow.
"""

import importlib.util
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_malicious_pr_security_review.py'
WORKFLOW_FILE = ROOT_DIR / '.github' / 'workflows' / 'malicious-pr-security-review.yml'
PROMPT_FILE = ROOT_DIR / '.github' / 'prompts' / 'malicious-pr-and-file-security-review.prompt.md'
CONFIG_FILE = ROOT_DIR / 'application' / 'single_app' / 'config.py'


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding='utf-8')


def load_checker_module():
    """Import the checker module from disk without mutating sys.path."""
    spec = importlib.util.spec_from_file_location('check_malicious_pr_security_review', CHECKER_FILE)
    assert spec is not None and spec.loader is not None, 'Expected a module spec for the checker'
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


def test_dependency_gate_blocks_unpinned_python_requirements_and_collects_exact_pins() -> None:
    """Verify unsafe Python requirement forms are blockers and exact pins are collected."""
    module = load_checker_module()
    findings = []
    releases = []
    requirements_source = """
requests==2.32.4
flask>=3.0
--extra-index-url https://packages.example.invalid/simple
git+https://example.invalid/package.git
""".strip()

    module.inspect_requirements_file(
        ROOT_DIR / 'requirements-test.txt',
        requirements_source,
        findings,
        releases,
    )

    blocker_messages = [finding.message for finding in findings if finding.verdict == 'Blocker']
    assert any('not exactly pinned' in message for message in blocker_messages), blocker_messages
    assert any('custom index' in message for message in blocker_messages), blocker_messages
    assert any('direct URL' in message for message in blocker_messages), blocker_messages
    assert [(release.package_name, release.version) for release in releases] == [('requests', '2.32.4')]


def test_checker_flags_hidden_unicode_and_records_suspicious_egress_markers() -> None:
    """Verify hidden Unicode blocks and external egress markers are reported."""
    module = load_checker_module()
    findings = []
    source = "fetch('https://example.invalid/webhook', { method: 'POST' });\n" + "\u202e"

    urls = module.scan_text_patterns(
        ROOT_DIR / 'application' / 'single_app' / 'static' / 'js' / 'sample.js',
        source,
        changed_lines=None,
        full_file=True,
        findings=findings,
    )

    assert 'https://example.invalid/webhook' in urls
    assert any(finding.verdict == 'Blocker' and 'Hidden Unicode' in finding.message for finding in findings), findings
    assert any('external connection' in finding.message for finding in findings), findings


def test_npm_and_docker_dependency_policy_review() -> None:
    """Verify npm floating ranges and Docker latest tags are rejected."""
    module = load_checker_module()
    findings = []
    releases = []

    module.inspect_package_json(
        ROOT_DIR / 'package.json',
        '{"dependencies":{"safe":"1.2.3","floating":"^4.5.6"}}',
        findings,
        releases,
    )
    module.inspect_dockerfile(
        ROOT_DIR / 'Dockerfile',
        'FROM python:latest\n',
        findings,
    )

    blocker_messages = [finding.message for finding in findings if finding.verdict == 'Blocker']
    assert any('npm dependency is not pinned' in message for message in blocker_messages), blocker_messages
    assert any('Docker base image is floating' in message for message in blocker_messages), blocker_messages
    assert [(release.package_name, release.version) for release in releases] == [('safe', '1.2.3')]


def test_checker_workflow_prompt_and_version_are_wired_into_repo() -> None:
    """Verify the checker, workflow, prompt, and version bump landed together."""
    assert CHECKER_FILE.exists(), f'Expected checker script at {CHECKER_FILE}'
    assert WORKFLOW_FILE.exists(), f'Expected workflow file at {WORKFLOW_FILE}'
    assert PROMPT_FILE.exists(), f'Expected prompt file at {PROMPT_FILE}'
    assert read_config_version() == '0.250.006'

    workflow_source = read_text(WORKFLOW_FILE)
    assert 'Malicious PR Security Review' in workflow_source
    assert 'pull_request' in workflow_source
    assert 'workflow_dispatch' in workflow_source
    assert 'scripts/check_malicious_pr_security_review.py' in workflow_source
    assert '--verify-release-age' in workflow_source
    assert 'actions/upload-artifact@v4' in workflow_source

    prompt_source = read_text(PROMPT_FILE)
    assert 'Dependency Gate' in prompt_source
    assert 'High-Risk Search Patterns' in prompt_source
    assert 'Do not run untrusted code' in prompt_source


if __name__ == '__main__':
    tests = [
        test_dependency_gate_blocks_unpinned_python_requirements_and_collects_exact_pins,
        test_checker_flags_hidden_unicode_and_records_suspicious_egress_markers,
        test_npm_and_docker_dependency_policy_review,
        test_checker_workflow_prompt_and_version_are_wired_into_repo,
    ]
    results = []

    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            results.append(False)

    success = all(results)
    print(f'Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)