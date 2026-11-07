// WorkflowRepeatProgress.tsx
// Lifetime identity and automatic-batch counters are intentionally separate.

import type { WorkflowRepeatProgress as RepeatProgress } from '../../lib/workflowEditor';

export function WorkflowRepeatProgress({ summary, label = 'Repeat progress' }: {
    summary?: RepeatProgress;
    label?: string;
}) {
    if (!summary) return null;
    return <section aria-label={label} className="min-w-0 space-y-1 rounded-lg border border-edge p-3 text-xs text-text-3">
        <p className="break-words font-medium text-text-2">Repeat {summary.node_id}</p>
        <p className="break-all">Repeat execution: {summary.execution_id}</p>
        <p>Lifetime completed rounds: {summary.completed_count}.
            {summary.completed_iteration >= 0 ? ` Last completed round: ${summary.completed_iteration + 1}.` : ' No round has completed yet.'}</p>
        <p>Automatic batch {summary.batch_number + 1}: {summary.batch_usage} of {summary.batch_size} rounds admitted.</p>
        {summary.state !== 'completed' && summary.state !== 'cancelled' ? <p>Next lifetime round: {summary.next_iteration + 1}.</p> : null}
        <p>Batch-limit pauses: {summary.exhaustion_count}. Manual continuations: {summary.continuation_count}.</p>
        <p>State: {summary.state.replaceAll('_', ' ')}. The batch size is frozen for this run; later administrator changes do not reset or shorten it.</p>
        {summary.partial ? <p className="rounded-lg bg-warn-soft p-2 text-warn">
            Accepted partial state. Coverage and limitations remain attached to subsequent rounds and final output.
        </p> : null}
    </section>;
}
