// test_v2_collaboration_ai_activity_logic.mjs
// Version: 0.261.255
// Implemented in: 0.261.255
// Executes the real V2 bookkeeping behind the agent activity line of a shared conversation:
// how started, progress and finished events build the list of running requests, how replayed
// history rebuilds a run that is still going, why an answer closes its run, and how the
// reader's own request is shown before its broadcast arrives without ever being listed twice.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    AI_ACTIVITY_MAX_AGE_MS, applyAiActivityEvent, describeAiActivityRun, finishAiRunsAnsweredBy,
    formatAiActivityElapsed, localAiRun, pruneStaleAiRuns, visibleAiRuns,
} = await import('../application/v2_ui/src/lib/aiActivity.ts');
const { dispatchCollaborationEvent } = await import('../application/v2_ui/src/lib/collaborationEvents.ts');

const NOW = Date.parse('2026-05-01T12:00:00Z');

function started(runId, overrides = {}) {
    return {
        kind: 'started',
        run: {
            run_id: runId,
            display_name: 'Watch Officer',
            target_type: 'agent',
            requested_by: { user_id: 'u-sam', display_name: 'Sam Lee' },
            request_message_id: `request-${runId}`,
            started_at: '2026-05-01T11:59:50+00:00',
            ...overrides,
        },
        occurredAt: NOW - 10_000,
        replayed: false,
    };
}

function testLiveEventsBuildTheRunningList() {
    let runs = applyAiActivityEvent([], started('a'), NOW);
    runs = applyAiActivityEvent(runs, started('b', {
        display_name: 'Response Cell Officer', requested_by: { user_id: 'u-ada', display_name: 'Ada' },
    }), NOW + 500);
    assert.equal(runs.length, 2, 'two requests can run at once');
    assert.equal(runs[0].startedAt, NOW, 'a live run is timed from when it arrived, not the server clock');
    assert.equal(runs[0].step, '');

    runs = applyAiActivityEvent(runs, { kind: 'progress', run: { run_id: 'a', step: 'Calling search' }, replayed: false }, NOW);
    runs = applyAiActivityEvent(runs, { kind: 'progress', run: { run_id: 'zzz', step: 'unknown run' }, replayed: false }, NOW);
    runs = applyAiActivityEvent(runs, { kind: 'progress', run: { run_id: 'b', step: '   ' }, replayed: false }, NOW);
    assert.deepEqual(runs.map((run) => run.step), ['Calling search', '']);

    runs = applyAiActivityEvent(runs, started('a'), NOW + 1000);
    assert.equal(runs.length, 2, 'a repeated start replaces the run rather than adding another');

    runs = applyAiActivityEvent(runs, { kind: 'finished', run: { run_id: 'a', status: 'completed' }, replayed: false }, NOW);
    assert.deepEqual(runs.map((run) => run.run_id), ['b']);
    assert.deepEqual(applyAiActivityEvent(runs, { kind: 'finished', run: {}, replayed: false }, NOW), runs);

    const odd = applyAiActivityEvent([], started('c', { target_type: 'spaceship', display_name: '' }), NOW);
    assert.equal(odd[0].target_type, 'model');
    assert.equal(odd[0].display_name, 'Assistant');
}

function testReplayRebuildsOnlyRunsStillGoing() {
    const replayStart = { ...started('a'), replayed: true, occurredAt: NOW - 120_000 };
    let runs = applyAiActivityEvent([], replayStart, NOW);
    assert.equal(runs[0].startedAt, NOW - 120_000, 'a run already going is timed from when it began');

    runs = applyAiActivityEvent(runs, { kind: 'finished', run: { run_id: 'a' }, replayed: true }, NOW);
    assert.deepEqual(runs, [], 'a finished run in the history stays finished');

    const old = { ...started('old'), replayed: true, occurredAt: NOW - AI_ACTIVITY_MAX_AGE_MS - 1 };
    assert.deepEqual(applyAiActivityEvent([], old, NOW), [], 'a run that never reported finishing expires');

    const future = { ...started('skewed'), replayed: true, occurredAt: NOW + 60_000 };
    assert.equal(applyAiActivityEvent([], future, NOW)[0].startedAt, NOW, 'a fast server clock cannot start the timer in the future');

    const stale = [{ ...applyAiActivityEvent([], started('x'), NOW)[0], startedAt: NOW - AI_ACTIVITY_MAX_AGE_MS - 5 }];
    assert.deepEqual(pruneStaleAiRuns(stale, NOW), []);
}

function testAnAnswerClosesItsRun() {
    const runs = [
        ...applyAiActivityEvent([], started('a'), NOW),
        ...applyAiActivityEvent([], started('b'), NOW),
    ];
    assert.deepEqual(
        finishAiRunsAnsweredBy(runs, { role: 'assistant', reply_to_message_id: 'request-a' }).map((run) => run.run_id),
        ['b'],
    );
    assert.equal(finishAiRunsAnsweredBy(runs, { role: 'user', reply_to_message_id: 'request-a' }).length, 2,
        'a person replying to the request does not end the run');
    assert.equal(finishAiRunsAnsweredBy(runs, { role: 'assistant' }).length, 2);
    assert.equal(finishAiRunsAnsweredBy(runs, undefined).length, 2);
}

