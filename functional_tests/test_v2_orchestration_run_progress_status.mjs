// test_v2_orchestration_run_progress_status.mjs
// Version: 0.261.253
// Implemented in: 0.261.253
// Executes the real describeRunProgress (lib/orchestrationPlan.ts), which writes the running plan
// card's status line. While a plan runs, the card is the only progress indicator: the streaming
// bubble no longer draws "Thinking" beside it. The line therefore says what the run is doing in
// words, not just a role label: starting, the kind of work and title of the running step, waiting,
// or preparing the answer once every step has settled.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

// The repository resolver must be registered before extensionless TypeScript imports load.
const { describeRunProgress } = await import('../application/v2_ui/src/lib/orchestrationPlan.ts');

/** A plan step with only the fields the status line reads. */
function step(stepId, { title = `Step ${stepId}`, role = 'reason', enabled = true } = {}) {
    return { step_id: stepId, title, role, enabled };
}

/** A step runtime map, shaped as orchestration_step frames leave it in the store. */
function runtime(statuses) {
    return Object.fromEntries(
        Object.entries(statuses).map(([stepId, status]) => [stepId, { status, summary: '' }]),
    );
}

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
