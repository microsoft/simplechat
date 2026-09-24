// WorkflowAlertSummary.tsx
// Read-only summary of a group workflow's stored alerts, with the classic editor where it can open them.

import { useId } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import {
    workflowAlertSummary,
    workflowAlertsEditableInClassic,
    type WorkflowAlertMode,
    type WorkflowAlertPriority,
    type WorkflowDefinition,
} from '../../lib/workflowEditor';

// The classic alert editor's own option labels, so both editors describe a setting the same way.
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

export function WorkflowAlertSummary({
    workflow,
    original,
    canEdit,
    onOpenClassic,
}: {
    workflow: WorkflowDefinition;
    original: WorkflowDefinition | null;
    canEdit: boolean;
    onOpenClassic?: () => void;
}) {
    const titleId = useId();
    const summary = workflowAlertSummary(workflow);
    const classic = workflowAlertsEditableInClassic(original);
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
            {classic ? (
                <>
                    <p className="max-w-prose text-xs text-text-3">
                        Alerts are edited in the classic group workspace. Saving this workflow here converts it to a V2
                        definition, and the classic editor can no longer open it, so edit alerts first.
                    </p>
                    {canEdit && onOpenClassic ? (
                        <GlassButton type="button" size="sm" onClick={onOpenClassic}>
                            Edit alerts in the classic workspace<ArrowUpRight size={14} />
                        </GlassButton>
                    ) : null}
                </>
            ) : (
                <p className="max-w-prose text-xs text-text-3">
                    {original
                        ? 'Alert settings are kept unchanged when you save. The classic editor cannot open workflows saved by V2, so these alerts cannot be changed until native alert editing is available.'
                        : 'Alerts cannot be added to workflows created in V2 until native alert editing is available.'}
                </p>
            )}
        </section>
    );
}
