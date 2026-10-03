// test_v2_workflow_run_status.mjs
// Version: 0.261.230
// Implemented in: 0.261.230
// Executes the V2 client's reading of 6b-1's chat-started workflow run status route
// (GET /api/v2/orchestration/workflow-runs/status): the response envelope, the rows dropped for ids
// that can't be used, the rows that fail closed to "Status unavailable" for any value outside the
// server's closed sets, the exact projection a good row keeps, the controls each row offers (Retry
// only from `actions.retry` on a failed run, never from the status alone), the fixed texts, the
// step and elapsed formatting, the id checks, the one batched request, and the closed sets and the
// status-to-phase pairing pinned against the server module that writes them.

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

function refuseNetwork() {
    throw new Error('Only the request tests may reach the network, through their own stub.');
}

globalThis.fetch = refuseNetwork;

// The repository resolver must be registered before extensionless TypeScript imports load.
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');
const {
    WORKFLOW_DELIVERY_MESSAGE_PREFIX,
    WORKFLOW_DELIVERY_REASONS,
    WORKFLOW_DELIVERY_ROW_STATUSES,
    WORKFLOW_FAILURE_CODES,
    WORKFLOW_RESULTS_IN_HISTORY_TEXT,
    WORKFLOW_RESULTS_POSTED_ELSEWHERE_TEXT,
    WORKFLOW_RESULTS_POSTED_TEXT,
    WORKFLOW_RESULTS_POSTING_TEXT,
    WORKFLOW_RETRY_BLOCKED_CODES,
    WORKFLOW_RETRY_TURNED_OFF_TEXT,
    WORKFLOW_RUN_CANCELLED_TEXT,
    WORKFLOW_RUN_ROW_PHASES,
    WORKFLOW_RUN_ROW_STATUSES,
    WORKFLOW_RUN_STATUS_INVALID_RESPONSE,
    WORKFLOW_RUN_STATUS_PATH,
    WORKFLOW_RUN_STATUS_UNAVAILABLE,
    WORKFLOW_STATUS_HALTED_TEXT,
    WORKFLOW_STATUS_READ_ERROR_TEXT,
    WORKFLOW_WAITING_ACTIONS,
    WORKFLOW_WAITING_REASONS,
    fetchWorkflowRunStatus,
    formatCheckedTime,
    formatWorkflowElapsed,
    isStatusConversationId,
    isWorkflowRunActive,
    isWorkflowRunIdentifier,
    isWorkflowRunInFlight,
    parseWorkflowRunStatusResponse,
    workflowRetryBlockedText,
    workflowRunRowControls,
    workflowRunStatusLabel,
    workflowRunStepLabel,
    workflowRunStepText,
    workflowWaitingText,
} = await import('../application/v2_ui/src/lib/workflowRunStatus.ts');

const APPROVAL = { reason: 'approval', action: 'approve', gate_id: 'gate-1' };
const RECOVERY = { reason: 'recovery', action: 'open_run', gate_id: null };
const RECONNECT = { reason: 'microsoft_365_reconnect', action: 'reconnect', gate_id: null };
const NO_CONTROLS = { cancel: false, retry: false, retryTurnedOff: false, approve: false, reconnect: false, openRun: true };

function parseRuns(rows) {
    return parseWorkflowRunStatusResponse(statusResponse(rows)).runs;
}

function parseRow(row) {
    const runs = parseRuns([row]);
    assert.equal(runs.length, 1, 'the row is kept');
    return runs[0];
}

function waitingRow(runId, waiting, overrides = {}) {
    return statusRow(runId, { status: 'waiting', phase: 'needs_you', waiting, ...overrides });
}

function expiredRow(runId, overrides = {}) {
    const { delivery = {}, actions = {}, ...rest } = overrides;
    return statusRow(runId, {
        status: 'expired',
        phase: 'failed',
        error: 'It reached its time limit.',
        error_code: 'deadline_exceeded',
        ...rest,
        delivery: { status: 'expired', reason: 'deadline_exceeded', ...delivery },
        actions: { cancel: false, ...actions },
    });
}

function cancelledRow(runId, overrides = {}) {
    const { delivery = {}, actions = {}, ...rest } = overrides;
    return statusRow(runId, {
        status: 'cancelled',
        phase: 'cancelled',
        completed_at: at(200),
        ...rest,
        delivery,
        actions: { cancel: false, ...actions },
    });
}

/** A copy of `row` with one change made by `mutate`, so a case can delete a key outright. */
function rowWith(mutate, row = statusRow('run-1')) {
    const copy = structuredClone(row);
    mutate(copy);
    return copy;
}

/** What "Status unavailable" keeps of statusRow('run-1'): its identity and nothing else. */
function unavailableRow(overrides = {}) {
    return {
        workflow_id: 'wf-run-1',
        workflow_scope: 'personal',
        run_id: 'run-1',
        conversation_id: 'chat-1',
        orchestration_run_id: 'orun-1',
        step_id: 'step-run-1',
        workflow_name: 'Weekly digest',
        requested_at: at(0),
        kind: 'unavailable',
        ...overrides,
    };
}

