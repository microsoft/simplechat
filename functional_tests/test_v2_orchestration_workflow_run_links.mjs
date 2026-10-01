// test_v2_orchestration_workflow_run_links.mjs
// Version: 0.261.212
// Implemented in: 0.261.212
// Executes the V2 run links under an answer whose plan started saved workflows: a link opens the
// Workflows page with that workflow's run history open and the run expanded, a link response is
// checked before anything is shown and fails closed on the wrong shape, an unavailable run is
// never linked and always says why in fixed text, names stay plain data, and the links mount
// only for an answer whose run completed a workflow_run step.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('Run link helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const { readWorkflowRunLink, workflowRunHref } = await import('../application/v2_ui/src/lib/workflowRunLink.ts');
const {
    WORKFLOW_RUN_LINK_STATES,
    WORKFLOW_RUN_LINKS_INVALID_RESPONSE,
    orchestrationStartedWorkflow,
    parseWorkflowRunLinkList,
    workflowRunDisplayName,
    workflowRunReasonText,
    workflowRunStateLabel,
} = await import('../application/v2_ui/src/lib/orchestrationWorkflowRuns.ts');

const RUN_ID = 'run-1';
const HOSTILE_NAME = '<img src=x onerror="alert(1)"> Digest & {{7*7}} [link](https://evil.example/)';
// Every reason the link route returns (functions_orchestration_workflow_run_links).
const SERVER_REASONS = [
    'workflow_deleted', 'workflow_run_missing', 'workflow_runs_disabled', 'workflow_role_required',
    'workflow_shared_conversation', 'content_review',
];
const FALLBACK = 'This workflow run is not available.';

function started(stepId, state = 'queued', overrides = {}) {
    return {
        step_id: stepId, name: 'Weekly digest', state, reason: null,
        workflow_id: `wf-${stepId}`, workflow_run_id: `wr-${stepId}`, ...overrides,
    };
}

function unavailable(stepId, reason = 'workflow_deleted', overrides = {}) {
    return {
        step_id: stepId, name: '', state: 'unavailable', reason, workflow_id: null, workflow_run_id: null,
        ...overrides,
    };
}

function response(items, runId = RUN_ID) {
    return { run_id: runId, workflow_runs: items };
}

test('a run link opens that workflow with the run expanded, whatever its ids contain', () => {
    const href = workflowRunHref('wf 1&x=2', 'run/2?y#z');
    assert.equal(href, '/workspace/workflows?workflow_id=wf+1%26x%3D2&run_id=run%2F2%3Fy%23z');
    const url = new URL(href, 'https://simplechat.example');
    assert.equal(url.pathname, '/workspace/workflows');
    assert.deepEqual(readWorkflowRunLink(url.search), { workflowId: 'wf 1&x=2', runId: 'run/2?y#z' });
});

test('every started state links its run, and an unavailable run says why without a link', () => {
    const states = WORKFLOW_RUN_LINK_STATES.filter((state) => state !== 'unavailable');
    const items = [...states.map((state, index) => started(`run_${index}`, state)), unavailable('gone')];
    const list = parseWorkflowRunLinkList(response(items), RUN_ID);
    assert.equal(list.run_id, RUN_ID);
    assert.deepEqual(list.workflow_runs.map((item) => item.state), [...states, 'unavailable']);
    list.workflow_runs.slice(0, -1).forEach((item, index) => {
        assert.equal(item.reason, null);
        assert.equal(item.href, workflowRunHref(`wf-run_${index}`, `wr-run_${index}`));
    });
    assert.deepEqual(list.workflow_runs.at(-1), {
        step_id: 'gone', name: '', state: 'unavailable', reason: 'workflow_deleted', href: null,
    });
    // The parsed links keep no raw ids beside the link itself.
    for (const item of list.workflow_runs) {
        assert.deepEqual(Object.keys(item).sort(), ['href', 'name', 'reason', 'state', 'step_id']);
    }
});

test('a name is kept as data, never trimmed into markup', () => {
    const list = parseWorkflowRunLinkList(response([started('run_digest', 'running', { name: HOSTILE_NAME })]), RUN_ID);
    assert.equal(list.workflow_runs[0].name, HOSTILE_NAME);
    assert.equal(workflowRunDisplayName(list.workflow_runs[0]), HOSTILE_NAME);
    assert.equal(workflowRunDisplayName({ name: '   ' }), 'Saved workflow');
    assert.equal(workflowRunDisplayName({ name: '' }), 'Saved workflow');
});

test('a response of the wrong shape fails closed', () => {
    const cases = [
        null, [], 'links', response([], 'run-2'), { run_id: RUN_ID }, { run_id: RUN_ID, workflow_runs: {} },
        response(['not a link']),
        response([started('a', 'finished')]),
        response([started('a', 'queued', { state: undefined })]),
        response([started('a', 'queued', { reason: 'workflow_deleted' })]),
        response([started('a', 'queued', { workflow_id: null })]),
        response([started('a', 'queued', { workflow_id: '   ' })]),
        response([started('a', 'queued', { workflow_run_id: '' })]),
        response([started('a', 'queued', { workflow_run_id: 7 })]),
        response([started('a', 'queued', { name: null })]),
        response([started('a', 'queued', { step_id: '' })]),
        response([started('a', 'queued', { step_id: 7 })]),
        response([unavailable('a', 'workflow_deleted', { workflow_id: 'wf-a' })]),
        response([unavailable('a', 'workflow_deleted', { workflow_run_id: 'wr-a' })]),
        response([unavailable('a', 'workflow_deleted', { workflow_id: undefined })]),
        response([unavailable('a', null)]),
        response([unavailable('a', '  ')]),
        response([started('a'), started('a', 'running')]),
    ];
    for (const value of cases) {
        assert.throws(() => parseWorkflowRunLinkList(value, RUN_ID), { message: WORKFLOW_RUN_LINKS_INVALID_RESPONSE });
    }
});

test('every reason the route returns has its own fixed sentence, and anything else reads as unavailable', () => {
    const texts = SERVER_REASONS.map((reason) => workflowRunReasonText(reason));
    texts.forEach((text) => assert.notEqual(text, FALLBACK));
    assert.equal(new Set(texts).size, SERVER_REASONS.length);
    for (const reason of [null, '', 'a_reason_added_later', '__proto__', 'toString', 'constructor', HOSTILE_NAME]) {
        assert.equal(workflowRunReasonText(reason), FALLBACK, String(reason));
    }
});

test('every state has a label', () => {
    const labels = WORKFLOW_RUN_LINK_STATES.map((state) => workflowRunStateLabel(state));
    labels.forEach((label) => assert.ok(typeof label === 'string' && label.trim()));
    assert.equal(new Set(labels).size, WORKFLOW_RUN_LINK_STATES.length);
});

test('the links mount only for an answer whose run completed a workflow_run step', () => {
    assert.equal(orchestrationStartedWorkflow({ plan_summary: { capabilities_used: ['compose', 'workflow_run'] } }), true);
    for (const metadata of [
        undefined, null, 'workflow_run', [], {}, { plan_summary: null },
        { plan_summary: { capabilities_used: 'workflow_run' } },
        { plan_summary: { capabilities_used: ['workflow_propose', 'compose'] } },
        { plan_summary: { capabilities_used: [] } },
        { capabilities_used: ['workflow_run'] },
    ]) {
        assert.equal(orchestrationStartedWorkflow(metadata), false, JSON.stringify(metadata));
    }
});
