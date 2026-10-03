// test_v2_workflow_run_tracker.mjs
// Version: 0.261.230
// Implemented in: 0.261.230
// Executes the app shell's one workflow run tracker against a fake clock, fake timers and a fake
// status route: the visible cadence (15 s easing to every 5 minutes, one batched request per tick),
// the hidden-tab pause and its desktop-notification exception, idle stops and kicks, back-off and
// halts, an idempotent start and a clean stop, the first-read baseline that keeps a reload from
// announcing a result twice (kept per chat, so one chat's read never silences another), closings
// and retirements, and the 10-second dedupe of a chat's own reads.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';
import { at, deliveredRow, statusResponse, statusRow } from './test_support/workflowRunStatusFixtures.mjs';

globalThis.fetch = () => {
    throw new Error('The workflow run tracker must not make network requests of its own.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    WORKFLOW_RUN_CONVERSATION_DEDUPE_MS,
    WORKFLOW_RUN_ERROR_DELAYS_MS,
    WORKFLOW_RUN_HIDDEN_DELAY_MS,
    WORKFLOW_RUN_POLL_DELAYS_MS,
    createWorkflowRunTracker,
    isTrackedRunInFlight,
    workflowRunTrackerShouldRun,
} = await import('../application/v2_ui/src/lib/workflowRunTracker.ts');
const {
    WORKFLOW_STATUS_READ_ERROR_TEXT,
    parseWorkflowRunStatusResponse,
} = await import('../application/v2_ui/src/lib/workflowRunStatus.ts');

const flush = () => new Promise((resolve) => setImmediate(resolve));

function undeliverableRow(runId, overrides = {}) {
    return statusRow(runId, {
        status: 'completed',
        phase: 'finished',
        step_index: 4,
        completed_at: at(250),
        actions: { cancel: false },
        delivery: { status: 'undeliverable', generation: 2, reason: 'chat_unavailable' },
        ...overrides,
    });
}

function expiredRow(runId) {
    return statusRow(runId, {
        status: 'expired',
        phase: 'failed',
        error: 'It reached its time limit.',
        error_code: 'deadline_exceeded',
        actions: { cancel: false },
        delivery: { status: 'expired' },
    });
}

/**
 * A tracker wired to a fake clock, fake timers, a fake page and a status route that answers only
 * when the test says so. Each request is kept, with its signal, until `respond` or `fail`.
 */
function createHarness({ visible = true, desktop = false, onState, onDelivered, onClosed } = {}) {
    const state = { visible, desktop, clock: 1_000_000 };
    const timers = new Map();
    const requests = [];
    const listeners = new Set();
    const counts = { subscribed: 0, unsubscribed: 0, halted: 0, maxTimers: 0, states: 0 };
    const events = { delivered: [], closed: [], retired: [] };
    let nextTimerId = 1;

    const tracker = createWorkflowRunTracker({
        fetchStatus(conversationId, signal) {
            return new Promise((resolve, reject) => {
                requests.push({ conversationId, signal, resolve, reject });
            });
        },
        setTimer(callback, delayMs) {
            const id = nextTimerId;
            nextTimerId += 1;
            timers.set(id, { callback, at: state.clock + delayMs });
            counts.maxTimers = Math.max(counts.maxTimers, timers.size);
            return id;
        },
        clearTimer(handle) {
            timers.delete(handle);
        },
        now: () => state.clock,
        isVisible: () => state.visible,
        subscribeVisibility(listener) {
            counts.subscribed += 1;
            listeners.add(listener);
            return () => {
                counts.unsubscribed += 1;
                listeners.delete(listener);
            };
        },
        desktopNotificationsOn: () => state.desktop,
        onState(snapshot) {
            counts.states += 1;
            onState?.(snapshot);
        },
        onDelivered(row) {
            events.delivered.push(row);
            onDelivered?.(row);
        },
        onClosed(row) {
            events.closed.push(row);
            onClosed?.(row);
        },
        onRetired(row) {
            events.retired.push(row);
        },
        onHalted() {
            counts.halted += 1;
        },
    });

    function request(index) {
        const sent = requests[index];
        assert.ok(sent, `request ${index} should have been sent`);
        return sent;
    }

    return {
        tracker,
        state,
        timers,
        requests,
        counts,
        events,
        async respond(index, body) {
            request(index).resolve(parseWorkflowRunStatusResponse(body));
            await flush();
        },
        async fail(index, status) {
            const error = new Error('read failed');
            if (status !== undefined) {
                error.status = status;
            }
            request(index).reject(error);
            await flush();
        },
        /** Milliseconds until the one scheduled check, or null when none is. */
        nextDelay() {
            assert.ok(timers.size <= 1, 'the tracker keeps at most one timer');
            const [entry] = timers.values();
            return entry ? entry.at - state.clock : null;
        },
        async fire() {
            assert.equal(timers.size, 1, 'one check should be scheduled');
            const [[id, entry]] = timers.entries();
            state.clock = entry.at;
            timers.delete(id);
            entry.callback();
            await flush();
        },
        advance(ms) {
            state.clock += ms;
        },
        async setVisible(value) {
            state.visible = value;
            for (const listener of [...listeners]) {
                listener();
            }
            await flush();
        },
        delivered() {
            return events.delivered.map((row) => `${row.run_id}:${row.delivery.generation}`);
        },
    };
}

test('the tracker runs only when the user can use workflows and chats can start them', () => {
    assert.equal(workflowRunTrackerShouldRun({
        allow_user_workflows: true,
        enable_chat_orchestration_workflow_runs: true,
    }), true);
    assert.equal(workflowRunTrackerShouldRun({
        allow_user_workflows: true,
        enable_chat_orchestration_workflow_runs: true,
        enable_chat_workflow_results: false,
    }), true, 'a run shows its progress on its card even when results are not posted back');
    for (const features of [
        null,
        undefined,
        {},
        { allow_user_workflows: true },
        { enable_chat_orchestration_workflow_runs: true },
        { allow_user_workflows: true, enable_chat_orchestration_workflow_runs: false },
        { allow_user_workflows: false, enable_chat_orchestration_workflow_runs: true },
        { allow_user_workflows: 'true', enable_chat_orchestration_workflow_runs: true },
        { allow_user_workflows: true, enable_chat_orchestration_workflow_runs: 1 },
    ]) {
        assert.equal(workflowRunTrackerShouldRun(features), false, String(JSON.stringify(features)));
    }
});

test('the cadence constants are the roadmap cadence', () => {
    assert.deepEqual([...WORKFLOW_RUN_POLL_DELAYS_MS], [15_000, 30_000, 60_000, 120_000, 300_000]);
    assert.deepEqual([...WORKFLOW_RUN_ERROR_DELAYS_MS], [30_000, 60_000, 120_000, 300_000]);
    assert.equal(WORKFLOW_RUN_HIDDEN_DELAY_MS, 300_000);
    assert.equal(WORKFLOW_RUN_CONVERSATION_DEDUPE_MS, 10_000);
});

test('a visible tab with runs in flight checks after 15 s, easing to every 5 minutes, one request per tick', async () => {
    const h = createHarness();
    const rows = [statusRow('run-a'), statusRow('run-b'), statusRow('run-c', { conversation_id: 'chat-2' })];
    h.tracker.start();
    assert.equal(h.requests.length, 1, 'start checks straight away');
    const delays = [];
    for (let tick = 0; tick < 6; tick += 1) {
        await h.respond(tick, statusResponse(rows, { checked_at: at(300 + tick * 400) }));
        delays.push(h.nextDelay());
        await h.fire();
        assert.equal(h.requests.length, tick + 2, 'one request per tick, however many runs are in flight');
    }
    assert.deepEqual(delays, [15_000, 30_000, 60_000, 120_000, 300_000, 300_000]);
    assert.ok(h.requests.every((sent) => sent.conversationId === null), 'every tick reads every chat at once');
    assert.equal(h.counts.maxTimers, 1);
});

test('with nothing in flight it stops until a kick starts it again', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([deliveredRow('run-a', 1, at(200))]));
    assert.equal(h.nextDelay(), null, 'nothing in flight: no check is scheduled');

    h.tracker.kick();
    assert.equal(h.requests.length, 1, 'a kick without immediate waits for the timer');
    assert.equal(h.nextDelay(), 15_000);
    await h.fire();
    assert.equal(h.requests.length, 2);
    await h.respond(1, statusResponse([deliveredRow('run-a', 1, at(200))], { checked_at: at(330) }));
    assert.equal(h.nextDelay(), null, 'the kick is spent once its check finds nothing in flight');

    h.tracker.kick({ immediate: true });
    assert.equal(h.requests.length, 3, 'an immediate kick checks at once');
    assert.equal(h.requests[2].conversationId, null);
});

