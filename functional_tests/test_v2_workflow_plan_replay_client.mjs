// test_v2_workflow_plan_replay_client.mjs
// Version: 0.261.305
// Implemented in: 0.261.305
// Exercises the V2 plan-replay client contract: preview and save parsing, fixed refusal copy,
// typed replay run results, stored replay summaries, capability labels, and workflow editor
// round-tripping of read-only plan_replay tasks.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import './test_support/tsResolve.mjs';

const calls = [];
let script = [];

globalThis.fetch = async (url, init = {}) => {
    const call = {
        url: String(url),
        method: init.method ?? 'GET',
        body: init.body,
        credentials: init.credentials,
        headers: { ...(init.headers ?? {}) },
    };
    calls.push(call);
    assert.ok(script.length, `Unexpected request: ${call.method} ${call.url}`);
    const next = script.shift();
    if (next instanceof Error) throw next;
    return next;
};

const {
    ERROR_TEXT,
    PLAN_REPLAY_ALERT_NOTICE,
    PLAN_REPLAY_ALERT_RULE_NAME,
    PLAN_REPLAY_CAPABILITY_LABELS,
    PLAN_REPLAY_GENERIC_ERROR,
    PLAN_REPLAY_INVALID_RESPONSE,
    describePlanReplayTimeHandling,
    fetchPlanReplayPreview,
    planReplayError,
    planReplayRunTimeZone,
    planReplaySummary,
    readPlanReplayResult,
    savePlanReplayWorkflow,
} = await import('../application/v2_ui/src/lib/workflowPlanReplay.ts');
const { ApiError } = await import('../application/v2_ui/src/lib/apiClient.ts');
const {
    normalizeWorkflowDefinition,
    workflowForSave,
    workflowPlanReplayTask,
    workflowValidationErrors,
} = await import('../application/v2_ui/src/lib/workflowEditor.ts');

const SERVER_DIR = new URL('../application/single_app/', import.meta.url);
const HASH = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
const CONVERSATION_ID = 'chat-1';
const RUN_ID = 'run-1';

/** Runs AST-only Python with the first interpreter found; nothing from the app is imported. */
function runPython(source) {
    const env = {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
        SIMPLECHAT_SERVER_DIR: fileURLToPath(SERVER_DIR),
    };
    let missing;
    for (const executable of [process.env.PYTHON, 'python', 'python3'].filter(Boolean)) {
        try {
            return execFileSync(executable, ['-c', source], { encoding: 'utf8', env });
        } catch (error) {
            if (error?.code === 'ENOENT') {
                missing = error;
                continue;
            }
            throw error;
        }
    }
    throw missing ?? new Error('No Python interpreter was found.');
}

function serverConstants() {
    const source = String.raw`
import ast
import json
import os
from pathlib import Path
root = Path(os.environ['SIMPLECHAT_SERVER_DIR'])

def literal(module, name):
    tree = ast.parse((root / f'{module}.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f'{module}.{name} not found')
print(json.dumps({
    'refusals': literal('functions_workflow_plan_replay', 'REFUSAL_MESSAGES'),
    'alert_rule_name': literal('functions_workflow_plan_replay', 'PLAN_REPLAY_DEFAULT_ALERT_RULE_NAME'),
}))
`;
    return JSON.parse(runPython(source));
}

function registryLabels() {
    const source = String.raw`
import ast
import json
import os
from pathlib import Path
root = Path(os.environ['SIMPLECHAT_SERVER_DIR'])
tree = ast.parse((root / 'functions_orchestration_registry.py').read_text(encoding='utf-8'))
assigned = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        try:
            assigned[node.targets[0].id] = ast.literal_eval(node.value)
        except Exception:
            pass

def eval_node(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return assigned.get(node.id)
    raise ValueError(type(node).__name__)
labels = {}
for node in ast.walk(tree):
    if isinstance(node, ast.Dict):
        pairs = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value in ('id', 'label'):
                try:
                    pairs[key.value] = eval_node(value)
                except Exception:
                    pass
        if isinstance(pairs.get('id'), str) and isinstance(pairs.get('label'), str):
            labels[pairs['id']] = pairs['label']
print(json.dumps(labels))
`;
    return JSON.parse(runPython(source));
}