function jsonResponse(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

// ----- The server module the route is built from, read as text so nothing has to import it. -----

const SERVER_DIR = new URL('../application/single_app/', import.meta.url);

function serverSource(fileName) {
    return readFileSync(new URL(fileName, SERVER_DIR), 'utf8').replace(/\r\n/g, '\n');
}

const STATUS_MODULE = serverSource('functions_workflow_chat_delivery_status.py');
const DELIVERY_MODULE = serverSource('functions_workflow_chat_delivery.py');
const ROUTE_MODULE = serverSource('route_backend_orchestration.py');

function serverStringConstants() {
    const constants = new Map();
    for (const source of [DELIVERY_MODULE, STATUS_MODULE]) {
        for (const [, name, value] of source.matchAll(/^(_?[A-Z][A-Z0-9_]*) = '([^'\n]*)'$/gm)) {
            constants.set(name, value);
        }
    }
    return constants;
}

const SERVER_CONSTANTS = serverStringConstants();

function serverValue(token) {
    assert.ok(SERVER_CONSTANTS.has(token), `${token} is a string constant in the server modules`);
    return SERVER_CONSTANTS.get(token);
}

/** The strings in a module-level tuple or frozenset, with named constants resolved. */
function serverCollection(source, name) {
    const match = source.match(new RegExp(`^${name} = (?:frozenset\\()?[({]([^)}]*)[)}]`, 'm'));
    assert.ok(match, `${name} is a module-level tuple or frozenset in the server module`);
    return [...match[1].matchAll(/'([^'\n]*)'|\b([A-Z][A-Z0-9_]*)\b/g)]
        .map(([, literal, constant]) => (literal !== undefined ? literal : serverValue(constant)));
}

function serverFunction(source, name) {
    const start = source.indexOf(`\ndef ${name}(`);
    assert.notEqual(start, -1, `${name} is defined in the server module`);
    const end = source.indexOf('\ndef ', start + 1);
    return source.slice(start, end === -1 ? undefined : end);
}

function serverInteger(source, name) {
    const match = source.match(new RegExp(`^${name} = (\\d+)$`, 'm'));
    assert.ok(match, `${name} is an integer constant in the server module`);
    return Number(match[1]);
}

/** The one phase the server writes with each status, read from `_status_and_phase`. */
function serverPhaseForStatus() {
    const body = serverFunction(STATUS_MODULE, '_status_and_phase');
    const phases = {};
    for (const [, condition = '', status, phase] of body.matchAll(
        /(?:if ([^\n]+):\n\s+)?return (state|'[a-z_]+'), '([a-z_]+)'/g,
    )) {
        if (status !== 'state') {
            phases[status.slice(1, -1)] = phase;
            continue;
        }
        const inline = condition.match(/^state in \(([^)]*)\)$/);
        const named = condition.match(/^state in ([A-Z][A-Z0-9_]*)$/);
        assert.ok(inline || named, `the condition "${condition}" names the states it passes through`);
        const states = inline
            ? [...inline[1].matchAll(/'([a-z_]+)'/g)].map((item) => item[1])
            : serverCollection(DELIVERY_MODULE, named[1]);
        for (const state of states) {
            phases[state] = phase;
        }
    }
    return phases;
}

function sorted(values) {
    return [...values].sort();
}

// ----- The closed sets -----

test('every closed set the client accepts is exactly the one the server writes', () => {
    assert.deepEqual(sorted(WORKFLOW_RUN_ROW_STATUSES), sorted(serverCollection(STATUS_MODULE, 'ROW_STATUSES')));
    assert.deepEqual(sorted(WORKFLOW_RUN_ROW_PHASES), sorted(serverCollection(STATUS_MODULE, 'ROW_PHASES')));
    assert.deepEqual(
        sorted(WORKFLOW_DELIVERY_ROW_STATUSES),
        sorted(serverCollection(STATUS_MODULE, 'DELIVERY_ROW_STATUSES')),
    );
    assert.deepEqual(sorted(WORKFLOW_DELIVERY_REASONS), sorted(serverCollection(STATUS_MODULE, 'DELIVERY_REASONS')));
    assert.deepEqual(
        sorted(WORKFLOW_RETRY_BLOCKED_CODES),
        sorted(serverCollection(STATUS_MODULE, 'RETRY_BLOCKED_CODES')),
    );

    const failureBlock = DELIVERY_MODULE.match(/^_FAILURE_REASONS = \{\n([\s\S]*?)\n\}/m);
    assert.ok(failureBlock, '_FAILURE_REASONS is a module-level dict');
    const failureCodes = [...failureBlock[1].matchAll(/^\s+(?:'([a-z0-9_]+)'|([A-Z][A-Z0-9_]*)):/gm)]
        .map(([, literal, constant]) => literal ?? serverValue(constant));
    assert.deepEqual(sorted(WORKFLOW_FAILURE_CODES), sorted(failureCodes));

    const waitingBody = serverFunction(STATUS_MODULE, '_waiting');
    const waitingReasons = new Set([...waitingBody.matchAll(/reason, action = '([a-z0-9_]+)'/g)].map((item) => item[1]));
    for (const [, constant, literal] of waitingBody.matchAll(/reason = ([A-Z][A-Z0-9_]*) if [^\n]* else '([a-z0-9_]+)'/g)) {
        waitingReasons.add(serverValue(constant));
        waitingReasons.add(literal);
    }
    assert.deepEqual(sorted(WORKFLOW_WAITING_REASONS), sorted(waitingReasons));
    const waitingActions = [...SERVER_CONSTANTS]
        .filter(([name]) => name.startsWith('WAITING_ACTION_'))
        .map(([, value]) => value);
    assert.deepEqual(sorted(WORKFLOW_WAITING_ACTIONS), sorted(waitingActions));

    assert.equal(WORKFLOW_DELIVERY_MESSAGE_PREFIX, serverValue('DELIVERY_MESSAGE_ID_PREFIX'));
    assert.equal(serverValue('_SECONDS_FORMAT'), '%Y-%m-%dT%H:%M:%SZ');
    assert.equal(serverInteger(STATUS_MODULE, '_ID_MAX_LENGTH'), 256);
    assert.equal(serverInteger(DELIVERY_MODULE, 'NAME_MAX_LENGTH'), 80);
    assert.ok(STATUS_MODULE.includes("_CONVERSATION_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')"));
    assert.ok(ROUTE_MODULE.includes(`@bp.route("${WORKFLOW_RUN_STATUS_PATH}", methods=["GET"])`));
});