test('a kick brings the next check forward but never pushes it back', async () => {
    const h = createHarness();
    const rows = [statusRow('run-a')];
    h.tracker.start();
    await h.respond(0, statusResponse(rows));
    for (let index = 1; index <= 4; index += 1) {
        await h.fire();
        await h.respond(index, statusResponse(rows, { checked_at: at(300 + index * 400) }));
    }
    assert.equal(h.nextDelay(), 300_000);
    h.tracker.kick();
    assert.equal(h.nextDelay(), 15_000, 'a kick restarts the ladder');
    h.advance(10_000);
    h.tracker.kick();
    assert.equal(h.nextDelay(), 5_000, 'a second kick keeps the sooner check');
    assert.equal(h.requests.length, 5);
});

test('a kick during a read sends no second request; the read schedules the next check', async () => {
    const h = createHarness();
    h.tracker.start();
    h.tracker.kick();
    h.tracker.kick({ immediate: true });
    assert.equal(h.requests.length, 1);
    assert.equal(h.nextDelay(), null, 'no timer runs while a read is under way');
    await h.respond(0, statusResponse([]));
    assert.equal(h.nextDelay(), 15_000, 'the read may predate the new run, so another check follows');
    await h.fire();
    await h.respond(1, statusResponse([], { checked_at: at(330) }));
    assert.equal(h.nextDelay(), null);
});

