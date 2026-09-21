// test_workflow_m365_run_as_client.js
/*
Functional tests for native V2 Microsoft 365 Run as authoring.
Version: 0.261.122
Implemented in: 0.261.122

Executes production TypeScript normalization, draft comparison, scoped account
lookup, and save serialization. Only HTTP transport is replaced; no application,
Microsoft 365 account, model, or live service is contacted.
Also covers nonterminal authorization waits and cancel-only runtime decisions.
*/

const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { afterEach, before, beforeEach, test } = require('node:test');

const root = path.resolve(__dirname, '..');
const nativeFetch = globalThis.fetch;
const personal = { type: 'personal' };
const group = { type: 'group', groupId: 'group/exact?name=Review&scope=personal' };
const requests = [];
const authorizationStates = [
    'awaiting_approval',
    'awaiting_sharing_approval',
    'awaiting_analysis_approval',
    'awaiting_run_as_approval',
    'awaiting_sign_in',
];
let editor;
let flow;
let respond;

before(async () => {
    await import(pathToFileURL(path.join(__dirname, 'test_support', 'tsResolve.mjs')));
    const sourceUrl = (name) => pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name}.ts`));
    editor = await import(sourceUrl('workflowEditor'));
    flow = await import(sourceUrl('workflowFlow'));
});

beforeEach(() => {
    requests.length = 0;
    respond = () => { throw new Error('Unexpected API request.'); };
    globalThis.fetch = async (url, init) => {
        const request = {
            url: new URL(url, 'https://simplechat.test'),
            ...init,
            body: init.body === undefined ? undefined : JSON.parse(init.body),
        };
        requests.push(request);
        return respond(request);
    };
});

afterEach(() => {
    globalThis.fetch = nativeFetch;
});

function savedWorkflow(scope = personal) {
    const draft = editor.newWorkflowDefinition(scope);
    draft.tasks[0].instructions = 'Review the approved records.';
    return editor.normalizeWorkflowDefinition({
        ...draft,
        id: 'existing-workflow',
        name: 'Review workflow',
        definition_revision: 'revision-before-edit',
        user_id: 'workflow-owner-not-consent',
        created_by: 'workflow-author-not-consent',
        m365_run_as_user_id: 'explicit-saved-account',
        file_sync: { source_id: 'existing-source', delete_policy: 'preserve' },
        alert_settings: { owner_on_failure: true },
        publication_options: { publish_to_public_workspace: false },
        metadata: { retained: { limit: 0, enabled: false } },
    }, scope);
}

test('new and legacy workflows never infer Run as from their owner, author, or group', () => {
    for (const scope of [personal, group]) {
        assert.equal(editor.newWorkflowDefinition(scope).m365_run_as_user_id, '');
        const existing = savedWorkflow(scope);
        delete existing.m365_run_as_user_id;
        const normalized = editor.normalizeWorkflowDefinition(existing, scope);
        assert.equal(normalized.m365_run_as_user_id, '');
        assert.equal(editor.workflowForSave(normalized, existing, scope).m365_run_as_user_id, '');
    }
});

test('authorized account lookup carries exact scope, credentials and cancellation without changing a draft', async () => {
    const draft = editor.newWorkflowDefinition(personal);
    const baseline = structuredClone(draft);
    for (const scope of [personal, group]) {
        requests.length = 0;
        const controller = new AbortController();
        respond = () => Response.json({ users: [{ id: 'signed-in-user', display_name: 'Current user' }] });
        const users = await editor.fetchWorkflowM365RunAsUsers(scope, controller.signal);
        assert.deepEqual(users, [{ id: 'signed-in-user', display_name: 'Current user' }]);
        assert.equal(requests.length, 1);
        const request = requests[0];
        assert.equal(request.method, 'GET');
        assert.equal(request.credentials, 'same-origin');
        assert.equal(request.signal, controller.signal);
        assert.equal(request.url.pathname, '/api/workflows/m365-run-as-users');
        assert.deepEqual(Object.fromEntries(request.url.searchParams), scope.type === 'group'
            ? { group_id: scope.groupId, scope: 'group' }
            : { scope: 'personal' });
        assert.deepEqual(draft, baseline);
        assert.equal(draft.m365_run_as_user_id, '');
    }
});

test('a missing group ID never falls back to the personal account list', async () => {
    respond = () => Response.json({ error: 'Select a group for this workflow.' }, { status: 400 });
    await assert.rejects(editor.fetchWorkflowM365RunAsUsers({ type: 'group', groupId: '' }),
        (cause) => cause.status === 400);
    assert.equal(requests[0].url.searchParams.get('scope'), 'group');
    assert.equal(requests[0].url.searchParams.get('group_id'), '');
});

test('account projection retains inert labels, deduplicates identities, and drops unrelated response fields', async () => {
    const label = '<img src=x onerror="unexpected()"> Group reviewer';
    respond = () => Response.json({
        users: [
            { id: 'group-user', display_name: 'Old label' },
            { id: 'group-user', display_name: label, unused_internal_field: 'not-an-option' },
            { id: 'unnamed-user' },
            { id: 'blank-label', display_name: ' ' },
        ],
        unused_internal_field: 'not-an-option',
    });
    assert.deepEqual(await editor.fetchWorkflowM365RunAsUsers(group), [
        { id: 'group-user', display_name: label },
        { id: 'unnamed-user', display_name: 'unnamed-user' },
        { id: 'blank-label', display_name: 'blank-label' },
    ]);
});

test('choosing and clearing are dirty edits, while returning to the saved choice restores the baseline', () => {
    const original = savedWorkflow();
    const draft = structuredClone(original);
    assert.equal(editor.sameWorkflowDefinition(original, draft), true);
    draft.m365_run_as_user_id = 'another-explicit-account';
    assert.equal(editor.sameWorkflowDefinition(original, draft), false);
    draft.m365_run_as_user_id = '';
    assert.equal(editor.sameWorkflowDefinition(original, draft), false);
    draft.m365_run_as_user_id = original.m365_run_as_user_id;
    assert.equal(editor.sameWorkflowDefinition(original, draft), true);
    assert.equal(editor.preservedWorkflowFieldLabels(original).some((label) => /365|run.as/i.test(label)), false);
});

test('personal and group saves serialize an explicit selection or empty string without losing saved metadata', async () => {
    for (const scope of [personal, group]) {
        for (const selected of ['chosen-account', '']) {
            const original = savedWorkflow(scope);
            const baseline = structuredClone(original);
            const draft = { ...structuredClone(original), m365_run_as_user_id: selected };
            respond = (request) => Response.json({ success: true, workflow: request.body });
            const response = await editor.saveWorkflowDefinition(scope, draft, original);
            const request = requests.at(-1);
            assert.equal(request.method, 'POST');
            assert.equal(request.url.pathname, scope.type === 'group' ? '/api/group/workflows' : '/api/user/workflows');
            assert.equal(request.url.searchParams.get('group_id'), scope.type === 'group' ? scope.groupId : null);
            assert.equal(request.body.m365_run_as_user_id, selected);
            assert.equal(request.body.definition_revision, original.definition_revision);
            for (const key of ['tasks', 'reference_inputs', 'file_sync', 'alert_settings', 'publication_options', 'metadata']) {
                assert.deepEqual(request.body[key], JSON.parse(JSON.stringify(original[key])));
            }
            assert.equal(editor.normalizeWorkflowDefinition(response.workflow, scope).m365_run_as_user_id, selected);
            assert.deepEqual(original, baseline);
        }
    }
});

test('an older draft omitting the field retains an explicitly saved account rather than inferring ownership', () => {
    const original = savedWorkflow();
    const draft = structuredClone(original);
    delete draft.m365_run_as_user_id;
    assert.equal(editor.workflowForSave(draft, original, personal).m365_run_as_user_id, 'explicit-saved-account');
    draft.m365_run_as_user_id = '';
    assert.equal(editor.workflowForSave(draft, original, personal).m365_run_as_user_id, '');
});

test('pending and absent account options do not clear an existing selection', async () => {
    const original = savedWorkflow();
    const draft = structuredClone(original);
    let finish;
    respond = () => new Promise((resolve) => { finish = resolve; });
    const loading = editor.fetchWorkflowM365RunAsUsers(personal);
    assert.equal(editor.workflowForSave(draft, original, personal).m365_run_as_user_id, 'explicit-saved-account');
    finish(Response.json({ users: [] }));
    assert.deepEqual(await loading, []);
    assert.equal(editor.workflowForSave(draft, original, personal).m365_run_as_user_id, 'explicit-saved-account');
    assert.equal(editor.sameWorkflowDefinition(original, draft), true);
});

test('forbidden, missing, failed and malformed account lists preserve the draft and saved revision', async () => {
    const original = savedWorkflow(group);
    const draft = structuredClone(original);
    const responses = [
        ...[401, 403, 404, 503].map((status) => () => Response.json({ error: 'Unsafe server diagnostic' }, { status })),
        () => { throw new TypeError('Network unavailable'); },
        ...[null, [], {}, { users: null }, { users: [null] }, { users: [{ id: 42 }] },
            { users: [{ id: ' ' }] }, { users: [{ id: 'user', display_name: {} }] },
        ].map((payload) => () => Response.json(payload)),
    ];
    for (const respondToRequest of responses) {
        respond = respondToRequest;
        await assert.rejects(editor.fetchWorkflowM365RunAsUsers(group));
        assert.deepEqual(draft, original);
        const saved = editor.workflowForSave(draft, original, group);
        assert.equal(saved.m365_run_as_user_id, 'explicit-saved-account');
        assert.equal(saved.definition_revision, 'revision-before-edit');
    }
});

test('a stale save retains the selected account and original revision for the existing retry/discard flow', async () => {
    const original = savedWorkflow();
    const baseline = structuredClone(original);
    const draft = { ...structuredClone(original), m365_run_as_user_id: 'new-explicit-account' };
    respond = () => Response.json({ error: 'Stale workflow definition.' }, { status: 409 });
    await assert.rejects(editor.saveWorkflowDefinition(personal, draft, original), (cause) => {
        assert.equal(cause.status, 409);
        assert.match(editor.workflowErrorMessage(cause, ''), /draft has been retained/);
        return true;
    });
    assert.equal(draft.m365_run_as_user_id, 'new-explicit-account');
    assert.equal(requests[0].body.definition_revision, original.definition_revision);
    assert.deepEqual(original, baseline);
});

test('Run as edits preserve structured, For each and Repeat until definitions exactly', () => {
    const definition = savedWorkflow(group);
    const contract = {
        kind: 'json',
        schema: { type: 'object', properties: { ready: { type: 'boolean' } }, required: ['ready'] },
        require_complete_coverage: false,
        allow_partial: false,
    };
    definition.tasks[0].output_contract = contract;
    definition.tasks.unshift({ ...structuredClone(definition.tasks[0]), id: 'seed-review', name: 'Seed review', order: 1 });
    definition.tasks[1].order = 2;
    const original = flow.convertToStructuredWorkflow(editor.normalizeWorkflowDefinition(definition, group), 'root');
    const taskNode = original.flow.nodes[1];
    const nextReview = {
        name: 'next_review',
        source: { kind: 'node_output', node_id: taskNode.id, output: 'json', scope: 'current' },
        required: true,
        expected_kind: 'json',
        allow_partial: false,
    };
    original.tasks[1].inputs = [{
        ...nextReview,
        name: 'review',
        source: { kind: 'repeat_state', loop_id: 'repeat-review', state_name: 'review', scope: 'current' },
    }];
    original.flow.nodes = [original.flow.nodes[0], {
        id: 'each-source',
        kind: 'for_each',
        inputs: [],
        iterable: { kind: 'documents', documents: [{ scope_type: 'group', scope_id: group.groupId, document_id: 'brief' }] },
        item_key: 'source_identity',
        max_items: 5,
        body: {
            id: 'each-body',
            nodes: [{
                id: 'repeat-review',
                kind: 'repeat_until',
                max_iterations: 3,
                state: [{
                    name: 'review',
                    initial: { kind: 'node_output', node_id: 'seed-review', output: 'json', scope: 'current' },
                    next: 'next_review',
                    output_contract: contract,
                }],
                body: { id: 'repeat-body', nodes: [taskNode], outputs: [nextReview] },
                until: { op: 'eq', left: { input: 'review', path: '/ready' }, right: { literal: true } },
                exports: [{ name: 'review', output: 'next_review' }],
            }],
            outputs: [],
        },
    }];
    assert.equal(flow.flowUnsupportedReason(original), '');
    const baseline = structuredClone(original);
    const saved = editor.workflowForSave({
        ...structuredClone(original), m365_run_as_user_id: 'selected-group-reviewer',
    }, original, group);
    assert.equal(saved.m365_run_as_user_id, 'selected-group-reviewer');
    assert.equal(saved.definition_version, 3);
    assert.equal(saved.durable_execution, true);
    assert.deepEqual(saved.flow, baseline.flow);
    assert.deepEqual(saved.limits, baseline.limits);
    assert.deepEqual(saved.tasks, baseline.tasks);
    assert.equal(saved.definition_revision, baseline.definition_revision);
    assert.deepEqual(original, baseline);
});

function authorizationGate() {
    return {
        id: 'm365-authorization',
        kind: 'pause',
        reason_code: 'm365_authorization',
        reason: 'Complete the required step in Approvals or Microsoft 365 connection settings.',
        choices: ['cancel'],
    };
}

test('all five Microsoft 365 wait states remain nonterminal in personal/group runtime and history responses', async () => {
    for (const scope of [personal, group]) {
        for (const state of authorizationStates) {
            const runtime = { version: 4, state, gate: authorizationGate(), can_resume: true };
            respond = (request) => Response.json(request.url.pathname.endsWith('/runtime')
                ? { runtime, can_decide: true }
                : { runs: [{ id: 'waiting-run', status: state, durable_execution: true }] });
            const response = await editor.fetchWorkflowRuntime(scope, 'workflow', 'waiting-run');
            const runs = await editor.fetchScopedWorkflowRuns(scope, 'workflow');
            assert.equal(response.runtime.state, state);
            assert.equal(editor.WORKFLOW_RUNTIME_TERMINAL_STATES.has(state), false);
            assert.equal(runs[0].status, state);
            assert.equal(runs[0].durable_execution, true);
            assert.equal(editor.workflowRuntimeCanResume(response.runtime), false);
            assert.equal(editor.workflowRuntimeGateAllowsDecision(response.runtime.gate, 'cancel'), true);
            for (const request of requests.slice(-2)) {
                assert.equal(request.method, 'GET');
                assert.equal(request.url.searchParams.get('group_id'), scope.type === 'group' ? scope.groupId : null);
            }
        }
    }
});

test('Microsoft 365 gates cannot offer generic approve/resume even with stale failure flags or broader choices', () => {
    const gate = {
        ...authorizationGate(),
        choices: ['approve', 'reject', 'retry', 'resume', 'continue_repeat', 'cancel'],
    };
    for (const choice of gate.choices) {
        assert.equal(editor.workflowRuntimeGateAllowsDecision(gate, choice), choice === 'cancel', choice);
    }
    for (const state of ['failed', 'incomplete', 'invalid', ...authorizationStates]) {
        assert.equal(editor.workflowRuntimeCanResume({ version: 1, state, can_resume: true, gate }), false);
    }
});

test('ordinary workflow approval, recovery, publication and Repeat affordances remain unchanged', () => {
    const gate = { id: 'ordinary-gate', kind: 'approval', choices: ['approve', 'reject'] };
    assert.equal(editor.workflowRuntimeGateAllowsDecision(gate, 'approve'), true);
    assert.equal(editor.workflowRuntimeGateAllowsDecision(gate, 'reject'), true);
    assert.equal(editor.workflowRuntimeGateAllowsDecision(gate, 'resume'), false);
    assert.equal(editor.workflowRuntimeGateAllowsDecision(undefined, 'cancel'), false);
    assert.equal(editor.workflowRuntimeGateAllowsDecision({ ...gate, kind: 'recovery', choices: ['retry', 'cancel'] }, 'retry'), true);
    const publication = { ...gate, publication: {}, choices: ['approve', 'reject', 'retry', 'resume', 'cancel'] };
    for (const choice of publication.choices) {
        assert.equal(editor.workflowRuntimeGateAllowsDecision(publication, choice), ['resume', 'cancel'].includes(choice));
    }
    const repeat = { ...gate, kind: 'pause', reason_code: 'repeat_iteration_limit', choices: ['continue_repeat', 'cancel'] };
    assert.equal(editor.workflowRuntimeGateAllowsDecision(repeat, 'continue_repeat'), true);
    assert.equal(editor.workflowRuntimeGateAllowsDecision(repeat, 'cancel'), true);
    assert.equal(editor.workflowRuntimeGateAllowsDecision(repeat, 'resume'), false);
    assert.equal(editor.workflowRuntimeCanResume({ version: 1, state: 'failed', can_resume: true }), true);
    assert.equal(editor.workflowRuntimeCanResume({ version: 1, state: 'failed', can_resume: true, gate: repeat }), false);
    assert.equal(editor.workflowRuntimeCanResume(null), false);
});

test('Flow explains Microsoft 365 authorization without mislabelling it as a Repeat budget stop', () => {
    const notice = editor.workflowRuntimeGateNotice(authorizationGate());
    assert.match(notice, /Cancel only/);
    assert.match(notice, /Approvals or Microsoft 365 connection settings/);
    assert.match(notice, /not workflow Resume or Approve task/);
    assert.doesNotMatch(notice, /Retained Repeat/);
    assert.match(editor.workflowRuntimeGateNotice({
        id: 'limit', kind: 'pause', reason_code: 'max_executions', choices: ['cancel'],
    }), /Retained Repeat progress does not permit another batch/);
    assert.equal(editor.workflowRuntimeGateNotice({
        id: 'approval', kind: 'approval', choices: ['approve', 'reject'],
    }), 'Decisions remain in the separate runtime panel.');
});