test('each status is read only with the one phase the server pairs it with', () => {
    const serverPhases = serverPhaseForStatus();
    assert.deepEqual(serverPhases, {
        expired: 'failed',
        queued: 'running',
        running: 'running',
        completed: 'finished',
        completed_partial: 'finished',
        failed: 'failed',
        cancelled: 'cancelled',
        waiting: 'needs_you',
    });
    assert.deepEqual(sorted(Object.keys(serverPhases)), sorted(WORKFLOW_RUN_ROW_STATUSES));

    for (const status of WORKFLOW_RUN_ROW_STATUSES) {
        for (const phase of WORKFLOW_RUN_ROW_PHASES) {
            const row = statusRow('run-1', {
                status,
                phase,
                ...(status === 'waiting' ? { waiting: APPROVAL } : {}),
                ...(status === 'failed' || status === 'expired'
                    ? { error: 'It stopped.', error_code: status === 'expired' ? 'deadline_exceeded' : 'failed' }
                    : {}),
            });
            const expected = phase === serverPhases[status] ? 'status' : 'unavailable';
            assert.equal(parseRow(row).kind, expected, `${status} with ${phase}`);
        }
    }
});

// ----- The envelope -----

test('a response that is not the route envelope is refused as a whole', () => {
    const good = statusResponse([statusRow('run-1')]);
    const broken = [
        null,
        undefined,
        'text',
        42,
        [],
        [good],
        { ...good, available: 'true' },
        { ...good, available: undefined },
        { ...good, truncated: 0 },
        { ...good, truncated: undefined },
        { ...good, runs: {} },
        { ...good, runs: null },
        { ...good, runs: undefined },
        { ...good, checked_at: '2026-01-05T09:05:00.123Z' },
        { ...good, checked_at: '2026-01-05T09:05:00+00:00' },
        { ...good, checked_at: '2026-01-05 09:05:00Z' },
        { ...good, checked_at: '2026-13-05T09:05:00Z' },
        { ...good, checked_at: '2026-01-05' },
        { ...good, checked_at: null },
        { ...good, checked_at: Date.parse(at(300)) },
    ];
    for (const value of broken) {
        assert.throws(() => parseWorkflowRunStatusResponse(value), { message: WORKFLOW_RUN_STATUS_INVALID_RESPONSE });
    }
});

test('a good envelope keeps exactly its four fields', () => {
    const parsed = parseWorkflowRunStatusResponse({
        ...statusResponse([], { available: false, truncated: true }),
        debug: '<img src=x onerror=alert(1)>',
    });
    assert.deepEqual(parsed, { available: false, runs: [], checked_at: at(300), truncated: true });
});

// ----- Rows dropped for their ids -----

test('a row whose ids cannot be used is dropped, and does not claim its run id', () => {
    const dropped = [
        null,
        'run-x',
        7,
        [statusRow('run-x')],
        statusRow('run-x', { workflow_id: '' }),
        statusRow('run-x', { workflow_id: ' wf-run-x' }),
        statusRow('run-x', { workflow_id: 7 }),
        statusRow('run-x', { conversation_id: undefined }),
        statusRow('run-x', { conversation_id: 'chat\u0007' }),
        statusRow('run-x', { orchestration_run_id: undefined }),
        statusRow('run-x', { orchestration_run_id: '' }),
        statusRow('run-x', { step_id: undefined }),
        statusRow('run-x', { step_id: 12 }),
        statusRow('run-x', { workflow_scope: 'group' }),
        statusRow('run-x', { workflow_scope: undefined }),
        statusRow('x'.repeat(257)),
        statusRow('run\ud800x'),
    ];
    const kept = statusRow('run-x', { workflow_name: 'Kept' });
    const runs = parseRuns([...dropped, kept]);
    assert.equal(runs.length, 1);
    assert.equal(runs[0].kind, 'status');
    assert.equal(runs[0].workflow_name, 'Kept');
});

test('a run with no plan run or step id is kept, tracked but joined to no answer', () => {
    const row = parseRow(statusRow('run-1', { orchestration_run_id: null, step_id: null }));
    assert.equal(row.kind, 'status');
    assert.equal(row.orchestration_run_id, null);
    assert.equal(row.step_id, null);
});

