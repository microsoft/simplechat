// test_workflow_results_clients.mjs
/**
 * Workflow results in chat (Follow up) client contract regressions.
 * Version: 0.261.213
 * Implemented in: 0.261.213
 *
 * Executes the bundled V2 helpers behind the workflow result chip: descriptor parsing and
 * inheritance, request shaping, refusal wording and which refusals remove the chip, the
 * descriptor read, the one-shot chat link, Ask in chat and Ask about this gating, and the
 * retry and edit guard. Browser rendering, the store and the stream are covered in
 * ui_tests/test_chat_workflow_results.py.
 *
 * Run: node functional_tests/test_workflow_results_clients.mjs
 */

import assert from 'node:assert/strict';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(root, 'application', 'v2_ui', 'src');
const { build } = await import(pathToFileURL(resolve(root, 'application', 'v2_ui', 'node_modules', 'esbuild', 'lib', 'main.js')));
const compiled = await build({
    stdin: {
        contents: [
            "export * from './lib/workflowResults';",
            "export * as url from './lib/conversationUrl';",
            "export * as alerts from './lib/workflowAlertNotices';",
            "export { ApiError } from './lib/apiClient';",
        ].join('\n'),
        resolveDir: source,
        loader: 'ts',
    },
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'node',
    define: { 'import.meta.env': '{}' },
    logLevel: 'silent',
});
const client = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
const { url, alerts, ApiError } = client;

const SHA = 'a'.repeat(64);
const descriptor = {
    version: 'workflow-result-v1', workflow_id: 'wf-digest', run_id: 'run-7', result_sha256: SHA,
    workflow_name: 'Weekly digest', status: 'completed', completed_at: '2026-01-05T09:02:00Z', available: true,
};
const context = { workflow_id: 'wf-digest', run_id: 'run-7', result_sha256: SHA };

function testDescriptorParsing() {
    const parsed = client.parseWorkflowResultDescriptor({
        ...descriptor, result_ref: { blob: 'backend-only' }, excerpt: 'backend-only',
    });
    assert.deepEqual(parsed, descriptor, 'only the public fields survive');
    assert.equal(client.readWorkflowResult({ workflow_result: descriptor }).run_id, 'run-7');
    assert.equal(client.readWorkflowResult(null), null);
    assert.equal(client.parseWorkflowResultDescriptor({ ...descriptor, status: 'completed_partial' }).status,
        'completed_partial');
    for (const [label, change] of [
        ['version', { version: 'workflow-result-v0' }],
        ['workflow id', { workflow_id: '../wf' }],
        ['run id', { run_id: '' }],
        ['long id', { run_id: 'r'.repeat(201) }],
        ['digest', { result_sha256: 'A'.repeat(64) }],
        ['short digest', { result_sha256: 'a'.repeat(63) }],
        ['failed status', { status: 'failed' }],
        ['running status', { status: 'running' }],
        ['name type', { workflow_name: 7 }],
    ]) {
        assert.equal(client.parseWorkflowResultDescriptor({ ...descriptor, ...change }), null, label);
    }
    assert.equal(client.parseWorkflowResultDescriptor('descriptor'), null);
    assert.equal(client.parseWorkflowResultDescriptor([descriptor]), null);
    // A masked answer keeps only the version and the unavailable flag: no ids, so no chip.
    assert.equal(client.readWorkflowResult({ workflow_result: { version: 'workflow-result-v1', available: false } }), null);
    const long = client.parseWorkflowResultDescriptor({ ...descriptor, workflow_name: `  ${'n'.repeat(120)}  ` });
    assert.equal(long.workflow_name.length, 80);
    assert.equal(client.parseWorkflowResultDescriptor({ ...descriptor, workflow_name: '   ' }).workflow_name, 'Workflow');
    assert.equal(client.parseWorkflowResultDescriptor({ ...descriptor, workflow_name: undefined }).workflow_name, 'Workflow');
    assert.equal(client.parseWorkflowResultDescriptor({ ...descriptor, completed_at: 'yesterday' }).completed_at, null);
    assert.equal(client.parseWorkflowResultDescriptor({ ...descriptor, available: false }).available, false);
    assert.deepEqual(client.workflowResultContext({ ...descriptor, extra: 1 }), context);
    assert.equal(client.sameWorkflowResult(context, { ...descriptor }), true);
    assert.equal(client.sameWorkflowResult(context, { ...context, result_sha256: 'b'.repeat(64) }), false);
    assert.equal(client.sameWorkflowResult(context, null), false);
}

