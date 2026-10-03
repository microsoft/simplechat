// workflowRunActions.ts
// Cancel and Retry for one run a chat started, and the plain sentence each outcome reads as.
//
// Every run a chat starts is a personal, durable run. Retry is that runtime's resume: it keeps the
// run id, so the run's results still come back to the chat. It is never `/resume-failed`, which
// refuses durable runs and would otherwise start a run the chat never hears from. Retry reads the
// runtime first, for the version to resume from and to confirm the run can still be resumed, and
// sends a fresh request id each attempt. Cancel is the run-level cancel, never the workflow-level one.
//
// Only fixed codes are read from a refusal, so a server sentence is never shown. The caller
// re-reads the run's status after every outcome, whatever it was.

import { ApiError } from './apiClient';
import {
    cancelScopedWorkflowRun,
    fetchWorkflowRuntime,
    newWorkflowRequestId,
    resumeWorkflowRuntime,
    workflowRuntimeCanResume,
    type WorkflowScope,
} from './workflowEditor';
import {
    WORKFLOW_RETRY_BLOCKED_CODES,
    workflowRetryBlockedText,
    type WorkflowRetryBlockedCode,
} from './workflowRunStatus';

const PERSONAL_SCOPE: WorkflowScope = { type: 'personal' };

export interface WorkflowRunActionTarget {
    workflowId: string;
    runId: string;
}

export interface WorkflowRunActionOutcome {
    ok: boolean;
    text: string;
}

export const WORKFLOW_RETRY_REQUESTED_TEXT = 'Retry requested.';
export const WORKFLOW_CANCEL_REQUESTED_TEXT = 'Cancel requested.';

const RUN_GONE_TEXT = 'This run is no longer available.';
const NO_ACCESS_TEXT = 'You don\'t have access to this run.';
const WORKFLOWS_UNAVAILABLE_TEXT = 'Workflows aren\'t available right now. Try again later.';
const RETRY_REJECTED_TEXT = 'The retry request wasn\'t accepted.';
export const WORKFLOW_RETRY_FAILED_TEXT = 'Couldn\'t retry the run. Try again.';
const RETRY_UNCONFIRMED_TEXT = 'Couldn\'t confirm the retry. Check its status.';
const RETRY_NOT_RESUMABLE_TEXT = 'This run can\'t be retried anymore.';
const CANCEL_CONFLICT_TEXT = 'This run already finished or changed. Check its status.';
export const WORKFLOW_CANCEL_FAILED_TEXT = 'Couldn\'t cancel the run. Try again.';

// The refusals only a resume returns. The ones a status row can also carry read the same either way.
const RESUME_CONFLICT_TEXT = new Map<string, string>([
    ['workflow_deleting', 'The workflow is being deleted, so this run can\'t be retried.'],
    ['stale_version', 'The run changed since it was checked. Check its status and try again.'],
    ['invalid_state', 'This run can\'t be retried in its current state.'],
    ['request_conflict', 'Another request changed this run. Check its status and try again.'],
]);
const RESUME_CONFLICT_FALLBACK_TEXT = 'This run can\'t be retried right now. Check its status.';

function refusalCode(error: ApiError): string {
    const payload = error.payload;
    if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
        return '';
    }
    const code = (payload as Record<string, unknown>).code;
    return typeof code === 'string' ? code : '';
}

function resumeConflictText(code: string): string {
    if ((WORKFLOW_RETRY_BLOCKED_CODES as readonly string[]).includes(code)) {
        return workflowRetryBlockedText(code as WorkflowRetryBlockedCode);
    }
    return RESUME_CONFLICT_TEXT.get(code) ?? RESUME_CONFLICT_FALLBACK_TEXT;
}

// What a refused read or resume reads as, for the answers both can give.
function sharedRefusalText(status: number): string | null {
    if (status === 403) return NO_ACCESS_TEXT;
    if (status === 404) return RUN_GONE_TEXT;
    if (status === 503) return WORKFLOWS_UNAVAILABLE_TEXT;
    return null;
}

function resumeFailureText(error: unknown): string {
    if (error instanceof ApiError) {
        if (error.status === 409) return resumeConflictText(refusalCode(error));
        if (error.status === 400) return RETRY_REJECTED_TEXT;
        return sharedRefusalText(error.status) ?? WORKFLOW_RETRY_FAILED_TEXT;
    }
    // fetch rejects with a TypeError when no answer came back. Anything else failed after a success
    // status, while reading the answer, so the retry may well have gone through.
    return error instanceof TypeError ? WORKFLOW_RETRY_FAILED_TEXT : RETRY_UNCONFIRMED_TEXT;
}

/**
 * Resume a failed run where it stopped. The runtime is read fresh for the version to resume from;
 * a run that can no longer be resumed, or a read that fails, sends nothing.
 */
export async function retryWorkflowRun(target: WorkflowRunActionTarget): Promise<WorkflowRunActionOutcome> {
    let expectedVersion: number;
    try {
        const { runtime } = await fetchWorkflowRuntime(PERSONAL_SCOPE, target.workflowId, target.runId);
        if (!workflowRuntimeCanResume(runtime)) {
            return { ok: false, text: RETRY_NOT_RESUMABLE_TEXT };
        }
        if (!Number.isSafeInteger(runtime.version) || runtime.version < 0) {
            return { ok: false, text: WORKFLOW_RETRY_FAILED_TEXT };
        }
        expectedVersion = runtime.version;
    } catch (error) {
        return {
            ok: false,
            text: (error instanceof ApiError ? sharedRefusalText(error.status) : null) ?? WORKFLOW_RETRY_FAILED_TEXT,
        };
    }
    let requestId: string;
    try {
        requestId = newWorkflowRequestId();
    } catch {
        return { ok: false, text: WORKFLOW_RETRY_FAILED_TEXT };
    }
    try {
        await resumeWorkflowRuntime(PERSONAL_SCOPE, target.workflowId, target.runId, {
            expected_version: expectedVersion,
            request_id: requestId,
        });
        return { ok: true, text: WORKFLOW_RETRY_REQUESTED_TEXT };
    } catch (error) {
        return { ok: false, text: resumeFailureText(error) };
    }
}

/** Ask one run to stop. Whatever it already did stays done. */
export async function cancelWorkflowRun(target: WorkflowRunActionTarget): Promise<WorkflowRunActionOutcome> {
    try {
        await cancelScopedWorkflowRun(PERSONAL_SCOPE, target.workflowId, target.runId);
        return { ok: true, text: WORKFLOW_CANCEL_REQUESTED_TEXT };
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
            return { ok: false, text: RUN_GONE_TEXT };
        }
        if (error instanceof ApiError && error.status === 409) {
            return { ok: false, text: CANCEL_CONFLICT_TEXT };
        }
        return { ok: false, text: WORKFLOW_CANCEL_FAILED_TEXT };
    }
}
