// test_v2_orchestration_streaming_surface.mjs
// Version: 0.261.254
// Implemented in: 0.261.254
// Executes the real chat store, orchestration store and orchestration controller to check who
// owns the streaming surface during an orchestrated turn. While a plan runs, the plan card is the
// only progress indicator, so the streaming bubble needs to know that the surface belongs to a
// run, not just that something is streaming. The planner takes the surface as `planning`, an
// approved run takes it as `running`, and every chat stream takes it as null. The phase follows
// the turn when the reader leaves and returns, and when the server re-keys the conversation. A
// chat reply sent while a run waits in the same conversation must not be mistaken for the run.
// Only HTTP is simulated: plan, run and chat streams are held open and fed server-shaped frames.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import './test_support/tsResolve.mjs';

// The repository resolver must be registered before extensionless TypeScript imports load.
const { useChatStore } = await import('../application/v2_ui/src/stores/chatStore.ts');
const { selectActiveTurnRunInFlight, useOrchestrationStore } = await import(
    '../application/v2_ui/src/stores/orchestrationStore.ts'
);
const { approveAndRunPlan, startOrchestrationPlan } = await import(
    '../application/v2_ui/src/lib/orchestrationController.ts'
);

const PLAN_PATH = '/api/v2/orchestration/plan';
const RUN_PATH = '/api/v2/orchestration/run';
const ANSWER = 'Revenue rose 12% between the two quarters.';
const NOTICE = 'Saved facts could not be searched. Any available instruction memories are still included.';

const chat = () => useChatStore.getState();
const runCardShowsProgress = (conversationId) =>
    selectActiveTurnRunInFlight(useOrchestrationStore.getState(), conversationId);

function openConversation(conversationId) {
    useChatStore.setState({
        ...useChatStore.getInitialState(),
        activeConversationId: conversationId,
        activeConversationKind: 'personal',
        conversations: [{ id: conversationId, title: 'Quarterly comparison' }],
    }, true);
}

/**
 * Replace fetch with streams the test feeds by hand.
 *
 * Every request opens a held stream keyed by its path, so each intermediate state can be read
 * before the next frame lands. A path the test never feeds simply stays pending.
 */
function holdStreams() {
    const encoder = new TextEncoder();
    const streams = new Map();
    const waiters = new Map();
    const original = globalThis.fetch;
    globalThis.fetch = async (input, init = {}) => {
        const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        const path = new URL(raw, 'http://localhost').pathname;
        const body = new ReadableStream({
            start(controller) {
                streams.set(path, controller);
            },
        });
        const waiter = waiters.get(path);
        if (waiter) {
            waiters.delete(path);
            waiter(typeof init.body === 'string' ? JSON.parse(init.body) : null);
        }
        return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    };
    return {
        opened(path) {
            return new Promise((resolve) => waiters.set(path, resolve));
        },
        emit(path, event) {
            streams.get(path).enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        },
        end(path) {
            try {
                streams.get(path).close();
            } catch {
                // The reader already stopped at the terminal frame.
            }
        },
        restore() {
            globalThis.fetch = original;
        },
    };
}

/** A single-step plan in planner contract 2, the only shape normalizePlan accepts. */
function makePlan(conversationId, turnId, mode = 'manual') {
    return {
        plan_id: `plan-${conversationId}`,
        run_id: `run-${conversationId}`,
        turn_id: turnId,
        conversation_id: conversationId,
        user_id: 'tester',
        revision: 0,
        planner_contract_version: 2,
        intent: { summary: 'Compare the quarterly reports.', complexity: 'simple' },
        steps: [{
            step_id: 'draft', capability_id: 'compose', title: 'Draft the comparison',
            arguments: {}, role: 'reason', estimated_cost: 'low',
        }],
        assumptions: [],
        status: mode === 'auto' ? 'approved' : 'awaiting_approval',
        approval: { mode, state: mode === 'auto' ? 'approved' : 'pending' },
        validation: { valid: true, errors: [], warnings: [], repairs: [] },
    };
}

/** A run-time notice, shaped as build_planning_thought serializes it. */
function runNotice() {
    return {
        type: 'thought', message_id: null, step_index: 1, step_type: 'orchestration_planning',
        content: NOTICE,
        activity: { lane_key: 'orchestration', kind: 'orchestration_planning', title: 'Building a plan', status: 'running' },
    };
}

