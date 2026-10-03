// test_v2_workflow_proposal_merge.mjs
// Version: 0.261.220
// Implemented in: 0.261.220
// Checks that the workflow proposal card's response parser accepts a proposed merge task, fails
// closed on a merge it cannot describe, and words each merge as code that runs no model.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('Workflow proposal parsing must not make network requests.');
};

const {
    WORKFLOW_PROPOSAL_INVALID_RESPONSE,
    parseWorkflowProposalList,
    workflowProposalMergeText,
} = await import('../application/v2_ui/src/lib/workflowProposals.ts');

function statusResponse(task) {
    return {
        run_id: 'run-1',
        proposals: [{
            proposal_id: 'proposal-1',
            step_id: 'propose',
            state: 'pending',
            reason: null,
            created_at: '2026-09-28T12:00:00+00:00',
            expires_at: '2026-10-12T12:00:00+00:00',
            actions: { accept: true, edit: true, deny: true, create_again: false, open_workflow: false },
            summary: {
                name: 'Regional sales merge',
                description: '',
                trigger_type: 'calendar',
                schedule_label: 'Mondays 08:00 America/New_York',
                time_zone: 'America/New_York',
                runs_per_month: { kind: 'count', value: 4 },
                tasks: [task],
                file_sync_sources: [],
                alerts: { mode: 'failures_only', severity: 'low' },
                durable: true,
            },
            similar_workflows: [],
            m365: { required: false, can_send: false, run_as: 'none', sources: [], connected: null, approval_state: null },
            workflow: null,
        }],
    };
}

const baseTask = {
    title: 'Merge regional sales',
    runner: 'model',
    agent_name: '',
    action_kinds: [],
    requested_actions: [],
    inputs: ['north.csv', 'south.xlsx'],
    instructions: 'Merge the regional sales files.',
};

test('a proposed merge task keeps which files it merges and what it creates', () => {
    const parsed = parseWorkflowProposalList(
        statusResponse({ ...baseTask, merge: { files: 'inputs', output_format: 'xlsx' } }),
        'run-1',
    );
    const [task] = parsed.proposals[0].summary.tasks;
    assert.deepEqual(task.merge, { files: 'inputs', output_format: 'xlsx' });
    assert.deepEqual(task.inputs, ['north.csv', 'south.xlsx']);
});

test('a task without a merge is parsed exactly as before', () => {
    const parsed = parseWorkflowProposalList(statusResponse(baseTask), 'run-1');
    const [task] = parsed.proposals[0].summary.tasks;
    assert.equal('merge' in task, false);
});

test('a merge the card cannot describe fails closed', () => {
    for (const merge of [
        'inputs',
        { files: 'everything', output_format: 'csv' },
        { files: 'all', output_format: 'pdf' },
        { files: 'all' },
    ]) {
        assert.throws(
            () => parseWorkflowProposalList(statusResponse({ ...baseTask, merge }), 'run-1'),
            new RegExp(WORKFLOW_PROPOSAL_INVALID_RESPONSE.replace('.', '\\.')),
        );
    }
});

test('each merge is described as code that runs no model', () => {
    assert.equal(
        workflowProposalMergeText({ merge: { files: 'inputs', output_format: 'xlsx' } }),
        'Merges the input files below, in order, into one Excel file with code. No model runs.',
    );
    assert.equal(
        workflowProposalMergeText({ merge: { files: 'changed', output_format: 'csv' } }),
        'Merges the files each sync adds or changes into one CSV file with code. No model runs.',
    );
    assert.equal(
        workflowProposalMergeText({ merge: { files: 'all', output_format: 'csv' } }),
        'Merges every CSV and Excel file in your personal workspace into one CSV file with code. No model runs.',
    );
    assert.equal(
        workflowProposalMergeText({ merge: { files: 'recent', output_format: 'xlsx' } }),
        'Merges the CSV and Excel files added or changed recently in your personal workspace into one Excel file '
            + 'with code. No model runs.',
    );
    assert.equal(workflowProposalMergeText({}), '');
});
