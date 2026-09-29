// workflowRunLink.ts
// The workflow, and optionally the run, that a workflows-section URL names.
//
// `?workflow_id=<id>` has always opened that workflow. Adding `&run_id=<id>` opens the
// workflow's run history instead, with that run expanded. Document provenance links use the
// run form; the server builds them (functions_document_provenance.workflow_origin_href) and
// this module is the one place the client reads them.

export const WORKFLOW_LINK_PARAM = 'workflow_id';
export const WORKFLOW_RUN_LINK_PARAM = 'run_id';

export interface WorkflowRunLink {
    workflowId: string;
    /** Null when the link names only the workflow. */
    runId: string | null;
}

/** The workflow and run a query string names, or null when it names no workflow. */
export function readWorkflowRunLink(search: string | URLSearchParams): WorkflowRunLink | null {
    const params = typeof search === 'string' ? new URLSearchParams(search) : search;
    const workflowId = (params.get(WORKFLOW_LINK_PARAM) ?? '').trim();
    if (!workflowId) {
        return null;
    }
    const runId = (params.get(WORKFLOW_RUN_LINK_PARAM) ?? '').trim();
    return { workflowId, runId: runId || null };
}
