#!/usr/bin/env python3
# test_v2_workflow_run_tracking_xss_guardrail.py
"""
Functional test for the V2 chat workflow run tracking passing the XSS sink guardrail.
Version: 0.261.249
Implemented in: 0.261.249

This test ensures that the files behind a chat-started workflow run in V2 pass
scripts/check_xss_sinks.py in full: the run card under a plan's answer, the
app-shell tracker and its store, the running tag in the chat list, the footer on
a delivered message, and the next and last run on the recurring workflow card.
None of the changed V2 files renders raw HTML, every link they render is built
by the reviewed workflowRunHref builder or is the fixed M365_CONNECT_HREF path,
and the run status rows carry ids, never a URL. The checker approves an
upper-case constant by its name alone, so the constant's value is checked here
too. App.tsx and MessageList.tsx are checked by CI on changed lines only,
because each has one older finding outside this work. Synthetic snippets show
that the checker still flags a link or HTML taken from a status row's own
fields.
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
STORES_DIR = V2_SRC_DIR / 'stores'
XSS_CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_xss_sinks.py'

RUN_CARD = CHAT_COMPONENTS_DIR / 'WorkflowRunCard.tsx'
DELIVERY_FOOTER = CHAT_COMPONENTS_DIR / 'WorkflowDeliveryFooter.tsx'
RUNNING_TAG = CHAT_COMPONENTS_DIR / 'WorkflowRunningTag.tsx'
PROPOSAL_RUN_SUMMARY = CHAT_COMPONENTS_DIR / 'WorkflowProposalRunSummary.tsx'
RUN_LINKS = CHAT_COMPONENTS_DIR / 'WorkflowRunLinks.tsx'
PROPOSAL_CARD = CHAT_COMPONENTS_DIR / 'WorkflowProposalCard.tsx'
M365_LINKS = LIB_DIR / 'm365Links.ts'
NOTIFICATION_LINKS = LIB_DIR / 'notificationLinks.ts'
RUN_STATUS = LIB_DIR / 'workflowRunStatus.ts'
DELIVERY = LIB_DIR / 'workflowDelivery.ts'
TRACKER = LIB_DIR / 'workflowRunTracker.ts'
TRACKER_STORE = STORES_DIR / 'workflowRunTrackerStore.ts'

NEW_FILES = (
    RUN_CARD,
    DELIVERY_FOOTER,
    RUNNING_TAG,
    PROPOSAL_RUN_SUMMARY,
    M365_LINKS,
    LIB_DIR / 'useFocusFallback.ts',
    LIB_DIR / 'useWorkflowRunAction.ts',
    LIB_DIR / 'useWorkflowRunTracker.ts',
    DELIVERY,
    LIB_DIR / 'workflowRunActions.ts',
    RUN_STATUS,
    TRACKER,
    TRACKER_STORE,
)

# Changed files with no older findings, so they're checked in full like the new ones.
CLEAN_CHANGED_FILES = (
    CHAT_COMPONENTS_DIR / 'ConversationRail.tsx',
    CHAT_COMPONENTS_DIR / 'MessageActions.tsx',
    PROPOSAL_CARD,
    RUN_LINKS,
    NOTIFICATION_LINKS,
    LIB_DIR / 'notifications.ts',
    LIB_DIR / 'workflowAlertNotices.ts',
    LIB_DIR / 'workflowEditor.ts',
    LIB_DIR / 'workflowRunLink.ts',
    STORES_DIR / 'chatStore.ts',
)

# Each has one older finding outside this work, so CI checks their changed lines instead.
CHANGED_LINES_ONLY_FILES = (
    V2_SRC_DIR / 'App.tsx',
    CHAT_COMPONENTS_DIR / 'MessageList.tsx',
)

LINK_COMPONENTS = (RUN_CARD, DELIVERY_FOOTER, RUNNING_TAG, PROPOSAL_RUN_SUMMARY, RUN_LINKS)
RAW_HTML_SINKS = ('dangerouslySetInnerHTML', '.innerHTML', '.outerHTML', 'insertAdjacentHTML', 'document.write')
LINK_ATTRIBUTE_RE = re.compile(r'(?<![\w-])(?:to|href)=\{([^{}]*)\}')
APPROVED_LINK_RE = re.compile(r'^(?:workflowRunHref\([^()]*\)|M365_CONNECT_HREF)$')

UNSAFE_ROW_SNIPPET = """
import { Link } from 'react-router-dom';

export function Unsafe({ row }: { row: { open_run_url: string; reconnect_url: string; error: string } }) {
    return (
        <>
            <Link to={row.open_run_url}>Open run</Link>
            <a href={row.reconnect_url}>Reconnect Microsoft 365</a>
            <p dangerouslySetInnerHTML={{ __html: row.error }} />
        </>
    );
}
"""

APPROVED_ROW_SNIPPET = """
import { Link } from 'react-router-dom';
import { M365_CONNECT_HREF } from '../../lib/m365Links';
import { workflowRunHref } from '../../lib/workflowRunLink';

