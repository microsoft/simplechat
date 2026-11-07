// OrchestrationWorkflowHandoffNotice.tsx
// Why a plan that hands work off to a one-time workflow waits for the user, and what approving it does.
//
// A request too big for one plan can make the plan prepare a one-time workflow instead of doing
// the work itself. The server saves every such plan as manual approval whatever mode was asked
// for (the registry's approval floor), and approving it only prepares the workflow: nothing is
// created or run until the user accepts it on the hand-off card under the answer. This notice
// says both on the approval card, where a user who chose Timed or Auto would otherwise wonder why
// the plan is waiting, or think that approving it starts the work.

import { Workflow } from 'lucide-react';
import type { OrchestrationPlan } from '../../lib/orchestration';
import { WORKFLOW_HANDOFF_CAPABILITY } from '../../lib/workflowHandoffs';

export function OrchestrationWorkflowHandoffNotice({ plan }: { plan: OrchestrationPlan }) {
    if (!plan.steps.some((step) => step.enabled && step.capability_id === WORKFLOW_HANDOFF_CAPABILITY)) {
        return null;
    }
    return (
        <div
            role="note"
            aria-label="Workflow hand-off in this plan"
            data-testid="orchestration-workflow-handoff-notice"
            className="mt-2 flex items-start gap-2 rounded-xl border border-edge bg-surface-1 px-2.5 py-2 text-xs text-text-2"
        >
            <Workflow size={14} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
            <div className="min-w-0 space-y-1">
                <p className="font-medium text-text-1">
                    This plan hands work off to a one-time workflow, so it always waits for your approval.
                </p>
                <p>
                    Approving this plan prepares a one-time workflow. Nothing runs until you accept it on the
                    hand-off card that appears under the answer.
                </p>
            </div>
        </div>
    );
}
