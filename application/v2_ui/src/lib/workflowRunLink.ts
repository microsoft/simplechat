// workflowRunLink.ts
// The workflow, and optionally the run, that a workflows-section URL names.
//
// `?workflow_id=<id>` has always opened that workflow. Adding `&run_id=<id>` opens the
// workflow's run history instead, with that run expanded. Document provenance links use the
// run form; the server builds them (functions_document_provenance.workflow_origin_href). The
// links to runs a chat plan started use it too, built by `workflowRunHref`, and so do the
// notices and alerts that name a run (notificationLinks.ts v2WorkflowRunPath). This module is
// the one place the client builds or reads them.
//
// The run link is this query form on the workspace's Workflows section. There is no separate
// `/runs/:runId` route: the section opens the run inspector from the query in both personal
// and group workspaces (WorkflowsSection.tsx).

import type { WorkflowScope } from './workflowEditor';
import { groupWorkspacePath } from './groupWorkspaceNavigation';

export const WORKFLOW_LINK_PARAM = 'workflow_id';
export const WORKFLOW_RUN_LINK_PARAM = 'run_id';

const PERSONAL_SCOPE: WorkflowScope = { type: 'personal' };

export interface WorkflowRunLink {
    workflowId: string;
    /** Null when the link names only the workflow. */
    runId: string | null;
}

/**
 * The V2 Workflows page with one workflow's run history open and the run `runId` expanded.
 *
 * Personal by default, which is where every run a chat plan starts lives. A group run opens
 * that group's Workflows section; the group id is checked there, and one a path segment cannot
 * carry throws rather than building a different path.
 */
export function workflowRunHref(workflowId: string, runId: string, scope: WorkflowScope = PERSONAL_SCOPE): string {
    const params = new URLSearchParams({ [WORKFLOW_LINK_PARAM]: workflowId, [WORKFLOW_RUN_LINK_PARAM]: runId });
    if (scope.type === 'group') {
        return `${groupWorkspacePath(scope.groupId, 'workflows')}?${params}`;
    }
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
