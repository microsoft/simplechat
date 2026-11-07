// WorkflowAlertSummary.tsx
// Read-only summary of a workflow's stored alerts, for viewers who cannot manage the workflow.

import { BellRing } from 'lucide-react';
import {
    workflowAlertSummary,
    WORKFLOW_ALERT_MODE_LABELS,
    WORKFLOW_ALERT_PRIORITY_LABELS,
} from '../../lib/workflowAlerts';
import type { WorkflowDefinition } from '../../lib/workflowEditor';
import { SectionCard } from '../ui/SectionCard';
import type { WorkflowCardFrame } from './WorkflowField';

/** One fact, label beside value on a wide card, the way Admin shows a readout. */
function SummaryRow({ term, children }: { term: string; children: string }) {
    return (
        <div className="admin-field admin-field-inline py-3" data-field-width="wide">
            <dt className="admin-field-heading text-sm font-semibold text-text-1">{term}</dt>
            <dd className="admin-field-control text-sm text-text-2">{children}</dd>
        </div>
    );
}

export function WorkflowAlertSummary({ workflow, card }: { workflow: WorkflowDefinition; card: WorkflowCardFrame }) {
    const summary = workflowAlertSummary(workflow);
    return (
        <SectionCard id={card.id} title="Alerts" icon={BellRing} status={card.status} meta={card.meta}
            headingLevel={card.headingLevel}>
            <dl className="divide-y divide-edge-strong">
                <SummaryRow term="When to alert">{WORKFLOW_ALERT_MODE_LABELS[summary.mode]}</SummaryRow>
                <SummaryRow term="Pop-up priority">{WORKFLOW_ALERT_PRIORITY_LABELS[summary.priority]}</SummaryRow>
                <SummaryRow term="Alert rules">{summary.ruleCount === 1 ? '1 rule' : `${summary.ruleCount} rules`}</SummaryRow>
                {summary.optionSummary.length ? (
                    <SummaryRow term="Pop-up options">{summary.optionSummary.join(' · ')}</SummaryRow>
                ) : null}
            </dl>
        </SectionCard>
    );
}