test('the first row for a run wins, because the route lists the newest request first', () => {
    const runs = parseRuns([
        statusRow('run-1', { workflow_name: 'Newest' }),
        statusRow('run-1', { workflow_name: 'Older' }),
        statusRow('run-2'),
    ]);
    assert.deepEqual(runs.map((row) => [row.run_id, row.workflow_name]), [
        ['run-1', 'Newest'],
        ['run-2', 'Weekly digest'],
    ]);

    // An unreadable newest row is not replaced by an older one that might be stale.
    const unreadable = parseRuns([statusRow('run-1', { status: 'mystery' }), statusRow('run-1')]);
    assert.equal(unreadable.length, 1);
    assert.equal(unreadable[0].kind, 'unavailable');
});

// ----- The exact projection -----

test('a good row keeps exactly the route projection, and nothing else it was sent', () => {
    const sent = waitingRow('run-1', { ...APPROVAL, debug: 'x' }, {
        step_label: 'Collect files',
        delivery: { debug: 'x' },
        actions: { approve: true, debug: true },
        debug: '<img src=x onerror=alert(1)>',
        raw_error: 'Traceback (most recent call last)',
    });
    assert.deepEqual(parseRow(sent), {
        workflow_id: 'wf-run-1',
        workflow_scope: 'personal',
        run_id: 'run-1',
        conversation_id: 'chat-1',
        orchestration_run_id: 'orun-1',
        step_id: 'step-run-1',
        workflow_name: 'Weekly digest',
        requested_at: at(0),
        kind: 'status',
        status: 'waiting',
        phase: 'needs_you',
        runtime_version: 3,
        step_index: 1,
        step_count: 4,
        step_label: 'Collect files',
        started_at: at(5),
        completed_at: null,
        elapsed_seconds: 95,
        waiting: { reason: 'approval', action: 'approve', gate_id: 'gate-1' },
        delivery: { status: 'pending', generation: null, message_id: null, delivered_at: null, reason: null },
        error: null,
        error_code: null,
        retry_blocked: null,
        actions: { cancel: true, retry: false, approve: true, open_run: true },
        live: true,
    });

    const delivered = parseRow(deliveredRow('run-2', 4, at(250)));
    assert.deepEqual(delivered.delivery, {
        status: 'delivered',
        generation: 4,
        message_id: deliveryMessageId('run-2', 4),
        delivered_at: at(250),
        reason: null,
    });
    assert.equal(delivered.status, 'completed');
    assert.equal(delivered.phase, 'finished');
});

test('values the contract allows to be empty are read, not refused', () => {
    const row = parseRow(statusRow('run-1', {
        requested_at: null,
        started_at: null,
        elapsed_seconds: null,
        runtime_version: null,
        step_index: null,
        step_count: null,
        live: false,
    }));
    assert.equal(row.kind, 'status');
    assert.equal(row.requested_at, null);
    assert.equal(row.runtime_version, null);
    assert.equal(row.live, false);

    const approvalWithoutGate = parseRow(waitingRow('run-1', { ...APPROVAL, gate_id: null }));
    assert.equal(approvalWithoutGate.kind, 'status');
    assert.equal(approvalWithoutGate.waiting.gate_id, null);

    const undeliverable = parseRow(deliveredRow('run-1', 2, at(250), {
        delivery: { status: 'undeliverable', message_id: null, delivered_at: null, reason: 'chat_unavailable' },
    }));
    assert.deepEqual(undeliverable.delivery, {
        status: 'undeliverable',
        generation: 2,
        message_id: null,
        delivered_at: null,
        reason: 'chat_unavailable',
    });
});

// ----- Rows that fail closed -----

