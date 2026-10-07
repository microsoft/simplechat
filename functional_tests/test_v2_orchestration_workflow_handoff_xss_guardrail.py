#!/usr/bin/env python3
# test_v2_orchestration_workflow_handoff_xss_guardrail.py
"""
Functional test for the V2 workflow hand-off card passing the XSS sink guardrail.
Version: 0.261.253
Implemented in: 0.261.281

This test ensures that the files behind the workflow hand-off card under a chat
answer, and the hand-off notice on the plan card, pass scripts/check_xss_sinks.py
the way CI runs it. A hand-off's workflow name, description, task titles, agent
names and scope names are user-controlled, so none of these files renders raw
HTML. The card's two links are built by the reviewed same-origin builders the
checker approves by name, workflowRunHref and workflowProposalLink, so this test
also pins that each builder still returns only the fixed Workflows path. The
hand-off client parses ids, never a URL to link to. MessageList.tsx has one
older finding outside this work, so its hand-off lines are checked on their own,
as CI checks changed lines. Synthetic snippets show that the checker still flags
a link or HTML taken from a hand-off item's own fields.

Refs #1549 and #1543.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
V2_SRC_DIR = ROOT_DIR / 'application' / 'v2_ui' / 'src'
CHAT_COMPONENTS_DIR = V2_SRC_DIR / 'components' / 'chat'
LIB_DIR = V2_SRC_DIR / 'lib'
XSS_CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_xss_sinks.py'

HANDOFF_CARD = CHAT_COMPONENTS_DIR / 'WorkflowHandoffCard.tsx'
HANDOFF_NOTICE = CHAT_COMPONENTS_DIR / 'OrchestrationWorkflowHandoffNotice.tsx'
HANDOFF_CLIENT = LIB_DIR / 'workflowHandoffs.ts'
MESSAGE_LIST = CHAT_COMPONENTS_DIR / 'MessageList.tsx'
PROPOSAL_CLIENT = LIB_DIR / 'workflowProposals.ts'
RUN_LINK_BUILDER = LIB_DIR / 'workflowRunLink.ts'

NEW_FILES = (HANDOFF_CARD, HANDOFF_NOTICE, HANDOFF_CLIENT)

# Changed files with no older findings, so they're checked in full like the new ones.
CLEAN_CHANGED_FILES = (
    CHAT_COMPONENTS_DIR / 'WorkflowRunCard.tsx',
    CHAT_COMPONENTS_DIR / 'OrchestrationPlanCard.tsx',
    CHAT_COMPONENTS_DIR / 'OrchestrationRunView.tsx',
    LIB_DIR / 'orchestrationPlan.ts',
)

RAW_HTML_SINKS = ('dangerouslySetInnerHTML', '.innerHTML', '.outerHTML', 'insertAdjacentHTML', 'document.write')
LINK_ATTRIBUTE_RE = re.compile(r'(?<![\w-])(?:to|href)=\{([^{}]*)\}')
HANDOFF_NAMES = ('WorkflowHandoffCards', 'orchestrationHandedOffWorkflow')

UNSAFE_ITEM_SNIPPET = """
import { Link } from 'react-router-dom';

export function Unsafe({ item }: { item: { workflow_url: string; summary: { description: string }; disclosure: { text: string } } }) {
    return (
        <>
            <Link to={item.workflow_url}>Open workflow</Link>
            <p dangerouslySetInnerHTML={{ __html: item.summary.description }} />
            <a href={item.disclosure.text}>Documents</a>
        </>
    );
}
"""

APPROVED_ITEM_SNIPPET = """
import { Link } from 'react-router-dom';
import { workflowProposalLink } from '../../lib/workflowProposals';
import { workflowRunHref } from '../../lib/workflowRunLink';

