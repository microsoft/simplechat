// OrchestrationDeliverables.tsx
// "You asked for": what a plan will deliver, and whether each part can be delivered.
//
// The planner lists the answer, files, images, charts and diagrams the user asked for, and the
// server checks each one against what it can actually produce. This section shows that list
// before the steps: which step produces each deliverable, and, for one that cannot be produced
// here, the server's reason in a warning tone. During and after a run the same rows follow their
// steps, so a file or image that did not arrive is never shown as delivered.
//
// Every value is rendered as React text. Descriptions and titles are model-authored plan data.

import { clsx } from 'clsx';
import { Ban, CheckCircle2, CircleAlert, Loader2, TriangleAlert, XCircle } from 'lucide-react';
import type { OrchestrationPlan, PlanEdits, StepStatus } from '../../lib/orchestration';
import { deliverableRows, type DeliverableRow, type DeliverableState } from '../../lib/orchestrationPlan';

const STATE_TONE: Record<DeliverableState, string> = {
    planned: 'text-text-3',
    running: 'text-accent',
    delivered: 'text-ok',
    unavailable: 'text-warn',
    not_delivered: 'text-danger',
    turned_off: 'text-warn',
};

function StateIcon({ state }: { state: DeliverableState }) {
    const className = clsx('mt-0.5 shrink-0', STATE_TONE[state]);
    switch (state) {
        case 'delivered':
            return <CheckCircle2 size={13} className={className} aria-hidden="true" />;
        case 'running':
            return <Loader2 size={13} className={clsx(className, 'animate-spin')} aria-hidden="true" />;
        case 'unavailable':
            return <TriangleAlert size={13} className={className} aria-hidden="true" />;
        case 'not_delivered':
            return <XCircle size={13} className={className} aria-hidden="true" />;
        case 'turned_off':
            return <Ban size={13} className={className} aria-hidden="true" />;
        default:
            return <CircleAlert size={13} className={clsx(className, 'opacity-60')} aria-hidden="true" />;
    }
}

function DeliverableItem({ row, compact }: { row: DeliverableRow; compact: boolean }) {
    const warning = row.state === 'unavailable' || row.state === 'turned_off';
    return (
        <li
            data-deliverable-id={row.deliverable.id}
            data-deliverable-state={row.state}
            className={clsx(
                'flex items-start gap-1.5 rounded-lg px-2 py-1 text-xs',
                warning && 'bg-warn-soft',
                row.state === 'not_delivered' && 'bg-danger-soft',
            )}
        >
            <StateIcon state={row.state} />
            <div className="min-w-0 flex-1 break-words">
                <p className="text-text-1">
                    <span className="font-medium">{row.label}</span>
                    <span className="text-text-2">{' — '}{row.deliverable.description}</span>
                </p>
                <p className={clsx('mt-0.5', STATE_TONE[row.state])}>
                    {row.stateLabel}
                    {row.reason ? `: ${row.reason}` : ''}
                    {!compact && row.steps.length > 0 && row.state !== 'unavailable'
                        ? ` · ${row.steps.length === 1 ? 'Step' : 'Steps'}: ${row.steps.join('; ')}`
                        : ''}
                </p>
            </div>
        </li>
    );
}

export function OrchestrationDeliverables({
    plan,
    statusOf,
    edits,
    compact = false,
}: {
    plan: OrchestrationPlan;
    /** A step's live status, when the run view knows it. */
    statusOf?: (stepId: string) => StepStatus | undefined;
    edits?: PlanEdits;
    /** The approval card lists only what the user asked for, without step names. */
    compact?: boolean;
}) {
    if (plan.planner_contract_version !== 2) return null;
    const rows = deliverableRows(plan, statusOf ?? (() => undefined), edits);
    const asked = rows.filter((row) => row.deliverable.requested === 'explicit');
    const added = compact ? [] : rows.filter((row) => row.deliverable.requested !== 'explicit');
    if (!asked.length && !added.length) return null;
    return (
        <section aria-label="What this plan delivers" className="space-y-1.5" data-testid="orchestration-deliverables">
            {asked.length > 0 ? (
                <div>
                    <h3 className="px-0.5 text-[11px] font-semibold uppercase tracking-wide text-text-3">
                        You asked for
                    </h3>
                    <ul className="mt-1 space-y-1">
                        {asked.map((row) => <DeliverableItem key={row.deliverable.id} row={row} compact={compact} />)}
                    </ul>
                </div>
            ) : null}
            {added.length > 0 ? (
                <div>
                    <h3 className="px-0.5 text-[11px] font-semibold uppercase tracking-wide text-text-3">
                        Also included
                    </h3>
                    <ul className="mt-1 space-y-1">
                        {added.map((row) => <DeliverableItem key={row.deliverable.id} row={row} compact={compact} />)}
                    </ul>
                </div>
            ) : null}
        </section>
    );
}
