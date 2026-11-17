// WorkflowActivityLinks.tsx
// The places V2 sends a person to the Workflow Activity page from: the chat header of a workflow's
// conversation, each run in a workflow's run history, and the workflow's own header.
//
// These are the places the classic interface offers workflow activity (chats.html's
// `workflow-activity-btn`, `workspace_workflows.js`' run history rows and Activity button), and like
// classic's they open the page in a new tab: it is a view to keep beside the chat or the workflow
// list while a run is going, and leaving either would drop a draft that is still being typed (the
// same reason Conversation references open in a new tab). They are real links to the page's route
// rather than buttons that call `window.open`, so copying the address and following it with the
// keyboard work, and a blocked pop-up cannot swallow the click. Each link says nothing when the
// record it was given does not name a run, a workflow or a conversation a link can carry.

import { clsx } from 'clsx';
import { Activity } from 'lucide-react';
import { Link } from 'react-router-dom';
import { workflowActivityHref, workflowConversationActivityHref } from '../../lib/workflowActivity';
import { formatActivityDateTime } from '../../lib/workflowActivitySnapshot';
import { workflowIsRunning } from '../../lib/workflowWorkbench';
import type { BadgeSource } from '../../lib/conversationBadges';
import type { WorkflowDefinition, WorkflowRunSummary, WorkflowScope } from '../../lib/workflowEditor';
import { useFeature } from '../../stores/bootstrapStore';

/** The look of a link that is drawn as a button, matching `GlassButton`'s subtle variant. */
export const ACTIVITY_LINK_BUTTON_CLASS = clsx(
    'inline-flex items-center gap-1.5 rounded-xl font-medium transition-colors glass-flat text-text-1',
    'hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
);

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * Workflow activity for the conversation open in chat, in the chat header's row of icons.
 *
 * Offered for a conversation a workflow made, while workflows are on for the reader, as classic
 * offers it. `sources` are the conversation's metadata and its row in the list, either of which
 * can be missing while the conversation loads.
 */
export function WorkflowActivityHeaderLink({
    conversationId,
    sources,
}: {
    conversationId: string | null;
    sources: ReadonlyArray<BadgeSource | null | undefined>;
}) {
    const personalWorkflowsEnabled = useFeature('allow_user_workflows');
    const groupWorkspacesEnabled = useFeature('enable_group_workspaces');
    const href = workflowConversationActivityHref({
        conversationId,
        sources,
        personalWorkflowsEnabled,
        groupWorkspacesEnabled,
    });
    if (!href) {
        return null;
    }
    return (
        <Link
            to={href}
            target="_blank"
            rel="noopener noreferrer"
            title="Open workflow activity in a new tab"
            aria-label="Open workflow activity (opens in a new tab)"
            data-testid="v2-chat-workflow-activity"
            className="rounded-lg p-2 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 max-md:flex max-md:min-h-11 max-md:min-w-11 max-md:items-center max-md:justify-center"
        >
            <Activity size={17} aria-hidden="true" />
        </Link>
    );
}

/** Open activity, on one run in a workflow's run history. */
export function WorkflowRunActivityLink({
    scope,
    workflowId,
    run,
}: {
    scope: WorkflowScope;
    workflowId: string;
    run: WorkflowRunSummary;
}) {
    const href = workflowActivityHref({
        scope,
        workflowId,
        runId: text(run.id) || text(run.run_id),
        conversationId: run.conversation_id,
    });
    if (!href) {
        return null;
    }
    const started = text(run.started_at);
    return (
        <Link
            to={href}
            target="_blank"
            rel="noopener noreferrer"
            title="Open this run's activity in a new tab"
            aria-label={
                started
                    ? `Open activity for the run of ${formatActivityDateTime(started)} (opens in a new tab)`
                    : 'Open activity for this run (opens in a new tab)'
            }
            data-testid="v2-workflow-run-activity-link"
            className={clsx(ACTIVITY_LINK_BUTTON_CLASS, 'h-7 shrink-0 px-2 text-xs')}
        >
            <Activity size={13} aria-hidden="true" />
            Open activity
        </Link>
    );
}

/**
 * Open the latest run's activity, in a workflow's own header.
 *
 * Offered once the workflow has a conversation and a run to show: one under way, or one on record.
 */
export function WorkflowActivityLink({ scope, workflow }: { scope: WorkflowScope; workflow: WorkflowDefinition }) {
    const workflowId = text(workflow.id);
    const conversationId = text(workflow.conversation_id);
    const ran = Boolean(text(workflow.last_run_status) || text(workflow.last_run_at));
    if (!workflowId || !conversationId || !(workflowIsRunning(workflow) || ran)) {
        return null;
    }
    const href = workflowActivityHref({ scope, workflowId, conversationId });
    if (!href) {
        return null;
    }
    return (
        <Link
            to={href}
            target="_blank"
            rel="noopener noreferrer"
            title="Open this workflow's activity in a new tab"
            aria-label={`Open activity for ${text(workflow.name) || 'workflow'} (opens in a new tab)`}
            data-testid="v2-workflow-activity-link"
            className={clsx(ACTIVITY_LINK_BUTTON_CLASS, 'h-8 px-3 text-sm')}
        >
            <Activity size={14} aria-hidden="true" />
            Activity
        </Link>
    );
}
