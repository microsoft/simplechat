// WorkflowFailureDetails.tsx
// Typed, text-only diagnostics shared by legacy tasks, gates and exact attempts.

import type { WorkflowFailureSummary } from '../../lib/workflowEditor';

export function WorkflowFailureDetails({ failure }: { failure: WorkflowFailureSummary }) {
    const details = [
        ['Code', failure.error_code],
        ['Phase', failure.failure_phase],
        ['Request stage', failure.request_stage],
        ['Missing capability', failure.missing_capability],
        ['Provider HTTP status', failure.provider_status],
        ['Provider error type', failure.provider_error_type],
        ['Protocol', failure.model_protocol],
        ['Request outcome', failure.request_outcome],
        ['Operation effects', failure.effect_certainty],
        ['Reference', failure.correlation_reference],
    ].filter(([, value]) => typeof value === 'string' || typeof value === 'number');
    if (typeof failure.error !== 'string' && !details.length) return null;
    return (
        <div aria-label="Failure details" className="space-y-1 rounded-xl bg-danger-soft p-3 text-xs text-text-2">
            {typeof failure.error === 'string' && failure.error ? <p>{failure.error}</p> : null}
            {details.map(([label, value]) => <p key={String(label)}><strong>{label}:</strong> {value}</p>)}
        </div>
    );
}
