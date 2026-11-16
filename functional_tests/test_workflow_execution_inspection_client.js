// test_workflow_execution_inspection_client.js
/*
Functional tests for exact, read-only workflow execution inspection.
Version: 0.261.121
Implemented in: 0.261.121

Uses the existing TypeScript compiler to execute the real client and guards.
Only API transport is mocked; no browser, backend, or live service is needed.
*/

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { beforeEach, test } = require('node:test');

const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'application', 'v2_ui', 'node_modules', 'typescript'));
const modules = new Map();
const requests = [];
let respond;

class ApiError extends Error {
    constructor(message, status, payload) {
        super(message);
        this.status = status;
        this.payload = payload;
    }
}

const api = {
    get: async (url, signal) => {
        requests.push({ url, signal });
        return respond(url, signal);
    },
};

function loadModule(name) {
    if (name === './apiClient') return { api, ApiError };
    if (modules.has(name)) return modules.get(name);
    const filename = path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name.replace('./', '')}.ts`);
    const source = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
        compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    }).outputText;
    const module = { exports: {} };
    modules.set(name, module.exports);
    vm.runInNewContext(source, {
        module, exports: module.exports, require: loadModule, URL, URLSearchParams,
    }, { filename });
    return module.exports;
}

const {
    fetchWorkflowExecutionForNode,
    fetchWorkflowExecutionsPage,
    fetchWorkflowRepeatStatePage,
} = loadModule('./workflowExecutionHistory');
const personal = { type: 'personal' };
const group = { type: 'group', groupId: 'group/exact' };
const mixedPath = [
    { loop_id: 'outer_each', item_id: 'a'.repeat(64), index: 4999 },
    { loop_id: 'repeat', iteration: 1000 },
    { loop_id: 'inner_each', item_id: 'b'.repeat(64), index: 0 },
];

function execution(iterationPath = []) {
    return {
        execution_id: 'server-resolved-execution',
        node_id: 'selected_node',
        node_kind: 'task',
        state: 'skipped',
        attempt: 0,
        iteration_path: structuredClone(iterationPath),
    };
}

function responseFor(items = []) {
    return { executions: items, next_cursor: null, total_count: items.length };
}

function requestedUrl() {
    assert.equal(requests.length, 1, 'An exact lookup must make one request, never scan history.');
    return new URL(requests[0].url, 'https://simplechat.test');
}

beforeEach(() => {
    requests.length = 0;
    respond = () => { throw new Error('Unexpected API request.'); };
});

test('root selection uses the exact server identity, one bounded GET, and its AbortSignal', async () => {
    const saved = execution();
    const controller = new AbortController();
    respond = () => responseFor([saved]);
    const result = await fetchWorkflowExecutionForNode(
        personal, 'workflow/fixture', 'run:fixture', saved.node_id, [], controller.signal,
    );
    assert.equal(result, saved);
    const url = requestedUrl();
    assert.equal(url.pathname, '/api/user/workflows/workflow%2Ffixture/runs/run%3Afixture/executions');
    assert.equal(url.searchParams.get('node_id'), saved.node_id);
    assert.equal(url.searchParams.get('iteration_path'), '[]');
    assert.equal(url.searchParams.get('limit'), '1');
    assert.equal(url.searchParams.has('cursor'), false);
    assert.equal(url.searchParams.has('group_id'), false);
    assert.equal(requests[0].signal, controller.signal);
});

test('group selection retains every mixed frame and lifetime round 1001 independent of object key order', async () => {
    const saved = execution(mixedPath);
    saved.iteration_path = [
        { index: 4999, item_id: 'a'.repeat(64), loop_id: 'outer_each' },
        { iteration: 1000, loop_id: 'repeat' },
        { item_id: 'b'.repeat(64), index: 0, loop_id: 'inner_each' },
    ];
    respond = () => responseFor([saved]);
    assert.equal(await fetchWorkflowExecutionForNode(group, 'workflow', 'run', saved.node_id, mixedPath), saved);
    const url = requestedUrl();
    assert.equal(url.pathname, '/api/group/workflows/workflow/runs/run/executions');
    assert.equal(url.searchParams.get('group_id'), group.groupId);
    assert.deepEqual(JSON.parse(url.searchParams.get('iteration_path')), mixedPath);
});

test('only a valid zero-result envelope becomes unobserved, without a latest-execution fallback', async () => {
    respond = () => responseFor();
    assert.equal(await fetchWorkflowExecutionForNode(personal, 'workflow', 'run', 'selected_node', mixedPath), null);
    assert.equal(requestedUrl().searchParams.get('limit'), '1');
});

test('malformed, unbounded, unknown, or contradictory success envelopes fail explicitly', async () => {
    const saved = execution();
    const invalidResponses = [
        undefined, null, [], 'unknown', {}, { error: 'denied' },
        { executions: null, next_cursor: null, total_count: 0 },
        { executions: [], total_count: 0 },
        { executions: [], next_cursor: null },
        { executions: [], next_cursor: '', total_count: 0 },
        { executions: [], next_cursor: 'next-page', total_count: 0 },
        { executions: [], next_cursor: 0, total_count: 0 },
        { executions: [], next_cursor: null, total_count: '0' },
        { executions: [], next_cursor: null, total_count: -1 },
        { executions: [], next_cursor: null, total_count: 1 },
        { executions: [saved], next_cursor: null, total_count: 0 },
        { ...responseFor(), unexpected: 'unknown-contract' },
        responseFor([saved, { ...saved, execution_id: 'another-execution' }]),
        responseFor([null]),
        responseFor([{ ...saved, execution_id: '' }]),
        responseFor([{ ...saved, node_kind: null }]),
        responseFor([{ ...saved, state: null }]),
        responseFor([{ ...saved, attempt: -1 }]),
        responseFor([{ ...saved, attempt: 0.5 }]),
        responseFor([{ ...saved, workflow_result: [] }]),
        responseFor([{ ...saved, workflow_validation: [] }]),
        responseFor([{ ...saved, iteration_path: undefined }]),
        responseFor([{ ...saved, node_id: 'another_node' }]),
        responseFor([{ ...saved, iteration_path: [{ loop_id: 'repeat', iteration: 0 }] }]),
    ];
    for (const value of invalidResponses) {
        requests.length = 0;
        respond = () => value;
        await assert.rejects(fetchWorkflowExecutionForNode(personal, 'workflow', 'run', saved.node_id, []));
        requestedUrl();
    }
});

test('same node and innermost identity cannot hide a different outer scope or frame', async () => {
    const differentPaths = [
        mixedPath.slice(1),
        [...mixedPath].reverse(),
        [{ ...mixedPath[0], index: 4998 }, ...mixedPath.slice(1)],
        [{ ...mixedPath[0], item_id: 'c'.repeat(64) }, ...mixedPath.slice(1)],
        [mixedPath[0], { loop_id: 'different_repeat', iteration: 1000 }, mixedPath[2]],
        [mixedPath[0], { loop_id: 'repeat', iteration: 999 }, mixedPath[2]],
        [mixedPath[0], { ...mixedPath[1], item_id: 'c'.repeat(64), index: 1 }, mixedPath[2]],
        [...mixedPath, { loop_id: 'too_deep', iteration: 0 }],
    ];
    for (const iterationPath of differentPaths) {
        requests.length = 0;
        respond = () => responseFor([execution(iterationPath)]);
        await assert.rejects(fetchWorkflowExecutionForNode(group, 'workflow', 'run', 'selected_node', mixedPath));
        requestedUrl();
    }
});

test('invalid selectors are rejected before making a request', async () => {
    const invalidSelectors = [
        ['', []], [' ', []], ['n'.repeat(257), []],
        ['selected_node', undefined], ['selected_node', null], ['selected_node', {}],
        ['selected_node', [{ loop_id: 'repeat', iteration: 5000 }]],
        ['selected_node', [{ loop_id: 'repeat', iteration: -1 }]],
        ['selected_node', [{ loop_id: 'repeat', iteration: 1, extra: true }]],
        ['selected_node', [{ loop_id: 'each', item_id: 'not-a-frozen-id', index: 0 }]],
        ['selected_node', [{ loop_id: 'each', item_id: 'a'.repeat(64), index: 5000 }]],
        ['selected_node', [{ loop_id: 'repeat', iteration: 0 }, { loop_id: 'repeat', iteration: 1 }]],
        ['selected_node', [...mixedPath, { loop_id: 'fourth', iteration: 0 }]],
    ];
    for (const [nodeId, iterationPath] of invalidSelectors) {
        await assert.rejects(fetchWorkflowExecutionForNode(personal, 'workflow', 'run', nodeId, iterationPath));
    }
    assert.equal(requests.length, 0);
});

test('caller mutation cannot retarget the identity of an in-flight lookup', async () => {
    const selectedPath = structuredClone(mixedPath);
    const saved = execution(selectedPath);
    let finish;
    respond = () => new Promise((resolve) => { finish = resolve; });
    const pending = fetchWorkflowExecutionForNode(group, 'workflow', 'run', saved.node_id, selectedPath);
    selectedPath[0].index = 0;
    selectedPath[1].iteration = 1;
    selectedPath.pop();
    finish(responseFor([saved]));
    assert.equal(await pending, saved);
    assert.deepEqual(JSON.parse(requestedUrl().searchParams.get('iteration_path')), mixedPath);
});

test('source revocation, missing history, and abort remain errors, not empty-success or fallback', async () => {
    for (const error of [
        new ApiError('Source access revoked.', 403, {}),
        new ApiError('Run unavailable.', 404, {}),
        new DOMException('Request aborted.', 'AbortError'),
    ]) {
        requests.length = 0;
        respond = () => { throw error; };
        await assert.rejects(
            fetchWorkflowExecutionForNode(personal, 'workflow', 'run', 'selected_node', []),
            (actual) => actual === error,
        );
        requestedUrl();
    }
});

test('ordinary history paging retains optional root paths, 50 defaults, and a 100-entry maximum', async () => {
    const saved = execution();
    delete saved.iteration_path;
    respond = () => ({ executions: [saved], next_cursor: 'next', total_count: 3 });
    const page = await fetchWorkflowExecutionsPage(personal, 'workflow', 'run', 'previous');
    assert.equal(page.items[0], saved);
    assert.equal(page.next_cursor, 'next');
    assert.equal(requestedUrl().searchParams.get('limit'), '50');
    assert.equal(requestedUrl().searchParams.get('cursor'), 'previous');
    requests.length = 0;
    await fetchWorkflowExecutionsPage(personal, 'workflow', 'run', null, 100);
    assert.equal(requestedUrl().searchParams.get('limit'), '100');
    requests.length = 0;
    await assert.rejects(fetchWorkflowExecutionsPage(personal, 'workflow', 'run', null, 101));
    assert.equal(requests.length, 0);
});

test('unavailable after-state for lifetime round 1001 stays unavailable rather than an eligible empty result', async () => {
    respond = () => ({
        repeat_execution_id: 'repeat-execution', iteration: 1000, phase: 'after',
        available: false, states: [], next_cursor: null, total_count: 0,
    });
    const page = await fetchWorkflowRepeatStatePage(personal, 'workflow', 'run', 'repeat-execution', 1000, 'after', null);
    assert.equal(page.metadata.stateAvailable, false);
    assert.equal(page.items.length, 0);
    assert.equal(page.next_cursor, null);
    assert.equal(requestedUrl().searchParams.get('limit'), '50');
});