export function Approved({ item }: { item: { workflow: { id: string }; run: { id: string }; summary: { description: string } } }) {
    return (
        <>
            <Link to={workflowProposalLink(item.workflow.id)}>Open workflow</Link>
            <Link to={workflowRunHref(item.workflow.id, item.run.id)}>Open run</Link>
            <p>{item.summary.description}</p>
        </>
    );
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


def test_version_includes_the_handoff_card() -> None:
    """The hand-off card ships after 0.261.253."""
    version = assert_app_version_at_least('0.261.253')
    assert version


def test_handoff_files_pass_xss_guardrail() -> None:
    """Every new file, and every changed file with no older findings, passes the checker in full."""
    module = load_xss_checker_module()
    for path in NEW_FILES + CLEAN_CHANGED_FILES:
        assert path.is_file(), f'Missing {path}'
        issues = module.inspect_file(path)
        assert issues == [], describe(module, issues)


def test_message_list_handoff_lines_pass_xss_guardrail() -> None:
    """The lines that import and mount the hand-off card pass the checker, as CI checks changed lines."""
    module = load_xss_checker_module()
    lines = read_text(MESSAGE_LIST).splitlines()
    handoff_lines = {
        number for number, line in enumerate(lines, start=1)
        if any(name in line for name in HANDOFF_NAMES)
    }
    # Two imports, the proposal and run mounts' exclusions, and the hand-off mount's condition and card.
    assert len(handoff_lines) == 6, sorted(handoff_lines)
    mount = max(handoff_lines)
    assert lines[mount - 1].strip().startswith('<WorkflowHandoffCards '), lines[mount - 1]
    # The card's props continue on the next line.
    handoff_lines.add(mount + 1)
    issues = module.inspect_file(MESSAGE_LIST, handoff_lines)
    assert issues == [], describe(module, issues)


def test_handoff_files_render_no_raw_html() -> None:
    """No hand-off file writes HTML, so every server and user string renders as text."""
    for path in NEW_FILES + CLEAN_CHANGED_FILES + (MESSAGE_LIST,):
        source = read_text(path)
        for sink in RAW_HTML_SINKS:
            assert sink not in source, f'{path.name} uses {sink}'


def test_handoff_links_use_reviewed_builders() -> None:
    """The card links to a run through workflowRunHref and to a workflow through workflowProposalLink."""
    module = load_xss_checker_module()
    assert 'workflowRunHref' in module.TS_SAME_ORIGIN_URL_BUILDERS
    assert 'workflowProposalLink' in module.TS_SAME_ORIGIN_URL_BUILDERS

    card_source = read_text(HANDOFF_CARD)
    assert [expression.strip() for expression in LINK_ATTRIBUTE_RE.findall(card_source)] == [
        'workflowRunHref(workflowId, runId)',
        'workflowProposalLink(item.workflow.id)',
    ]
    assert LINK_ATTRIBUTE_RE.findall(read_text(HANDOFF_NOTICE)) == []
    assert "import { workflowRunHref } from '../../lib/workflowRunLink';" in card_source
    assert "import { workflowProposalLink } from '../../lib/workflowProposals';" in card_source


def test_link_builders_return_only_the_fixed_workflows_path() -> None:
    """The checker trusts both builders by name, so each must still return a fixed same-origin path."""
    proposal_source = read_text(PROPOSAL_CLIENT)
    assert (
        'export function workflowProposalLink(workflowId: string): string {\n'
        '    return `/workspace/workflows?${new URLSearchParams({ [WORKFLOW_LINK_PARAM]: workflowId })}`;\n'
        '}\n'
    ) in proposal_source
    assert "import { WORKFLOW_LINK_PARAM } from './workflowRunLink';" in proposal_source

    builder_source = read_text(RUN_LINK_BUILDER)
    assert (
        'export function workflowRunHref(workflowId: string, runId: string, '
        'scope: WorkflowScope = PERSONAL_SCOPE): string {'
    ) in builder_source
    assert 'return `/workspace/workflows?${params}`;' in builder_source


def test_handoff_client_carries_ids_not_urls() -> None:
    """A parsed hand-off names its workflow and run by id; nothing the server sends becomes a link."""
    source = read_text(HANDOFF_CLIENT)
    assert 'href' not in source, 'workflowHandoffs.ts carries an href'
    assert 'link_url' not in source, 'workflowHandoffs.ts reads a link_url'
    assert 'workflow_url' not in source, 'workflowHandoffs.ts reads a workflow_url'
    assert 'run_url' not in source, 'workflowHandoffs.ts reads a run_url'


def test_checker_still_flags_links_and_html_from_a_handoff_item() -> None:
    """Approving the builders doesn't approve a URL or HTML from a hand-off item's own fields."""
    module = load_xss_checker_module()

    unsafe_issues = module.inspect_source(Path('Synthetic.tsx'), UNSAFE_ITEM_SNIPPET)
    assert [issue.line for issue in unsafe_issues] == [7, 8, 9], describe(module, unsafe_issues)
    assert module.TS_RULE_JSX_URL_ATTRIBUTE in unsafe_issues[0].message, describe(module, unsafe_issues)
    assert module.TS_RULE_DANGEROUS_INNER_HTML in unsafe_issues[1].message, describe(module, unsafe_issues)
    assert module.TS_RULE_JSX_URL_ATTRIBUTE in unsafe_issues[2].message, describe(module, unsafe_issues)

    approved_issues = module.inspect_source(Path('Synthetic.tsx'), APPROVED_ITEM_SNIPPET)
    assert approved_issues == [], describe(module, approved_issues)


if __name__ == '__main__':
    # Run through pytest, which rewrites these asserts so they still run under python -O.
    raise SystemExit(pytest.main([__file__, '-q']))
