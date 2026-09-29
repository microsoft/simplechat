// test_v2_orchestration_progress_lane.mjs
// Version: 0.261.204
// Implemented in: 0.261.204
// Executes the real activity-lane fold (lib/activityLanes.ts) over the reasoning steps an
// orchestrated turn produces. The orchestration lane still claims those steps, so they are never
// counted as agent or tabular work, but it draws no progress card: the plan card and the reasoning
// toggle already show that progress. Tabular and agent work keep their cards.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

// The repository resolver must be registered before extensionless TypeScript imports load.
const { buildLaneProgress } = await import('../application/v2_ui/src/lib/activityLanes.ts');

/** A planner reasoning step, shaped as build_planning_thought serializes it. */
function planningThought(content, status = 'running') {
    return {
        step_type: 'orchestration_planning',
        content,
        step_index: 1,
        activity: {
            lane_key: 'orchestration', kind: 'orchestration_planning', title: 'Building a plan', status,
        },
    };
}

/** A reasoning-setting notice, shaped as build_reasoning_adjustment_event serializes it. */
function adjustmentThought() {
    return {
        step_type: 'orchestration_planning',
        content: 'Reasoning adjusted from High to Medium for gpt-5.4.',
        step_index: 0,
        activity: {
            lane_key: 'orchestration', kind: 'orchestration_planning',
            title: 'Reasoning setting adjusted', status: 'completed',
        },
    };
}

/** A workbook tool call, shaped as build_tabular_activity_payload reports it. */
function tabularThought(status = 'running') {
    return {
        step_type: 'tabular_analysis',
        content: 'Reading the quarterly workbook.',
        activity: {
            activity_key: 'call-1', kind: 'tabular_tool_invocation', title: 'describe_tabular_file',
            status, state: status, lane_key: 'tabular', plugin_name: 'TabularProcessingPlugin',
        },
    };
}

test('planning steps belong to the orchestration lane, which draws no card', () => {
    for (const live of [true, false]) {
        const progress = buildLaneProgress([planningThought('Deciding what this question needs.')], { live });
        assert.equal(progress?.lane.key, 'orchestration');
        assert.equal(progress.lane.showsCard, false);
    }
    const planned = buildLaneProgress([
        planningThought('Deciding what this question needs.'),
        planningThought('Plan ready.', 'completed'),
    ]);
    assert.equal(planned?.lane.key, 'orchestration');
    assert.equal(planned.lane.showsCard, false);
});

test('run-time notices stay in the card-less orchestration lane', () => {
    const progress = buildLaneProgress(
        [adjustmentThought(), planningThought('Saved facts could not be searched.')],
        { live: true },
    );
    assert.equal(progress?.lane.key, 'orchestration');
    assert.equal(progress.lane.showsCard, false);
});

test('orchestration step types are claimed without an activity payload', () => {
    const stepTypes = [
        'orchestration_triage', 'orchestration_planning', 'orchestration_step', 'orchestration_synthesis',
    ];
    for (const stepType of stepTypes) {
        const progress = buildLaneProgress([{ step_type: stepType, content: 'Working.' }]);
        assert.equal(progress?.lane.key, 'orchestration', stepType);
        assert.equal(progress.lane.showsCard, false, stepType);
    }
});

test('an agent hand-off inside an orchestrated turn does not bring back a card', () => {
    const progress = buildLaneProgress([
        planningThought('Deciding what this question needs.'),
        { step_type: 'agent_tool_call', content: 'Sending to agent researcher' },
    ], { live: true });
    assert.equal(progress?.lane.key, 'orchestration');
    assert.equal(progress.lane.showsCard, false);
});

test('tabular and agent work keep their progress cards', () => {
    const tabular = buildLaneProgress([tabularThought()], { live: true });
    assert.equal(tabular?.lane.key, 'tabular');
    assert.equal(tabular.lane.showsCard, true);

    const handedOff = buildLaneProgress([
        { step_type: 'agent_tool_call', content: 'Sending to agent analyst' },
        tabularThought('completed'),
    ]);
    assert.equal(handedOff?.lane.key, 'tabular');
    assert.equal(handedOff.lane.showsCard, true);

    const agent = buildLaneProgress(
        [{ step_type: 'agent_tool_call', content: 'Sending to agent researcher' }],
        { live: true },
    );
    assert.equal(agent?.lane.key, 'agent');
    assert.equal(agent.lane.showsCard, true);
});

test('ordinary reasoning still forms no lane at all', () => {
    assert.equal(buildLaneProgress([{ step_type: 'generation', content: 'Thinking' }]), null);
    assert.equal(buildLaneProgress([]), null);
    assert.equal(buildLaneProgress(undefined), null);
});
