// test_v2_agent_tabular_progress_cards.mjs
// Version: 0.261.318
// Implemented in: 0.261.318
// Agent and tabular activity stays classified and available as reasoning, but neither lane
// draws a duplicate progress card in live or saved V2 responses.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

// Register the repository resolver before loading TypeScript application modules.
const { buildLaneProgress } = await import('../application/v2_ui/src/lib/activityLanes.ts');

const markers = [
    ['agent hand-off text', 'agent', { content: 'Sending to agent researcher' }],
    ['agent step type', 'agent', { step_type: 'agent_tool_call', content: 'Calling search.' }],
    ['agent activity lane', 'agent', {
        content: 'Calling search.',
        activity: { lane_key: 'agent', activity_key: 'search', title: 'Search', status: 'running' },
    }],
    ['tabular step type', 'tabular', { step_type: 'tabular_analysis', content: 'Reading a workbook.' }],
    ['tabular tool kind', 'tabular', {
        activity: { kind: 'tabular_tool_invocation', activity_key: 'read', status: 'running' },
    }],
    ['tabular post-processing kind', 'tabular', {
        activity: { kind: 'tabular_post_processing', activity_key: 'export', status: 'running' },
    }],
    ['tabular activity lane', 'tabular', { activity: { lane_key: 'tabular', status: 'running' } }],
    ['tabular plugin', 'tabular', {
        activity: { plugin_name: 'TabularProcessingPlugin', status: 'running' },
    }],
];

for (const [name, lane, thought] of markers) {
    test(`${name} claims its lane without drawing a live or saved card`, () => {
        for (const live of [true, false]) {
            const thoughts = [structuredClone(thought)];
            const original = structuredClone(thoughts);
            const progress = buildLaneProgress(thoughts, { live });
            assert.ok(progress);
            assert.equal(progress.lane.key, lane);
            assert.equal(progress.lane.showsCard, false);
            assert.deepEqual(thoughts, original, 'Reasoning content must not be removed or mutated.');
        }
    });
}

for (const lane of ['agent', 'tabular']) {
    for (const status of ['running', 'completed', 'failed']) {
        test(`${lane} ${status} activity never brings back a progress card`, () => {
            const thoughts = [
                { step_type: 'agent_tool_call', content: 'Sending to agent analyst' },
                {
                    step_type: lane === 'agent' ? 'agent_tool_call' : 'tabular_analysis',
                    content: status === 'failed' ? 'The tool could not finish.' : 'Reading evidence.',
                    activity: {
                        activity_key: 'read',
                        lane_key: lane,
                        kind: lane === 'tabular' ? 'tabular_tool_invocation' : 'agent_tool_invocation',
                        title: 'Read evidence',
                        status,
                    },
                },
            ];
            for (const live of [true, false]) {
                const progress = buildLaneProgress(thoughts, { live });
                assert.ok(progress);
                assert.equal(progress.lane.key, lane, 'Tabular must still supersede the agent hand-off.');
                assert.equal(progress.lane.showsCard, false);
                assert.equal(progress.failedCount, status === 'failed' ? 1 : 0);
            }

            const answered = buildLaneProgress([
                ...thoughts,
                { step_type: 'generation', content: 'Agent responded with the answer.' },
            ]);
            assert.ok(answered);
            assert.equal(answered.lane.key, lane);
            assert.equal(answered.completed, true);
            assert.equal(answered.lane.showsCard, false);
        });
    }
}