/** The run's terminal frame, shaped as build_run_done_event serializes it. */
function runDone(plan, status = 'completed') {
    return {
        done: true, type: 'orchestration_done', conversation_id: plan.conversation_id,
        message_id: `answer-${plan.conversation_id}`, run_id: plan.run_id,
        full_content: status === 'completed' ? ANSWER : '',
        hybrid_citations: [], web_search_citations: [], agent_citations: [], augmented: false,
        generated_artifacts: [], orchestration: {}, status, outcome: status, turn_id: plan.turn_id,
        attempt_index: 1, retry_of_run_id: null, failure: null, failures: [], recovery: null,
        message_saved: status === 'completed', reasoning_adjustments: [],
    };
}

/** Plan a turn through the real controller and return its plan once the stream has closed. */
async function planTurn(streams, conversationId, mode = 'manual') {
    const opened = streams.opened(PLAN_PATH);
    const planning = startOrchestrationPlan({
        conversationId, message: 'Compare the quarterly reports.', approvalMode: mode, seeds: {},
    });
    const request = await opened;
    assert.equal(chat().streaming, true);
    assert.equal(chat().orchestrationSurface, 'planning', 'the planner takes the surface as planning');
    const plan = makePlan(conversationId, request.turn_id, mode);
    streams.emit(PLAN_PATH, { type: 'orchestration_plan', plan, done: true });
    streams.end(PLAN_PATH);
    return { plan, planning };
}

test('the planner takes the surface as planning and an approved run as running', async () => {
    const conversation = 'surface-manual';
    openConversation(conversation);
    const streams = holdStreams();
    try {
        const { plan, planning } = await planTurn(streams, conversation);
        await planning;
        assert.equal(chat().streaming, false);
        assert.equal(chat().orchestrationSurface, null, 'a plan awaiting approval holds no surface');
        assert.equal(runCardShowsProgress(conversation), false);

        const opened = streams.opened(RUN_PATH);
        const running = approveAndRunPlan({ conversationId: conversation, turnId: plan.turn_id });
        await opened;
        assert.equal(chat().streaming, true, 'Stop and the composer lock still follow the run');
        assert.equal(chat().orchestrationSurface, 'running');
        assert.equal(runCardShowsProgress(conversation), true, 'the card is drawing the run');

        streams.emit(RUN_PATH, { type: 'orchestration_step', step_id: 'draft', status: 'running', summary: '' });
        streams.emit(RUN_PATH, runNotice());
        streams.emit(RUN_PATH, { type: 'orchestration_step', step_id: 'draft', status: 'completed', summary: '' });
        streams.emit(RUN_PATH, { content: ANSWER });
        streams.emit(RUN_PATH, runDone(plan));
        streams.end(RUN_PATH);
        await running;

        assert.equal(chat().streaming, false);
        assert.equal(chat().orchestrationSurface, null);
        assert.equal(runCardShowsProgress(conversation), false);
        const answer = chat().messages.find((message) => message.id === `answer-${conversation}`);
        assert.equal(answer?.content, ANSWER);
        // The bubble hid the live reasoning toggle during the run; the notice is not lost.
        assert.deepEqual(answer.thoughts?.map((thought) => thought.content), [NOTICE]);
    } finally {
        streams.restore();
    }
});

test('an auto-approved plan hands the surface straight from planning to the run', async () => {
    const conversation = 'surface-auto';
    openConversation(conversation);
    const seen = [];
    const unsubscribe = useChatStore.subscribe((state) => {
        seen.push(`${state.streaming}:${state.orchestrationSurface}`);
    });
    const streams = holdStreams();
    try {
        const opened = streams.opened(RUN_PATH);
        const { plan, planning } = await planTurn(streams, conversation, 'auto');
        await opened;
        assert.equal(chat().orchestrationSurface, 'running');
        assert.equal(runCardShowsProgress(conversation), true);

        streams.emit(RUN_PATH, { content: ANSWER });
        streams.emit(RUN_PATH, runDone(plan));
        streams.end(RUN_PATH);
        await planning;
        await new Promise((resolve) => setTimeout(resolve, 0));
        assert.equal(chat().orchestrationSurface, null);

        const changes = seen.filter((entry, index) => entry !== seen[index - 1]);
        assert.ok(!changes.includes('true:null'), `a chat-owned stream never appeared: ${changes.join(', ')}`);
        const planningAt = changes.indexOf('true:planning');
        assert.ok(planningAt >= 0, 'the planner held the surface');
        assert.equal(changes[planningAt + 1], 'true:running', 'nothing came between the plan and its run');
    } finally {
        unsubscribe();
        streams.restore();
    }
});