test('a row with any value outside the closed contract shows "Status unavailable" with only its identity', () => {
    const failed = failedRow('run-1');
    const cases = [
        ['an unknown status', (row) => { row.status = 'paused'; }],
        ['a missing status', (row) => { delete row.status; }],
        ['a phase the server never pairs with the status', (row) => { row.phase = 'finished'; }],
        ['an unknown phase', (row) => { row.phase = 'thinking'; }],
        ['a waiting run in the running phase', (row) => { row.status = 'waiting'; row.waiting = APPROVAL; }],
        ['a fractional runtime version', (row) => { row.runtime_version = 1.5; }],
        ['a negative runtime version', (row) => { row.runtime_version = -1; }],
        ['a runtime version sent as text', (row) => { row.runtime_version = '3'; }],
        ['a missing step index', (row) => { delete row.step_index; }],
        ['a step count sent as text', (row) => { row.step_count = '4'; }],
        ['negative elapsed seconds', (row) => { row.elapsed_seconds = -5; }],
        ['a step label that is not text', (row) => { row.step_label = 5; }],
        ['a start time with milliseconds', (row) => { row.started_at = '2026-01-05T09:00:05.000Z'; }],
        ['a start time with an offset', (row) => { row.started_at = '2026-01-05T09:00:05+00:00'; }],
        ['a completion time that is not a time', (row) => { row.completed_at = 'yesterday'; }],
        ['a missing live flag', (row) => { delete row.live; }],
        ['a live flag sent as text', (row) => { row.live = 'true'; }],
        ['an unknown waiting reason', (row) => { row.waiting = { ...RECOVERY, reason: 'coffee' }; }],
        ['an unknown waiting action', (row) => { row.waiting = { ...RECOVERY, action: 'approve_all' }; }],
        ['an empty gate id', (row) => { row.waiting = { ...APPROVAL, gate_id: '' }; }],
        ['a missing gate id', (row) => { row.waiting = { reason: 'approval', action: 'approve' }; }],
        ['waiting that is not a record', (row) => { row.waiting = 'approval'; }],
        ['a missing waiting value', (row) => { delete row.waiting; }],
        ['a missing delivery', (row) => { delete row.delivery; }],
        ['a delivery that is not a record', (row) => { row.delivery = 'delivered'; }],
        ['the stored delivery status the route maps away', (row) => { row.delivery.status = 'ready'; }],
        ['a negative delivery generation', (row) => { row.delivery.generation = -1; }],
        ['a delivery generation sent as text', (row) => { row.delivery.generation = '2'; }],
        ['a delivered time with milliseconds', (row) => { row.delivery.delivered_at = '2026-01-05T09:04:10.000Z'; }],
        ['a message id without the delivery prefix', (row) => { row.delivery.message_id = 'assistant_1'; }],
        ['a message id with a trailing space', (row) => { row.delivery.message_id = `${deliveryMessageId('run-1', 1)} `; }],
        ['a message id that is too long', (row) => { row.delivery.message_id = WORKFLOW_DELIVERY_MESSAGE_PREFIX + 'x'.repeat(229); }],
        ['an unknown delivery reason', (row) => { row.delivery.reason = 'network_down'; }],
        ['a missing delivery reason', (row) => { delete row.delivery.reason; }],
        ['missing actions', (row) => { delete row.actions; }],
        ['an action sent as text', (row) => { row.actions.retry = 'true'; }],
        ['a missing Open run action', (row) => { delete row.actions.open_run; }],
        ['an unknown failure code', (row) => { row.error_code = 'boom'; }],
        ['a missing failure code', (row) => { delete row.error_code; }],
        ['an unknown retry block', (row) => { row.retry_blocked = 'maybe_later'; }],
        ['a missing retry block', (row) => { delete row.retry_blocked; }],
        ['an error that is not text', (row) => { row.error = { message: 'x' }; }],
        ['a needs-you row with nothing to wait for', (row) => {
            Object.assign(row, { status: 'waiting', phase: 'needs_you', waiting: null });
        }],
        ['a failed row with a blank error', (row) => { Object.assign(row, failed, { error: '   ' }); }],
        ['a failed row with no error', (row) => { Object.assign(row, failed, { error: null }); }],
        ['a failed row with no failure code', (row) => { Object.assign(row, failed, { error_code: null }); }],
        ['a timed-out row with no failure code', (row) => { Object.assign(row, expiredRow('run-1'), { error_code: null }); }],
    ];
    for (const [label, mutate] of cases) {
        assert.deepEqual(parseRuns([rowWith(mutate)]), [unavailableRow()], label);
    }

    // A message id of exactly 256 characters is still an id.
    const longest = parseRow(rowWith((row) => {
        row.delivery.message_id = WORKFLOW_DELIVERY_MESSAGE_PREFIX + 'x'.repeat(228);
    }));
    assert.equal(longest.kind, 'status');
});

test('an unreadable name or request time makes the row unavailable, with a safe name and no time', () => {
    const cases = [
        ['a name that is not text', (row) => { row.workflow_name = 42; }, { workflow_name: 'Workflow' }],
        ['a missing name', (row) => { delete row.workflow_name; }, { workflow_name: 'Workflow' }],
        ['a request time that is not a time', (row) => { row.requested_at = 'soon'; }, { requested_at: null }],
        ['a missing request time', (row) => { delete row.requested_at; }, { requested_at: null }],
    ];
    for (const [label, mutate, identity] of cases) {
        assert.deepEqual(parseRuns([rowWith(mutate)]), [unavailableRow(identity)], label);
    }
});

test('an unavailable row is never in flight and offers only Open run', () => {
    const row = parseRow(statusRow('run-1', { status: 'mystery' }));
    assert.equal(workflowRunStatusLabel(row), WORKFLOW_RUN_STATUS_UNAVAILABLE);
    assert.equal(WORKFLOW_RUN_STATUS_UNAVAILABLE, 'Status unavailable');
    assert.equal(isWorkflowRunInFlight(row), false);
    assert.equal(isWorkflowRunActive(row), false);
    assert.deepEqual(workflowRunRowControls(row, true), NO_CONTROLS);
    assert.deepEqual(workflowRunRowControls(row, false), NO_CONTROLS);
});

// ----- The states 6b-1 calls out -----

test('a recovering run reads as running, with its reason, and never as needing you', () => {
    const row = parseRow(statusRow('run-1', { waiting: RECOVERY }));
    assert.equal(row.kind, 'status');
    assert.equal(row.status, 'running');
    assert.equal(row.phase, 'running');
    assert.deepEqual(row.waiting, RECOVERY);
    assert.equal(workflowRunStatusLabel(row), 'Running');
    assert.equal(workflowWaitingText(row.waiting.reason), 'Recovering after an interruption.');
    assert.equal(isWorkflowRunActive(row), true);
    assert.deepEqual(workflowRunRowControls(row, true), { ...NO_CONTROLS, cancel: true });
});