function json(status, body) {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function reset(...responses) {
    calls.length = 0;
    script = responses;
}

function preview(overrides = {}) {
    return {
        eligible: true,
        request: 'Review the invoices <img src=x onerror=alert(1)>',
        steps: [
            { number: 1, step_id: 'search', title: 'Search docs', capability_id: 'document_search', capability_label: 'Search documents', enabled: true },
            { number: 2, step_id: 'compose', title: 'Write answer', capability_id: 'compose', capability_label: 'Prepare content', enabled: true },
        ],
        refusals: [],
        plan_sha256: HASH,
        time_handling: 'frozen_with_run_time_line',
        time_zone: 'America/New_York',
        min_interval_seconds: 900,
        allowlist_version: 'plan-replay-allowlist-v1',
        max_steps: 8,
        ...overrides,
    };
}

function replayTask(planReplayOverrides = {}) {
    return {
        id: 'task-1',
        type: 'plan_replay',
        name: 'Repeat saved plan',
        instructions: 'Review invoices',
        runner: { type: 'inherit' },
        plan_replay: {
            version: 1,
            allowlist_version: 'plan-replay-allowlist-v1',
            request: 'Review invoices',
            frozen_plan: {
                steps: [
                    { step_id: 'search', title: 'Find invoices', capability_id: 'document_search', arguments: { threshold: 1.0, nested: [1.0, { x: 2.0 }] }, enabled: true },
                    { step_id: 'mystery', title: 'Mystery', capability_id: 'unknown_capability', arguments: {}, enabled: true },
                ],
            },
            frozen_seeds: { alpha: 1.0 },
            plan_sha256: HASH,
            approval: { approved_by: 'user-1', approved_at: '2026-10-08T10:00:00Z', plan_sha256: HASH },
            provenance: {
                source_run_id: RUN_ID,
                source_conversation_id: CONVERSATION_ID,
                created_by: 'user-1',
                frozen_at: '2026-10-08T10:00:00Z',
                time_handling: 'frozen_with_run_time_line',
                time_zone: 'America/New_York',
            },
            ...planReplayOverrides,
        },
    };
}

function workflow(task = replayTask(), overrides = {}) {
    return {
        id: 'workflow-1',
        definition_version: 2,
        definition_revision: 'rev-1',
        name: 'Repeat invoice review',
        description: '',
        runner_type: 'model',
        chat_capabilities_enabled: false,
        trigger_type: 'manual',
        schedule: { unit: 'hours', value: 24 },
        is_enabled: false,
        error_handling: { strategy: 'halt', retry_count: 0 },
        tasks: [task],
        reference_inputs: [],
        durable_execution: false,
        ...overrides,
    };
}

function options() {
    return {
        definition_version: 2,
        supported_definition_versions: [2],
        can_manage: true,
        max_tasks: 10,
        agents: [],
        models: [],
        default_model: { valid: false },
        scope: { type: 'personal' },
        schedule: { min_interval_seconds: 300, calendar: true, timezones: ['UTC', 'America/New_York'] },
    };
}

test('preview parser accepts the server shape and fetches only the requested URL', async () => {
    reset(json(200, preview()));
    const parsed = await fetchPlanReplayPreview(RUN_ID, CONVERSATION_ID);
    assert.equal(parsed.plan_sha256, HASH);
    assert.equal(parsed.steps[0].capability_label, 'Search documents');
    assert.equal(calls[0].method, 'GET');
    assert.equal(calls[0].url, `/api/v2/orchestration/runs/${RUN_ID}/plan-replay?conversation_id=${CONVERSATION_ID}`);
});

test('preview parser fails closed for malformed responses', async () => {
    for (const body of [
        preview({ plan_sha256: 'bad' }),
        preview({ steps: {} }),
        preview({ steps: [{ number: 1 }] }),
        preview({ refusals: {} }),
        preview({ time_handling: 'live' }),
        { ...preview(), eligible: 'yes' },
    ]) {
        reset(json(200, body));
        await assert.rejects(fetchPlanReplayPreview(RUN_ID, CONVERSATION_ID), { message: PLAN_REPLAY_INVALID_RESPONSE });
    }
});

test('save request sends the body and validates created/status parity', async () => {
    const body = { conversation_id: CONVERSATION_ID, plan_sha256: HASH, name: 'Repeat it', enabled: false };
    reset(json(201, { ok: true, workflow: workflow(), created: true }));
    const created = await savePlanReplayWorkflow(RUN_ID, body);
    assert.equal(created.created, true);
    assert.equal(calls[0].method, 'POST');
    assert.deepEqual(JSON.parse(calls[0].body), body);

    reset(json(200, { ok: true, workflow: workflow(), created: false }));
    const existing = await savePlanReplayWorkflow(RUN_ID, body);
    assert.equal(existing.created, false);

    reset(json(200, { ok: true, workflow: workflow(), created: true }));
    await assert.rejects(savePlanReplayWorkflow(RUN_ID, body), { message: PLAN_REPLAY_INVALID_RESPONSE });
});

test('client refusal text mirrors server constants and handles generic refusals', () => {
    assert.deepEqual(ERROR_TEXT, serverConstants().refusals);
    assert.equal(planReplayError(new ApiError('Forbidden', 403, { error: 'Forbidden' })).text,
        'You do not have access to save this chat plan as a workflow.');
    assert.equal(planReplayError(new ApiError('nope', 422, { code: 'new_code', error: 'server words' })).text,
        PLAN_REPLAY_GENERIC_ERROR);
    assert.equal(planReplayError(new ApiError('Minimum cadence is 15 minutes.', 422, {
        code: 'cadence_below_minimum', error: 'Minimum cadence is 15 minutes.',
    })).text, 'Minimum cadence is 15 minutes.');
    assert.equal(planReplayError(new ApiError('changed', 409, { code: 'plan_hash_mismatch', error: 'ignored' })).text,
        ERROR_TEXT.plan_hash_mismatch);
});

test('the card names the failure alert rule the server saves on every replay workflow', () => {
    assert.equal(PLAN_REPLAY_ALERT_RULE_NAME, serverConstants().alert_rule_name);
    assert.equal(PLAN_REPLAY_ALERT_NOTICE,
        "If a run fails, you'll get a 'Run failed' notification in the bell. You can change this in the workflow's alerts.");
});

test('typed run result parser accepts only the plan replay contract', () => {
    const result = readPlanReplayResult({
        contract: 'plan-replay-result-v1',
        orchestration_run_id: RUN_ID,
        conversation_id: CONVERSATION_ID,
        plan_sha256: HASH,
        status: 'completed',
        outcome: 'completed',
        steps: [{ step_id: 'compose', capability_id: 'compose', label: 'Prepare content', status: 'completed' }],
        final_response: { message_id: 'message-1', text: '<script>inert</script>' },
        artifacts: [{ id: 'image-1', kind: 'image', message_id: 'message-2' }, { id: 'file-1', kind: 'file' }],
    });
    assert.equal(result?.final_response.text, '<script>inert</script>');
    assert.equal(result?.final_response.truncated, undefined);
    const capped = readPlanReplayResult({
        contract: 'plan-replay-result-v1', orchestration_run_id: RUN_ID, conversation_id: CONVERSATION_ID,
        plan_sha256: HASH, status: 'completed', outcome: 'completed', steps: [],
        final_response: { message_id: 'message-1', text: 'start', truncated: true }, artifacts: [],
    });
    assert.equal(capped?.final_response.truncated, true);
    assert.equal(readPlanReplayResult({
        contract: 'plan-replay-result-v1', orchestration_run_id: RUN_ID, conversation_id: CONVERSATION_ID,
        plan_sha256: HASH, status: 'completed', outcome: 'completed', steps: [],
        final_response: { message_id: 'message-1', text: 'x' }, artifacts: [{ id: 'a', kind: 'spreadsheet' }],
    }), null);
    assert.equal(readPlanReplayResult({ contract: 'other' }), null);
    assert.equal(readPlanReplayResult({ contract: 'plan-replay-result-v1', plan_sha256: 'bad' }), null);
});

test('stored replay summaries and capability labels are stable', () => {
    const summary = planReplaySummary(replayTask());
    assert.equal(summary?.request, 'Review invoices');
    assert.equal(summary?.steps[0].label, 'Search documents');
    assert.equal(summary?.steps[1].label, 'Unknown step');
    assert.equal(summary?.frozen_at, '2026-10-08T10:00:00Z');
    assert.match(describePlanReplayTimeHandling('America/New_York'), /current date and time in America\/New_York/);

    const labels = registryLabels();
    for (const [capability, label] of Object.entries(PLAN_REPLAY_CAPABILITY_LABELS)) {
        assert.equal(label, labels[capability], capability);
    }
});

test('workflow editor keeps plan_replay tasks unchanged and skips runner/task validation', () => {
    const originalReplay = replayTask();
    const normalized = normalizeWorkflowDefinition(workflow(originalReplay));
    assert.equal(workflowPlanReplayTask(normalized)?.type, 'plan_replay');
    assert.deepEqual(workflowPlanReplayTask(normalized)?.plan_replay, originalReplay.plan_replay);

    const saved = workflowForSave({ ...normalized, name: ' Updated replay ' }, normalized, { type: 'personal' });
    assert.equal(workflowPlanReplayTask(saved)?.type, 'plan_replay');
    assert.deepEqual(workflowPlanReplayTask(saved)?.plan_replay, originalReplay.plan_replay);
    assert.equal(saved.name, 'Updated replay');

    const replayErrors = workflowValidationErrors(normalized, options(), normalized);
    assert.ok(!replayErrors.some((error) => error.includes('default model')), replayErrors.join('\n'));
    assert.ok(!replayErrors.some((error) => error.includes('needs instructions')), replayErrors.join('\n'));

    const unnamed = normalizeWorkflowDefinition(workflow(originalReplay, { name: '' }));
    assert.ok(workflowValidationErrors(unnamed, options(), unnamed).includes('Workflow name is required.'));
});

test('run-time zone mirrors the server: schedule zone, then frozen zone, then UTC', () => {
    assert.equal(planReplayRunTimeZone({ kind: 'calendar', timezone: ' Europe/Paris ' }, 'America/Chicago'), 'Europe/Paris');
    assert.equal(planReplayRunTimeZone({ unit: 'hours', value: 24 }, ' America/Chicago '), 'America/Chicago');
    assert.equal(planReplayRunTimeZone(null, ''), 'UTC');
    assert.equal(planReplayRunTimeZone({ timezone: 42 }, ''), 'UTC');
    assert.match(describePlanReplayTimeHandling(planReplayRunTimeZone(null, '')), /stay as written.*in UTC\./);
});