test("a chat's read that finds a run in flight starts the checks again", async () => {
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([]));
    assert.equal(h.nextDelay(), null);
    const read = h.tracker.requestConversationRuns('chat-1');
    await h.respond(1, statusResponse([statusRow('run-a')], { checked_at: at(310) }));
    assert.equal(await read, true);
    assert.equal(h.nextDelay(), 15_000);
    await h.fire();
    assert.equal(h.requests[2].conversationId, null, 'the checks that follow read every chat at once');
});

test('a hidden tab pauses and checks as soon as it is shown again, from the start of the ladder', async () => {
    const h = createHarness();
    const rows = [statusRow('run-a')];
    h.tracker.start();
    await h.setVisible(false);
    await h.setVisible(true);
    assert.equal(h.requests.length, 1, 'showing the tab during a read sends no second one');
    await h.respond(0, statusResponse(rows));
    await h.fire();
    await h.respond(1, statusResponse(rows, { checked_at: at(400) }));
    assert.equal(h.nextDelay(), 30_000);

    await h.setVisible(false);
    assert.equal(h.nextDelay(), null, 'hidden: paused');
    h.advance(3_600_000);
    assert.equal(h.requests.length, 2);
    await h.setVisible(true);
    assert.equal(h.requests.length, 3, 'shown: it checks at once');
    await h.respond(2, statusResponse(rows, { checked_at: at(4_000) }));
    assert.equal(h.nextDelay(), 15_000, 'and the ladder starts over');
});

test('showing the tab checks only when something is in flight, failing or asked for', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([deliveredRow('run-a', 1, at(200))]));
    await h.setVisible(false);
    await h.setVisible(true);
    assert.equal(h.requests.length, 1, 'nothing in flight: showing the tab sends nothing');
    assert.equal(h.nextDelay(), null);

    await h.setVisible(false);
    h.tracker.kick();
    assert.equal(h.nextDelay(), null, 'hidden: the kick waits for the tab');
    await h.setVisible(true);
    assert.equal(h.requests.length, 2, 'a kick that came while hidden is checked once the tab is shown');
});

test('a hidden tab keeps a 5-minute check only while desktop notifications are on and a run is in flight', async () => {
    const h = createHarness({ desktop: true });
    h.tracker.start();
    await h.respond(0, statusResponse([statusRow('run-a')]));
    assert.equal(h.nextDelay(), 15_000);
    await h.setVisible(false);
    assert.equal(h.nextDelay(), 300_000);
    await h.fire();
    assert.equal(h.requests.length, 2);
    await h.respond(1, statusResponse([statusRow('run-a')], { checked_at: at(600) }));
    assert.equal(h.nextDelay(), 300_000, 'every 5 minutes while hidden');
    await h.fire();
    await h.respond(2, statusResponse([deliveredRow('run-a', 1, at(850))], { checked_at: at(900) }));
    assert.equal(h.nextDelay(), null, 'nothing in flight: a hidden tab stops checking');

    const off = createHarness({ desktop: true });
    off.tracker.start();
    await off.respond(0, statusResponse([statusRow('run-a')]));
    await off.setVisible(false);
    assert.equal(off.nextDelay(), 300_000);
    off.state.desktop = false;
    await off.fire();
    await off.respond(1, statusResponse([statusRow('run-a')], { checked_at: at(600) }));
    assert.equal(off.nextDelay(), null, 'desktop notifications turned off: a hidden tab is paused');
});

