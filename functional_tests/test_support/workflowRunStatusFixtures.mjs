// workflowRunStatusFixtures.mjs
// Version: 0.261.230
// Implemented in: 0.261.230
// Builds rows and responses in the exact shape of 6b-1's chat-started workflow run status route
// (GET /api/v2/orchestration/workflow-runs/status, functions_workflow_chat_delivery_status.py),
// for the V2 workflow run tests. Every key the route writes is present, so a test that drops or
// changes one is testing exactly that change.

const BASE_TIME = Date.parse('2026-01-05T09:00:00Z');

/** A seconds-precision UTC time, as the route writes it, `seconds` after the fixtures' base time. */
export function at(seconds) {
    return new Date(BASE_TIME + seconds * 1000).toISOString().replace('.000Z', 'Z');
}

/** A delivered message id with the prefix the route requires. */
export function deliveryMessageId(runId, generation) {
    return `assistant_workflow_delivery_${runId}_g${generation}`;
}

/** A running row in chat-1, started by orchestration run orun-1, with every field set. */
export function statusRow(runId, overrides = {}) {
    const { delivery = {}, actions = {}, ...rest } = overrides;
    return {
        workflow_id: `wf-${runId}`,
        workflow_scope: 'personal',
        run_id: runId,
        conversation_id: 'chat-1',
        orchestration_run_id: 'orun-1',
        step_id: `step-${runId}`,
        workflow_name: 'Weekly digest',
        status: 'running',
        phase: 'running',
        runtime_version: 3,
        step_index: 1,
        step_count: 4,
        step_label: null,
        waiting: null,
        live: true,
        requested_at: at(0),
        started_at: at(5),
        completed_at: null,
        elapsed_seconds: 95,
        delivery: {
            status: 'pending',
            generation: null,
            message_id: null,
            delivered_at: null,
            reason: null,
            ...delivery,
        },
        error: null,
        error_code: null,
        retry_blocked: null,
        actions: { cancel: true, retry: false, approve: false, open_run: true, ...actions },
        ...rest,
    };
}

/** A completed run whose result was posted to its chat under `generation` at `deliveredAt`. */
export function deliveredRow(runId, generation, deliveredAt, overrides = {}) {
    const { delivery = {}, actions = {}, ...rest } = overrides;
    return statusRow(runId, {
        status: 'completed',
        phase: 'finished',
        step_index: 4,
        completed_at: deliveredAt,
        ...rest,
        delivery: {
            status: 'delivered',
            generation,
            message_id: deliveryMessageId(runId, generation),
            delivered_at: deliveredAt,
            reason: null,
            ...delivery,
        },
        actions: { cancel: false, ...actions },
    });
}

/** A failed run with the route's default failure sentence and code. */
export function failedRow(runId, overrides = {}) {
    const { delivery = {}, actions = {}, ...rest } = overrides;
    return statusRow(runId, {
        status: 'failed',
        phase: 'failed',
        completed_at: at(200),
        error: 'The run stopped before it finished.',
        error_code: 'failed',
        ...rest,
        delivery,
        actions: { cancel: false, ...actions },
    });
}

/** A whole response; `checked_at` defaults to 300 s after the base time. */
export function statusResponse(runs, overrides = {}) {
    return { available: true, runs, checked_at: at(300), truncated: false, ...overrides };
}