test('a skipped run reads as failed with its own code, and is never offered Retry', () => {
    const row = parseRow(failedRow('run-1', {
        error: 'No new or changed files were detected.',
        error_code: 'skipped',
    }));
    assert.equal(row.status, 'failed');
    assert.equal(row.phase, 'failed');
    assert.equal(row.error_code, 'skipped');
    assert.equal(workflowRunStatusLabel(row), 'Failed');
    assert.deepEqual(workflowRunRowControls(row, true), NO_CONTROLS);
});

test('a run that reached its time limit reads as timed out, not in flight, with nothing to retry', () => {
    const row = parseRow(expiredRow('run-1'));
    assert.equal(row.status, 'expired');
    assert.equal(row.phase, 'failed');
    assert.equal(row.error, 'It reached its time limit.');
    assert.equal(workflowRunStatusLabel(row), 'Timed out');
    assert.equal(isWorkflowRunInFlight(row), false);
    assert.deepEqual(workflowRunRowControls(row, true), NO_CONTROLS);
});

// ----- Controls -----

test('each control comes from the server actions, never from the status alone', () => {
    const cases = [
        ['a running run the server lets you cancel', statusRow('r'), true, { ...NO_CONTROLS, cancel: true }],
        ['a queued run', statusRow('r', { status: 'queued' }), true, { ...NO_CONTROLS, cancel: true }],
        ['a run already cancelling', statusRow('r', { actions: { cancel: false } }), true, NO_CONTROLS],
        ['a finished run marked cancellable', deliveredRow('r', 1, at(250), { actions: { cancel: true } }), true, NO_CONTROLS],
        ['a failed run the server lets you retry', failedRow('r', { actions: { retry: true } }), true, { ...NO_CONTROLS, retry: true }],
        ['a failed run the server does not let you retry', failedRow('r'), true, NO_CONTROLS],
        [
            'a failed run that is blocked but marked retryable',
            failedRow('r', { actions: { retry: true }, retry_blocked: 'workflow_definition_changed' }),
            true,
            NO_CONTROLS,
        ],
        [
            'a retryable failed run while chats cannot start workflows',
            failedRow('r', { actions: { retry: true } }),
            false,
            { ...NO_CONTROLS, retryTurnedOff: true },
        ],
        [
            'a blocked failed run while chats cannot start workflows',
            failedRow('r', { retry_blocked: 'retry_unavailable' }),
            false,
            NO_CONTROLS,
        ],
        ['a timed-out run marked retryable', expiredRow('r', { actions: { retry: true } }), true, NO_CONTROLS],
        ['a cancelled run marked retryable', cancelledRow('r', { actions: { retry: true } }), true, NO_CONTROLS],
        ['a running run marked retryable', statusRow('r', { actions: { retry: true } }), true, { ...NO_CONTROLS, cancel: true }],
        [
            'a run waiting at an approval gate',
            waitingRow('r', APPROVAL, { actions: { approve: true } }),
            true,
            { ...NO_CONTROLS, cancel: true, approve: true },
        ],
        [
            'an approval with no gate',
            waitingRow('r', { ...APPROVAL, gate_id: null }, { actions: { approve: true } }),
            true,
            { ...NO_CONTROLS, cancel: true },
        ],
        ['an approval the server does not allow', waitingRow('r', APPROVAL), true, { ...NO_CONTROLS, cancel: true }],
        [
            'an output review marked approvable',
            waitingRow('r', { reason: 'output_review', action: 'open_run', gate_id: 'gate-1' }, { actions: { approve: true } }),
            true,
            { ...NO_CONTROLS, cancel: true },
        ],
        [
            'a running run carrying an approval',
            statusRow('r', { waiting: APPROVAL, actions: { approve: true } }),
            true,
            { ...NO_CONTROLS, cancel: true },
        ],
        ['a Microsoft 365 sign-in', waitingRow('r', RECONNECT), true, { ...NO_CONTROLS, cancel: true, reconnect: true }],
        ['a running run carrying a sign-in', statusRow('r', { waiting: RECONNECT }), true, { ...NO_CONTROLS, cancel: true }],
    ];
    for (const [label, sent, available, expected] of cases) {
        assert.deepEqual(workflowRunRowControls(parseRow(sent), available), expected, label);
    }
});

test('a run is in flight while it is going or its result is still on its way', () => {
    const cases = [
        ['queued', statusRow('r', { status: 'queued' }), true, true],
        ['running', statusRow('r'), true, true],
        ['waiting', waitingRow('r', APPROVAL), true, true],
        ['completed, result pending', deliveredRow('r', 1, at(250), { delivery: { status: 'pending', message_id: null, delivered_at: null } }), true, false],
        ['completed, result posting', deliveredRow('r', 1, at(250), { delivery: { status: 'delivering', message_id: null, delivered_at: null } }), true, false],
        ['completed, result posted', deliveredRow('r', 1, at(250)), false, false],
        ['failed, note pending', failedRow('r'), true, false],
        ['failed, nothing to post', failedRow('r', { delivery: { status: 'not_applicable' } }), false, false],
        ['undeliverable', deliveredRow('r', 1, at(250), { delivery: { status: 'undeliverable', message_id: null, delivered_at: null } }), false, false],
        ['timed out', expiredRow('r'), false, false],
        ['cancelled, note posted', cancelledRow('r', { delivery: { status: 'delivered', generation: 1, message_id: deliveryMessageId('r', 1), delivered_at: at(250) } }), false, false],
    ];
    for (const [label, sent, inFlight, active] of cases) {
        const row = parseRow(sent);
        assert.equal(isWorkflowRunInFlight(row), inFlight, `${label} in flight`);
        assert.equal(isWorkflowRunActive(row), active, `${label} active`);
    }
});

