// test_v2_orchestration_run_progress_status.mjs
// Version: 0.261.306
// Implemented in: 0.261.256
// Executes the real describeRunProgress (lib/orchestrationPlan.ts), which writes the running plan
// card's status line. While a plan runs, the card is the only progress indicator: the streaming
// bubble no longer draws "Thinking" beside it. The line therefore says what the run is doing in
// words, not just a role label: starting, the kind of work and title of the running step, waiting,
// or preparing the answer once every step has settled. A plan waiting for a quick saved workflow it
// started (6c) shows the server's own line for that step, which names the workflow and the bound.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

// The repository resolver must be registered before extensionless TypeScript imports load.
const { describeRunProgress } = await import('../application/v2_ui/src/lib/orchestrationPlan.ts');

/** A plan step with only the fields the status line reads. */
function step(stepId, { title = `Step ${stepId}`, role = 'reason', enabled = true, capabilityId = null } = {}) {
    return { step_id: stepId, title, role, enabled, capability_id: capabilityId };
}

/**
 * A step runtime map, shaped as orchestration_step frames leave it in the store. A status alone
 * has an empty summary; an object is used as it is.
 */
function runtime(statuses) {
    return Object.fromEntries(
        Object.entries(statuses).map(([stepId, value]) => [
            stepId,
            typeof value === 'string' ? { status: value, summary: '' } : value,
        ]),
    );
}

/** The server's line for a waiting saved workflow run step (_waiting_summary). */
const WAITING_LINE = 'Waiting for "Sales digest" to finish (up to 5 min).';

test('a run with no step reported yet is starting', () => {
    const steps = [step('a'), step('b')];
    assert.equal(describeRunProgress(steps, {}), 'Starting');
    assert.equal(describeRunProgress(steps, runtime({ a: 'pending', b: 'pending' })), 'Starting');
});

test('a running step is named by its kind of work and its title', () => {
    const cases = [
        ['gather', 'Search the quarterly reports', 'Gathering: Search the quarterly reports'],
        ['reason', 'Draft candidate names', 'Reasoning: Draft candidate names'],
        ['render', 'Build the comparison chart', 'Rendering: Build the comparison chart'],
    ];
    for (const [role, title, expected] of cases) {
        const steps = [step('a', { role, title })];
        assert.equal(describeRunProgress(steps, runtime({ a: 'running' })), expected, role);
    }
});

test('a running step without a role or a title falls back to what is known', () => {
    assert.equal(
        describeRunProgress([step('a', { role: null, title: 'Draft candidate names' })], runtime({ a: 'running' })),
        'Draft candidate names',
    );
    assert.equal(
        describeRunProgress([step('a', { role: 'reason', title: '   ' })], runtime({ a: 'running' })),
        'Reasoning',
    );
    assert.equal(
        describeRunProgress([step('a', { role: null, title: '' })], runtime({ a: 'running' })),
        'Running',
    );
});

test('the first running step in plan order is named when several run at once', () => {
    const steps = [
        step('a', { role: 'gather', title: 'Search the reports' }),
        step('b', { role: 'gather', title: 'Search the web' }),
    ];
    assert.equal(
        describeRunProgress(steps, runtime({ a: 'running', b: 'running' })),
        'Gathering: Search the reports',
    );
});

test('between two steps there is nothing new to say', () => {
    const steps = [step('a'), step('b')];
    assert.equal(describeRunProgress(steps, runtime({ a: 'completed' })), null);
    assert.equal(describeRunProgress(steps, runtime({ a: 'completed', b: 'pending' })), null);
});

test('once every enabled step has settled the run is preparing the answer', () => {
    const steps = [step('a'), step('b'), step('c'), step('d'), step('e')];
    assert.equal(
        describeRunProgress(steps, runtime({
            a: 'completed', b: 'partial', c: 'skipped', d: 'failed', e: 'cancelled',
        })),
        'Preparing the answer',
    );
    // A run whose only step failed is finishing, not starting.
    assert.equal(describeRunProgress([step('a')], runtime({ a: 'failed' })), 'Preparing the answer');
});