test('a tracker started in a hidden tab waits for the tab unless desktop notifications are on', async () => {
    const hidden = createHarness({ visible: false });
    hidden.tracker.start();
    assert.equal(hidden.requests.length, 0);
    assert.equal(hidden.nextDelay(), null);
    hidden.tracker.kick({ immediate: true });
    assert.equal(hidden.requests.length, 0, 'an immediate kick in a hidden tab waits too');
    assert.equal(hidden.nextDelay(), null);
    await hidden.setVisible(true);
    assert.equal(hidden.requests.length, 1, 'shown: it checks at once');

    const desktop = createHarness({ visible: false, desktop: true });
    desktop.tracker.start();
    assert.equal(desktop.requests.length, 1, 'desktop notifications on: a hidden tab checks at once');
});

test('starting a running tracker adds no second subscription, request or timer', async () => {
    const h = createHarness();
    h.tracker.start();
    h.tracker.start();
    assert.equal(h.counts.subscribed, 1);
    assert.equal(h.requests.length, 1);
    await h.respond(0, statusResponse([statusRow('run-a')]));
    h.tracker.start();
    assert.equal(h.requests.length, 1);
    assert.equal(h.timers.size, 1);
    assert.equal(h.counts.maxTimers, 1);
    assert.equal(h.counts.subscribed, 1);
});

test('stop aborts every read, drops the timer and ignores late answers', async () => {
    const h = createHarness();
    h.tracker.start();
    const chatRead = h.tracker.requestConversationRuns('chat-1');
    assert.equal(h.requests.length, 2);
    assert.equal(h.tracker.getSnapshot().conversations['chat-1'].reading, true);

    h.tracker.stop();
    assert.equal(h.requests[0].signal.aborted, true);
    assert.equal(h.requests[1].signal.aborted, true);
    assert.equal(h.counts.unsubscribed, 1);
    let snapshot = h.tracker.getSnapshot();
    assert.equal(snapshot.running, false);
    assert.equal(snapshot.conversations['chat-1'].reading, false);

    await h.respond(0, statusResponse([statusRow('run-a')]));
    await h.respond(1, statusResponse([statusRow('run-a')]));
    assert.equal(await chatRead, false);
    snapshot = h.tracker.getSnapshot();
    assert.deepEqual(snapshot.runs, {}, 'a late answer changes nothing');
    assert.equal(h.nextDelay(), null);

    h.tracker.kick();
    h.tracker.kick({ immediate: true });
    assert.equal(await h.tracker.requestConversationRuns('chat-1'), false);
    await h.setVisible(false);
    await h.setVisible(true);
    assert.equal(h.requests.length, 2, 'a stopped tracker sends nothing');
    assert.equal(h.nextDelay(), null);
});

test('stopping and starting again keeps what the page session already saw', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([deliveredRow('run-a', 1, at(200)), statusRow('run-b')]));
    assert.equal(h.nextDelay(), 15_000);
    h.tracker.stop();
    assert.equal(h.nextDelay(), null, 'stop drops the timer');
    h.tracker.start();
    assert.equal(h.counts.subscribed, 2);
    assert.equal(h.requests.length, 2);
    await h.respond(1, statusResponse([
        deliveredRow('run-a', 1, at(200)),
        deliveredRow('run-b', 1, at(320)),
    ], { checked_at: at(330) }));
    assert.deepEqual(h.delivered(), ['run-b:1'], 'only the posting that is new to this page session');
});

test('failed reads back off to every 5 minutes without a tight loop, then recover', async () => {
    const h = createHarness();
    h.tracker.start();
    const delays = [];
    for (let index = 0; index < 5; index += 1) {
        await h.fail(index, 503);
        delays.push(h.nextDelay());
        assert.equal(h.tracker.getSnapshot().globalError, true);
        await h.fire();
    }
    assert.deepEqual(delays, [30_000, 60_000, 120_000, 300_000, 300_000]);
    assert.equal(h.requests.length, 6);

    await h.setVisible(false);
    assert.equal(h.nextDelay(), null, 'hidden: paused, even while failing');
    await h.setVisible(true);
    assert.equal(h.requests.length, 6, 'a read is already under way');
    await h.respond(5, statusResponse([statusRow('run-a')]));
    const snapshot = h.tracker.getSnapshot();
    assert.equal(snapshot.globalError, false);
    assert.equal(snapshot.halted, false);
    assert.equal(h.nextDelay(), 15_000);
});

test('a failing tracker that is hidden and shown again checks at once', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.fail(0, 503);
    await h.setVisible(false);
    assert.equal(h.nextDelay(), null);
    await h.setVisible(true);
    assert.equal(h.requests.length, 2);
});