// ----- Fixed texts -----

test('every status, waiting reason, retry block and card sentence reads as fixed text', () => {
    const labels = {};
    for (const status of WORKFLOW_RUN_ROW_STATUSES) {
        const phase = { queued: 'running', running: 'running', waiting: 'needs_you', completed: 'finished', completed_partial: 'finished', failed: 'failed', expired: 'failed', cancelled: 'cancelled' }[status];
        const row = statusRow('r', {
            status,
            phase,
            waiting: status === 'waiting' ? APPROVAL : null,
            ...(phase === 'failed' ? { error: 'It stopped.', error_code: 'failed' } : {}),
        });
        labels[status] = workflowRunStatusLabel(parseRow(row));
    }
    assert.deepEqual(labels, {
        queued: 'Queued',
        running: 'Running',
        waiting: 'Needs you',
        completed: 'Completed',
        completed_partial: 'Partly completed',
        failed: 'Failed',
        cancelled: 'Cancelled',
        expired: 'Timed out',
    });

    assert.deepEqual(Object.fromEntries(WORKFLOW_WAITING_REASONS.map((reason) => [reason, workflowWaitingText(reason)])), {
        approval: 'Waiting for your approval.',
        microsoft_365_reconnect: 'Reconnect Microsoft 365 to continue.',
        microsoft_365_approval: 'Waiting for a Microsoft 365 approval.',
        output_review: 'Waiting for you to review its output.',
        recovery: 'Recovering after an interruption.',
        deadline_exceeded: 'Paused. Open the run to continue.',
        paused: 'Paused. Open the run to continue.',
    });

    assert.deepEqual(Object.fromEntries(WORKFLOW_RETRY_BLOCKED_CODES.map((code) => [code, workflowRetryBlockedText(code)])), {
        retry_unavailable: 'Retry isn\'t available for this run right now.',
        workflow_deleted: 'The workflow was deleted, so this run can\'t be retried.',
        not_resumable: 'This run can\'t be retried.',
        deadline_exceeded: 'This run reached its time limit, so it can\'t be retried.',
        workflow_definition_changed: 'The workflow changed after this run started. Start a new run from Workflows.',
        workflow_already_running: 'Another run of this workflow is in progress. Retry when it finishes.',
    });

    assert.equal(WORKFLOW_RETRY_TURNED_OFF_TEXT, 'Starting workflows from chat is turned off, so Retry isn\'t available here.');
    assert.equal(WORKFLOW_RUN_CANCELLED_TEXT, 'The run was cancelled.');
    assert.equal(WORKFLOW_RESULTS_POSTING_TEXT, 'Posting results…');
    assert.equal(WORKFLOW_RESULTS_POSTED_TEXT, 'Results posted below');
    assert.equal(WORKFLOW_RESULTS_POSTED_ELSEWHERE_TEXT, 'Results were posted to this chat.');
    assert.equal(WORKFLOW_RESULTS_IN_HISTORY_TEXT, 'The results are in the workflow\'s run history.');
    assert.equal(WORKFLOW_STATUS_READ_ERROR_TEXT, 'Couldn\'t check the run status right now. Try again.');
    assert.equal(WORKFLOW_STATUS_HALTED_TEXT, 'Live status isn\'t available right now.');
});

test('a workflow name is kept as one line of at most 80 characters, and as text', () => {
    const name = (workflowName) => parseRow(statusRow('r', { workflow_name: workflowName })).workflow_name;
    assert.equal(name('  Weekly\n\tdigest  '), 'Weekly digest');
    assert.equal(name('😀'.repeat(81)), '😀'.repeat(80));
    assert.equal([...name('😀'.repeat(81))].length, 80);
    assert.equal(name(`${'a'.repeat(79)} b`), 'a'.repeat(79));
    assert.equal(name('   '), 'Workflow');
    assert.equal(name(''), 'Workflow');
    assert.equal(name('<img src=x onerror=alert(1)>'), '<img src=x onerror=alert(1)>');
    assert.equal(name('Use `code` & "quotes"'), 'Use `code` & "quotes"');
    // Only a name that isn't text makes the row unavailable; an empty one still reads.
    assert.equal(parseRow(statusRow('r', { workflow_name: '' })).kind, 'status');
});

test('steps and elapsed time read plainly, and only once the server counted them', () => {
    const step = (overrides) => workflowRunStepText(parseRow(statusRow('r', overrides)));
    assert.equal(step({}), 'Step 2 of 4');
    assert.equal(step({ step_index: 0 }), 'Step 1 of 4');
    assert.equal(step({ step_index: 4 }), 'Step 4 of 4');
    assert.equal(step({ step_index: 9 }), 'Step 4 of 4');
    assert.equal(step({ step_index: 0, step_count: 0 }), '');
    assert.equal(step({ step_count: null }), '');
    assert.equal(step({ step_index: null }), '');

    const label = (stepLabel) => workflowRunStepLabel(parseRow(statusRow('r', { step_label: stepLabel })));
    assert.equal(label(null), '');
    assert.equal(label(''), '');
    assert.equal(label(' Collect\n  files '), 'Collect files');
    assert.equal(label('<b>Draft</b>'), '<b>Draft</b>');

    const elapsed = [
        [null, ''],
        [-1, ''],
        [Number.NaN, ''],
        [Number.POSITIVE_INFINITY, ''],
        [0, '0 s'],
        [59.9, '59 s'],
        [60, '1 min'],
        [3599, '59 min'],
        [3600, '1 h'],
        [3660, '1 h 1 min'],
        [7325, '2 h 2 min'],
    ];
    for (const [seconds, text] of elapsed) {
        assert.equal(formatWorkflowElapsed(seconds), text, String(seconds));
    }
});

