// WorkflowAlertSummary.tsx
// Read-only summary of a workflow's stored alerts, for viewers who cannot manage the workflow.

import { useId } from 'react';
import {
    workflowAlertSummary,
    type WorkflowAlertMode,
    type WorkflowAlertPriority,
} from '../../lib/workflowAlerts';
import type { WorkflowDefinition } from '../../lib/workflowEditor';

// The alert editor's own option labels, so both views describe a setting the same way.
const MODE_LABELS: Record<WorkflowAlertMode, string> = {
    off: 'Never notify me',
    rules: 'Only when a condition is met',
    every_run: 'On every run',
};
const PRIORITY_LABELS: Record<WorkflowAlertPriority, string> = {
    none: 'No notification',
    low: 'Low priority',
    medium: 'Medium priority',
    high: 'High priority',
};

export function WorkflowAlertSummary({ workflow }: { workflow: WorkflowDefinition }) {
    const titleId = useId();
    const summary = workflowAlertSummary(workflow);
    return (
        <section aria-labelledby={titleId} className="space-y-3 rounded-2xl border border-edge p-4">
            <h3 id={titleId} className="text-base font-semibold text-text-1">Alerts</h3>
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
                <div>
                    <dt className="text-xs text-text-3">When to alert</dt>
                    <dd className="text-text-1">{MODE_LABELS[summary.mode]}</dd>
                </div>
                <div>
                    <dt className="text-xs text-text-3">Pop-up priority</dt>
                    <dd className="text-text-1">{PRIORITY_LABELS[summary.priority]}</dd>
                </div>
                <div>
                    <dt className="text-xs text-text-3">Alert rules</dt>
                    <dd className="text-text-1">{summary.ruleCount === 1 ? '1 rule' : `${summary.ruleCount} rules`}</dd>
                </div>
            </dl>
        </section>
    );
}
