// test_v2_workflow_proposal_alerts.mjs
// Version: 0.261.315
// Implemented in: 0.261.315
// Validates quiet legacy summaries and native alert review contracts without network access.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const { parseWorkflowProposalList } = await import('../application/v2_ui/src/lib/workflowProposals.ts');

const rule = {
    name: 'Active fault', enabled: true, condition: 'An actual active fault was reported.',
    scope: 'Read telemetry', severity: 'critical', delivery: 'popup',
    require_acknowledgment: true, sound: 'repeat', size: 'large',
};

function response(alerts) {
    return {
        run_id: 'run-1',
        proposals: [{
            proposal_id: 'proposal-1', step_id: 'propose', state: 'pending', reason: null,
            created_at: null, expires_at: null,
            actions: { accept: true, edit: true, deny: true, create_again: false, open_workflow: false },
            summary: {
                name: 'Monitor', description: '', trigger_type: 'manual', schedule_label: '',
                time_zone: 'UTC', runs_per_month: { kind: 'manual', value: null },
                tasks: [], file_sync_sources: [], alerts, durable: true,
            },
            similar_workflows: [], workflow: null,
            m365: { required: false, can_send: false, run_as: 'none', sources: [], connected: null, approval_state: null },
        }],
    };
}

test('legacy quiet summaries and explicit native rules retain all review fields', () => {
    for (const alerts of [
        { mode: 'every_run', severity: 'info' },
        { mode: 'failures_only', severity: 'low' },
        { mode: 'rules', rules: [rule] },
    ]) {
        const parsed = parseWorkflowProposalList(response(alerts), 'run-1');
        assert.deepEqual(parsed.proposals[0].summary.alerts, alerts);
    }
});

test('unrenderable or incompatible alert options fail closed', () => {
    for (const alerts of [
        { mode: 'rules', rules: [] },
        { mode: 'rules', rules: Array(21).fill(rule) },
        ...[
            { sound: 'continuous' }, { size: 'huge' }, { severity: 'maximum' },
            { require_acknowledgment: 'true' }, { delivery: 'notify_only' },
            { require_acknowledgment: false }, { condition: null },
        ].map(change => ({ mode: 'rules', rules: [{ ...rule, ...change }] })),
    ]) {
        assert.throws(() => parseWorkflowProposalList(response(alerts), 'run-1'), /invalid response/);
    }
});
