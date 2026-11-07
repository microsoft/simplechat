// OrchestrationWorkflowRunNotice.tsx
// Why a plan that starts a saved workflow waits for the user, and which workflows it starts.
//
// Starting a saved workflow is work the user can't take back from the chat, so the server saves
// every such plan as manual approval whatever mode was asked for (`normalize_plan`'s approval
// floor). This notice says so on the approval card, where a user who chose Timed or Auto would
// otherwise wonder why the plan is waiting, and names each workflow before they select Run.
// Names and trigger summaries are the user's own text, so they render as text, never markup.

import { Workflow } from 'lucide-react';
import type { OrchestrationPlan } from '../../lib/orchestration';
import { planWorkflowRuns } from '../../lib/orchestrationPlan';

export function OrchestrationWorkflowRunNotice({ plan }: { plan: OrchestrationPlan }) {
    const { count, workflows } = planWorkflowRuns(plan);
    if (!count) {
        return null;
    }
    const anyPaused = workflows.some((workflow) => workflow.paused);
    return (
        <div
            role="note"
            aria-label="Saved workflows in this plan"
            data-testid="orchestration-workflow-run-notice"
            className="mt-2 flex items-start gap-2 rounded-xl border border-edge bg-surface-1 px-2.5 py-2 text-xs text-text-2"
        >
            <Workflow size={14} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
            <div className="min-w-0 space-y-1">
                <p className="font-medium text-text-1">
                    {count === 1
                        ? 'This plan starts a saved workflow, so it always waits for you to run it.'
                        : 'This plan starts saved workflows, so it always waits for you to run it.'}
                </p>
                {workflows.length ? (
                    <ul className="space-y-0.5" aria-label="Workflows this plan starts">
                        {workflows.map((workflow) => (
                            <li key={workflow.handle} className="break-words" data-testid="orchestration-workflow-run-item">
                                <span className="font-medium text-text-1">{workflow.name}</span>
                                {workflow.trigger_summary ? <span>{` · ${workflow.trigger_summary}`}</span> : null}
                                {workflow.paused ? (
                                    <span className="ml-1.5 rounded-full bg-warn-soft px-1.5 py-0.5 font-medium text-warn">
                                        Paused
                                    </span>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                ) : null}
                {anyPaused ? (
                    <p>A paused workflow still runs once when you start it here. Starting it doesn't turn it back on.</p>
                ) : null}
            </div>
        </div>
    );
}