function testLatestWorkflowResult() {
    const question = { id: 'user-1', role: 'user', content: 'What changed?', metadata: { workflow_result_context: context } };
    const answer = { id: 'assistant-1', role: 'assistant', content: 'Three items.', metadata: { workflow_result: descriptor } };
    assert.equal(client.latestWorkflowResult([question, answer]).run_id, 'run-7');
    assert.equal(client.latestWorkflowResult([question, answer, { id: 'user-2', role: 'user', content: 'Unrelated' }]), null,
        'a later question ends the inheritance');
    assert.equal(client.latestWorkflowResult([question, answer,
        { id: 'user-2', role: 'user', content: 'Deleted', metadata: { is_deleted: true } }]).run_id, 'run-7',
        'deleted messages are skipped');
    assert.equal(client.latestWorkflowResult([question, { ...answer, metadata: { ...answer.metadata, masked: true } }]), null);
    assert.equal(client.latestWorkflowResult([question,
        { ...answer, metadata: { ...answer.metadata, masked_ranges: [{ start: 0, end: 3 }] } }]), null);
    assert.equal(client.latestWorkflowResult([question,
        { ...answer, metadata: { workflow_result: { ...descriptor, available: false } } }]), null);
    assert.equal(client.latestWorkflowResult([question,
        { ...answer, metadata: { workflow_result: { version: 'workflow-result-v1', available: false } } }]), null);
    assert.equal(client.latestWorkflowResult([]), null);
    assert.equal(client.latestWorkflowResult([question, answer, { id: 'system', role: 'system', content: 'note' }]).run_id,
        'run-7', 'only questions and answers count as turns');
}

function testRequestShaping() {
    const request = {
        conversation_id: 'conversation-1', message: 'What changed?', model_id: 'chosen-model',
        agent_info: { id: 'local-agent' }, hybrid_search: true, image_generation: true,
        web_search_enabled: true, url_access_enabled: true, source_review_enabled: true,
        deep_research_enabled: true, selected_document_id: 'doc-1', selected_document_ids: ['doc-1'],
        conversation_task_document_ids: ['upload-1'], tags: ['tag'], doc_scope: 'group',
        active_group_ids: ['group-1'], active_group_id: 'group-1', active_public_workspace_ids: ['public-1'],
        active_public_workspace_id: 'public-1', analysis_result_context: { conversation_id: 'x' },
        document_action: { type: 'analyze' }, analyze: { enabled: true }, document_filter_mode: 'any',
        orchestration: { required_capabilities: ['web_search'] }, orchestration_context: { plan: 1 },
        image_references: [{ id: 'image-1' }],
    };
    const before = structuredClone(request);
    const shaped = client.applyWorkflowResultContext(request, {
        conversation_id: 'conversation-1', descriptor: { ...descriptor, result_ref: 'backend-only' },
    });
    assert.deepEqual(request, before, 'the request passed in is not changed');
    assert.deepEqual(shaped.workflow_result_context, context, 'only the three selector fields are sent');
    assert.equal(shaped.model_id, 'chosen-model');
    assert.deepEqual(shaped.agent_info, { id: 'local-agent' });
    for (const key of ['hybrid_search', 'web_search_enabled', 'url_access_enabled', 'source_review_enabled',
        'deep_research_enabled', 'image_generation', 'document_context_requested', 'user_workspace_context_enabled']) {
        assert.equal(shaped[key], false, key);
    }
    for (const key of ['selected_document_ids', 'conversation_task_document_ids', 'tags', 'active_group_ids',
        'active_public_workspace_ids']) {
        assert.deepEqual(shaped[key], [], key);
    }
    for (const key of ['selected_document_id', 'active_group_id', 'active_public_workspace_id']) {
        assert.equal(shaped[key], null, key);
    }
    assert.equal(shaped.doc_scope, 'personal');
    for (const key of ['analysis_result_context', 'document_action', 'analyze', 'document_filter_mode',
        'orchestration', 'orchestration_context', 'image_references']) {
        assert.equal(key in shaped, false, key);
    }
    if ('time_zone' in shaped) {
        assert.equal(typeof shaped.time_zone, 'string');
        assert.ok(shaped.time_zone.length > 0 && shaped.time_zone.length <= 64);
    }
    const zone = client.requestTimeZone();
    assert.ok(zone === undefined || (typeof zone === 'string' && zone.length <= 64));

    // A selection for another chat, or none, leaves the request exactly as it was.
    assert.equal(client.applyWorkflowResultContext(request, { conversation_id: 'conversation-2', descriptor }), request);
    assert.equal(client.applyWorkflowResultContext(request, null), request);
    assert.equal(client.applyWorkflowResultContext({ message: 'new chat' }, { conversation_id: 'conversation-1', descriptor }).workflow_result_context,
        undefined, 'a request without a conversation does not take a bound selection');
}