function testTheReadersOwnRequestIsShownOnce() {
    const messages = [
        { id: 'm-0', role: 'assistant', content: 'earlier' },
        {
            id: 'pending-user-1', role: 'user', content: '@Watch Officer status?',
            timestamp: new Date(NOW - 3000).toISOString(),
            metadata: { ai_invocation_target: { target_type: 'agent', display_name: 'Watch Officer' } },
        },
    ];
    const local = localAiRun({ messages, currentUserId: 'u-me', now: NOW });
    assert.equal(local.display_name, 'Watch Officer');
    assert.equal(local.target_type, 'agent');
    assert.equal(local.step, '', 'steps come from the server, already in plain words');
    assert.equal(local.startedAt, NOW - 3000);
    assert.equal(local.request_message_id, 'pending-user-1');
    assert.equal(describeAiActivityRun(local, 'u-me'), 'Watch Officer is working for you');
    assert.equal(localAiRun({ messages: [], currentUserId: 'u-me', now: NOW }), null);

    // Somebody else writing while the request runs does not take over the reader's line.
    const withReply = [...messages, {
        id: 'm-sam', role: 'user', content: 'on it', timestamp: new Date(NOW - 1000).toISOString(),
        sender: { user_id: 'u-sam', display_name: 'Sam Lee' },
    }];
    assert.equal(localAiRun({ messages: withReply, currentUserId: 'u-me', now: NOW }).request_message_id,
        'pending-user-1');
    const echoed = [{ ...messages[1], id: 'm-echo', sender: { user_id: 'u-me' }, timestamp: '2020-01-01T00:00:00Z' }];
    assert.equal(localAiRun({ messages: echoed, currentUserId: 'u-me', now: NOW }).startedAt, NOW,
        'an implausibly old timestamp does not start the timer hours ago');

    const someoneElse = applyAiActivityEvent([], started('a'), NOW);
    assert.equal(describeAiActivityRun(someoneElse[0], 'u-me'), 'Watch Officer is working for Sam Lee');
    assert.deepEqual(visibleAiRuns(someoneElse, local, 'u-me', NOW).map((run) => run.run_id), ['a', 'local']);

    const mine = applyAiActivityEvent(someoneElse, started('mine', {
        requested_by: { user_id: 'u-me', display_name: 'Pat' },
    }), NOW);
    assert.deepEqual(visibleAiRuns(mine, local, 'u-me', NOW).map((run) => run.run_id), ['a', 'mine'],
        'once the broadcast arrives the local line goes, so the request is not listed twice');
    assert.equal(describeAiActivityRun(mine[1], 'u-me'), 'Watch Officer is working for you');
    assert.equal(
        describeAiActivityRun({ ...mine[1], requested_by: { user_id: '', display_name: '' } }, 'u-me'),
        'Watch Officer is working',
    );
}

function testElapsedFormatting() {
    assert.equal(formatAiActivityElapsed(0), '0:00');
    assert.equal(formatAiActivityElapsed(42_400), '0:42');
    assert.equal(formatAiActivityElapsed(245_000), '4:05');
    assert.equal(formatAiActivityElapsed(3_729_000), '1:02:09');
    assert.equal(formatAiActivityElapsed(-5000), '0:00');
}

function testDispatchDeliversActivityEvents() {
    const received = [];
    const conversationUpdates = [];
    const handlers = {
        onAiActivity: (event) => received.push(event),
        onConversationUpdated: (conversation) => conversationUpdates.push(conversation),
    };
    dispatchCollaborationEvent({
        conversation_id: 'c-1', event_type: 'collaboration.ai.started', occurred_at: '2026-05-01T12:00:00+00:00',
        payload: { run: { run_id: 'a', display_name: 'Watch Officer' }, conversation: { id: 'c-1' } },
    }, handlers);
    dispatchCollaborationEvent({
        conversation_id: 'c-1', event_type: 'collaboration.ai.progress', occurred_at: '2026-05-01T12:00:01',
        payload: { run: { run_id: 'a', step: 'Calling search' } },
    }, handlers, true);
    dispatchCollaborationEvent({
        conversation_id: 'c-1', event_type: 'collaboration.ai.finished', payload: { run: ['not', 'a', 'run'] },
    }, handlers);

    assert.equal(received.length, 2, 'a malformed run is ignored');
    assert.equal(received[0].kind, 'started');
    assert.equal(received[0].replayed, false);
    assert.equal(received[0].occurredAt, NOW);
    assert.equal(received[1].kind, 'progress');
    assert.equal(received[1].replayed, true);
    assert.equal(received[1].occurredAt, NOW + 1000, 'a bare server timestamp is read as UTC');
    assert.deepEqual(conversationUpdates, [], 'activity events never touch the conversation');
}

const tests = [
    testLiveEventsBuildTheRunningList,
    testReplayRebuildsOnlyRunsStillGoing,
    testAnAnswerClosesItsRun,
    testTheReadersOwnRequestIsShownOnce,
    testElapsedFormatting,
    testDispatchDeliversActivityEvents,
];

for (const test of tests) {
    test();
    console.log(`passed: ${test.name}`);
}
console.log(`${tests.length} AI activity checks passed`);