test('the checked time is the reader\'s local time to the minute, or nothing', () => {
    for (const value of [null, '', 'not a time']) {
        assert.equal(formatCheckedTime(value), '');
    }
    const checked = at(307);
    const shown = formatCheckedTime(checked);
    assert.equal(shown, new Date(checked).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }));
    assert.doesNotMatch(shown, /[:.]07(?!\d)/, 'the seconds are not shown');
});

// ----- Ids -----

test('ids are checked the way the server keeps them', () => {
    const good = ['a', 'run-1', 'x'.repeat(256), '😀'.repeat(256), 'run\u007f1', 'é'];
    const bad = [
        '', ' a', 'a ', '\ta', 'x'.repeat(257), '😀'.repeat(257), 'a\u0000b', 'a\u001fb', 'a\nb', '\ud800', 'a\udc00b',
        5, null, undefined, {}, ['a'],
    ];
    for (const value of good) {
        assert.equal(isWorkflowRunIdentifier(value), true, JSON.stringify(value));
    }
    for (const value of bad) {
        assert.equal(isWorkflowRunIdentifier(value), false, String(value));
    }

    const goodChats = ['chat-1', 'Chat_2', 'x'.repeat(128), 'a'];
    const badChats = ['', 'x'.repeat(129), 'chat 1', 'chat.1', 'chat/1', 'é', ' chat', 'chat\n', 5, null, undefined];
    for (const value of goodChats) {
        assert.equal(isStatusConversationId(value), true, value);
    }
    for (const value of badChats) {
        assert.equal(isStatusConversationId(value), false, String(value));
    }
});

// ----- The request -----

test('one batched GET reads every tracked run, or one chat\'s runs', async (t) => {
    t.after(() => {
        globalThis.fetch = refuseNetwork;
    });
    const requests = [];
    globalThis.fetch = async (url, init) => {
        requests.push({ url, init });
        return jsonResponse(statusResponse([statusRow('run-1')], { truncated: true, available: false }));
    };
    const controller = new AbortController();
    const all = await fetchWorkflowRunStatus(null, controller.signal);
    await fetchWorkflowRunStatus('chat-1', controller.signal);
    await fetchWorkflowRunStatus('a&b=c', controller.signal);

    assert.deepEqual(requests.map((request) => request.url), [
        WORKFLOW_RUN_STATUS_PATH,
        `${WORKFLOW_RUN_STATUS_PATH}?conversation_id=chat-1`,
        `${WORKFLOW_RUN_STATUS_PATH}?conversation_id=a%26b%3Dc`,
    ]);
    assert.equal(WORKFLOW_RUN_STATUS_PATH, '/api/v2/orchestration/workflow-runs/status');
    for (const { init } of requests) {
        assert.equal(init.method, 'GET');
        assert.equal(init.credentials, 'same-origin');
        assert.equal(init.signal, controller.signal);
        assert.equal(init.body, undefined);
        assert.equal(init.headers.Accept, 'application/json');
    }
    assert.equal(all.truncated, true);
    assert.equal(all.available, false);
    assert.equal(all.runs.length, 1, 'rows still come back when chats cannot start workflows');
});

test('a refused read raises the server\'s own error, and an unreadable one the fixed text', async (t) => {
    t.after(() => {
        globalThis.fetch = refuseNetwork;
    });
    const refusals = [
        [503, { error: 'Workflow run status isn\'t available right now. Try again later.', code: 'workflow_run_status_unavailable' }, false],
        [400, { error: 'The conversation ID is not valid.', code: 'invalid_conversation_id' }, false],
        [401, { error: 'Sign in again.' }, true],
        [403, { error: 'Workflows aren\'t available for your account.' }, true],
    ];
    for (const [status, body, authError] of refusals) {
        globalThis.fetch = async () => jsonResponse(body, status);
        await assert.rejects(fetchWorkflowRunStatus(null), (error) => {
            assert.ok(error instanceof ApiError);
            assert.equal(error.status, status);
            assert.equal(error.message, body.error);
            assert.equal(error.isAuthError, authError);
            return true;
        });
    }

    globalThis.fetch = async () => jsonResponse({ runs: [] });
    await assert.rejects(fetchWorkflowRunStatus(null), { message: WORKFLOW_RUN_STATUS_INVALID_RESPONSE });

    globalThis.fetch = async () => new Response('<html>Sign in</html>', {
        status: 200,
        headers: { 'content-type': 'text/html' },
    });
    await assert.rejects(fetchWorkflowRunStatus(null), { message: WORKFLOW_RUN_STATUS_INVALID_RESPONSE });
});
