// workflowRunLink.ts
// The workflow, and optionally the run, that a workflows-section URL names.
//
// `?workflow_id=<id>` has always opened that workflow. Adding `&run_id=<id>` opens the
// workflow's run history instead, with that run expanded. Document provenance links use the
// run form; the server builds them (functions_document_provenance.workflow_origin_href). The
// links to runs a chat plan started use it too, built by `workflowRunHref`. This module is the
// one place the client builds or reads them.

export const WORKFLOW_LINK_PARAM = 'workflow_id';
export const WORKFLOW_RUN_LINK_PARAM = 'run_id';

export interface WorkflowRunLink {
    workflowId: string;
    /** Null when the link names only the workflow. */
    runId: string | null;
}

/** The V2 Workflows page with one workflow's run history open and the run `runId` expanded. */
export function workflowRunHref(workflowId: string, runId: string): string {
    const params = new URLSearchParams({ [WORKFLOW_LINK_PARAM]: workflowId, [WORKFLOW_RUN_LINK_PARAM]: runId });
    return `/workspace/workflows?${params}`;
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
