// test_v2_workflow_run_action_clients.mjs
// Version: 0.261.230
// Implemented in: 0.261.230
// Executes Cancel and Retry for a run a chat started, against a fetch that records every request.
// Retry reads the run's runtime fresh, then resumes it with exactly {expected_version, request_id}:
// the version that read returned and a new UUID each attempt. It sends nothing when the runtime says
// the run can't be resumed or the read fails. Cancel is the run-level cancel with no body. Neither
// ever reaches /resume-failed or the workflow-level /cancel. Every refusal reads as a fixed sentence
// chosen by status and code, never the server's own words. The routes, request keys, refusal codes
// and texts are pinned against the server modules that answer them.

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import './test_support/tsResolve.mjs';

const calls = [];
const allCalls = [];
let script = [];

async function recordingFetch(url, init = {}) {
    const call = {
        url: String(url),
        method: init.method ?? 'GET',
        headers: { ...(init.headers ?? {}) },
        body: init.body,
        credentials: init.credentials,
    };
    calls.push(call);
    allCalls.push(call);
    assert.ok(script.length > 0, `Unexpected request: ${call.method} ${call.url}`);
    const next = script.shift();
    if (next instanceof Error) {
        throw next;
    }
    return next;
}

globalThis.fetch = recordingFetch;

// The repository resolver must be registered before extensionless TypeScript imports load.
const {
    WORKFLOW_CANCEL_FAILED_TEXT,
    WORKFLOW_CANCEL_REQUESTED_TEXT,
    WORKFLOW_RETRY_FAILED_TEXT,
    WORKFLOW_RETRY_REQUESTED_TEXT,
    cancelWorkflowRun,
    retryWorkflowRun,
} = await import('../application/v2_ui/src/lib/workflowRunActions.ts');
const { WORKFLOW_RETRY_BLOCKED_CODES, workflowRetryBlockedText } = await import(
    '../application/v2_ui/src/lib/workflowRunStatus.ts'
);

const TARGET = { workflowId: 'wf-1', runId: 'run-1' };
const RUNTIME_PATH = '/api/user/workflows/wf-1/runs/run-1/runtime';
const RESUME_PATH = '/api/user/workflows/wf-1/runs/run-1/runtime/resume';
const CANCEL_PATH = '/api/user/workflows/wf-1/runs/run-1/cancel';
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
// A sentence no person should read: every refusal below carries it, and no outcome may repeat it.
const SERVER_SENTENCE = 'Server sentence <b>meant for logs</b>';

const RUN_GONE = 'This run is no longer available.';
const NO_ACCESS = "You don't have access to this run.";
const UNAVAILABLE = "Workflows aren't available right now. Try again later.";
const REJECTED = "The retry request wasn't accepted.";
const UNCONFIRMED = "Couldn't confirm the retry. Check its status.";
const NOT_RESUMABLE = "This run can't be retried anymore.";
const CANCEL_CONFLICT = 'This run already finished or changed. Check its status.';
const CONFLICT_FALLBACK = "This run can't be retried right now. Check its status.";

function reset(...responses) {
    calls.length = 0;
    script = responses;
}