function testRefusals() {
    const changed = client.workflowResultErrorMessage('workflow_result_changed', 409);
    assert.match(changed, /result has changed since it was selected/);
    assert.equal(client.workflowResultErrorMessage(undefined, 401), 'Sign in again to ask about this workflow result.');
    assert.equal(client.workflowResultErrorMessage(undefined, 400), 'Workflow results in chat are not available.');
    assert.equal(client.workflowResultErrorMessage(undefined, 403), 'Workflow results in chat are not available.');
    assert.match(client.workflowResultErrorMessage(undefined, 404), /The run may have been removed/);
    assert.match(client.workflowResultErrorMessage('not_a_known_code', 404), /The run may have been removed/);
    assert.match(client.workflowResultErrorMessage(undefined, 503), /couldn't be read right now/);
    assert.equal(client.workflowResultErrorMessage(undefined, 500), 'This workflow result is unavailable.');
    assert.equal(client.workflowResultErrorMessage('__proto__', 500), 'This workflow result is unavailable.');
    assert.equal(client.WORKFLOW_RESULT_RETRY_UNSUPPORTED_MESSAGE,
        client.workflowResultErrorMessage('workflow_result_retry_unsupported'));

    const clearing = [
        'workflow_results_disabled', 'workflow_result_invalid_context', 'workflow_result_private_only',
        'workflow_result_not_found', 'workflow_result_access_denied', 'workflow_result_changed',
        'workflow_result_in_progress', 'workflow_result_not_finished', 'workflow_result_preview_only',
        'workflow_result_unsupported', 'workflow_result_invalid', 'workflow_result_conversation_unavailable',
    ];
    const keeping = [
        'workflow_result_storage_unavailable', 'workflow_result_too_large', 'workflow_result_model_unsupported',
        'workflow_result_answer_failed', 'workflow_result_answer_rejected', 'workflow_result_retry_unsupported',
        'workflow_result_context_conflict',
    ];
    for (const code of clearing) {
        // The stream's error event names the code `error_code`; the JSON precheck names it `code`.
        const streamed = client.workflowResultRefusal({ error: 'raw', error_code: code, status_code: 409 });
        const prechecked = client.workflowResultRefusal({ error: 'raw', code, warning_type: client.WORKFLOW_RESULT_WARNING_TYPE });
        assert.equal(streamed.clears, true, code);
        assert.equal(prechecked.clears, true, code);
        assert.equal(streamed.message, client.workflowResultErrorMessage(code), code);
        assert.notEqual(streamed.message, 'raw', 'the fixed wording is used, never the raw text');
    }
    for (const code of keeping) {
        assert.equal(client.workflowResultRefusal({ error_code: code }).clears, false, code);
    }
    const unknown = client.workflowResultRefusal({ error: 'Server sentence.', warning_type: client.WORKFLOW_RESULT_WARNING_TYPE });
    assert.deepEqual(unknown, { code: '', message: 'Server sentence.', clears: false });
    const fallback = client.workflowResultRefusal({ warning_type: client.WORKFLOW_RESULT_WARNING_TYPE, status_code: 404 });
    assert.match(fallback.message, /The run may have been removed/);
    assert.equal(client.workflowResultRefusal({ error: 'Model timed out', error_code: 'model_timeout' }), null);
    assert.equal(client.workflowResultRefusal({ error: 'Saved analysis gone', warning_type: 'saved_analysis_unavailable' }), null);
    assert.equal(client.workflowResultRefusal(null), null);
    assert.equal(client.workflowResultRefusal(undefined), null);
}

async function testDescriptorRead() {
    const requests = [];
    let reply = { status: 200, body: { workflow_result: descriptor } };
    globalThis.fetch = async (target, init) => {
        requests.push({ target: String(target), init });
        return new Response(JSON.stringify(reply.body), {
            status: reply.status, headers: { 'content-type': 'application/json' },
        });
    };

    assert.deepEqual(await client.fetchWorkflowResultDescriptor('wf-digest', 'run-7'), descriptor);
    assert.equal(requests.at(-1).target, '/api/user/workflows/wf-digest/runs/run-7/result-context');
    assert.equal(requests.at(-1).init.method, 'GET');
    assert.equal(client.workflowResultContextPath('wf:1', 'run.2'), '/api/user/workflows/wf%3A1/runs/run.2/result-context');

    const refusedWith = async (status, body) => {
        reply = { status, body };
        try {
            await client.fetchWorkflowResultDescriptor('wf-digest', 'run-7');
        } catch (error) {
            return error;
        }
        assert.fail(`status ${status} must be refused`);
    };
    for (const body of [
        { workflow_result: { ...descriptor, run_id: 'run-8' } },
        { workflow_result: { ...descriptor, workflow_id: 'wf-other' } },
        { workflow_result: { ...descriptor, available: false } },
        { workflow_result: { ...descriptor, result_sha256: 'nope' } },
        {},
    ]) {
        const error = await refusedWith(200, body);
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, 409);
        assert.equal(error.payload.code, 'workflow_result_invalid');
        assert.equal(client.isWorkflowResultUnavailable(error), true);
    }

    const missing = await refusedWith(404, { error: 'Workflow result not found.', code: 'workflow_result_not_found' });
    assert.equal(missing.status, 404);
    assert.match(client.workflowResultFetchErrorMessage(missing), /The run may have been removed/);
    assert.equal(client.isWorkflowResultUnavailable(missing), true);

    const changed = await refusedWith(409, { error: 'raw', code: 'workflow_result_in_progress' });
    assert.match(client.workflowResultFetchErrorMessage(changed), /hasn't finished yet/);

    const disabled = await refusedWith(403, { error: 'Forbidden' });
    assert.equal(client.workflowResultFetchErrorMessage(disabled), 'Workflow results in chat are not available.');

    const storage = await refusedWith(503, { error: 'raw', code: 'workflow_result_storage_unavailable' });
    assert.match(client.workflowResultFetchErrorMessage(storage), /couldn't be read right now/);
    assert.equal(client.isWorkflowResultUnavailable(storage), false, 'a transient failure is not "unavailable"');
    assert.match(client.workflowResultFetchErrorMessage(new TypeError('network down')), /couldn't be read right now/);

    const sent = requests.length;
    const invalid = await client.fetchWorkflowResultDescriptor('../wf', 'run-7').catch((error) => error);
    assert.equal(invalid.status, 404);
    assert.equal(requests.length, sent, 'an invalid id is never sent');
    delete globalThis.fetch;
}

function testChatLink() {
    const href = url.chatHrefForWorkflowResult('wf:digest', 'run.7');
    assert.equal(href, '/chat?result_workflow_id=wf%3Adigest&result_run_id=run.7&new=1');
    const params = new URLSearchParams(href.split('?')[1]);
    assert.deepEqual(url.readWorkflowResultLaunch(params), { workflow_id: 'wf:digest', run_id: 'run.7' });
    assert.equal(url.hasWorkflowResultLaunch(params), true);

    const read = (query) => url.readWorkflowResultLaunch(new URLSearchParams(query));
    assert.equal(read('result_workflow_id=wf&result_run_id=run'), null, 'only a new chat can carry one');
    assert.equal(read('result_workflow_id=wf&result_run_id=run&new=1&conversationId=c-1'), null);
    assert.equal(read('result_workflow_id=wf&result_run_id=run&new=1&agent_id=a-1'), null);
    assert.equal(read('result_workflow_id=wf&new=1'), null);
    assert.equal(read('result_workflow_id=..%2Fwf&result_run_id=run&new=1'), null);
    assert.equal(url.hasWorkflowResultLaunch(new URLSearchParams('result_run_id=x')), true);
    assert.equal(url.hasWorkflowResultLaunch(new URLSearchParams('prompt=x')), false);

    // The link is one-shot: the writer strips both ids and `new`, and keeps anything else.
    const stripped = url.syncedConversationParams(new URLSearchParams('result_workflow_id=wf&result_run_id=run&new=1&keep=1'), null);
    assert.equal(stripped.get('result_workflow_id'), null);
    assert.equal(stripped.get('result_run_id'), null);
    assert.equal(stripped.get('new'), null);
    assert.equal(stripped.get('keep'), '1');
    const opened = url.syncedConversationParams(new URLSearchParams('result_workflow_id=wf&result_run_id=run&new=1'), 'conversation-9');
    assert.equal(opened.get('result_workflow_id'), null);
    assert.equal(url.readConversationParam(opened), 'conversation-9');
    assert.equal(url.syncedConversationParams(new URLSearchParams(''), null), null, 'nothing to strip, nothing written');
}

function testAskInChatGating() {
    const personal = { type: 'personal' };
    const run = { id: 'run-7', status: 'completed', completed_at: descriptor.completed_at };
    assert.equal(client.canAskAboutWorkflowRun(personal, run, true), true);
    assert.equal(client.canAskAboutWorkflowRun(personal, { ...run, status: 'completed_partial' }, true), true);
    for (const status of ['failed', 'cancelled', 'running', 'queued', 'invalid', 'incomplete', undefined]) {
        assert.equal(client.canAskAboutWorkflowRun(personal, { ...run, status }, true), false, String(status));
    }
    assert.equal(client.canAskAboutWorkflowRun(personal, run, false), false, 'the setting off hides it');
    assert.equal(client.canAskAboutWorkflowRun({ type: 'group', groupId: 'g-1' }, run, true), false);
    assert.equal(client.canAskAboutWorkflowRun(personal, { ...run, definition_version: 3 }, true), false);
    assert.equal(client.canAskAboutWorkflowRun(personal, { ...run, id: '../run' }, true), false);
    assert.equal(client.workflowRunChatId({ run_id: 'run-legacy' }), 'run-legacy');
    assert.equal(client.workflowRunChatId({ id: 4 }), null);
    assert.equal(client.isWorkflowResultReadableStatus('completed'), true);
    assert.equal(client.isWorkflowResultReadableStatus('COMPLETED'), false);
}

function testAlertFollowUp() {
    const raw = (metadata) => ({
        id: `alert-${Math.random()}`, notification_type: 'workflow_priority_alert', title: 'Digest', message: 'Found items',
        created_at: new Date().toISOString(), is_read: false,
        metadata: {
            workflow_id: 'wf-digest', workflow_name: 'Weekly digest', workflow_scope: 'personal', run_id: 'run-7',
            status: 'completed', category: 'alert', priority: 'medium', ...metadata,
        },
    });
    const opened = [];
    const options = { enabled: true, open: (workflowId, runId) => opened.push([workflowId, runId]) };
    const alert = alerts.readWorkflowAlert(raw({}));
    assert.equal(alert.runStatus, 'completed');
    const action = alerts.workflowAlertFollowUpAction(alert, options);
    assert.equal(action.label, 'Ask about this');
    action.run();
    assert.deepEqual(opened, [['wf-digest', 'run-7']]);

    assert.ok(alerts.workflowAlertFollowUpAction(alerts.readWorkflowAlert(raw({ status: 'Completed_Partial ' })), options));
    assert.equal(alerts.workflowAlertFollowUpAction(alert), null, 'no options, no action');
    assert.equal(alerts.workflowAlertFollowUpAction(alert, { ...options, enabled: false }), null);
    for (const [label, metadata] of [
        ['group', { workflow_scope: 'group', workflow_group_id: 'group-1' }],
        ['no run', { run_id: '' }],
        ['no workflow', { workflow_id: '' }],
        ['failed', { status: 'failed', category: 'failure' }],
        ['cancelled', { status: 'cancelled' }],
        ['no status', { status: '' }],
        ['unknown scope', { workflow_scope: '' }],
    ]) {
        assert.equal(alerts.workflowAlertFollowUpAction(alerts.readWorkflowAlert(raw(metadata)), options), null, label);
    }
    assert.equal(opened.length, 1, 'building an action never opens anything');
}

function testChipLabel() {
    const label = client.workflowResultChipLabel(descriptor, 'en-US', 'UTC');
    assert.match(label, /^Answering from the Weekly digest run of Mon, Jan 5, 9:02[\s\u202f]AM — not re-running the workflow$/u);
    assert.equal(client.workflowResultChipLabel({ ...descriptor, completed_at: null }, 'en-US', 'UTC'),
        'Answering from the Weekly digest run — not re-running the workflow');
    assert.equal(client.formatWorkflowRunTime('not a date'), '');
    assert.equal(client.formatWorkflowRunTime(null), '');
    assert.equal(client.formatWorkflowRunTime(descriptor.completed_at, 'en-US', 'Not/AZone'), '');
    assert.match(client.formatWorkflowRunTime(descriptor.completed_at, 'en-US', 'America/New_York'), /Mon, Jan 5, 4:02/);
}

function testRetryGuard() {
    const thread = (id, attempt = 1) => ({ thread_info: { thread_id: id, thread_attempt: attempt } });
    const messages = [
        { id: 'plain-q', role: 'user', content: 'Hi', metadata: thread('t-0') },
        { id: 'plain-a', role: 'assistant', content: 'Hello', metadata: thread('t-0') },
        { id: 'result-q', role: 'user', content: 'What changed?', metadata: { ...thread('t-1'), workflow_result_context: context } },
        { id: 'result-a', role: 'assistant', content: 'Three items', metadata: { ...thread('t-1'), workflow_result: descriptor } },
        // Masked on read: the question lost its selector, the answer kept only the flag.
        { id: 'masked-q', role: 'user', content: 'And before?', metadata: thread('t-2') },
        { id: 'masked-a', role: 'assistant', content: 'Unavailable', metadata: { ...thread('t-2'), workflow_result: { version: 'workflow-result-v1', available: false } } },
    ];
    assert.equal(client.turnAsksAboutWorkflowResult(messages, 'plain-q'), false);
    assert.equal(client.turnAsksAboutWorkflowResult(messages, 'plain-a'), false);
    assert.equal(client.turnAsksAboutWorkflowResult(messages, 'result-q'), true);
    assert.equal(client.turnAsksAboutWorkflowResult(messages, 'result-a'), true);
    assert.equal(client.turnAsksAboutWorkflowResult(messages, 'masked-q'), true, 'found through its thread');
    assert.equal(client.turnAsksAboutWorkflowResult(messages, 'missing'), false);
    assert.equal(client.messageAsksAboutWorkflowResult(undefined), false);
}

const tests = [
    testDescriptorParsing, testLatestWorkflowResult, testRequestShaping, testRefusals, testDescriptorRead,
    testChatLink, testAskInChatGating, testAlertFollowUp, testChipLabel, testRetryGuard,
];
for (const test of tests) {
    await test();
    console.log(`passed ${test.name}`);
}
console.log(`Workflow results client contract passed (${tests.length} groups).`);
