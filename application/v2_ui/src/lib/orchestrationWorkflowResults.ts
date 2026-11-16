// orchestrationWorkflowResults.ts
// How the plan card names a step that reads a saved workflow's stored result.
//
// A workflow_results step names its workflow by a request-local handle and picks one run with a
// selector. The card shows the workflow's own name from the plan inputs and the selector in words.
// The handle means nothing to a reader, and the workflow's and the run's ids never reach the plan.

/** The orchestration capability that reads a saved workflow's stored result. */
export const WORKFLOW_RESULTS_CAPABILITY = 'workflow_results';

/** The step arguments the card shows in words rather than as raw values. */
export const WORKFLOW_RESULTS_ARGUMENT_KEYS: readonly string[] = ['workflow', 'selector', 'completed_on', 'status'];

// The status filters the server accepts (functions_orchestration_workflow_results).
const STATUS_WORDS: Record<string, string> = {
    completed: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
};

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const DEFAULT_NAME = 'Workflow details unavailable';
const UNKNOWN_SELECTION = 'Run details unavailable';

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The run a workflow_results step reads, in words, from its static arguments. The day is the
 * user's local day as the plan wrote it, so it is shown as written rather than re-parsed.
 */
export function workflowResultsSelection(args: unknown): string {
    if (!args || typeof args !== 'object' || Array.isArray(args)) {
        return UNKNOWN_SELECTION;
    }
    const record = args as Record<string, unknown>;
    const status = typeof record.status === 'string'
        && Object.prototype.hasOwnProperty.call(STATUS_WORDS, record.status)
        ? STATUS_WORDS[record.status]
        : '';
    if (record.status !== undefined && !status) {
        return UNKNOWN_SELECTION;
    }
    if (record.selector === 'latest') {
        return status ? `Latest ${status} run` : 'Latest run';
    }
    if (
        record.selector === 'completed_on'
        && typeof record.completed_on === 'string'
        && DAY_PATTERN.test(record.completed_on)
    ) {
        return `${status ? `${capitalize(status)} run` : 'Run'} finished on ${record.completed_on}`;
    }
    return UNKNOWN_SELECTION;
}

/** The name a step shows: the workflow's own name from the plan inputs, or a neutral label. */
export function workflowResultsDisplayName(workflow: { name: string } | undefined): string {
    return workflow?.name.trim() || DEFAULT_NAME;
}