function json(status, body) {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

/** A runtime answer as the server sends it, defaulting to a failed run that can be resumed. */
function runtime(overrides = {}) {
    return json(200, { runtime: { version: 7, state: 'failed', can_resume: true, gate: null, ...overrides }, can_decide: true });
}

/** The runtime a successful resume answers with: queued, one version on. */
function resumed(version = 8) {
    return runtime({ version, state: 'queued', can_resume: false });
}

function refusal(status, extra = {}) {
    return json(status, { error: SERVER_SENTENCE, ...extra });
}

function assertNoServerText(outcome) {
    assert.ok(!outcome.text.includes(SERVER_SENTENCE), `The outcome repeated the server's sentence: ${outcome.text}`);
    assert.ok(!/[<>]/.test(outcome.text), `The outcome carries markup: ${outcome.text}`);
}

function assertRead(call, path = RUNTIME_PATH) {
    assert.equal(call.method, 'GET');
    assert.equal(call.url, path);
    assert.equal(call.body, undefined);
    assert.equal(call.credentials, 'same-origin');
}

function assertResume(call, expectedVersion, path = RESUME_PATH) {
    assert.equal(call.method, 'POST');
    assert.equal(call.url, path);
    assert.equal(call.headers['Content-Type'], 'application/json');
    assert.equal(call.credentials, 'same-origin');
    const body = JSON.parse(call.body);
    assert.deepEqual(Object.keys(body).sort(), ['expected_version', 'request_id']);
    assert.equal(body.expected_version, expectedVersion);
    assert.match(body.request_id, UUID_V4);
    return body;
}

function serverSource(name) {
    return readFileSync(new URL(name, new URL('../application/single_app/', import.meta.url)), 'utf8')
        .replace(/\r\n/g, '\n');
}

function serverFunction(source, name) {
    const start = source.indexOf(`\ndef ${name}(`);
    assert.ok(start >= 0, `The server no longer defines ${name}.`);
    const end = source.indexOf('\ndef ', start + 1);
    return source.slice(start, end < 0 ? undefined : end);
}

function serverMethod(source, name) {
    const start = source.indexOf(`\n    def ${name}(`);
    assert.ok(start >= 0, `The server no longer defines the method ${name}.`);
    const ends = ['\n    def ', '\nclass ', '\ndef ']
        .map((marker) => source.indexOf(marker, start + 1))
        .filter((index) => index > 0);
    return source.slice(start, ends.length ? Math.min(...ends) : undefined);
}

/** One route's decorators and body, up to the next route the blueprint declares. */
function serverRoute(source, path) {
    const marker = `@bp.route('${path}', methods=['POST'])`;
    const start = source.indexOf(marker);
    assert.ok(start >= 0, `The server no longer declares POST ${path}.`);
    const end = source.indexOf('@bp.route(', start + marker.length);
    return source.slice(start, end < 0 ? undefined : end);
}

test('Retry reads the runtime, then resumes from exactly the version that read returned', async () => {
    reset(runtime({ version: 7 }), resumed(8));
    const first = await retryWorkflowRun(TARGET);

    assert.deepEqual(first, { ok: true, text: WORKFLOW_RETRY_REQUESTED_TEXT });
    assert.equal(calls.length, 2);
    assertRead(calls[0]);
    const firstBody = assertResume(calls[1], 7);

    // The status row's runtime_version (3 in the shared fixtures) is never the version sent: each
    // attempt reads the runtime again, and a second attempt sends a new request id.
    reset(runtime({ version: 11 }), resumed(12));
    const second = await retryWorkflowRun(TARGET);

    assert.deepEqual(second, { ok: true, text: WORKFLOW_RETRY_REQUESTED_TEXT });
    assertRead(calls[0]);
    const secondBody = assertResume(calls[1], 11);
    assert.notEqual(secondBody.request_id, firstBody.request_id);
});

test('Retry and Cancel encode the workflow and run ids in every path', async () => {
    const target = { workflowId: 'wf 1/x', runId: 'run?1#2' };
    const runtimePath = '/api/user/workflows/wf%201%2Fx/runs/run%3F1%232/runtime';

    reset(runtime({ version: 2 }), resumed(3));
    assert.equal((await retryWorkflowRun(target)).ok, true);
    assertRead(calls[0], runtimePath);
    assertResume(calls[1], 2, `${runtimePath}/resume`);

    reset(json(202, { success: true }));
    assert.equal((await cancelWorkflowRun(target)).ok, true);
    assert.equal(calls[0].url, '/api/user/workflows/wf%201%2Fx/runs/run%3F1%232/cancel');
});

test('Retry sends nothing when the runtime says the run cannot be resumed', async () => {
    const unresumable = [
        ['can_resume is false', { can_resume: false }],
        ['can_resume is missing', { can_resume: undefined }],
        ['the run completed', { state: 'completed' }],
        ['the run was cancelled', { state: 'cancelled' }],
        ['the run was skipped', { state: 'skipped' }],
        ['the run is still running', { state: 'running' }],
        ['the run is queued', { state: 'queued' }],
        ['a Microsoft 365 sign-in holds the run', { gate: { id: 'gate-1', reason_code: 'm365_authorization', choices: ['cancel'] } }],
    ];
    for (const [label, overrides] of unresumable) {
        reset(runtime(overrides));
        const outcome = await retryWorkflowRun(TARGET);
        assert.deepEqual(outcome, { ok: false, text: NOT_RESUMABLE }, label);
        assert.equal(calls.length, 1, `${label}: only the read is sent`);
        assertRead(calls[0]);
    }

    // A Repeat limit pause is never a failed run the runtime would resume; either way nothing is sent.
    reset(runtime({ gate: { id: 'gate-2', reason_code: 'repeat_iteration_limit', choices: ['continue_repeat', 'cancel'] } }));
    const repeat = await retryWorkflowRun(TARGET);
    assert.equal(repeat.ok, false);
    assert.equal(calls.length, 1);
});

test('Retry sends nothing when the runtime has no version it can resume from', async () => {
    for (const version of [-1, 1.5, '7', null, undefined, Number.MAX_SAFE_INTEGER + 2, Number.NaN]) {
        reset(runtime({ version }));
        const outcome = await retryWorkflowRun(TARGET);
        assert.deepEqual(outcome, { ok: false, text: WORKFLOW_RETRY_FAILED_TEXT }, `version ${String(version)}`);
        assert.equal(calls.length, 1);
    }
});

test('A failed runtime read sends nothing and reads as a fixed sentence', async () => {
    const reads = [
        [refusal(403), NO_ACCESS],
        [json(404, { error: 'Workflow not found.' }), RUN_GONE],
        [json(404, { error: 'Durable workflow run not found.' }), RUN_GONE],
        [refusal(503), UNAVAILABLE],
        [refusal(500), WORKFLOW_RETRY_FAILED_TEXT],
        [refusal(409, { code: 'invalid_state' }), WORKFLOW_RETRY_FAILED_TEXT],
        [new TypeError('fetch failed'), WORKFLOW_RETRY_FAILED_TEXT],
        // A 200 V2 can't read: no runtime at all.
        [json(200, { can_decide: true }), WORKFLOW_RETRY_FAILED_TEXT],
    ];
    for (const [answer, text] of reads) {
        reset(answer);
        const outcome = await retryWorkflowRun(TARGET);
        assert.deepEqual(outcome, { ok: false, text });
        assertNoServerText(outcome);
        assert.equal(calls.length, 1, 'Nothing is resumed after a failed read.');
    }
});

test('Each resume refusal reads as its own fixed sentence', async () => {
    const blocked = (code) => workflowRetryBlockedText(code);
    const refusals = [
        [409, { code: 'workflow_definition_changed' }, blocked('workflow_definition_changed')],
        [409, { code: 'workflow_already_running' }, blocked('workflow_already_running')],
        [409, { code: 'workflow_deleted' }, blocked('workflow_deleted')],
        [409, { code: 'deadline_exceeded' }, blocked('deadline_exceeded')],
        [409, { code: 'workflow_deleting' }, "The workflow is being deleted, so this run can't be retried."],
        [409, { code: 'stale_version' }, 'The run changed since it was checked. Check its status and try again.'],
        [409, { code: 'invalid_state' }, "This run can't be retried in its current state."],
        [409, { code: 'request_conflict' }, 'Another request changed this run. Check its status and try again.'],
        [409, { code: 'etag_conflict' }, CONFLICT_FALLBACK],
        [409, { code: 'tombstoned' }, CONFLICT_FALLBACK],
        [409, { code: 'Stale_Version' }, CONFLICT_FALLBACK],
        [409, { code: 42 }, CONFLICT_FALLBACK],
        [409, {}, CONFLICT_FALLBACK],
        [400, {}, REJECTED],
        [403, {}, NO_ACCESS],
        [404, {}, RUN_GONE],
        [503, {}, UNAVAILABLE],
        [500, {}, WORKFLOW_RETRY_FAILED_TEXT],
        [502, {}, WORKFLOW_RETRY_FAILED_TEXT],
    ];
    for (const [status, extra, text] of refusals) {
        reset(runtime({ version: 5 }), refusal(status, extra));
        const outcome = await retryWorkflowRun(TARGET);
        assert.deepEqual(outcome, { ok: false, text }, `${status} ${JSON.stringify(extra)}`);
        assertNoServerText(outcome);
        assert.equal(calls.length, 2);
        assertResume(calls[1], 5);
    }

    // Each code a status row can also block Retry with reads the same from a refused resume.
    for (const code of WORKFLOW_RETRY_BLOCKED_CODES) {
        reset(runtime({ version: 5 }), refusal(409, { code }));
        assert.equal((await retryWorkflowRun(TARGET)).text, blocked(code));
    }

    // A 409 whose answer isn't JSON still reads as the fallback, never as its body.
    reset(runtime({ version: 5 }), new Response(SERVER_SENTENCE, { status: 409, headers: { 'content-type': 'text/html' } }));
    const html = await retryWorkflowRun(TARGET);
    assert.deepEqual(html, { ok: false, text: CONFLICT_FALLBACK });
});

test('Both 404 answers a resume can give read as a run that is gone', async () => {
    for (const error of ['Workflow not found.', 'Durable workflow run not found.']) {
        reset(runtime(), json(404, { error }));
        assert.deepEqual(await retryWorkflowRun(TARGET), { ok: false, text: RUN_GONE });
    }
});

test('A resume with no answer reads as failed; one V2 cannot read may have gone through', async () => {
    reset(runtime(), new TypeError('fetch failed'));
    assert.deepEqual(await retryWorkflowRun(TARGET), { ok: false, text: WORKFLOW_RETRY_FAILED_TEXT });
    assert.equal(calls.length, 2);

    reset(runtime(), json(200, { can_decide: true }));
    assert.deepEqual(await retryWorkflowRun(TARGET), { ok: false, text: UNCONFIRMED });

    reset(runtime(), new Response('<html>ok</html>', { status: 200, headers: { 'content-type': 'text/html' } }));
    assert.deepEqual(await retryWorkflowRun(TARGET), { ok: false, text: UNCONFIRMED });
});

test('Cancel posts the run-level cancel with no body', async () => {
    reset(json(202, { success: true, workflow: { id: 'wf-1' }, run: { id: 'run-1', status: 'cancelling' } }));
    const outcome = await cancelWorkflowRun(TARGET);

    assert.deepEqual(outcome, { ok: true, text: WORKFLOW_CANCEL_REQUESTED_TEXT });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, 'POST');
    assert.equal(calls[0].url, CANCEL_PATH);
    assert.equal(calls[0].body, undefined);
    assert.equal(calls[0].headers['Content-Type'], undefined);
    assert.equal(calls[0].credentials, 'same-origin');

    reset(new Response(null, { status: 204 }));
    assert.deepEqual(await cancelWorkflowRun(TARGET), { ok: true, text: WORKFLOW_CANCEL_REQUESTED_TEXT });
});