test('the error back-off keeps the ladder position', async () => {
    const h = createHarness();
    const rows = [statusRow('run-a')];
    h.tracker.start();
    await h.respond(0, statusResponse(rows));
    await h.fire();
    await h.fail(1, 503);
    assert.equal(h.nextDelay(), 30_000);
    await h.fire();
    await h.respond(2, statusResponse(rows, { checked_at: at(400) }));
    assert.equal(h.nextDelay(), 30_000, 'it resumes where it was, not from the start or a step further on');
    await h.fire();
    await h.respond(3, statusResponse(rows, { checked_at: at(500) }));
    assert.equal(h.nextDelay(), 60_000);
});

test('a kick keeps the back-off timer, Check now still checks, and any failure counts', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.fail(0, 503);
    h.advance(10_000);
    h.tracker.kick();
    assert.equal(h.nextDelay(), 20_000, 'a kick does not cut the back-off short');
    assert.equal(h.requests.length, 1);
    h.tracker.kick({ immediate: true });
    assert.equal(h.requests.length, 2, 'an immediate kick (Check now) checks at once');

    const network = createHarness();
    network.tracker.start();
    await network.fail(0);
    const snapshot = network.tracker.getSnapshot();
    assert.equal(snapshot.halted, false);
    assert.equal(snapshot.globalError, true);
    assert.equal(network.nextDelay(), 30_000, 'a failure without a status backs off too');
});

for (const status of [401, 403, 400]) {
    test(`a ${status} on the read of every chat halts the tracker for the page session`, async () => {
        const h = createHarness();
        h.tracker.start();
        const chatRead = h.tracker.requestConversationRuns('chat-1');
        await h.fail(0, status);
        const snapshot = h.tracker.getSnapshot();
        assert.equal(snapshot.halted, true);
        assert.equal(h.counts.halted, 1);
        assert.equal(h.requests[1].signal.aborted, true, 'a halt aborts the reads under way');
        assert.equal(snapshot.conversations['chat-1'].reading, false);
        await h.respond(1, statusResponse([statusRow('run-a')]));
        assert.equal(await chatRead, false);
        assert.deepEqual(h.tracker.getSnapshot().runs, {});
        assert.equal(h.nextDelay(), null);

        h.tracker.kick();
        h.tracker.kick({ immediate: true });
        await h.setVisible(false);
        await h.setVisible(true);
        assert.equal(await h.tracker.requestConversationRuns('chat-1'), false);
        h.tracker.start();
        assert.equal(h.requests.length, 2, 'a halted tracker sends nothing, even when started again');
        assert.equal(h.nextDelay(), null);
        assert.equal(h.counts.halted, 1);

        h.tracker.stop();
        h.tracker.start();
        assert.equal(h.tracker.getSnapshot().halted, false, 'a fresh start clears the halt');
        assert.equal(h.requests.length, 3);
    });
}

test("a failed read of one chat shows its error on that chat only and does not halt", async () => {
    const h = createHarness({ visible: false });
    h.tracker.start();
    let index = 0;
    for (const status of [400, 503, undefined]) {
        const read = h.tracker.requestConversationRuns('chat-1');
        assert.equal(h.requests.length, index + 1, 'a failed read is never deduped');
        assert.equal(h.requests[index].conversationId, 'chat-1');
        await h.fail(index, status);
        assert.equal(await read, false);
        const snapshot = h.tracker.getSnapshot();
        assert.equal(snapshot.halted, false);
        assert.deepEqual(snapshot.conversations['chat-1'], {
            checkedAt: null,
            reading: false,
            error: WORKFLOW_STATUS_READ_ERROR_TEXT,
        });
        assert.equal(snapshot.globalError, false, "one chat's failure is not the tracker's");
        index += 1;
    }
    const good = h.tracker.requestConversationRuns('chat-1');
    await h.respond(index, statusResponse([statusRow('run-a')], { checked_at: at(310) }));
    assert.equal(await good, true);
    assert.deepEqual(h.tracker.getSnapshot().conversations['chat-1'], {
        checkedAt: at(310),
        reading: false,
        error: null,
    });
    assert.equal(h.nextDelay(), null, 'hidden with desktop notifications off: nothing is scheduled');
});

for (const status of [401, 403]) {
    test(`a ${status} on one chat's read halts the tracker`, async () => {
        const h = createHarness({ visible: false });
        h.tracker.start();
        const read = h.tracker.requestConversationRuns('chat-1');
        await h.fail(0, status);
        assert.equal(await read, false);
        const snapshot = h.tracker.getSnapshot();
        assert.equal(snapshot.halted, true);
        assert.equal(h.counts.halted, 1);
        assert.equal(snapshot.conversations['chat-1'].error, WORKFLOW_STATUS_READ_ERROR_TEXT);
        await h.setVisible(true);
        assert.equal(h.requests.length, 1);
    });
}