test('disabled steps never run and are ignored', () => {
    const steps = [step('a'), step('b', { enabled: false })];
    assert.equal(describeRunProgress(steps, runtime({ a: 'completed' })), 'Preparing the answer');
    assert.equal(describeRunProgress(steps, runtime({ b: 'running' })), 'Starting');
});

test('a waiting run or step says so, and a running step is named first', () => {
    const steps = [step('a', { title: 'Draft candidate names' }), step('b')];
    assert.equal(describeRunProgress(steps, runtime({ a: 'running' }), true), 'Waiting for results');
    assert.equal(describeRunProgress(steps, runtime({ a: 'completed', b: 'waiting' })), 'Waiting for results');
    assert.equal(
        describeRunProgress(steps, runtime({ a: 'running', b: 'waiting' })),
        'Reasoning: Draft candidate names',
    );
});

test('a plan waiting for a saved workflow it started names the workflow and how long it waits', () => {
    const steps = [
        step('a', { role: 'gather', title: 'Run the sales digest', capabilityId: 'workflow_run' }),
        step('b', { title: 'Compare the totals with the Q3 report' }),
    ];
    // The executor parks the step that reads the run's result as waiting too, with its own line.
    const waiting = runtime({
        a: { status: 'waiting', summary: WAITING_LINE },
        b: { status: 'waiting', summary: 'Waiting for required results.' },
    });
    assert.equal(describeRunProgress(steps, waiting), WAITING_LINE);
    assert.equal(describeRunProgress(steps, waiting, true), WAITING_LINE, 'and while the run itself waits');
});

test('the workflow name is kept exactly as the server wrote it, as one line of text', () => {
    const steps = [step('a', { capabilityId: 'workflow_run' })];
    const hostile = 'Waiting for "<img src=x onerror=alert(1)><script>alert(2)</script>" to finish (up to 5 min).';
    assert.equal(describeRunProgress(steps, runtime({ a: { status: 'waiting', summary: hostile } })), hostile);
    assert.equal(
        describeRunProgress(steps, runtime({
            a: { status: 'waiting', summary: '  Waiting for\n"Sales\tdigest"   to finish (up to 5 min).\n' },
        })),
        WAITING_LINE,
    );
});

test('any other wait, or a run step with nothing to say, still reads "Waiting for results"', () => {
    // A native tabular wait keeps the generic line, whatever its step says.
    const native = [step('a', { capabilityId: 'tabular_analyze' })];
    assert.equal(
        describeRunProgress(native, runtime({ a: { status: 'waiting', summary: 'Waiting for the analysis.' } })),
        'Waiting for results',
    );
    const run = [step('a', { capabilityId: 'workflow_run' })];
    for (const entry of [
        { status: 'waiting', summary: '' },
        { status: 'waiting', summary: ' \n\t ' },
        { status: 'waiting' },
        { status: 'waiting', summary: 42 },
    ]) {
        assert.equal(describeRunProgress(run, { a: entry }), 'Waiting for results', JSON.stringify(entry));
    }
    // Only a run step that is waiting has a waiting line.
    assert.equal(
        describeRunProgress(run, runtime({ a: { status: 'completed', summary: WAITING_LINE } }), true),
        'Waiting for results',
    );
    // A disabled run step never runs, so its line is never used.
    const disabled = [
        step('a', { capabilityId: 'workflow_run', enabled: false }),
        step('b', { capabilityId: 'tabular_analyze' }),
    ];
    assert.equal(
        describeRunProgress(disabled, runtime({ a: { status: 'waiting', summary: WAITING_LINE }, b: 'waiting' })),
        'Waiting for results',
    );
});

test('a running step is still named before a saved workflow the plan is waiting for', () => {
    const steps = [
        step('a', { capabilityId: 'workflow_run' }),
        step('b', { role: 'gather', title: 'Search the Q3 report' }),
    ];
    assert.equal(
        describeRunProgress(steps, runtime({ a: { status: 'waiting', summary: WAITING_LINE }, b: 'running' })),
        'Gathering: Search the Q3 report',
    );
});
