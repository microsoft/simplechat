#!/usr/bin/env python3
# test_v2_orchestration_workflow_run_links_xss_guardrail.py
"""
Functional test for the V2 workflow run links passing the XSS sink guardrail.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that the Started workflows links under a chat answer pass
scripts/check_xss_sinks.py the way CI runs it. The link component calls the
reviewed same-origin builder workflowRunHref inside the link, the checker lists
that builder as approved, a link taken from a plain property is still flagged,
and the builder still returns only the fixed Workflows path.
"""

import importlib.util
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
V2_SRC_DIR = ROOT_DIR / 'application' / 'v2_ui' / 'src'
RUN_LINKS_COMPONENT = V2_SRC_DIR / 'components' / 'chat' / 'WorkflowRunLinks.tsx'
RUN_NOTICE_COMPONENT = V2_SRC_DIR / 'components' / 'chat' / 'OrchestrationWorkflowRunNotice.tsx'
RUN_LINKS_CLIENT = V2_SRC_DIR / 'lib' / 'orchestrationWorkflowRuns.ts'
RUN_LINK_BUILDER = V2_SRC_DIR / 'lib' / 'workflowRunLink.ts'
XSS_CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_xss_sinks.py'

UNSAFE_LINK_SNIPPET = """
import { Link } from 'react-router-dom';

export function Unsafe({ item }: { item: { href: string } }) {
    return <Link to={item.href}>Open run</Link>;
}
"""

APPROVED_LINK_SNIPPET = """
import { Link } from 'react-router-dom';
import { workflowRunHref } from '../../lib/workflowRunLink';

export function Approved({ run }: { run: { workflowId: string; runId: string } }) {
    return <Link to={workflowRunHref(run.workflowId, run.runId)}>Open run</Link>;
}
"""


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding='utf-8')


def load_xss_checker_module():
    """Import the XSS checker module from disk without changing sys.path."""
    spec = importlib.util.spec_from_file_location('check_xss_sinks', XSS_CHECKER_FILE)
    assert spec is not None and spec.loader is not None, 'Expected a module spec for check_xss_sinks.py'
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def describe(module, issues) -> list[str]:
    """Format checker issues the way CI annotates them."""
    return [module.format_error_annotation(issue) for issue in issues]


def test_run_link_files_pass_xss_guardrail() -> None:
    """Every file behind the run links and the approval notice passes the checker in full."""
    module = load_xss_checker_module()
    for path in (RUN_LINKS_COMPONENT, RUN_NOTICE_COMPONENT, RUN_LINKS_CLIENT, RUN_LINK_BUILDER):
        issues = module.inspect_file(path)
        assert issues == [], describe(module, issues)


def test_run_link_uses_the_reviewed_builder_in_the_link() -> None:
    """The component builds the link with workflowRunHref, which the checker approves."""
    module = load_xss_checker_module()
    component_source = read_text(RUN_LINKS_COMPONENT)
    client_source = read_text(RUN_LINKS_CLIENT)

    assert 'workflowRunHref' in module.TS_SAME_ORIGIN_URL_BUILDERS
    assert "import { workflowRunHref } from '../../lib/workflowRunLink';" in component_source
    assert '<Link to={workflowRunHref(item.run.workflowId, item.run.runId)}' in component_source
    assert 'to={item.href}' not in component_source
    # The parsed item carries the ids the response check accepted, never a prebuilt URL.
    assert 'run: WorkflowRunTarget | null;' in client_source
    assert 'href:' not in client_source


def test_checker_still_flags_a_link_from_a_property() -> None:
    """Approving the builder does not approve links from untraceable values."""
    module = load_xss_checker_module()

    unsafe_issues = module.inspect_source(Path('Synthetic.tsx'), UNSAFE_LINK_SNIPPET)
    assert len(unsafe_issues) == 1, describe(module, unsafe_issues)
    assert module.TS_RULE_JSX_URL_ATTRIBUTE in unsafe_issues[0].message, describe(module, unsafe_issues)
    assert unsafe_issues[0].line == 5, describe(module, unsafe_issues)

    approved_issues = module.inspect_source(Path('Synthetic.tsx'), APPROVED_LINK_SNIPPET)
    assert approved_issues == [], describe(module, approved_issues)


def test_builder_returns_only_the_fixed_workflows_path() -> None:
    """The approval holds only while the builder returns the fixed same-origin path."""
    builder_source = read_text(RUN_LINK_BUILDER)

    assert 'export function workflowRunHref(workflowId: string, runId: string): string {' in builder_source
    assert (
        'const params = new URLSearchParams({ [WORKFLOW_LINK_PARAM]: workflowId, '
        '[WORKFLOW_RUN_LINK_PARAM]: runId });'
    ) in builder_source
    assert 'return `/workspace/workflows?${params}`;' in builder_source


if __name__ == '__main__':
    tests = [
        test_run_link_files_pass_xss_guardrail,
        test_run_link_uses_the_reviewed_builder_in_the_link,
        test_checker_still_flags_a_link_from_a_property,
        test_builder_returns_only_the_fixed_workflows_path,
    ]
    failures = 0
    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print('  passed')
        except AssertionError as error:
            failures += 1
            print(f'  failed: {error}')
    print(f'Results: {len(tests) - failures}/{len(tests)} tests passed')
    sys.exit(1 if failures else 0)