export function Approved({ row }: { row: { workflow_id: string; run_id: string; error: string } }) {
    return (
        <>
            <Link to={workflowRunHref(row.workflow_id, row.run_id)}>Open run</Link>
            <a href={M365_CONNECT_HREF}>Reconnect Microsoft 365</a>
            <p>{row.error}</p>
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


def test_version_is_at_least_the_tracking_release() -> None:
    """The run tracking ships in 0.261.249."""
    version = assert_app_version_at_least('0.261.249')
    assert version


def test_run_tracking_files_pass_xss_guardrail() -> None:
    """Every new file, and every changed file with no older findings, passes the checker in full."""
    module = load_xss_checker_module()
    for path in NEW_FILES + CLEAN_CHANGED_FILES:
        assert path.is_file(), f'Missing {path}'
        issues = module.inspect_file(path)
        assert issues == [], describe(module, issues)


def test_run_tracking_files_render_no_raw_html() -> None:
    """No changed V2 file writes HTML, so every server string renders as text."""
    for path in NEW_FILES + CLEAN_CHANGED_FILES + CHANGED_LINES_ONLY_FILES:
        source = read_text(path)
        for sink in RAW_HTML_SINKS:
            assert sink not in source, f'{path.name} uses {sink}'


def test_run_tracking_links_use_reviewed_builders() -> None:
    """Each link is workflowRunHref over a run's ids or the fixed Microsoft 365 path."""
    module = load_xss_checker_module()
    assert 'workflowRunHref' in module.TS_SAME_ORIGIN_URL_BUILDERS

    found = {}
    for path in LINK_COMPONENTS:
        expressions = LINK_ATTRIBUTE_RE.findall(read_text(path))
        for expression in expressions:
            assert APPROVED_LINK_RE.match(expression.strip()), f'{path.name} links to {expression!r}'
        found[path.name] = [expression.strip() for expression in expressions]

    # The scan finds the links it is meant to check.
    assert found[RUN_CARD.name] == [
        'workflowRunHref(workflowId, runId)',
        'workflowRunHref(run.workflowId, run.runId)',
        'M365_CONNECT_HREF',
    ]
    assert found[DELIVERY_FOOTER.name] == ['workflowRunHref(delivery.workflow_id, delivery.run_id)']
    assert found[PROPOSAL_RUN_SUMMARY.name] == ['workflowRunHref(workflowId, latestResultRunId)']
    assert found[RUNNING_TAG.name] == []
    assert found[RUN_LINKS.name] == ['workflowRunHref(item.run.workflowId, item.run.runId)']

    builder_import = "import { workflowRunHref } from '../../lib/workflowRunLink';"
    constant_import = "import { M365_CONNECT_HREF } from '../../lib/m365Links';"
    for path in (RUN_CARD, DELIVERY_FOOTER, PROPOSAL_RUN_SUMMARY, RUN_LINKS):
        assert builder_import in read_text(path), f'{path.name} does not import workflowRunHref'
    # The proposal card shares the run card's reconnect path instead of keeping its own copy.
    for path in (RUN_CARD, PROPOSAL_CARD):
        source = read_text(path)
        assert constant_import in source, f'{path.name} does not import M365_CONNECT_HREF'
        assert 'const M365_CONNECT_HREF' not in source, f'{path.name} defines its own M365_CONNECT_HREF'


def test_fixed_link_values_stay_same_origin() -> None:
    """The constant the checker trusts by name is a fixed same-origin path, and notices reuse the builder."""
    m365_source = read_text(M365_LINKS)
    assert "export const M365_CONNECT_HREF = '/profile?tab=settings#m365-connection-status';" in m365_source
    assert m365_source.count('export ') == 1

    notification_source = read_text(NOTIFICATION_LINKS)
    assert "import { workflowRunHref } from './workflowRunLink';" in notification_source
    assert '    const workflow = safeId(workflowId);\n' in notification_source
    assert '    const run = safeId(runId);\n' in notification_source
    assert "(scope.type !== 'personal' && scope.type !== 'group')" in notification_source
    assert 'return workflowRunHref(workflow, run, scope);' in notification_source

    # Status rows, delivery metadata and tracker state carry ids, never a URL to render.
    for path in (RUN_STATUS, DELIVERY, TRACKER, TRACKER_STORE):
        source = read_text(path)
        assert 'href' not in source, f'{path.name} carries an href'
        assert 'link_url' not in source, f'{path.name} reads a link_url'


def test_checker_still_flags_links_and_html_from_a_status_row() -> None:
    """Approving the builder and the constant doesn't approve a URL or HTML from the server."""
    module = load_xss_checker_module()

    unsafe_issues = module.inspect_source(Path('Synthetic.tsx'), UNSAFE_ROW_SNIPPET)
    assert [issue.line for issue in unsafe_issues] == [7, 8, 9], describe(module, unsafe_issues)
    assert module.TS_RULE_JSX_URL_ATTRIBUTE in unsafe_issues[0].message, describe(module, unsafe_issues)
    assert module.TS_RULE_JSX_URL_ATTRIBUTE in unsafe_issues[1].message, describe(module, unsafe_issues)
    assert module.TS_RULE_DANGEROUS_INNER_HTML in unsafe_issues[2].message, describe(module, unsafe_issues)

    approved_issues = module.inspect_source(Path('Synthetic.tsx'), APPROVED_ROW_SNIPPET)
    assert approved_issues == [], describe(module, approved_issues)


if __name__ == '__main__':
    # Run through pytest, which rewrites these asserts so they still run under python -O.
    raise SystemExit(pytest.main([__file__, '-q']))