test('the first read of a page session records what is already posted and announces none of it', async () => {
    const posted = [
        deliveredRow('run-a', 2, at(200)),
        deliveredRow('run-b', 1, at(300), { conversation_id: 'chat-2' }),
    ];
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([...posted, statusRow('run-c')]));
    assert.deepEqual(h.events.delivered, [], 'already posted, even in the same second as the read');
    await h.fire();
    await h.respond(1, statusResponse([...posted, statusRow('run-c')], { checked_at: at(330) }));
    assert.deepEqual(h.events.delivered, [], 'and still silent on the next read');

    // A reload starts a new tracker, whose first read is silent too.
    const reloaded = createHarness();
    reloaded.tracker.start();
    await reloaded.respond(0, statusResponse(posted, { checked_at: at(400) }));
    reloaded.tracker.kick({ immediate: true });
    await reloaded.respond(1, statusResponse(posted, { checked_at: at(430) }));
    assert.deepEqual(reloaded.events.delivered, []);
});

test('a posting seen later in the page session is announced once per generation, after the state is published', async () => {
    const statusWhenAnnounced = [];
    const h = createHarness({
        onDelivered(row) {
            statusWhenAnnounced.push(h.tracker.getSnapshot().runs[row.run_id].row.delivery.status);
        },
    });
    h.tracker.start();
    await h.respond(0, statusResponse([statusRow('run-a'), statusRow('run-b')]));
    await h.fire();
    await h.respond(1, statusResponse([
        deliveredRow('run-a', 4, at(310)),
        deliveredRow('run-b', 1, at(310), { delivery: { message_id: null } }),
    ], { checked_at: at(320) }));
    assert.deepEqual(h.delivered(), ['run-a:4'], 'a posting without a message id is never announced');
    assert.deepEqual(statusWhenAnnounced, ['delivered'], 'readers see the new state when they are told');

    h.tracker.kick({ immediate: true });
    await h.respond(2, statusResponse([deliveredRow('run-a', 4, at(310))], { checked_at: at(350) }));
    assert.equal(h.events.delivered.length, 1, 'the same posting is announced once');

    // Retried: the run runs again and posts under a new generation.
    h.tracker.kick({ immediate: true });
    await h.respond(3, statusResponse([statusRow('run-a', { runtime_version: 5 })], { checked_at: at(400) }));
    await h.fire();
    await h.respond(4, statusResponse([deliveredRow('run-a', 6, at(420))], { checked_at: at(430) }));
    assert.deepEqual(h.delivered(), ['run-a:4', 'run-a:6']);
});

test('a posting in the same second as the first read, but missing from it, is announced', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([], { checked_at: at(300) }));
    h.tracker.kick({ immediate: true });
    await h.respond(1, statusResponse([
        deliveredRow('run-new', 1, at(300)),
        deliveredRow('run-old', 1, at(299)),
    ], { checked_at: at(330) }));
    assert.deepEqual(h.delivered(), ['run-new:1'], 'posted before the first read: already there, so silent');
});

test("one chat's own read never silences another chat's first listing", async () => {
    const h = createHarness({ visible: false });
    h.tracker.start();
    const chatRead = h.tracker.requestConversationRuns('chat-a');
    await h.respond(0, statusResponse([statusRow('run-a1', { conversation_id: 'chat-a' })], { checked_at: at(300) }));
    assert.equal(await chatRead, true);
    assert.equal(h.requests.length, 1, 'hidden with desktop notifications off: no read of every chat yet');

    await h.setVisible(true);
    assert.equal(h.requests.length, 2);
    assert.equal(h.requests[1].conversationId, null);
    await h.respond(1, statusResponse([
        deliveredRow('run-b1', 1, at(300), { conversation_id: 'chat-b' }),
        deliveredRow('run-a1', 1, at(300), { conversation_id: 'chat-a' }),
    ], { checked_at: at(310) }));
    assert.deepEqual(h.delivered(), ['run-a1:1'], "chat-b's first listing is silent; chat-a's posting is new");
});

test("a chat's own first read records what is already posted there; later postings are announced", async () => {
    const h = createHarness({ visible: false });
    h.tracker.start();
    const first = h.tracker.requestConversationRuns('chat-1');
    await h.respond(0, statusResponse([deliveredRow('run-x', 1, at(100))], { checked_at: at(300) }));
    assert.equal(await first, true);
    assert.deepEqual(h.events.delivered, []);
    h.advance(WORKFLOW_RUN_CONVERSATION_DEDUPE_MS);
    const second = h.tracker.requestConversationRuns('chat-1');
    await h.respond(1, statusResponse([
        deliveredRow('run-y', 2, at(305)),
        deliveredRow('run-x', 1, at(100)),
    ], { checked_at: at(310) }));
    assert.equal(await second, true);
    assert.deepEqual(h.delivered(), ['run-y:2']);
});