test('a chat reply sent while a run waits is not mistaken for the run', async () => {
    const conversation = 'surface-waiting';
    openConversation(conversation);
    const streams = holdStreams();
    try {
        const { plan, planning } = await planTurn(streams, conversation);
        await planning;
        const opened = streams.opened(RUN_PATH);
        void approveAndRunPlan({ conversationId: conversation, turnId: plan.turn_id });
        await opened;
        streams.emit(RUN_PATH, runDone(plan, 'waiting'));
        streams.end(RUN_PATH);
        await new Promise((resolve) => setTimeout(resolve, 0));

        // A durable wait releases the surface but leaves the run in flight on its card.
        assert.equal(chat().streaming, false);
        assert.equal(chat().orchestrationSurface, null);
        assert.equal(runCardShowsProgress(conversation), true);

        const chatOpened = streams.opened('/api/chat/stream');
        void chat().sendMessage('And what about costs?', {});
        await chatOpened;
        assert.equal(chat().streaming, true);
        assert.equal(chat().orchestrationSurface, null, 'the reply is a chat stream and shows Thinking');
    } finally {
        streams.restore();
    }
});

test('a run keeps its phase when the reader leaves and comes back', () => {
    const original = globalThis.fetch;
    // Opening a conversation reads its messages; held forever, nothing else happens.
    globalThis.fetch = () => new Promise(() => {});
    try {
        openConversation('surface-elsewhere');
        chat().beginOrchestrationTurn('surface-away', '', false, undefined, undefined, 'running');
        assert.equal(chat().streaming, false, 'a turn out of sight does not touch this conversation');
        assert.equal(chat().orchestrationSurface, null);

        void chat().selectConversation('surface-away', { kind: 'personal' });
        assert.equal(chat().streaming, true);
        assert.equal(chat().orchestrationSurface, 'running');

        chat().startNewConversation();
        assert.equal(chat().streaming, false);
        assert.equal(chat().orchestrationSurface, null);

        void chat().selectConversation('surface-away', { kind: 'personal' });
        assert.equal(chat().orchestrationSurface, 'running');

        chat().settleOrchestrationTurn('surface-away', { status: 'planned' });
        assert.equal(chat().streaming, false);
        assert.equal(chat().orchestrationSurface, null);

        void chat().selectConversation('surface-elsewhere', { kind: 'personal' });
        void chat().selectConversation('surface-away', { kind: 'personal' });
        assert.equal(chat().streaming, false, 'a settled turn does not come back');
        assert.equal(chat().orchestrationSurface, null);
    } finally {
        globalThis.fetch = original;
    }
});

test('a turn re-keyed to the server conversation id keeps its phase', () => {
    const original = globalThis.fetch;
    globalThis.fetch = () => new Promise(() => {});
    try {
        openConversation('surface-client-id');
        chat().beginOrchestrationTurn('surface-client-id', 'Compare the reports.', true, 'turn-1');
        assert.equal(chat().orchestrationSurface, 'planning', 'callers that predate the phase still plan');

        chat().reassignOrchestrationTurn({
            fromConversationId: 'surface-client-id', toConversationId: 'surface-server-id',
            fromTurnId: 'turn-1', toTurnId: 'turn-1',
        });
        chat().startNewConversation();
        void chat().selectConversation('surface-server-id', { kind: 'personal' });
        assert.equal(chat().streaming, true);
        assert.equal(chat().orchestrationSurface, 'planning');
        chat().settleOrchestrationTurn('surface-server-id', { status: 'planned' });
    } finally {
        globalThis.fetch = original;
    }
});

test('every write that takes the streaming flag says who owns it', () => {
    const store = readFileSync(new URL('../application/v2_ui/src/stores/chatStore.ts', import.meta.url), 'utf8');
    const takes = store.match(/streaming: true,/g) ?? [];
    const owners = [...store.matchAll(/streaming: true,\s*\n\s*orchestrationSurface: (null|phase),/g)]
        .map((match) => match[1]);
    assert.ok(takes.length >= 5, 'the chat starters and the orchestration seam are all present');
    assert.equal(owners.length, takes.length, 'a stream that takes `streaming` must name its owner');
    assert.deepEqual(owners.filter((owner) => owner === 'phase'), ['phase'], 'only the orchestration seam takes a phase');

    const controller = readFileSync(
        new URL('../application/v2_ui/src/lib/orchestrationController.ts', import.meta.url), 'utf8',
    );
    const runs = controller.match(/beginOrchestrationTurn\([^)]*'running'\)/g) ?? [];
    assert.deepEqual(runs, ["beginOrchestrationTurn(conversationId, '', false, undefined, undefined, 'running')"]);
});
