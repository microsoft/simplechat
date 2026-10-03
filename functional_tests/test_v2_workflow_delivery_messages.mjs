// test_v2_workflow_delivery_messages.mjs
// Version: 0.261.230
// Implemented in: 0.261.230
// Executes the pure helpers behind the messages a chat-started workflow run posts back to the chat
// that started it (phase 6b): how a posted message is recognised (the server's own test, the id
// prefix or the metadata key), how its metadata is read (fail closed), when its footer offers
// Follow up and when Retry (only for the same run, step and generation, and only while the
// tracker's newest read says the server would resume it), how a posted result settles as a
// workflow reply, when the open chat must wait before it is re-read, where each posted result
// lands, the chat list's running tag, and the bell's label for 6b-1's notice. The server facts the
// client mirrors are pinned against the modules that write them, so a change on either side fails
// here first.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import './test_support/tsResolve.mjs';
import {
    at,
    deliveredRow,
    deliveryMessageId,
    failedRow,
    statusResponse,
    statusRow,
} from './test_support/workflowRunStatusFixtures.mjs';

globalThis.fetch = () => {
    throw new Error('The workflow delivery helpers must not make network requests.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    WORKFLOW_DELIVERY_KINDS,
    WORKFLOW_DELIVERY_VERSION,
    isWorkflowDeliveryMessage,
    parseWorkflowDeliveryMetadata,
    planWorkflowDeliveryLanding,
    readWorkflowDelivery,
    workflowDeliveryCanRetry,
    workflowDeliveryFollowUp,
    workflowDeliveryFooterId,
    workflowDeliveryMustWait,
    workflowDeliveryReply,
    workflowDeliveryRun,
} = await import('../application/v2_ui/src/lib/workflowDelivery.ts');
const {
    WORKFLOW_DELIVERY_MESSAGE_PREFIX,
    parseWorkflowRunStatusResponse,
} = await import('../application/v2_ui/src/lib/workflowRunStatus.ts');
const { describeNotification, normalizeNotification } = await import('../application/v2_ui/src/lib/notifications.ts');
const {
    EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT,
    trackedWorkflowRun,
    useWorkflowRunTrackerStore,
    workflowRunConversationRead,
    workflowRunForAnswerStep,
    workflowRunningLabel,
    workflowRunningTagLabel,
    workflowRunsCheckedAt,
    workflowRunsForAnswer,
    workflowRunsInFlight,
} = await import('../application/v2_ui/src/stores/workflowRunTrackerStore.ts');

const SERVER_DIR = new URL('../application/single_app/', import.meta.url);
const CLIENT_DIR = new URL('../application/v2_ui/src/', import.meta.url);

function source(directory, fileName) {
    return readFileSync(new URL(fileName, directory), 'utf8').replace(/\r\n/g, '\n');
}

/** One top-level Python function, from its `def` to the next top-level `def`. */
function serverFunction(moduleSource, name) {
    const start = moduleSource.indexOf(`\ndef ${name}(`);
    assert.notEqual(start, -1, `The server no longer defines ${name}().`);
    const end = moduleSource.indexOf('\ndef ', start + 1);
    return moduleSource.slice(start, end === -1 ? undefined : end);
}

const DELIVERY_MODULE = source(SERVER_DIR, 'functions_workflow_chat_delivery.py');
const WORKER_MODULE = source(SERVER_DIR, 'functions_workflow_chat_delivery_worker.py');
const NOTIFICATIONS_MODULE = source(SERVER_DIR, 'functions_notifications.py');
const TRACKER_HOOK = source(CLIENT_DIR, 'lib/useWorkflowRunTracker.ts');
const CHAT_STORE = source(CLIENT_DIR, 'stores/chatStore.ts');

const SHA = 'a'.repeat(64);

/** The metadata 6b-1 writes on every posted message, for run `runId` of the fixtures. */
function deliveryMetadata(runId, overrides = {}) {
    return {
        version: 1,
        kind: 'result',
        workflow_id: `wf-${runId}`,
        workflow_scope: 'personal',
        run_id: runId,
        generation: 2,
        run_status: 'completed',
        orchestration_run_id: 'orun-1',
        step_id: `step-${runId}`,
        requested_at: at(0),
        ...overrides,
    };
}

/** 6a's descriptor, as a posted result carries it in `metadata.workflow_result`. */
function resultDescriptor(runId, overrides = {}) {
    return {
        version: 'workflow-result-v1',
        workflow_id: `wf-${runId}`,
        run_id: runId,
        result_sha256: SHA,
        workflow_name: 'Weekly digest',
        status: 'completed',
        completed_at: at(250),
        ...overrides,
    };
}

function parsed(metadata) {
    const value = parseWorkflowDeliveryMetadata(metadata);
    assert.ok(value, 'The fixture metadata must parse.');
    return value;
}

/** A tracker snapshot holding the rows of one status response, as the engine would publish it. */
function snapshotOf(rows, overrides = {}) {
    const runs = {};
    for (const row of parseWorkflowRunStatusResponse(statusResponse(rows)).runs) {
        runs[row.run_id] ??= { row, checkedAt: at(300), retired: false };
    }
    return {
        running: true,
        halted: false,
        available: true,
        runs,
        globalCheckedAt: at(300),
        globalError: false,
        conversations: {},
        ...overrides,
    };
}

function retire(snapshot, runId) {
    return {
        ...snapshot,
        runs: { ...snapshot.runs, [runId]: { ...snapshot.runs[runId], retired: true } },
    };
}

/** A failed run whose note was posted under generation 4, which the server would resume. */
function retryableFailedRow(runId, overrides = {}) {
    const { delivery = {}, actions = {}, ...rest } = overrides;
    return failedRow(runId, {
        runtime_version: 4,
        ...rest,
        delivery: {
            status: 'delivered',
            generation: 4,
            message_id: deliveryMessageId(runId, 4),
            delivered_at: at(250),
            ...delivery,
        },
        actions: { retry: true, ...actions },
    });
}

const failedNote = (runId, overrides = {}) =>
    parsed(deliveryMetadata(runId, { kind: 'failed', generation: 4, run_status: 'failed', ...overrides }));

test('a posted message is recognised by its id prefix or its metadata key, as the server checks it', () => {
    const prefixOnly = { id: deliveryMessageId('run-1', 2), metadata: {} };
    const metadataOnly = { id: 'assistant_123', metadata: { workflow_delivery: {} } };
    assert.equal(isWorkflowDeliveryMessage(prefixOnly), true, 'The id prefix alone marks a posted message.');
    assert.equal(isWorkflowDeliveryMessage({ id: deliveryMessageId('run-1', 2) }), true);
    assert.equal(isWorkflowDeliveryMessage(metadataOnly), true, 'The metadata key alone marks a posted message.');
    assert.equal(
        isWorkflowDeliveryMessage({ id: 'assistant_123', metadata: { workflow_delivery: { version: 99 } } }),
        true,
        'Any object under the key counts, as a Mapping does on the server, whatever it holds.',
    );
    for (const value of [null, undefined, [], ['workflow'], 'yes', 1, true]) {
        assert.equal(
            isWorkflowDeliveryMessage({ id: 'assistant_123', metadata: { workflow_delivery: value } }),
            false,
            `A workflow_delivery of ${JSON.stringify(value)} is not a Mapping.`,
        );
    }
    for (const message of [
        null,
        undefined,
        { id: 'assistant_123' },
        { id: 'assistant_123', metadata: {} },
        { id: 'assistant_123', metadata: [] },
        { id: 'assistant_123', metadata: null },
        { id: `x${deliveryMessageId('run-1', 2)}` },
        { id: deliveryMessageId('run-1', 2).toUpperCase() },
        { id: 42, metadata: {} },
    ]) {
        assert.equal(isWorkflowDeliveryMessage(message), false, `${JSON.stringify(message)} was not posted by a run.`);
    }

    const check = serverFunction(DELIVERY_MODULE, 'is_workflow_delivery_message');
    assert.match(check, /message_id\.startswith\(DELIVERY_MESSAGE_ID_PREFIX\)/);
    assert.match(check, /isinstance\(metadata\.get\(DELIVERY_METADATA_KEY\), Mapping\)/);
    assert.match(DELIVERY_MODULE, new RegExp(`\\nDELIVERY_MESSAGE_ID_PREFIX = '${WORKFLOW_DELIVERY_MESSAGE_PREFIX}'\\n`));
    assert.match(DELIVERY_MODULE, /\nDELIVERY_METADATA_KEY = 'workflow_delivery'\n/);
});

test('delivery metadata parses exactly as the server writes it, and fails closed on anything else', () => {
    const metadata = deliveryMetadata('run-1', { extra: 'ignored' });
    assert.deepEqual(parseWorkflowDeliveryMetadata(metadata), {
        version: 1,
        kind: 'result',
        workflow_id: 'wf-run-1',
        workflow_scope: 'personal',
        run_id: 'run-1',
        generation: 2,
        run_status: 'completed',
        orchestration_run_id: 'orun-1',
        step_id: 'step-run-1',
        requested_at: at(0),
    });

    const sparse = deliveryMetadata('run-1');
    for (const key of ['generation', 'run_status', 'orchestration_run_id', 'step_id', 'requested_at']) {
        delete sparse[key];
    }
    assert.deepEqual(parseWorkflowDeliveryMetadata(sparse), {
        version: 1,
        kind: 'result',
        workflow_id: 'wf-run-1',
        workflow_scope: 'personal',
        run_id: 'run-1',
        generation: null,
        run_status: null,
        orchestration_run_id: null,
        step_id: null,
        requested_at: null,
    }, 'The optional fields read as null when the server had none.');
    assert.equal(parseWorkflowDeliveryMetadata(deliveryMetadata('run-1', { generation: 0 })).generation, 0);

    for (const value of [null, undefined, [], 'workflow', 1]) {
        assert.equal(parseWorkflowDeliveryMetadata(value), null);
    }
    const invalid = {
        version: [undefined, 2, '1', 0],
        kind: [undefined, '', '   ', 3, null],
        workflow_id: [undefined, '', ' wf-1', 'wf-1 ', 'wf\u0001', 'w'.repeat(257), 5, '\ud800'],
        run_id: [undefined, '', ' run-1', 'run\u001f', 'r'.repeat(257), null],
        workflow_scope: [undefined, 'group', 'public', 'Personal'],
        generation: [-1, 1.5, '2', Number.NaN, true],
        orchestration_run_id: ['', ' orun', 5],
        step_id: ['', 'step\u0000', 5],
        run_status: [5, {}],
        requested_at: [5, []],
    };
    for (const [key, values] of Object.entries(invalid)) {
        for (const value of values) {
            const candidate = deliveryMetadata('run-1');
            if (value === undefined) {
                delete candidate[key];
            } else {
                candidate[key] = value;
            }
            assert.equal(
                parseWorkflowDeliveryMetadata(candidate),
                null,
                `A ${key} of ${JSON.stringify(value)} must not parse.`,
            );
        }
    }
    assert.equal(
        parseWorkflowDeliveryMetadata(deliveryMetadata('run-1', { workflow_id: 'w'.repeat(256) })).workflow_id.length,
        256,
        'An id of 256 characters is still one the server keeps.',
    );

    assert.equal(parseWorkflowDeliveryMetadata(deliveryMetadata('run-1', { kind: 'mystery' })).kind, 'unknown');
    assert.equal(
        parseWorkflowDeliveryMetadata(deliveryMetadata('run-1', { kind: 'expired' })).kind,
        'unknown',
        'Expired is only ever a bell notice, so a message claiming it offers Open run only.',
    );
    for (const kind of WORKFLOW_DELIVERY_KINDS) {
        assert.equal(parseWorkflowDeliveryMetadata(deliveryMetadata('run-1', { kind })).kind, kind);
    }

    assert.deepEqual(
        readWorkflowDelivery({ id: deliveryMessageId('run-1', 2), metadata: { workflow_delivery: metadata } }),
        parseWorkflowDeliveryMetadata(metadata),
    );
    for (const message of [null, undefined, {}, { metadata: null }, { metadata: [] }, { metadata: {} }]) {
        assert.equal(readWorkflowDelivery(message), null);
    }
});

test('the client\'s delivery kinds and metadata keys are the server\'s', () => {
    const serverKinds = [...DELIVERY_MODULE.matchAll(/^KIND_[A-Z_]+ = '([a-z_]+)'$/gm)].map((match) => match[1]);
    assert.ok(serverKinds.length >= 8, 'The server\'s delivery kinds could not be read.');
    assert.deepEqual(
        [...WORKFLOW_DELIVERY_KINDS, 'expired'].sort(),
        [...serverKinds].sort(),
        'Every kind the server can post is known here; only `expired`, a notice, is left out.',
    );
    assert.match(DELIVERY_MODULE, new RegExp(`\\nCHAT_DELIVERY_VERSION = ${WORKFLOW_DELIVERY_VERSION}\\n`));
    assert.match(DELIVERY_MODULE, /\nWORKFLOW_SCOPE = 'personal'\n/);

    const builder = serverFunction(DELIVERY_MODULE, 'build_delivery_metadata');
    const serverKeys = [...builder.matchAll(/^ {8}'([a-z_]+)':/gm)].map((match) => match[1]);
    assert.deepEqual(
        [...serverKeys].sort(),
        Object.keys(parseWorkflowDeliveryMetadata(deliveryMetadata('run-1'))).sort(),
        'The client reads every key the server writes, and nothing it doesn\'t.',
    );
});

test('Follow up offers a posted result\'s own descriptor, only for a result or analysis of the same run', () => {
    const metadata = (descriptor) => ({ workflow_delivery: deliveryMetadata('run-1'), workflow_result: descriptor });
    const result = parsed(deliveryMetadata('run-1'));
    const analysis = parsed(deliveryMetadata('run-1', { kind: 'analysis' }));

    const followUp = workflowDeliveryFollowUp(result, metadata(resultDescriptor('run-1')));
    assert.equal(followUp?.run_id, 'run-1');
    assert.equal(followUp?.workflow_id, 'wf-run-1');
    assert.equal(followUp?.result_sha256, SHA);
    assert.equal(followUp?.available, true);
    assert.equal(workflowDeliveryFollowUp(analysis, metadata(resultDescriptor('run-1')))?.run_id, 'run-1');
    assert.equal(
        workflowDeliveryFollowUp(result, metadata(resultDescriptor('run-1', { status: 'completed_partial' })))?.status,
        'completed_partial',
    );

    for (const kind of ['failed', 'cancelled', 'skipped', 'status', 'content_blocked', 'mystery']) {
        assert.equal(
            workflowDeliveryFollowUp(parsed(deliveryMetadata('run-1', { kind })), metadata(resultDescriptor('run-1'))),
            null,
            `A ${kind} message is not a source, even carrying a descriptor.`,
        );
    }
    for (const descriptor of [
        undefined,
        null,
        resultDescriptor('run-1', { available: false }),
        resultDescriptor('run-2'),
        resultDescriptor('run-1', { workflow_id: 'wf-other' }),
        resultDescriptor('run-1', { status: 'failed' }),
        resultDescriptor('run-1', { result_sha256: 'A'.repeat(64) }),
        resultDescriptor('run-1', { version: 'workflow-result-v2' }),
    ]) {
        assert.equal(
            workflowDeliveryFollowUp(result, metadata(descriptor)),
            null,
            `${JSON.stringify(descriptor)} is not this run's readable result.`,
        );
    }
    assert.equal(workflowDeliveryFollowUp(result, null), null);
});

test('a posted message joins the tracker\'s row only for the same chat, workflow, plan run and step', () => {
    const snapshot = snapshotOf([deliveredRow('run-1', 2, at(250))]);
    const delivery = parsed(deliveryMetadata('run-1'));
    assert.equal(workflowDeliveryRun(snapshot, delivery, 'chat-1'), snapshot.runs['run-1']);
    assert.equal(workflowDeliveryRun(snapshot, delivery, 'chat-2'), undefined, 'Another chat\'s message never joins.');
    for (const overrides of [
        { run_id: 'run-9' },
        { workflow_id: 'wf-other' },
        { orchestration_run_id: 'orun-2' },
        { orchestration_run_id: null },
        { step_id: 'step-other' },
        { step_id: null },
    ]) {
        assert.equal(
            workflowDeliveryRun(snapshot, parsed(deliveryMetadata('run-1', overrides)), 'chat-1'),
            undefined,
            `${JSON.stringify(overrides)} must not join the row.`,
        );
    }
    assert.equal(workflowDeliveryRun(EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT, delivery, 'chat-1'), undefined);
});

test('a failed run\'s note offers Retry only from the newest read of the same run and generation', () => {
    const snapshot = snapshotOf([retryableFailedRow('run-f')]);
    const note = failedNote('run-f');
    assert.equal(workflowDeliveryCanRetry(snapshot, note, 'chat-1'), true);

    // The note, not the row, decides which kinds can retry.
    for (const kind of ['result', 'analysis', 'cancelled', 'skipped', 'status', 'content_blocked', 'mystery']) {
        assert.equal(
            workflowDeliveryCanRetry(snapshot, failedNote('run-f', { kind }), 'chat-1'),
            false,
            `A ${kind} message never offers Retry.`,
        );
    }
    assert.equal(workflowDeliveryCanRetry(snapshot, failedNote('run-f', { generation: null }), 'chat-1'), false);

    // A note from an earlier generation never retries a run that has moved on.
    for (const generation of [3, 5]) {
        assert.equal(
            workflowDeliveryCanRetry(snapshot, failedNote('run-f', { generation }), 'chat-1'),
            false,
            `A generation ${generation} note doesn't match the row's generation 4.`,
        );
    }
    const reopened = snapshotOf([retryableFailedRow('run-f', { delivery: { status: 'pending', generation: null, message_id: null, delivered_at: null } })]);
    assert.equal(workflowDeliveryCanRetry(reopened, note, 'chat-1'), false);

    // The tracker must be reading, and chats must be able to start workflows.
    for (const overrides of [{ running: false }, { halted: true }, { available: false }, { available: null }]) {
        assert.equal(
            workflowDeliveryCanRetry({ ...snapshot, ...overrides }, note, 'chat-1'),
            false,
            `${JSON.stringify(overrides)} offers no Retry.`,
        );
    }
    assert.equal(workflowDeliveryCanRetry(retire(snapshot, 'run-f'), note, 'chat-1'), false);
    assert.equal(workflowDeliveryCanRetry(EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT, note, 'chat-1'), false);

    // Only the server's `actions.retry` on a failed row offers it, never the status alone.
    for (const overrides of [
        { actions: { retry: false } },
        { actions: { retry: false }, retry_blocked: 'workflow_definition_changed' },
        { actions: { retry: true }, retry_blocked: 'workflow_already_running' },
    ]) {
        assert.equal(
            workflowDeliveryCanRetry(snapshotOf([retryableFailedRow('run-f', overrides)]), note, 'chat-1'),
            false,
            `${JSON.stringify(overrides)} offers no Retry.`,
        );
    }
    const resumed = snapshotOf([statusRow('run-f', {
        runtime_version: 5,
        delivery: { status: 'delivered', generation: 4, message_id: deliveryMessageId('run-f', 4), delivered_at: at(250) },
        actions: { retry: true },
    })]);
    assert.equal(workflowDeliveryCanRetry(resumed, note, 'chat-1'), false, 'A resumed run is running again.');

    const unreadable = snapshotOf([retryableFailedRow('run-f', { status: 'mystery' })]);
    assert.equal(unreadable.runs['run-f'].row.kind, 'unavailable');
    assert.equal(workflowDeliveryCanRetry(unreadable, note, 'chat-1'), false, 'An unreadable row offers Open run only.');

    // Every part of the join must hold.
    assert.equal(workflowDeliveryCanRetry(snapshot, note, 'chat-2'), false);
    for (const overrides of [{ workflow_id: 'wf-other' }, { orchestration_run_id: 'orun-2' }, { step_id: 'step-other' }]) {
        assert.equal(workflowDeliveryCanRetry(snapshot, failedNote('run-f', overrides), 'chat-1'), false);
    }
});

test('a posted result settles as a workflow reply, keyed by the posted message', () => {
    const [row] = parseWorkflowRunStatusResponse(statusResponse([deliveredRow('run-1', 2, at(250))])).runs;
    assert.deepEqual(workflowDeliveryReply(row, 'Planning the offsite'), {
        conversationId: 'chat-1',
        messageId: deliveryMessageId('run-1', 2),
        runId: 'run-1',
        conversationTitle: 'Planning the offsite',
        blocked: false,
        source: 'workflow',
    });
    assert.equal(workflowDeliveryReply(row, null).conversationTitle, null);
    assert.equal(workflowDeliveryFooterId(row.delivery.message_id), `workflow-delivery-${deliveryMessageId('run-1', 2)}`);

    // The shell settles it through the chat store's one path, which the server marked unread.
    assert.match(
        TRACKER_HOOK,
        /settleCompletedReply\(workflowDeliveryReply\(row, [^)]*\), \{ current, serverMarksUnread: true \}\)/,
    );
    assert.doesNotMatch(TRACKER_HOOK, /announceCompletedReply|setConversationUnread|markWatchedReplyRead|deferReplyRead/);
    assert.doesNotMatch(TRACKER_HOOK, /source: '(chat|orchestration)'/);
    assert.doesNotMatch(TRACKER_HOOK, /\bfetch\(|\bapi\.(get|post|put|patch|delete)\(/, 'The hook adds no request of its own.');
    assert.match(CHAT_STORE, /export function settleCompletedReply\(/);
    assert.equal(CHAT_STORE.match(/announceCompletedReply\(/g)?.length, 1, 'The store announces replies in one place.');
});

test('the open chat is re-read only once it is quiet', () => {
    const quiet = { streaming: false, messagesLoading: false, orchestrationActive: false };
    assert.equal(workflowDeliveryMustWait(quiet), false);
    for (const key of Object.keys(quiet)) {
        assert.equal(workflowDeliveryMustWait({ ...quiet, [key]: true }), true, `${key} must hold the re-read.`);
    }
    assert.match(TRACKER_HOOK, /orchestrationActive: hasActiveOrchestration\(conversationId\)/);
    assert.match(TRACKER_HOOK, /planWorkflowDeliveryLanding\(waitingDeliveries, openId, openId !== null && chatIsBusy\(openId\)\)/);
    assert.match(TRACKER_HOOK, /await useChatStore\.getState\(\)\.reloadMessages\(\);/);
});

test('each posted result lands in its own chat: another chat\'s now, the open chat\'s after one quiet re-read', () => {
    const rows = [
        { conversation_id: 'chat-1', run_id: 'a' },
        { conversation_id: 'chat-2', run_id: 'b' },
        { conversation_id: 'chat-1', run_id: 'c' },
        { conversation_id: 'chat-3', run_id: 'd' },
    ];
    const ids = (list) => list.map((row) => row.run_id);
    const plan = (openId, busy) => {
        const landing = planWorkflowDeliveryLanding(rows, openId, busy);
        return { elsewhere: ids(landing.elsewhere), reloadNow: ids(landing.reloadNow), waiting: ids(landing.waiting) };
    };

    assert.deepEqual(plan('chat-1', false), { elsewhere: ['b', 'd'], reloadNow: ['a', 'c'], waiting: [] });
    assert.deepEqual(
        plan('chat-1', true),
        { elsewhere: ['b', 'd'], reloadNow: [], waiting: ['a', 'c'] },
        'A busy open chat is never re-read mid-stream.',
    );
    for (const busy of [false, true]) {
        assert.deepEqual(plan(null, busy), { elsewhere: ['a', 'b', 'c', 'd'], reloadNow: [], waiting: [] });
        assert.deepEqual(plan('chat-9', busy), { elsewhere: ['a', 'b', 'c', 'd'], reloadNow: [], waiting: [] });
    }
    assert.deepEqual(planWorkflowDeliveryLanding([], 'chat-1', false), { elsewhere: [], reloadNow: [], waiting: [] });
});

test('the chat list\'s running tag reads only the tracker\'s state, and gives way once a result is posted', () => {
    const snapshot = snapshotOf([
        statusRow('run-b', { requested_at: at(20), workflow_name: 'Inbox sweep' }),
        statusRow('run-a', { requested_at: at(20) }),
        statusRow('run-c', { requested_at: at(10), status: 'completed', phase: 'finished', completed_at: at(200) }),
        deliveredRow('run-d', 1, at(250)),
        statusRow('run-e', { status: 'mystery' }),
        statusRow('run-f', { conversation_id: 'chat-2', workflow_name: 'Digest for chat two' }),
        statusRow('run-g', { status: 'completed', phase: 'finished', completed_at: at(200), delivery: { status: 'undeliverable', generation: 2, reason: 'chat_unavailable' } }),
        statusRow('run-h'),
    ]);
    const inFlight = retire(snapshot, 'run-h');

    assert.deepEqual(
        workflowRunsInFlight(inFlight, 'chat-1').map((tracked) => tracked.row.run_id),
        ['run-c', 'run-a', 'run-b'],
        'Running, or finished and still being posted; oldest request first, then by run id.',
    );
    assert.equal(workflowRunningLabel(inFlight, 'chat-1'), 'Running 3 workflows');
    assert.equal(workflowRunningLabel(inFlight, 'chat-2'), 'Running Digest for chat two');
    assert.equal(workflowRunningLabel(inFlight, 'chat-3'), '');
    for (const conversationId of [null, undefined, '']) {
        assert.deepEqual(workflowRunsInFlight(inFlight, conversationId), []);
        assert.equal(workflowRunningLabel(inFlight, conversationId), '');
    }

    const single = snapshotOf([statusRow('run-1'), deliveredRow('run-2', 1, at(250))]);
    assert.equal(workflowRunningTagLabel(single, 'chat-1'), 'Running Weekly digest');
    const posted = snapshotOf([deliveredRow('run-1', 1, at(250)), deliveredRow('run-2', 1, at(250))]);
    assert.equal(workflowRunningTagLabel(posted, 'chat-1'), '', 'A posted result leaves the unread dot alone.');
    assert.equal(workflowRunningTagLabel({ ...single, halted: true }, 'chat-1'), '');
    assert.equal(workflowRunningTagLabel({ ...single, running: false }, 'chat-1'), '');
    assert.equal(workflowRunningTagLabel(EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT, 'chat-1'), '');
});

test('a plan answer finds its own runs, and each step its own run, or nothing', () => {
    const snapshot = snapshotOf([
        statusRow('run-2', { requested_at: at(20) }),
        statusRow('run-1', { requested_at: at(10) }),
        deliveredRow('run-3', 1, at(250), { requested_at: at(30) }),
        statusRow('run-4', { orchestration_run_id: 'orun-2' }),
        statusRow('run-5', { conversation_id: 'chat-2' }),
    ]);
    assert.deepEqual(
        workflowRunsForAnswer(snapshot, 'chat-1', 'orun-1').map((tracked) => tracked.row.run_id),
        ['run-1', 'run-2', 'run-3'],
    );
    for (const [conversationId, orchestrationRunId] of [[null, 'orun-1'], ['chat-1', null], ['chat-1', undefined]]) {
        assert.deepEqual(workflowRunsForAnswer(snapshot, conversationId, orchestrationRunId), []);
    }

    const step = { stepId: 'step-run-1', workflowId: 'wf-run-1', runId: 'run-1' };
    assert.equal(workflowRunForAnswerStep(snapshot, 'chat-1', 'orun-1', step), snapshot.runs['run-1']);
    for (const [conversationId, orchestrationRunId, stepOverrides] of [
        ['chat-2', 'orun-1', {}],
        ['chat-1', 'orun-2', {}],
        [null, 'orun-1', {}],
        ['chat-1', null, {}],
        ['chat-1', 'orun-1', { stepId: 'step-run-2' }],
        ['chat-1', 'orun-1', { workflowId: 'wf-run-2' }],
        ['chat-1', 'orun-1', { runId: 'run-9' }],
    ]) {
        assert.equal(
            workflowRunForAnswerStep(snapshot, conversationId, orchestrationRunId, { ...step, ...stepOverrides }),
            undefined,
            `${JSON.stringify([conversationId, orchestrationRunId, stepOverrides])} must not match.`,
        );
    }

    assert.equal(trackedWorkflowRun(snapshot, 'run-1'), snapshot.runs['run-1']);
    for (const runId of [null, undefined, '', 'run-9']) {
        assert.equal(trackedWorkflowRun(snapshot, runId), undefined);
    }
});

test('a chat\'s own reads and the newest check time come from the tracker\'s state', () => {
    const read = { checkedAt: at(120), reading: false, error: null };
    const snapshot = { ...EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT, conversations: { 'chat-1': read } };
    assert.equal(workflowRunConversationRead(snapshot, 'chat-1'), read);
    for (const conversationId of ['chat-2', null, undefined, '']) {
        assert.deepEqual(workflowRunConversationRead(snapshot, conversationId), { checkedAt: null, reading: false, error: null });
    }

    assert.equal(workflowRunsCheckedAt(EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT, 'chat-1'), null);
    assert.equal(workflowRunsCheckedAt({ ...snapshot, globalCheckedAt: null }, 'chat-1'), at(120));
    assert.equal(workflowRunsCheckedAt({ ...snapshot, globalCheckedAt: at(60) }, 'chat-1'), at(120));
    assert.equal(workflowRunsCheckedAt({ ...snapshot, globalCheckedAt: at(180) }, 'chat-1'), at(180));
    assert.equal(workflowRunsCheckedAt({ ...snapshot, globalCheckedAt: at(180) }, 'chat-2'), at(180));

    assert.equal(Object.isFrozen(EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT), true);
    assert.equal(EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT.running, false);
    assert.equal(EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT.available, null);
    const published = snapshotOf([statusRow('run-1')]);
    useWorkflowRunTrackerStore.getState().publish(published);
    assert.equal(useWorkflowRunTrackerStore.getState().snapshot, published);
    useWorkflowRunTrackerStore.getState().reset();
    assert.equal(useWorkflowRunTrackerStore.getState().snapshot, EMPTY_WORKFLOW_RUN_TRACKER_SNAPSHOT);
});

test('the bell names 6b-1\'s notice as workflow results, in the tone the server gives it', () => {
    const notice = (overrides = {}) => normalizeNotification({
        id: 'notice-1',
        notification_type: 'workflow_chat_delivery',
        title: '"Weekly digest" didn\'t finish',
        message: 'The chat that started this run can\'t show it anymore. Open the run in Workflows to see the details.',
        type_config: { icon: 'bi-activity', color: 'info' },
        link_url: '/workflow-activity?workflowId=wf-1&runId=run-1&scope=personal',
        metadata: { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal', delivery_status: 'undeliverable' },
        ...overrides,
    });
    assert.deepEqual(describeNotification(notice()), { kind: 'workflow', label: 'Workflow results', tone: 'info' });
    assert.deepEqual(
        describeNotification(notice({ category: 'failure' })),
        { kind: 'workflow', label: 'Workflow results', tone: 'info' },
        'Unlike a priority alert, the label never depends on a category.',
    );
    assert.deepEqual(
        describeNotification(notice({ notification_type: 'chat_response_complete', type_config: { color: 'success' } })),
        { kind: 'reply', label: 'AI responded', tone: 'ok' },
        'A posted result\'s own notice is the ordinary reply notice.',
    );

    assert.match(NOTIFICATIONS_MODULE, /\nWORKFLOW_CHAT_DELIVERY_NOTIFICATION_TYPE = 'workflow_chat_delivery'\n/);
    assert.match(
        NOTIFICATIONS_MODULE,
        /\n {4}WORKFLOW_CHAT_DELIVERY_NOTIFICATION_TYPE: \{\n {8}'icon': 'bi-activity',\n {8}'color': 'info'\n {4}\},/,
    );
    assert.match(DELIVERY_MODULE, /\nNOTIFICATION_TYPE = 'workflow_chat_delivery'\n/);
    assert.match(serverFunction(WORKER_MODULE, '_send_notice'), /notification_type=NOTIFICATION_TYPE,/);
    assert.match(serverFunction(WORKER_MODULE, '_send_chat_notice'), /\.create_chat_response_notification\(/);
});