test('only a complete read of every chat retires a run that dropped out, and only once', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([statusRow('run-a'), statusRow('run-b')]));
    await h.fire();
    await h.respond(1, statusResponse([statusRow('run-b')], { checked_at: at(330), truncated: true }));
    let snapshot = h.tracker.getSnapshot();
    assert.equal(snapshot.runs['run-a'].retired, false, 'a truncated read leaves rows out, so it retires nothing');
    assert.equal(snapshot.globalCheckedAt, at(300), 'a truncated read is not a complete read');

    const chatRead = h.tracker.requestConversationRuns('chat-1');
    await h.respond(2, statusResponse([], { checked_at: at(340) }));
    assert.equal(await chatRead, true);
    assert.equal(h.tracker.getSnapshot().runs['run-a'].retired, false, "a chat's own read is capped, so it retires nothing");
    assert.deepEqual(h.events.retired, []);

    await h.fire();
    await h.respond(3, statusResponse([statusRow('run-b')], { checked_at: at(370) }));
    snapshot = h.tracker.getSnapshot();
    assert.equal(snapshot.runs['run-a'].retired, true);
    assert.equal(isTrackedRunInFlight(snapshot.runs['run-a']), false);
    assert.equal(isTrackedRunInFlight(undefined), false);
    assert.equal(snapshot.runs['run-a'].checkedAt, at(300), 'a retired run keeps the read it came from');
    assert.equal(snapshot.globalCheckedAt, at(370));
    assert.deepEqual(h.events.retired.map((row) => row.run_id), ['run-a']);

    h.tracker.kick({ immediate: true });
    await h.respond(4, statusResponse([statusRow('run-b')], { checked_at: at(400) }));
    assert.equal(h.events.retired.length, 1, 'a retired run is retired once');

    // A chat's read listed run-c in the same second as a complete read that does not list it: the
    // complete read is no newer, so it says nothing about run-c.
    const otherChat = h.tracker.requestConversationRuns('chat-2');
    await h.respond(5, statusResponse([statusRow('run-c', { conversation_id: 'chat-2' })], { checked_at: at(430) }));
    assert.equal(await otherChat, true);
    h.tracker.kick({ immediate: true });
    await h.respond(6, statusResponse([statusRow('run-b')], { checked_at: at(430) }));
    assert.equal(h.tracker.getSnapshot().runs['run-c'].retired, false);

    h.tracker.kick({ immediate: true });
    await h.respond(7, statusResponse([], { checked_at: at(460) }));
    snapshot = h.tracker.getSnapshot();
    assert.equal(snapshot.runs['run-b'].retired, true);
    assert.equal(snapshot.runs['run-c'].retired, true);
    assert.deepEqual(h.events.retired.map((row) => row.run_id), ['run-a', 'run-b', 'run-c']);
    assert.equal(h.nextDelay(), null, 'nothing in flight: no check is scheduled');
});

test("a chat's own read is shared while under way and stands for 10 seconds after a good answer", async () => {
    const h = createHarness({ visible: false });
    h.tracker.start();
    const first = h.tracker.requestConversationRuns('chat-1');
    assert.equal(h.tracker.requestConversationRuns('chat-1'), first, 'a read under way is shared');
    assert.equal(h.requests.length, 1);
    assert.equal(h.requests[0].conversationId, 'chat-1');
    await h.respond(0, statusResponse([deliveredRow('run-a', 1, at(200))]));
    assert.equal(await first, true);

    assert.equal(await h.tracker.requestConversationRuns('chat-1'), true);
    h.advance(WORKFLOW_RUN_CONVERSATION_DEDUPE_MS - 1);
    assert.equal(await h.tracker.requestConversationRuns('chat-1'), true);
    assert.equal(h.requests.length, 1, 'within 10 s the last good read stands');
    h.advance(1);
    const later = h.tracker.requestConversationRuns('chat-1');
    assert.equal(h.requests.length, 2, 'after 10 s it reads again');
    await h.respond(1, statusResponse([deliveredRow('run-a', 1, at(200))], { checked_at: at(310) }));
    assert.equal(await later, true);

    const forced = h.tracker.requestConversationRuns('chat-1', { force: true });
    assert.equal(h.requests.length, 3, 'a forced read skips the dedupe');
    const replacement = h.tracker.requestConversationRuns('chat-1', { force: true });
    assert.equal(h.requests[2].signal.aborted, true, 'a forced read replaces the one under way');
    assert.equal(h.requests.length, 4);
    await h.respond(2, statusResponse([statusRow('run-late')], { checked_at: at(320) }));
    assert.equal(await forced, false);
    assert.equal(h.tracker.getSnapshot().runs['run-late'], undefined, 'the replaced read changes nothing');
    await h.respond(3, statusResponse([deliveredRow('run-a', 1, at(200))], { checked_at: at(330) }));
    assert.equal(await replacement, true);

    const other = h.tracker.requestConversationRuns('chat-2');
    assert.equal(h.requests.length, 5, 'another chat is read on its own');
    assert.equal(h.requests[4].conversationId, 'chat-2');
    await h.respond(4, statusResponse([], { checked_at: at(340) }));
    assert.equal(await other, true);

    for (const invalid of ['', 'has space', ' chat-1', 'chat-1 ', 'x/y', 'chat?x=1', 'a'.repeat(129), null, undefined, 42]) {
        assert.equal(await h.tracker.requestConversationRuns(invalid), false, String(invalid));
    }
    assert.equal(h.requests.length, 5, 'an id the route would refuse is never sent');
});