test('Each cancel refusal reads as a fixed sentence', async () => {
    const refusals = [
        [json(404, { error: 'Workflow not found.' }), RUN_GONE],
        [json(404, { error: 'Workflow run not found.' }), RUN_GONE],
        [json(409, { error: 'Workflow run cancellation conflict.' }), CANCEL_CONFLICT],
        [refusal(409, { code: 'invalid_state' }), CANCEL_CONFLICT],
        [refusal(500), WORKFLOW_CANCEL_FAILED_TEXT],
        [refusal(403), WORKFLOW_CANCEL_FAILED_TEXT],
        [refusal(503), WORKFLOW_CANCEL_FAILED_TEXT],
        [new TypeError('fetch failed'), WORKFLOW_CANCEL_FAILED_TEXT],
    ];
    for (const [answer, text] of refusals) {
        reset(answer);
        const outcome = await cancelWorkflowRun(TARGET);
        assert.deepEqual(outcome, { ok: false, text });
        assertNoServerText(outcome);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].url, CANCEL_PATH);
    }
});

test('The resume route takes exactly the two keys V2 sends and answers with the codes V2 reads', () => {
    const routes = serverSource('route_backend_workflows.py');
    const resumeRoute = serverRoute(routes, '/api/user/workflows/<workflow_id>/runs/<run_id>/runtime/resume');
    assert.match(resumeRoute, /@enabled_required\('allow_user_workflows'\)\n\s+@workflow_user_required\n/);
    assert.match(resumeRoute, /return _workflow_runtime_response\(workflow_id, run_id, action='resume'\)/);

    const response = serverFunction(routes, '_workflow_runtime_response');
    assert.ok(response.includes("allowed = {'expected_version', 'request_id'} | ({'gate_id', 'choice'} if action == 'decision' else set())"));
    assert.ok(response.includes("if not isinstance(data, dict) or data.keys() - allowed:"));
    assert.ok(response.includes("return jsonify({'error': exc.public_message, 'code': exc.code}), 409"));
    assert.ok(response.includes("return jsonify({'error': 'Workflow not found.'}), 404"));
    assert.ok(response.includes("return jsonify({'error': 'Durable workflow run not found.'}), 404"));
    assert.ok(response.includes("return jsonify({'error': 'Invalid workflow decision.'}), 400"));
    assert.ok(response.includes("return jsonify({'error': 'Invalid workflow decision or request identifier.'}), 400"));
    assert.match(response, /except PermissionError:\n\s+return jsonify\(\{'error': '[^']+'\}\), 403/);
    assert.ok(response.includes("return jsonify({'error': 'Workflow progress is temporarily unavailable.'}), 503"));

    // The resume itself refuses with the codes the client names.
    const runtimeModule = serverSource('functions_workflow_runtime.py');
    const decide = serverFunction(runtimeModule, 'decide_workflow_runtime');
    assert.ok(decide.includes('raise WorkflowRuntimeConflict("workflow_definition_changed")'));
    assert.ok(decide.includes('raise WorkflowRuntimeConflict("workflow_already_running")'));
    assert.ok(decide.includes('request_id = str(uuid.UUID(data.get("request_id", "")))'));
    const authorize = serverFunction(runtimeModule, '_authorize_execution');
    assert.ok(authorize.includes('raise WorkflowRuntimeConflict("workflow_deleting"'));

    const journal = serverMethod(serverSource('functions_workflow_journal.py'), 'journal_request');
    for (const code of ['request_conflict', 'stale_version', 'invalid_state', 'deadline_exceeded']) {
        assert.ok(journal.includes(`self._journal_conflict("${code}")`), `journal_request no longer refuses with ${code}`);
    }
    assert.match(journal, /if type\(expected_version\) is not int or expected_version != control\["version"\]:/);

    const store = serverSource('functions_workflow_runtime_store.py');
    const resumable = store.match(/\nRESUMABLE_STATES = frozenset\(\{([^}]*)\}\)/);
    assert.ok(resumable, 'The runtime store no longer declares RESUMABLE_STATES.');
    assert.deepEqual(resumable[1].match(/[a-z_]+/g).sort(), ['failed', 'incomplete', 'invalid']);
    const conflict = serverMethod(serverSource('functions_workflow_journal.py'), '_journal_conflict');
    assert.ok(conflict.includes('raise WorkflowRuntimeConflict(code)'));
});

test('The run-level cancel route answers 202, 404 or a code-less 409', () => {
    const routes = serverSource('route_backend_workflows.py');
    const cancel = serverRoute(routes, '/api/user/workflows/<workflow_id>/runs/<run_id>/cancel');
    assert.match(cancel, /@enabled_required\('allow_user_workflows'\)\n\s+@workflow_user_required\n/);
    assert.ok(cancel.includes('_request_workflow_run_cancellation('));
    assert.ok(cancel.includes("return jsonify({'error': 'Workflow not found.'}), 404"));
    assert.ok(cancel.includes("return jsonify({'error': 'Workflow run not found.'}), 404"));
    assert.ok(cancel.includes("return jsonify({'error': 'Workflow run cancellation conflict.'}), 409"));
    assert.ok(cancel.includes("return jsonify({'success': True, 'workflow': updated_workflow, 'run': run_record}), 202"));
    assert.ok(!cancel.includes("'code'"), 'The cancel route started sending a code; read it in cancelWorkflowRun.');

    // A durable run, which every chat-started run is, cancels through the durable runtime.
    const request = serverFunction(routes, '_request_workflow_run_cancellation');
    assert.ok(request.includes("if run_record and run_record.get('durable_execution') is True:"));
    assert.ok(request.includes('cancel_durable_workflow_run(workflow, target_run_id, actor_user_id=requested_by)'));
});

test('/resume-failed refuses durable runs, and no V2 module calls it', () => {
    const routes = serverSource('route_backend_workflows.py');
    const resumeFailed = serverRoute(routes, '/api/user/workflows/<workflow_id>/runs/<run_id>/resume-failed');
    assert.match(resumeFailed, /if workflow\.get\('durable_execution'\) is True:\n\s+return jsonify\(\{'error': '[^']+'\}\), 409/);

    const sourceRoot = fileURLToPath(new URL('../application/v2_ui/src/', import.meta.url));
    const offenders = [];
    let scanned = 0;
    for (const entry of readdirSync(sourceRoot, { recursive: true, withFileTypes: true })) {
        if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name)) {
            continue;
        }
        const file = join(entry.parentPath, entry.name);
        scanned += 1;
        readFileSync(file, 'utf8').split(/\r?\n/).forEach((line, index) => {
            const code = line.trim();
            if (code.includes('resume-failed') && !code.startsWith('//') && !code.startsWith('*')) {
                offenders.push(`${relative(sourceRoot, file)}:${index + 1}`);
            }
        });
    }
    assert.ok(scanned > 100, `Only ${scanned} V2 source files were scanned.`);
    assert.deepEqual(offenders, []);

    const actions = readFileSync(new URL('../application/v2_ui/src/lib/workflowRunActions.ts', import.meta.url), 'utf8');
    assert.ok(!/\bcancelScopedWorkflow\b/.test(actions), 'Run actions must never use the workflow-level cancel.');
});

test('No request in this file reached /resume-failed or the workflow-level cancel', () => {
    assert.ok(allCalls.length > 0);
    for (const call of allCalls) {
        assert.ok(!call.url.includes('resume-failed'), call.url);
        assert.ok(!/\/api\/user\/workflows\/[^/]+\/cancel$/.test(call.url), call.url);
        assert.ok(!call.url.startsWith('/api/group/'), call.url);
    }
});