test("a chat's read speaks for that chat only, and an older answer never overwrites a newer one", async () => {
    const h = createHarness();
    h.tracker.start();
    const chatRead = h.tracker.requestConversationRuns('chat-1');
    await h.respond(0, statusResponse([statusRow('run-a')], { checked_at: at(320) }));
    await h.respond(1, statusResponse([
        statusRow('run-a', { status: 'queued' }),
        statusRow('run-z', { conversation_id: 'chat-2' }),
    ], { checked_at: at(310), available: false }));
    assert.equal(await chatRead, true);
    let snapshot = h.tracker.getSnapshot();
    assert.equal(snapshot.runs['run-a'].row.status, 'running', 'the older answer is ignored');
    assert.equal(snapshot.runs['run-a'].checkedAt, at(320));
    assert.equal(snapshot.runs['run-z'], undefined, "another chat's row in a chat's read is ignored");
    assert.equal(snapshot.available, true, 'availability follows the newest answer');
    assert.equal(snapshot.conversations['chat-1'].checkedAt, at(310));

    h.tracker.kick({ immediate: true });
    await h.respond(2, statusResponse([statusRow('run-a')], { checked_at: at(350), available: false }));
    snapshot = h.tracker.getSnapshot();
    assert.equal(snapshot.available, false);
    assert.equal(snapshot.runs['run-a'].checkedAt, at(350));
});

test('a run seen in flight that can no longer post to its chat is reported once', async () => {
    const h = createHarness();
    h.tracker.start();
    await h.respond(0, statusResponse([statusRow('run-a'), statusRow('run-d'), undeliverableRow('run-b')]));
    assert.deepEqual(h.events.closed, [], 'nothing is reported from the first read');
    await h.fire();
    const closedRows = [
        undeliverableRow('run-a'),
        expiredRow('run-d'),
        undeliverableRow('run-b'),
        undeliverableRow('run-e'),
    ];
    await h.respond(1, statusResponse(closedRows, { checked_at: at(330) }));
    assert.deepEqual(
        h.events.closed.map((row) => `${row.run_id}:${row.delivery.status}`),
        ['run-a:undeliverable', 'run-d:expired'],
        'never for a run that was not seen in flight',
    );
    assert.equal(h.nextDelay(), null);
    h.tracker.kick({ immediate: true });
    await h.respond(2, statusResponse(closedRows, { checked_at: at(360) }));
    assert.equal(h.events.closed.length, 2, 'each closing is reported once');
    assert.deepEqual(h.events.delivered, []);
});

test("a reader's failure never stops the tracker", async () => {
    const h = createHarness({
        onState() {
            throw new Error('state reader failed');
        },
        onDelivered() {
            throw new Error('delivery reader failed');
        },
    });
    h.tracker.start();
    await h.respond(0, statusResponse([statusRow('run-a'), statusRow('run-b')]));
    assert.equal(h.nextDelay(), 15_000);
    await h.fire();
    await h.respond(1, statusResponse([
        deliveredRow('run-a', 1, at(310)),
        undeliverableRow('run-b'),
        statusRow('run-c'),
    ], { checked_at: at(330) }));
    assert.ok(h.counts.states > 0);
    assert.deepEqual(h.delivered(), ['run-a:1']);
    assert.deepEqual(h.events.closed.map((row) => row.run_id), ['run-b'], 'the next reader is still told');
    assert.equal(h.nextDelay(), 30_000, 'and the next check is still scheduled');
    assert.equal(h.tracker.getSnapshot().runs['run-a'].row.delivery.status, 'delivered');
});
